# Rohini Property Pulse

Mobile-friendly visual explorer for Delhi NGDRS property registration data, focused on Rohini's residential sectors.

Drill from **Rohini sector map** → **Sector 28 pocket map** → **pocket detail** with full transaction list.

Live site: enabled via GitHub Pages from the `docs/` folder on `main`.

---

## Repository layout

```
.
├── data/                              # scraper output (CSV + raw JSON)
│   └── rohini_sector28_<date-range>.csv
├── scripts/
│   ├── process_data.py                # CSV → JSON consumed by the UI
│   └── smoke_test.py                  # headless browser smoke test
├── docs/                              # GitHub Pages site (static, no build)
│   ├── .nojekyll
│   ├── index.html
│   ├── assets/
│   │   ├── styles.css                 # mobile-first responsive CSS
│   │   ├── app.js                     # vanilla JS app (router + 4 views)
│   │   ├── rohini-sectors.svg         # overview map of 30 Rohini sectors
│   │   └── sector-28-pockets.svg      # pocket-level map of Sector 28
│   └── data/
│       ├── meta.json
│       ├── sector28-summary.json
│       └── registrations.json
└── requirements.txt                   # playwright, pandas, … (scraper)
```

## Data pipeline

```
NGDRS portal ─(scraper)─► data/*.csv ─(process_data.py)─► docs/data/*.json
                                                              │
                                                              └─► docs/index.html (static UI)
```

Re-generate the processed JSON after every scrape run:

```bash
.venv/bin/python scripts/process_data.py
```

## Local development

```bash
# Serve the static site on http://127.0.0.1:8765
.venv/bin/python -m http.server 8765 --bind 127.0.0.1 --directory docs

# Run headless smoke test (Playwright)
.venv/bin/python scripts/smoke_test.py
```

## Deploying to GitHub Pages

1. Push to GitHub.
2. Repo → **Settings → Pages**.
3. **Source**: *Deploy from a branch* · **Branch**: `main` · **Folder**: `/docs`.
4. The site will be live at `https://<user>.github.io/<repo>/`.

The `docs/.nojekyll` file disables Jekyll processing so the `_`-prefixed folders (none here) and `data/` directory are served as-is.

## UI tour

| Route | What's there |
|---|---|
| `#/` | Rohini sector map (30 sectors, sector 28 highlighted), 4 stat cards, activity-by-article and daily-trend bar charts. |
| `#/sector/28` | Pocket map of Sector 28 (Block A pockets 3-6, Block C pockets 1-5, GH-1..4 DDA flats), per-pocket summary cards, charts, search/filter bar, first 50 transactions. |
| `#/sector/28/pocket/<pocket>` | Pocket detail: transaction count, top article, avg plot / plinth / floors, article and daily breakdowns, full transaction list (mobile cards / desktop table). |
| `#/sector/28/all` | All 90 transactions with full search, filter, and sort. |

## Data schema (pocket inference rules)

A "pocket" is inferred from the free-text `plot_number` and `property_description` fields:

- `POCKET-GH-1..4` / `GH-1..4` → GH flats cluster
- `BLOCK-A POCKET-N` / `BLK-A POCKET-N` / `BLOCK-C PKT-N` → Block A / C pocket N
- `A-N/<plot>` / `C-N/<plot>` → Block A / C pocket N
- `28A3-282` (ledger style) → A-3
- Anything else → `Unknown`

Pockets with bare numeric plot numbers (e.g. `326`) are bucketed under `Unknown` and shown in their own area of the map.

## Notes

- Vanilla JS, no build step, no external CDN → works offline once cached.
- Mobile-first CSS with safe-area insets; SVG maps scale fluidly.
- `data/raw/` and `data/*.csv` are git-ignored (raw scraper artefacts). Only the processed JSON under `docs/data/` is published.
