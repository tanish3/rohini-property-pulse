---
name: ngdrs-search
description: Scrape the Delhi NGDRS citizen e-Search portal (ngdrs.delhi.gov.in) for property registrations. Use when the user asks to fetch, scrape, or export NGDRS / DORIS / Delhi property registration data, or to run the Rohini property scraper. Defaults to North > Alipur > Rohini Sector-28 with Plot Number, but taluka and village are configurable per run. Uses file-based input for captcha and OTP so the agent can supply them deterministically.
license: MIT
compatibility: opencode
metadata:
  audience: data-engineers
  workflow: property-scraping
  site: ngdrs.delhi.gov.in
---

# NGDRS Citizen e-Search Scraper

Hybrid skill: the agent drives the workflow and delegates each subaction to a
deterministic Python script under `scripts/`. State is checkpointed to
`data/state/workflow_state.json` so a failed run can be resumed without
re-doing finished steps.

The skill folder is **self-contained** — code, scripts, data outputs, Chrome
profile, and state all live under `.opencode/skills/ngdrs-search/`. The only
external dependency is the project venv at `<repo>/.venv/` (override with
`NGDRS_VENV`).

## When to load me

- User asks to scrape / fetch / export property data from `ngdrs.delhi.gov.in`
- User mentions Rohini, Delhi property registrations, DORIS, or "the NGDRS workflow"
- User wants to re-run an interrupted scrape or change village / date range

## Required env (set before invoking scripts)

| Var             | Purpose                                                          |
| --------------- | ---------------------------------------------------------------- |
| `NGD_USER`      | Citizen login username                                           |
| `NGD_PASS`      | Citizen login password                                           |

## Optional search-params (defaults shown)

| Var             | Default            | CLI flag         |
| --------------- | ------------------ | ---------------- |
| `NGD_DISTRICT`  | `North`            | `--district`     |
| `NGD_TALUKA`    | `Alipur`           | `--taluka`       |
| `NGD_VILLAGE`   | `Rohini Sector-28` | `--village`      |
| `NGD_ATTRIBUTE` | `Plot Number`      | `--attribute`    |
| `NGD_SEARCH_BY` | `Property Details` | `--search-by`    |

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

**Alternative input channels** (in priority order):
1. The value file (above) — used by the agent
2. Stdin line — used by humans running the script directly
3. Env var (`NGD_CAPTCHA` / `NGD_OTP`) — only when `--non-interactive` is passed

To solve the captcha:
1. Read `data/state/inputs/awaiting_captcha.json` to confirm what's expected
2. Open the image at the path in `data/screenshots/captcha.png`
3. Write the characters to `data/state/inputs/captcha.txt`

To submit the OTP after the script clicks "Get OTP":
1. Read `data/state/inputs/awaiting_otp.json`
2. Wait for the SMS, write the code to `data/state/inputs/otp.txt`

## Steps (one persistent Chrome instance per run)

| # | Script                             | What it does                                                                                |
| - | ---------------------------------- | ------------------------------------------------------------------------------------------- |
| 1 | `scripts/01_open_browser.py`       | Launch persistent Chrome (`.chrome-profile/`) so cookies survive between steps               |
| 2 | `scripts/02_login.py`              | Username + password + captcha (PNG saved) + OTP — both via file-based inputs                |
| 3 | `scripts/03_navigate.py`           | Open sidebar, expand E-Search, click nested Search, wait for `/srosearch`                    |
| 4 | `scripts/04_search.py`             | Fill the form (Property Details, district, last N days, taluka, village, attribute) and submit |
| 5 | `scripts/05_extract.py`            | Set page-length dropdown to All, scrape `#tableparty` to `data/raw/ngdrs_search_latest.json`|
| 6 | `scripts/06_export.py`             | Convert JSON to `data/ngdrs_<from>_to_<to>.csv`                                              |

Or one shot: `scripts/run_workflow.py [--non-interactive] [--days-back N] [--reset] [--village ...] [--taluka ...]`.

## How to run the workflow

1. Smoke test: `bash scripts/smoke_test.sh` (verifies imports and Chrome)
2. Set credentials: `export NGD_USER=... NGD_PASS=...`
3. Run: `bash scripts/run.sh --village "Rohini Sector-28" --days-back 30`
4. Watch the marker files under `data/state/inputs/`
5. Write captcha to `data/state/inputs/captcha.txt` when prompted
6. Write OTP to `data/state/inputs/otp.txt` when prompted
7. Result: CSV at `data/ngdrs_<date_from>_to_<date_to>.csv`

## How state works

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

## Files I create / touch

```
.opencode/skills/ngdrs-search/
  data/
    raw/ngdrs_search_latest.json
    ngdrs_<from>_to_<to>.csv
    screenshots/{captcha,after_login,search_page,form_filled,search_results,extract_all}.png
    state/workflow_state.json
    state/inputs/awaiting_*.json
    state/inputs/{captcha,otp}.txt
  .chrome-profile/   (persistent Chrome profile - do not commit)
```
