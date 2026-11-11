# Config Reference

The runner loads `config.json` once at startup. Every value can be
overridden via an environment variable using the `${VAR}` / `$VAR`
syntax in the JSON file.

## Value source map

This is where every value in `config.json` comes from, so you know what
to keep and what to fill in.

| Key                       | Source                                                          | Status                  |
| ------------------------- | --------------------------------------------------------------- | ----------------------- |
| `ngdrs.username`          | your citizen login at [ngdrs.delhi.gov.in](https://ngdrs.delhi.gov.in) | **REPLACE** — or set `$NGD_USER` |
| `ngdrs.password`          | your citizen password                                            | **REPLACE** — or set `$NGD_PASS` |
| `ngdrs.headless`          | local debug preference                                           | `false` (set `true` for cron/lambda) |
| `ngdrs.channel`           | local install: `chrome` (system) or `chromium` (bundled)         | `chrome`                |
| `ngdrs.days_back`         | how many days back to scrape (1 = daily)                         | `1`                     |
| `ngdrs.district`          | e-Search dropdown — fixed by NGDRS                               | `North`                 |
| `ngdrs.taluka`            | e-Search dropdown                                                | `Alipur`                |
| `ngdrs.village`           | e-Search dropdown                                                | `Rohini Sector-28`      |
| `ngdrs.attribute`         | e-Search "Property Attribute" dropdown                           | `Plot Number`           |
| `ngdrs.search_by`         | e-Search "Search By" dropdown                                    | `Property Details`      |
| `ai.enabled`              | master switch for AI captcha                                     | `false`                 |
| `ai.api_key`              | your [Anthropic](https://console.anthropic.com) API key          | **REPLACE** — or set `$ANTHROPIC_API_KEY` |
| `ai.model`                | Claude model id                                                  | `claude-sonnet-4-5`     |
| `verification.*`          | screenshot + timeout tuning (rarely changed)                     | sane defaults           |
| `paths.*`                 | on-disk layout                                                   | sane defaults           |
| `browser.*`               | Playwright tuning (rarely changed)                               | sane defaults           |
| `logging.log_file`        | where the result dict is written                                 | `data/state/last_run.json` |
| `deploy.enabled`          | enable the post-scrape commit+push step                          | `false` (set `true` to use `--update-site`) |
| `deploy.git_user`         | commit author — auto-filled from `git log`: **Tanish Mittal**   | from repo               |
| `deploy.git_email`        | commit author — auto-filled from `git log`: **tanishmittal@example.com** | from repo — verify not a placeholder |
| `deploy.commit_message_template` | pattern for the auto-commit message                       | `data: daily scrape {date} ({rows} rows)` |
| `deploy.pages_build_timeout_s`   | max seconds to wait for the GitHub Pages build             | `180`                   |

### How the deploy values were filled

```bash
$ git log -1 --format='name:  %an%nemail: %ae'
name:  Tanish Mittal
email: tanishmittal@example.com

$ git remote get-url origin
https://github.com/tanish3/rohini-property-pulse.git
```

If `tanishmittal@example.com` is a placeholder (it looks like one — `example.com` is a reserved domain), set your real email with:

```bash
git config user.email "your-real-email@example.com"
```

…or just edit `deploy.git_email` in `config.json`. The `deploy_site.py` script uses these values for the commit author when `--update-site` is active.

### How the site login is set (separate from this config)

The site itself (`docs/assets/auth.js`) is gated by a SHA-256 hash:

```js
username:    "admin"
passwordHash: "5479dabd460644b52d11151c796827307add8c95f248f98183acb31ca51cd98f"
```

The default password is **`rohini2026`**. To change it:

```bash
.venv/bin/python ../.opencode/skills/ngdrs-search/scripts/generate_password_hash.py
# copy the printed hash into docs/assets/auth.js → AUTH_CONFIG.passwordHash
```

## Top-level fields

### `ngdrs`
The actual NGDRS credentials and search parameters. Every value except
`username` and `password` has a sensible default.

| key           | meaning                                                      | default              |
| ------------- | ------------------------------------------------------------ | -------------------- |
| `username`    | citizen login username                                       | **required**         |
| `password`    | citizen login password                                       | **required**         |
| `headless`    | `true` = Playwright headless, `false` = visible browser      | `true`               |
| `channel`     | `chrome` (system) or `chromium` (bundled)                    | `chrome`             |
| `days_back`   | scrape the last N days (use 1 for daily)                     | `30`                 |
| `district`    | e-Search district dropdown                                   | `North`              |
| `taluka`      | e-Search taluka dropdown                                     | `Alipur`             |
| `village`     | e-Search village dropdown                                    | `Rohini Sector-28`   |
| `attribute`   | e-Search property attribute (e.g. `Plot Number`)             | `Plot Number`        |
| `search_by`   | e-Search "Search By" mode                                    | `Property Details`   |

You can also set the username/password via env vars `NGD_USER` and
`NGD_PASS`. Use that for CI / shared environments.

### `ai`
When `enabled=true` AND `api_key` is non-empty, the captcha is read by
Anthropic Claude vision. OTP always falls back to a human (AI cannot
receive an SMS). Leave `enabled=false` until you have a key wired up.

| key                 | meaning                                              | default              |
| ------------------- | ---------------------------------------------------- | -------------------- |
| `enabled`           | master switch                                        | `false`              |
| `provider`          | `anthropic` (only one supported)                     | `anthropic`          |
| `api_key`           | API key (do **not** commit; use env / secret store)  | `""`                 |
| `model`             | Claude model id                                      | `claude-sonnet-4-5`  |
| `max_tokens`        | max tokens for the vision reply                      | `64`                 |
| `fallback_on_failure`| if AI fails, ask the human instead                  | `true`               |

### `verification`
How the captcha image is shared with the user and how long to wait for
input. Tweaking these is the main way to integrate the runner with an
external system (chat bot, S3 watcher, etc.).

| key                       | meaning                                                                                          | default |
| ------------------------- | ------------------------------------------------------------------------------------------------ | ------- |
| `screenshot_on_captcha`   | save the captcha image to disk                                                                    | `true`  |
| `share_screenshot_path`   | print the absolute path to the screenshot in the stderr banner                                    | `true`  |
| `share_screenshot_base64` | also write a `.b64` sidecar + embed the data-URL in the result dict (so a Lambda can return it)   | `true`  |
| `input_timeout_seconds`   | max seconds to wait for a captcha / OTP value file to appear before raising `TimeoutError`        | `300`   |
| `poll_interval_seconds`   | how often the file watcher checks for the value file                                              | `1.0`   |

### `paths`
All on-disk locations. On AWS Lambda, set these to `/tmp/...` (the only
writable directory). The runner auto-creates them.

| key              | meaning                                                                                  | default                          |
| ---------------- | ---------------------------------------------------------------------------------------- | -------------------------------- |
| `screenshot_dir` | where captcha images land                                                                | `data/screenshots`               |
| `input_dir`      | where the marker + value files live (`awaiting_captcha.json`, `captcha.txt`, etc.)       | `data/state/inputs`              |
| `state_file`     | reserved for future resumable state                                                      | `data/state/workflow_state.json` |
| `raw_dir`        | where the raw extracted JSON is written before CSV export                                | `data/raw`                       |
| `csv_dir`        | where the date-stamped CSV ends up                                                        | `data`                           |
| `user_data_dir`  | persistent Chrome profile (cookies, login session)                                       | `data/user_data`                 |

### `browser`
Playwright-specific tuning. Most people won't need to touch this.

| key               | meaning                                                                                | default            |
| ----------------- | -------------------------------------------------------------------------------------- | ------------------ |
| `user_data_dir`   | persistent Chrome profile path                                                         | `data/user_data`   |
| `viewport_width`  | viewport width (headless only)                                                          | `1440`             |
| `viewport_height` | viewport height (headless only)                                                         | `900`              |
| `channel`         | `chrome` (system) or `chromium` (bundled) — overrides `ngdrs.channel`                   | `chrome`           |
| `args`            | extra Chromium command-line args                                                        | `["--start-maximized"]` |

### `logging`
Where the result dict is written so the integrator can read it.

| key        | meaning                                                       | default                    |
| ---------- | ------------------------------------------------------------- | -------------------------- |
| `level`    | log verbosity (currently informational only)                  | `INFO`                     |
| `log_file` | path to the JSON result of the last run                       | `data/state/last_run.json` |

## Environment variable substitution

Any string value in the JSON can use `${ENV_VAR}` or `$ENV_VAR`. The
runner substitutes them from `os.environ` at load time. Unknown vars
are left as-is so typos don't silently turn into empty strings.

```jsonc
{
  "ngdrs": {
    "username": "${NGD_USER}",          // from $NGD_USER
    "password": "${NGD_PASS}"           // from $NGD_PASS
  },
  "ai": {
    "api_key": "${ANTHROPIC_API_KEY}"   // from $ANTHROPIC_API_KEY
  }
}
```

This is the recommended way to keep secrets out of the committed file.

## How the "ask the user" flow works

When the runner hits a captcha:

1. Playwright takes a screenshot of the captcha image and saves it to
   `<screenshot_dir>/captcha.png`.
2. The runner writes a structured marker:
   ```json
   {
     "input": "captcha",
     "hint": "Read the captcha image and write the characters",
     "image_path": "/abs/path/to/captcha.png",
     "created_at": "2026-07-20T10:30:00",
     "deadline_at": "2026-07-20T10:35:00",
     "run_id": "a1b2c3d4e5f6",
     "write_to": "/abs/path/to/captcha.txt"
   }
   ```
   to `<input_dir>/awaiting_captcha.json`.
3. A base64 sidecar is written next to the PNG so an external system can
   embed the image without a file read.
4. The banner is printed to stderr:
   ```
   ==================================================================
   [daily-runner] WAITING FOR 'captcha'
           marker:   /…/data/state/inputs/awaiting_captcha.json
           write to: /…/data/state/inputs/captcha.txt
           image:    /…/data/screenshots/captcha.png
           (open the file in any image viewer to read the captcha)
           hint:     Read the captcha image and write the characters
           deadline: 2026-07-20T10:35:00
           base64:   data:image/png;base64,iVBORw0KGgo…  (full: /…/captcha.png.b64)
   ==================================================================
   ```
5. The runner polls `<input_dir>/captcha.txt` once per second.
6. As soon as the file appears with content, the runner reads it,
   deletes both the marker and the value file (so re-runs don't reuse
   stale values), and continues.
7. The OTP flow is identical but uses `awaiting_otp.json` / `otp.txt`.

The exact same protocol works for the OTP step.

## Result dict schema

Every run writes its result to `logging.log_file` and (with
`--print-json`) prints it to stdout.

```jsonc
{
  "run_id": "a1b2c3d4e5f6",
  "status": "success",                 // "success" | "error" | "need_input"
  "started_at": "2026-07-20T10:30:00",
  "finished_at": "2026-07-20T10:33:42",
  "days_back": 1,
  "date_from": "2026-07-19",
  "date_to":   "2026-07-20",
  "headless": true,
  "solver":   "file",                  // or "ai-anthropic" or "combined"
  "captcha_image":     "/…/captcha.png",
  "captcha_image_b64": "iVBORw0KGgo…",  // omitted in --print-json
  "rows_extracted": 90,
  "csv_path":  "/…/ngdrs_20260719_to_20260720.csv",
  "json_path": "/…/ngdrs_search_latest.json",
  "error":     null,
  "error_type":null
}
```

`status` values:
- `success`     — full pipeline finished
- `need_input`  — captcha/OTP timed out; the marker is still on disk.
                  Resumable: re-running with the same config picks up
                  from the same step (state is preserved in the file
                  protocol — the previous value file is just empty).
- `error`       — any other failure (network, bad creds, etc.)

## Exit codes

- `0` — success
- `1` — generic error
- `2` — bad config (missing file, malformed JSON)
- `3` — captcha/OTP timed out (so a cron can distinguish)
