#!/usr/bin/env python3
"""Fetch and cache OpenStreetMap polygon boundaries for every Rohini sector.

Results are cached at `.cache/nominatim/sector_<n>.json` (gitignored) so the
Nominatim API is hit only on the first run. Re-runs are instant and offline.

Nominatim usage policy: max 1 request/second. We sleep 1.1 s between calls.
https://operations.osmfoundation.org/policies/nominatim/
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "nominatim"
CACHE.mkdir(parents=True, exist_ok=True)

# Rohini has sectors 1-38 (39-41 are outside the scraped set).
SECTORS = list(range(1, 39))

UA = "rohini-property-pulse/1.0 (https://github.com/tanish3/rohini-property-pulse)"

QUERIES = [
    "Sector {n}, Rohini, Delhi",
    "Sector {n}, Rohini, Narela, Delhi",
    "Sector {n} Rohini Delhi",
]

def fetch(n: int) -> list | None:
    # The top hit is often a nearby sector or a railway point, so take the
    # first polygon whose name is exactly this sector, trying several phrasings.
    for template in QUERIES:
        q = urllib.parse.urlencode({
            "q": template.format(n=n),
            "format": "json",
            "polygon_geojson": "1",
            "limit": "8",
        })
        url = f"https://nominatim.openstreetmap.org/search?{q}"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            results = json.loads(r.read())
        for item in results:
            name = item.get("display_name", "")
            geom = item.get("geojson") or {}
            if geom.get("type") in ("Polygon", "MultiPolygon") and name.startswith(f"Sector {n},"):
                return [item]
        time.sleep(1.1)
    return None

def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None  # optional: a specific sector number
    targets = [int(only)] if only else SECTORS

    fetched = 0
    cached = 0
    for n in targets:
        f = CACHE / f"sector_{n}.json"
        if f.exists() and f.stat().st_size > 100:
            cached += 1
            continue
        try:
            data = fetch(n)
        except Exception as e:
            print(f"  sector {n}: ERROR {e}", file=sys.stderr)
            continue
        if not data:
            print(f"  sector {n}: no results")
            continue
        f.write_text(json.dumps(data, ensure_ascii=False))
        fetched += 1
        print(f"  sector {n}: fetched ({data[0].get('display_name', '')[:60]})")
        time.sleep(1.1)  # respect Nominatim rate limit
    print(f"Done. fetched={fetched} cached={cached} cache={CACHE}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
