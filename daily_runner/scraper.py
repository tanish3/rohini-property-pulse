"""Self-contained NGDRS e-Search scraper.

This is a complete, deterministic Playwright-based scraper for the Delhi
NGDRS citizen e-Search portal (ngdrs.delhi.gov.in). It is intentionally
written from scratch — it does NOT import anything from the ngdrs skill.

Pipeline (each step returns the page so the next step can take over):

  1. open_browser()         — Playwright persistent context
  2. login()                — username + password + captcha + OTP
  3. navigate_to_search()   — click the menu to reach the e-Search form
  4. fill_search_form()     — pick district, taluka, village, dates, attribute
  5. submit_search()        — click Search and wait for the results table
  6. extract_table()        — set page length to All, scrape every row
  7. write_csv()            — persist a date-stamped CSV

The captcha and OTP are obtained through a `CaptchaSolver` (see
captcha_solver.py). The default solver is file-based: it writes a marker
JSON with the screenshot path and waits for a value file to appear. The
screenshot is also written next to the marker so a human (or an
integrator) can read it.

All selectors and URLs are defined at the top so the rest of the code
stays declarative. To override anything, pass it to the relevant function
or set it in config.json.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

# Local imports — kept inside the same folder to keep the module
# self-contained.
from captcha_solver import CaptchaSolver

# Relative paths in config.json are resolved against this folder so a cron
# job works regardless of its working directory.
_HERE = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# Selectors / URLs / defaults                                                 #
# --------------------------------------------------------------------------- #

URLS = {
    "base":    "https://ngdrs.delhi.gov.in/",
    "login":   "https://ngdrs.delhi.gov.in/NGDRS_DL/Citizenentry/citizenlogin",
    "search":  "https://ngdrs.delhi.gov.in/NGDRS_DL/DLSroSearch/srosearch",
    "welcome": "https://ngdrs.delhi.gov.in/NGDRS_DL/Citizenentry/welcome",
}

# CSS / text selectors. Keep them in one place so a site change touches
# one file, not ten.
SEL = {
    # login form (IDs first — the portal dropped placeholder attributes)
    "username":   "#username, input[placeholder='Enter Username']",
    "password":   "#password, input[placeholder='Enter Password']",
    "captcha":    "#captcha, input[placeholder='Enter Captcha']",
    # Captcha image: pick the one INSIDE the same form as the captcha input,
    # AND closest to it. The old loose selector matched logos / banners.
    "captcha_img": "#captcha_image, form img[src*='captcha' i], form img[alt*='captcha' i], form img[id*='captcha' i]",
    "get_otp":    "#btnotp, button:has-text('Get OTP')",
    # Multiple candidates for the "Get OTP" button — the site has changed
    # its label over the years. We try them in order.
    "get_otp_candidates": [
        "#btnotp",
        "button:has-text('Get OTP')",
        "button:has-text('Send OTP')",
        "button:has-text('Generate OTP')",
        "button:has-text('Request OTP')",
        "a:has-text('Get OTP')",
        "a:has-text('Send OTP')",
        "input[value*='OTP' i][type='button']",
        "input[value*='OTP' i][type='submit']",
        "button[id*='otp' i]",
    ],
    "otp":        "#otp, input[placeholder='Enter OTP']",
    "login_btn":  "#btnSubmit, button:has-text('Login'):not(:has-text('Citizen'))",

    # navigation
    "toggle_nav":   "button[aria-label*='oggle' i], .navbar-toggle, button:has-text('Toggle navigation')",
    "esearch_link": "a[href*='TRSearch/searchindex'], a:has-text('E-Search')",
    "search_subitem": "a[href*='srosearch'], a:text-is('Search')",

    # search form
    "search_by":       "select[name*='Search' i]:not([name*='table' i])",
    "district":        "select[name*='district_id' i]",
    "date_from":       "#fromdate, input[placeholder='Search For Date']",
    "date_to":         "#todate, input[placeholder='To']",
    "taluka":          "select[name*='taluka_id' i]",
    "village":         "select[name*='village_id' i]",
    "attribute":       "select[name*='attribute_id' i]",
    "attribute_value": "input[placeholder='Plot']",
    "search_btn":      "#btnsearch2, button:has-text('Search')",

    # results
    "table":       "#tableparty",
    "page_length": "#tableparty_length, select[name$='_length'], .dataTables_length select",
}

DEFAULT_SEARCH = {
    "search_by": "Property Details",
    "district":  "North",
    "taluka":    "Alipur",
    "village":   "Rohini Sector-28",
    "attribute": "Plot Number",
}

TIMING_MS = {
    "page_load": 30_000,
    "short":     1_500,
    "long":      3_000,
}


# --------------------------------------------------------------------------- #
# Small DOM helpers                                                            #
# --------------------------------------------------------------------------- #


def _human_type(page, selector: str, text: str) -> None:
    """Type each character with a small delay so the site doesn't reject
    the input as a bot."""
    el = page.locator(selector).first
    el.wait_for(state="visible", timeout=TIMING_MS["page_load"])
    el.click()
    el.fill("")
    for ch in text:
        if ch == "-":
            page.keyboard.press("Minus")
        else:
            page.keyboard.type(ch)
        page.wait_for_timeout(60)
    page.wait_for_timeout(200)


def _select_by_text(page, selector: str, text: str) -> None:
    el = page.locator(selector).first
    el.wait_for(state="visible", timeout=TIMING_MS["page_load"])
    el.select_option(label=text)
    page.wait_for_timeout(300)


def _type_date(page, selector: str, dd_mm_yyyy: str) -> None:
    el = page.locator(selector).first
    el.wait_for(state="visible", timeout=TIMING_MS["page_load"])
    el.click()
    el.fill("")
    for ch in dd_mm_yyyy:
        if ch == "-":
            page.keyboard.press("Minus")
        else:
            page.keyboard.type(ch)
        page.wait_for_timeout(60)
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)


# --------------------------------------------------------------------------- #
# Browser lifecycle                                                           #
# --------------------------------------------------------------------------- #


# JavaScript injected before any page loads, to make the browser look like
# a real human Chrome (not Playwright automation). The NGDRS site checks
# these fingerprints and refreshes the captcha / rejects submissions when
# it detects automation.
STEALTH_INIT_SCRIPT = r"""
(function() {
  // 1. DELETE navigator.webdriver entirely (not set to false — real Chrome
  //    doesn't have this property at all, so accessing it returns undefined)
  try {
    delete Navigator.prototype.webdriver;
    delete window.navigator.__proto__.webdriver;
    // Belt and suspenders: also redefine to return undefined
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      get: () => undefined,
      set: () => {},
      configurable: true,
      enumerable: false,
    });
  } catch (e) {}

  // 2. Add the chrome runtime object (Playwright Chromium is missing it)
  try {
    window.chrome = {
      runtime: {
        PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
        PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64' },
        RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' },
        OnInstalledReason: { CHROME_UPDATE: 'chrome_update', ON_INSTALL: 'on_install', SHARED_MODULE_UPDATE: 'shared_module_update' },
        OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
        connect: function() {},
        sendMessage: function() {},
      },
      loadTimes: function() {
        return { requestTime: Date.now() / 1000, startLoadTime: Date.now() / 1000,
                 commitLoadTime: Date.now() / 1000, finishDocumentLoadTime: Date.now() / 1000,
                 finishLoadTime: Date.now() / 1000, firstPaintTime: 0,
                 firstPaintAfterLoadTime: 0, navigationType: 'Other',
                 wasFetchedViaSpdy: false, wasNpnNegotiated: false,
                 npnNegotiatedProtocol: 'unknown', wasAlternateProtocolAvailable: false,
                 connectionInfo: 'unknown' };
      },
      csi: function() { return { startE: Date.now(), onloadT: Date.now() }; },
      app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }, getDetails: function() {}, getIsInstalled: function() {}, installState: function() {}, isInstalled: false, runningState: function() {} },
    };
  } catch (e) {}

  // 3. Add fake plugins (Playwright Chromium returns an empty list)
  try {
    Object.defineProperty(Navigator.prototype, 'plugins', {
      get: () => {
        const list = [
          { name: 'Chrome PDF Plugin',  filename: 'internal-pdf-viewer',  description: 'Portable Document Format' },
          { name: 'Chrome PDF Viewer',  filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
          { name: 'Native Client',      filename: 'internal-nacl-plugin', description: '' },
        ];
        list.item = i => list[i] || null;
        list.namedItem = n => list.find(p => p.name === n) || null;
        list.refresh = () => {};
        return list;
      },
      configurable: true,
    });
  } catch (e) {}

  // 4. Realistic languages
  try {
    Object.defineProperty(Navigator.prototype, 'languages', {
      get: () => ['en-US', 'en'],
      configurable: true,
    });
  } catch (e) {}

  // 5. WebGL vendor/renderer (Playwright reports "SwiftShader" which is a giveaway)
  try {
    const proto = WebGLRenderingContext.prototype;
    const orig  = proto.getParameter;
    proto.getParameter = function(p) {
      if (p === 37445) return 'Intel Inc.';
      if (p === 37446) return 'Intel Iris OpenGL Engine';
      if (p === 0x1F00) return 'Google Inc. (Intel)';
      if (p === 0x1F01) return 'ANGLE (Intel, Intel(R) Iris(TM) Graphics 6100, OpenGL 4.1)';
      return orig.call(this, p);
    };
  } catch (e) {}

  // 6. Notification permission (real Chrome returns 'default' or 'denied')
  try {
    const orig = Notification.permission;
    Object.defineProperty(Notification, 'permission', {
      get: () => orig || 'default',
      configurable: true,
    });
  } catch (e) {}

  // 7. Permissions.query override
  try {
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {
      window.navigator.permissions.query = (params) =>
        params && params.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission, onchange: null })
          : origQuery.call(window.navigator.permissions, params);
    }
  } catch (e) {}

  // 8. Headless detection — Playwright's Chromium sets this in some versions
  try {
    Object.defineProperty(Navigator.prototype, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(window, 'outerWidth',  { get: () => window.innerWidth  });
    Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight });
  } catch (e) {}
})();
"""


@contextmanager
def open_browser(
    *,
    user_data_dir: Path,
    headless: bool = True,
    channel: str = "chrome",
    viewport: tuple[int, int] = (1440, 900),
    extra_args: Optional[list[str]] = None,
) -> Iterator[Any]:
    """Yield a persistent Playwright browser context with stealth patches.

    The site (ngdrs.delhi.gov.in) checks for automation fingerprints and
    behaves differently (refreshes captcha, rejects submissions) when it
    detects Playwright. We apply two layers of stealth:

      1. Chrome flags: --disable-blink-features=AutomationControlled
         (the main fix — removes navigator.webdriver)
      2. JS init script (STEALTH_INIT_SCRIPT) that adds the missing
         chrome runtime, plugins, languages, WebGL vendor, etc.
    """
    from playwright.sync_api import sync_playwright

    args = list(extra_args or [])
    if headless:
        args.extend(["--no-sandbox", "--disable-dev-shm-usage"])
    # Anti-detection: don't advertise that this is automation
    args.extend([
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process,AutomationControlled",
    ])
    user_data_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            channel=channel,
            headless=headless,
            viewport={"width": viewport[0], "height": viewport[1]},
            no_viewport=False,
            args=args or [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
            # Override the user agent so it doesn't say "HeadlessChrome"
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        # Inject the stealth script before any page's JavaScript runs
        ctx.add_init_script(STEALTH_INIT_SCRIPT)
        # Also apply the playwright-stealth plugin (does a more thorough
        # job of patching the dozens of fingerprints that bot detectors
        # look for — navigator.webdriver, chrome.runtime, permissions,
        # WebGL vendor, iframe contentWindow, etc.)
        try:
            from playwright_stealth import Stealth
            Stealth().apply_stealth_sync(ctx)
            sys.stderr.write("[daily-runner] playwright-stealth applied\n")
        except ImportError:
            sys.stderr.write(
                "[daily-runner] WARNING: playwright-stealth not installed — "
                "the site may detect automation. Run: "
                "pip install playwright-stealth\n"
            )
        except Exception as exc:
            sys.stderr.write(
                f"[daily-runner] WARNING: playwright-stealth failed: {exc!r}\n"
            )
        try:
            yield ctx
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def _active_page(ctx) -> Any:
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def _screenshot(page, name: str, screenshot_dir: Path) -> Path:
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    out = screenshot_dir / f"{name}.png"
    page.screenshot(path=str(out), full_page=True)
    return out


# --------------------------------------------------------------------------- #
# Login                                                                       #
# --------------------------------------------------------------------------- #


def _read_captcha_image(page, screenshot_dir: Path) -> Path:
    """Grab the captcha image; fall back to a clipped page screenshot.

    Strategy: find the captcha INPUT, then walk up to its enclosing
    form, then pick the image INSIDE that form. This avoids matching
    unrelated logos / banners that happen to have "captcha" in the src.
    """
    out = screenshot_dir / "captcha.png"

    # Best-effort: the form-local image (closest to the captcha input)
    try:
        local = page.evaluate(
            """() => {
              const input = document.querySelector("input[placeholder='Enter Captcha']");
              if (!input) return null;
              const form = input.closest('form') || document.body;
              const imgs = Array.from(form.querySelectorAll('img'));
              // pick the one whose bounding box is closest to the input
              const ir = input.getBoundingClientRect();
              let best = null, bestDist = Infinity;
              for (const img of imgs) {
                const r = img.getBoundingClientRect();
                if (r.width < 10 || r.height < 10) continue;     // skip tiny icons
                if (r.width > 400) continue;                     // skip banners
                const d = Math.abs(r.top - ir.top) + Math.abs(r.left - ir.left);
                if (d < bestDist) { bestDist = d; best = img; }
              }
              return best ? best.src : null;
            }"""
        )
        if local:
            sys.stderr.write(f"  captcha image src: {local}\n")
    except Exception as exc:
        sys.stderr.write(f"  (could not find captcha image via JS: {exc!r})\n")
        local = None

    # Fall back to the CSS selector
    img = page.locator(SEL["captcha_img"]).first
    if img.count() == 0:
        page.screenshot(
            path=str(out),
            full_page=False,
            clip={"x": 0, "y": 0, "width": 800, "height": 400},
        )
        sys.stderr.write("  (no captcha image found; saved top-of-page screenshot instead)\n")
    else:
        img.screenshot(path=str(out))
    return out


def _already_logged_in(page) -> bool:
    page.goto(URLS["welcome"], wait_until="domcontentloaded", timeout=TIMING_MS["page_load"])
    page.wait_for_timeout(TIMING_MS["short"])
    if page.locator("a:has-text('Logout'), a:has-text('Sign Out')").count() > 0:
        return True
    return (
        page.locator("button:has-text('Get OTP')").count() == 0
        and "welcome" in page.url
    )


def _install_dialog_handler(page) -> tuple[list[str], Any]:
    """Register a Playwright dialog handler that captures the message
    and accepts the dialog. Returns (messages_list, handler_ref) so the
    caller can read messages and uninstall later."""
    messages: list[str] = []

    def on_dialog(dialog: Any) -> None:
        msg = f"[{dialog.type}] {dialog.message}"
        messages.append(msg)
        sys.stderr.write(f"  [login] DIALOG FIRED: {msg}\n")
        try:
            dialog.accept()
        except Exception:
            try:
                dialog.dismiss()
            except Exception:
                pass

    page.on("dialog", on_dialog)
    return messages, on_dialog


def _fill_captcha(page, captcha_text: str) -> None:
    """Type the captcha into the field using human-style typing
    (click → fill empty → type each char with delay). This matches
    what the original ngdrs skill did, and it worked."""
    el = page.locator(SEL["captcha"]).first
    el.wait_for(state="visible", timeout=TIMING_MS["page_load"])
    el.click()                          # focus the field (just like a human)
    el.fill("")                         # clear any existing value
    for ch in captcha_text:
        page.keyboard.type(ch)
        page.wait_for_timeout(80)       # human-like typing speed
    page.wait_for_timeout(200)


def _js_click_button(page, *, text_contains: str) -> bool:
    """Click a button by dispatching a full mousedown/mouseup/click
    event sequence with real coordinates — the way a browser would
    when a human actually clicks. This is what the NGDRS site expects;
    a plain `b.click()` only fires the click event and gets flagged
    as automated (→ "Not Allowed Right Click" dialog).
    """
    try:
        clicked = page.evaluate(
            r"""(needle) => {
              const btns = Array.from(document.querySelectorAll(
                'button, input[type=button], input[type=submit], a, [role=button]'));
              for (const b of btns) {
                const t = (b.textContent || b.value || '').toLowerCase();
                if (b.offsetParent !== null && t.includes(needle.toLowerCase())) {
                  const rect = b.getBoundingClientRect();
                  const x = rect.left + rect.width  / 2;
                  const y = rect.top  + rect.height / 2;
                  const base = {
                    bubbles: true, cancelable: true, view: window,
                    button: 0, buttons: 1,
                    clientX: x, clientY: y,
                    screenX: x, screenY: y,
                  };
                  b.dispatchEvent(new MouseEvent('mouseover', base));
                  b.dispatchEvent(new MouseEvent('mousedown',  base));
                  b.dispatchEvent(new MouseEvent('mouseup',    base));
                  b.dispatchEvent(new MouseEvent('click',      base));
                  return true;
                }
              }
              return false;
            }""",
            text_contains,
        )
        return bool(clicked)
    except Exception as exc:
        sys.stderr.write(f"  js_click({text_contains!r}) failed: {exc!r}\n")
        return False


def _try_click_get_otp(page) -> Optional[str]:
    """Try every known "Get OTP" selector using a JS click (stealthier
    than Playwright's loc.click() which the site detects). Returns the
    selector that worked, or None if none exist."""
    for sel in SEL["get_otp_candidates"]:
        loc = page.locator(sel).first
        if loc.count() == 0:
            continue
        try:
            loc.wait_for(state="visible", timeout=2_000)
            if loc.get_attribute("disabled") is not None:
                sys.stderr.write(f"  get_otp candidate {sel!r}: present but disabled\n")
                continue
            # Use JS click to avoid the "Not Allowed Right Click" detection
            text = loc.text_content() or "Get OTP"
            if _js_click_button(page, text_contains=text.strip()):
                sys.stderr.write(f"  get_otp: JS-clicked {sel!r} (text={text.strip()!r})\n")
                return sel
        except Exception as exc:
            sys.stderr.write(f"  get_otp candidate {sel!r}: {exc!r}\n")
    return None


def _wait_for_button_text(page, *, contains: str, timeout_s: int = 10) -> bool:
    """Wait until at least one visible button on the page has text containing
    the given substring. Returns True if found."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            count = page.evaluate(
                """(needle) => Array.from(document.querySelectorAll('button'))
                  .filter(b => b.offsetParent !== null &&
                               (b.textContent || '').toLowerCase()
                                 .includes(needle.toLowerCase()))
                  .length""",
                contains,
            )
            if count and count > 0:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _button_text(page) -> Optional[str]:
    """Return the text of the first visible button on the page, or None."""
    try:
        return page.evaluate(
            """() => {
              const b = Array.from(document.querySelectorAll('button'))
                .find(b => b.offsetParent !== null);
              return b ? (b.textContent || '').trim() : null;
            }"""
        )
    except Exception:
        return None
    """Try every known "Get OTP" selector. Returns the one that worked,
    or None if none exist (the current site often has no Get OTP button —
    the captcha + OTP are submitted in one Login click)."""
    for sel in SEL["get_otp_candidates"]:
        loc = page.locator(sel).first
        if loc.count() == 0:
            continue
        try:
            # Wait for it to be visible AND enabled
            loc.wait_for(state="visible", timeout=2_000)
            # Is it disabled? Skip if so.
            if loc.get_attribute("disabled") is not None:
                sys.stderr.write(f"  get_otp candidate {sel!r}: present but disabled\n")
                continue
            loc.click()
            sys.stderr.write(f"  get_otp: clicked {sel!r}\n")
            return sel
        except Exception as exc:
            sys.stderr.write(f"  get_otp candidate {sel!r}: {exc!r}\n")
    return None


def _debug_dump_page(page, screenshot_dir: Path, name: str) -> None:
    """Save a screenshot + dump of all buttons/inputs for debugging."""
    _screenshot(page, name, screenshot_dir)
    try:
        info = page.evaluate(
            """() => {
              const items = (sel) => Array.from(document.querySelectorAll(sel))
                .slice(0, 30)
                .map(el => ({
                  tag: el.tagName.toLowerCase(),
                  id: el.id || null,
                  name: el.name || null,
                  type: el.type || null,
                  placeholder: el.placeholder || null,
                  value: (el.value || '').slice(0, 50),
                  text: (el.textContent || '').trim().slice(0, 50),
                  disabled: el.disabled || false,
                  visible: el.offsetParent !== null,
                }));
              return { url: location.href, buttons: items('button'),
                       inputs: items('input'), links: items('a[href]') };
            }"""
        )
        sys.stderr.write(
            f"  [debug] page dump @ {screenshot_dir / (name + '.png')}:\n"
            f"    url: {info['url']}\n"
        )
        for b in info["buttons"]:
            if not b["visible"]:
                continue
            sys.stderr.write(
                f"    <button> id={b['id']!r} type={b['type']!r} "
                f"text={b['text']!r} disabled={b['disabled']}\n"
            )
        for inp in info["inputs"]:
            if not inp["visible"]:
                continue
            sys.stderr.write(
                f"    <input>  id={inp['id']!r} name={inp['name']!r} "
                f"placeholder={inp['placeholder']!r} value={inp['value']!r} "
                f"type={inp['type']!r} disabled={inp['disabled']}\n"
            )
    except Exception as exc:
        sys.stderr.write(f"  [debug] dump failed: {exc!r}\n")


def login(
    page,
    *,
    username: str,
    password: str,
    solver: CaptchaSolver,
    screenshot_dir: Path,
    timeout_s: int = 300,
    run_id: Optional[str] = None,
    skip_get_otp: bool = False,
) -> Path:
    """Log in. Returns the path to the captcha image (also recorded).

    The NGDRS login flow on the current site:

      1. Fill username, password, captcha
      2. Click "Get OTP" → button text changes to "Login", OTP field
         becomes visible/active, OTP is sent to registered mobile
      3. Fill the OTP
      4. Click "Login" (the same button — text changed)
      5. Redirect to /welcome

    The captcha can be flaky (the server sometimes rejects a "correct"
    captcha because the image changed mid-submission). We capture any
    JavaScript dialog that fires and re-fill the captcha if it got
    cleared after the Get OTP click.
    """
    if _already_logged_in(page):
        sys.stderr.write("[daily-runner] session still valid, skipping login\n")
        return screenshot_dir / "captcha.png"

    # Install dialog handler — captures any alert/confirm the site throws
    # (e.g. "Invalid Captcha", "Authentication failed", "Not Allowed Right Click")
    dialog_messages, dialog_handler = _install_dialog_handler(page)

    # Up to 3 captcha attempts — the server sometimes rejects a "correct"
    # captcha because the image changed between when the user read it
    # and when the form was submitted.
    MAX_CAPTCHA_ATTEMPTS = 3

    try:
        captcha_text = ""  # remembered across attempts
        for attempt in range(1, MAX_CAPTCHA_ATTEMPTS + 1):
            sys.stderr.write(f"  [login] captcha attempt {attempt}/{MAX_CAPTCHA_ATTEMPTS}\n")
            dialog_messages.clear()  # reset between attempts

            page.goto(URLS["login"], wait_until="domcontentloaded", timeout=TIMING_MS["page_load"])
            page.wait_for_timeout(TIMING_MS["short"])

            _human_type(page, SEL["username"], username)
            page.wait_for_timeout(TIMING_MS["short"])
            _human_type(page, SEL["password"], password)
            page.wait_for_timeout(TIMING_MS["short"])

            # Re-read the captcha image fresh on every attempt
            captcha_png = _read_captcha_image(page, screenshot_dir)

            captcha_text = solver.solve_captcha(
                captcha_png,
                hint=f"captcha for NGDRS login (attempt {attempt}/{MAX_CAPTCHA_ATTEMPTS})",
                run_id=run_id,
            )
            # Strip whitespace — the captcha image often shows chars
            # spaced out (e.g. "4 B K F 8 K") but the value is "4BKF8K".
            captcha_text = captcha_text.replace(" ", "").replace("\t", "").strip()
            sys.stderr.write(f"  [login] captcha value to submit: {captcha_text!r}\n")

            # Fill the captcha IMMEDIATELY after the user types it, then
            # click Get OTP without any extra delays. This minimizes the
            # window in which the captcha can change.
            _fill_captcha(page, captcha_text)
            page.wait_for_timeout(200)  # tiny breath — but not too long

            if skip_get_otp:
                sys.stderr.write("  [login] skip_get_otp=true → skipping Get OTP click\n")
                break

            # ---- click "Get OTP" (using JS click to bypass bot detection) ---- #
            sys.stderr.write("  [login] clicking 'Get OTP'…\n")
            get_otp_clicked = _try_click_get_otp(page)
            if not get_otp_clicked:
                sys.stderr.write("  [login] no 'Get OTP' button found.\n")
                break  # fall through to the "no Get OTP" branch below

            # ---- wait for the OTP field to appear ---- #
            sys.stderr.write(
                "  [login] Get OTP clicked; waiting for OTP field to appear…\n"
            )
            otp_visible = False
            for waited in range(20):  # up to 20 * 0.5s = 10s
                try:
                    otp_loc = page.locator(SEL["otp"]).first
                    if otp_loc.count() > 0 and otp_loc.is_visible():
                        otp_visible = True
                        break
                except Exception:
                    pass
                page.wait_for_timeout(500)

            if otp_visible:
                sys.stderr.write(
                    "  [login] OTP field is visible → captcha was accepted\n"
                )
                # Re-fill the captcha in case the page reset the field
                cur = page.locator(SEL["captcha"]).first.input_value()
                if not cur.strip():
                    sys.stderr.write("  [login] captcha field was cleared; re-filling\n")
                    _fill_captcha(page, captcha_text)
                    page.wait_for_timeout(300)
                break  # success — exit the retry loop

            # OTP field didn't appear → captcha was probably rejected
            btn = _button_text(page)
            sys.stderr.write(
                f"  [login] OTP field never appeared (button is now {btn!r})\n"
            )
            if dialog_messages:
                # Filter out the "Not Allowed Right Click" noise
                real_errors = [m for m in dialog_messages if "Right Click" not in m]
                if real_errors:
                    sys.stderr.write(f"  [login] server said: {real_errors[-1]}\n")
                else:
                    sys.stderr.write(
                        f"  [login] only got anti-bot warnings: {dialog_messages}\n"
                    )
            if attempt < MAX_CAPTCHA_ATTEMPTS:
                sys.stderr.write(
                    "  [login] captcha was rejected; reloading and trying a "
                    "fresh captcha image…\n"
                )
                continue  # next attempt — re-reads the captcha
            else:
                # Out of attempts
                _debug_dump_page(page, screenshot_dir, "captcha_rejected_3x")
                if dialog_messages:
                    raise RuntimeError(
                        f"Captcha was rejected {MAX_CAPTCHA_ATTEMPTS} times. "
                        f"Last server message: {dialog_messages[-1]}. Check "
                        f"{screenshot_dir / 'captcha_rejected_3x.png'}."
                    )
                raise RuntimeError(
                    f"Captcha was rejected {MAX_CAPTCHA_ATTEMPTS} times. "
                    f"Check {screenshot_dir / 'captcha_rejected_3x.png'}."
                )

        # ---- at this point the OTP field should be visible/active ---- #
        page.wait_for_timeout(TIMING_MS["short"])

        # Ask the user for the OTP. If there's no "Get OTP" button on
        # this site, the OTP might not have been sent yet — prompt the
        # user to check their phone anyway (it usually arrives in <5s).
        otp = solver.get_otp(
            hint=(
                "OTP sent to your registered mobile. "
                "If you don't see 'OTP field appeared' above, the OTP "
                "may not have been sent — check your phone in case it "
                "arrived from a previous attempt."
            ),
            run_id=run_id,
        )
        if not otp:
            raise RuntimeError("no OTP provided")
        # Use fill() for OTP too — no need to simulate keystrokes
        otp_clean = otp.replace(" ", "").replace("\t", "").strip()
        page.locator(SEL["otp"]).first.fill(otp_clean)
        page.wait_for_timeout(TIMING_MS["short"])

        # ---- submit the login form ---- #
        # The portal's #btnSubmit is display:none and never revealed, so a
        # normal click would hang. Its own submit handler applies a salted
        # password hash (after_validation_check) before POSTing; replicate it
        # and submit the form natively.
        sys.stderr.write("  [login] submitting login form…\n")
        page.evaluate(
            """() => {
                const pwd = document.querySelector('#password');
                const salt = document.querySelector('#hfSaltedStr');
                if (pwd && salt && typeof hex_sha256 === 'function') {
                    pwd.value = hex_sha256(salt.value + hex_sha256(pwd.value));
                }
                document.getElementById('User').submit();
            }"""
        )

        # Wait for welcome page
        try:
            page.wait_for_url("**/welcome*", timeout=TIMING_MS["page_load"])
        except Exception:
            if "welcome" in page.url:
                pass
            else:
                _debug_dump_page(page, screenshot_dir, "login_failed")
                if dialog_messages:
                    raise RuntimeError(
                        f"Login failed. Server dialog said: {dialog_messages[-1]}. "
                        f"Check {screenshot_dir / 'login_failed.png'}."
                    )
                raise RuntimeError(
                    f"Login didn't redirect to /welcome (URL: {page.url}). "
                    f"The captcha or OTP is probably wrong. "
                    f"Check {screenshot_dir / 'login_failed.png'}."
                )
        sys.stderr.write(f"  [login] logged in (URL={page.url})\n")
        _screenshot(page, "after_login", screenshot_dir)
        return captcha_png
    finally:
        try:
            page.remove_listener("dialog", dialog_handler)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Navigation + search form                                                    #
# --------------------------------------------------------------------------- #


def navigate_to_search(page) -> None:
    """From the welcome screen, reach the e-Search form."""
    if "srosearch" in page.url:
        return
    esearch = page.locator(SEL["esearch_link"]).first
    if not (esearch.count() and esearch.is_visible()):
        toggle = page.locator(SEL["toggle_nav"]).first
        if toggle.count() > 0:
            toggle.click()
            page.wait_for_timeout(TIMING_MS["short"])
    page.locator(SEL["esearch_link"]).first.click()
    page.wait_for_timeout(TIMING_MS["short"])
    sub = page.locator(SEL["search_subitem"]).first
    if sub.count() > 0:
        sub.click()
        page.wait_for_timeout(TIMING_MS["short"])
    if "srosearch" not in page.url:
        page.goto(URLS["search"], wait_until="domcontentloaded", timeout=TIMING_MS["page_load"])
        page.wait_for_timeout(TIMING_MS["short"])


def _date_range(days_back: int) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=days_back)
    return start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y")


def fill_search_form(
    page,
    *,
    days_back: int = 1,
    search_by: str = DEFAULT_SEARCH["search_by"],
    district:  str = DEFAULT_SEARCH["district"],
    taluka:    str = DEFAULT_SEARCH["taluka"],
    village:   str = DEFAULT_SEARCH["village"],
    attribute: str = DEFAULT_SEARCH["attribute"],
    date_from: Optional[str] = None,
    date_to:   Optional[str] = None,
    screenshot_dir: Path,
) -> dict[str, str]:
    """Fill the e-Search form. Returns the resolved params."""
    if "srosearch" not in page.url:
        page.goto(URLS["search"], wait_until="domcontentloaded", timeout=TIMING_MS["page_load"])
        page.wait_for_timeout(TIMING_MS["short"])

    if not (date_from and date_to):
        date_from, date_to = _date_range(days_back)

    _select_by_text(page, SEL["search_by"], search_by)
    page.wait_for_timeout(TIMING_MS["short"])
    _select_by_text(page, SEL["district"], district)
    page.wait_for_timeout(TIMING_MS["short"])
    _type_date(page, SEL["date_from"], date_from)
    _type_date(page, SEL["date_to"], date_to)
    _select_by_text(page, SEL["taluka"], taluka)
    page.wait_for_timeout(TIMING_MS["short"])
    _select_by_text(page, SEL["village"], village)
    page.wait_for_timeout(TIMING_MS["short"])
    _select_by_text(page, SEL["attribute"], attribute)
    page.wait_for_timeout(TIMING_MS["short"])

    _screenshot(page, "form_filled", screenshot_dir)
    return {
        "search_by": search_by,
        "district":  district,
        "taluka":    taluka,
        "village":   village,
        "attribute": attribute,
        "date_from": date_from,
        "date_to":   date_to,
    }


def submit_search(page, *, screenshot_dir: Path) -> None:
    # The page contains more than one Search button (some hidden), so click
    # the first visible one whose label is exactly "Search".
    clicked = False
    candidates = page.locator(SEL["search_btn"])
    for i in range(candidates.count()):
        btn = candidates.nth(i)
        try:
            label = (btn.inner_text() or btn.get_attribute("value") or "").strip().lower()
        except Exception:
            label = ""
        if btn.is_visible() and label == "search":
            btn.click()
            clicked = True
            break
    if not clicked:
        raise RuntimeError("visible 'Search' submit button not found")
    page.wait_for_timeout(TIMING_MS["long"])
    page.locator(SEL["table"]).first.wait_for(
        state="visible", timeout=TIMING_MS["page_load"]
    )
    page.wait_for_timeout(TIMING_MS["short"])
    _screenshot(page, "search_results", screenshot_dir)


# --------------------------------------------------------------------------- #
# Extraction                                                                  #
# --------------------------------------------------------------------------- #

_PARTY_RE = re.compile(r"<b>([^<]+)</b>\s*\(([^)]+)\)\s*<br>\s*([^<]+)", re.IGNORECASE)
_DETAILS_RE = re.compile(r"Property ID:\s*(\d+)")
_DOC_ID_RE = re.compile(r"details\('([^']+)'\)")


def _select_all_rows(page) -> None:
    candidates = page.locator(SEL["page_length"])
    sel = None
    for i in range(candidates.count()):
        cand = candidates.nth(i)
        if cand.is_visible():
            sel = cand
            break
    if sel is not None:
        try:
            sel.select_option(value="-1")
        except Exception:
            sel.select_option(label="All")
        page.wait_for_timeout(TIMING_MS["long"])
        return

    # Newer builds paginate with a custom widget; DataTables keeps all rows
    # in the DOM, so asking its API for "all" is enough. If it isn't a
    # DataTable, scraping proceeds with whatever rows are present.
    page.evaluate(
        """() => {
            try {
                if (window.jQuery && jQuery.fn.dataTable &&
                    jQuery.fn.dataTable.isDataTable('#tableparty')) {
                    jQuery('#tableparty').DataTable().page.len(-1).draw(false);
                }
            } catch (e) {}
        }"""
    )
    page.wait_for_timeout(TIMING_MS["long"])


def _scrape_rows(page) -> list[dict[str, Any]]:
    """Pull the result table out as a list of normalized dicts.

    The site uses a nested DataTable layout — Property Details and Party
    cells contain sub-tables — so we evaluate a JS blob in the page that
    flattens each row's HTML, then parse it Python-side.
    """
    raw = page.evaluate(
        """() => {
          const table = document.querySelector('#tableparty');
          if (!table) return [];
          return Array.from(table.querySelectorAll('tbody tr'))
            .filter(tr => tr.querySelector('.dropdown-toggle'))
            .map(tr => {
              const tds = tr.querySelectorAll(':scope > td');
              if (tds.length < 7) return null;
              const regNo = (tds[1].textContent || '').trim();
              const regDate = (tds[2].textContent || '').trim();
              const pt = tds[3].querySelector('table');
              const partyRows = pt ? Array.from(pt.querySelectorAll('tr')).map(pr => pr.querySelector('td')?.innerHTML || '') : [];
              const pd = tds[4].querySelector('table');
              const propRows = pd ? Array.from(pd.querySelectorAll('tr')).map(pr => {
                const c = pr.querySelectorAll('td');
                return c.length === 2 ? [(c[0].textContent||'').trim(), (c[1].textContent||'').trim()] : null;
              }).filter(Boolean) : [];
              const link = tr.querySelector("a[onclick*='details(']");
              const m = link ? (link.getAttribute('onclick')||'').match(/details\\('([^']+)'/) : null;
              const propText = tds[4].textContent || '';
              const pid = (propText.match(/Property ID:\\s*(\\d+)/) || [])[1] || '';
              return {
                reg_no: regNo,
                reg_date: regDate,
                party_html: partyRows,
                prop_text: propText,
                prop_id: pid,
                prop_kv: propRows,
                doc_id: m ? m[1] : '',
                article: (tds[5].textContent||'').trim(),
                office: (tds[6].textContent||'').trim(),
              };
            }).filter(Boolean);
        }"""
    )

    rows: list[dict[str, Any]] = []
    for i, r in enumerate(raw):
        seller_name = seller_addr = ""
        purchaser_name = purchaser_addr = ""
        for html in r["party_html"]:
            m = _PARTY_RE.search(html)
            if not m:
                continue
            name, role, addr = m.group(1).strip(), m.group(2).lower(), m.group(3).strip()
            if "seller" in role:
                seller_name, seller_addr = name, addr
            elif "purchaser" in role:
                purchaser_name, purchaser_addr = name, addr

        village = prop_desc = plot_no = upic = ""
        for key, val in r["prop_kv"]:
            k = key.lower()
            if k == "village name":
                village = val
            elif k == "property description":
                prop_desc = val
            elif "plot number" in k:
                plot_no = val
            elif "upic" in k:
                upic = val

        rows.append({
            "sno": i + 1,
            "document_id": r["doc_id"],
            "registration_no": r["reg_no"],
            "registration_date": r["reg_date"],
            "seller_name": seller_name,
            "seller_address": seller_addr,
            "purchaser_name": purchaser_name,
            "purchaser_address": purchaser_addr,
            "property_id": r["prop_id"],
            "village_name": village,
            "property_description": prop_desc,
            "plot_number": plot_no,
            "upic_number": upic,
            "article": r["article"],
            "registration_office": r["office"],
        })
    return rows


def extract_table(page, *, screenshot_dir: Path) -> list[dict[str, Any]]:
    """Switch to 'All' rows and scrape. Returns the row list."""
    table = page.locator(SEL["table"]).first
    table.wait_for(state="visible", timeout=TIMING_MS["page_load"])
    _select_all_rows(page)
    _screenshot(page, "extract_all", screenshot_dir)
    rows = _scrape_rows(page)
    if not rows:
        raise RuntimeError("no rows extracted — check that 'All' was applied")
    return rows


# --------------------------------------------------------------------------- #
# CSV export                                                                  #
# --------------------------------------------------------------------------- #


def write_csv(
    rows: list[dict[str, Any]],
    *,
    out_dir: Path,
    date_from: str,
    date_to: str,
) -> Path:
    """Write a date-stamped CSV. Returns the path."""
    if not rows:
        raise RuntimeError("no rows to export")
    out_dir.mkdir(parents=True, exist_ok=True)
    # Match the project-wide naming (ISO dates) so process_data's
    # source_csv metadata reads cleanly.
    def _iso(d: str) -> str:
        dd, mm, yyyy = d.split("-")
        return f"{yyyy}-{mm}-{dd}"

    out = out_dir / f"rohini_sector28_{_iso(date_from)}_to_{_iso(date_to)}.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    sys.stderr.write(f"[daily-runner] wrote {len(rows)} rows to {out}\n")
    return out


def write_json(
    rows: list[dict[str, Any]],
    *,
    out_dir: Path,
) -> Path:
    """Write a stable JSON snapshot the integrator can pick up."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "ngdrs_search_latest.json"
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    return out


# --------------------------------------------------------------------------- #
# One-shot end-to-end                                                         #
# --------------------------------------------------------------------------- #


def run_full_scrape(
    config: dict[str, Any],
    solver: CaptchaSolver,
    run_id: str,
) -> dict[str, Any]:
    """Run the entire pipeline. Returns a result dict with the artifact paths.

    The result dict has the same shape as DailyRunner.run(); this function
    is the "do the actual work" half of DailyRunner and is split out so
    it can be called directly from tests or other orchestrators.
    """
    ngdrs = config.get("ngdrs", {}) or {}
    paths = config.get("paths", {}) or {}
    browser = config.get("browser", {}) or {}
    verif = config.get("verification", {}) or {}

    user_data_dir = Path(paths.get("user_data_dir", "data/user_data"))
    if not user_data_dir.is_absolute():
        user_data_dir = (_HERE / user_data_dir).resolve()
    screenshot_dir = Path(paths.get("screenshot_dir", "data/screenshots"))
    if not screenshot_dir.is_absolute():
        screenshot_dir = (_HERE / screenshot_dir).resolve()
    raw_dir = Path(paths.get("raw_dir", "data/raw"))
    if not raw_dir.is_absolute():
        raw_dir = (_HERE / raw_dir).resolve()
    csv_dir = Path(paths.get("csv_dir", "../data"))
    if not csv_dir.is_absolute():
        csv_dir = (_HERE / csv_dir).resolve()

    days_back = int(ngdrs.get("days_back", 1))
    username = ngdrs.get("username", "")
    password = ngdrs.get("password", "")

    if not username or not password:
        raise ValueError(
            "ngdrs.username and ngdrs.password must be set in config.json "
            "(or via $NGD_USER / $NGD_PASS env)"
        )

    started_at = datetime.now().isoformat(timespec="seconds")
    captcha_image: Optional[Path] = None
    rows: list[dict[str, Any]] = []
    csv_path: Optional[Path] = None
    json_path: Optional[Path] = None
    params: dict[str, str] = {}
    error: Optional[str] = None
    error_type: Optional[str] = None

    with open_browser(
        user_data_dir=user_data_dir,
        headless=bool(ngdrs.get("headless", True)),
        channel=browser.get("channel", ngdrs.get("channel", "chrome")),
        viewport=(
            int(browser.get("viewport_width", 1440)),
            int(browser.get("viewport_height", 900)),
        ),
        extra_args=browser.get("args", ["--start-maximized"]),
    ) as ctx:
        page = _active_page(ctx)
        page.goto(URLS["base"], wait_until="domcontentloaded", timeout=TIMING_MS["page_load"])
        try:
            captcha_image = login(
                page,
                username=username,
                password=password,
                solver=solver,
                screenshot_dir=screenshot_dir,
                timeout_s=int(verif.get("input_timeout_seconds", 300)),
                run_id=run_id,
                skip_get_otp=bool(
                    (config.get("verification") or {}).get("skip_get_otp", False)
                ),
            )
            navigate_to_search(page)
            params = fill_search_form(
                page,
                days_back=days_back,
                search_by=ngdrs.get("search_by", DEFAULT_SEARCH["search_by"]),
                district=ngdrs.get("district", DEFAULT_SEARCH["district"]),
                taluka=ngdrs.get("taluka", DEFAULT_SEARCH["taluka"]),
                village=ngdrs.get("village", DEFAULT_SEARCH["village"]),
                attribute=ngdrs.get("attribute", DEFAULT_SEARCH["attribute"]),
                screenshot_dir=screenshot_dir,
            )
            submit_search(page, screenshot_dir=screenshot_dir)
            rows = extract_table(page, screenshot_dir=screenshot_dir)
        except TimeoutError as exc:
            error = f"timeout: {exc}"
            error_type = "TimeoutError"
        except Exception as exc:
            error = str(exc)
            error_type = type(exc).__name__

    if rows:
        json_path = write_json(rows, out_dir=raw_dir)
        csv_path = write_csv(
            rows,
            out_dir=csv_dir,
            date_from=params.get("date_from", date.today().strftime("%d-%m-%Y")),
            date_to=params.get("date_to", date.today().strftime("%d-%m-%Y")),
        )

    finished_at = datetime.now().isoformat(timespec="seconds")
    return {
        "run_id": run_id,
        "status": "success" if rows else ("need_input" if error_type == "TimeoutError" else "error"),
        "started_at": started_at,
        "finished_at": finished_at,
        "days_back": days_back,
        "date_from": params.get("date_from"),
        "date_to": params.get("date_to"),
        "headless": bool(ngdrs.get("headless", True)),
        "solver": solver.name,
        "captcha_image": str(captcha_image) if captcha_image else None,
        "rows_extracted": len(rows),
        "csv_path": str(csv_path) if csv_path else None,
        "json_path": str(json_path) if json_path else None,
        "error": error,
        "error_type": error_type,
    }
