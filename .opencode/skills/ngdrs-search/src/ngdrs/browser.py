"""Chrome lifecycle helpers shared across steps.

Each script gets its own browser instance pointing at the same persistent
profile so cookies, login state, and the user-data-dir survive between runs.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .config import CONFIG


def _build_context(p: Playwright) -> BrowserContext:
    return p.chromium.launch_persistent_context(
        user_data_dir=str(CONFIG.paths.chrome_profile),
        channel=CONFIG.channel,
        headless=CONFIG.headless,
        viewport={"width": 1440, "height": 900},
        no_viewport=False,
        args=["--start-maximized"],
    )


@contextmanager
def open_browser() -> Iterator[BrowserContext]:
    """Yield a persistent Chrome context. Closes it on exit."""
    with sync_playwright() as p:
        ctx = _build_context(p)
        try:
            yield ctx
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def active_page(ctx: BrowserContext) -> Page:
    if ctx.pages:
        return ctx.pages[0]
    return ctx.new_page()


def screenshot(page: Page, name: str) -> Path:
    """Save a screenshot under data/screenshots and return the path."""
    out = CONFIG.paths.state_dir.parent / "screenshots" / f"{name}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out), full_page=True)
    return out


def log(msg: str) -> None:
    print(f"[ngdrs] {msg}", file=sys.stderr, flush=True)
