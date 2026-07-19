"""Step 03: navigate from the welcome screen to the e-Search page."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ngdrs.browser import open_browser
from ngdrs.navigate import navigate_to_search
from ngdrs.state import State


def main() -> int:
    state = State.load()
    with open_browser() as ctx:
        navigate_to_search(ctx, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
