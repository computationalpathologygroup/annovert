/**
 * annovert viewer
 *
 * Views
 * ------
 *   overview  -- annotation card grid; group breakdown per file
 *   inspect   -- OpenSeadragon deep-zoom (with WSI) or canvas (without WSI)
 *                colour-coded polygon overlays, click to inspect properties
 *
 * Layers
 * -------
 *   converted -- the output .geojson from annovert (solid fill + stroke)
 *   source    -- original annotation XML served via /api/source/{stem}
 *                drawn as dashed strokes, same group colours, no fill
 *                only available when --source dir is supplied to the server
 *
 * Coordinate chain (inspect + WSI)
 * ----------------------------------
 *   GeoJSON coord (level-0 pixel space)
 *     * scale_to_viewport (= 1/slide_W)  -> OSD viewport x in [0,1]
 *   viewportToViewerElementCoordinates() -> canvas CSS pixel
 *
 * Coordinate chain (inspect, no WSI)
 * ------------------------------------
 *   ctx.setTransform(scale, 0, 0, scale, tx, ty) applied before drawing;
 *   geometry is drawn directly in GeoJSON coordinate space.
 */

"use strict";

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────

const S = {
  view:             "overview",
  index:            null,           // /api/index payload
  activeStem:       null,
  activeGroups:     new Set(),      // groups visible in inspect view
  overlayCache:     {},             // stem -> { features, scale, bbox, has_source }
  sourceCache:      {},             // stem -> { features, scale, bbox } | null
  compareOn:        false,          // whether source comparison layer is active
  viewer:           null,           // OSD Viewer (inspect, has-WSI)
  overlayCanvas:    null,           // <canvas> layered on OSD
  noWsiCanvas:      null,           // <canvas> for annotation-only view
  noWsiTx:          { scale: 1, tx: 0, ty: 0 },
  selectedFeat:     null,
  _abortController: null,           // cleans up no-WSI event listeners
  _osdAbort:        null,           // cleans up OSD click handler
  cardObserver:     null,           // IntersectionObserver for overview card canvases
};

// ─────────────────────────────────────────────────────────────────────────────
// Boot
// ─────────────────────────────────────────────────────────────────────────────

async function init() {
  let res;
  try {
    res = await fetch("/api/index");
    if (!res.ok) throw new Error(res.statusText);
  } catch (err) {
    document.body.innerHTML =
      `<p style="padding:2rem;color:#f44">Failed to load index: ${err.message}</p>`;
    return;
  }
  S.index = await res.json();

  document.getElementById("dir-label").textContent =
    S.index.output_dir.split("/").at(-1);
  const n = S.index.annotations.length;
  document.getElementById("count-chip").textContent =
    `${n} file${n !== 1 ? "s" : ""}`;

  buildSidebar();
  buildGroupToggles();   // right-panel chips (built once)
  buildGroupLegend();    // overview toolbar legend
  renderOverview();

  // Compare toggle is in the panel, wired per-stem in openInspect

  document.querySelectorAll(".tab").forEach((btn) =>
    btn.addEventListener("click", () => switchView(btn.dataset.view))
  );

  document.getElementById("search").addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll("#sidebar-list li").forEach((li) =>
      li.classList.toggle("hidden", !li.dataset.stem.toLowerCase().includes(q))
    );
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Sidebar
// ─────────────────────────────────────────────────────────────────────────────

function buildSidebar() {
  const ul = document.getElementById("sidebar-list");
  ul.innerHTML = "";
  for (const ann of S.index.annotations) {
    const li = document.createElement("li");
    li.dataset.stem = ann.stem;
    li.innerHTML = `
      <span class="wsi-dot ${ann.has_wsi ? "has-wsi" : ""}"></span>
      <span class="wsi-stem" title="${_esc(ann.stem)}">${_esc(ann.stem)}</span>
      <span class="feat-badge">${ann.feature_count}</span>`;
    li.addEventListener("click", () => selectStem(ann.stem));
    ul.appendChild(li);
  }
}

function _updateSidebarActive(stem) {
  document.querySelectorAll("#sidebar-list li").forEach((li) =>
    li.classList.toggle("active", li.dataset.stem === stem)
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Overview
// ─────────────────────────────────────────────────────────────────────────────

function buildGroupLegend() {
  const el = document.getElementById("group-legend");
  el.innerHTML = "";
  const { all_groups, group_colors } = S.index;
  for (const g of all_groups) {
    const color = group_colors[g] || "#94a3b8";
    const chip = document.createElement("span");
    chip.className = "legend-chip";
    chip.innerHTML =
      `<span class="legend-dot" style="background:${color}"></span>` +
      _esc(g === "_ungrouped" ? "(no group)" : g);
    el.appendChild(chip);
  }
}

function renderOverview() {
  const grid = document.getElementById("overview-grid");
  grid.innerHTML = "";
  const { annotations, group_colors } = S.index;

  for (const ann of annotations) {
    const card = document.createElement("div");
    card.className = "ann-card";
    card.dataset.stem = ann.stem;
    if (S.activeStem === ann.stem) card.classList.add("active");

    const groupRows = ann.groups.map((g) => {
      const color  = group_colors[g] || "#94a3b8";
      const cnt    = ann.group_counts[g] ?? 0;
      const label  = g === "_ungrouped" ? "(no group)" : g;
      return `<div class="card-group-row">
        <span class="cgdot" style="background:${color}"></span>
        <span class="cgname">${_esc(label)}</span>
        <span class="cgcount">${cnt}</span>
      </div>`;
    }).join("") || `<span class="no-groups">no annotations</span>`;

    const wsiBadge = ann.has_wsi ? `<span class="badge-wsi">WSI</span>` : "";

    card.innerHTML = `
      <canvas class="card-canvas"></canvas>
      <div class="card-head">
        <span class="card-stem" title="${_esc(ann.stem)}">${_esc(ann.stem)}</span>
        ${wsiBadge}
      </div>
      <div class="card-total">${ann.feature_count} annotation${ann.feature_count !== 1 ? "s" : ""}</div>
      <div class="card-groups">${groupRows}</div>`;

    card.addEventListener("click", () => { selectStem(ann.stem); switchView("inspect"); });
    grid.appendChild(card);
  }

  _setupCardObserver();
}

// ─────────────────────────────────────────────────────────────────────────────
// Overview card canvas (lazy mini-preview)
// ─────────────────────────────────────────────────────────────────────────────

function _setupCardObserver() {
  if (S.cardObserver) { S.cardObserver.disconnect(); S.cardObserver = null; }
  const cards = document.querySelectorAll(".ann-card[data-stem]");
  if (!"IntersectionObserver" in window) {
    cards.forEach(_loadCardCanvas);
    return;
  }
  S.cardObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        _loadCardCanvas(entry.target);
        S.cardObserver.unobserve(entry.target);
      }
    }
  }, { rootMargin: "200px" });
  cards.forEach((c) => S.cardObserver.observe(c));
}

async function _loadCardCanvas(card) {
  const stem   = card.dataset.stem;
  const canvas = card.querySelector(".card-canvas");
  if (!canvas || canvas.dataset.loaded) return;
  canvas.dataset.loaded = "1";
  await _ensureOverlay(stem);
  const overlay = S.overlayCache[stem];
  if (!overlay?.features.length) return;
  _drawCardCanvas(canvas, overlay.features);
}

function _drawCardCanvas(canvas, features) {
  const w = canvas.offsetWidth;
  const h = canvas.offsetHeight;
  if (!w || !h) return;
  canvas.width  = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#1a1a2e";
  ctx.fillRect(0, 0, w, h);
  const bbox = _computeBbox(features);
  if (!bbox) return;
  const tx = _fitTransform(bbox, w, h, 6);
  ctx.save();
  ctx.setTransform(tx.scale, 0, 0, tx.scale, tx.tx, tx.ty);
  const { group_colors } = S.index;
  const byGroup = new Map();
  for (const f of features) {
    const g = _getGroup(f);
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g).push(f);
  }
  for (const [g, gFeatures] of byGroup) {
    const color = group_colors[g] || "#94a3b8";
    ctx.beginPath();
    for (const f of gFeatures) {
      if (f.geometry) _traceGeometry(ctx, f.geometry, null, null, true);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.5 / tx.scale;
    ctx.globalAlpha = 0.9;
    ctx.stroke();
    ctx.fillStyle   = _hexToRgba(color, 0.15);
    ctx.globalAlpha = 1;
    ctx.fill();
  }
  ctx.restore();
}

// ─────────────────────────────────────────────────────────────────────────────
// Stem selection & inspect
// ─────────────────────────────────────────────────────────────────────────────

async function selectStem(stem) {
  S.activeStem   = stem;
  S.selectedFeat = null;
  S.compareOn    = false;  // reset compare when switching files
  _updateSidebarActive(stem);
  document.querySelectorAll(".ann-card").forEach((c) =>
    c.classList.toggle("active", c.dataset.stem === stem)
  );
  if (S.view === "inspect") await openInspect(stem);
}

async function openInspect(stem) {
  const ann = S.index.annotations.find((a) => a.stem === stem);
  if (!ann) return;

  // Show panel
  document.getElementById("panel-empty").style.display = "none";
  document.getElementById("panel-inspect").style.display = "flex";
  document.getElementById("panel-stem").textContent  = stem;
  document.getElementById("panel-count").textContent =
    `${ann.feature_count} annotation${ann.feature_count !== 1 ? "s" : ""}`;

  // Fetch overlay (cached after first load)
  await _ensureOverlay(stem);
  const overlay = S.overlayCache[stem];

  // Reset group visibility and update counts for this stem
  S.activeGroups = new Set(S.index.all_groups);
  _refreshGroupChips();
  _updateGroupCounts(stem);
  _updateSelectedPanel(null);
  _refreshCompareChip(stem);

  _destroyViewers();

  if (!overlay?.features.length) {
    document.getElementById("inspect-empty").style.display = "flex";
    return;
  }
  document.getElementById("inspect-empty").style.display = "none";

  if (ann.has_wsi) {
    _openOsd(stem, overlay);
  } else {
    _openNoWsi(stem, overlay);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Overlay fetch
// ─────────────────────────────────────────────────────────────────────────────

async function _ensureOverlay(stem) {
  if (S.overlayCache[stem]) return;
  try {
    const res = await fetch(`/api/overlay/${encodeURIComponent(stem)}`);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    S.overlayCache[stem] = {
      features:   data.features ?? [],
      scale:      data._meta?.scale_to_viewport ?? null,
      bbox:       data._meta?.bbox ?? null,
      has_source: data._meta?.has_source ?? false,
    };
  } catch (err) {
    console.error("Overlay fetch failed:", err);
    S.overlayCache[stem] = { features: [], scale: null, bbox: null, has_source: false };
  }
}

async function _ensureSource(stem) {
  if (stem in S.sourceCache) return;  // null means already tried + not found
  try {
    const res = await fetch(`/api/source/${encodeURIComponent(stem)}`);
    if (!res.ok) {
      const msg = await res.text().catch(() => res.statusText);
      console.error(`Source fetch ${stem}: HTTP ${res.status}`, msg);
      S.sourceCache[stem] = null; return;
    }
    const data = await res.json();
    S.sourceCache[stem] = {
      features: data.features ?? [],
      scale:    data._meta?.scale_to_viewport ?? S.overlayCache[stem]?.scale ?? null,
      bbox:     data._meta?.bbox ?? null,
    };
    console.log(`Source loaded ${stem}: ${S.sourceCache[stem].features.length} features`);
  } catch (err) {
    console.error("Source fetch failed:", err);
    S.sourceCache[stem] = null;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// OSD viewer  (has-WSI path)
// ─────────────────────────────────────────────────────────────────────────────

function _openOsd(stem, overlay) {
  const osdEl = document.getElementById("osd-viewer");
  document.getElementById("no-wsi-container").style.display = "none";
  osdEl.style.display = "";

  S.viewer = OpenSeadragon({
    element:   osdEl,
    prefixUrl: "https://cdn.jsdelivr.net/npm/openseadragon@4.1/build/openseadragon/images/",
    tileSources:      `/api/wsi/${encodeURIComponent(stem)}/dzi`,
    showNavigationControl: true,
    showNavigator:    true,
    navigatorPosition: "BOTTOM_RIGHT",
    navigatorSizeRatio: 0.14,
    animationTime: 0.35,
    blendTime:     0.1,
    constrainDuringPan: false,
    maxZoomPixelRatio: 8,
    minZoomLevel:   0.05,
    zoomPerClick:   2,
    zoomPerScroll:  1.25,
    gestureSettingsMouse: { scrollToZoom: true, clickToZoom: false },
    backgroundColor: "#1a1a2e",
  });

  S.viewer.addHandler("open", () => {
    requestAnimationFrame(() => { _initOsdCanvas(); drawOsdOverlay(); });
  });
  S.viewer.addHandler("animation",       _scheduleOsdRedraw);
  S.viewer.addHandler("animation-finish", drawOsdOverlay);
  S.viewer.addHandler("update-viewport",  _scheduleOsdRedraw);
  S.viewer.addHandler("resize",  () => { _syncOsdCanvas(); drawOsdOverlay(); });
}

let _rafPending = false;
function _scheduleOsdRedraw() {
  if (_rafPending) return;
  _rafPending = true;
  requestAnimationFrame(() => { _rafPending = false; drawOsdOverlay(); });
}

function _initOsdCanvas() {
  document.getElementById("osd-overlay-canvas")?.remove();
  const canvas = document.createElement("canvas");
  canvas.id = "osd-overlay-canvas";
  // Append directly to the OSD element (which OSD sets to position:relative)
  // so position:absolute inset fills it correctly and z-index puts it on top.
  canvas.style.cssText = "position:absolute;top:0;left:0;pointer-events:none;z-index:5;";
  S.viewer.element.appendChild(canvas);
  S.overlayCanvas = canvas;
  _syncOsdCanvas();
  // Attach click handler via AbortController so it's removed cleanly on teardown
  if (S._osdAbort) S._osdAbort.abort();
  S._osdAbort = new AbortController();
  S.viewer.element.addEventListener("click", _handleOsdClick, { signal: S._osdAbort.signal });
}

function _syncOsdCanvas() {
  if (!S.overlayCanvas || !S.viewer) return;
  const { clientWidth: w, clientHeight: h } = S.viewer.element;
  if (!w || !h) return;
  S.overlayCanvas.width        = w;
  S.overlayCanvas.height       = h;
  S.overlayCanvas.style.width  = `${w}px`;
  S.overlayCanvas.style.height = `${h}px`;
}

function drawOsdOverlay() {
  if (!S.overlayCanvas || !S.viewer) return;
  const ctx = S.overlayCanvas.getContext("2d");
  ctx.clearRect(0, 0, S.overlayCanvas.width, S.overlayCanvas.height);

  const overlay = S.overlayCache[S.activeStem];
  if (!overlay?.features.length || overlay.scale == null) return;
  // Draw converted layer first, then source dashes on top so they are visible
  _drawFeatures(ctx, overlay.features, overlay.scale, S.viewer, false, false);
  if (S.compareOn) {
    const src = S.sourceCache[S.activeStem];
    // For no-WSI source, fall back to overlay.scale so the coordinates still project
    const srcScale = src?.scale ?? overlay.scale;
    if (src?.features.length) {
      _drawFeatures(ctx, src.features, srcScale, S.viewer, false, true);
    }
  }
}

function _handleOsdClick(e) {
  const overlay = S.overlayCache[S.activeStem];
  if (!overlay?.features.length || overlay.scale == null || !S.viewer) return;

  const rect = S.viewer.element.getBoundingClientRect();
  const vp   = S.viewer.viewport.viewerElementToViewportCoordinates(
    new OpenSeadragon.Point(e.clientX - rect.left, e.clientY - rect.top)
  );
  const gx = vp.x / overlay.scale;
  const gy = vp.y / overlay.scale;

  S.selectedFeat = _hitTest(overlay.features, gx, gy);
  _updateSelectedPanel(S.selectedFeat);
  drawOsdOverlay();
}

// ─────────────────────────────────────────────────────────────────────────────
// No-WSI canvas  (annotation-only path: pan + zoom + click)
// ─────────────────────────────────────────────────────────────────────────────

function _openNoWsi(stem, overlay) {
  document.getElementById("osd-viewer").style.display = "none";
  const container = document.getElementById("no-wsi-container");
  container.style.display = "";

  // Fresh canvas each time to avoid accumulating listeners
  document.getElementById("no-wsi-canvas")?.remove();
  const canvas = document.createElement("canvas");
  canvas.id = "no-wsi-canvas";
  container.appendChild(canvas);
  S.noWsiCanvas = canvas;

  const w = container.clientWidth;
  const h = container.clientHeight;
  canvas.width  = w;  canvas.height  = h;
  canvas.style.width = `${w}px`;  canvas.style.height = `${h}px`;

  const bbox    = overlay.bbox ?? _computeBbox(overlay.features);
  S.noWsiTx     = bbox ? _fitTransform(bbox, w, h, 48) : { scale: 1, tx: 0, ty: 0 };

  _setupNoWsiEvents(canvas, container);
  drawNoWsiCanvas();
}

function _setupNoWsiEvents(canvas, container) {
  if (S._abortController) S._abortController.abort();
  S._abortController = new AbortController();
  const { signal } = S._abortController;

  canvas.style.cursor = "grab";

  // Wheel zoom centred on cursor
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect   = canvas.getBoundingClientRect();
    const mx     = e.clientX - rect.left;
    const my     = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    S.noWsiTx.tx  = mx - (mx - S.noWsiTx.tx) * factor;
    S.noWsiTx.ty  = my - (my - S.noWsiTx.ty) * factor;
    S.noWsiTx.scale *= factor;
    drawNoWsiCanvas();
  }, { passive: false, signal });

  // Pan drag (mousedown on canvas, move/up on window)
  let dragging = false, dragStart = null, origTx = 0, origTy = 0;

  canvas.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    dragging  = true;
    dragStart = { x: e.clientX, y: e.clientY };
    origTx    = S.noWsiTx.tx;
    origTy    = S.noWsiTx.ty;
    canvas.style.cursor = "grabbing";
  }, { signal });

  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    S.noWsiTx.tx = origTx + (e.clientX - dragStart.x);
    S.noWsiTx.ty = origTy + (e.clientY - dragStart.y);
    drawNoWsiCanvas();
  }, { signal });

  window.addEventListener("mouseup", (e) => {
    if (!dragging) return;
    const dx = e.clientX - dragStart.x;
    const dy = e.clientY - dragStart.y;
    dragging = false;
    canvas.style.cursor = "grab";
    // Small movement -> treat as annotation click
    if (Math.abs(dx) < 5 && Math.abs(dy) < 5) {
      const rect = canvas.getBoundingClientRect();
      _handleNoWsiClick(e.clientX - rect.left, e.clientY - rect.top);
    }
  }, { signal });

  // Keep canvas filling its container on resize
  window.addEventListener("resize", () => {
    if (!S.noWsiCanvas) return;
    const w2 = container.clientWidth;
    const h2 = container.clientHeight;
    canvas.width  = w2;  canvas.height  = h2;
    canvas.style.width = `${w2}px`;  canvas.style.height = `${h2}px`;
    drawNoWsiCanvas();
  }, { signal });
}

function drawNoWsiCanvas() {
  const canvas = S.noWsiCanvas;
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#1a1a2e";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const overlay = S.overlayCache[S.activeStem];
  if (!overlay?.features.length) return;

  ctx.save();
  ctx.setTransform(S.noWsiTx.scale, 0, 0, S.noWsiTx.scale, S.noWsiTx.tx, S.noWsiTx.ty);
  // Draw converted first, then source dashes on top so they are clearly visible
  _drawFeatures(ctx, overlay.features, null, null, true, false);
  if (S.compareOn) {
    const src = S.sourceCache[S.activeStem];
    if (src?.features.length) {
      _drawFeatures(ctx, src.features, null, null, true, true);
    }
  }
  ctx.restore();
}

function _handleNoWsiClick(cx, cy) {
  const overlay = S.overlayCache[S.activeStem];
  if (!overlay?.features.length) return;
  const gx = (cx - S.noWsiTx.tx) / S.noWsiTx.scale;
  const gy = (cy - S.noWsiTx.ty) / S.noWsiTx.scale;
  S.selectedFeat = _hitTest(overlay.features, gx, gy);
  _updateSelectedPanel(S.selectedFeat);
  drawNoWsiCanvas();
}

// ─────────────────────────────────────────────────────────────────────────────
// Feature rendering  (shared by OSD overlay and no-WSI canvas)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Draw all visible features colour-coded by group.
 * In noWsi mode ctx.setTransform is already applied, so geometry uses raw geo coords.
 * In OSD mode each coordinate is projected through OSD's viewport transform.
 * @param {boolean} isSource - if true, render as dashed "source" style (no fill, dash)
 */
function _drawFeatures(ctx, features, scale, viewer, noWsi, isSource) {
  const { group_colors } = S.index;
  const lw = noWsi ? 1.5 / S.noWsiTx.scale : 1.5;
  const srcLw = noWsi ? 2.0 / S.noWsiTx.scale : 2.0;

  // Batch draw by group (skip selected feature -- drawn last with highlight)
  const byGroup = new Map();
  for (const f of features) {
    if (!isSource && f === S.selectedFeat) continue;
    const g = _getGroup(f);
    // Source layer always renders all features regardless of group toggles
    if (!isSource && !S.activeGroups.has(g)) continue;
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g).push(f);
  }

  for (const [g, gFeatures] of byGroup) {
    const color = group_colors[g] || "#94a3b8";
    ctx.beginPath();
    for (const f of gFeatures) {
      if (f.geometry) _traceGeometry(ctx, f.geometry, scale, viewer, noWsi);
    }
    ctx.strokeStyle  = color;
    if (isSource) {
      ctx.lineWidth   = srcLw;
      ctx.globalAlpha = 0.90;
      ctx.setLineDash(noWsi ? [8 / S.noWsiTx.scale, 5 / S.noWsiTx.scale] : [8, 5]);
      ctx.stroke();
      ctx.setLineDash([]);
    } else {
      ctx.lineWidth    = lw;
      ctx.globalAlpha  = 0.9;
      ctx.stroke();
      ctx.fillStyle    = _hexToRgba(color, 0.10);
      ctx.globalAlpha  = 1;
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  // Highlight selected feature on top (converted layer only)
  if (!isSource && S.selectedFeat) {
    const f = S.selectedFeat;
    const g = _getGroup(f);
    if (f.geometry && S.activeGroups.has(g)) {
      const color = group_colors[g] || "#94a3b8";
      ctx.beginPath();
      _traceGeometry(ctx, f.geometry, scale, viewer, noWsi);
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth   = noWsi ? 2.5 / S.noWsiTx.scale : 2.5;
      ctx.globalAlpha = 1;
      ctx.stroke();
      ctx.fillStyle   = _hexToRgba(color, 0.28);
      ctx.fill();
    }
  }
}

function _traceGeometry(ctx, geometry, scale, viewer, noWsi) {
  const { type, coordinates } = geometry;
  if (type === "Polygon") {
    _traceRing(ctx, coordinates[0], scale, viewer, noWsi);
  } else if (type === "MultiPolygon") {
    for (const poly of coordinates) _traceRing(ctx, poly[0], scale, viewer, noWsi);
  } else if (type === "Point") {
    const [px, py] = _project(coordinates, scale, viewer, noWsi);
    const r = noWsi ? 5 / S.noWsiTx.scale : 5;
    ctx.moveTo(px + r, py);
    ctx.arc(px, py, r, 0, 2 * Math.PI);
  }
}

function _traceRing(ctx, ring, scale, viewer, noWsi) {
  if (!ring || ring.length < 3) return;
  let first = true;
  for (const coord of ring) {
    const [cx, cy] = _project(coord, scale, viewer, noWsi);
    if (first) { ctx.moveTo(cx, cy); first = false; }
    else          ctx.lineTo(cx, cy);
  }
  ctx.closePath();
}

function _project(coord, scale, viewer, noWsi) {
  // noWsi: ctx.setTransform is applied; return raw geo coords unchanged
  if (noWsi) return [coord[0], coord[1]];
  // OSD: convert geo pixel -> viewport -> canvas CSS pixel
  const pt = viewer.viewport.viewportToViewerElementCoordinates(
    new OpenSeadragon.Point(coord[0] * scale, coord[1] * scale)
  );
  return [pt.x, pt.y];
}

// ─────────────────────────────────────────────────────────────────────────────
// Hit testing
// ─────────────────────────────────────────────────────────────────────────────

function _hitTest(features, gx, gy) {
  // Check in reverse render order so top-drawn features are hit first
  for (let i = features.length - 1; i >= 0; i--) {
    const f = features[i];
    if (!S.activeGroups.has(_getGroup(f)) || !f.geometry) continue;
    const { type, coordinates } = f.geometry;
    if (type === "Polygon") {
      if (_pointInRing(gx, gy, coordinates[0])) return f;
    } else if (type === "MultiPolygon") {
      for (const poly of coordinates) {
        if (_pointInRing(gx, gy, poly[0])) return f;
      }
    } else if (type === "Point") {
      const [px, py] = coordinates;
      if (Math.abs(gx - px) < 10 && Math.abs(gy - py) < 10) return f;
    }
  }
  return null;
}

function _pointInRing(px, py, ring) {
  if (!ring || ring.length < 3) return false;
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

// ─────────────────────────────────────────────────────────────────────────────
// Compare toggle  (right panel, per-stem)
// ─────────────────────────────────────────────────────────────────────────────

function _refreshCompareChip(stem) {
  const container = document.getElementById("compare-section");
  const overlay   = S.overlayCache[stem];
  const available = overlay?.has_source ?? false;

  if (!available) {
    container.style.display = "none";
    S.compareOn = false;
    return;
  }
  container.style.display = "";

  const chip = document.getElementById("compare-chip");
  chip.classList.toggle("active", S.compareOn);
  chip.querySelector(".compare-status").textContent = S.compareOn ? "on" : "off";

  // Wire click only once (flag on element)
  if (!chip._wired) {
    chip._wired = true;
    chip.addEventListener("click", async () => {
      S.compareOn = !S.compareOn;
      chip.classList.toggle("active", S.compareOn);
      chip.querySelector(".compare-status").textContent = S.compareOn ? "on" : "off";
      if (S.compareOn) {
        const lbl = chip.querySelector(".compare-label");
        lbl.textContent = "loading\u2026";
        await _ensureSource(S.activeStem);
        const src = S.sourceCache[S.activeStem];
        if (!src?.features.length) {
          lbl.textContent = "Source overlay (unavailable)";
          S.compareOn = false;
          chip.classList.remove("active");
          chip.querySelector(".compare-status").textContent = "off";
        } else {
          lbl.textContent = "Source overlay (" + src.features.length + " ann.)";
        }
      } else {
        chip.querySelector(".compare-label").textContent = "Source overlay";
      }
      if (S.viewer)           drawOsdOverlay();
      else if (S.noWsiCanvas) drawNoWsiCanvas();
    });
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Group toggles  (right panel -- built once on init)
// ─────────────────────────────────────────────────────────────────────────────

function buildGroupToggles() {
  const container = document.getElementById("group-toggles");
  container.innerHTML = "";
  const { all_groups, group_colors } = S.index;
  for (const g of all_groups) {
    const color = group_colors[g] || "#94a3b8";
    const chip  = document.createElement("div");
    chip.className    = "group-chip active";
    chip.dataset.group = g;
    chip.innerHTML = `
      <span class="chip-swatch" style="background:${color}"></span>
      <span class="chip-name">${_esc(g === "_ungrouped" ? "(no group)" : g)}</span>
      <span class="chip-count" id="gcount-${_esc(g)}"></span>`;
    chip.addEventListener("click", () => _toggleGroup(g, chip));
    container.appendChild(chip);
  }
}

function _toggleGroup(group, chipEl) {
  if (S.activeGroups.has(group)) {
    S.activeGroups.delete(group);
    chipEl.classList.remove("active");
  } else {
    S.activeGroups.add(group);
    chipEl.classList.add("active");
  }
  if (S.viewer)       drawOsdOverlay();
  else if (S.noWsiCanvas) drawNoWsiCanvas();
}

function _refreshGroupChips() {
  document.querySelectorAll(".group-chip").forEach((chip) =>
    chip.classList.toggle("active", S.activeGroups.has(chip.dataset.group))
  );
}

function _updateGroupCounts(stem) {
  // Zero all counts first
  document.querySelectorAll(".chip-count").forEach((el) => (el.textContent = "0"));
  const overlay = S.overlayCache[stem];
  if (!overlay) return;
  const counts = {};
  for (const f of overlay.features) {
    const g = _getGroup(f);
    counts[g] = (counts[g] || 0) + 1;
  }
  for (const [g, cnt] of Object.entries(counts)) {
    const el = document.getElementById(`gcount-${g}`);
    if (el) el.textContent = cnt;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Selected annotation panel
// ─────────────────────────────────────────────────────────────────────────────

function _updateSelectedPanel(feature) {
  const el = document.getElementById("selected-info");
  if (!feature) {
    el.innerHTML = `<span class="no-selection">Click an annotation to inspect it</span>`;
    return;
  }
  const g     = _getGroup(feature);
  const color = S.index.group_colors[g] || "#94a3b8";
  const props = feature.properties || {};

  const fields = [
    ["Name",   props.name   ?? "—"],
    ["Group",  props.group  ?? "(none)"],
    ["Type",   props.type   ?? feature.geometry?.type ?? "—"],
    ["Source", props.source ?? "—"],
  ];

  const nPts = _countPoints(feature.geometry);
  if (nPts) fields.push(["Vertices", nPts]);

  const rows = fields.map(([k, v]) =>
    `<div class="prop-row">
      <span class="prop-key">${k}</span>
      <span class="prop-val">${_esc(String(v))}</span>
    </div>`
  ).join("");

  el.innerHTML =
    `<div class="selected-group-banner" style="border-left-color:${color}">${rows}</div>`;
}

function _countPoints(geometry) {
  if (!geometry) return 0;
  if (geometry.type === "Polygon") {
    const n = geometry.coordinates[0]?.length ?? 0;
    return n > 0 ? n - 1 : 0;  // subtract closing duplicate
  }
  if (geometry.type === "MultiPolygon")
    return geometry.coordinates.reduce((s, p) => {
      const n = p[0]?.length ?? 0;
      return s + (n > 0 ? n - 1 : 0);
    }, 0);
  return 0;
}

// ─────────────────────────────────────────────────────────────────────────────
// View switching
// ─────────────────────────────────────────────────────────────────────────────

async function switchView(view) {
  S.view = view;
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === view)
  );
  document.getElementById("view-overview").style.display =
    view === "overview" ? "" : "none";
  document.getElementById("view-inspect").style.display =
    view === "inspect" ? "" : "none";
  if (view === "inspect" && S.activeStem) await openInspect(S.activeStem);
}

// ─────────────────────────────────────────────────────────────────────────────
// Viewer cleanup
// ─────────────────────────────────────────────────────────────────────────────

function _destroyViewers() {
  if (S._osdAbort) { S._osdAbort.abort(); S._osdAbort = null; }
  if (S.viewer) {
    S.viewer.destroy();
    S.viewer = null;
    S.overlayCanvas = null;
    document.getElementById("osd-overlay-canvas")?.remove();
  }
  if (S._abortController) {
    S._abortController.abort();
    S._abortController = null;
  }
  S.noWsiCanvas = null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Geometry utilities
// ─────────────────────────────────────────────────────────────────────────────

function _computeBbox(features) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const f of features) {
    if (!f.geometry) continue;
    const { type, coordinates } = f.geometry;
    let pts = [];
    if      (type === "Polygon")      pts = coordinates[0] ?? [];
    else if (type === "MultiPolygon") pts = coordinates.flatMap((p) => p[0] ?? []);
    else if (type === "Point")        pts = [coordinates];
    for (const [x, y] of pts) {
      if (x < minX) minX = x;  if (x > maxX) maxX = x;
      if (y < minY) minY = y;  if (y > maxY) maxY = y;
    }
  }
  return isFinite(minX) ? [minX, minY, maxX, maxY] : null;
}

function _fitTransform(bbox, canvasW, canvasH, padding) {
  const [minX, minY, maxX, maxY] = bbox;
  const geoW  = maxX - minX || 1;
  const geoH  = maxY - minY || 1;
  const scale = Math.min((canvasW - 2 * padding) / geoW, (canvasH - 2 * padding) / geoH);
  const tx    = padding + (canvasW - 2 * padding - geoW * scale) / 2 - minX * scale;
  const ty    = padding + (canvasH - 2 * padding - geoH * scale) / 2 - minY * scale;
  return { scale, tx, ty };
}

// ─────────────────────────────────────────────────────────────────────────────
// Micro-utilities
// ─────────────────────────────────────────────────────────────────────────────

function _getGroup(feature) {
  const g = feature.properties?.group;
  return g != null && g !== "" ? g : "_ungrouped";
}

function _hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function _esc(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ─────────────────────────────────────────────────────────────────────────────
init();
