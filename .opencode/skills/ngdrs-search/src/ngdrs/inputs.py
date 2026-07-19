"""File-based input channel for captcha, OTP, and other human-in-the-loop values.

The agent or user solves the captcha / receives the OTP and writes the value
to a file under data/state/. The script polls for the file to appear, reads
it, then deletes it (so re-runs don't reuse stale values).

This is more deterministic than stdin prompts because:
  - the watcher reads from a stable path the agent can target
  - values don't get lost if the script crashes
  - re-runs always re-prompt (no caching)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from .config import CONFIG
from .state import State

INPUTS_DIR = CONFIG.paths.inputs_dir


def _ensure_inputs_dir() -> Path:
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    return INPUTS_DIR


def marker(name: str) -> Path:
    return _ensure_inputs_dir() / f"awaiting_{name}.json"


def value(name: str) -> Path:
    return _ensure_inputs_dir() / f"{name}.txt"


def write_marker(name: str, *, hint: str = "") -> Path:
    """Write a small JSON marker so the agent knows the script is waiting."""
    import json
    from datetime import datetime

    path = marker(name)
    payload = {
        "input": name,
        "hint": hint,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "write_to": str(value(name)),
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def clear_marker(name: str) -> None:
    p = marker(name)
    if p.exists():
        p.unlink()


def await_input(
    name: str,
    *,
    hint: str = "",
    timeout_s: int = 300,
    poll_s: float = 0.5,
    allow_stdin: bool = True,
) -> str:
    """Block until `value(name)` exists or stdin receives a line.

    On success, returns the value and deletes the file. If timeout elapses,
    raises TimeoutError.
    """
    write_marker(name, hint=hint)
    val_path = value(name)
    deadline = time.monotonic() + timeout_s
    sys.stderr.write(
        f"\n[ngdrs] waiting for {name!r} (write to: {val_path})\n"
        f"        hint: {hint}\n"
    )
    sys.stderr.flush()
    while time.monotonic() < deadline:
        if val_path.exists():
            content = val_path.read_text().strip()
            if content:
                val_path.unlink()
                clear_marker(name)
                return content
        if allow_stdin and sys.stdin is not None and sys.stdin.readable():
            import select

            r, _, _ = select.select([sys.stdin], [], [], 0.0)
            if r:
                line = sys.stdin.readline().strip()
                if line:
                    clear_marker(name)
                    return line
        time.sleep(poll_s)
    clear_marker(name)
    raise TimeoutError(f"Timed out waiting for {name!r} after {timeout_s}s")


def record_input(name: str, value: str) -> Path:
    """Write an input value (used by callers that already have it)."""
    p = value(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value.strip())
    return p
