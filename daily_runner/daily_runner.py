"""Daily NGDRS scrape — headless-friendly, config-driven, deterministic.

This is the main entry point. It is fully self-contained: it does NOT
import anything from the ngdrs skill. It only depends on:

  - playwright        (browser automation)
  - anthropic         (optional, only when AI captcha is enabled)
  - captcha_solver.py (sibling module)
  - scraper.py        (sibling module)

Usage:

  # Default config (./config.json)
  python daily_runner.py --print-json

  # Custom config
  python daily_runner.py --config /path/to/config.json

  # Dry run (load + validate config, no browser)
  python daily_runner.py --dry-run

  # For Lambda / cron
  python daily_runner.py --quiet > /dev/null
  # the result is always written to data/state/last_run.json

Exit codes:
  0  success
  1  generic error
  2  bad config
  3  captcha/OTP timed out (so a cron can alert)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Make the local captcha_solver / scraper importable when running this
# file directly (`python daily_runner.py …`).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from captcha_solver import create_solver  # noqa: E402
from deploy import run_deploy              # noqa: E402
from scraper import run_full_scrape        # noqa: E402

# --------------------------------------------------------------------------- #
# Config                                                                      #
# --------------------------------------------------------------------------- #

DEFAULT_CONFIG_PATH = _HERE / "config.json"
EXAMPLE_CONFIG_PATH = _HERE / "config.example.json"
LAST_RUN_PATH = _HERE / "data" / "state" / "last_run.json"


def load_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Config not found: {p}\n"
            f"  → copy {EXAMPLE_CONFIG_PATH} to {p} and fill in your credentials"
        )
    cfg = json.loads(p.read_text())
    return _substitute_env(cfg)


def _substitute_env(obj: Any) -> Any:
    """Substitute ${VAR} / $VAR strings from os.environ (unknown vars
    are left as-is so typos don't silently turn into empty strings)."""
    if isinstance(obj, str):
        if obj.startswith("${") and obj.endswith("}"):
            return os.environ.get(obj[2:-1], obj)
        if obj.startswith("$") and len(obj) > 1 and obj[1].isupper():
            return os.environ.get(obj[1:], obj)
        return obj
    if isinstance(obj, dict):
        return {k: _substitute_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_env(v) for v in obj]
    return obj


def _resolve(cfg: dict[str, Any], dotted: str, default: Any = None) -> Any:
    cur: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


# --------------------------------------------------------------------------- #
# Runner                                                                      #
# --------------------------------------------------------------------------- #


class DailyRunner:
    def __init__(self, config: dict[str, Any], *, deploy: bool = False) -> None:
        self.config = config
        self.run_id = uuid.uuid4().hex[:12]
        self.solver = create_solver(config)
        self.deploy = deploy

    def run(self) -> dict[str, Any]:
        try:
            result = run_full_scrape(self.config, self.solver, self.run_id)
        except Exception as exc:
            result = {
                "run_id": self.run_id,
                "status": "error",
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "headless": bool(_resolve(self.config, "ngdrs.headless", True)),
                "solver": self.solver.name,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

        # Attach the captcha screenshot as base64 (for Lambda responses,
        # S3 upload, etc.) so the integrator doesn't have to read the
        # file separately.
        if result.get("captcha_image"):
            ip = Path(result["captcha_image"])
            if ip.exists() and _resolve(self.config, "verification.share_screenshot_base64", True):
                try:
                    result["captcha_image_b64"] = base64.b64encode(
                        ip.read_bytes()
                    ).decode("ascii")
                except Exception:
                    pass

        # ----- deploy step (only on success, only if --update-site) -----
        if self.deploy and result.get("status") == "success":
            deploy_result = run_deploy(self.config, result)
            result["deploy"] = deploy_result
            # If deploy failed, downgrade the overall status so the
            # caller knows the site is NOT up to date.
            if deploy_result.get("status") == "error":
                result["status"] = "deploy_failed"
                result["error"] = deploy_result.get("error")
                result["error_type"] = deploy_result.get("error_type")
            elif deploy_result.get("status") == "success":
                # Promote the live URL to the top level for convenience.
                result["live_url"] = deploy_result.get("live_url")

        self._write_last_run(result)
        return result

    def _write_last_run(self, result: dict[str, Any]) -> None:
        path = Path(
            _resolve(self.config, "logging.log_file", str(LAST_RUN_PATH))
        )
        if not path.is_absolute():
            path = _HERE / path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as exc:  # pragma: no cover
            sys.stderr.write(f"[daily-runner] could not write {path}: {exc!r}\n")


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Daily NGDRS e-search scrape (headless-friendly).",
    )
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    p.add_argument("--print-json", action="store_true",
                   help="print the result dict as JSON to stdout")
    p.add_argument("--dry-run", action="store_true",
                   help="load + validate config, do not launch a browser")
    p.add_argument("--quiet", action="store_true",
                   help="suppress the human prompt banner (still writes marker)")
    p.add_argument("--update-site", action="store_true",
                   help="after a successful scrape, convert CSV→JSON, "
                        "commit, push to GitHub, and wait for the Pages "
                        "build to finish. The site auto-loads the new "
                        "JSON on the next visitor; nothing more to do.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {args.config}: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        printable = {k: v for k, v in config.items() if not k.startswith("_")}
        sys.stderr.write("[daily-runner] dry-run: would run with config:\n")
        sys.stderr.write(json.dumps(printable, indent=2, ensure_ascii=False) + "\n")
        if args.update_site:
            sys.stderr.write("\n[daily-runner] --update-site is set: after a "
                             "successful scrape, the runner would also:\n")
            sys.stderr.write("  1. run scripts/process_data.py (CSV → JSON)\n")
            sys.stderr.write("  2. git add + commit + push\n")
            sys.stderr.write("  3. wait for the GitHub Pages build\n")
            sys.stderr.write("  4. (the site loads the new JSON on the next "
                             "visit — no further work needed)\n")
        return 0

    if args.quiet:
        # The solver still prints its banner; redirect stderr to /dev/null
        # but keep stdout for the result dict. Use a log file instead.
        solver_section = sys.stderr
        log_path = _HERE / "data" / "state" / "stderr.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "a")
        os.dup2(log_fh.fileno(), sys.stderr.fileno())
        solver_section.write(
            f"[daily-runner] stderr redirected to {log_path} (--quiet)\n"
        )

    runner = DailyRunner(config, deploy=args.update_site)
    result = runner.run()

    if args.print_json:
        printable = {k: v for k, v in result.items() if k != "captcha_image_b64"}
        print(json.dumps(printable, indent=2, ensure_ascii=False))

    if result["status"] == "success":
        return 0
    if result["status"] == "need_input":
        return 3
    if result["status"] == "deploy_failed":
        return 4  # scrape ok, deploy failed
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
