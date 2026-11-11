"""Login step: username + password + captcha + OTP.

Captcha and OTP are read via the inputs module. The script writes a marker
file under data/state/inputs/awaiting_*.json and waits for the value file
(otp.txt / captcha.txt) to appear. The agent (or a human) can write the
value to the file at any time, including via env var override.

The portal validates the captcha and the credentials inside its "Get OTP"
AJAX call and reloads the whole form on any non-zero status, so we post the
same request ourselves to read the real JSON status.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from .browser import active_page, log, open_browser, screenshot
from .config import CONFIG
from .dom import human_type
from .inputs import await_input
from .state import State

MAX_CAPTCHA_ATTEMPTS = 3

# The portal validates the captcha *and* the credentials inside this AJAX call.
# Its own click handler alerts and then reloads the whole form on every
# non-zero status, which hides the real error from the caller. Posting the
# same payload ourselves returns the JSON status verbatim.
_OTP_POST_JS = """
() => new Promise((resolve) => {
  $.post('/NGDRS_DL/Users/otpsavecitizen', {
    username: document.querySelector('#username').value,
    password: hex_sha256(document.querySelector('#password').value),
    captcha: document.querySelector('#captcha').value
  }, function (data) {
    resolve({ok: true, raw: String(data)});
  }).fail(function (xhr, status, err) {
    resolve({ok: false, status: String(status), err: String(err)});
  });
})
"""

# The Login button (#btnSubmit) is display:none in the portal's CSS and no
# script ever reveals it, so the form is submitted programmatically with the
# same password transform the page's after_validation_check() applies.
_SUBMIT_LOGIN_JS = """
() => {
  const pwd = document.querySelector('#password');
  const salt = document.querySelector('#hfSaltedStr').value;
  pwd.value = hex_sha256(salt + hex_sha256(pwd.value));
  document.getElementById('User').submit();
}
"""


def _resolve_creds() -> tuple[str, str]:
    user = os.environ.get(CONFIG.creds.user_env)
    pwd = os.environ.get(CONFIG.creds.pass_env)
    if not user or not pwd:
        raise SystemExit(
            f"Set {CONFIG.creds.user_env} and {CONFIG.creds.pass_env} env vars first."
        )
    return user, pwd


def _read_captcha_image(page: Page) -> Path:
    out = CONFIG.paths.state_dir.parent / "screenshots" / "captcha.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = page.locator(CONFIG.sel.captcha_img).first
    if img.count() == 0:
        page.screenshot(path=str(out), full_page=False, clip={"x": 0, "y": 0, "width": 800, "height": 400})
    else:
        img.screenshot(path=str(out))
    return out


def _already_logged_in(page: Page) -> bool:
    page.goto(CONFIG.urls.welcome, wait_until="domcontentloaded", timeout=CONFIG.timing.page_load_ms)
    page.wait_for_timeout(CONFIG.timing.short_ms)
    if page.locator("a:has-text('Logout'), a:has-text('Sign Out')").count() > 0:
        return True
    return page.locator("button:has-text('Get OTP')").count() == 0 and "welcome" in page.url


def _fill_credentials(page: Page, user: str, pwd: str) -> None:
    human_type(page, CONFIG.sel.username, user)
    page.wait_for_timeout(CONFIG.timing.short_ms)
    human_type(page, CONFIG.sel.password, pwd)
    page.wait_for_timeout(CONFIG.timing.short_ms)


def _post_otp_request(page: Page) -> dict:
    """Call the portal's OTP endpoint and return {status, msg}."""
    result = page.evaluate(_OTP_POST_JS)
    if not result.get("ok"):
        raise RuntimeError(
            f"Get OTP request failed: {result.get('status')} {result.get('err')}"
        )
    try:
        return json.loads(result["raw"])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Unexpected Get OTP response: {result['raw']!r}") from exc


def _request_otp(
    page: Page,
    state: State,
    *,
    timeout_s: int,
    allow_stdin: bool,
) -> None:
    """Fill the login form and request an OTP, retrying bad captchas.

    A rejected captcha is retried; rejected credentials are fatal so we don't
    burn attempts (or lock the account) against a stale password.
    """
    user, pwd = _resolve_creds()
    for attempt in range(1, MAX_CAPTCHA_ATTEMPTS + 1):
        page.goto(CONFIG.urls.login, wait_until="domcontentloaded", timeout=CONFIG.timing.page_load_ms)
        page.wait_for_timeout(CONFIG.timing.short_ms)
        _fill_credentials(page, user, pwd)

        captcha_png = _read_captcha_image(page)
        state.record("captcha_image", str(captcha_png))
        captcha_text = await_input(
            "captcha",
            hint=f"Read the image at {captcha_png} and write the characters",
            timeout_s=timeout_s,
            allow_stdin=allow_stdin,
        )
        human_type(page, CONFIG.sel.captcha, captcha_text)
        page.wait_for_timeout(CONFIG.timing.short_ms)

        payload = _post_otp_request(page)
        status = payload.get("status")
        msg = str(payload.get("msg", ""))
        log(f"login: otpsavecitizen -> status={status!r} msg={msg!r}")

        if status == 0:
            # Server accepted the credentials and sent an SMS. Reveal the
            # OTP field ourselves — the site's own handler is what reloads.
            page.evaluate("() => { $('#otp_div').show(); $('#otp').show(); }")
            page.locator(CONFIG.sel.otp).first.wait_for(
                state="visible", timeout=CONFIG.timing.page_load_ms
            )
            return

        if status == 4:
            raise RuntimeError(
                "NGDRS requires a password change for this account "
                "(status=4). Log in once in a browser, set a new password, "
                "then update NGD_PASS."
            )

        if "username or password" in msg.lower():
            raise RuntimeError(
                f"NGDRS rejected the credentials for {user!r}: {msg} "
                "The password on file is stale — update NGD_PASS and re-run."
            )

        log(
            f"login: captcha rejected (attempt {attempt}/{MAX_CAPTCHA_ATTEMPTS}); retrying"
        )
        page.wait_for_timeout(CONFIG.timing.short_ms)

    raise RuntimeError(
        "OTP request failed on every attempt — the captcha was likely misread"
    )


def login(
    ctx: BrowserContext,
    state: State,
    *,
    timeout_s: int = 300,
    allow_stdin: bool = True,
) -> None:
    if state.is_done("logged_in"):
        log("login: already marked done; skipping")
        return
    page = active_page(ctx)
    if _already_logged_in(page):
        log("login: session still valid")
        state.mark("logged_in")
        return

    # Surface the portal's JS alerts in the run log instead of letting
    # Playwright dismiss them silently.
    page.on(
        "dialog",
        lambda d: (log(f"login: portal alert: {d.message}"), d.dismiss()),
    )

    _request_otp(page, state, timeout_s=timeout_s, allow_stdin=allow_stdin)

    otp = await_input(
        "otp",
        hint="Enter the OTP received on your registered mobile",
        timeout_s=timeout_s,
        allow_stdin=allow_stdin,
    )
    if not otp:
        raise RuntimeError("No OTP provided")

    human_type(page, CONFIG.sel.otp, otp)
    page.wait_for_timeout(CONFIG.timing.short_ms)

    # #btnSubmit is hidden by the portal's CSS, so click() would hang. Submit
    # the form the way its own handler does (salted password hash + POST).
    page.evaluate(_SUBMIT_LOGIN_JS)
    try:
        page.wait_for_url("**/welcome*", timeout=CONFIG.timing.page_load_ms)
    except PlaywrightTimeoutError:
        detail = ""
        for sel in ("#otp_error", ".form-error", ".alert", ".error-message"):
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                detail = (loc.text_content() or "").strip()
                if detail:
                    break
        raise RuntimeError(
            f"Login failed after OTP (url={page.url}): {detail or 'no error text on page'}"
        )

    log(f"login: post-login URL = {page.url}")
    state.mark("logged_in")
    state.record("login_screenshot", str(screenshot(page, "after_login")))


def main() -> int:
    p_args = sys.argv[1:]
    timeout_s = 300
    allow_stdin = True
    if "--non-interactive" in p_args:
        allow_stdin = False
    state = State.load()
    with open_browser() as ctx:
        login(ctx, state, timeout_s=timeout_s, allow_stdin=allow_stdin)
    return 0
