#!/usr/bin/env python3
"""Commit, push, and wait for the GitHub Pages build to finish.

Usage:
    .venv/bin/python scripts/deploy_site.py [commit-message]

Reads GH_TOKEN / uses `gh auth token` for auth. Exits 0 on success, non-zero on
any failure (with a clear message).

Steps (all idempotent / deterministic):
  1. Stage docs/data/*.json, docs/data/*.geojson, and data/*.csv
  2. Bail if there's nothing to commit (already up to date)
  3. Commit with the provided message (or default "data refresh YYYY-MM-DD")
  4. Push to origin/main
  5. Poll gh api /repos/<owner>/<repo>/pages/builds/latest until built or timeout
  6. Print the live URL and build status
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GH_REPO = "rohini-property-pulse"  # default; override with $GH_REPO
OWNER_RE = r"^https?://[^/]+/([^/]+)/rohini-property-pulse(?:\.git)?/?$"


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True, **kw)


def gh_api(path: str) -> dict:
    """Call GitHub API via `gh api` using the active auth."""
    out = subprocess.run(
        ["gh", "api", path, "--jq", "."],
        check=True, capture_output=True, text=True,
    )
    return json.loads(out.stdout) if out.stdout.strip() else {}


def get_repo_owner() -> str:
    """Find the GitHub owner of the current remote."""
    out = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    url = out.stdout.strip()
    import re
    m = re.search(OWNER_RE, url)
    if not m:
        raise SystemExit(f"Could not parse owner from remote URL: {url!r}")
    return m.group(1)


def has_changes_to_commit() -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    # Only count docs/data and the source CSV (not the persistent .cache)
    tracked = []
    for line in out.stdout.splitlines():
        path = line[3:].strip().strip('"')
        if path.startswith("docs/data/") or path.startswith("data/") and path.endswith(".csv"):
            tracked.append(line)
    return bool(tracked)


def main() -> int:
    msg = sys.argv[1] if len(sys.argv) > 1 else (
        f"data refresh {dt.date.today().isoformat()}"
    )

    if shutil.which("gh") is None:
        print("ERROR: `gh` CLI not found. Install: brew install gh", file=sys.stderr)
        return 2

    if not has_changes_to_commit():
        print("No docs/data or data/*.csv changes to commit. Site already up to date.")
        # Still verify the live build is healthy
        try:
            owner = get_repo_owner()
            repo = os.environ.get("GH_REPO", GH_REPO)
            status = gh_api(f"/repos/{owner}/{repo}/pages/builds/latest").get("status")
            print(f"Latest Pages build: {status}")
        except Exception as e:
            print(f"  (could not query Pages status: {e})")
        return 0

    print("=== Staging changes ===")
    run(["git", "add", "docs/data/"])
    # Also stage the freshly exported CSV (data/*.csv is git-ignored, so use -f)
    csvs = list((ROOT / "data").glob("rohini_sector28_*.csv"))
    if csvs:
        latest = max(csvs, key=lambda p: p.stat().st_mtime)
        # Use --force so the .gitignore'd CSV is staged
        run(["git", "add", "-f", str(latest.relative_to(ROOT))])
    run(["git", "status", "--short"])

    print("\n=== Committing ===")
    run(["git", "commit", "-m", msg])
    print(f"  → {msg}")

    print("\n=== Pushing to origin/main ===")
    run(["git", "push", "origin", "main"])

    print("\n=== Waiting for GitHub Pages build ===")
    owner = get_repo_owner()
    repo = os.environ.get("GH_REPO", GH_REPO)
    deadline = time.time() + 180  # 3 min
    last_status = None
    while time.time() < deadline:
        build = gh_api(f"/repos/{owner}/{repo}/pages/builds/latest")
        last_status = build.get("status")
        if last_status == "built":
            err = build.get("error", {}).get("message") if build.get("error") else None
            commit = build.get("commit", "")[:12]
            duration = build.get("duration", 0)
            print(f"  ✓ build complete · commit {commit} · {duration}ms · error: {err or 'none'}")
            url = f"https://{owner}.github.io/{repo}/"
            print(f"\n  Live URL: {url}")
            print(f"  Login:    admin / rohini2026")
            return 0
        if last_status == "errored":
            print(f"  ✗ build ERRORED: {build.get('error')}")
            return 1
        print(f"  ... {last_status}")
        time.sleep(5)

    print(f"  ✗ build did not finish in 180s (last status: {last_status})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
