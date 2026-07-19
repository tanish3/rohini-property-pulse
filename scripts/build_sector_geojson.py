#!/usr/bin/env python3
"""Build a single GeoJSON FeatureCollection of all Rohini sector polygons
from the persistent Nominatim cache at .cache/nominatim/.

Run scripts/refresh_sector_cache.py first if the cache is empty.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "nominatim"
OUT = ROOT / "docs" / "data" / "sectors.geojson"

features = []
for f in sorted(CACHE.glob("sector_*.json")):
    n = int(f.stem.split("_")[1])
    try:
        data = json.loads(f.read_text())
    except Exception:
        continue
    if not data:
        continue
    item = data[0]
    if "geojson" not in item:
        continue
    geom = item["geojson"]
    if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
        continue
    features.append(
        {
            "type": "Feature",
            "properties": {
                "sector": n,
                "display_name": item.get("display_name", f"Sector {n}"),
                "osm_id": item.get("osm_id"),
                "osm_type": item.get("osm_type"),
                "has_data": (n == 28),
            },
            "geometry": geom,
        }
    )

fc = {"type": "FeatureCollection", "features": features}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(fc, ensure_ascii=False))
print(f"Wrote {len(features)} sectors to {OUT}")
for feat in features[:5]:
    p = feat["properties"]
    print(f"  sector {p['sector']:>2}: {p['display_name'][:60]}")
