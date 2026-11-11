"""Post-scrape deploy: convert CSV → JSON, commit, push, wait for Pages.

This module is the "finish line" of the daily pipeline. After a successful
scrape, it:

  1. Locates the freshly-exported CSV (`data/rohini_sector28_*.csv`)
  2. Runs the project's `scripts/process_data.py` to convert the CSV
     into the three JSON files the static site consumes:
       docs/data/registrations.json
       docs/data/sector28-summary.json
       docs/data/meta.json
  3. Optionally rebuilds the OSM-based geojson files (only if the
     Nominatim cache is fresh — usually a no-op).
  4. Stages + commits + pushes via the project's
     `scripts/deploy_site.py`, which then polls the GitHub Pages
     build until it finishes.
  5. Returns a result dict with the live URL, commit SHA, and build
     status.

The script is intentionally thin: it doesn't reimplement the deploy
logic, it just orchestrates the project's existing scripts. This way
the daily runner and the manual monthly_refresh.sh stay in sync — they
both use the same deploy pipeline.

Why stop after push?
    The static site is designed to load data at runtime. `index.html`
    is a pure shell; `app.js` fetches the three JSON files on every
    page load. Once GitHub Pages rebuilds (usually < 60 s after push),
    the next visitor sees the new data automatically. Nothing else is
    needed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Repo root (one level up from this file: daily_runner/deploy.py → repo root)
_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


# --------------------------------------------------------------------------- #
# Logging helpers                                                             #
# --------------------------------------------------------------------------- #


def _log(msg: str) -> None:
    sys.stderr.write(f"[daily-runner/deploy] {msg}\n")
    sys.stderr.flush()


def _run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
    """Run a subprocess, streaming stderr but capturing stdout."""
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
        **kw,
    )


# --------------------------------------------------------------------------- #
# 1. Locate the freshest CSV                                                  #
# --------------------------------------------------------------------------- #


def find_latest_csv(data_dir: Path) -> Optional[Path]:
    """Return the most recently modified `rohini_sector28_*.csv` or None."""
    if not data_dir.exists():
        return None
    csvs = sorted(
        data_dir.glob("rohini_sector28_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return csvs[0] if csvs else None


# --------------------------------------------------------------------------- #
# 2. CSV → JSON                                                               #
# --------------------------------------------------------------------------- #


def process_csv_to_json(
    python: str,
    csv_path: Path | None = None,
    all_csvs: Optional[list[Path]] = None,
) -> dict[str, Any]:
    """Run `scripts/process_data.py` over every known CSV.

    Passing the full list keeps the site's month-by-month history intact
    while today's window is refreshed (process_data dedupes by registration
    number).
    """
    script = SCRIPTS_DIR / "process_data.py"
    if not script.exists():
        raise FileNotFoundError(
            f"{script} not found — is the daily_runner folder inside the project root?"
        )
    cmd = [python, str(script)]
    if all_csvs:
        cmd.extend(str(p) for p in all_csvs)
    elif csv_path is not None:
        cmd.append(str(csv_path))
    _log(f"running process_data.py  (csv={csv_path}, cwd={REPO_ROOT})")
    out = _run(cmd)
    # process_data.py prints to stdout; surface the last few lines.
    tail = "\n".join(out.stdout.splitlines()[-6:])
    _log("process_data.py finished:\n" + tail)
    return {
        "process_data_stdout_tail": tail,
        "registrations_json": str(REPO_ROOT / "docs" / "data" / "registrations.json"),
        "summary_json":       str(REPO_ROOT / "docs" / "data" / "sector28-summary.json"),
        "meta_json":          str(REPO_ROOT / "docs" / "data" / "meta.json"),
    }


# --------------------------------------------------------------------------- #
# 3. Geojson (optional, only if cache is fresh)                               #
# --------------------------------------------------------------------------- #


def maybe_rebuild_geojson(python: str, *, force: bool = False) -> dict[str, Any]:
    """Rebuild sectors.geojson and sector-28-pockets.geojson.

    If `force=False` and the Nominatim cache is missing, the rebuild is
    skipped (the geojson files are static; we only need to regenerate
    them when the OSM boundaries actually change).
    """
    cache_dir = REPO_ROOT / ".cache" / "nominatim"
    if not force and not cache_dir.exists():
        _log("no Nominatim cache → skipping geojson rebuild (files unchanged)")
        return {"rebuilt": False, "reason": "no nominatim cache"}

    result: dict[str, Any] = {"rebuilt": True, "steps": []}
    for script in ("build_sector_geojson.py", "build_pocket_geojson.py"):
        sp = SCRIPTS_DIR / script
        if not sp.exists():
            _log(f"  (skipping {script}: not found)")
            continue
        try:
            _run([python, str(sp)])
            result["steps"].append(script)
        except subprocess.CalledProcessError as exc:
            _log(f"  {script} failed: {exc.stderr or exc}")
            result["steps"].append(f"{script}: FAILED")
    return result


# --------------------------------------------------------------------------- #
# 4. Commit + push + wait for Pages                                           #
# --------------------------------------------------------------------------- #


def commit_and_push(
    python: str,
    *,
    commit_message: str,
    wait_timeout_s: int = 180,
    git_user: Optional[str] = None,
    git_email: Optional[str] = None,
) -> dict[str, Any]:
    """Run the project's `scripts/deploy_site.py` with the given message.

    Returns a dict with the live URL, build status, and the commit SHA
    the build is for. Raises on failure.
    """
    script = SCRIPTS_DIR / "deploy_site.py"
    if not script.exists():
        raise FileNotFoundError(f"{script} not found")

    # Set git identity for the commit (deploy_site.py doesn't do this;
    # we wrap it here so the runner can override).
    env_overrides: dict[str, str] = {}
    if git_user:
        env_overrides["GIT_AUTHOR_NAME"] = git_user
        env_overrides["GIT_COMMITTER_NAME"] = git_user
    if git_email:
        env_overrides["GIT_AUTHOR_EMAIL"] = git_email
        env_overrides["GIT_COMMITTER_EMAIL"] = git_email

    # Capture the SHA we're about to push, so we can include it in the
    # result (and so we can confirm the Pages build is for OUR commit).
    try:
        sha_before = _run(
            ["git", "rev-parse", "HEAD"]
        ).stdout.strip()
    except subprocess.CalledProcessError:
        sha_before = ""

    env = os.environ.copy()
    env.update(env_overrides)
    _log(f"running deploy_site.py  (msg={commit_message!r})")
    proc = subprocess.run(
        [python, str(script), commit_message],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"deploy_site.py exited {proc.returncode}; the push may have "
            f"failed. Check `git status` and the gh auth status."
        )

    # Best-effort: derive the live URL from the git remote.
    live_url = None
    try:
        remote = _run(
            ["git", "remote", "get-url", "origin"]
        ).stdout.strip()
        if "github.com" in remote:
            import re
            m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", remote)
            if m:
                owner, repo = m.group(1), m.group(2)
                live_url = f"https://{owner}.github.io/{repo}/"
    except Exception:
        pass

    # Best-effort: get the SHA that was actually pushed.
    try:
        sha_after = _run(
            ["git", "rev-parse", "HEAD"]
        ).stdout.strip()
    except subprocess.CalledProcessError:
        sha_after = ""

    return {
        "live_url": live_url,
        "sha_before": sha_before,
        "sha_after":  sha_after,
        "deploy_returncode": proc.returncode,
    }


# --------------------------------------------------------------------------- #
# 5. Top-level orchestrator                                                   #
# --------------------------------------------------------------------------- #


def run_deploy(
    config: dict[str, Any],
    scrape_result: dict[str, Any],
) -> dict[str, Any]:
    """End-to-end post-scrape deploy. Returns a deploy result dict.

    `scrape_result` is the result of DailyRunner.run() — we use its
    csv_path to know what was just exported.
    """
    deploy_cfg = config.get("deploy", {}) or {}
    if not deploy_cfg.get("enabled", False):
        return {"status": "skipped", "reason": "deploy.enabled is false"}

    python = sys.executable
    started_at = datetime.now().isoformat(timespec="seconds")
    result: dict[str, Any] = {
        "status": "pending",
        "started_at": started_at,
        "finished_at": None,
        "steps": {},
        "live_url": None,
        "csv_used": None,
        "commit_message": None,
        "error": None,
        "error_type": None,
    }

    # ----- step 1: locate the CSV ----- #
    csv_paths_cfg = config.get("paths", {}) or {}
    data_dir = Path(csv_paths_cfg.get("csv_dir", "data"))
    if not data_dir.is_absolute():
        data_dir = REPO_ROOT / data_dir
    csv_path = scrape_result.get("csv_path") or find_latest_csv(data_dir)
    if not csv_path:
        raise FileNotFoundError(
            f"no CSV found in {data_dir} — was the scrape successful?"
        )
    result["csv_used"] = str(csv_path)
    _log(f"using CSV: {csv_path}")

    try:
        # ----- step 2: CSV → JSON ----- #
        all_csvs = sorted(data_dir.glob("rohini_sector28_*.csv"))
        result["steps"]["process"] = process_csv_to_json(
            python, Path(csv_path), all_csvs=all_csvs
        )

        # ----- step 3: geojson (optional) ----- #
        if deploy_cfg.get("rebuild_geojson", False):
            result["steps"]["geojson"] = maybe_rebuild_geojson(
                python, force=bool(deploy_cfg.get("force_geojson", False))
            )
        else:
            _log("rebuild_geojson=false → skipping geojson rebuild")
            result["steps"]["geojson"] = {"rebuilt": False, "reason": "disabled in config"}

        # ----- step 4: commit + push + wait ----- #
        commit_msg = deploy_cfg.get(
            "commit_message_template",
            "data: daily scrape {date} ({rows} rows)",
        ).format(
            date=datetime.now().strftime("%Y-%m-%d"),
            rows=scrape_result.get("rows_extracted", "?"),
        )
        result["commit_message"] = commit_msg

        push = commit_and_push(
            python,
            commit_message=commit_msg,
            wait_timeout_s=int(deploy_cfg.get("pages_build_timeout_s", 180)),
            git_user=deploy_cfg.get("git_user"),
            git_email=deploy_cfg.get("git_email"),
        )
        result["steps"]["push"] = push
        result["live_url"] = push.get("live_url")

        result["status"] = "success"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        result["error_type"] = type(exc).__name__

    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return result
