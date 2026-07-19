"""Run the full NGDRS e-search workflow end-to-end.

Usage:
    export NGD_USER='...' NGD_PASS='...'
    .venv/bin/python scripts/run_workflow.py [--non-interactive] [--days-back N] [--reset]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ngdrs.orchestrator import main

if __name__ == "__main__":
    raise SystemExit(main())
