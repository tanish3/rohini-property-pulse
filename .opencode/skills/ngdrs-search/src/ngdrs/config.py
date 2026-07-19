"""Centralized configuration for the NGDRS workflow.

All selectors, URLs, env-var names, and file paths live here so the rest of
the code stays declarative. Override anything via env vars without editing
code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # .opencode/skills/ngdrs-search
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SHOTS_DIR = DATA_DIR / "screenshots"
STATE_DIR = DATA_DIR / "state"
for d in (DATA_DIR, RAW_DIR, SHOTS_DIR, STATE_DIR):
    d.mkdir(parents=True, exist_ok=True)


def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val  # type: ignore[return-value]


@dataclass(frozen=True)
class URLs:
    base: str = "https://ngdrs.delhi.gov.in/"
    login: str = "https://ngdrs.delhi.gov.in/NGDRS_DL/Citizenentry/citizenlogin"
    search: str = "https://ngdrs.delhi.gov.in/NGDRS_DL/DLSroSearch/srosearch"
    welcome: str = "https://ngdrs.delhi.gov.in/NGDRS_DL/Citizenentry/welcome"


@dataclass(frozen=True)
class Credentials:
    user_env: str = "NGD_USER"
    pass_env: str = "NGD_PASS"
    otp_env: str = "NGD_OTP"  # non-interactive mode; otherwise prompted


@dataclass(frozen=True)
class Paths:
    chrome_profile: Path = ROOT / ".chrome-profile"
    state_dir: Path = STATE_DIR
    state_file: Path = STATE_DIR / "workflow_state.json"
    inputs_dir: Path = STATE_DIR / "inputs"
    last_csv: Path = DATA_DIR / "ngdrs_search_latest.csv"
    last_json: Path = RAW_DIR / "ngdrs_search_latest.json"


@dataclass(frozen=True)
class Selectors:
    # login form
    username: str = "input[placeholder='Enter Username']"
    password: str = "input[placeholder='Enter Password']"
    captcha: str = "input[placeholder='Enter Captcha']"
    captcha_img: str = "img[alt*='aptcha' i], img[src*='aptcha' i], #captcha_image"
    get_otp: str = "button:has-text('Get OTP')"
    otp: str = "input[placeholder='Enter OTP']"
    login_btn: str = "button:has-text('Login'):not(:has-text('Citizen'))"

    # navigation
    toggle_nav: str = "button[aria-label*='oggle' i], .navbar-toggle, button:has-text('Toggle navigation')"
    esearch_link: str = "a:has-text('E-Search')"
    search_subitem: str = "a:has-text('Search')"

    # search form
    search_by: str = "select[name*='Search' i]:not([name*='table' i])"
    district: str = "select[name*='district_id' i]"
    date_from: str = "input[placeholder='Search For Date']"
    date_to: str = "input[placeholder='To']"
    taluka: str = "select[name*='taluka_id' i]"
    village: str = "select[name*='village_id' i]"
    attribute: str = "select[name*='attribute_id' i]"
    attribute_value: str = "input[placeholder='Plot']"
    search_btn: str = "button:has-text('Search')"

    # results
    table: str = "#tableparty"
    page_length: str = "select[name='tableparty_length']"


@dataclass(frozen=True)
class Defaults:
    district: str = "North"
    taluka: str = "Alipur"
    village: str = "Rohini Sector-28"
    attribute: str = "Plot Number"
    search_by: str = "Property Details"


def get_search_params(
    *,
    district: str | None = None,
    taluka: str | None = None,
    village: str | None = None,
    attribute: str | None = None,
    search_by: str | None = None,
) -> dict[str, str]:
    """Resolve search params with priority: explicit > env > default."""
    return {
        "search_by": search_by or env("NGD_SEARCH_BY", CONFIG.defaults.search_by),
        "district": district or env("NGD_DISTRICT", CONFIG.defaults.district),
        "taluka": taluka or env("NGD_TALUKA", CONFIG.defaults.taluka),
        "village": village or env("NGD_VILLAGE", CONFIG.defaults.village),
        "attribute": attribute or env("NGD_ATTRIBUTE", CONFIG.defaults.attribute),
    }


@dataclass(frozen=True)
class Timing:
    page_load_ms: int = 30000
    short_ms: int = 1500
    long_ms: int = 3000
    human_typing_min_ms: int = 80
    human_typing_max_ms: int = 180


@dataclass(frozen=True)
class Config:
    urls: URLs = field(default_factory=URLs)
    creds: Credentials = field(default_factory=Credentials)
    paths: Paths = field(default_factory=Paths)
    sel: Selectors = field(default_factory=Selectors)
    defaults: Defaults = field(default_factory=Defaults)
    timing: Timing = field(default_factory=Timing)
    headless: bool = False
    channel: str = "chrome"


CONFIG = Config()
