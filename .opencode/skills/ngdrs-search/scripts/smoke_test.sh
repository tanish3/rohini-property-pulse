#!/usr/bin/env bash
# Smoke test: import every module and verify Chrome launches.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/with_venv.sh" - <<'PY'
from ngdrs import config, browser, dom, state, login, navigate, search_form, extract, export, orchestrator
print('imports OK')

from ngdrs.config import CONFIG
print('  urls.base =', CONFIG.urls.base)
print('  defaults =', CONFIG.defaults)

with browser.open_browser() as ctx:
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto('about:blank')
    print('  chrome launch OK on', page.title() or 'blank')
print('smoke test PASSED')
PY
