"""Step 06: convert the JSON snapshot to a date-stamped CSV."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ngdrs.export import export


def main() -> int:
    out = export()
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
