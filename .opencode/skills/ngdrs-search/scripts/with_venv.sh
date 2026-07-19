#!/usr/bin/env bash
# Locate the project venv by walking up from this script.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_DIR/../../.." && pwd)"

# Allow override
VENV_PATH="${NGDRS_VENV:-$REPO_ROOT/.venv}"
if [ ! -x "$VENV_PATH/bin/python" ]; then
  echo "Cannot find venv at $VENV_PATH" >&2
  echo "Set NGDRS_VENV=/path/to/.venv" >&2
  exit 1
fi

cd "$SKILL_DIR"
export PYTHONPATH=src
exec "$VENV_PATH/bin/python" "$@"
