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

  // Sector 28 colors
  const COLOR_HIGHLIGHT = "#2563eb";
  const COLOR_OTHER = "#3b82f6";
  const COLOR_OTHER_FILL = "#93c5fd";

  // Pocket colors by transaction count (matches old SVG heatmap)
  const POCKET_COLOR = (n) => {
    if (n >= 12) return "#b91c1c";
    if (n >= 10) return "#dc2626";
    if (n >= 7)  return "#ea580c";
    if (n >= 5)  return "#f97316";
    if (n >= 3)  return "#fb923c";
    return "#fed7aa";
  };
  const POCKET_LABEL_COLOR = (n) => (n >= 5 ? "#ffffff" : "#7c2d12");

  // -------- Public: render Rohini overview --------
  async function renderRohiniMap(containerId, onSectorClick) {
    const el = document.getElementById(containerId);
    if (!el) return null;
    el.innerHTML = "";

    const map = L.map(el, {
      center: [28.74, 77.085],
      zoom: 13,
      zoomControl: true,
      scrollWheelZoom: false,
    });
    L.tileLayer(TILE_URL, TILE_OPTS).addTo(map);

    const sectors = await fetch("data/sectors.geojson").then((r) => r.json());
    const layer = L.geoJSON(sectors, {
      style: (feat) => {
        const is28 = feat.properties.sector === 28;
        return {
          color: is28 ? COLOR_HIGHLIGHT : COLOR_OTHER,
          weight: is28 ? 3 : 1.2,
          opacity: is28 ? 0.95 : 0.55,
          fillColor: is28 ? COLOR_HIGHLIGHT : COLOR_OTHER_FILL,
          fillOpacity: is28 ? 0.35 : 0.18,
        };
      },
      onEachFeature: (feat, lyr) => {
        const s = feat.properties.sector;
        const has = feat.properties.has_data;
        lyr.bindTooltip(
          `Sector ${s}${has ? " · 90 registrations" : ""}`,
          { sticky: true, direction: "top" }
        );
        lyr.on("click", () => onSectorClick && onSectorClick(s, has));
        lyr.on("mouseover", () => lyr.setStyle({ weight: 3, fillOpacity: 0.4 }));
        lyr.on("mouseout",  () => lyr.setStyle({
          weight: s === 28 ? 3 : 1.2,
          fillOpacity: s === 28 ? 0.35 : 0.18,
        }));
        lyr.on("keypress", (e) => {
          if (e.originalEvent.key === "Enter") lyr.fire("click");
        });
      },
    }).addTo(map);

    map.fitBounds(layer.getBounds(), { padding: [16, 16] });
    map.once("focus", () => map.scrollWheelZoom.enable());
    el.addEventListener("click", () => map.scrollWheelZoom.enable(), { once: true });

    return { map, layer };
  }

  // -------- Public: render Sector 28 pocket map --------
  async function renderSector28Map(containerId, onPocketClick, activePocket) {
    const el = document.getElementById(containerId);
    if (!el) return null;
    el.innerHTML = "";

    const map = L.map(el, {
      center: [28.756, 77.100],
      zoom: 15,
      zoomControl: true,
      scrollWheelZoom: false,
    });
    L.tileLayer(TILE_URL, TILE_OPTS).addTo(map);

    // Sector 28 outline (for context)
    const sectors = await fetch("data/sectors.geojson").then((r) => r.json());
    const s28 = sectors.features.find((f) => f.properties.sector === 28);
    if (s28) {
      L.geoJSON(s28, {
        style: {
          color: "#1e3a8a",
          weight: 2.5,
          opacity: 0.8,
          fillColor: "#1e3a8a",
          fillOpacity: 0.04,
          dashArray: "6 4",
        },
      }).addTo(map);
    }

    // Pocket polygons with heatmap color
    const pocketGeo = await fetch("data/sector-28-pockets.geojson").then((r) => r.json());
    // Lookup count from state (passed via global window)
    const counts = (window.RPP_STATE && window.RPP_STATE.pocketCounts) || {};

    const pocketLayer = L.geoJSON(pocketGeo, {
      style: (feat) => {
        const id = feat.properties.pocket;
        const n = counts[id] || 0;
        const isActive = id === activePocket;
        return {
          color: isActive ? "#0f172a" : "#ffffff",
          weight: isActive ? 4 : 1.5,
          opacity: 1,
          fillColor: POCKET_COLOR(n),
          fillOpacity: n === 0 ? 0.15 : 0.7,
          dashArray: n === 0 ? "4 3" : null,
        };
      },
      onEachFeature: (feat, lyr) => {
        const id = feat.properties.pocket;
        const n = counts[id] || 0;
        const block = feat.properties.block;
        const blockLabel = block === "GH" ? "DDA Flats" : block === "Unknown" ? "Unmapped" : `Block ${block}`;
        lyr.bindTooltip(
          `<strong>${id}</strong> · ${blockLabel}<br>${n} registration${n === 1 ? "" : "s"}`,
          { sticky: true, direction: "top" }
        );
        lyr.on("click", () => onPocketClick && onPocketClick(id));
        lyr.on("mouseover", () => {
          lyr.setStyle({ weight: 3, fillOpacity: 0.85 });
          lyr.openTooltip();
        });
        lyr.on("mouseout", () => {
          const isActive = id === activePocket;
          lyr.setStyle({
            weight: isActive ? 4 : 1.5,
            fillOpacity: n === 0 ? 0.15 : 0.7,
            color: isActive ? "#0f172a" : "#ffffff",
          });
        });
      },
    }).addTo(map);

    // Labels
    pocketLayer.eachLayer((lyr) => {
      const id = lyr.feature.properties.pocket;
      const n = counts[id] || 0;
      const c = lyr.getBounds().getCenter();
      const label = n > 0
        ? `<div class="pkt-label"><b>${id}</b><span>${n}</span></div>`
        : `<div class="pkt-label dim"><b>${id}</b></div>`;
      L.marker(c, {
        icon: L.divIcon({
          className: "pkt-label-wrap",
          html: label,
          iconSize: null,
          iconAnchor: [0, 0],
        }),
        interactive: false,
      }).addTo(map);
    });

    map.fitBounds(pocketLayer.getBounds(), { padding: [24, 24] });
    el.addEventListener("click", () => map.scrollWheelZoom.enable(), { once: true });

    return { map, layer: pocketLayer };
  }

  // Inject CSS for labels
  function injectCss() {
    if (document.getElementById("rpp-map-css")) return;
    const css = document.createElement("style");
    css.id = "rpp-map-css";
    css.textContent = `
      .pkt-label-wrap { background: transparent; border: 0; }
      .pkt-label {
        font: 700 12px system-ui, -apple-system, "Segoe UI", sans-serif;
        color: #fff;
        text-align: center;
        text-shadow: 0 1px 2px rgba(0,0,0,0.6);
        pointer-events: none;
        line-height: 1.15;
        white-space: nowrap;
      }
      .pkt-label b { display: block; font-size: 13px; }
      .pkt-label span { font-size: 11px; opacity: 0.95; }
      .pkt-label.dim { color: #475569; text-shadow: 0 1px 2px rgba(255,255,255,0.6); opacity: 0.8; }
      .leaflet-container { font: inherit; border-radius: 12px; }
      .leaflet-control-attribution { font-size: 10px; }
    `;
    document.head.appendChild(css);
  }

  window.RPPMap = {
    renderRohiniMap,
    renderSector28Map,
    injectCss,
  };
})();
