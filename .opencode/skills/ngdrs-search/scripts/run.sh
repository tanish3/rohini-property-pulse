#!/usr/bin/env bash
# Run the full NGDRS workflow end-to-end. Requires NGD_USER, NGD_PASS in env.
# Captcha + OTP are read from stdin.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/with_venv.sh" "$DIR/run_workflow.py" "$@"
