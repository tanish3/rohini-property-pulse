#!/usr/bin/env python3
"""Generate approximate pocket polygons for Sector 28.

The actual Sector 28 outline is taken from OpenStreetMap (Nominatim).
Pocket boundaries are APPROXIMATE divisions of the sector — the real
pocket boundaries are managed by DDA and not in OSM. This is a
visualization aid, not a survey-grade map.

Layout used (based on public DDA Rohini maps):
- Northern half: Block A, pockets A-1..A-6 (W→E)
- Southern half: Block C, pockets C-1..C-5 (W→E)
- Eastern strip: GH-1, GH-2, GH-3, GH-4 (DDA LIG/MIG flats)
- Remaining bare-plot records: Unknown bucket
"""
import json
from pathlib import Path

SECTOR_FACE = Path("/tmp/rohini_sectors/sector_28.json")
OUT = Path(__file__).resolve().parent.parent / "docs" / "data" / "sector-28-pockets.geojson"

s28 = json.loads(SECTOR_FACE.read_text())[0]
bb = [float(x) for x in s28["boundingbox"]]  # [S, N, W, E]
south, north, west, east = bb

# Reserve the eastern strip for GH flats (about 12% of width)
gh_w = west + (east - west) * 0.86
# Divide the rest into Block A (north) and Block C (south)
mid_lat = south + (north - south) * 0.50

# Block A: 6 pockets (A-1..A-6) — only A-3..A-6 have data
block_a_west = west
block_a_east = gh_w
# Block C: 5 pockets (C-1..C-5)
block_c_west = west
block_c_east = gh_w

# A pocket width (6 pockets)
a_step = (block_a_east - block_a_west) / 6
# C pocket width (5 pockets)
c_step = (block_c_east - block_c_west) / 5
# GH strip: divide into 4 vertical sub-strips
gh_step = (north - south) / 4

# A small inset so the polygons don't overlap perfectly
EPS = 0.00003

pockets = []

def add(name, block, count, polygon):
    pockets.append({
        "type": "Feature",
        "properties": {
            "pocket": name,
            "block": block,
            "approximate": True,
        },
        "geometry": {"type": "Polygon", "coordinates": [polygon]},
    })

# Block A: 6 pockets, west to east (mid_lat..north)
for i in range(6):
    w = block_a_west + a_step * i + EPS
    e = block_a_west + a_step * (i + 1) - EPS
    name = f"A-{i+1}"
    add(name, "A", 0, [
        [w, mid_lat + EPS],
        [e, mid_lat + EPS],
        [e, north - EPS],
        [w, north - EPS],
        [w, mid_lat + EPS],
    ])

# Block C: 5 pockets, west to east (south..mid_lat)
for i in range(5):
    w = block_c_west + c_step * i + EPS
    e = block_c_west + c_step * (i + 1) - EPS
    name = f"C-{i+1}"
    add(name, "C", 0, [
        [w, south + EPS],
        [e, south + EPS],
        [e, mid_lat - EPS],
        [w, mid_lat - EPS],
        [w, south + EPS],
    ])

# GH flats: 4 vertical strips in the eastern strip
for i in range(4):
    s = south + gh_step * i + EPS
    n = south + gh_step * (i + 1) - EPS
    name = f"GH-{i+1}"
    add(name, "GH", 0, [
        [gh_w + EPS, s],
        [east - EPS, s],
        [east - EPS, n],
        [gh_w + EPS, n],
        [gh_w + EPS, s],
    ])

fc = {
    "type": "FeatureCollection",
    "features": pockets,
    "properties": {
        "source": "Approximate — derived from Sector 28 OSM boundary",
        "bbox": bb,
    },
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(fc, ensure_ascii=False, indent=2))
print(f"Wrote {len(pockets)} pocket polygons to {OUT}")
