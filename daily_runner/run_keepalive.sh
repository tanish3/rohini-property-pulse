#!/usr/bin/env bash
# Keep the NGDRS session warm so the daily scrape never needs the SMS OTP.
#
#   crontab (every 10 minutes):
#     */10 * * * * /Users/tanishmittal/codes/Property/Rohini_prop_scrape/daily_runner/run_keepalive.sh
#
# Exit codes: 0 session alive · 3 no/expired session (cleared; next scrape logs in)
set -uo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$REPO_ROOT/daily_runner/data/state"
LOG="$STATE_DIR/keepalive.log"
mkdir -p "$STATE_DIR"

cd "$REPO_ROOT" || exit 1

# Never race a scrape: NGDRS allows one active session, and two Chrome
# instances cannot share the same profile.
if pgrep -f "daily_runner.py|backfill_sectors.py|backfill_history.py" >/dev/null 2>&1; then
    echo "=== $(date '+%F %T %Z') scrape in progress — keepalive skipped ===" >> "$LOG"
    exit 0
fi

{
    echo "=== $(date '+%F %T %Z') keepalive ==="
    .venv/bin/python daily_runner/session_store.py --touch "$@"
    rc=$?
    echo "=== exit=$rc ==="
    exit "$rc"
} >> "$LOG" 2>&1
