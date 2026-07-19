---
name: ngdrs-search
description: One-shot monthly workflow that scrapes the Delhi NGDRS citizen e-Search portal (ngdrs.delhi.gov.in), processes the records, builds the geojson maps, and deploys the static site to GitHub Pages. Use when the user asks to refresh the Rohini Property Pulse site, run the monthly data refresh, scrape NGDRS, or push property data to GitHub Pages. Defaults to North > Alipur > Rohini Sector-28 with Plot Number, but taluka and village are configurable per run. Uses file-based input for captcha and OTP so the agent can supply them deterministically. Entirely scripted — no LLM in the loop.
license: MIT
compatibility: opencode
metadata:
  audience: data-engineers
  workflow: property-scraping-and-publishing
  site: ngdrs.delhi.gov.in
  destination: github-pages
---

# NGDRS Citizen e-Search + Static Site Refresh

Hybrid skill: the agent drives the workflow and delegates each subaction to a
**deterministic Python script** under `scripts/`. State is checkpointed to
`data/state/workflow_state.json` so a failed run can be resumed without
re-doing finished steps.

The skill folder is **self-contained** — code, scripts, data outputs, Chrome
profile, and state all live under `.opencode/skills/ngdrs-search/`. The only
external dependencies are the project venv at `<repo>/.venv/` and the `gh` CLI.

## When to load me

- User says "refresh the site", "monthly refresh", "update the website", "run the scrape and push", "rerun the workflow"
- User mentions Rohini, Delhi property registrations, DORIS, NGDRS, or "the property site"
- User wants to scrape, process, and **publish** property data in one shot

## TL;DR — the one command

```bash
export NGD_USER=... NGD_PASS=...
bash .opencode/skills/ngdrs-search/scripts/monthly_refresh.sh
```

That runs the full pipeline end-to-end (scrape → process → build maps → smoke
test → commit → push → wait for Pages build) and prints the live URL when done.

For fine-grained control, see [Stage-by-stage commands](#stage-by-stage-commands).

---

## Pipeline (end-to-end)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 1: NGDRS Scraper (Playwright)                                │
│  01_open_browser → 02_login → 03_navigate → 04_search →            │
│  05_extract → 06_export                                            │
│  Output: data/rohini_sector28_<from>_to_<to>.csv                   │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 2: Process CSV (pure Python)                                 │
│  scripts/process_data.py                                            │
│  Output: docs/data/{meta,registrations,sector28-summary}.json       │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 3: Build maps (pure Python, cached)                          │
│  scripts/refresh_sector_cache.py    (only on first run)            │
│  scripts/build_sector_geojson.py    → docs/data/sectors.geojson    │
│  scripts/build_pocket_geojson.py    → docs/data/sector-28-pockets  │
│                                                                     │
│  Cache: .cache/nominatim/sector_*.json  (gitignored, persistent)   │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 4: Smoke test (Playwright headless)                          │
│  scripts/smoke_test.py                                              │
│  Login → assert .leaflet-container → assert OSM tiles loaded        │
└─────────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 5: Deploy (git + gh API)                                     │
│  scripts/deploy_site.py                                             │
│  - stage docs/data/ + latest CSV                                    │
│  - commit + push origin/main                                        │
│  - poll gh api /repos/.../pages/builds/latest until "built"         │
│  - print live URL                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

## Required env (set before running)

| Var             | Purpose                                                          |
| --------------- | ---------------------------------------------------------------- |
| `NGD_USER`      | Citizen login username (ngdrs.delhi.gov.in)                      |
| `NGD_PASS`      | Citizen login password                                           |
| `GH_TOKEN`      | (optional) GitHub token — only if `gh auth login` was skipped    |

## Optional search params (defaults shown)

| Var             | Default            | CLI flag         |
| --------------- | ------------------ | ---------------- |
| `NGD_DISTRICT`  | `North`            | `--district`     |
| `NGD_TALUKA`    | `Alipur`           | `--taluka`       |
| `NGD_VILLAGE`   | `Rohini Sector-28` | `--village`      |
| `NGD_ATTRIBUTE` | `Plot Number`      | `--attribute`    |
| `NGD_SEARCH_BY` | `Property Details` | `--search-by`    |
| `NGDRS_VENV`    | `<repo>/.venv`     | env only         |
| `GH_REPO`       | `rohini-property-pulse` | env only   |

## Input contract (human-in-the-loop values)

Captcha and OTP are **file-based** so the agent can supply them deterministically.
The script writes a marker JSON and waits for the value file to appear.

| Step     | Marker file                                            | Value file                              |
| -------- | ------------------------------------------------------ | --------------------------------------- |
| Captcha  | `data/state/inputs/awaiting_captcha.json`              | `data/state/inputs/captcha.txt`         |
| OTP      | `data/state/inputs/awaiting_otp.json`                  | `data/state/inputs/otp.txt`             |

Each marker JSON looks like:
```json
{
  "input": "captcha",
  "hint": "Read the image at .../captcha.png and write the characters",
  "created_at": "2026-07-19T16:45:00",
  "write_to": ".../inputs/captcha.txt"
}
```

The script blocks until the value file exists (default timeout 300 s). The
file is deleted after consumption so re-runs always re-prompt.

**Input channels** (in priority order):
1. The value file (above) — used by the agent
2. Stdin line — used by humans running the script directly
3. Env var (`NGD_CAPTCHA` / `NGD_OTP`) — only when `--non-interactive` is passed

To solve the captcha:
1. Read `data/state/inputs/awaiting_captcha.json` to confirm what's expected
2. Open the image at the path in `data/screenshots/captcha.png`
3. Write the characters to `data/state/inputs/captcha.txt`

To submit the OTP:
1. Read `data/state/inputs/awaiting_otp.json`
2. Wait for the SMS, write the code to `data/state/inputs/otp.txt`

## Stage 1 — Scraper substeps

| # | Script                             | What it does                                                                                |
| - | ---------------------------------- | ------------------------------------------------------------------------------------------- |
| 1 | `scripts/01_open_browser.py`       | Launch persistent Chrome (`.chrome-profile/`) so cookies survive between steps               |
| 2 | `scripts/02_login.py`              | Username + password + captcha (PNG saved) + OTP — both via file-based inputs                |
| 3 | `scripts/03_navigate.py`           | Open sidebar, expand E-Search, click nested Search, wait for `/srosearch`                    |
| 4 | `scripts/04_search.py`             | Fill the form (Property Details, district, last N days, taluka, village, attribute) and submit |
| 5 | `scripts/05_extract.py`            | Set page-length dropdown to All, scrape `#tableparty` to `data/raw/ngdrs_search_latest.json`|
| 6 | `scripts/06_export.py`             | Convert JSON to `data/ngdrs_<from>_to_<to>.csv`                                              |

One-shot wrapper: `scripts/run_workflow.py [--non-interactive] [--days-back N] [--reset] [--village ...] [--taluka ...]`.

## Stage-by-stage commands

Run **only the scrape** (Stage 1):
```bash
bash .opencode/skills/ngdrs-search/scripts/run.sh --village "Rohini Sector-28" --days-back 30
```

Run **only the data processing** (Stage 2 — no scraping, no deploy):
```bash
.venv/bin/python scripts/process_data.py
```

Run **only the geojson build** (Stage 3 — no scraping, no deploy):
```bash
.venv/bin/python scripts/refresh_sector_cache.py    # one-time, ~35 s
.venv/bin/python scripts/build_sector_geojson.py
.venv/bin/python scripts/build_pocket_geojson.py
```

Run **only the deploy** (Stage 5 — assumes data already processed):
```bash
.venv/bin/python scripts/deploy_site.py
```

Run the **smoke test** (Stage 4):
```bash
# Serve docs/ on :8765 in one terminal, then:
.venv/bin/python scripts/smoke_test.py
```

Run **everything** (recommended monthly command):
```bash
bash .opencode/skills/ngdrs-search/scripts/monthly_refresh.sh
```

## Determinism guarantees

Every substep is **scripted** — no LLM in the loop at runtime:

| Stage | LLM involvement |
| --- | --- |
| 1 (scrape) | None — pure Playwright, deterministic selectors in `src/ngdrs/config.py` |
| 2 (process CSV) | None — pure Python regex + Counter aggregation |
| 3 (build geojson) | None — pure Python; cache is persistent, so re-runs are byte-identical |
| 4 (smoke test) | None — Playwright assertions only |
| 5 (deploy) | None — `git` + `gh api` only |

**Idempotency**:
- Re-running `process_data.py` on the same CSV → identical JSON output
- `refresh_sector_cache.py` skips files already in `.cache/nominatim/`
- `build_sector_geojson.py` reads cache only, no network
- `deploy_site.py` exits 0 with "already up to date" if there's nothing to commit
- Scraper re-runs always re-prompt for captcha/OTP (intentional — they can't be replayed)

## How state works (scraper)

Each step writes a checkpoint to `data/state/workflow_state.json`. Re-running
without `--reset` skips completed steps. To start over: `--reset` (or delete
the file).

If a step fails, fix the cause and re-run; it resumes from the first unfinished
step. Captcha and OTP always re-prompt because they cannot be replayed.

## Output columns (CSV)

`sno, document_id, registration_no, registration_date, seller_name,
seller_address, purchaser_name, purchaser_address, property_id, village_name,
property_description, plot_number, upic_number, article, registration_office`

## When something breaks

- **Captcha wrong / `verification unsuccessful`** — read the new PNG, write a new value
- **Login session expired** — `--reset` to re-login from scratch
- **Empty CSV** — check `data/screenshots/results.png` and the `search_params`
  block in `data/state/workflow_state.json`
- **Need a different village / dates** — re-run with `--village` / `--days-back`
  (or set `NGD_VILLAGE` / `NGD_TALUKA` env vars)
- **Villages dropdown stays empty after picking taluka** — the site does an
  AJAX load; the script waits 1.5 s after the taluka pick before selecting
  the village. If your network is slow, increase `CONFIG.timing.short_ms` in
  `src/ngdrs/config.py`.
- **Nominatim rate-limited** — `refresh_sector_cache.py` sleeps 1.1 s between
  calls; just re-run and it picks up where it left off (already-cached sectors
  are skipped)
- **Pages build takes too long** — `deploy_site.py` polls for 180 s. If
  GitHub is slow, re-run `deploy_site.py` alone — it will not re-commit if
  the working tree is clean.

## Files I create / touch

```
.opencode/skills/ngdrs-search/
  data/
    raw/ngdrs_search_latest.json
    rohini_sector28_<from>_to_<to>.csv
    screenshots/{captcha,after_login,search_page,form_filled,search_results,extract_all}.png
    state/workflow_state.json
    state/inputs/awaiting_*.json
    state/inputs/{captcha,otp}.txt
  .chrome-profile/   (persistent Chrome profile - do not commit)

<repo>/
  data/rohini_sector28_<from>_to_<to>.csv           # exported CSV
  docs/data/{meta,registrations,sector28-summary}.json
  docs/data/sectors.geojson
  docs/data/sector-28-pockets.geojson
  .cache/nominatim/sector_*.json                    # OSM polygons (gitignored)
```

## Pre-flight check (before first run)

```bash
# 1. Verify the venv has playwright + pandas
.venv/bin/python -c "import playwright, pandas; print('ok')"

# 2. Verify gh is logged in
gh auth status

# 3. Smoke-test the scraper
bash .opencode/skills/ngdrs-search/scripts/smoke_test.sh

# 4. Run the monthly workflow
export NGD_USER=... NGD_PASS=...
bash .opencode/skills/ngdrs-search/scripts/monthly_refresh.sh
```
