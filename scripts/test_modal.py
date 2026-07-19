"""Test the transaction detail modal."""
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
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
    page = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)

    login(page)
    print("✓ logged in")

    # Go to the all-transactions list
    page.goto(BASE + "/#/sector/28/all", wait_until="networkidle")
    page.wait_for_selector("table.tx-table tbody tr", timeout=10000)
    rows = page.query_selector_all("table.tx-table tbody tr.tx-row")
    print(f"  found {len(rows)} clickable rows")
    if not rows:
        errors.append("no clickable rows found")
        sys.exit(1)

    # Click the first row
    first_row = rows[0]
    first_row.click()
    page.wait_for_selector("#tx-detail-modal", timeout=3000)
    print("✓ modal opened")

    # Check modal content
    title = page.text_content("#tx-detail-modal h2")
    print(f"  title: {title!r}")
    sections = page.query_selector_all("#tx-detail-modal .rpp-modal-section h3")
    section_names = [s.text_content() for s in sections]
    print(f"  sections: {section_names}")
    if "Parties" not in section_names or "Property" not in section_names or "Description (parsed)" not in section_names:
        errors.append(f"missing sections: {section_names}")

    # Test Escape to close
    page.keyboard.press("Escape")
    page.wait_for_selector("#tx-detail-modal", state="detached", timeout=2000)
    print("✓ Escape closes modal")

    # Test clicking row 2
    rows[1].click()
    page.wait_for_selector("#tx-detail-modal", timeout=3000)
    title2 = page.text_content("#tx-detail-modal h2")
    print(f"  row 2 title: {title2!r}")
    if title == title2:
        errors.append("row 2 shows same title as row 1")

    # Test backdrop click (top-left corner where the modal isn't covering)
    page.click(".rpp-modal-backdrop", position={"x": 5, "y": 5})
    page.wait_for_selector("#tx-detail-modal", state="detached", timeout=2000)
    print("✓ backdrop click closes modal")

    # Test mobile card click
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(BASE + "/#/sector/28/all", wait_until="networkidle")
    page.wait_for_selector(".tx-list .tx-card", timeout=10000)
    cards = page.query_selector_all(".tx-list .tx-card")
    print(f"\n[mobile] {len(cards)} cards")
    cards[0].click()
    page.wait_for_selector("#tx-detail-modal", timeout=3000)
    page.screenshot(path="/tmp/modal_mobile.png", full_page=False)
    print("✓ mobile card click opens modal")
    page.keyboard.press("Escape")

    browser.close()

if errors:
    print(f"\nFAILED: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("\nAll checks passed.")
