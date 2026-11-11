"""Persist and refresh the NGDRS session cookie.

The portal has no OAuth/JWT refresh token. Login sets a single httpOnly
`NGDRS` cookie that identifies a server-side session; the browser-side
expiry is ~15 minutes, but the server keeps the session alive as long as it
is used.

Strategy:
  * after a successful login, save the cookie under data/state/session.json
  * inject it into Playwright on every run (with expires=-1 so a stale
    client-side expiry does not discard it) → scrapes skip the SMS OTP
  * a keep-alive job (`run_keepalive.sh`) pings /welcome every 10 min so the
    server-side idle timer never fires

If the server session really dies (portal restart, absolute timeout, or the
machine was off), `probe()` returns False, the stored cookie is cleared, and
the next scrape falls back to the normal captcha + OTP flow.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
SESSION_PATH = _HERE / "data" / "state" / "session.json"
WELCOME_URL = "https://ngdrs.delhi.gov.in/NGDRS_DL/Citizenentry/welcome"
COOKIE_NAME = "NGDRS"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)


def load() -> Optional[dict[str, Any]]:
    """Return the stored session record, or None."""
    try:
        return json.loads(SESSION_PATH.read_text())
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[session] ignoring unreadable {SESSION_PATH}: {exc!r}\n")
        return None


def save_from_context(ctx) -> Optional[dict[str, Any]]:
    """Copy the NGDRS cookie out of a Playwright BrowserContext."""
    try:
        cookies = ctx.cookies()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[session] could not read cookies: {exc!r}\n")
        return None

    for c in cookies:
        if c.get("name") != COOKIE_NAME:
            continue
        rec = {
            "value": c["value"],
            "domain": c.get("domain", "ngdrs.delhi.gov.in"),
            "path": c.get("path", "/"),
            "httpOnly": bool(c.get("httpOnly", True)),
            "secure": bool(c.get("secure", True)),
            "sameSite": c.get("sameSite", "Lax"),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "browser_expires": c.get("expires"),
        }
        SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(json.dumps(rec, indent=2))
        sys.stderr.write(f"[session] stored {COOKIE_NAME} cookie ({SESSION_PATH})\n")
        return rec

    sys.stderr.write(f"[session] no {COOKIE_NAME} cookie in the browser context\n")
    return None


def as_playwright_cookie(rec: dict[str, Any]) -> dict[str, Any]:
    """Shape a stored record for BrowserContext.add_cookies().

    expires=-1 makes it a session cookie in the browser, so an expired
    client-side timestamp never causes the browser to drop a session that
    the server still accepts.
    """
    return {
        "name": COOKIE_NAME,
        "value": rec["value"],
        "domain": rec.get("domain", "ngdrs.delhi.gov.in"),
        "path": rec.get("path", "/"),
        "httpOnly": bool(rec.get("httpOnly", True)),
        "secure": bool(rec.get("secure", True)),
        "sameSite": rec.get("sameSite", "Lax"),
        "expires": -1,
    }


def probe(value: str, *, timeout_s: int = 30) -> bool:
    """True if the portal still treats this cookie as authenticated."""
    req = urllib.request.Request(
        WELCOME_URL,
        headers={"Cookie": f"{COOKIE_NAME}={value}", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if exc.fp else ""
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[session] probe failed: {exc!r}\n")
        return False

    authed = "logout" in body.lower() and 'id="captcha"' not in body
    return authed


def clear() -> None:
    try:
        SESSION_PATH.unlink()
    except FileNotFoundError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    rec = load()

    if "--clear" in args:
        clear()
        print("stored session cleared")
        return 0

    if not rec:
        print("no stored session — run the daily runner once to log in")
        return 3

    ok = probe(rec["value"])
    saved = rec.get("saved_at", "?")
    if ok:
        print(f"session alive (stored {saved})")
        return 0

    print(f"session expired (stored {saved}) — cleared; next run will log in")
    clear()
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
