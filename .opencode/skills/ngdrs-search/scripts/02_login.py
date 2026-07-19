"""Step 02: log in. Waits for captcha.txt then otp.txt under data/state/inputs/.

Pass --non-interactive to disable stdin fallback (file/env only).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ngdrs.browser import open_browser
from ngdrs.login import login
from ngdrs.state import State


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--input-timeout", type=int, default=300)
    args = p.parse_args()
    state = State.load()
    with open_browser() as ctx:
        login(
            ctx, state,
            timeout_s=args.input_timeout,
            allow_stdin=not args.non_interactive,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
