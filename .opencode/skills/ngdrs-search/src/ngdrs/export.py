"""Convert the extracted JSON to a named CSV."""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from .config import CONFIG
from .state import State


def _filename_suffix() -> str:
    state = State.load()
    p = state.search_params or {}
    df, dt = p.get("date_from", ""), p.get("date_to", "")
    if df and dt:
        return f"{df}_to_{dt}".replace("-", "")
    today = datetime.now().strftime("%Y%m%d")
    return f"asof_{today}"


def export() -> Path:
    json_path = CONFIG.paths.last_json
    if not json_path.exists():
        raise FileNotFoundError(
            f"{json_path} missing; run the extract step first."
        )
    rows = json.loads(json_path.read_text())
    if not rows:
        raise RuntimeError("No rows in JSON; nothing to export")

    suffix = _filename_suffix()
    out = CONFIG.paths.last_csv.with_name(f"ngdrs_{suffix}.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    state = State.load()
    state.record("csv_path", str(out))
    state.mark("csv_exported")
    print(f"Wrote {len(rows)} rows to {out}")
    return out


def main() -> int:
    export()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
