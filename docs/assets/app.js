// Rohini Property Pulse — vanilla JS, no build step.
(() => {
  "use strict";

  const state = {
    meta: null,
    summary: null,
    registrations: null,
    route: { name: "overview", params: {} },
  };

  // -------- DOM helpers --------
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const el = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function")
        node.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v === true) node.setAttribute(k, "");
      else if (v === false || v == null) {} // skip
      else node.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
  };
  const fmtNum = (n, digits = 0) =>
    n == null ? "—" : Number(n).toLocaleString("en-IN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  const fmtDate = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    });
  };
  const fmtTime = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  };
  const esc = (s) =>
    s == null ? "" : String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

  const articleBadge = (article) => {
    const map = {
      "Sale Deed": "badge-sale",
      "Gift Deed": "badge-gift",
      "Relinquishment Deed": "badge-relinquishment",
      "Sale Agreement": "badge-agreement",
    };
    const cls = map[article] || "badge-default";
    return `<span class="badge ${cls}">${esc(article)}</span>`;
  };

  // -------- Routing --------
  function parseRoute() {
    const h = location.hash.replace(/^#/, "") || "/";
    const parts = h.split("/").filter(Boolean);
    if (parts.length === 0) return { name: "overview" };
    if (parts[0] === "sector" && parts[1] === "28") {
      if (parts[2] === "all") return { name: "list" };
      if (parts[2] === "pocket" && parts[3])
        return { name: "pocket", params: { pocket: decodeURIComponent(parts[3]) } };
      return { name: "sector", params: { sector: 28 } };
    }
    if (parts[0] === "sector" && parts[1])
      return { name: "sector", params: { sector: Number(parts[1]) } };
    return { name: "overview" };
  }

  function setActiveNav(name) {
    $$(".primary-nav a").forEach((a) => {
      const n = a.dataset.nav;
      a.classList.toggle("active", n === name);
    });
  }

  function renderBreadcrumb(items) {
    const bc = $("#breadcrumbs");
    bc.innerHTML = items
      .map((it, i) => {
        const sep = i > 0 ? `<span class="sep">›</span>` : "";
        const body = it.href
          ? `<a href="${it.href}">${esc(it.label)}</a>`
          : `<span class="current">${esc(it.label)}</span>`;
        return sep + body;
      })
      .join("");
  }

  // -------- Data load --------
  async function loadData() {
    if (state.meta && state.summary && state.registrations) return;
    const [meta, summary, reg] = await Promise.all([
      fetch("data/meta.json").then((r) => r.json()),
      fetch("data/sector28-summary.json").then((r) => r.json()),
      fetch("data/registrations.json").then((r) => r.json()),
    ]);
    state.meta = meta;
    state.summary = summary;
    state.registrations = reg.items;
  }

  // -------- Views --------
  function viewOverview() {
    setActiveNav("overview");
    renderBreadcrumb([{ label: "Overview" }]);
    const m = state.meta;
    const s = state.summary;

    const html = `
      <section class="hero">
        <h1>Rohini Property Registrations</h1>
        <p>${esc(m.date_from)} → ${esc(m.date_to)} · ${m.sector} · ${esc(m.taluka)}, ${esc(m.district)}</p>
      </section>

      <div class="stat-grid">
        <div class="stat">
          <div class="label">Total registrations</div>
          <div class="value">${m.total_registrations}</div>
          <div class="sub">In selected period</div>
        </div>
        <div class="stat">
          <div class="label">Active pockets</div>
          <div class="value">${m.unique_pockets}</div>
          <div class="sub">Across 3 blocks</div>
        </div>
        <div class="stat">
          <div class="label">Sale deeds</div>
          <div class="value">${(m.articles["Sale Deed"] || 0)}</div>
          <div class="sub">${Math.round((m.articles["Sale Deed"] || 0) / m.total_registrations * 100)}% of activity</div>
        </div>
        <div class="stat">
          <div class="label">Other articles</div>
          <div class="value">${m.total_registrations - (m.articles["Sale Deed"] || 0)}</div>
          <div class="sub">Gift, relinquishment, agreements</div>
        </div>
      </div>

      <div class="card">
        <h2>Rohini Sector Map <span class="pill">Tap sector 28</span></h2>
        <div class="map-toolbar">
          <div>OpenStreetMap base · 30+ sectors · sector 28 highlighted</div>
          <div class="legend">
            <span class="swatch" style="background:#2563eb"></span> Selected
            <span class="swatch" style="background:#93c5fd;margin-left:8px"></span> Other
          </div>
        </div>
        <div class="map-wrap leaflet-wrap" id="sector-map" style="height:480px"></div>
      </div>

      <div class="cols-2">
        <div class="card">
          <h2>Activity by article</h2>
          <div class="bar-chart" id="article-chart"></div>
        </div>
        <div class="card">
          <h2>Daily registrations</h2>
          <div class="bar-chart" id="date-chart"></div>
        </div>
      </div>
    `;

    $("#view").innerHTML = html;
    setRppState();
    if (window.RPPMap) {
      window.RPPMap.injectCss();
      window.RPPMap.renderRohiniMap("sector-map", (sector, hasData) => {
        if (hasData) location.hash = "#/sector/28";
      });
    }
    renderArticleChart();
    renderDateChart();
  }

  function attachSectorHandlers(svgRoot) {
    $$(".sector", svgRoot).forEach((s) => {
      s.addEventListener("click", () => {
        const n = Number(s.dataset.sector);
        if (n === 28) location.hash = "#/sector/28";
        else flashTooltip(s, "No scraped data for this sector yet");
      });
      s.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          s.click();
        }
      });
    });
  }

  function flashTooltip(node, msg) {
    const original = node.querySelector("title")?.textContent || "";
    const t = el("title", {}, msg);
    node.appendChild(t);
    setTimeout(() => t.remove(), 1500);
  }

  function loadSvg(containerId, url, afterLoad) {
    fetch(url)
      .then((r) => r.text())
      .then((svgText) => {
        const container = document.getElementById(containerId);
        container.innerHTML = svgText;
        const svg = container.querySelector("svg");
        if (afterLoad) afterLoad(svg);
      });
  }

  function renderArticleChart() {
    const articles = state.meta.articles;
    const max = Math.max(...Object.values(articles));
    const root = $("#article-chart");
    root.innerHTML = "";
    Object.entries(articles)
      .sort((a, b) => b[1] - a[1])
      .forEach(([name, count]) => {
        const pct = (count / max) * 100;
        root.insertAdjacentHTML(
          "beforeend",
          `<div class="bar-row">
             <span class="bar-name">${articleBadge(name)}</span>
             <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
             <span class="bar-value">${count}</span>
           </div>`
        );
      });
  }

  function renderDateChart() {
    const series = state.summary.date_series;
    const max = Math.max(...series.map((d) => d.count));
    const root = $("#date-chart");
    root.innerHTML = "";
    if (series.length === 0) {
      root.innerHTML = '<div class="empty">No data</div>';
      return;
    }
    // Show last 14 days to keep it readable on mobile
    const slice = series.slice(-14);
    slice.forEach((d) => {
      const pct = (d.count / max) * 100;
      const label = new Date(d.date).toLocaleDateString("en-IN", {
        day: "2-digit", month: "short",
      });
      root.insertAdjacentHTML(
        "beforeend",
        `<div class="bar-row">
           <span class="bar-name">${label}</span>
           <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
           <span class="bar-value">${d.count}</span>
         </div>`
      );
    });
  }

  // -------- Sector 28 --------
  function viewSector(params) {
    setActiveNav("sector");
    renderBreadcrumb([
      { label: "Overview", href: "#/" },
      { label: "Sector 28" },
    ]);
    const m = state.meta;
    const s = state.summary;

    // Pocket cards
    const pocketCards = Object.entries(s.pockets)
      .map(([pid, p]) => renderPocketCard(pid, p))
      .join("");

    // Block summary
    const blockRows = Object.entries(s.blocks)
      .map(([block, b]) => {
        const cls =
          block === "A" ? "block-A" : block === "C" ? "block-C" :
          block === "GH" ? "block-GH" : "block-unknown";
        return `<div class="stat">
          <div class="label">Block ${esc(block)}</div>
          <div class="value">${b.count}</div>
          <div class="sub">${b.pockets.length} pockets · ${esc(b.pockets.join(", "))}</div>
        </div>`;
      })
      .join("");

    const html = `
      <a href="#/" class="back-link">Back to overview</a>
      <section class="hero">
        <h1>Sector 28 — Pocket Map</h1>
        <p>${esc(m.date_from)} → ${esc(m.date_to)} · ${m.total_registrations} registrations</p>
      </section>

      <div class="stat-grid">
        ${blockRows}
      </div>

      <div class="card">
        <h2>Pocket Map <span class="pill">Tap a pocket</span></h2>
        <div class="map-toolbar">
          <div>OpenStreetMap base · real Sector 28 boundary · approximate pocket areas</div>
          <div class="legend">
            <span class="swatch" style="background:#b91c1c"></span> 12+
            <span class="swatch" style="background:#dc2626;margin-left:6px"></span> 10-11
            <span class="swatch" style="background:#ea580c;margin-left:6px"></span> 7-9
            <span class="swatch" style="background:#f97316;margin-left:6px"></span> 5-6
            <span class="swatch" style="background:#fb923c;margin-left:6px"></span> 3-4
            <span class="swatch" style="background:#fed7aa;margin-left:6px"></span> 1-2
          </div>
        </div>
        <div class="map-wrap leaflet-wrap" id="pocket-map" style="height:520px"></div>
      </div>

      <div class="card">
        <h2>All pockets <span class="pill">${Object.keys(s.pockets).length}</span></h2>
        <div class="pocket-grid">${pocketCards}</div>
      </div>

      <div class="cols-2">
        <div class="card">
          <h2>Activity by pocket</h2>
          <div class="bar-chart" id="pocket-chart"></div>
        </div>
        <div class="card">
          <h2>By article</h2>
          <div class="bar-chart" id="article-chart-2"></div>
        </div>
      </div>

      <div class="card">
        <h2>All transactions <span class="pill">${m.total_registrations}</span></h2>
        <div class="filters">
          <input type="search" id="tx-search" placeholder="Search seller / purchaser / plot…" inputmode="search" />
          <select id="tx-pocket">
            <option value="">All pockets</option>
            ${Object.keys(s.pockets).map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("")}
          </select>
          <select id="tx-article">
            <option value="">All articles</option>
            ${Object.keys(m.articles).map((a) => `<option value="${esc(a)}">${esc(a)}</option>`).join("")}
          </select>
        </div>
        <div id="tx-results"></div>
        <p style="text-align:center;margin-top:12px;"><a href="#/sector/28/all">View full table with sorting →</a></p>
      </div>
    `;

    $("#view").innerHTML = html;
    setRppState();
    if (window.RPPMap) {
      window.RPPMap.injectCss();
      window.RPPMap.renderSector28Map("pocket-map", (pocket) => {
        location.hash = `#/sector/28/pocket/${encodeURIComponent(pocket)}`;
      });
    }
    renderPocketChart();
    renderArticleChart2();
    bindTxFilters();
    renderTxResults();
  }

  function attachPocketHandlers(svgRoot) {
    $$(".pocket", svgRoot).forEach((p) => {
      p.addEventListener("click", () => {
        const pid = p.dataset.pocket;
        if (pid) location.hash = `#/sector/28/pocket/${encodeURIComponent(pid)}`;
      });
      p.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          p.click();
        }
      });
    });
  }

  function setRppState() {
    const counts = {};
    if (state.summary) {
      for (const [pid, p] of Object.entries(state.summary.pockets)) {
        counts[pid] = p.count;
      }
    }
    window.RPP_STATE = { pocketCounts: counts };
  }

  function renderPocketCard(pid, p) {
    const topArticle = Object.entries(p.articles).sort((a, b) => b[1] - a[1])[0];
    return `
      <a class="pocket-card" href="#/sector/28/pocket/${encodeURIComponent(pid)}">
        <div class="pocket-name">${esc(pid)}</div>
        <div class="pocket-block">${pid.startsWith("GH-") ? "DDA Flats" : pid === "Unknown" ? "Unmapped" : "Block " + esc(pid.split("-")[0])}</div>
        <div class="pocket-count">${p.count}</div>
        <div class="pocket-articles">${articleBadge(topArticle[0])} <span style="font-size:11px;color:var(--text-2);align-self:center">${topArticle[1]}</span></div>
      </a>
    `;
  }

  function renderPocketChart() {
    const pockets = state.summary.pockets;
    const max = Math.max(...Object.values(pockets).map((p) => p.count));
    const root = $("#pocket-chart");
    root.innerHTML = "";
    Object.entries(pockets)
      .sort((a, b) => b[1].count - a[1].count)
      .forEach(([pid, p]) => {
        const pct = (p.count / max) * 100;
        root.insertAdjacentHTML(
          "beforeend",
          `<div class="bar-row">
             <span class="bar-name">${esc(pid)}</span>
             <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
             <span class="bar-value">${p.count}</span>
           </div>`
        );
      });
  }

  function renderArticleChart2() {
    const articles = state.meta.articles;
    const max = Math.max(...Object.values(articles));
    const root = $("#article-chart-2");
    root.innerHTML = "";
    Object.entries(articles)
      .sort((a, b) => b[1] - a[1])
      .forEach(([name, count]) => {
        const pct = (count / max) * 100;
        root.insertAdjacentHTML(
          "beforeend",
          `<div class="bar-row">
             <span class="bar-name">${articleBadge(name)}</span>
             <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
             <span class="bar-value">${count}</span>
           </div>`
        );
      });
  }

  // -------- Pocket detail --------
  function viewPocket(params) {
    setActiveNav("sector");
    const pocket = params.pocket;
    const s = state.summary.pockets[pocket];
    if (!s) {
      $("#view").innerHTML = `
        <a href="#/sector/28" class="back-link">Back to Sector 28</a>
        <div class="empty">No data for pocket <strong>${esc(pocket)}</strong>.</div>
      `;
      renderBreadcrumb([
        { label: "Overview", href: "#/" },
        { label: "Sector 28", href: "#/sector/28" },
        { label: pocket },
      ]);
      return;
    }

    const items = state.registrations.filter((r) => r.property.pocket === pocket);
    items.sort((a, b) => b.registration_date.localeCompare(a.registration_date));

    const block = items[0]?.property.block || "?";
    const blockLabel =
      block === "GH" ? "DDA Flats (LIG/MIG)" :
      block === "Unknown" ? "Unmapped" :
      `Block ${block}`;

    renderBreadcrumb([
      { label: "Overview", href: "#/" },
      { label: "Sector 28", href: "#/sector/28" },
      { label: `Pocket ${pocket}` },
    ]);

    const topArticle = Object.entries(s.articles).sort((a, b) => b[1] - a[1])[0];
    const topConstruction = Object.entries(s.construction || {}).sort((a, b) => b[1] - a[1])[0];
    const dateSeries = computeDateSeries(items);

    const html = `
      <a href="#/sector/28" class="back-link">Back to Sector 28</a>
      <section class="hero">
        <h1>Pocket ${esc(pocket)}</h1>
        <p>${esc(blockLabel)} · ${s.count} registrations · ${esc(s.earliest)} → ${esc(s.latest)}</p>
      </section>

      <div class="stat-grid">
        <div class="stat">
          <div class="label">Transactions</div>
          <div class="value">${s.count}</div>
          <div class="sub">${esc(s.earliest)} → ${esc(s.latest)}</div>
        </div>
        <div class="stat">
          <div class="label">Top article</div>
          <div class="value" style="font-size:18px;line-height:1.4">${articleBadge(topArticle[0])}</div>
          <div class="sub">${topArticle[1]} of ${s.count} transactions</div>
        </div>
        <div class="stat">
          <div class="label">Avg plot area</div>
          <div class="value">${s.avg_plot_area_sqm ? fmtNum(s.avg_plot_area_sqm, 1) + " m²" : "—"}</div>
          <div class="sub">${s.avg_plinth_area_sqm ? "Avg plinth: " + fmtNum(s.avg_plinth_area_sqm, 1) + " m²" : "Flat-type units"}</div>
        </div>
        <div class="stat">
          <div class="label">Avg floors</div>
          <div class="value">${s.avg_floors ? fmtNum(s.avg_floors, 1) : "—"}</div>
          <div class="sub">${topConstruction ? topConstruction[0] : "Mixed"} construction</div>
        </div>
      </div>

      <div class="cols-2">
        <div class="card">
          <h2>Article breakdown</h2>
          <div class="bar-chart">
            ${Object.entries(s.articles).sort((a, b) => b[1] - a[1]).map(([name, count]) => {
              const pct = (count / s.count) * 100;
              return `<div class="bar-row">
                <span class="bar-name">${articleBadge(name)}</span>
                <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
                <span class="bar-value">${count}</span>
              </div>`;
            }).join("")}
          </div>
        </div>
        <div class="card">
          <h2>Daily activity</h2>
          <div class="bar-chart">
            ${dateSeries.slice(-14).map((d) => {
              const max = Math.max(...dateSeries.map((x) => x.count), 1);
              const pct = (d.count / max) * 100;
              const label = new Date(d.date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
              return `<div class="bar-row">
                <span class="bar-name">${label}</span>
                <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
                <span class="bar-value">${d.count}</span>
              </div>`;
            }).join("") || '<div class="empty">No data</div>'}
          </div>
        </div>
      </div>

      <div class="card">
        <h2>Transactions <span class="pill">${items.length}</span></h2>
        <div class="tx-list" id="tx-list-mobile"></div>
        <div class="table-wrap">
          <table class="tx-table" id="tx-table">
            <thead>
              <tr>
                <th>Date</th><th>Article</th><th>Parties</th><th>Plot / Pocket</th><th>Area (m²)</th>
              </tr>
            </thead>
            <tbody id="tx-tbody"></tbody>
          </table>
        </div>
      </div>
    `;

    $("#view").innerHTML = html;
    renderTxListMobile(items, "#tx-list-mobile");
    renderTxTable(items, "#tx-tbody");
  }

  function computeDateSeries(items) {
    const m = new Map();
    items.forEach((r) => {
      const d = r.registration_date.slice(0, 10);
      m.set(d, (m.get(d) || 0) + 1);
    });
    return [...m.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, count]) => ({ date, count }));
  }

  function renderTxListMobile(items, sel) {
    const root = $(sel);
    root.innerHTML = "";
    if (items.length === 0) {
      root.innerHTML = '<div class="empty">No matching transactions</div>';
      return;
    }
    items.forEach((r) => root.appendChild(txCard(r)));
  }

  function renderTxTable(items, sel) {
    const tbody = $(sel);
    tbody.innerHTML = "";
    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty">No matching transactions</td></tr>';
      return;
    }
    items.forEach((r) => {
      const tr = el("tr", { class: "tx-row", "data-tx-id": r.id, tabindex: "0", role: "button", "aria-label": `View details for ${r.seller.name || "unknown"} to ${r.purchaser.name || "unknown"}` });
      const desc = r.property.description;
      const areaParts = [];
      if (desc.plot_area_sqm) areaParts.push(`Plot ${fmtNum(desc.plot_area_sqm, 1)}`);
      if (desc.plinth_area_sqm) areaParts.push(`Plinth ${fmtNum(desc.plinth_area_sqm, 1)}`);
      const area = areaParts.join(" · ") || "—";
      tr.innerHTML = `
        <td class="date">${fmtDate(r.registration_date)}</td>
        <td>${articleBadge(r.article)}</td>
        <td class="parties">
          ${esc(r.seller.name || "(unknown)")}
          <span class="arrow">→</span>
          ${esc(r.purchaser.name || "(unknown)")}
        </td>
        <td>${esc(r.property.pocket)}<br><span style="font-size:11px;color:var(--text-2)">${esc(r.property.raw_plot_number)}</span></td>
        <td>${area}</td>
      `;
      tr.addEventListener("click", () => openTxDetail(r.id));
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openTxDetail(r.id);
        }
      });
      tbody.appendChild(tr);
    });
  }

  function txCard(r) {
    const desc = r.property.description;
    const areaParts = [];
    if (desc.plot_area_sqm) areaParts.push(`Plot ${fmtNum(desc.plot_area_sqm, 1)} m²`);
    if (desc.plinth_area_sqm) areaParts.push(`Plinth ${fmtNum(desc.plinth_area_sqm, 1)} m²`);
    if (desc.floors != null) areaParts.push(`${fmtNum(desc.floors, 0)} floor${desc.floors > 1 ? "s" : ""}`);
    if (desc.floor_label) areaParts.push(esc(desc.floor_label));
    const area = areaParts.join(" · ");
    const card = el(
      "div",
      { class: "tx-card", "data-tx-id": r.id, tabindex: "0", role: "button", "aria-label": `View details for ${r.seller.name || "unknown"} to ${r.purchaser.name || "unknown"}` },
      el("div", { class: "tx-head" },
        el("span", { class: "tx-date" }, fmtTime(r.registration_date)),
        el("span", { html: articleBadge(r.article) }),
      ),
      el("div", { class: "tx-parties", html:
        `${esc(r.seller.name || "(unknown)")}<span class="arrow">→</span>${esc(r.purchaser.name || "(unknown)")}` }),
      el("div", { class: "tx-plot" }, esc(r.property.raw_plot_number)),
      el("div", { class: "tx-meta" },
        el("span", {}, `📍 ${esc(r.property.pocket)}`),
        area ? el("span", {}, `📐 ${area}`) : null,
        r.property.upic && r.property.upic !== "000000000000000"
          ? el("span", {}, `UPIC ${esc(r.property.upic)}`)
          : null,
      ),
      el("div", { class: "tx-card-cta" }, "Tap for details →")
    );
    card.addEventListener("click", () => openTxDetail(r.id));
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openTxDetail(r.id);
      }
    });
    return card;
  }

  // -------- Transaction detail modal --------
  function findTx(id) {
    return state.registrations?.find((r) => r.id === id) || null;
  }

  function buildDetailHtml(r) {
    const d = r.property.description;
    const blockLabel =
      r.property.block === "GH" ? "DDA Flats" :
      r.property.block === "Unknown" ? "Unmapped" :
      `Block ${r.property.block}`;

    const fields = [
      ["Document ID", r.document_id, true],
      ["Registration #", r.registration_no, true],
      ["Registration Office", r.registration_office],
      ["Date & time", fmtTime(r.registration_date)],
      ["Article", `${r.article}${r.article_code != null ? ` (code ${r.article_code})` : ""}`],
    ];

    const propFields = [];
    propFields.push(["Plot (as registered)", r.property.raw_plot_number]);
    propFields.push(["Pocket (inferred)", `<a href="#/sector/28/pocket/${encodeURIComponent(r.property.pocket)}" class="link">${esc(r.property.pocket)}</a>`, true]);
    propFields.push(["Block", blockLabel]);
    if (r.property.property_id) propFields.push(["Property ID", r.property.property_id]);
    if (r.property.upic && r.property.upic !== "000000000000000")
      propFields.push(["UPIC", r.property.upic, true]);
    propFields.push(["Village", r.property.village]);

    const descRows = [];
    if (d.plot_area_sqm != null)        descRows.push(["Plot area", `${fmtNum(d.plot_area_sqm, 2)} m²`]);
    if (d.plinth_area_sqm != null)      descRows.push(["Plinth / FAR area", `${fmtNum(d.plinth_area_sqm, 2)} m²`]);
    if (d.plinth_area_transferred_sqm != null) descRows.push(["Plinth area transferred", `${fmtNum(d.plinth_area_transferred_sqm, 2)} m²`]);
    if (d.land_share_transferred_sqm != null)  descRows.push(["Land share transferred", `${fmtNum(d.land_share_transferred_sqm, 2)} m²`]);
    if (d.land_share_transferred_pct != null)  descRows.push(["Land share %", `${fmtNum(d.land_share_transferred_pct, 2)} %`]);
    if (d.floors != null)               descRows.push(["Floors (1-4)", fmtNum(d.floors, 0)]);
    if (d.floor_label)                  descRows.push(["Floor label", d.floor_label]);
    if (d.floor_number != null)         descRows.push(["Floor #", fmtNum(d.floor_number, 0)]);
    if (d.type_of_flats)                descRows.push(["Flat type", d.type_of_flats]);
    if (d.construction_type)            descRows.push(["Construction", d.construction_type]);
    if (d.category_of_locality)         descRows.push(["Category of locality", d.category_of_locality]);
    if (d.stilt_parking_sqm != null)    descRows.push(["Stilt parking", `${fmtNum(d.stilt_parking_sqm, 2)} m²`]);
    if (d.is_parking_present)           descRows.push(["Parking present", d.is_parking_present]);

    return `
      <div class="rpp-modal-backdrop" data-close></div>
      <div class="rpp-modal" role="dialog" aria-modal="true" aria-labelledby="tx-detail-title" tabindex="-1">
        <header class="rpp-modal-head">
          <div>
            <div class="rpp-modal-eyebrow">${articleBadge(r.article)}</div>
            <h2 id="tx-detail-title">${esc(r.seller.name || "(unknown)")} → ${esc(r.purchaser.name || "(unknown)")}</h2>
            <div class="rpp-modal-sub">${fmtTime(r.registration_date)} · ${esc(r.registration_office || "")}</div>
          </div>
          <button class="rpp-modal-close" data-close aria-label="Close">✕</button>
        </header>

        <section class="rpp-modal-body">
          <div class="rpp-modal-section">
            <h3>Parties</h3>
            <div class="party-grid">
              <div class="party-card">
                <div class="party-label">Seller</div>
                <div class="party-name">${esc(r.seller.name) || '<em>(not recorded)</em>'}</div>
                <div class="party-addr">${esc(r.seller.address) || ""}</div>
              </div>
              <div class="party-arrow" aria-hidden="true">→</div>
              <div class="party-card">
                <div class="party-label">Purchaser</div>
                <div class="party-name">${esc(r.purchaser.name) || '<em>(not recorded)</em>'}</div>
                <div class="party-addr">${esc(r.purchaser.address) || ""}</div>
              </div>
            </div>
          </div>

          <div class="rpp-modal-section">
            <h3>Property</h3>
            <dl class="rpp-dl">${propFields.map(([k, v, mono]) =>
              `<dt>${esc(k)}</dt><dd class="${mono ? "mono" : ""}">${typeof v === "string" ? v : esc(String(v))}</dd>`
            ).join("")}</dl>
          </div>

          ${descRows.length ? `
          <div class="rpp-modal-section">
            <h3>Description (parsed)</h3>
            <dl class="rpp-dl">${descRows.map(([k, v]) =>
              `<dt>${esc(k)}</dt><dd>${esc(String(v))}</dd>`
            ).join("")}</dl>
          </div>` : ""}

          <div class="rpp-modal-section">
            <h3>Registration</h3>
            <dl class="rpp-dl">${fields.map(([k, v, mono]) =>
              `<dt>${esc(k)}</dt><dd class="${mono ? "mono" : ""}">${esc(String(v))}</dd>`
            ).join("")}</dl>
          </div>
        </section>

        <footer class="rpp-modal-foot">
          <a href="#/sector/28/pocket/${encodeURIComponent(r.property.pocket)}" class="btn btn-primary" data-close>View pocket ${esc(r.property.pocket)} →</a>
          <button class="btn" data-close>Close</button>
        </footer>
      </div>
    `;
  }

  function openTxDetail(id) {
    const r = findTx(id);
    if (!r) return;
    closeTxDetail();  // ensure no duplicate
    const wrap = document.createElement("div");
    wrap.id = "tx-detail-modal";
    wrap.className = "rpp-modal-wrap";
    wrap.innerHTML = buildDetailHtml(r);
    document.body.appendChild(wrap);
    document.documentElement.classList.add("modal-open");
    // Focus the modal for keyboard nav
    const modal = wrap.querySelector(".rpp-modal");
    if (modal) modal.focus();
    // Click on any [data-close] closes; also clicks directly on the backdrop
    wrap.addEventListener("click", (e) => {
      if (e.target.closest("[data-close]")) closeTxDetail();
      else if (e.target === wrap || e.target.classList.contains("rpp-modal-backdrop")) {
        closeTxDetail();
      }
    });
    // Escape key
    wrap._esc = (e) => { if (e.key === "Escape") closeTxDetail(); };
    document.addEventListener("keydown", wrap._esc);
  }

  function closeTxDetail() {
    const wrap = document.getElementById("tx-detail-modal");
    if (wrap) {
      if (wrap._esc) document.removeEventListener("keydown", wrap._esc);
      wrap.remove();
    }
    document.documentElement.classList.remove("modal-open");
  }

  // -------- Filters on sector view --------
  function bindTxFilters() {
    const search = $("#tx-search");
    const pocket = $("#tx-pocket");
    const article = $("#tx-article");
    [search, pocket, article].forEach((e) =>
      e.addEventListener("input", renderTxResults)
    );
  }

  function renderTxResults() {
    const q = ($("#tx-search")?.value || "").toLowerCase().trim();
    const pf = $("#tx-pocket")?.value || "";
    const af = $("#tx-article")?.value || "";
    const items = state.registrations.filter((r) => {
      if (pf && r.property.pocket !== pf) return false;
      if (af && r.article !== af) return false;
      if (q) {
        const hay = [
          r.seller.name, r.seller.address,
          r.purchaser.name, r.purchaser.address,
          r.property.raw_plot_number, r.property.pocket, r.registration_no,
        ].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    items.sort((a, b) => b.registration_date.localeCompare(a.registration_date));
    const wrap = $("#tx-results");
    wrap.innerHTML = "";
    if (items.length === 0) {
      wrap.innerHTML = '<div class="empty">No matching transactions</div>';
      return;
    }
    wrap.appendChild(el("div", { class: "tx-list", id: "tx-list-mobile" }));
    wrap.appendChild(el("div", { class: "table-wrap" },
      el("table", { class: "tx-table" },
        el("thead", {},
          el("tr", {},
            el("th", {}, "Date"), el("th", {}, "Article"),
            el("th", {}, "Parties"), el("th", {}, "Plot / Pocket"),
            el("th", {}, "Area (m²)"),
          )
        ),
        el("tbody", { id: "tx-tbody" })
      )
    ));
    renderTxListMobile(items.slice(0, 50), "#tx-list-mobile");
    renderTxTable(items.slice(0, 50), "#tx-tbody");
    if (items.length > 50) {
      wrap.appendChild(el("p", { style: "text-align:center;margin-top:12px;font-size:13px;color:var(--text-2)" },
        `Showing first 50 of ${items.length} matching. `,
        el("a", { href: "#/sector/28/all" }, "Open full table →")
      ));
    }
  }

  // -------- List view (all transactions) --------
  function viewList() {
    setActiveNav("list");
    renderBreadcrumb([
      { label: "Overview", href: "#/" },
      { label: "Sector 28", href: "#/sector/28" },
      { label: "All transactions" },
    ]);
    const html = `
      <a href="#/sector/28" class="back-link">Back to Sector 28</a>
      <section class="hero">
        <h1>All Sector 28 Transactions</h1>
        <p>${state.meta.total_registrations} registrations · ${esc(state.meta.date_from)} → ${esc(state.meta.date_to)}</p>
      </section>

      <div class="card">
        <div class="filters">
          <input type="search" id="tx-search" placeholder="Search…" inputmode="search" />
          <select id="tx-pocket">
            <option value="">All pockets</option>
            ${Object.keys(state.summary.pockets).map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("")}
          </select>
          <select id="tx-article">
            <option value="">All articles</option>
            ${Object.keys(state.meta.articles).map((a) => `<option value="${esc(a)}">${esc(a)}</option>`).join("")}
          </select>
          <select id="tx-sort">
            <option value="date-desc">Newest first</option>
            <option value="date-asc">Oldest first</option>
            <option value="area-desc">Largest plot area</option>
            <option value="area-asc">Smallest plot area</option>
          </select>
        </div>
        <div id="tx-results"></div>
      </div>
    `;
    $("#view").innerHTML = html;
    bindTxFilters();
    $("#tx-sort").addEventListener("change", renderListResults);
    renderListResults();
  }

  function renderListResults() {
    const q = ($("#tx-search")?.value || "").toLowerCase().trim();
    const pf = $("#tx-pocket")?.value || "";
    const af = $("#tx-article")?.value || "";
    const sort = $("#tx-sort")?.value || "date-desc";
    const items = state.registrations.filter((r) => {
      if (pf && r.property.pocket !== pf) return false;
      if (af && r.article !== af) return false;
      if (q) {
        const hay = [
          r.seller.name, r.seller.address,
          r.purchaser.name, r.purchaser.address,
          r.property.raw_plot_number, r.property.pocket, r.registration_no,
        ].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    items.sort((a, b) => {
      if (sort === "date-asc") return a.registration_date.localeCompare(b.registration_date);
      if (sort === "date-desc") return b.registration_date.localeCompare(a.registration_date);
      if (sort === "area-asc")
        return (a.property.description.plot_area_sqm || 0) - (b.property.description.plot_area_sqm || 0);
      if (sort === "area-desc")
        return (b.property.description.plot_area_sqm || 0) - (a.property.description.plot_area_sqm || 0);
      return 0;
    });
    const wrap = $("#tx-results");
    wrap.innerHTML = "";
    if (items.length === 0) {
      wrap.innerHTML = '<div class="empty">No matching transactions</div>';
      return;
    }
    wrap.appendChild(el("div", { class: "tx-list", id: "tx-list-mobile" }));
    wrap.appendChild(el("div", { class: "table-wrap" },
      el("table", { class: "tx-table" },
        el("thead", {},
          el("tr", {},
            el("th", {}, "Date"), el("th", {}, "Article"),
            el("th", {}, "Parties"), el("th", {}, "Plot / Pocket"),
            el("th", {}, "Plot area"), el("th", {}, "Plinth area"),
            el("th", {}, "Reg #"),
          )
        ),
        el("tbody", { id: "tx-tbody" })
      )
    ));
    renderTxListMobile(items, "#tx-list-mobile");
    const tbody = $("#tx-tbody");
    tbody.innerHTML = "";
    items.forEach((r) => {
      const d = r.property.description;
      const tr = el("tr", {
        class: "tx-row",
        "data-tx-id": r.id,
        tabindex: "0",
        role: "button",
        "aria-label": `View details for ${r.seller.name || "unknown"} to ${r.purchaser.name || "unknown"}`,
      });
      tr.innerHTML = `
        <td class="date">${fmtDate(r.registration_date)}</td>
        <td>${articleBadge(r.article)}</td>
        <td class="parties">
          ${esc(r.seller.name || "(unknown)")}
          <span class="arrow">→</span>
          ${esc(r.purchaser.name || "(unknown)")}
        </td>
        <td>${esc(r.property.pocket)}<br><span style="font-size:11px;color:var(--text-2)">${esc(r.property.raw_plot_number)}</span></td>
        <td>${d.plot_area_sqm ? fmtNum(d.plot_area_sqm, 1) + " m²" : "—"}</td>
        <td>${d.plinth_area_sqm ? fmtNum(d.plinth_area_sqm, 1) + " m²" : "—"}</td>
        <td style="font-size:11px;color:var(--text-2)">${esc(r.registration_no)}</td>
      `;
      tr.addEventListener("click", () => openTxDetail(r.id));
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openTxDetail(r.id);
        }
      });
      tbody.appendChild(tr);
    });
  }

  // -------- Router --------
  async function render() {
    const r = parseRoute();
    state.route = r;
    closeMobileNav();
    try {
      await loadData();
      if (r.name === "overview") return viewOverview();
      if (r.name === "sector") return viewSector(r.params);
      if (r.name === "pocket") return viewPocket(r.params);
      if (r.name === "list") return viewList();
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
    nav.addEventListener("click", (e) => {
      if (e.target.tagName === "A") closeMobileNav();
    });
  }

  function initFooter() {
    const m = state.meta;
    if (!m) return;
    $("#footer-meta").textContent =
      `Last generated ${m.generated_at} · ${m.total_registrations} records`;
  }

  let appInitialized = false;
  function init() {
    if (appInitialized) return;
    appInitialized = true;
    initNavToggle();
    initSignout();
    window.addEventListener("hashchange", render);
    render().then(initFooter);
  }

  function initSignout() {
    const link = document.getElementById("signout-link");
    if (!link) return;
    link.addEventListener("click", (e) => {
      e.preventDefault();
      if (window.rppLock) {
        window.rppLock();
      } else {
        location.reload();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      // Wait for auth to complete; auth.js fires rpp:ready when it's safe
      if (window.rppAuthReady) init();
      else window.addEventListener("rpp:ready", init, { once: true });
    });
  } else {
    if (window.rppAuthReady) init();
    else window.addEventListener("rpp:ready", init, { once: true });
  }
})();
