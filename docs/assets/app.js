// Rohini Property Pulse — vanilla JS, no build step.
(() => {
  "use strict";

  const PAGE_SIZE = 50;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const ARTICLE_CLASS = {
    "Sale Deed": "badge-sale",
    "Gift Deed": "badge-gift",
    "Relinquishment Deed": "badge-relinquishment",
    "Sale Agreement": "badge-agreement",
  };
  const ARTICLE_NAMES = {
    "Certificate of sale": "Certificate of Sale",
    "Rectification deed": "Rectification Deed",
  };
  const SORTS = [
    ["date-desc", "Newest first"],
    ["date-asc", "Oldest first"],
    ["area-desc", "Largest plot"],
    ["area-asc", "Smallest plot"],
  ];

  const state = {
    meta: null,
    registrations: [],
    allMeta: null,
    allRegistrations: [],
    txIndex: new Map(),
    month: "",
    sector: "",
    summary: { pockets: {} },
    route: { name: "overview", params: {}, query: {} },
  };
  let currentMap = null;
  let renderSeq = 0;
  let leagueSort = { key: "records", dir: -1 };
  let modalOpener = null;
  let lastPath = null;
  let appInitialized = false;
  let dataPromise = null;

  // -------- DOM helpers --------
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const esc = (s) =>
    s == null ? "" : String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  // -------- Formatting --------
  const fmtNum = (n, digits = 0) =>
    n == null || Number.isNaN(Number(n)) ? "—" : Number(n).toLocaleString("en-IN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  const pad = (n) => String(n).padStart(2, "0");
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
  const has = (v) => v != null && v > 0;
  const plural = (n, one, many = `${one}s`) => `${fmtNum(n)} ${n === 1 ? one : many}`;

  // Dates are formatted by hand so output does not depend on browser locale data.
  const dayOf = (r) => r._day || (r.registration_date || "").slice(0, 10);
  function shiftDay(iso, n) {
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d) + n * 86400000).toISOString().slice(0, 10);
  }
  function mondayOf(iso) {
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    const dow = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
    return shiftDay(iso, -dow);
  }
  function fmtDay(iso) {
    if (!iso) return "—";
    const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
    return `${pad(d)} ${MONTHS[m - 1]} ${y}`;
  }
  function fmtDayShort(iso) {
    const [, m, d] = iso.slice(0, 10).split("-").map(Number);
    return `${pad(d)} ${MONTHS[m - 1]}`;
  }
  function fmtRange(a, b) {
    if (!a || !b) return "—";
    const [ya, ma, da] = a.split("-").map(Number);
    const [yb, mb, db] = b.split("-").map(Number);
    if (ya === yb) return `${pad(da)} ${MONTHS[ma - 1]} – ${pad(db)} ${MONTHS[mb - 1]} ${yb}`;
    return `${fmtDay(a)} – ${fmtDay(b)}`;
  }
  function fmtDateTime(iso) {
    if (!iso) return "—";
    const day = fmtDay(iso);
    const t = iso.slice(11, 16);
    if (!t) return day;
    let [h, mi] = t.split(":").map(Number);
    const ap = h >= 12 ? "pm" : "am";
    h = h % 12 || 12;
    return `${day}, ${h}:${pad(mi)} ${ap}`;
  }
  function monthLabel(id) {
    if (!id) return "All months";
    const [y, m] = id.split("-").map(Number);
    return `${MONTHS[m - 1]} ${y}`;
  }
  const titleCase = (s) =>
    s
      ? String(s).trim().toLowerCase()
        .replace(/(^|[\s.\-\/(&,])([a-z])/g, (_, p, c) => p + c.toUpperCase())
        .replace(/\b(dda|lig|mig|sr|sec|blk|pkt|nh|dl|upic)\b/gi, (w) => w.toUpperCase())
      : "";
  const articleName = (raw) => {
    const base = String(raw || "").replace(/\s*-\s*\d+\s*$/, "").trim();
    return ARTICLE_NAMES[base] || base || "Other";
  };
  const articleBadge = (name) =>
    `<span class="badge ${ARTICLE_CLASS[name] || "badge-default"}">${esc(name)}</span>`;
  const isSectorPocket = (p) => /^S\d+$/.test(p);
  const pocketLabel = (p) =>
    p === "Unknown" ? "Unmapped" :
    isSectorPocket(p) ? `Sector ${p.slice(1)}` :
    /^[A-Z]$/.test(p) ? `Block ${p} (unnumbered)` : p;
  const pocketTitle = (p) =>
    p === "Unknown" ? "Unmapped plots" :
    /^[A-Z]$/.test(p) ? `Block ${p} (unnumbered)` : `Pocket ${p}`;
  const blockLabel = (b) =>
    b === "GH" ? "DDA Flats (LIG/MIG)" :
    b === "Unknown" ? "Unmapped" :
    isSectorPocket(b) ? `Sector ${b.slice(1)}` : `Block ${b}`;
  const pocketOrder = (pid) => {
    if (pid === "Unknown") return [9, 0];
    if (pid.startsWith("GH-")) return [2, parseInt(pid.slice(3), 10) || 0];
    if (isSectorPocket(pid)) return [3, parseInt(pid.slice(1), 10) || 0];
    const [block, n] = pid.split("-");
    return [block === "A" ? 0 : block === "C" ? 1 : 4, parseInt(n, 10) || 0];
  };
  const party = (name) => esc(titleCase(name) || "Not recorded");
  const parties = (r) =>
    `${party(r.seller && r.seller.name)}<span class="arrow" aria-hidden="true">→</span>${party(r.purchaser && r.purchaser.name)}`;
  const placeText = (r) =>
    [isSectorPocket(r.property.pocket) ? null : pocketLabel(r.property.pocket),
      `Sector ${r.sector}`,
      r.property.raw_plot_number ? `Plot ${r.property.raw_plot_number}` : null]
      .filter(Boolean).join(" · ");
  const byDateDesc = (items) =>
    items.slice().sort((a, b) => (b.registration_date || "").localeCompare(a.registration_date || ""));

  // -------- URL state --------
  function safeDecode(s) {
    try { return decodeURIComponent(s); } catch (e) { return s; }
  }
  function parseHash() {
    const raw = location.hash.replace(/^#/, "");
    const cut = raw.indexOf("?");
    const path = cut >= 0 ? raw.slice(0, cut) : raw;
    const query = Object.fromEntries(new URLSearchParams(cut >= 0 ? raw.slice(cut + 1) : ""));
    const parts = path.split("/").filter(Boolean).map(safeDecode);
    return { parts, query };
  }
  function parseRoute() {
    const { parts, query } = parseHash();
    if (parts[0] === "about") return { name: "about", params: {}, query };
    if (parts[0] === "transactions") return { name: "list", params: {}, query };
    if (parts[0] === "sector" && parts[1]) {
      if (parts[2] === "pocket" && parts[3])
        return { name: "pocket", params: { sector: parts[1], pocket: parts[3] }, query };
      return { name: "sector", params: { sector: parts[1] }, query };
    }
    return { name: "overview", params: {}, query };
  }
  // Writes filters into the hash without adding history entries or re-rendering.
  function setQuery(patch) {
    const { parts, query } = parseHash();
    const next = { ...query };
    for (const [k, v] of Object.entries(patch)) {
      if (v == null || v === "") delete next[k];
      else next[k] = String(v);
    }
    const qs = new URLSearchParams(next).toString();
    const path = "#/" + parts.map(encodeURIComponent).join("/");
    const url = qs ? `${path}?${qs}` : path;
    if (url !== location.hash) history.replaceState(null, "", url);
  }
  // The month lives in the URL, so every in-app link carries it forward.
  function withMonth(hash) {
    if (!state.month) return hash;
    const cut = hash.indexOf("?");
    const path = cut >= 0 ? hash.slice(0, cut) : hash;
    const query = new URLSearchParams(cut >= 0 ? hash.slice(cut + 1) : "");
    if (query.has("month")) return hash;
    query.set("month", state.month);
    return `${path}?${query}`;
  }
  function go(hash) {
    const target = withMonth(hash);
    if (location.hash === target) render();
    else location.hash = target;
  }
  const isValidMonth = (id) => (state.allMeta.months || []).some((m) => m.id === id);

  function syncFromRoute(r) {
    const q = r.query || {};
    let sector = state.sector;
    if (r.name === "sector" || r.name === "pocket") sector = String(r.params.sector);
    else if (r.name === "list" && q.sector !== undefined) sector = q.sector === "all" ? "" : q.sector;
    const month = q.month !== undefined && isValidMonth(q.month) ? q.month : "";
    if (sector !== state.sector || month !== state.month) {
      state.sector = sector;
      state.month = month;
      applyScope();
    }
  }

  // -------- Routing --------
  function setActiveNav(name) {
    $$(".primary-nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === name));
  }
  function renderBreadcrumb(items) {
    $("#breadcrumbs").innerHTML = items
      .map((it, i) => {
        const sep = i > 0 ? `<span class="sep" aria-hidden="true">›</span>` : "";
        const body = it.href
          ? `<a href="${esc(it.href)}">${esc(it.label)}</a>`
          : `<span class="current" aria-current="page">${esc(it.label)}</span>`;
        return sep + body;
      })
      .join("");
  }

  // -------- Data load and scope --------
  async function loadData() {
    if (state.allRegistrations.length) return;
    if (!dataPromise) {
      dataPromise = Promise.all([
        fetch("data/meta.json").then((r) => r.json()),
        fetch("data/registrations.json").then((r) => r.json()),
      ]);
    }
    const [meta, reg] = await dataPromise;
    state.allMeta = meta;
    state.allRegistrations = reg.items.map((r) => {
      r._article = articleName(r.article);
      r._day = (r.registration_date || "").slice(0, 10);
      return r;
    });
    state.txIndex = new Map(state.allRegistrations.map((r) => [String(r.id), r]));
    applyScope();
  }

  // Scope = sector + month. Everything on screen is derived from this subset.
  function applyScope() {
    state.registrations = state.allRegistrations.filter(
      (r) =>
        (!state.sector || String(r.sector) === String(state.sector)) &&
        (!state.month || r.month === state.month)
    );
    state.meta = buildMeta(state.registrations);
    state.summary = summarize(state.registrations);
  }

  function buildMeta(items) {
    const base = state.allMeta || {};
    const dates = items.map(dayOf).filter(Boolean).sort();
    const articles = {};
    const pockets = new Set();
    const sectors = new Set();
    for (const r of items) {
      articles[r._article] = (articles[r._article] || 0) + 1;
      pockets.add(r.property.pocket);
      sectors.add(String(r.sector));
    }
    return {
      ...base,
      total_registrations: items.length,
      unique_pockets: pockets.size,
      sector_count: sectors.size,
      date_from: dates[0] || null,
      date_to: dates[dates.length - 1] || null,
      articles,
    };
  }

  function summarize(items) {
    const pockets = {};
    for (const r of items) {
      const pid = r.property.pocket;
      const d = r.property.description || {};
      const p = pockets[pid] || (pockets[pid] = {
        block: r.property.block, count: 0, articles: {}, plot_areas: [], plinth_areas: [],
        floors: [], construction: {}, earliest: null, latest: null,
      });
      p.count += 1;
      p.articles[r._article] = (p.articles[r._article] || 0) + 1;
      const day = dayOf(r);
      if (day) {
        if (!p.earliest || day < p.earliest) p.earliest = day;
        if (!p.latest || day > p.latest) p.latest = day;
      }
      if (d.plot_area_sqm != null) p.plot_areas.push(d.plot_area_sqm);
      if (d.plinth_area_sqm != null) p.plinth_areas.push(d.plinth_area_sqm);
      if (d.floors != null) p.floors.push(d.floors);
      if (d.construction_type) p.construction[d.construction_type] = (p.construction[d.construction_type] || 0) + 1;
    }
    const avg = (xs) => (xs.length ? Math.round((xs.reduce((a, b) => a + b, 0) / xs.length) * 100) / 100 : null);
    const out = {};
    Object.keys(pockets)
      .sort((a, b) => {
        const [ga, na] = pocketOrder(a);
        const [gb, nb] = pocketOrder(b);
        return ga - gb || na - nb;
      })
      .forEach((pid) => {
        const p = pockets[pid];
        out[pid] = {
          block: p.block,
          count: p.count,
          articles: p.articles,
          avg_plot_area_sqm: avg(p.plot_areas),
          avg_plinth_area_sqm: avg(p.plinth_areas),
          avg_floors: avg(p.floors),
          construction: p.construction,
          earliest: p.earliest,
          latest: p.latest,
        };
      });
    return { pockets: out };
  }

  function weeklySeries(items) {
    if (!items.length) return [];
    const counts = new Map();
    for (const r of items) {
      const w = mondayOf(dayOf(r));
      counts.set(w, (counts.get(w) || 0) + 1);
    }
    const keys = [...counts.keys()].sort();
    const out = [];
    for (let w = keys[0]; w <= keys[keys.length - 1]; w = shiftDay(w, 7)) {
      out.push({ week: w, count: counts.get(w) || 0 });
    }
    return out;
  }

  function sectorStats(items) {
    const map = new Map();
    for (const r of items) {
      const s = String(r.sector);
      let x = map.get(s);
      if (!x) {
        x = { sector: s, records: 0, sale: 0, first: null, last: null, pockets: new Set() };
        map.set(s, x);
      }
      x.records += 1;
      if (r._article === "Sale Deed") x.sale += 1;
      const d = dayOf(r);
      if (!x.first || d < x.first) x.first = d;
      if (!x.last || d > x.last) x.last = d;
      x.pockets.add(r.property.pocket);
    }
    return [...map.values()];
  }

  // -------- Selects --------
  function refreshSelects() {
    const sel = $("#sector-select");
    const msel = $("#month-select");
    if (!sel || !msel || !state.allRegistrations.length) return;
    const bySector = {};
    const byMonth = {};
    for (const r of state.allRegistrations) {
      if (!state.month || r.month === state.month) bySector[r.sector] = (bySector[r.sector] || 0) + 1;
      if (!state.sector || String(r.sector) === String(state.sector)) byMonth[r.month] = (byMonth[r.month] || 0) + 1;
    }
    const inMonth = Object.values(bySector).reduce((a, b) => a + b, 0);
    const inSector = Object.values(byMonth).reduce((a, b) => a + b, 0);
    const sectors = [...new Set(state.allRegistrations.map((r) => String(r.sector)))]
      .sort((a, b) => Number(a) - Number(b));
    sel.innerHTML = `<option value="">All sectors (${fmtNum(inMonth)})</option>` +
      sectors.map((s) =>
        `<option value="${esc(s)}"${bySector[s] ? "" : " disabled"}>Sector ${esc(s)} (${fmtNum(bySector[s] || 0)})</option>`
      ).join("");
    sel.value = state.sector || "";
    msel.innerHTML = `<option value="">All months (${fmtNum(inSector)})</option>` +
      (state.allMeta.months || []).map((m) =>
        `<option value="${esc(m.id)}"${byMonth[m.id] ? "" : " disabled"}>${esc(monthLabel(m.id))} (${fmtNum(byMonth[m.id] || 0)})</option>`
      ).join("");
    msel.value = state.month || "";
  }

  function updatePeriodNote() {
    const note = $("#period-note");
    if (!note) return;
    note.textContent = `${state.sector ? `Sector ${state.sector}` : "All sectors"} · ${monthLabel(state.month)} · ${plural(state.registrations.length, "record")}`;
  }

  function setRppState() {
    const sectorCounts = {};
    for (const r of state.allRegistrations) {
      if (!state.month || r.month === state.month) sectorCounts[r.sector] = (sectorCounts[r.sector] || 0) + 1;
    }
    window.RPP_STATE = { sectorCounts, pockets: state.summary.pockets };
  }

  function setMonth(id) {
    state.month = id || "";
    setQuery({ month: state.month || null });
    applyScope();
    render();
  }

  function onSectorChange(e) {
    state.sector = e.target.value;
    applyScope();
    const name = state.route.name;
    if (name === "list") {
      setQuery({ sector: state.sector || "all" });
      render();
      return;
    }
    if (name === "about") {
      updatePeriodNote();
      return;
    }
    go(state.sector ? `#/sector/${state.sector}` : "#/");
  }

  // -------- Shared components --------
  function pageHead(title, sub) {
    return `<header class="page-head"><div><h1>${title}</h1>${sub ? `<p>${sub}</p>` : ""}</div></header>`;
  }
  const kpi = (label, value, sub, cls = "") =>
    `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value${cls ? ` ${cls}` : ""}">${value}</div><div class="kpi-sub">${sub}</div></div>`;

  function kpiStrip() {
    const m = state.meta;
    const total = m.total_registrations;
    const deeds = m.articles["Sale Deed"] || 0;
    const latest = m.date_to;
    let last7 = 0;
    let prev7 = 0;
    if (latest) {
      const from7 = shiftDay(latest, -6);
      const from14 = shiftDay(latest, -13);
      for (const r of state.registrations) {
        const d = dayOf(r);
        if (d >= from7 && d <= latest) last7 += 1;
        else if (d >= from14 && d < from7) prev7 += 1;
      }
    }
    return `<section class="kpi-strip" aria-label="Key figures">
      ${kpi("Registrations", fmtNum(total), `${plural(m.sector_count, "sector", "sectors")} · ${monthLabel(state.month)}`)}
      ${kpi("Sale deeds", fmtNum(deeds), `${pct(deeds, total)}% of registrations`)}
      ${kpi("Last 7 days", fmtNum(last7), `${fmtNum(prev7)} in the 7 days before`)}
      ${kpi("Latest record", latest ? fmtDay(latest) : "—", m.date_from ? `First record ${fmtDay(m.date_from)}` : "No records", "text")}
    </section>`;
  }

  function coverageNotice() {
    return `<div class="notice" role="note"><strong>Coverage varies by sector.</strong>
      Sectors started recording at different dates, so compare sectors and months with care.
      <a href="#/about">How to read this</a></div>`;
  }

  function emptyState(msg) {
    return `<div class="empty">${msg} <a href="#/">Back to overview</a></div>`;
  }

  function mapLegend(withSelected) {
    return `<div class="legend">
      <span><span class="swatch sw-data"></span>With records</span>
      <span><span class="swatch sw-none"></span>No records</span>
      ${withSelected ? `<span><span class="swatch sw-sel"></span>Selected</span>` : ""}
    </div>`;
  }

  function destroyMap() {
    if (currentMap) {
      currentMap.remove();
      currentMap = null;
    }
  }
  function trackMap(promise) {
    promise.then((res) => { if (res) currentMap = res.map; }).catch((err) => console.error(err));
  }

  const barRow = (nameHtml, value, max) =>
    `<div class="bar-row"><span class="bar-name">${nameHtml}</span><span class="bar-track" aria-hidden="true"><span class="bar-fill" style="width:${max ? ((value / max) * 100).toFixed(1) : 0}%"></span></span><span class="bar-value">${fmtNum(value)}</span></div>`;
  function barList(entries, nameFn, emptyMsg) {
    if (!entries.length) return `<div class="empty">${emptyMsg}</div>`;
    const max = Math.max(...entries.map((e) => e[1]), 1);
    return entries.map(([k, v]) => barRow(nameFn(k), v, max)).join("");
  }

  function colChart(cols, maxH = 120, dense = false) {
    if (!cols.length || cols.every((c) => !c.value)) return `<div class="empty">No records in this view</div>`;
    const max = Math.max(...cols.map((c) => c.value), 1);
    return `<div class="col-chart${dense ? " dense" : ""}">${cols.map((c) => {
      const h = c.value ? Math.max(3, Math.round((c.value / max) * maxH)) : 0;
      const inner = `<div class="col-plot"><div class="col-bar" style="height:${h}px"><span class="col-val">${c.value ? fmtNum(c.value) : ""}</span></div></div>
        <div class="col-label">${esc(c.label || "")}</div>
        <div class="col-sub">${esc(c.sub || "")}</div>`;
      if (c.id) {
        return `<button type="button" class="col is-link${c.active ? " is-active" : ""}" data-month="${esc(c.id)}" aria-pressed="${c.active ? "true" : "false"}" title="${esc(c.title || "")}">${inner}</button>`;
      }
      return `<div class="col" title="${esc(c.title || "")}">${inner}</div>`;
    }).join("")}</div>`;
  }

  // -------- Overview --------
  function officesText() {
    return (state.allMeta.source_offices || []).map((o) => o.taluka).join(", ");
  }

  function viewOverview() {
    setActiveNav("overview");
    renderBreadcrumb([{ label: "Overview" }]);
    const m = state.meta;
    $("#view").innerHTML = `
      ${pageHead("Rohini property registrations",
        `${fmtRange(m.date_from, m.date_to)} · Registration offices: ${esc(officesText())}`)}
      ${coverageNotice()}
      ${kpiStrip()}
      <section class="card">
        <div class="card-head"><h2>Map of Rohini sectors</h2><span class="hint">Click a sector with records to open it</span></div>
        <div class="map-toolbar"><div>Sectors 18–38 · OpenStreetMap</div>${mapLegend(false)}</div>
        <div class="map-wrap leaflet-wrap" id="sector-map" style="height:440px"></div>
      </section>
      <section class="card">
        <div class="card-head"><h2>Sectors compared</h2><span class="hint">Click a column heading to sort</span></div>
        <div id="league"></div>
      </section>
      <div class="cols-2">
        <section class="card">
          <div class="card-head"><h2>Registrations by month</h2></div>
          <p class="warn">Sectors were added at different times, so monthly totals are not like-for-like. The line under each month shows how many sectors had records. Click a month to filter.</p>
          <div id="month-chart"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Registrations per week</h2></div>
          <div id="week-chart"></div>
        </section>
      </div>
      <div class="cols-2">
        <section class="card">
          <div class="card-head"><h2>By article type</h2></div>
          <div class="bar-chart" id="article-chart"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>Latest registrations</h2><a href="#/transactions">All transactions →</a></div>
          <div id="recent"></div>
        </section>
      </div>`;
    setRppState();
    trackMap(window.RPPMap.renderRohiniMap("sector-map", (sector, hasData) => {
      if (hasData) go(`#/sector/${sector}`);
    }, null));
    renderLeague();
    renderMonthChart();
    renderWeekChart("week-chart", state.registrations);
    $("#article-chart").innerHTML = barList(
      Object.entries(state.meta.articles).sort((a, b) => b[1] - a[1]), articleBadge, "No records in this view");
    renderRecent();
  }

  function renderLeague() {
    const root = $("#league");
    if (!root) return;
    const stats = sectorStats(state.allRegistrations.filter((r) => !state.month || r.month === state.month));
    const val = (s) => ({
      name: Number(s.sector), records: s.records, sale: s.sale, first: s.first, last: s.last, pockets: s.pockets.size,
    })[leagueSort.key];
    stats.sort((a, b) => {
      const x = val(a);
      const y = val(b);
      return (x > y ? 1 : x < y ? -1 : 0) * leagueSort.dir;
    });
    const cols = [
      ["name", "Sector", false],
      ["records", "Records", true],
      ["sale", "Sale deeds", true],
      ["first", "Records from", false],
      ["last", "Last record", false],
      ["pockets", "Pockets", true],
    ];
    const heads = cols.map(([k, label, num]) => {
      const active = leagueSort.key === k;
      const arrow = active ? (leagueSort.dir > 0 ? " ▲" : " ▼") : "";
      const aria = active ? (leagueSort.dir > 0 ? "ascending" : "descending") : "none";
      return `<th scope="col"${num ? ' class="num"' : ""} aria-sort="${aria}"><button type="button" class="th-btn" data-sort="${k}">${label}${arrow}</button></th>`;
    }).join("");
    const rows = stats.map((s) => `<tr class="${String(state.sector) === s.sector ? "is-selected" : ""}">
        <td><a href="#/sector/${esc(s.sector)}">Sector ${esc(s.sector)}</a></td>
        <td class="num">${fmtNum(s.records)}</td>
        <td class="num">${fmtNum(s.sale)}</td>
        <td>${fmtDay(s.first)}</td>
        <td>${fmtDay(s.last)}</td>
        <td class="num">${s.sector === "28" ? fmtNum(s.pockets.size) : "—"}</td>
      </tr>`).join("");
    root.innerHTML = `<div class="table-wrap"><table class="tx-table league">
        <thead><tr>${heads}</tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <p class="fine">Pockets are split out only for Sector 28. Other sectors are recorded as a single unit. "Records from" and "Last record" show the first and last registration in each sector. A late start may mean the sector was added later, or that no registrations were recorded earlier.</p>`;
  }

  function renderMonthChart() {
    const root = $("#month-chart");
    if (!root) return;
    const sectorItems = state.allRegistrations.filter((r) => !state.sector || String(r.sector) === String(state.sector));
    const cols = (state.allMeta.months || []).map((m) => {
      const items = sectorItems.filter((r) => r.month === m.id);
      const sectors = new Set(items.map((r) => String(r.sector))).size;
      return {
        id: m.id,
        value: items.length,
        label: MONTHS[Number(m.id.slice(5, 7)) - 1],
        sub: `${sectors} sector${sectors === 1 ? "" : "s"}`,
        title: `${monthLabel(m.id)}: ${plural(items.length, "record")} from ${plural(sectors, "sector")}`,
        active: state.month === m.id,
      };
    });
    root.innerHTML = colChart(cols, 120);
  }

  function renderWeekChart(rootId, items) {
    const root = $(`#${rootId}`);
    if (!root) return;
    const weeks = weeklySeries(items);
    let prev = "";
    const cols = weeks.map((w) => {
      const mon = w.week.slice(5, 7);
      const label = mon !== prev ? MONTHS[Number(mon) - 1] : "";
      prev = mon;
      return { value: w.count, label, title: `Week of ${fmtDay(w.week)}: ${plural(w.count, "record")}` };
    });
    root.innerHTML = colChart(cols, 120, true) + (weeks.length
      ? `<p class="fine">One bar per week, starting Monday, from ${fmtDay(weeks[0].week)} to ${fmtDay(weeks[weeks.length - 1].week)}. The first and last weeks can be partial.</p>`
      : "");
  }

  function renderRecent() {
    const root = $("#recent");
    if (!root) return;
    const items = byDateDesc(state.registrations).slice(0, 10);
    root.innerHTML = items.length
      ? `<ul class="recent">${items.map((r) => `<li><button type="button" class="recent-item" data-tx="${esc(r.id)}">
          <span class="recent-date">${fmtDayShort(dayOf(r))}</span>
          <span class="recent-main">${articleBadge(r._article)}<span class="recent-parties">${parties(r)}</span></span>
          <span class="recent-meta">${esc(placeText(r))}</span>
        </button></li>`).join("")}</ul>`
      : `<div class="empty">No records in this view</div>`;
  }

  // -------- Sector views --------
  function viewSector(sid) {
    if (sid === "28") return viewSector28();
    return viewSectorGeneric(sid);
  }

  function viewSectorGeneric(sid) {
    setActiveNav("sector");
    renderBreadcrumb([{ label: "Overview", href: "#/" }, { label: `Sector ${sid}` }]);
    const m = state.meta;
    if (!state.registrations.length) {
      $("#view").innerHTML = pageHead(`Sector ${esc(sid)}`, `No records for this sector in ${esc(monthLabel(state.month))}.`) +
        emptyState("Try another month or sector.");
      return;
    }
    $("#view").innerHTML = `
      ${pageHead(`Sector ${esc(sid)}`,
        `Records ${fmtRange(m.date_from, m.date_to)} · Pockets are not split for this sector`)}
      ${kpiStrip()}
      <section class="card">
        <div class="card-head"><h2>Sector ${esc(sid)} on the map</h2><span class="hint">Click another sector with records to switch</span></div>
        <div class="map-toolbar"><div>Sectors 18–38 · OpenStreetMap</div>${mapLegend(true)}</div>
        <div class="map-wrap leaflet-wrap" id="sector-map" style="height:380px"></div>
      </section>
      <div class="cols-2">
        <section class="card"><div class="card-head"><h2>By article type</h2></div><div class="bar-chart" id="article-chart"></div></section>
        <section class="card"><div class="card-head"><h2>Registrations per week</h2></div><div id="week-chart"></div></section>
      </div>
      <section class="card">
        <div class="card-head"><h2>Transactions</h2></div>
        <div id="tx-browser"></div>
      </section>`;
    setRppState();
    trackMap(window.RPPMap.renderRohiniMap("sector-map", (sector, hasData) => {
      if (hasData) go(`#/sector/${sector}`);
    }, Number(sid)));
    $("#article-chart").innerHTML = barList(
      Object.entries(m.articles).sort((a, b) => b[1] - a[1]), articleBadge, "No records");
    renderWeekChart("week-chart", state.registrations);
    mountTxBrowser($("#tx-browser"), state.registrations, { sectorCol: false });
  }

  function viewSector28() {
    setActiveNav("sector");
    renderBreadcrumb([{ label: "Overview", href: "#/" }, { label: "Sector 28" }]);
    const m = state.meta;
    if (!state.registrations.length) {
      $("#view").innerHTML = pageHead("Sector 28", `No records in ${esc(monthLabel(state.month))}.`) +
        emptyState("Try another month.");
      return;
    }
    const s = state.summary;
    const blockCounts = {};
    for (const r of state.registrations) {
      const b = r.property.block || "Unknown";
      blockCounts[b] = (blockCounts[b] || 0) + 1;
    }
    const blockLine = Object.entries(blockCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([b, n]) => `<span title="${esc(blockLabel(b))}">${esc(blockLabel(b))} <strong>${fmtNum(n)}</strong></span>`)
      .join('<span class="sep-dot" aria-hidden="true">·</span>');
    const leaderboard = Object.entries(s.pockets).sort(
      (a, b) => (a[0] === "Unknown") - (b[0] === "Unknown") || b[1].count - a[1].count);

    $("#view").innerHTML = `
      ${pageHead("Sector 28", `Records ${fmtRange(m.date_from, m.date_to)} · ${esc(monthLabel(state.month))}`)}
      ${kpiStrip()}
      <section class="card">
        <div class="card-head"><h2>Pocket map</h2><span class="hint">Click a pocket with records to open it</span></div>
        <div class="map-toolbar"><div>Sector 28 boundary · OpenStreetMap · darker pocket = more records</div>${mapLegend(true)}</div>
        <div class="map-wrap leaflet-wrap" id="pocket-map" style="height:480px"></div>
      </section>
      <section class="card">
        <div class="card-head"><h2>Pocket leaderboard</h2><span class="hint blocks-line">${blockLine}</span></div>
        <div class="table-wrap">
          <table class="tx-table leaderboard">
            <thead><tr>
              <th scope="col" class="num">#</th><th scope="col">Pocket</th><th scope="col">Block</th>
              <th scope="col" class="num">Records</th><th scope="col" class="num">Avg plot (m²)</th><th scope="col">Top article</th>
            </tr></thead>
            <tbody>${leaderboard.map(([pid, p], i) => {
              const top = Object.entries(p.articles).sort((a, b) => b[1] - a[1])[0];
              return `<tr>
                <td class="num">${i + 1}</td>
                <td><a href="#/sector/28/pocket/${encodeURIComponent(pid)}">${esc(pocketLabel(pid))}</a></td>
                <td>${esc(blockLabel(p.block))}</td>
                <td class="num">${fmtNum(p.count)}</td>
                <td class="num">${p.avg_plot_area_sqm != null ? fmtNum(p.avg_plot_area_sqm, 1) : "—"}</td>
                <td>${articleBadge(top[0])}</td>
              </tr>`;
            }).join("")}</tbody>
          </table>
        </div>
      </section>
      <div class="cols-2">
        <section class="card"><div class="card-head"><h2>Registrations by pocket</h2></div><div class="bar-chart" id="pocket-chart"></div></section>
        <section class="card"><div class="card-head"><h2>By article type</h2></div><div class="bar-chart" id="article-chart"></div></section>
      </div>
      <section class="card"><div class="card-head"><h2>Registrations per week</h2></div><div id="week-chart"></div></section>
      <section class="card">
        <div class="card-head"><h2>Transactions</h2></div>
        <div id="tx-browser"></div>
      </section>`;
    setRppState();
    trackMap(window.RPPMap.renderSector28Map("pocket-map", (pocket) => {
      go(`#/sector/28/pocket/${encodeURIComponent(pocket)}`);
    }, null));
    $("#pocket-chart").innerHTML = barList(
      leaderboard.map(([pid, p]) => [pid, p.count]), (pid) => esc(pocketLabel(pid)), "No records");
    $("#article-chart").innerHTML = barList(
      Object.entries(m.articles).sort((a, b) => b[1] - a[1]), articleBadge, "No records");
    renderWeekChart("week-chart", state.registrations);
    mountTxBrowser($("#tx-browser"), state.registrations, { pocketFilter: true, sectorCol: false });
  }

  // -------- Pocket detail --------
  function viewPocket(params) {
    setActiveNav("sector");
    const pid = params.pocket;
    const p = state.summary.pockets[pid];
    renderBreadcrumb([
      { label: "Overview", href: "#/" },
      { label: "Sector 28", href: "#/sector/28" },
      { label: pocketTitle(pid) },
    ]);
    if (!p) {
      $("#view").innerHTML = pageHead(esc(pocketTitle(pid)), `No records in ${esc(monthLabel(state.month))}.`) +
        emptyState("Try another month.");
      return;
    }
    const items = byDateDesc(state.registrations.filter((r) => r.property.pocket === pid));
    const topArticle = Object.entries(p.articles).sort((a, b) => b[1] - a[1])[0];
    const topConstruction = Object.entries(p.construction || {}).sort((a, b) => b[1] - a[1])[0];
    $("#view").innerHTML = `
      ${pageHead(esc(pocketTitle(pid)),
        `${esc(blockLabel(p.block))} · Records ${fmtRange(p.earliest, p.latest)} · ${esc(monthLabel(state.month))}`)}
      <section class="kpi-strip" aria-label="Pocket figures">
        ${kpi("Registrations", fmtNum(p.count), `${pct(topArticle[1], p.count)}% are ${esc(topArticle[0])}`)}
        ${kpi("Top article", articleBadge(topArticle[0]), `${fmtNum(topArticle[1])} of ${fmtNum(p.count)}`, "text")}
        ${kpi("Average plot", p.avg_plot_area_sqm ? `${fmtNum(p.avg_plot_area_sqm, 1)} m²` : "—",
          p.avg_plinth_area_sqm ? `Average plinth ${fmtNum(p.avg_plinth_area_sqm, 1)} m²` : "Flat-type units")}
        ${kpi("Average floors", p.avg_floors ? fmtNum(p.avg_floors, 1) : "—",
          topConstruction ? `${esc(topConstruction[0])} construction` : "Construction not recorded")}
      </section>
      <div class="cols-2">
        <section class="card"><div class="card-head"><h2>By article type</h2></div><div class="bar-chart">${barList(
          Object.entries(p.articles).sort((a, b) => b[1] - a[1]), articleBadge, "No records")}</div></section>
        <section class="card"><div class="card-head"><h2>Registrations per week</h2></div><div id="week-chart"></div></section>
      </div>
      <section class="card">
        <div class="card-head"><h2>Transactions</h2></div>
        <div id="tx-browser"></div>
      </section>`;
    renderWeekChart("week-chart", items);
    mountTxBrowser($("#tx-browser"), items, { sectorCol: false });
  }

  // -------- Transactions (all sectors / sector 28) --------
  function viewList() {
    setActiveNav("list");
    const sid = state.sector;
    const crumbs = [{ label: "Overview", href: "#/" }];
    if (sid) crumbs.push({ label: `Sector ${sid}`, href: `#/sector/${sid}` });
    crumbs.push({ label: "Transactions" });
    renderBreadcrumb(crumbs);
    const m = state.meta;
    $("#view").innerHTML = `
      ${pageHead(sid ? `Sector ${esc(sid)} transactions` : "All transactions",
        `${plural(m.total_registrations, "record")} · ${fmtRange(m.date_from, m.date_to)} · ${esc(monthLabel(state.month))}`)}
      <section class="card">
        <div id="tx-browser"></div>
      </section>`;
    mountTxBrowser($("#tx-browser"), state.registrations, { pocketFilter: sid === "28", sectorCol: !sid });
  }

  // Shared transaction browser: filters, sort, paging. Filters are kept in the URL.
  function mountTxBrowser(root, items, { pocketFilter = false, sectorCol = false } = {}) {
    if (!root) return;
    const q = parseHash().query;
    const pockets = [...new Set(items.map((r) => r.property.pocket))]
      .sort((a, b) => {
        const [ga, na] = pocketOrder(a);
        const [gb, nb] = pocketOrder(b);
        return ga - gb || na - nb;
      });
    const articles = [...new Set(items.map((r) => r._article))].sort();
    const sortVal = SORTS.some(([k]) => k === q.sort) ? q.sort : "date-desc";
    root.innerHTML = `
      <div class="filters">
        <input type="search" id="tb-q" placeholder="Search name, address, plot or registration no." aria-label="Search transactions" value="${esc(q.q || "")}" />
        ${pocketFilter ? `<select id="tb-pocket" aria-label="Filter by pocket"><option value="">All pockets</option>${pockets.map((p) =>
          `<option value="${esc(p)}"${q.pocket === p ? " selected" : ""}>${esc(pocketLabel(p))}</option>`).join("")}</select>` : ""}
        <select id="tb-article" aria-label="Filter by article type"><option value="">All article types</option>${articles.map((a) =>
          `<option value="${esc(a)}"${q.article === a ? " selected" : ""}>${esc(a)}</option>`).join("")}</select>
        <select id="tb-sort" aria-label="Sort transactions">${SORTS.map(([k, l]) =>
          `<option value="${k}"${sortVal === k ? " selected" : ""}>${l}</option>`).join("")}</select>
      </div>
      <p class="result-count" id="tb-count" aria-live="polite"></p>
      <div class="tx-list" id="tb-cards"></div>
      <div class="table-wrap">
        <table class="tx-table">
          <thead><tr>
            <th scope="col">Date</th><th scope="col">Type</th><th scope="col">Parties</th><th scope="col">Location</th><th scope="col">Area</th>
          </tr></thead>
          <tbody id="tb-rows"></tbody>
        </table>
      </div>
      <div class="more-wrap"><button type="button" class="btn-more" id="tb-more">Show more</button></div>`;

    let shown = PAGE_SIZE;
    const apply = (resetPaging) => {
      if (resetPaging) shown = PAGE_SIZE;
      const qv = $("#tb-q").value.trim();
      const pf = pocketFilter ? $("#tb-pocket").value : "";
      const af = $("#tb-article").value;
      const sv = $("#tb-sort").value;
      setQuery({
        q: qv || null,
        pocket: pf || null,
        article: af || null,
        sort: sv === "date-desc" ? null : sv,
      });
      const needle = qv.toLowerCase();
      const rows = items.filter((r) => {
        if (pf && r.property.pocket !== pf) return false;
        if (af && r._article !== af) return false;
        if (needle && !haystack(r).includes(needle)) return false;
        return true;
      });
      rows.sort(txSorter(sv));
      const slice = rows.slice(0, shown);
      $("#tb-count").textContent = rows.length
        ? `Showing ${fmtNum(slice.length)} of ${fmtNum(rows.length)} matching transactions`
        : "No matching transactions";
      $("#tb-cards").innerHTML = slice.map((r) => txCard(r)).join("");
      $("#tb-rows").innerHTML = slice.map((r) => txRow(r, sectorCol)).join("");
      const left = rows.length - slice.length;
      const more = $("#tb-more");
      more.hidden = left <= 0;
      more.textContent = `Show ${fmtNum(Math.min(PAGE_SIZE, left))} more (${fmtNum(left)} left)`;
    };

    root.addEventListener("input", (e) => { if (e.target.id === "tb-q") apply(true); });
    root.addEventListener("change", (e) => { if (e.target.tagName === "SELECT") apply(true); });
    $("#tb-more").addEventListener("click", () => { shown += PAGE_SIZE; apply(false); });
    apply(false);
  }

  function haystack(r) {
    return [
      r.seller && r.seller.name, r.seller && r.seller.address,
      r.purchaser && r.purchaser.name, r.purchaser && r.purchaser.address,
      r.property.raw_plot_number, r.property.pocket, r.registration_no, r.document_id,
    ].join(" ").toLowerCase();
  }

  function txSorter(sv) {
    if (sv === "date-asc") return (a, b) => a.registration_date.localeCompare(b.registration_date);
    if (sv === "area-desc") return (a, b) => (b.property.description.plot_area_sqm || 0) - (a.property.description.plot_area_sqm || 0);
    if (sv === "area-asc") return (a, b) => (a.property.description.plot_area_sqm || 0) - (b.property.description.plot_area_sqm || 0);
    return (a, b) => b.registration_date.localeCompare(a.registration_date);
  }

  function areaLine(r) {
    const d = r.property.description || {};
    return [
      has(d.plot_area_sqm) ? `Plot ${fmtNum(d.plot_area_sqm, 1)} m²` : null,
      has(d.plinth_area_sqm) ? `Plinth ${fmtNum(d.plinth_area_sqm, 1)} m²` : null,
    ].filter(Boolean);
  }

  function txRow(r, sectorCol) {
    const areas = areaLine(r);
    const pl = isSectorPocket(r.property.pocket) ? "" : pocketLabel(r.property.pocket);
    return `<tr class="tx-row" data-tx="${esc(r.id)}" tabindex="0" aria-label="Details for ${esc(titleCase(r.seller && r.seller.name) || "record")}">
      <td class="date">${fmtDay(dayOf(r))}</td>
      <td>${articleBadge(r._article)}</td>
      <td class="parties">${parties(r)}</td>
      <td>${esc(pl)}${pl ? "<br>" : ""}<span class="sub">Plot ${esc(r.property.raw_plot_number || "—")}</span>${sectorCol ? `<br><span class="src-tag">Sector ${esc(r.sector)}</span>` : ""}</td>
      <td>${areas.length ? areas.map(esc).join("<br>") : "—"}</td>
    </tr>`;
  }

  function txCard(r) {
    const areas = areaLine(r);
    const pl = isSectorPocket(r.property.pocket) ? "" : pocketLabel(r.property.pocket);
    return `<button type="button" class="tx-card" data-tx="${esc(r.id)}">
      <span class="tx-head"><span class="tx-date">${fmtDay(dayOf(r))}</span>${articleBadge(r._article)}</span>
      <span class="tx-parties">${parties(r)}</span>
      <span class="tx-plot">${esc([pl, `Plot ${r.property.raw_plot_number || "—"}`, `Sector ${r.sector}`].filter(Boolean).join(" · "))}</span>
      ${areas.length ? `<span class="tx-meta">${areas.map((a) => `<span>${esc(a)}</span>`).join("")}</span>` : ""}
      <span class="tx-card-cta">Details →</span>
    </button>`;
  }

  // -------- Transaction detail modal --------
  function buildDetailHtml(r) {
    const d = r.property.description || {};
    const p = r.property;
    const pocketCell = String(r.sector) === "28"
      ? `<a href="#/sector/28/pocket/${encodeURIComponent(p.pocket)}" class="link">${esc(pocketLabel(p.pocket))}</a>`
      : esc("Not split (sector level)");
    const propRows = [
      ["Sector", esc(`Sector ${r.sector}`)],
      ["Plot (as registered)", esc(p.raw_plot_number || "—")],
      ["Pocket (inferred)", pocketCell],
      ["Block", esc(blockLabel(p.block))],
    ];
    if (p.property_id) propRows.push(["Property ID", esc(p.property_id), true]);
    if (r.taluka) propRows.push(["Registered at", `${esc(r.taluka)} taluka${r.district ? ` · ${esc(r.district)} district` : ""}`]);
    if (p.upic && p.upic !== "000000000000000") propRows.push(["UPIC", esc(p.upic), true]);
    if (p.village) propRows.push(["Village", esc(p.village)]);

    const descRows = [];
    if (has(d.plot_area_sqm)) descRows.push(["Plot area", `${fmtNum(d.plot_area_sqm, 2)} m²`]);
    if (has(d.plinth_area_sqm)) descRows.push(["Plinth / FAR area", `${fmtNum(d.plinth_area_sqm, 2)} m²`]);
    if (has(d.plinth_area_transferred_sqm)) descRows.push(["Plinth area transferred", `${fmtNum(d.plinth_area_transferred_sqm, 2)} m²`]);
    if (has(d.land_share_transferred_sqm)) descRows.push(["Land share transferred", `${fmtNum(d.land_share_transferred_sqm, 2)} m²`]);
    if (has(d.land_share_transferred_pct)) descRows.push(["Land share", `${fmtNum(d.land_share_transferred_pct, 2)} %`]);
    if (d.floors != null) descRows.push(["Floors", fmtNum(d.floors, 0)]);
    if (d.floor_label) descRows.push(["Floor", esc(titleCase(d.floor_label))]);
    if (d.type_of_flats) descRows.push(["Flat type", esc(d.type_of_flats)]);
    if (d.construction_type) descRows.push(["Construction", esc(d.construction_type)]);
    if (d.category_of_locality) descRows.push(["Category of locality", esc(d.category_of_locality)]);
    if (has(d.stilt_parking_sqm)) descRows.push(["Stilt parking", `${fmtNum(d.stilt_parking_sqm, 2)} m²`]);
    if (d.is_parking_present) descRows.push(["Parking present", esc(d.is_parking_present)]);

    const regRows = [
      ["Document ID", esc(r.document_id), true],
      ["Registration no.", esc(r.registration_no), true],
      ["Registration office", esc(r.registration_office || "—")],
      ["Registered on", esc(fmtDateTime(r.registration_date))],
      ["Article", `${esc(r._article)}${r.article_code != null ? ` (form code ${esc(r.article_code)})` : ""}`],
    ];
    const dl = (rows) => `<dl class="rpp-dl">${rows.map(([k, v, mono]) =>
      `<dt>${esc(k)}</dt><dd class="${mono ? "mono" : ""}">${v}</dd>`).join("")}</dl>`;
    const nameOf = (x) => party(x && x.name);
    const addrOf = (x) => esc(titleCase(x && x.address));

    return `
      <div class="rpp-modal-backdrop" data-close></div>
      <div class="rpp-modal" role="dialog" aria-modal="true" aria-labelledby="tx-detail-title" tabindex="-1">
        <header class="rpp-modal-head">
          <div>
            <div class="rpp-modal-eyebrow">${articleBadge(r._article)}</div>
            <h2 id="tx-detail-title">${parties(r)}</h2>
            <div class="rpp-modal-sub">${esc(fmtDateTime(r.registration_date))} · ${esc(r.registration_office || "")}</div>
          </div>
          <button type="button" class="rpp-modal-close" data-close aria-label="Close">✕</button>
        </header>

        <section class="rpp-modal-body">
          <div class="rpp-modal-section">
            <h3>Parties</h3>
            <div class="party-grid">
              <div class="party-card">
                <div class="party-label">Seller</div>
                <div class="party-name">${nameOf(r.seller)}</div>
                <div class="party-addr">${addrOf(r.seller)}</div>
              </div>
              <div class="party-arrow" aria-hidden="true">→</div>
              <div class="party-card">
                <div class="party-label">Purchaser</div>
                <div class="party-name">${nameOf(r.purchaser)}</div>
                <div class="party-addr">${addrOf(r.purchaser)}</div>
              </div>
            </div>
          </div>
          <div class="rpp-modal-section"><h3>Property</h3>${dl(propRows)}</div>
          ${descRows.length ? `<div class="rpp-modal-section"><h3>Description (as declared)</h3>${dl(descRows.map(([k, v]) => [k, v]))}</div>` : ""}
          <div class="rpp-modal-section"><h3>Registration</h3>${dl(regRows)}</div>
        </section>

        <footer class="rpp-modal-foot">
          ${String(r.sector) === "28"
            ? `<a href="#/sector/28/pocket/${encodeURIComponent(p.pocket)}" class="btn btn-primary" data-close>View ${esc(pocketLabel(p.pocket))} →</a>`
            : `<a href="#/sector/${esc(r.sector)}" class="btn btn-primary" data-close>View Sector ${esc(r.sector)} →</a>`}
          <button type="button" class="btn" data-copy>Copy link</button>
          <button type="button" class="btn" data-close>Close</button>
        </footer>
      </div>`;
  }

  function openTxDetail(id, { updateUrl = true } = {}) {
    const r = state.txIndex.get(String(id));
    if (!r) return;
    closeTxDetail(false);
    modalOpener = document.activeElement;
    const wrap = document.createElement("div");
    wrap.id = "tx-detail-modal";
    wrap.className = "rpp-modal-wrap";
    wrap.innerHTML = buildDetailHtml(r);
    document.body.appendChild(wrap);
    document.documentElement.classList.add("modal-open");
    wrap.querySelector(".rpp-modal").focus();
    wrap.addEventListener("click", (e) => {
      const copy = e.target.closest("[data-copy]");
      if (copy) {
        if (navigator.clipboard) {
          navigator.clipboard.writeText(location.href).then(() => { copy.textContent = "Link copied"; }).catch(() => {});
        }
        return;
      }
      if (e.target.closest("[data-close]")) closeTxDetail();
    });
    document.addEventListener("keydown", onModalKey);
    if (updateUrl) setQuery({ tx: String(id) });
  }

  function onModalKey(e) {
    if (e.key === "Escape") closeTxDetail();
  }

  function closeTxDetail(updateUrl = true) {
    const wrap = document.getElementById("tx-detail-modal");
    if (!wrap) return;
    document.removeEventListener("keydown", onModalKey);
    wrap.remove();
    document.documentElement.classList.remove("modal-open");
    if (updateUrl) setQuery({ tx: null });
    if (modalOpener && document.contains(modalOpener)) modalOpener.focus();
    modalOpener = null;
  }

  // -------- About --------
  function viewAbout() {
    setActiveNav("about");
    renderBreadcrumb([{ label: "Overview", href: "#/" }, { label: "How to read this" }]);
    $("#view").innerHTML = `
      ${pageHead("How to read this data", "What each number means, and what it does not show.")}
      <section class="card prose">
        <h2>Where the data comes from</h2>
        <p>Each record is one property document registered with the Delhi Government's NGDRS Citizen e-Search, at the Bawana, Alipur and Sdm Rohini registration offices. The site is refreshed by a script; the time of the last refresh is in the footer. This is not an official record. Verify any document with the Sub-Registrar's office.</p>
        <h2>Coverage differs by sector</h2>
        <p>The overview table shows the first and last record for each sector. Sectors were added to tracking at different times, and some only have records from late September onward. A late start can mean the sector was added later, or that no registrations were recorded earlier. The data cannot tell these apart, so treat a late start as "no data we have", not as "no activity".</p>
        <h2>Monthly totals are not like-for-like</h2>
        <p>October looks much bigger than other months mainly because more sectors were reporting by then. Compare sectors within the same period, or check the sector count under each month before drawing conclusions.</p>
        <h2>Pockets (Sector 28 only)</h2>
        <p>A pocket is a cluster of plots inside Sector 28, grouped by block. Pocket IDs are inferred from the plot number and the DDA keyplan. <strong>Block A</strong> and <strong>Block C</strong> are the planned blocks; <strong>DDA Flats</strong> are the LIG/MIG flat blocks (GH). <strong>Unmapped</strong> means the plot number did not match any pocket in the keyplan, so these records are counted in Sector 28 but cannot be placed on the map. <strong>Block A (unnumbered)</strong> means the record names block A but gives no pocket number.</p>
        <h2>Article types</h2>
        <ul>
          <li><strong>Sale Deed</strong>: transfer of ownership for a sale.</li>
          <li><strong>Sale Agreement</strong>: an agreement to sell. It is not a transfer of ownership.</li>
          <li><strong>Gift Deed</strong>, <strong>Partition</strong>, <strong>Conveyance</strong>: transfers for other reasons.</li>
          <li><strong>Relinquishment Deed</strong>: a co-owner gives up a share.</li>
          <li><strong>Rectification, Cancellation, Certificate of Sale, General Agreement</strong>: corrections, cancellations and other instruments, usually small in number.</li>
        </ul>
        <p>These are simplified. The registry's own definitions prevail.</p>
        <h2>Areas and floors</h2>
        <p>Plot area, plinth area and floors are as declared in the registered document. They are not checked against a survey. Averages mix flats and plots, so read them as a rough guide.</p>
        <h2>What is not included</h2>
        <p>The source file has no sale price or consideration field, so this site cannot show prices or price per square metre. If a price field becomes available, it could add median price by pocket.</p>
        <h2>Names and addresses</h2>
        <p>Names and addresses are shown in title case for readability. Spelling is as recorded.</p>
      </section>`;
  }

  // -------- Router --------
  async function render() {
    const seq = ++renderSeq;
    const { parts, query } = parseHash();
    if (parts[0] === "sector" && parts[2] === "all") {
      history.replaceState(null, "", `#/transactions?${new URLSearchParams({ ...query, sector: parts[1] })}`);
    }
    const r = parseRoute();
    state.route = r;
    closeMobileNav();
    closeTxDetail(false);
    destroyMap();
    try {
      await loadData();
      if (seq !== renderSeq) return;
      syncFromRoute(r);
      refreshSelects();
      updatePeriodNote();
      if (r.name === "overview") viewOverview();
      else if (r.name === "sector") viewSector(r.params.sector);
      else if (r.name === "pocket") viewPocket(r.params);
      else if (r.name === "list") viewList();
      else if (r.name === "about") viewAbout();
      initFooter();
      const path = location.hash.split("?")[0];
      if (path !== lastPath) window.scrollTo(0, 0);
      lastPath = path;
      if (r.query.tx) openTxDetail(r.query.tx, { updateUrl: false });
    } catch (err) {
      console.error(err);
      $("#view").innerHTML = `<div class="empty">Failed to load data: ${esc(err.message)}</div>`;
    }
  }

  function closeMobileNav() {
    const nav = $("#primary-nav");
    const btn = $("#nav-toggle");
    if (nav) nav.classList.remove("open");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function initNavToggle() {
    const btn = $("#nav-toggle");
    const nav = $("#primary-nav");
    btn.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      btn.setAttribute("aria-expanded", String(open));
    });
  }

  function initFooter() {
    const m = state.allMeta;
    if (!m) return;
    $("#footer-meta").textContent =
      `Updated ${fmtDateTime(m.generated_at)} IST · ${fmtNum(state.allRegistrations.length)} records in the dataset`;
  }

  function initSignout() {
    const link = document.getElementById("signout-link");
    if (!link) return;
    link.addEventListener("click", (e) => {
      e.preventDefault();
      if (window.rppLock) window.rppLock();
      else location.reload();
    });
  }

  function init() {
    if (appInitialized) return;
    appInitialized = true;
    initNavToggle();
    initSignout();
    window.RPPMap.injectCss();
    $("#sector-select").addEventListener("change", onSectorChange);
    $("#month-select").addEventListener("change", (e) => setMonth(e.target.value));
    const view = $("#view");
    view.addEventListener("click", (e) => {
      const tx = e.target.closest("[data-tx]");
      if (tx) { openTxDetail(tx.dataset.tx); return; }
      const month = e.target.closest("[data-month]");
      if (month) { setMonth(month.dataset.month === state.month ? "" : month.dataset.month); return; }
      const sort = e.target.closest("[data-sort]");
      if (sort) {
        const key = sort.dataset.sort;
        leagueSort = { key, dir: leagueSort.key === key ? -leagueSort.dir : (key === "name" ? 1 : -1) };
        renderLeague();
      }
    });
    document.addEventListener("click", (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = e.target.closest('a[href^="#/"]');
      if (!a) return;
      e.preventDefault();
      go(a.getAttribute("href"));
    });
    view.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && e.target.matches("tr[data-tx]")) {
        e.preventDefault();
        openTxDetail(e.target.dataset.tx);
      }
    });
    window.addEventListener("hashchange", render);
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      if (window.rppAuthReady) init();
      else window.addEventListener("rpp:ready", init, { once: true });
    });
  } else {
    if (window.rppAuthReady) init();
    else window.addEventListener("rpp:ready", init, { once: true });
  }
})();
