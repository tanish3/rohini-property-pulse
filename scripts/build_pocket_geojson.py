#!/usr/bin/env python3
"""Generate approximate pocket polygons for Sector 28, laid out to match
the official DDA keyplan (3 vertical columns):

  Block A (west)  ──  Block B / GH (center)  ──  Block C (east)
  A-6, A-5, A-4   │   GH-2, GH-3              │   C-3, C-4, C-5   (north)
  ─────────── 30.0 M WIDE ROAD ────────────────────────────────────
  A-3, A-1        │   GH-1, GH-4              │   C-1, C-2       (south)

The actual Sector 28 outline is taken from OpenStreetMap (Nominatim).
Pocket boundaries are APPROXIMATE divisions of the sector — the real
pocket boundaries are managed by DDA and not in OSM.

Output: docs/data/sector-28-pockets.geojson
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTOR_FILE = ROOT / ".cache" / "nominatim" / "sector_28.json"
OUT = ROOT / "docs" / "data" / "sector-28-pockets.geojson"

s28 = json.loads(SECTOR_FILE.read_text())[0]
bb = [float(x) for x in s28["boundingbox"]]  # [S, N, W, E]
south, north, west, east = bb
mid_lat = (south + north) / 2  # 28.75607

# Column boundaries (longitude). Block A is wider, Block B narrower, Block C
# takes the east edge.
COL_A_W = west
COL_A_E = west + (east - west) * 0.36
COL_B_W = COL_A_E
COL_B_E = west + (east - west) * 0.55
COL_C_W = COL_B_E
COL_C_E = east

# Row split for the 30.0M central road (slightly below the lat midpoint to
# match the keyplan which has more pockets in the north row of Block A)
ROW_MID = mid_lat - 0.0008

EPS = 0.00003  # small inset so adjacent polygons don't overlap visually

pockets: list[dict] = []


def rect(name: str, block: str, label_count: bool, w: float, e: float, s: float, n: float) -> None:
    """Add an axis-aligned rectangle pocket, inset by EPS."""
    pockets.append({
        "type": "Feature",
        "properties": {
            "pocket": name,
            "block": block,
            "approximate": True,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [w + EPS, s + EPS],
                [e - EPS, s + EPS],
                [e - EPS, n - EPS],
                [w + EPS, n - EPS],
                [w + EPS, s + EPS],
            ]],
        },
    })


# --- Block A (west column) — 5 pockets ---
# North row subdivided into 3 vertical strips
a_n = ROW_MID + 0.0014  # start north row a bit above the road (PKT-15/PKT-16 area)
a_third = (COL_A_E - COL_A_W) / 3
rect("A-6", "A", True, COL_A_W,            COL_A_W + a_third,   a_n, north)
rect("A-5", "A", True, COL_A_W + a_third,   COL_A_W + 2*a_third, a_n, north)
rect("A-4", "A", True, COL_A_W + 2*a_third, COL_A_E,             a_n, north)

# South row subdivided into 2 vertical strips (A-3 on top, A-1 on bottom)
a_s_mid = (south + ROW_MID) / 2 + 0.0006
a_half = (COL_A_E - COL_A_W) / 2
rect("A-3", "A", True, COL_A_W,        COL_A_W + a_half,   a_s_mid, ROW_MID)
rect("A-1", "A", True, COL_A_W,        COL_A_W + a_half,   south,   a_s_mid)
# Right half of south row — community / unmapped area (no data, but still
# useful to show the DDA keyplan layout in context)
rect("A-UNK", "A", False, COL_A_W + a_half, COL_A_E, south, ROW_MID)

# --- Block B / GH (center column) — 2x2 grid of LIG/MIG flats ---
b_half_w = (COL_B_E - COL_B_W) / 2
b_half_h = (north - south) / 2
rect("GH-2", "GH", True, COL_B_W,                COL_B_W + b_half_w, south + b_half_h + EPS, north)
rect("GH-3", "GH", True, COL_B_W + b_half_w,     COL_B_E,             south + b_half_h + EPS, north)
rect("GH-1", "GH", True, COL_B_W,                COL_B_W + b_half_w, south,                  south + b_half_h)
rect("GH-4", "GH", True, COL_B_W + b_half_w,     COL_B_E,             south,                  south + b_half_h)

# --- Block C (east column) — 3 north + 2 south ---
c_third = (COL_C_E - COL_C_W) / 3
rect("C-3", "C", True, COL_C_W,             COL_C_W + c_third,   ROW_MID, north)
rect("C-4", "C", True, COL_C_W + c_third,   COL_C_W + 2*c_third, ROW_MID, north)
rect("C-5", "C", True, COL_C_W + 2*c_third, COL_C_E,             ROW_MID, north)

c_half = (COL_C_E - COL_C_W) / 2
rect("C-1", "C", True, COL_C_W,         COL_C_W + c_half, south, ROW_MID)
rect("C-2", "C", True, COL_C_W + c_half, COL_C_E,         south, ROW_MID)

fc = {
    "type": "FeatureCollection",
    "features": pockets,
    "properties": {
        "source": "Approximate — derived from Sector 28 OSM boundary, DDA keyplan layout",
        "bbox": bb,
        "columns": {"A_w": COL_A_W, "A_e": COL_A_E, "B_w": COL_B_W, "B_e": COL_B_E, "C_w": COL_C_W, "C_e": COL_C_E},
        "row_mid_lat": ROW_MID,
    },
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(fc, ensure_ascii=False, indent=2))
print(f"Wrote {len(pockets)} pocket polygons to {OUT}")
for p in pockets:
    name = p["properties"]["pocket"]
    block = p["properties"]["block"]
    print(f"  {name:6s} (block {block})")
