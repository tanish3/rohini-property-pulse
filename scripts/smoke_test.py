"""Headless smoke test for the static site.
- Loads each route in a mobile + desktop viewport
- Verifies key elements render
- Captures screenshots for visual review
- Asserts no console errors
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path("/tmp/rpp_screens")
OUT.mkdir(exist_ok=True)

routes = [
    ("/", "overview"),
    ("/#/sector/28", "sector"),
    ("/#/sector/28/pocket/C-2", "pocket_c2"),
    ("/#/sector/28/pocket/GH-1", "pocket_gh1"),
    ("/#/sector/28/all", "list"),
]

errors = []


def check(page, label, route_name):
    page.wait_for_load_state("networkidle")
    body = page.inner_text("body")
    title = page.title()
    print(f"  {label}: title={title!r}, body_len={len(body)}")
    # Check no error placeholder
    if "Failed to load data" in body:
        errors.append(f"{label}: data load failure")
    # Check view loaded (no "Loading…" left)
    if body.strip().endswith("Loading…"):
        errors.append(f"{label}: stuck on loading")
    # Check stat cards rendered
    if route_name == "overview" and "TOTAL REGISTRATIONS" not in body.upper():
        errors.append(f"{label}: missing total registrations card")
    if route_name == "sector" and "Pocket Map" not in body:
        errors.append(f"{label}: missing pocket map section")
    if route_name.startswith("pocket") and "Transactions" not in body:
        errors.append(f"{label}: missing transactions section")
    if route_name == "list" and "All Sector 28" not in body:
        errors.append(f"{label}: missing list heading")
    # Check no SVG parse errors (look for error attribute)
    svgs = page.query_selector_all("svg")
    for s in svgs:
        if s.get_attribute("data-error"):
            errors.append(f"{label}: svg parse error")


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for viewport_name, w, h in [("mobile", 390, 844), ("desktop", 1280, 800)]:
        print(f"\n=== {viewport_name} ({w}x{h}) ===")
        ctx = browser.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page()
        console_errs = []
        page.on("console", lambda m: console_errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errs.append(str(e)))

        for route, name in routes:
            print(f"route {route} ({name})")
            page.goto(BASE + route)
            check(page, name, name)
            page.screenshot(path=str(OUT / f"{viewport_name}_{name}.png"), full_page=True)

        if console_errs:
            print(f"  console errors: {console_errs}")
            errors.extend([f"{viewport_name}: {e}" for e in console_errs])
        ctx.close()
    browser.close()

if errors:
    print("\nFAILED:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("\nAll checks passed. Screenshots in", OUT)
