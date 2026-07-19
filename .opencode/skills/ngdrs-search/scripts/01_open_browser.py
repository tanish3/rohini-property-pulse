"""Step 01: open persistent Chrome. Exits immediately after launch.

The browser stays open in the background. Use scripts 02-06 in the same
session, or run scripts/run_workflow.py to do everything in one go.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ngdrs.browser import open_browser
from ngdrs.config import CONFIG
from ngdrs.state import State


def main() -> int:
    state = State.load()
    state.mark("browser_opened")
    print(f"Launching Chrome with profile at {CONFIG.paths.chrome_profile}")
    with open_browser() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(CONFIG.urls.base, wait_until="domcontentloaded")
        print(f"Browser open at: {page.url}")
        print("Leave this window open. Other scripts reuse the same profile.")
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
