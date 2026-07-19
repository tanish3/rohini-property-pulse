"""Step 04: fill the e-Search form (defaults: North, Alipur, Rohini Sector-28, Plot, 30-day window)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ngdrs.browser import open_browser
from ngdrs.search_form import fill_form, submit_search
from ngdrs.state import State


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days-back", type=int, default=30)
    p.add_argument("--district")
    p.add_argument("--taluka")
    p.add_argument("--village")
    p.add_argument("--attribute")
    p.add_argument("--search-by")
    args = p.parse_args()
    state = State.load()
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
