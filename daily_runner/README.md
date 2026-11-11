# daily_runner — self-contained NGDRS scraper

A headless-friendly, config-driven, daily-update scraper for the Delhi
NGDRS citizen e-Search portal. **Completely standalone** — does not
import anything from the ngdrs skill.

## Why a separate folder?

The existing ngdrs skill under `.opencode/skills/ngdrs-search/` is a
heavily interactive, headed-Chrome workflow that the user (or an LLM
agent) drives step by step. It's perfect for one-off scrapes and
debugging, but awkward for:

- Cron / EventBridge daily triggers
- AWS Lambda invocations
- Any environment where a human can't sit at the keyboard

This folder is the answer: a single self-contained Python program that
runs the full pipeline end-to-end, asks for human input via a stable
file-based protocol, and (optionally) uses an AI vision model to solve
the captcha automatically.

## Quick start

```bash
# 1. Dependencies (the project venv already has playwright + Chrome)
cd /path/to/Rohini_prop_scrape
.venv/bin/python -c "import playwright, pandas; print('ok')"

# 2. Configure — daily_runner/config.json is already filled in
#    Key fields:
#      ngdrs.username / ngdrs.password   ← NGDRS citizen login
#      ngdrs.days_back                   ← 30 = sliding monthly window
#      paths.user_data_dir               ← Chrome profile with the login session
#      verification.solver               ← "file" (cron) or "terminal" (local)

# 3. Run the full pipeline (scrape → JSON → commit → push → wait for Pages)
./daily_runner/run_daily.sh
# or, to watch it live:
.venv/bin/python daily_runner/daily_runner.py --update-site --print-json

# 4. If the session has expired, the file solver asks for input:
ls daily_runner/data/state/inputs/awaiting_captcha.json   # marker
open daily_runner/data/screenshots/captcha.png            # read it
echo "AbCd12" > daily_runner/data/state/inputs/captcha.txt

# 5. And for the OTP (SMS arrives on the registered mobile)
echo "12345678" > daily_runner/data/state/inputs/otp.txt
```

The same file protocol works for both captcha and OTP. Sessions normally
last days/weeks, so most cron runs skip login entirely (the runner logs
`session still valid, skipping login`).

## Backfilling history

The site keeps every window it has ever scraped. To fill gaps (or pull a
long history for the month selector):

```bash
# scrape 30-day windows from START to END (inclusive)
.venv/bin/python scripts/backfill_history.py 2026-07-19 2026-11-11 --window 30

# merge every data/rohini_sector28_*.csv into docs/data (deduped by reg no.)
.venv/bin/python scripts/process_data.py
```

`process_data.py` tags each row with its calendar month and writes
`meta.months`, which powers the “Period” selector on the site.

## File layout

```
daily_runner/
├── daily_runner.py        ← main entry; CLI + result writer
├── scraper.py             ← full Playwright pipeline (login → extract → CSV)
├── captcha_solver.py      ← solver interface + File / AI / Combined impls
├── config.json            ← your copy (edit me)
├── config.example.json    ← template with every flag documented
├── CONFIG.md              ← full config reference
├── README.md              ← this file
├── requirements.txt       ← playwright, anthropic
└── .gitignore
```

## Config

See `CONFIG.md` for the full reference. Quick summary:

| Top-level key    | What it does                                            |
| ---------------- | ------------------------------------------------------- |
| `ngdrs`          | credentials, headless/headed, date range, search params |
| `ai`             | AI captcha solver (currently anthropic / Claude)         |
| `verification`   | screenshot sharing + input timeout                      |
| `paths`          | on-disk layout (screenshot, input, raw, csv, …)         |
| `browser`        | Playwright tuning (channel, viewport, args)             |
| `logging`        | where the result dict is written                        |

The runner also accepts `${ENV_VAR}` strings — useful for keeping
passwords and API keys out of the committed file.

## The "ask the user" protocol

The default solver is file-based. When a captcha or OTP is needed:

1. The runner writes a marker JSON to `data/state/inputs/awaiting_<name>.json`
   with the screenshot path, hint, and a deadline.
2. The runner prints a banner to stderr with the path to the image.
3. A base64 sidecar is written next to the screenshot so an external
   system can embed it without reading the binary.
4. The runner polls `data/state/inputs/<name>.txt` once per second.
5. As soon as the file appears with content, the runner reads it,
   deletes both files, and continues.

The exact same protocol works for the OTP step (just use `otp.txt` and
`awaiting_otp.json`).

Any external system can hook into this:

```python
# Example: a chat bot that reads the captcha from S3 and asks the user
import json, time
from pathlib import Path

while True:
    marker = Path("data/state/inputs/awaiting_captcha.json")
    if marker.exists():
        payload = json.loads(marker.read_text())
        # 1. Upload payload["image_path"] to S3
        # 2. Send the user a message with the image URL
        # 3. When they reply, write their answer to payload["write_to"]
        break
    time.sleep(1)
```

## AI captcha (optional)

When `ai.enabled = true` AND `ai.api_key` is set, the runner uses Claude
vision to read the captcha. If the AI fails (e.g. unreadable image), it
falls back to the file-based human prompt so the run never gets stuck.

OTP is **always** asked from the human (AI can't receive an SMS).

For now, keep `ai.enabled = false` and just type the captcha yourself.

## Result dict

Every run writes its result to `data/state/last_run.json` and (with
`--print-json`) prints it to stdout. The shape is:

```json
{
  "run_id": "a1b2c3d4e5f6",
  "status": "success",                  // success | error | need_input
  "started_at":  "2026-07-20T10:30:00",
  "finished_at": "2026-07-20T10:33:42",
  "days_back": 1,
  "date_from": "2026-07-19",
  "date_to":   "2026-07-20",
  "headless": true,
  "solver":   "file",                   // or "ai-anthropic" or "combined"
  "captcha_image":     "/abs/path/captcha.png",
  "captcha_image_b64": "iVBORw0KGgo…",  // for Lambda responses
  "rows_extracted": 90,
  "csv_path":  "/abs/path/ngdrs_20260719_to_20260720.csv",
  "json_path": "/abs/path/ngdrs_search_latest.json",
  "error":     null,
  "error_type":null
}
```

## Exit codes

- `0` success
- `1` generic error
- `2` bad config (missing file, malformed JSON)
- `3` captcha / OTP needed (timed out waiting for input)
- `4` scrape ok, deploy failed

## Daily cron (macOS)

Two jobs: a **daily scrape** and a **session keepalive**.

```cron
# crontab -e
# keep the NGDRS session warm (offset so it never overlaps the 09:30 scrape)
5,15,25,35,45,55 * * * * /Users/tanishmittal/codes/Property/Rohini_prop_scrape/daily_runner/run_keepalive.sh
# refresh the site at 09:30
30 9 * * * /Users/tanishmittal/codes/Property/Rohini_prop_scrape/daily_runner/run_daily.sh
```

The wrappers handle PATH, logging, and the working directory:

- scrape log: `daily_runner/data/state/cron-YYYY-MM-DD.log`
- keepalive log: `daily_runner/data/state/keepalive.log`
- result dict: `daily_runner/data/state/last_run.json`

### How the login is automated

NGDRS has no OAuth/JWT refresh token — login issues one httpOnly `NGDRS`
cookie that identifies a server-side session (the browser-side expiry is
~15 minutes). `session_store.py` automates it:

1. After any successful login the cookie is saved to
   `data/state/session.json`.
2. Every scrape injects that cookie into Playwright (with `expires=-1`), so
   the SMS OTP is normally never needed.
3. The cookie rotates when the server reissues it, so `run_keepalive.sh`
   opens the real Chrome profile every 10 minutes, visits `/welcome`,
   refreshes and re-saves the cookie — which also keeps the server-side
   idle timer from expiring.

If the server session really dies (portal restart, long machine downtime),
the keepalive clears the store; the next scrape falls back to the normal
captcha + OTP flow, or to `otp_command` below.

macOS also supports launchd if you prefer it over cron:

```xml
<!-- ~/Library/LaunchAgents/com.rohini.pulse.daily.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.rohini.pulse.daily</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/tanishmittal/codes/Property/Rohini_prop_scrape/daily_runner/run_daily.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
  <key>RunAtLoad</key><false/>
</dict></plist>
```

Add a second agent (or cron line) pointing at `run_keepalive.sh` with a
`StartInterval` of 600 seconds.

### Fully unattended OTP

The only human step is the SMS OTP when a session expires. If you have an
SMS forwarder (Android app, IMAP-to-command, Twilio webhook, …) point the
runner at it:

```json
"verification": {
  "otp_command": "termux-sms-list -l 1 | jq -r '.[0].body' | grep -oE '[0-9]{6,8}' | head -1"
}
```

The command's first stdout line is used as the OTP; if it fails or prints
nothing, the runner falls back to the file protocol and exits `3` when the
timeout hits, so cron can alert you.

## Later: AWS Lambda

The same code is Lambda-deployable. You'll need:

- A Lambda layer with the `playwright` Python wheel + Chromium binary
  (or use the `playwright-aws-lambda` community layer)
- An external system (chat bot, S3 uploader, etc.) to read the
  `awaiting_*.json` markers and write the value files back
- The `paths.*` set to `/tmp/...` (the only writable directory)

The solver abstraction is already in place — drop in a custom
`CaptchaSolver` subclass and `create_solver` will return it.

## Determinism guarantees

- The captcha/OTP flow is the same protocol regardless of who answers
  (human, AI, or external system), so a re-run is fully resumable.
- The date range is computed from `days_back` + `date.today()`, so the
  same config run on the same day always scrapes the same window.
- The result dict is always written to the same path with the same
  shape, so the integrator's downstream code never has to special-case.
- All on-disk paths are configurable, so the same code works locally,
  in cron, and in Lambda without changes.
