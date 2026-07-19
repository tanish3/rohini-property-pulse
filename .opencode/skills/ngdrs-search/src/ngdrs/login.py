"""Login step: username + password + captcha + OTP.

Captcha and OTP are read via the inputs module. The script writes a marker
file under data/state/inputs/awaiting_*.json and waits for the value file
(otp.txt / captcha.txt) to appear. The agent (or a human) can write the
value to the file at any time, including via env var override.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import BrowserContext, Page

from .browser import active_page, log, open_browser, screenshot
from .config import CONFIG
from .dom import human_type
from .inputs import await_input
from .state import State


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
    user, pwd = _resolve_creds()
    page = active_page(ctx)
    if _already_logged_in(page):
        log("login: session still valid")
        state.mark("logged_in")
        return

    page.goto(CONFIG.urls.login, wait_until="domcontentloaded", timeout=CONFIG.timing.page_load_ms)
    page.wait_for_timeout(CONFIG.timing.short_ms)

    human_type(page, CONFIG.sel.username, user)
    page.wait_for_timeout(CONFIG.timing.short_ms)
    human_type(page, CONFIG.sel.password, pwd)
    page.wait_for_timeout(CONFIG.timing.short_ms)

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

    page.locator(CONFIG.sel.get_otp).first.click()
    page.wait_for_timeout(CONFIG.timing.long_ms)

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
    page.locator(CONFIG.sel.login_btn).first.click()
    page.wait_for_url("**/welcome*", timeout=CONFIG.timing.page_load_ms)

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


if __name__ == "__main__":
    raise SystemExit(main())
