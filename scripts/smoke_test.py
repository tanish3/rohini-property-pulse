"""Test the new Leaflet maps by visiting each route and checking
that the map container is populated (Leaflet attaches .leaflet-container class).
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = Path("/tmp/rpp_screens2")
OUT.mkdir(exist_ok=True)

routes = [
    ("/", "overview"),
    ("/#/sector/28", "sector"),
    ("/#/sector/28/pocket/C-2", "pocket_c2"),
    ("/#/sector/28/pocket/GH-1", "pocket_gh1"),
    ("/#/sector/28/all", "list"),
]

errors = []


def login(page):
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_selector("#login-username", timeout=5000)
    page.fill("#login-username", "admin")
    page.fill("#login-password", "rohini2026")
    page.click("button.login-submit")
    page.wait_for_selector("#app-root:not([hidden])", timeout=5000)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for viewport_name, w, h in [("mobile", 390, 844), ("desktop", 1280, 800)]:
        print(f"\n=== {viewport_name} ({w}x{h}) ===")
        ctx = browser.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page()
        console_errs = []
        page.on("console", lambda m: console_errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errs.append(str(e)))

        # Authenticate once
        login(page)
        print("  logged in")

        for route, name in routes:
            print(f"route {route} ({name})")
            page.goto(BASE + route, wait_until="networkidle")
            # Wait for Leaflet tiles to load
            try:
                page.wait_for_selector(".leaflet-container", timeout=10000)
                print(f"  ✓ Leaflet container present")
            except Exception as e:
                if name in ("overview", "sector"):
                    errors.append(f"{name}: leaflet container missing ({e})")
                    print(f"  ✗ {e}")
            # Check that the tile layer loaded some images
            tile_count = page.evaluate("document.querySelectorAll('.leaflet-tile-loaded').length")
            print(f"  tiles loaded: {tile_count}")
            if tile_count == 0 and name in ("overview", "sector"):
                errors.append(f"{name}: no OSM tiles loaded")
            page.screenshot(path=str(OUT / f"{viewport_name}_{name}.png"), full_page=True)

        if console_errs:
            print(f"  console errors: {console_errs[:5]}")
        ctx.close()
    browser.close()

if errors:
    print("\nFAILED:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("\nAll checks passed. Screenshots in", OUT)
