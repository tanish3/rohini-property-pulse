#!/usr/bin/env python3
"""Backfill NGDRS history into data/rohini_sector28_*.csv, one window at a time.

Uses the same fixed scraper as daily_runner (stored session cookie, ID-based
selectors) but accepts an explicit date range, so consecutive runs cover the
whole history without relying on `days_back`.

Usage:
    .venv/bin/python scripts/backfill_history.py 2026-07-19 2026-11-11
    .venv/bin/python scripts/backfill_history.py 2026-07-19 2026-11-11 --window 30
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "daily_runner"))

import scraper as S  # noqa: E402
from captcha_solver import create_solver  # noqa: E402
from session_store import as_playwright_cookie, load as load_session  # noqa: E402

DEFAULT_CONFIG = ROOT / "daily_runner" / "config.json"


def parse_day(s: str) -> date:
    return date.fromisoformat(s)


def windows(start: date, end: date, step_days: int) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=step_days - 1), end)
        out.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("start", help="YYYY-MM-DD (inclusive)")
    ap.add_argument("end", help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--window", type=int, default=30, help="days per search (default 30)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args()

    start, end = parse_day(args.start), parse_day(args.end)
    if end < start:
        raise SystemExit("end must be >= start")

    config = json.loads(Path(args.config).read_text())
    ngdrs = config.get("ngdrs", {})
    paths = config.get("paths", {})
    screenshots = (ROOT / "daily_runner" / paths.get("screenshot_dir", "data/screenshots")).resolve()
    screenshots.mkdir(parents=True, exist_ok=True)
    csv_dir = (ROOT / "daily_runner" / paths.get("csv_dir", "../data")).resolve()
    csv_dir.mkdir(parents=True, exist_ok=True)

    solver = create_solver(config)
    user_data = (ROOT / "daily_runner" / paths.get("user_data_dir", "data/user_data")).resolve()

    total = 0
    with S.open_browser(
        user_data_dir=user_data,
        headless=bool(ngdrs.get("headless", True)),
        channel=ngdrs.get("channel", "chrome"),
        viewport=(1440, 900),
        extra_args=config.get("browser", {}).get("args", ["--start-maximized"]),
    ) as ctx:
        page = S._active_page(ctx)
        stored = load_session()
        if stored:
            ctx.add_cookies([as_playwright_cookie(stored)])
            print("[backfill] injected stored session cookie")

        page.goto(S.URLS["base"], wait_until="domcontentloaded", timeout=S.TIMING_MS["page_load"])
        S.login(
            page,
            username=ngdrs["username"],
            password=ngdrs["password"],
            solver=solver,
            screenshot_dir=screenshots,
            timeout_s=int(config.get("verification", {}).get("input_timeout_seconds", 300)),
            run_id="backfill",
        )
        S.navigate_to_search(page)

        for df, dt in windows(start, end, args.window):
            d1 = df.strftime("%d-%m-%Y")
            d2 = dt.strftime("%d-%m-%Y")
            print(f"[backfill] {d1} → {d2}", flush=True)

            page.goto(S.URLS["search"], wait_until="domcontentloaded", timeout=S.TIMING_MS["page_load"])
            page.wait_for_timeout(S.TIMING_MS["short"])

            S.fill_search_form(
                page,
                date_from=d1,
                date_to=d2,
                search_by=ngdrs.get("search_by", S.DEFAULT_SEARCH["search_by"]),
                district=ngdrs.get("district", S.DEFAULT_SEARCH["district"]),
                taluka=ngdrs.get("taluka", S.DEFAULT_SEARCH["taluka"]),
                village=ngdrs.get("village", S.DEFAULT_SEARCH["village"]),
                attribute=ngdrs.get("attribute", S.DEFAULT_SEARCH["attribute"]),
                screenshot_dir=screenshots,
            )
            S.submit_search(page, screenshot_dir=screenshots)
            rows = S.extract_table(page, screenshot_dir=screenshots)
            print(f"[backfill]   {len(rows)} rows", flush=True)
            total += len(rows)
            if rows:
                out = S.write_csv(rows, out_dir=csv_dir, date_from=d1, date_to=d2)
                print(f"[backfill]   wrote {out.name}", flush=True)

    print(f"[backfill] done: {total} rows across {len(windows(start, end, args.window))} windows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
