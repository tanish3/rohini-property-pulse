"""Small DOM helpers: human-paced typing, captcha image extraction, etc."""
from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import ElementHandle, Locator, Page

from .config import CONFIG


def human_type(page: Page, selector: str, text: str, *, press_enter: bool = False) -> None:
    """Type one char at a time with a small per-char jitter."""
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=CONFIG.timing.page_load_ms)
    loc.click()
    loc.fill("")
    for ch in text:
        loc.press(ch if ch != " " else "Space")
        page.wait_for_timeout(CONFIG.timing.human_typing_min_ms)
        # pseudo-jitter without randomness: alternate min/max
    if press_enter:
        page.keyboard.press("Enter")


def select_by_text(page: Page, selector: str, visible_text: str) -> None:
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=CONFIG.timing.page_load_ms)
    options = loc.locator("option").all()
    target_value: str | None = None
    for opt in options:
        if (opt.text_content() or "").strip() == visible_text:
            target_value = opt.get_attribute("value")
            if target_value:
                break
    if not target_value:
        raise RuntimeError(f"Option {visible_text!r} not found in {selector}")
    loc.select_option(value=target_value)


def select_by_visible(page: Page, selector: str, visible_text: str) -> None:
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=CONFIG.timing.page_load_ms)
    loc.select_option(label=visible_text)


def read_captcha_text(page: Page, out_png: Path) -> str:
    """Grab the captcha image bytes and return the path; OCR is the caller's job."""
    img = page.locator(CONFIG.sel.captcha_img).first
    img.wait_for(state="visible", timeout=CONFIG.timing.page_load_ms)
    img.screenshot(path=str(out_png))
    return str(out_png)


def click_when_ready(page: Page, selector: str, *, timeout_ms: int | None = None) -> None:
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=timeout_ms or CONFIG.timing.page_load_ms)
    loc.scroll_into_view_if_needed()
    loc.click()


def wait_for_url_contains(page: Page, fragment: str, *, timeout_ms: int | None = None) -> None:
    page.wait_for_url(
        f"**/*{fragment}*",
        timeout=timeout_ms or CONFIG.timing.page_load_ms,
        wait_until="domcontentloaded",
    )


def safe_text(handle: ElementHandle | Locator) -> str:
    if isinstance(handle, Locator):
        return (handle.text_content() or "").strip()
    return (handle.text_content() or "").strip()


_DDMMYYYY = re.compile(r"(\d{2})-(\d{2})-(\d{4})")


def normalize_date(s: str) -> str:
    """Return DD-MM-YYYY; raise if it doesn't match."""
    m = _DDMMYYYY.search(s)
    if not m:
        raise ValueError(f"Unexpected date format: {s!r}")
    return m.group(0)
