"""Extract the e-Search results table to structured JSON.

The site uses a custom DataTables layout where the Property Details and Party
columns contain nested sub-tables, so a simple header->row zip won't work.
This module normalizes each main row into a flat dict.
"""
from __future__ import annotations

import json
import re
from typing import Any

from playwright.sync_api import BrowserContext, Page

from .browser import active_page, log, screenshot
from .config import CONFIG
from .state import State

_PARTY_RE = re.compile(
    r"<b>([^<]+)</b>\s*\(([^)]+)\)\s*<br>\s*([^<]+)", re.IGNORECASE
)
_DETAILS_RE = re.compile(r"Property ID:\s*(\d+)")
_DOC_ID_RE = re.compile(r"details\('([^']+)'")


def _normalize_row(tr, idx: int) -> dict[str, Any]:
    tds = tr.query_selector_all(":scope > td")
    if len(tds) < 7:
        return {}

    reg_no = (tds[1].text_content() or "").strip()
    reg_date = (tds[2].text_content() or "").strip()

    seller_name = seller_addr = ""
    purchaser_name = purchaser_addr = ""
    party_tbl = tds[3].query_selector("table")
    if party_tbl:
        for pr in party_tbl.query_selector_all("tr"):
            cells = pr.query_selector_all("td")
            if not cells:
                continue
            html = cells[0].inner_html() if hasattr(cells[0], "inner_html") else ""
            m = _PARTY_RE.search(html)
            if not m:
                continue
            name, role, addr = m.group(1).strip(), m.group(2).lower(), m.group(3).strip()
            if "seller" in role:
                seller_name, seller_addr = name, addr
            elif "purchaser" in role:
                purchaser_name, purchaser_addr = name, addr

    prop_cell_text = tds[4].text_content() or ""
    m = _DETAILS_RE.search(prop_cell_text)
    property_id = m.group(1) if m else ""

    village = prop_desc = plot_no = upic = ""
    prop_tbl = tds[4].query_selector("table")
    if prop_tbl:
        for pr in prop_tbl.query_selector_all("tr"):
            cells = pr.query_selector_all("td")
            if len(cells) != 2:
                continue
            key = (cells[0].text_content() or "").strip().lower()
            val = (cells[1].text_content() or "").strip()
            if key == "village name":
                village = val
            elif key == "property description":
                prop_desc = val
            elif "plot number" in key:
                plot_no = val
            elif "upic" in key:
                upic = val

    doc_id = ""
    link = tr.query_selector("a[onclick*='details(']")
    if link:
        m = _DOC_ID_RE.search(link.get_attribute("onclick") or "")
        if m:
            doc_id = m.group(1)

    article = (tds[5].text_content() or "").strip()
    office = (tds[6].text_content() or "").strip()

    return {
        "sno": idx + 1,
        "document_id": doc_id,
        "registration_no": reg_no,
        "registration_date": reg_date,
        "seller_name": seller_name,
        "seller_address": seller_addr,
        "purchaser_name": purchaser_name,
        "purchaser_address": purchaser_addr,
        "property_id": property_id,
        "village_name": village,
        "property_description": prop_desc,
        "plot_number": plot_no,
        "upic_number": upic,
        "article": article,
        "registration_office": office,
    }


def _select_all_rows(page: Page) -> None:
    sel = page.locator(CONFIG.sel.page_length).first
    sel.wait_for(state="visible", timeout=CONFIG.timing.page_load_ms)
    sel.select_option(value="-1")
    page.wait_for_timeout(CONFIG.timing.long_ms)


def _scrape_rows(page: Page) -> list[dict[str, Any]]:
    raw = page.evaluate(
        """() => {
          const table = document.querySelector('#tableparty');
          if (!table) return [];
          return Array.from(table.querySelectorAll('tbody tr'))
            .filter(tr => tr.querySelector('.dropdown-toggle'))
            .map(tr => {
              const tds = tr.querySelectorAll(':scope > td');
              if (tds.length < 7) return null;
              const regNo = (tds[1].textContent || '').trim();
              const regDate = (tds[2].textContent || '').trim();
              const pt = tds[3].querySelector('table');
              const partyRows = pt ? Array.from(pt.querySelectorAll('tr')).map(pr => pr.querySelector('td')?.innerHTML || '') : [];
              const pd = tds[4].querySelector('table');
              const propRows = pd ? Array.from(pd.querySelectorAll('tr')).map(pr => {
                const c = pr.querySelectorAll('td');
                return c.length === 2 ? [(c[0].textContent||'').trim(), (c[1].textContent||'').trim()] : null;
              }).filter(Boolean) : [];
              const link = tr.querySelector("a[onclick*='details(']");
              const m = link ? (link.getAttribute('onclick')||'').match(/details\\('([^']+)'/) : null;
              const propText = tds[4].textContent || '';
              const pid = (propText.match(/Property ID:\\s*(\\d+)/) || [])[1] || '';
              return {
                reg_no: regNo,
                reg_date: regDate,
                party_html: partyRows,
                prop_text: propText,
                prop_id: pid,
                prop_kv: propRows,
                doc_id: m ? m[1] : '',
                article: (tds[5].textContent||'').trim(),
                office: (tds[6].textContent||'').trim(),
              };
            }).filter(Boolean);
        }"""
    )
    rows: list[dict[str, Any]] = []
    for i, r in enumerate(raw):
        seller_name = seller_addr = ""
        purchaser_name = purchaser_addr = ""
        for html in r["party_html"]:
            m = _PARTY_RE.search(html)
            if not m:
                continue
            name, role, addr = m.group(1).strip(), m.group(2).lower(), m.group(3).strip()
            if "seller" in role:
                seller_name, seller_addr = name, addr
            elif "purchaser" in role:
                purchaser_name, purchaser_addr = name, addr

        village = prop_desc = plot_no = upic = ""
        for key, val in r["prop_kv"]:
            k = key.lower()
            if k == "village name":
                village = val
            elif k == "property description":
                prop_desc = val
            elif "plot number" in k:
                plot_no = val
            elif "upic" in k:
                upic = val

        rows.append(
            {
                "sno": i + 1,
                "document_id": r["doc_id"],
                "registration_no": r["reg_no"],
                "registration_date": r["reg_date"],
                "seller_name": seller_name,
                "seller_address": seller_addr,
                "purchaser_name": purchaser_name,
                "purchaser_address": purchaser_addr,
                "property_id": r["prop_id"],
                "village_name": village,
                "property_description": prop_desc,
                "plot_number": plot_no,
                "upic_number": upic,
                "article": r["article"],
                "registration_office": r["office"],
            }
        )
    return rows


def extract(ctx: BrowserContext, state: State) -> list[dict[str, Any]]:
    if state.is_done("table_extracted"):
        log("extract: already done; skipping")
        path = CONFIG.paths.last_json
        return json.loads(path.read_text()) if path.exists() else []

    page = active_page(ctx)
    table = page.locator(CONFIG.sel.table).first
    table.wait_for(state="visible", timeout=CONFIG.timing.page_load_ms)
    _select_all_rows(page)
    state.record("extract_screenshot", str(screenshot(page, "extract_all")))

    rows = _scrape_rows(page)
    if not rows:
        raise RuntimeError("No rows extracted - check that 'All' was applied")

    CONFIG.paths.last_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    state.record("json_path", str(CONFIG.paths.last_json))
    state.mark("table_extracted")
    log(f"extract: wrote {len(rows)} rows to {CONFIG.paths.last_json}")
    return rows


def main() -> int:
    state = State.load()
    from .browser import open_browser

    with open_browser() as ctx:
        rows = extract(ctx, state)
    print(f"{len(rows)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
