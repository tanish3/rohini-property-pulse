// Rohini Property Pulse — interactive Leaflet map helpers
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

  // Sector colors
  const COLOR_S28 = "#1d4ed8";
  const COLOR_OTHER_STROKE = "#1e40af";
  const COLOR_OTHER_FILL = "#60a5fa";

  // Pocket heatmap
  const POCKET_COLOR = (n) => {
    if (n >= 12) return "#b91c1c";
    if (n >= 10) return "#dc2626";
    if (n >= 7)  return "#ea580c";
    if (n >= 5)  return "#f97316";
    if (n >= 3)  return "#fb923c";
    if (n >= 1)  return "#fed7aa";
    return "#e2e8f0";
  };
  const POCKET_LABEL_COLOR = (n) => (n >= 3 ? "#ffffff" : "#1e293b");

  // -------- Public: render Rohini overview --------
  async function renderRohiniMap(containerId, onSectorClick) {
    const el = document.getElementById(containerId);
    if (!el) return null;
    el.innerHTML = "";

    const map = L.map(el, {
      center: [28.74, 77.085],
      zoom: 12,
      minZoom: 11,
      maxZoom: 18,
      zoomControl: true,
      scrollWheelZoom: true,
    });
    L.tileLayer(TILE_URL, TILE_OPTS).addTo(map);

    const sectors = await fetch("data/sectors.geojson").then((r) => r.json());
    const layer = L.geoJSON(sectors, {
      style: (feat) => {
        const s = feat.properties.sector;
        const is28 = s === 28;
        return {
          color: is28 ? COLOR_S28 : COLOR_OTHER_STROKE,
          weight: is28 ? 4 : 2,
          opacity: is28 ? 1 : 0.85,
          fillColor: is28 ? COLOR_S28 : COLOR_OTHER_FILL,
          fillOpacity: is28 ? 0.55 : 0.35,
          dashArray: is28 ? null : "4 3",
        };
      },
      onEachFeature: (feat, lyr) => {
        const s = feat.properties.sector;
        const is28 = s === 28;
        const has = feat.properties.has_data;
        const baseStyle = {
          color: is28 ? COLOR_S28 : COLOR_OTHER_STROKE,
          weight: is28 ? 4 : 2,
          fillOpacity: is28 ? 0.55 : 0.35,
        };
        lyr.bindTooltip(
          `<div class="rpp-tip">
             <div class="rpp-tip-title">Sector ${s}${is28 ? " · Selected" : ""}</div>
             <div class="rpp-tip-sub">${has ? "90 registrations in selected period" : "No scraped data"}</div>
             ${is28 ? `<div class="rpp-tip-cta">Tap to drill in →</div>` : ""}
           </div>`,
          { sticky: true, direction: "top", className: "rpp-tooltip", opacity: 1 }
        );
        lyr.on("mouseover", () => {
          lyr.setStyle({
            weight: is28 ? 5 : 3.5,
            fillOpacity: is28 ? 0.7 : 0.55,
          });
          lyr.openTooltip();
          lyr.bringToFront();
        });
        lyr.on("mouseout", () => lyr.setStyle(baseStyle));
        lyr.on("click", () => onSectorClick && onSectorClick(s, has));
        lyr.on("keypress", (e) => {
          if (e.originalEvent.key === "Enter") lyr.fire("click");
        });
      },
    }).addTo(map);

    // Sector number labels at polygon centroids
    layer.eachLayer((lyr) => {
      const s = lyr.feature.properties.sector;
      const is28 = s === 28;
      const c = lyr.getBounds().getCenter();
      const html = is28
        ? `<div class="sec-label sec-label-28"><b>${s}</b><span>90 regs</span></div>`
        : `<div class="sec-label">${s}</div>`;
      L.marker(c, {
        icon: L.divIcon({
          className: "sec-label-wrap",
          html,
          iconSize: null,
          iconAnchor: [0, 0],
        }),
        interactive: false,
      }).addTo(map);
    });

    // Fit all sectors in view with padding
    const bounds = layer.getBounds();
    map.fitBounds(bounds, { padding: [24, 24] });
    // Lock max zoom-out so users can't lose the whole map
    map.setMinZoom(map.getZoom() - 1);

    return { map, layer };
  }

  // -------- Public: render Sector 28 pocket map --------
  async function renderSector28Map(containerId, onPocketClick, activePocket) {
    const el = document.getElementById(containerId);
    if (!el) return null;
    el.innerHTML = "";

    const map = L.map(el, {
      center: [28.756, 77.100],
      zoom: 16,
      minZoom: 14,
      maxZoom: 19,
      zoomControl: true,
      scrollWheelZoom: true,
    });
    L.tileLayer(TILE_URL, TILE_OPTS).addTo(map);

    // Sector 28 outline (for context)
    const sectors = await fetch("data/sectors.geojson").then((r) => r.json());
    const s28 = sectors.features.find((f) => f.properties.sector === 28);
    if (s28) {
      L.geoJSON(s28, {
        style: {
          color: "#1e3a8a",
          weight: 3,
          opacity: 0.9,
          fillColor: "#1e3a8a",
          fillOpacity: 0.04,
          dashArray: "8 4",
        },
      }).addTo(map);
    }

    const pocketGeo = await fetch("data/sector-28-pockets.geojson").then((r) => r.json());
    const counts = (window.RPP_STATE && window.RPP_STATE.pocketCounts) || {};
    const articles = (window.RPP_STATE && window.RPP_STATE.pocketArticles) || {};

    const pocketLayer = L.geoJSON(pocketGeo, {
      style: (feat) => {
        const id = feat.properties.pocket;
        const n = counts[id] || 0;
        const isActive = id === activePocket;
        return {
          color: isActive ? "#0f172a" : "#ffffff",
          weight: isActive ? 5 : 2.5,
          opacity: 1,
          fillColor: POCKET_COLOR(n),
          fillOpacity: n === 0 ? 0.25 : 0.78,
          dashArray: n === 0 ? "4 3" : null,
        };
      },
      onEachFeature: (feat, lyr) => {
        const id = feat.properties.pocket;
        const n = counts[id] || 0;
        const block = feat.properties.block;
        const blockLabel =
          block === "GH" ? "DDA Flats" :
          block === "Unknown" ? "Unmapped" :
          `Block ${block}`;
        const topArticle = articles[id] ? Object.entries(articles[id]).sort((a, b) => b[1] - a[1])[0] : null;
        const topArticleHtml = topArticle
          ? `<div class="rpp-tip-row">Top article: <b>${topArticle[0]}</b> (${topArticle[1]})</div>`
          : "";
        lyr.bindTooltip(
          `<div class="rpp-tip">
             <div class="rpp-tip-title">Pocket ${id} <span class="rpp-tip-badge">${blockLabel}</span></div>
             <div class="rpp-tip-sub">${n} registration${n === 1 ? "" : "s"} in selected period</div>
             ${topArticleHtml}
             <div class="rpp-tip-cta">Tap to drill in →</div>
           </div>`,
          { sticky: true, direction: "top", className: "rpp-tooltip", opacity: 1 }
        );
        const baseStyle = {
          color: id === activePocket ? "#0f172a" : "#ffffff",
          weight: id === activePocket ? 5 : 2.5,
          fillOpacity: n === 0 ? 0.25 : 0.78,
        };
        lyr.on("mouseover", () => {
          lyr.setStyle({ weight: 4, fillOpacity: 0.9, color: "#0f172a" });
          lyr.openTooltip();
          lyr.bringToFront();
        });
        lyr.on("mouseout", () => lyr.setStyle(baseStyle));
        lyr.on("click", () => onPocketClick && onPocketClick(id));
      },
    }).addTo(map);

    // Pocket number + count badges
    pocketLayer.eachLayer((lyr) => {
      const id = lyr.feature.properties.pocket;
      const n = counts[id] || 0;
      const c = lyr.getBounds().getCenter();
      const labelColor = POCKET_LABEL_COLOR(n);
      const html = n > 0
        ? `<div class="pkt-label" style="color:${labelColor}"><b>${id}</b><span class="pkt-count">${n}</span></div>`
        : `<div class="pkt-label dim"><b>${id}</b><span class="pkt-count">·</span></div>`;
      L.marker(c, {
        icon: L.divIcon({
          className: "pkt-label-wrap",
          html,
          iconSize: null,
          iconAnchor: [0, 0],
        }),
        interactive: false,
      }).addTo(map);
    });

    // Fit all pockets in view
    const bounds = pocketLayer.getBounds();
    map.fitBounds(bounds, { padding: [28, 28] });
    map.setMinZoom(Math.max(14, map.getZoom() - 1));

    return { map, layer: pocketLayer };
  }

  // Inject CSS for labels and tooltips
  function injectCss() {
    if (document.getElementById("rpp-map-css")) return;
    const css = document.createElement("style");
    css.id = "rpp-map-css";
    css.textContent = `
      .leaflet-container { font: inherit; border-radius: 12px; }
      .leaflet-control-attribution { font-size: 10px; }

      /* === Sector labels (overview map) === */
      .sec-label-wrap, .pkt-label-wrap { background: transparent !important; border: 0 !important; }
      .sec-label {
        font: 700 13px system-ui, -apple-system, "Segoe UI", sans-serif;
        color: #1e3a8a;
        text-align: center;
        pointer-events: none;
        line-height: 1;
        white-space: nowrap;
        background: rgba(255,255,255,0.85);
        border-radius: 10px;
        padding: 3px 7px;
        min-width: 22px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.15);
      }
      .sec-label-28 {
        background: #1d4ed8;
        color: #fff;
        font-size: 14px;
        padding: 4px 8px;
        box-shadow: 0 2px 6px rgba(29, 78, 216, 0.5);
      }
      .sec-label-28 b { font-size: 16px; }
      .sec-label-28 span {
        display: block;
        font: 600 10px system-ui, sans-serif;
        color: #bfdbfe;
        margin-top: 1px;
      }

      /* === Pocket labels (sector 28 map) === */
      .pkt-label {
        font: 700 13px system-ui, -apple-system, "Segoe UI", sans-serif;
        text-align: center;
        pointer-events: none;
        line-height: 1.05;
        white-space: nowrap;
        text-shadow: 0 1px 2px rgba(0,0,0,0.4);
      }
      .pkt-label b { display: block; font-size: 14px; }
      .pkt-label .pkt-count {
        display: inline-block;
        margin-top: 2px;
        background: rgba(0,0,0,0.45);
        color: #fff;
        font: 700 11px system-ui, sans-serif;
        padding: 1px 6px;
        border-radius: 999px;
        text-shadow: none;
      }
      .pkt-label.dim { color: #475569; opacity: 0.75; text-shadow: 0 1px 2px rgba(255,255,255,0.6); }
      .pkt-label.dim .pkt-count { background: rgba(71, 85, 105, 0.5); }

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
