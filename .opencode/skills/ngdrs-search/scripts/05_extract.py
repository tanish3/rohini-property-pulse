"""Step 05: set the page-length dropdown to All and extract the table to JSON."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ngdrs.browser import open_browser
from ngdrs.extract import extract
from ngdrs.state import State


def main() -> int:
    state = State.load()
    with open_browser() as ctx:
        rows = extract(ctx, state)
    print(f"{len(rows)} rows -> {state.artifacts.get('json_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
