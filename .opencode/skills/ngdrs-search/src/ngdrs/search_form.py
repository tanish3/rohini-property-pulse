"""Fill the e-Search form and submit.

Taluka and village are user inputs with sensible defaults (Alipur, Rohini
Sector-28). They can be passed explicitly, via env vars, or via state from
a previous run.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from playwright.sync_api import BrowserContext, Page

from .browser import active_page, log, screenshot
from .config import CONFIG, get_search_params
from .dom import human_type, select_by_text
from .state import State


def _date_range(days_back: int) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=days_back)
    return start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y")


def _type_date(page: Page, selector: str, dd_mm_yyyy: str) -> None:
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=CONFIG.timing.page_load_ms)
    loc.click()
    loc.fill("")
    for ch in dd_mm_yyyy:
        loc.press(ch if ch != "-" else "Minus")
        page.wait_for_timeout(60)
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)


def _select_cascading(page: Page, taluka: str, village: str) -> None:
    select_by_text(page, CONFIG.sel.taluka, taluka)
    page.wait_for_timeout(CONFIG.timing.short_ms)
    select_by_text(page, CONFIG.sel.village, village)
    page.wait_for_timeout(CONFIG.timing.short_ms)


def fill_form(
    ctx: BrowserContext,
    state: State,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    days_back: int = 30,
    district: str | None = None,
    taluka: str | None = None,
    village: str | None = None,
    attribute: str | None = None,
    search_by: str | None = None,
) -> dict[str, Any]:
    if state.is_done("form_filled"):
        log("search_form: already done; skipping")
        return state.search_params

    page = active_page(ctx)
    if "srosearch" not in page.url:
        page.goto(CONFIG.urls.search, wait_until="domcontentloaded", timeout=CONFIG.timing.page_load_ms)
        page.wait_for_timeout(CONFIG.timing.short_ms)

    params = get_search_params(
        district=district, taluka=taluka, village=village,
        attribute=attribute, search_by=search_by,
    )
    log(f"search_form: using params = {params}")

    select_by_text(page, CONFIG.sel.search_by, params["search_by"])
    page.wait_for_timeout(CONFIG.timing.short_ms)
    select_by_text(page, CONFIG.sel.district, params["district"])
    page.wait_for_timeout(CONFIG.timing.short_ms)

    if not (date_from and date_to):
        date_from, date_to = _date_range(days_back)
    _type_date(page, CONFIG.sel.date_from, date_from)
    _type_date(page, CONFIG.sel.date_to, date_to)

    _select_cascading(page, params["taluka"], params["village"])
    select_by_text(page, CONFIG.sel.attribute, params["attribute"])
    page.wait_for_timeout(CONFIG.timing.short_ms)

    state.search_params = {
        **params,
        "date_from": date_from,
        "date_to": date_to,
    }
    state.save()
    state.record("form_filled_screenshot", str(screenshot(page, "form_filled")))
    state.mark("form_filled")
    return state.search_params


def submit_search(ctx: BrowserContext, state: State) -> None:
    if state.is_done("search_submitted"):
        log("search_form: already submitted; skipping")
        return
    page = active_page(ctx)
    page.locator(CONFIG.sel.search_btn).first.click()
    page.wait_for_timeout(CONFIG.timing.long_ms)
    page.locator(CONFIG.sel.table).first.wait_for(
        state="visible", timeout=CONFIG.timing.page_load_ms
    )
    page.wait_for_timeout(CONFIG.timing.short_ms)
    state.record("results_screenshot", str(screenshot(page, "search_results")))
    state.mark("search_submitted")


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--days-back", type=int, default=30)
    p.add_argument("--district")
    p.add_argument("--taluka")
    p.add_argument("--village")
    p.add_argument("--attribute")
    p.add_argument("--search-by")
    args = p.parse_args()
    state = State.load()
    from .browser import open_browser

    with open_browser() as ctx:
        params = fill_form(
            ctx, state,
            days_back=args.days_back,
            district=args.district,
            taluka=args.taluka,
            village=args.village,
            attribute=args.attribute,
            search_by=args.search_by,
        )
        submit_search(ctx, state)
    print(params)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
