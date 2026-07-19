"""Navigate from the welcome screen to the e-Search page."""
from __future__ import annotations

from playwright.sync_api import BrowserContext, Page

from .browser import active_page, log, screenshot
from .config import CONFIG
from .dom import click_when_ready, wait_for_url_contains
from .state import State


def navigate_to_search(ctx: BrowserContext, state: State) -> None:
    if state.is_done("navigated_to_search"):
        log("navigate: already done; skipping")
        return
    page = active_page(ctx)
    page.goto(CONFIG.urls.welcome, wait_until="domcontentloaded", timeout=CONFIG.timing.page_load_ms)
    page.wait_for_timeout(CONFIG.timing.short_ms)

    # If the sidebar is collapsed, click the hamburger first.
    if page.locator(CONFIG.sel.search_subitem).count() == 0:
        click_when_ready(page, CONFIG.sel.toggle_nav)
        page.wait_for_timeout(CONFIG.timing.short_ms)

    click_when_ready(page, CONFIG.sel.esearch_link)
    page.wait_for_timeout(CONFIG.timing.short_ms)

    # E-Search expands inline; click the nested "Search" item.
    click_when_ready(page, CONFIG.sel.search_subitem)
    wait_for_url_contains(page, "srosearch", timeout_ms=CONFIG.timing.page_load_ms)
    page.wait_for_timeout(CONFIG.timing.short_ms)

    state.mark("navigated_to_search")
    state.record("navigate_screenshot", str(screenshot(page, "search_page")))


def main() -> int:
    state = State.load()
    from .browser import open_browser

    with open_browser() as ctx:
        navigate_to_search(ctx, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
