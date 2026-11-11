// Rohini Property Pulse — interactive Leaflet map helpers.
// Uses OpenStreetMap tiles (no API key, free, attribution required).
(() => {
  "use strict";

  const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
  const TILE_ATTR =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  const TILE_OPTS = {
    maxZoom: 19,
    minZoom: 10,
    attribution: TILE_ATTR,
  };

  const SECTOR_MIN = 18;
  const SECTOR_MAX = 38;

  const COLORS = {
    dataFill: "#3b82f6",
    dataStroke: "#1e3a8a",
    noneFill: "#cbd5e1",
    noneStroke: "#64748b",
    selFill: "#1d4ed8",
    selStroke: "#fbbf24",
  };

  const esc = (s) =>
    s == null ? "" : String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const fmt = (n) => Number(n).toLocaleString("en-IN");
  const plural = (n, one) => `${fmt(n)} ${n === 1 ? one : one + "s"}`;

  const blockName = (b) =>
    b === "GH" ? "DDA Flats" : b === "Unknown" ? "Unmapped" : `Block ${b}`;
  const pocketTitle = (id) =>
    id === "Unknown" ? "Unmapped plots" :
    /^[A-Z]$/.test(id) ? `Block ${id} (unnumbered)` : `Pocket ${id}`;

  // Makes a Leaflet path reachable by Tab and activatable with Enter/Space.
  function makeFocusable(lyr, label, activate) {
    lyr.on("add", () => {
      const node = lyr.getElement();
      if (!node || node.dataset.rppFocus) return;
      node.dataset.rppFocus = "1";
      node.setAttribute("tabindex", "0");
      node.setAttribute("role", "button");
      node.setAttribute("aria-label", label);
      node.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          activate();
        }
      });
      node.addEventListener("focus", () => lyr.fire("mouseover"));
      node.addEventListener("blur", () => lyr.fire("mouseout"));
    });
  }

  // -------- Public: Rohini sectors overview --------
  async function renderRohiniMap(containerId, onSectorClick, activeSector = null) {
    const el = document.getElementById(containerId);
    if (!el) return null;
    el.innerHTML = "";

    const counts = (window.RPP_STATE && window.RPP_STATE.sectorCounts) || {};
    const countOf = (s) => counts[String(s)] || 0;
    const isActive = (s) => activeSector != null && Number(s) === Number(activeSector);

    const map = L.map(el, {
      center: [28.74, 77.085],
      zoom: 12,
      minZoom: 11,
      maxZoom: 18,
      scrollWheelZoom: true,
    });
    L.tileLayer(TILE_URL, TILE_OPTS).addTo(map);
    map.attributionControl.setPrefix(false);

    const geo = await fetch("data/sectors.geojson").then((r) => r.json());
    const features = geo.features.filter(
      (f) => f.properties.sector >= SECTOR_MIN && f.properties.sector <= SECTOR_MAX
    );

    const styleFor = (s) => {
      if (isActive(s)) {
        return { color: COLORS.selStroke, weight: 5, opacity: 1, fillColor: COLORS.selFill, fillOpacity: 0.6 };
      }
      if (countOf(s) > 0) {
        return { color: COLORS.dataStroke, weight: 2.5, opacity: 0.9, fillColor: COLORS.dataFill, fillOpacity: 0.45 };
      }
      return { color: COLORS.noneStroke, weight: 1.5, opacity: 0.8, fillColor: COLORS.noneFill, fillOpacity: 0.35, dashArray: "4 3" };
    };

    const layer = L.geoJSON({ type: "FeatureCollection", features }, {
      style: (feat) => styleFor(feat.properties.sector),
      onEachFeature: (feat, lyr) => {
        const s = feat.properties.sector;
        const n = countOf(s);
        const hasData = n > 0;
        const base = styleFor(s);
        lyr.bindTooltip(
          `<div class="rpp-tip">
             <div class="rpp-tip-title">Sector ${s}${isActive(s) ? " · Selected" : ""}</div>
             <div class="rpp-tip-sub">${hasData ? `${plural(n, "record")} in this period` : "No records in this period"}</div>
             ${hasData ? `<div class="rpp-tip-cta">Click to open →</div>` : ""}
           </div>`,
          { sticky: true, direction: "top", className: "rpp-tooltip", opacity: 1 }
        );
        lyr.on("mouseover", () => {
          lyr.setStyle({ weight: base.weight + 1.5, fillOpacity: Math.min(0.8, (base.fillOpacity || 0.4) + 0.25) });
          lyr.openTooltip();
          lyr.bringToFront();
        });
        lyr.on("mouseout", () => lyr.setStyle(base));
        lyr.on("click", () => onSectorClick && onSectorClick(s, hasData));
        makeFocusable(lyr, `Sector ${s}, ${hasData ? plural(n, "record") : "no records"}`, () => lyr.fire("click"));
      },
    }).addTo(map);

    layer.eachLayer((lyr) => {
      const s = lyr.feature.properties.sector;
      const n = countOf(s);
      const html = isActive(s)
        ? `<div class="sec-label sec-label-active"><b>${s}</b><span>${fmt(n)} records</span></div>`
        : `<div class="sec-label${n > 0 ? "" : " dim"}">${s}</div>`;
      L.marker(lyr.getBounds().getCenter(), {
        icon: L.divIcon({ className: "sec-label-wrap", html, iconSize: null, iconAnchor: [0, 0] }),
        interactive: false,
      }).addTo(map);
    });

    map.fitBounds(layer.getBounds(), { padding: [16, 16] });
    map.setMinZoom(map.getZoom() - 1);

    return { map, layer };
  }

  // -------- Public: Sector 28 pocket map (same styling as the sector map) --------
  async function renderSector28Map(containerId, onPocketClick, activePocket = null) {
    const el = document.getElementById(containerId);
    if (!el) return null;
    el.innerHTML = "";

    const map = L.map(el, {
      center: [28.756, 77.1],
      zoom: 15,
      minZoom: 13,
      maxZoom: 19,
      scrollWheelZoom: true,
    });
    L.tileLayer(TILE_URL, TILE_OPTS).addTo(map);
    map.attributionControl.setPrefix(false);

    const sectors = await fetch("data/sectors.geojson").then((r) => r.json());
    const s28 = sectors.features.find((f) => f.properties.sector === 28);
    const outline = s28
      ? L.geoJSON(s28, {
          interactive: false,
          style: { color: COLORS.dataStroke, weight: 2, opacity: 0.7, fillOpacity: 0, dashArray: "6 4" },
        }).addTo(map)
      : null;

    const pocketGeo = await fetch("data/sector-28-pockets.geojson").then((r) => r.json());
    const pockets = (window.RPP_STATE && window.RPP_STATE.pockets) || {};
    const countOf = (id) => (pockets[id] ? pockets[id].count : 0);
    const isActive = (id) => id === activePocket;

    const styleFor = (id) => {
      const n = countOf(id);
      if (isActive(id)) {
        return { color: COLORS.selStroke, weight: 4, opacity: 1, fillColor: COLORS.selFill, fillOpacity: 0.6 };
      }
      if (n > 0) {
        const fillOpacity = 0.3 + 0.4 * Math.min(1, n / 40);
        return { color: COLORS.dataStroke, weight: 2, opacity: 0.9, fillColor: COLORS.dataFill, fillOpacity };
      }
      return { color: COLORS.noneStroke, weight: 1.2, opacity: 0.8, fillColor: COLORS.noneFill, fillOpacity: 0.3, dashArray: "4 3" };
    };

    const pocketLayer = L.geoJSON(pocketGeo, {
      style: (feat) => styleFor(feat.properties.pocket),
      onEachFeature: (feat, lyr) => {
        const id = feat.properties.pocket;
        const n = countOf(id);
        const p = pockets[id];
        const base = styleFor(id);
        const top = p ? Object.entries(p.articles).sort((a, b) => b[1] - a[1])[0] : null;
        lyr.bindTooltip(
          `<div class="rpp-tip">
             <div class="rpp-tip-title">${esc(pocketTitle(id))} <span class="rpp-tip-badge">${esc(blockName(feat.properties.block))}</span></div>
             <div class="rpp-tip-sub">${n > 0 ? `${plural(n, "record")} in this period` : "No records in this period"}</div>
             ${p && p.avg_plot_area_sqm ? `<div class="rpp-tip-row">Avg plot ${esc(p.avg_plot_area_sqm)} m²</div>` : ""}
             ${top ? `<div class="rpp-tip-row">Top article: <b>${esc(top[0])}</b> (${top[1]})</div>` : ""}
             ${n > 0 ? `<div class="rpp-tip-cta">Click to open →</div>` : ""}
           </div>`,
          { sticky: true, direction: "top", className: "rpp-tooltip", opacity: 1 }
        );
        lyr.on("mouseover", () => {
          lyr.setStyle({ weight: base.weight + 1.5, fillOpacity: Math.min(0.85, (base.fillOpacity || 0.4) + 0.25) });
          lyr.openTooltip();
          lyr.bringToFront();
        });
        lyr.on("mouseout", () => lyr.setStyle(base));
        if (n > 0) lyr.on("click", () => onPocketClick && onPocketClick(id));
        makeFocusable(lyr, `${pocketTitle(id)}, ${n > 0 ? plural(n, "record") : "no records"}`, () => {
          if (n > 0) lyr.fire("click");
        });
      },
    }).addTo(map);

    map.fitBounds((outline || pocketLayer).getBounds(), { padding: [16, 16], animate: false });
    map.setMinZoom(map.getZoom() - 1);

    // Number pills at pocket centres. Pills that would collide with one already placed are skipped
    // (the tooltip and the leaderboard still name them).
    const placed = [];
    pocketLayer.eachLayer((lyr) => {
      const id = lyr.feature.properties.pocket;
      const n = countOf(id);
      if (n === 0 || id === "Unknown") return;
      const center = lyr.getBounds().getCenter();
      const pt = map.latLngToContainerPoint(center);
      const active = isActive(id);
      const w = 6.2 * id.length + 12;
      if (!active && placed.some((q) => Math.abs(q.x - pt.x) < (q.w + w) / 2 + 2 && Math.abs(q.y - pt.y) < 16)) return;
      placed.push({ x: pt.x, y: pt.y, w });
      const html = active
        ? `<div class="sec-label sec-label-active"><b>${esc(id)}</b><span>${fmt(n)} records</span></div>`
        : `<div class="sec-label pocket-pill">${esc(id)}</div>`;
      L.marker(center, {
        icon: L.divIcon({ className: "sec-label-wrap", html, iconSize: null, iconAnchor: [0, 0] }),
        interactive: false,
      }).addTo(map);
    });

    return { map, layer: pocketLayer };
  }

  function injectCss() {
    if (document.getElementById("rpp-map-css")) return;
    const css = document.createElement("style");
    css.id = "rpp-map-css";
    css.textContent = `
      .leaflet-container { font: inherit; border-radius: 12px; }
      .leaflet-control-attribution { font-size: 10px; }
      path.leaflet-interactive:focus { outline: none; stroke: #fbbf24; stroke-width: 4px; }

      /* === Sector labels (overview map) === */
      .sec-label-wrap, .pkt-label-wrap { background: transparent !important; border: 0 !important; }
      .sec-label {
        font: 700 13px system-ui, -apple-system, "Segoe UI", sans-serif;
        color: #fff;
        background: #1e3a8a;
        border-radius: 10px;
        padding: 3px 7px;
        min-width: 24px;
        text-align: center;
        white-space: nowrap;
        line-height: 1.2;
        box-shadow: 0 1px 3px rgba(0,0,0,0.4);
        pointer-events: none;
        transform: translate(-50%, -50%);
      }
      .sec-label.dim { background: #64748b; opacity: 0.85; }
      .sec-label-active {
        background: #1d4ed8;
        font-size: 14px;
        padding: 4px 9px;
        outline: 2px solid #fbbf24;
        outline-offset: 1px;
      }
      .sec-label-active b { font-size: 16px; display: block; }
      .sec-label.pocket-pill { font-size: 10px; padding: 2px 5px; }
      .sec-label-active span { display: block; font: 600 10px system-ui, sans-serif; color: #fde68a; }
      @media (max-width: 599px) {
        .sec-label-wrap .sec-label:not(.sec-label-active) { display: none; }
      }

      /* === Pocket labels (sector 28 map) === */
      .pkt-label {
        display: inline-flex;
        align-items: center;
        background: rgba(255, 255, 255, 0.95);
        color: #0f172a;
        border-radius: 999px;
        padding: 1px 6px;
        font: 700 9px system-ui, -apple-system, "Segoe UI", sans-serif;
        line-height: 1.4;
        white-space: nowrap;
        pointer-events: none;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.35);
      }

      /* === Custom tooltips === */
      .rpp-tooltip {
        background: #0f172a !important;
        color: #fff !important;
        border: 0 !important;
        border-radius: 8px !important;
        padding: 8px 12px !important;
        box-shadow: 0 6px 20px rgba(0,0,0,0.3) !important;
        font: 500 12px system-ui, sans-serif !important;
        white-space: normal !important;
        max-width: 240px;
      }
      .rpp-tooltip::before { display: none !important; }
      .rpp-tip-title { font-weight: 700; font-size: 13px; }
      .rpp-tip-sub { opacity: 0.85; margin-top: 2px; }
      .rpp-tip-row { margin-top: 4px; opacity: 0.95; }
      .rpp-tip-cta { margin-top: 6px; font-weight: 600; color: #fbbf24; }
      .rpp-tip-badge {
        display: inline-block;
        background: #fbbf24;
        color: #0f172a;
        font: 700 9px system-ui, sans-serif;
        padding: 1px 6px;
        border-radius: 4px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-left: 4px;
        vertical-align: 1px;
      }
    `;
    document.head.appendChild(css);
  }

  window.RPPMap = {
    renderRohiniMap,
    renderSector28Map,
    injectCss,
  };
})();
