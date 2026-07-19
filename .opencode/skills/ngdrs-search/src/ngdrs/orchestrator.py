"""End-to-end orchestrator. Runs every step in one persistent browser session."""
from __future__ import annotations

import argparse
import sys

from .browser import log, open_browser
from .export import export
from .extract import extract
from .login import login
from .navigate import navigate_to_search
from .search_form import fill_form, submit_search
from .state import State


def run(
    *,
    days_back: int = 30,
    district: str | None = None,
    taluka: str | None = None,
    village: str | None = None,
    attribute: str | None = None,
    search_by: str | None = None,
    timeout_s: int = 300,
    allow_stdin: bool = True,
) -> int:
    state = State.load()
    log(f"state: {state.status()}")
    with open_browser() as ctx:
        login(ctx, state, timeout_s=timeout_s, allow_stdin=allow_stdin)
        navigate_to_search(ctx, state)
        fill_form(
            ctx, state,
            days_back=days_back,
            district=district, taluka=taluka, village=village,
            attribute=attribute, search_by=search_by,
        )
        submit_search(ctx, state)
        extract(ctx, state)
    out = export()
    log(f"done. csv -> {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="NGDRS e-search scraper")
    p.add_argument("--non-interactive", action="store_true", help="Disable stdin prompts (file/env only)")
    p.add_argument("--days-back", type=int, default=30)
    p.add_argument("--district", help="Override district (default: North)")
    p.add_argument("--taluka", help="Override taluka (default: Alipur)")
    p.add_argument("--village", help="Override village (default: Rohini Sector-28)")
    p.add_argument("--attribute", help="Override property attribute (default: Plot Number)")
    p.add_argument("--search-by", help="Override search-by (default: Property Details)")
    p.add_argument("--input-timeout", type=int, default=300, help="Seconds to wait for captcha/OTP")
    p.add_argument("--reset", action="store_true", help="Clear workflow state first")
    args = p.parse_args()

    if args.reset:
        State.load().reset()
        log("state reset")

    try:
        return run(
            days_back=args.days_back,
            district=args.district,
            taluka=args.taluka,
            village=args.village,
            attribute=args.attribute,
            search_by=args.search_by,
            timeout_s=args.input_timeout,
            allow_stdin=not args.non_interactive,
        )
    except KeyboardInterrupt:
        log("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
