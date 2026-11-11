#!/usr/bin/env python3
"""Backfill every Rohini sector (default 28–41) from the NGDRS e-Search.

Runs sequentially, one sector at a time, inside a single browser session so
only one captcha/OTP is needed for the whole sweep. Each sector is searched
over the full date range first (the portal accepts long ranges); if that
returns nothing the script falls back to 30-day windows.

Usage:
    .venv/bin/python scripts/backfill_sectors.py --start 2026-06-19
    .venv/bin/python scripts/backfill_sectors.py --start 2026-06-19 --sectors 28-41
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "daily_runner"))

import scraper as S  # noqa: E402
from captcha_solver import create_solver  # noqa: E402
from session_store import (  # noqa: E402
    as_playwright_cookie,
    load as load_session,
    save_from_context as save_session,
)

DEFAULT_CONFIG = ROOT / "daily_runner" / "config.json"

# Sectors that exist as NGDRS villages. Sectors 29-37 and 39-41 are DDA
# sectors carved out of revenue villages (Pooth Kalan, Begum Pur, ...) and
# are not selectable in the portal.
SECTOR_MAP: dict[int, tuple[str, str, str]] = {
    18: ("North", "Alipur", "Rohini Sector-18"),
    19: ("North", "Alipur", "Rohini Sector-19"),
    26: ("North", "Alipur", "Rohini Sector-26"),
    27: ("North", "Alipur", "Rohini Sector-27"),
    28: ("North", "Alipur", "Rohini Sector-28"),
    38: ("North West", "Sdm Rohini", "Rohini Sector 38"),
}


def parse_sectors(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def find_village(options: list[str], sector: int) -> str | None:
    """Match 'Rohini Sector-29', 'Rohini Sector 29', 'Rohini Sector-29A'…"""
    pat = re.compile(rf"^rohini\s+sector[-\s]?{sector}\b", re.IGNORECASE)
    for opt in options:
        if pat.match(opt.strip()):
            return opt
    return None


def window_list(start: date, end: date, step: int) -> list[tuple[date, date]]:
    out = []
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=step - 1), end)
        out.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return out


def search(page, *, village: str, d1: str, d2: str, shots: Path,
           district: str | None = None, taluka: str | None = None) -> list[dict]:
    page.goto(S.URLS["search"], wait_until="domcontentloaded", timeout=S.TIMING_MS["page_load"])
    page.wait_for_timeout(S.TIMING_MS["short"])
    S.fill_search_form(
        page,
        date_from=d1,
        date_to=d2,
        district=district or "North",
        taluka=taluka or "Alipur",
        village=village,
        screenshot_dir=shots,
    )
    S.submit_search(page, screenshot_dir=shots)
    return S.extract_table(page, screenshot_dir=shots)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-06-19")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--sectors", default="28-41")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args()

    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    sectors = parse_sectors(args.sectors)

    config = json.loads(Path(args.config).read_text())
    ngdrs = config.get("ngdrs", {})
    paths = config.get("paths", {})
    shots = (ROOT / "daily_runner" / paths.get("screenshot_dir", "data/screenshots")).resolve()
    shots.mkdir(parents=True, exist_ok=True)
    csv_dir = (ROOT / "daily_runner" / paths.get("csv_dir", "../data")).resolve()
    csv_dir.mkdir(parents=True, exist_ok=True)
    user_data = (ROOT / "daily_runner" / paths.get("user_data_dir", "data/user_data")).resolve()

    full = (start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y"))
    windows = window_list(start, end, 30)

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
        page.goto(S.URLS["base"], wait_until="domcontentloaded", timeout=S.TIMING_MS["page_load"])
        S.login(
            page,
            username=ngdrs["username"],
            password=ngdrs["password"],
            solver=create_solver(config),
            screenshot_dir=shots,
            timeout_s=int(config.get("verification", {}).get("input_timeout_seconds", 300)),
            run_id="sector-backfill",
        )
        save_session(ctx)

        # Discover the actual village option labels once.
        page.goto(S.URLS["search"], wait_until="domcontentloaded", timeout=S.TIMING_MS["page_load"])
        page.wait_for_timeout(S.TIMING_MS["short"])
        S._select_by_text(page, S.SEL["search_by"], ngdrs.get("search_by", "Property Details"))
        page.wait_for_timeout(S.TIMING_MS["short"])
        S._select_by_text(page, S.SEL["district"], ngdrs.get("district", "North"))
        page.wait_for_timeout(S.TIMING_MS["short"])
        S._select_by_text(page, S.SEL["taluka"], ngdrs.get("taluka", "Alipur"))
        page.wait_for_timeout(S.TIMING_MS["short"])
        options = [
            (o.text_content() or "").strip()
            for o in page.locator(S.SEL["village"]).first.locator("option").all()
        ]
        rohini = [o for o in options if "rohini" in o.lower()]
        print(f"[sectors] {len(options)} villages, {len(rohini)} Rohini:", rohini, flush=True)

        totals: dict[int, int] = {}
        for sector in sectors:
            mapped = SECTOR_MAP.get(sector)
            if mapped:
                district, taluka, village = mapped
            else:
                village = find_village(options, sector)
                district, taluka = "North", "Alipur"
                if not village:
                    print(f"[sectors] sector {sector}: NOT FOUND in village list", flush=True)
                    continue

            print(f"[sectors] sector {sector}: {district}/{taluka}/{village!r} (full range)", flush=True)
            rows: list[dict] = []
            try:
                rows = search(page, village=village, d1=full[0], d2=full[1], shots=shots,
                              district=district, taluka=taluka)
            except Exception as exc:  # noqa: BLE001
                print(f"[sectors]   full range failed: {exc!r}; using windows", flush=True)

            if not rows:
                print("[sectors]   no rows for full range → 30-day windows", flush=True)
                for a, b in windows:
                    d1, d2 = a.strftime("%d-%m-%Y"), b.strftime("%d-%m-%Y")
                    try:
                        part = search(page, village=village, d1=d1, d2=d2, shots=shots,
                                      district=district, taluka=taluka)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[sectors]   {d1}→{d2} failed: {exc!r}", flush=True)
                        part = []
                    print(f"[sectors]   {d1}→{d2}: {len(part)} rows", flush=True)
                    rows.extend(part)

            # Deduplicate across windows before writing.
            by_key: dict[str, dict] = {}
            for r in rows:
                by_key[r.get("registration_no") or r.get("document_id") or str(len(by_key))] = r
            rows = list(by_key.values())

            totals[sector] = len(rows)
            if rows:
                out = S.write_csv(
                    rows,
                    out_dir=csv_dir,
                    date_from=full[0],
                    date_to=full[1],
                    prefix=f"rohini_sector{sector}",
                )
                print(f"[sectors]   wrote {out.name}", flush=True)

        save_session(ctx)

    print("[sectors] summary:", {k: totals[k] for k in sorted(totals)}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
