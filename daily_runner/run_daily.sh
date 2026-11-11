#!/usr/bin/env bash
# Cron-safe wrapper for the daily NGDRS refresh.
#
#   crontab entry (09:30 every day):
#     30 9 * * * /Users/tanishmittal/codes/Property/Rohini_prop_scrape/daily_runner/run_daily.sh
#
# It pins PATH (cron starts with a minimal environment), writes a dated log
# under daily_runner/data/state/, and exits with the runner's status:
#   0 success · 1 error · 2 bad config · 3 captcha/OTP needed · 4 deploy failed
set -uo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$REPO_ROOT/daily_runner/data/state"
LOG="$STATE_DIR/cron-$(date +%F).log"
mkdir -p "$STATE_DIR"

cd "$REPO_ROOT" || exit 1

LOCK_DIR="$STATE_DIR/chrome-profile.lock"
acquire_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        echo $$ > "$LOCK_DIR/pid"
        return 0
    fi
    # Stale lock from a crashed run (older than 15 minutes) -> reclaim.
    if [ -d "$LOCK_DIR" ]; then
        now=$(date +%s)
        mtime=$(stat -f %m "$LOCK_DIR" 2>/dev/null || echo "$now")
        if [ $((now - mtime)) -gt 900 ]; then
            rm -rf "$LOCK_DIR"
            mkdir "$LOCK_DIR" 2>/dev/null && echo $$ > "$LOCK_DIR/pid" && return 0
        fi
    fi
    return 1
}
if ! acquire_lock; then
    echo "=== $(date '+%F %T %Z') another scrape/keepalive holds the Chrome profile — skipping ===" >> "$STATE_DIR/chrome-lock.log"
    exit 0
fi
trap 'rm -rf "$LOCK_DIR"' EXIT

{
    echo "=== $(date '+%F %T %Z') starting daily refresh ==="
    .venv/bin/python daily_runner/daily_runner.py --update-site --print-json
    rc=$?
    echo "=== $(date '+%F %T %Z') finished with exit=$rc ==="
    exit "$rc"
} >> "$LOG" 2>&1
