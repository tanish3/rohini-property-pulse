#!/usr/bin/env python3
"""Convert the scraped NGDRS CSV into JSON files consumed by the static UI.

Outputs (in docs/data/):
  - registrations.json   flat list of all registrations, with parsed fields
  - sector28-summary.json  per-pocket / per-article aggregates
  - meta.json           top-level summary card data

Run:  python3 scripts/process_data.py
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC_CSV = ROOT / "data" / "rohini_sector28_2026-06-19_to_2026-07-19.csv"
OUT_DIR = ROOT / "docs" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ARTICLE_MAP = {
    "Sale Deed - 23": ("Sale Deed", 23),
    "Sale Agreement - 23 A": ("Sale Agreement", "23 A"),
    "Gift Deed - 33": ("Gift Deed", 33),
    "Relinquishment deed - 55": ("Relinquishment Deed", 55),
}

# Plot number → (pocket_id, block)
POCKET_RE = re.compile(
    r"\b(?:POCKET|PKT|PKT-)\s*[-]?\s*([A-Z0-9/\-]+)",
    re.IGNORECASE,
)
BLOCK_SLASH_RE = re.compile(
    r"\b([AC])[-\s]?(\d+)/"
)
BLK_RE = re.compile(
    r"\b(?:BLK|BLOCK)[-\s]+([AC])(?:[-\s]+(?:POCKET|PKT))?",
    re.IGNORECASE,
)
GH_RE = re.compile(r"\bGH[-\s]?(\d)\b", re.IGNORECASE)
NUMBERED_POCKET_RE = re.compile(
    r"\bPOCKET[-\s]+(\d)\b", re.IGNORECASE
)
COMPOUND_POCKET_RE = re.compile(
    r"\bPOCKET[-\s]+([AC])[-\s]+(\d)\b", re.IGNORECASE
)


def parse_date(s: str) -> str:
    s = s.strip()
    for fmt in ("%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M %p", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return s


def parse_description(raw: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not raw:
        return out
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for p in parts:
        if ":" not in p:
            continue
        key, _, val = p.partition(":")
        key = key.strip().lower()
        val = val.strip()
        out[key] = val
    return out


def num(v: Any) -> float | None:
    if v is None:
        return None
    m = re.search(r"[-+]?\d*\.?\d+", str(v).replace(",", ""))
    return float(m.group()) if m else None


def first(v: Any) -> Any:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


LEDGER_RE = re.compile(r"(\d{2})([AC])(\d)(?:[-/]?(\d+))?", re.IGNORECASE)


def _normalize(pocket_id: str) -> str:
    """Drop leading zeros in the trailing number, e.g. C-01 -> C-1."""
    if "-" not in pocket_id:
        return pocket_id
    block, num = pocket_id.split("-", 1)
    if num.isdigit():
        num = str(int(num))
    return f"{block}-{num}"


def infer_pocket(plot_number: str, desc: dict[str, Any]) -> tuple[str, str]:
    """Return (pocket_id, block_label) e.g. ('C-1', 'C') or ('GH-1', 'GH')."""
    pn = (plot_number or "").upper()
    desc_text = " ".join(str(v) for v in desc.values()).upper()
    haystack = f"{pn} {desc_text}"

    # 0. Ledger-style 28A3-282 → 28 [A] [3] - 282
    m = LEDGER_RE.search(pn)
    if m:
        return f"{m.group(2).upper()}-{m.group(3)}", m.group(2).upper()

    # 1. GH pockets
    m = GH_RE.search(haystack)
    if m:
        return _normalize(f"GH-{m.group(1)}"), "GH"

    # 2. Explicit POCKET-A-3 / POCKET-C-2
    m = COMPOUND_POCKET_RE.search(haystack)
    if m:
        return _normalize(f"{m.group(1)}-{m.group(2)}"), m.group(1)

    # 3. POCKET-<digit> preceded by a block keyword (BLOCK-A / BLK-C)
    m = NUMBERED_POCKET_RE.search(haystack)
    if m:
        block_m = BLK_RE.search(haystack) or BLOCK_SLASH_RE.search(haystack)
        if block_m:
            return _normalize(f"{block_m.group(1)}-{m.group(1)}"), block_m.group(1)

    # 4. POCKET-<token> like A-3, A/3
    m = POCKET_RE.search(pn)
    if m:
        tok = m.group(1).upper().strip("-")
        if tok.isdigit():
            block_m = BLK_RE.search(haystack) or BLOCK_SLASH_RE.search(haystack)
            if block_m:
                return _normalize(f"{block_m.group(1)}-{tok}"), block_m.group(1)
        m2 = re.match(r"([AC])[/\-]?(\d+)$", tok)
        if m2:
            return _normalize(f"{m2.group(1)}-{m2.group(2)}"), m2.group(1)

    # 5. BLOCK-A / BLK-A without an explicit pocket
    m = BLK_RE.search(haystack)
    if m:
        m2 = re.search(rf"\b{re.escape(m.group(1))}[-\s]+(\d+)\b", haystack)
        if m2:
            return _normalize(f"{m.group(1)}-{m2.group(1)}"), m.group(1)
        return m.group(1), m.group(1)

    # 6. A-N/... or C-N/... slash-prefix pattern
    m = BLOCK_SLASH_RE.search(pn)
    if m:
        return _normalize(f"{m.group(1)}-{m.group(2)}"), m.group(1)

    return "Unknown", "Unknown"


def load_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with SRC_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            article_raw = (r.get("article") or "").strip()
            article_name, article_code = ARTICLE_MAP.get(
                article_raw, (article_raw or "Unknown", None)
            )
            desc = parse_description(r.get("property_description") or "")
            plot_number = (r.get("plot_number") or "").strip()
            pocket_id, block = infer_pocket(plot_number, desc)
            seller = first(r.get("seller_name"))
            purchaser = first(r.get("purchaser_name"))
            rows.append(
                {
                    "id": int(r["sno"]),
                    "document_id": (r.get("document_id") or "").strip(),
                    "registration_no": (r.get("registration_no") or "").strip(),
                    "registration_date": parse_date(r.get("registration_date") or ""),
                    "article": article_name,
                    "article_raw": article_raw,
                    "article_code": article_code,
                    "registration_office": (r.get("registration_office") or "").strip(),
                    "seller": {
                        "name": seller,
                        "address": first(r.get("seller_address")),
                    },
                    "purchaser": {
                        "name": purchaser,
                        "address": first(r.get("purchaser_address")),
                    },
                    "property": {
                        "raw_plot_number": plot_number,
                        "pocket": pocket_id,
                        "block": block,
                        "upic": (r.get("upic_number") or "").strip(),
                        "property_id": (r.get("property_id") or "").strip(),
                        "village": (r.get("village_name") or "").strip(),
                        "description": {
                            "plot_area_sqm": num(desc.get("plot area")),
                            "plinth_area_sqm": num(desc.get("total plinth area/far of the property"))
                            or num(desc.get("total plinth area")),
                            "plinth_area_transferred_sqm": num(
                                desc.get("plinth area under released / transfer")
                            ),
                            "land_share_transferred_sqm": num(
                                desc.get("land share under transfer")
                            ),
                            "land_share_transferred_pct": num(
                                desc.get("land share under trasnfer in percentage")
                            ),
                            "floors": num(desc.get("number of floors (1 to 4)"))
                            or num(desc.get("number of floors")),
                            "floor_label": first(desc.get("floor")),
                            "floor_number": num(desc.get("floor number")),
                            "construction_type": first(desc.get("construction type")),
                            "category_of_locality": first(desc.get("category of the locality")),
                            "stilt_parking_sqm": num(desc.get("stilt parking area")),
                            "is_parking_present": first(desc.get("is parking present")),
                            "type_of_flats": first(desc.get("type of flats")),
                        },
                    },
                }
            )
    return rows


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pocket_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "articles": Counter(),
            "plot_areas": [],
            "plinth_areas": [],
            "floors": [],
            "construction": Counter(),
            "parking_present": Counter(),
            "earliest": None,
            "latest": None,
        }
    )
    article_counts: Counter = Counter()
    block_counts: Counter = Counter()
    date_counts: Counter = Counter()
    by_block_pockets: dict[str, set[str]] = defaultdict(set)

    for r in rows:
        pid = r["property"]["pocket"]
        block = r["property"]["block"]
        s = pocket_stats[pid]
        s["count"] += 1
        s["articles"][r["article"]] += 1
        article_counts[r["article"]] += 1
        block_counts[block] += 1
        by_block_pockets[block].add(pid)
        d = r["registration_date"][:10]
        date_counts[d] += 1
        s["earliest"] = min(s["earliest"] or d, d)
        s["latest"] = max(s["latest"] or d, d)
        d_desc = r["property"]["description"]
        if d_desc.get("plot_area_sqm") is not None:
            s["plot_areas"].append(d_desc["plot_area_sqm"])
        if d_desc.get("plinth_area_sqm") is not None:
            s["plinth_areas"].append(d_desc["plinth_area_sqm"])
        if d_desc.get("floors") is not None:
            s["floors"].append(d_desc["floors"])
        if d_desc.get("construction_type"):
            s["construction"][d_desc["construction_type"]] += 1
        if d_desc.get("is_parking_present"):
            s["parking_present"][d_desc["is_parking_present"]] += 1

    def avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 2) if xs else None

    pockets_out = {}
    for pid, s in pocket_stats.items():
        pockets_out[pid] = {
            "count": s["count"],
            "articles": dict(s["articles"]),
            "avg_plot_area_sqm": avg(s["plot_areas"]),
            "avg_plinth_area_sqm": avg(s["plinth_areas"]),
            "avg_floors": avg(s["floors"]),
            "construction": dict(s["construction"]),
            "parking": dict(s["parking_present"]),
            "earliest": s["earliest"],
            "latest": s["latest"],
        }

    block_summary = {}
    for block, cnt in block_counts.items():
        block_summary[block] = {
            "count": cnt,
            "pockets": sorted(by_block_pockets[block]),
        }

    date_series = [
        {"date": d, "count": date_counts[d]}
        for d in sorted(date_counts)
    ]

    return {
        "pockets": pockets_out,
        "articles": dict(article_counts),
        "blocks": block_summary,
        "date_series": date_series,
    }


def pocket_order_key(pid: str) -> tuple:
    if pid.startswith("GH-"):
        return (2, int(pid[3:]))
    if pid == "Unknown":
        return (9, 0)
    block, n = pid.split("-")
    return (0 if block == "A" else 1, int(n))


def main() -> None:
    rows = load_rows()
    rows.sort(key=lambda r: r["registration_date"])
    summary = aggregate(rows)

    # Reorder pockets by block then number for predictable UI rendering
    summary["pockets"] = dict(
        sorted(
            summary["pockets"].items(),
            key=lambda kv: pocket_order_key(kv[0]),
        )
    )

    dates = [r["registration_date"][:10] for r in rows]
    meta = {
        "source_csv": SRC_CSV.name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "date_from": min(dates) if dates else None,
        "date_to": max(dates) if dates else None,
        "total_registrations": len(rows),
        "unique_pockets": len({r["property"]["pocket"] for r in rows}),
        "articles": summary["articles"],
        "sector": "Rohini Sector-28",
        "taluka": "Alipur",
        "district": "North",
    }

    (OUT_DIR / "registrations.json").write_text(
        json.dumps({"meta": meta, "items": rows}, ensure_ascii=False, indent=2)
    )
    (OUT_DIR / "sector28-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    (OUT_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )
    print(f"Wrote {len(rows)} rows to {OUT_DIR}")
    print(f"Pockets: {sorted(summary['pockets'].keys())}")
    print(f"Articles: {summary['articles']}")


if __name__ == "__main__":
    main()
