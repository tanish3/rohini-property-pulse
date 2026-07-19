#!/usr/bin/env bash
# Monthly refresh: scrape → process → build geojson → commit → push → wait.
#
# Usage:
#   export NGD_USER=... NGD_PASS=...
#   bash .opencode/skills/ngdrs-search/scripts/monthly_refresh.sh [--days-back 30]
#
# All sub-steps are idempotent and resumable:
#   - The NGDRS workflow checkpoints to data/state/workflow_state.json
#   - The Nominatim cache lives in .cache/nominatim/ (persists across runs)
#   - The deploy helper exits cleanly if there's nothing to commit
#
# Required env: NGD_USER, NGD_PASS (citizen login for ngdrs.delhi.gov.in)
# Optional:     NGD_VILLAGE (default: "Rohini Sector-28")
#               NGD_TALUKA  (default: "Alipur")
#               GH_TOKEN    (for gh CLI; or `gh auth login` first)
#               GH_REPO     (default: rohini-property-pulse)

set -euo pipefail

# --- locate paths ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../.." && pwd)"

PY="$REPO_ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "ERROR: $PY not found. Set NGDRS_VENV or create .venv"; exit 2; }

VENV_PY="${NGDRS_VENV:-$REPO_ROOT/.venv}/bin/python"
[ -x "$VENV_PY" ] || { echo "ERROR: $VENV_PY not found"; exit 2; }

# --- args ---
DAYS_BACK=30
while [ $# -gt 0 ]; do
  case "$1" in
    --days-back) DAYS_BACK="$2"; shift 2 ;;
    --help|-h) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

step() { printf "\n\033[1;34m=== %s ===\033[0m\n" "$*"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[1;33m!\033[0m %s\n" "$*"; }
die()  { printf "  \033[1;31m✗\033[0m %s\n" "$*" >&2; exit 1; }

# --- preflight ---
[ -n "${NGD_USER:-}" ] || die "NGD_USER not set (citizen login username)"
[ -n "${NGD_PASS:-}" ] || die "NGD_PASS not set (citizen login password)"
command -v gh >/dev/null 2>&1 || die "gh CLI not installed (brew install gh)"

# --- 1. Run the scraper (always with --reset so we get a fresh run) ---
step "1/5  Scrape NGDRS (days_back=$DAYS_BACK, village=${NGD_VILLAGE:-Rohini Sector-28})"
cd "$SKILL_DIR"
bash scripts/run.sh --reset --days-back "$DAYS_BACK" ${NGD_VILLAGE:+--village "$NGD_VILLAGE"} ${NGD_TALUKA:+--taluka "$NGD_TALUKA"}
ok "scraper finished"

# --- 2. Locate the freshly exported CSV ---
step "2/5  Process CSV → JSON"
cd "$REPO_ROOT"
LATEST_CSV=$(ls -t data/rohini_sector28_*.csv 2>/dev/null | head -1 || true)
[ -n "$LATEST_CSV" ] || die "no CSV found under data/rohini_sector28_*.csv"
ok "using $LATEST_CSV"

"$PY" scripts/process_data.py
ok "wrote meta.json, sector28-summary.json, registrations.json"

# --- 3. Build geojson (Nominatim cache is persistent, fetched on demand) ---
step "3/5  Refresh OSM boundaries (cached) + write geojson"
if [ ! -f .cache/nominatim/sector_28.json ]; then
  warn "Nominatim cache empty — fetching (one-time, ~35 s)"
  "$PY" scripts/refresh_sector_cache.py
else
  ok "Nominatim cache present ($(ls .cache/nominatim/*.json | wc -l | tr -d ' ') files)"
fi
"$PY" scripts/build_sector_geojson.py
"$PY" scripts/build_pocket_geojson.py
ok "wrote sectors.geojson + sector-28-pockets.geojson"

# --- 4. Smoke test the live site (optional but cheap) ---
step "4/5  Smoke test the local build"
"$PY" -m http.server 8765 --bind 127.0.0.1 --directory docs > /tmp/rpp_smoke.log 2>&1 &
SRV_PID=$!
trap "kill $SRV_PID 2>/dev/null || true" EXIT
for i in 1 2 3 4 5; do
  curl -s -o /dev/null -w "" "http://127.0.0.1:8765/" && break || sleep 0.5
done
if "$PY" scripts/smoke_test.py 2>&1 | tail -3; then
  ok "smoke test passed"
else
  warn "smoke test reported issues — continuing to deploy anyway"
fi
kill $SRV_PID 2>/dev/null || true
trap - EXIT

# --- 5. Deploy (commit + push + wait for Pages) ---
step "5/5  Deploy to GitHub Pages"
"$PY" scripts/deploy_site.py
ok "site updated"

printf "\n\033[1;32mMonthly refresh complete.\033[0m\n"
printf "  URL:   https://%(owner)s.github.io/rohini-property-pulse/\n" \
  -v owner "$(git remote get-url origin | sed -E 's#.*github.com[:/]([^/]+)/.*#\1#')"
printf "  Login: admin / rohini2026\n"
