"use strict";

// ---------- DOM refs ----------
const els = {
  station: document.getElementById("sel-station"),
  product: document.getElementById("sel-product"),
  date:    document.getElementById("sel-date"),
  status:  document.getElementById("status"),
  frame:   document.getElementById("frame"),
  loading: document.getElementById("overlay-loading"),
  error:   document.getElementById("overlay-error"),
  empty:   document.getElementById("overlay-empty"),
  elevBar: document.getElementById("elevation-bar"),
  timeline:document.getElementById("timeline"),
  btnPlay: document.getElementById("btn-play"),
  infoTime:document.getElementById("info-time"),
  infoElev:document.getElementById("info-elev"),
  infoCount:document.getElementById("info-count"),
};

// ---------- State ----------
const state = {
  station: "",
  product: "",
  date: "",            // yyyymmdd
  times: [],
  timeLabels: [],
  elevations: [],      // numeric (deg), empty for no-elevation products
  elevationRaws: [],
  hasElev: false,
  matrix: {},          // matrix[time][elevRawOrNull] = frame
  tIdx: 0,
  eIdx: 0,
  isPlaying: false,
  playTimer: null,
  cached: new Set(),   // bin paths confirmed rendered
  renderToken: 0,      // race-guard for async renders
  prerenderToken: 0,
  filesSignature: "",
  autoRefreshTimer: null,
  loadingTimer: null,
  timelineHoverIdx: -1,
};

const PRODUCT_REFRESH_INTERVAL_MS = 5 * 60 * 1000;
const RENDER_LOADING_DELAY_MS = 500;

// ---------- Utilities ----------
function setStatus(msg, kind = "") {
  els.status.textContent = msg || "";
  els.status.className = "status" + (kind ? " " + kind : "");
}

function showOverlay(which, text) {
  for (const el of [els.loading, els.error, els.empty]) el.classList.remove("show");
  if (which) {
    which.textContent = text ?? which.textContent;
    which.classList.add("show");
  }
}

function ymdToInputValue(ymd) { // 20240726 -> 2024-07-26
  if (!ymd || ymd.length !== 8) return "";
  return `${ymd.slice(0,4)}-${ymd.slice(4,6)}-${ymd.slice(6,8)}`;
}
function inputValueToYmd(v) {   // 2024-07-26 -> 20240726
  return (v || "").replaceAll("-", "");
}

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}
async function postJson(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

// ---------- Bootstrap ----------
async function init() {
  bindEvents();
  loadStations();
  showOverlay(els.empty);
}

let stationsPollTimer = null;

async function loadStations() {
  try {
    const r = await getJson("/api/stations");
    const prev = els.station.value;
    fillSelect(els.station, r.stations, "请选择站号");
    const codes = r.stations.map(s => typeof s === "string" ? s : s.code);
    if (prev && codes.includes(prev)) els.station.value = prev;

    if (r.stations.length === 0) {
      if (r.refreshing) {
        setStatus("正在扫描数据目录…(首次需稍候)", "");
        stationsPollTimer = setTimeout(loadStations, 3000);
        return;
      }
      setStatus("未在数据根目录发现任何站点", "err");
      return;
    }

    if (r.refreshing) {
      setStatus("索引刷新中（后台进行，不影响使用）", "");
    } else if (r.updated_at) {
      setStatus(`索引已加载 · ${formatAge(r.updated_at)}前更新`, "ok");
    } else {
      setStatus("");
    }
  } catch (e) {
    setStatus("加载站号失败: " + e.message, "err");
  }
}

function formatAge(updatedAtSec) {
  const ageSec = Math.max(0, Date.now() / 1000 - updatedAtSec);
  if (ageSec < 90) return `${Math.round(ageSec)}秒`;
  if (ageSec < 3600 * 2) return `${Math.round(ageSec / 60)}分钟`;
  return `${(ageSec / 3600).toFixed(1)}小时`;
}

function fillSelect(sel, items, placeholder) {
  sel.innerHTML = "";
  const opt = document.createElement("option");
  opt.value = "";
  opt.textContent = placeholder;
  sel.appendChild(opt);
  for (const v of items) {
    const o = document.createElement("option");
    if (typeof v === "string") {
      o.value = v;
      o.textContent = v;
    } else if (v && typeof v === "object") {
      o.value = v.code ?? v.value ?? "";
      o.textContent = v.label ?? v.code ?? "";
      if (v.name) o.title = v.name;
      else if (v.label) o.title = v.label;
    }
    sel.appendChild(o);
  }
}

function bindEvents() {
  els.station.addEventListener("change", onStationChange);
  els.date.addEventListener("change", onDateChange);
  els.product.addEventListener("change", onProductChange);
  els.btnPlay.addEventListener("click", togglePlay);
  els.timeline.addEventListener("mousemove", onTimelineHover);
  els.timeline.addEventListener("mouseleave", onTimelineLeave);
  els.timeline.addEventListener("click", onTimelineClick);
  document.addEventListener("keydown", onKeyDown);
}

// ---------- Selector cascades ----------
let datesPollTimer = null;

async function onStationChange() {
  state.station = els.station.value;
  stopProductAutoRefresh();
  els.product.innerHTML = "<option value=''>—</option>";
  els.product.disabled = true;
  els.date.value = "";
  els.date.disabled = true;
  if (datesPollTimer) { clearTimeout(datesPollTimer); datesPollTimer = null; }
  setStatus("");

  if (!state.station) return;
  loadDates(state.station);
}

async function loadDates(station) {
  if (station !== els.station.value) return; // station changed mid-flight
  try {
    const r = await getJson(`/api/dates?station=${encodeURIComponent(station)}`);
    if (station !== els.station.value) return;
    if (r.dates.length === 0) {
      if (r.refreshing) {
        setStatus("正在扫描数据目录…", "");
        datesPollTimer = setTimeout(() => loadDates(station), 3000);
        return;
      }
      setStatus("该站点下没有可用日期", "err");
      return;
    }
    const minD = ymdToInputValue(r.dates[0]);
    const maxD = ymdToInputValue(r.dates[r.dates.length - 1]);
    els.date.min = minD;
    els.date.max = maxD;
    els.date.disabled = false;
    if (!els.date.value) els.date.value = maxD;
    state.availableDates = new Set(r.dates);
    if (r.refreshing) {
      setStatus("索引刷新中（后台进行，不影响使用）", "");
    } else {
      setStatus("");
    }
    onDateChange();
  } catch (e) {
    setStatus("加载日期失败: " + e.message, "err");
  }
}

async function onDateChange() {
  state.date = inputValueToYmd(els.date.value);
  stopProductAutoRefresh();
  els.product.innerHTML = "<option value=''>—</option>";
  els.product.disabled = true;

  if (!state.station || !state.date) return;
  if (state.availableDates && !state.availableDates.has(state.date)) {
    setStatus(`该日期 ${state.date} 暂无数据`, "err");
    return;
  }
  setStatus("");
  try {
    const { products } = await getJson(
      `/api/products?station=${encodeURIComponent(state.station)}&date=${encodeURIComponent(state.date)}`);
    fillSelect(els.product, products, "请选择产品");
    els.product.disabled = products.length === 0;
  } catch (e) {
    setStatus("加载产品失败: " + e.message, "err");
  }
}

async function onProductChange() {
  state.product = els.product.value;
  stopProductAutoRefresh();
  stopPlay();
  if (!state.product) {
    showOverlay(els.empty);
    return;
  }
  setStatus("正在读取文件列表…");
  showOverlay(els.loading, "读取文件列表…");
  try {
    const data = await getJson(
      `/api/files?station=${encodeURIComponent(state.station)}` +
      `&date=${encodeURIComponent(state.date)}` +
      `&product=${encodeURIComponent(state.product)}`);
    buildFromFiles(data);
    if (state.times.length === 0) {
      setStatus("该产品下没有解析到任何文件", "err");
      showOverlay(els.empty, "无可用文件");
      return;
    }
    state.tIdx = 0;
    state.eIdx = 0;
    buildTimeline();
    buildElevationBar();
    setStatus("");
    await goTo(state.tIdx, state.eIdx);
    startProductAutoRefresh();
  } catch (e) {
    setStatus("加载文件列表失败: " + e.message, "err");
    showOverlay(els.error, e.message);
  }
}

function buildFromFiles(data) {
  state.times = data.times;
  state.timeLabels = data.time_labels;
  state.elevations = data.elevations || [];
  state.elevationRaws = data.elevation_raws || [];
  state.hasElev = state.elevationRaws.length > 0;
  state.cached = new Set();

  state.matrix = {};
  for (const t of state.times) state.matrix[t] = {};

  for (const fr of data.frames) {
    const k = state.hasElev ? String(fr.elevation_raw) : "_";
    state.matrix[fr.time][k] = fr;
    if (fr.cached) state.cached.add(fr.path);
  }
  state.filesSignature = buildFilesSignature(data);
}

function buildFilesSignature(data) {
  const tLast = data.times && data.times.length ? data.times[data.times.length - 1] : "";
  const fLast = data.frames && data.frames.length ? data.frames[data.frames.length - 1].path : "";
  return `${data.frames?.length || 0}|${data.times?.length || 0}|${tLast}|${fLast}`;
}

function stopProductAutoRefresh() {
  if (state.autoRefreshTimer) {
    clearInterval(state.autoRefreshTimer);
    state.autoRefreshTimer = null;
  }
}

function startProductAutoRefresh() {
  stopProductAutoRefresh();
  if (!state.station || !state.date || !state.product) return;
  state.autoRefreshTimer = setInterval(refreshSelectedProductFiles, PRODUCT_REFRESH_INTERVAL_MS);
}

function pickElevationForTime(tIdx, preferredEIdx) {
  if (!state.hasElev) return 0;
  if (frameAt(tIdx, preferredEIdx)) return preferredEIdx;
  for (let i = 0; i < state.elevationRaws.length; i++) {
    if (frameAt(tIdx, i)) return i;
  }
  return 0;
}

async function refreshSelectedProductFiles() {
  if (!state.station || !state.date || !state.product) return;
  try {
    const data = await getJson(
      `/api/files?station=${encodeURIComponent(state.station)}` +
      `&date=${encodeURIComponent(state.date)}` +
      `&product=${encodeURIComponent(state.product)}`);
    const nextSignature = buildFilesSignature(data);
    if (nextSignature === state.filesSignature) return;

    const prevEIdx = state.eIdx;
    buildFromFiles(data);
    if (state.times.length === 0) return;

    buildTimeline();
    buildElevationBar();
    const latestTIdx = state.times.length - 1;
    const nextEIdx = pickElevationForTime(latestTIdx, prevEIdx);
    setStatus("检测到新文件，已自动切换到最新时次", "ok");
    await goTo(latestTIdx, nextEIdx);
  } catch (_) {
    // ignore polling errors
  }
}

// ---------- Indexing ----------
function currentFrame() {
  const t = state.times[state.tIdx];
  if (!t) return null;
  const cell = state.matrix[t];
  if (!cell) return null;
  if (state.hasElev) {
    const raw = state.elevationRaws[state.eIdx];
    return cell[String(raw)] || null;
  }
  return cell["_"] || null;
}

function frameAt(tIdx, eIdx) {
  if (tIdx < 0 || tIdx >= state.times.length) return null;
  if (state.hasElev && (eIdx < 0 || eIdx >= state.elevationRaws.length)) return null;
  const t = state.times[tIdx];
  const cell = state.matrix[t];
  if (!cell) return null;
  if (state.hasElev) {
    return cell[String(state.elevationRaws[eIdx])] || null;
  }
  return cell["_"] || null;
}

// ---------- Navigation ----------
async function goTo(tIdx, eIdx) {
  state.tIdx = Math.max(0, Math.min(state.times.length - 1, tIdx));
  if (state.hasElev) {
    state.eIdx = Math.max(0, Math.min(state.elevationRaws.length - 1, eIdx));
  } else {
    state.eIdx = 0;
  }

  updateActiveMarkers();
  updateInfoBar();

  const fr = currentFrame();
  if (!fr) {
    showOverlay(els.error, "当前时次/仰角缺失该文件");
    els.frame.removeAttribute("src");
    return;
  }
  scheduleNeighbors();
  await renderCurrent(fr);
}

async function renderCurrent(fr) {
  const token = ++state.renderToken;
  if (state.loadingTimer) {
    clearTimeout(state.loadingTimer);
    state.loadingTimer = null;
  }

  const showLoading = () => {
    els.frame.classList.add("loading");
    showOverlay(els.loading, "渲染中…");
  };
  const cachedHint = state.cached.has(fr.path);
  if (cachedHint) {
    state.loadingTimer = setTimeout(() => {
      if (token === state.renderToken) showLoading();
    }, RENDER_LOADING_DELAY_MS);
  } else {
    showLoading();
  }

  try {
    const data = await getJson(`/api/render?path=${encodeURIComponent(fr.path)}`);
    if (token !== state.renderToken) return; // a newer goTo has taken over
    if (state.loadingTimer) {
      clearTimeout(state.loadingTimer);
      state.loadingTimer = null;
    }
    if (!data.ok) throw new Error(data.error || "render failed");
    els.frame.src = data.url + "?t=" + Date.now(); // bust browser cache once
    els.frame.onload = () => {
      els.frame.classList.remove("loading");
      showOverlay(null);
    };
    els.frame.onerror = () => {
      els.frame.classList.remove("loading");
      showOverlay(els.error, "图片加载失败");
    };
    state.cached.add(fr.path);
    markCachedInUI(fr.path);
  } catch (e) {
    if (token !== state.renderToken) return;
    if (state.loadingTimer) {
      clearTimeout(state.loadingTimer);
      state.loadingTimer = null;
    }
    els.frame.classList.remove("loading");
    showOverlay(els.error, "渲染失败: " + e.message);
  }
}

// ---------- Prerender scheduling ----------
function scheduleNeighbors() {
  // Build a list of nearby frames, prioritized by closeness.
  // Time has higher weight (users scrub time more often).
  const T = state.times.length;
  const E = state.hasElev ? state.elevationRaws.length : 1;
  const items = [];

  const RT = 5, RE = state.hasElev ? 2 : 0;
  for (let dt = -RT; dt <= RT; dt++) {
    for (let de = -RE; de <= RE; de++) {
      if (dt === 0 && de === 0) continue;
      const t = state.tIdx + dt;
      const e = state.hasElev ? state.eIdx + de : 0;
      if (t < 0 || t >= T) continue;
      if (state.hasElev && (e < 0 || e >= E)) continue;
      const fr = frameAt(t, e);
      if (!fr) continue;
      if (state.cached.has(fr.path)) continue;
      // Priority: smaller = sooner. Time distance counts more.
      const priority = Math.abs(dt) * 10 + Math.abs(de) * 30;
      items.push({ path: fr.path, priority });
    }
  }
  items.sort((a, b) => a.priority - b.priority);

  const token = ++state.prerenderToken;
  // Fire and forget; ignore response if a newer one supersedes it.
  postJson("/api/prerender", { items }).catch(() => {});
  // Periodically poll cache status to colorize ticks/buttons.
  setTimeout(() => pollCacheStatus(token, items.map(i => i.path)), 1500);
}

async function pollCacheStatus(token, paths) {
  if (token !== state.prerenderToken) return;
  if (!paths.length) return;
  const qs = paths.map(p => "path=" + encodeURIComponent(p)).join("&");
  try {
    const { cached } = await getJson("/api/cache-status?" + qs);
    let anyNew = false;
    for (const p of paths) {
      if (cached[p] && !state.cached.has(p)) {
        state.cached.add(p);
        markCachedInUI(p);
        anyNew = true;
      }
    }
    const remaining = paths.filter(p => !state.cached.has(p));
    if (remaining.length > 0 && token === state.prerenderToken) {
      setTimeout(() => pollCacheStatus(token, remaining), anyNew ? 1500 : 3000);
    }
  } catch (_) {
    // ignore
  }
}

// ---------- UI building ----------
function buildTimeline() {
  els.timeline.innerHTML = "";
  const n = state.times.length;
  if (n === 0) return;

  // Major labels: aim for ~8 labels regardless of n.
  const labelStep = Math.max(1, Math.floor(n / 8));

  for (let i = 0; i < n; i++) {
    const tick = document.createElement("div");
    tick.className = "tick";
    tick.style.left = ((i + 0.5) / n * 100) + "%";
    tick.dataset.idx = String(i);
    tick.title = state.timeLabels[i];
    const fr = frameAt(i, state.eIdx);
    if (fr && state.cached.has(fr.path)) tick.classList.add("cached");
    els.timeline.appendChild(tick);

    if (i % labelStep === 0 || i === n - 1) {
      const lbl = document.createElement("div");
      lbl.className = "tick-label";
      lbl.style.left = ((i + 0.5) / n * 100) + "%";
      lbl.textContent = state.timeLabels[i].slice(0, 5); // HH:MM
      els.timeline.appendChild(lbl);
    }
  }
}

function timelineIdxFromEvent(e) {
  const n = state.times.length;
  if (n <= 0) return -1;
  const rect = els.timeline.getBoundingClientRect();
  if (rect.width <= 1) return -1;
  const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
  const ratio = x / rect.width;
  const idx = Math.round(ratio * (n - 1));
  return Math.max(0, Math.min(n - 1, idx));
}

function ensureTimelineTip() {
  let tip = els.timeline.querySelector(".timeline-tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "timeline-tip";
    els.timeline.appendChild(tip);
  }
  return tip;
}

function onTimelineHover(e) {
  const idx = timelineIdxFromEvent(e);
  if (idx < 0) return;
  state.timelineHoverIdx = idx;
  const tip = ensureTimelineTip();
  tip.textContent = state.timeLabels[idx] || state.times[idx] || "--:--:--";
  tip.style.left = `${((idx + 0.5) / state.times.length) * 100}%`;
  tip.classList.add("show");
}

function onTimelineLeave() {
  state.timelineHoverIdx = -1;
  const tip = els.timeline.querySelector(".timeline-tip");
  if (tip) tip.classList.remove("show");
}

function onTimelineClick(e) {
  const idx = timelineIdxFromEvent(e);
  if (idx < 0) return;
  goTo(idx, state.eIdx);
}

function buildElevationBar() {
  els.elevBar.innerHTML = "";
  if (!state.hasElev) {
    els.elevBar.classList.add("empty");
    return;
  }
  els.elevBar.classList.remove("empty");
  // Render top->down from highest elevation to lowest so ↑ key naturally raises elevation.
  const order = state.elevations.map((_, i) => i).reverse();
  for (const idx of order) {
    const btn = document.createElement("button");
    btn.className = "elev-btn";
    btn.dataset.idx = String(idx);
    btn.innerHTML = `${state.elevations[idx].toFixed(1)}°<span class="dot"></span>`;
    btn.addEventListener("click", () => goTo(state.tIdx, idx));
    els.elevBar.appendChild(btn);
    const fr = frameAt(state.tIdx, idx);
    if (fr && state.cached.has(fr.path)) btn.classList.add("cached");
  }
}

function updateActiveMarkers() {
  for (const tick of els.timeline.querySelectorAll(".tick")) {
    tick.classList.toggle("active", Number(tick.dataset.idx) === state.tIdx);
    const idx = Number(tick.dataset.idx);
    const fr = frameAt(idx, state.eIdx);
    tick.classList.toggle("cached", !!(fr && state.cached.has(fr.path)));
  }
  if (state.hasElev) {
    for (const btn of els.elevBar.querySelectorAll(".elev-btn")) {
      const idx = Number(btn.dataset.idx);
      btn.classList.toggle("active", idx === state.eIdx);
      const fr = frameAt(state.tIdx, idx);
      btn.classList.toggle("cached", !!(fr && state.cached.has(fr.path)));
    }
  }
}

function updateInfoBar() {
  els.infoTime.textContent = state.timeLabels[state.tIdx] || "--:--:--";
  els.infoElev.textContent = state.hasElev
    ? `仰角 ${state.elevations[state.eIdx].toFixed(1)}°`
    : "";
  els.infoCount.textContent = state.times.length
    ? `${state.tIdx + 1}/${state.times.length}`
    : "";
}

function markCachedInUI(path) {
  // refresh anything that might display this path
  for (const tick of els.timeline.querySelectorAll(".tick")) {
    const idx = Number(tick.dataset.idx);
    const fr = frameAt(idx, state.eIdx);
    if (fr && fr.path === path) tick.classList.add("cached");
  }
  if (state.hasElev) {
    for (const btn of els.elevBar.querySelectorAll(".elev-btn")) {
      const idx = Number(btn.dataset.idx);
      const fr = frameAt(state.tIdx, idx);
      if (fr && fr.path === path) btn.classList.add("cached");
    }
  }
}

// ---------- Playback ----------
function togglePlay() {
  if (state.isPlaying) stopPlay(); else startPlay();
}
function startPlay() {
  if (state.times.length < 2) return;
  state.isPlaying = true;
  els.btnPlay.textContent = "⏸";
  els.btnPlay.classList.add("playing");
  scheduleNextPlayStep();
}
function stopPlay() {
  state.isPlaying = false;
  els.btnPlay.textContent = "▶";
  els.btnPlay.classList.remove("playing");
  if (state.playTimer) {
    clearTimeout(state.playTimer);
    state.playTimer = null;
  }
}
function scheduleNextPlayStep() {
  if (!state.isPlaying) return;
  state.playTimer = setTimeout(async () => {
    if (!state.isPlaying) return;
    let next = state.tIdx + 1;
    if (next >= state.times.length) next = 0; // loop
    await goTo(next, state.eIdx);
    scheduleNextPlayStep();
  }, 350);
}

// ---------- Keyboard ----------
function onKeyDown(e) {
  if (state.times.length === 0) return;
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;

  switch (e.key) {
    case "ArrowLeft":  e.preventDefault(); goTo(state.tIdx - 1, state.eIdx); break;
    case "ArrowRight": e.preventDefault(); goTo(state.tIdx + 1, state.eIdx); break;
    case "ArrowUp":
      if (state.hasElev) { e.preventDefault(); goTo(state.tIdx, state.eIdx + 1); }
      break;
    case "ArrowDown":
      if (state.hasElev) { e.preventDefault(); goTo(state.tIdx, state.eIdx - 1); }
      break;
    case "Home": e.preventDefault(); goTo(0, state.eIdx); break;
    case "End":  e.preventDefault(); goTo(state.times.length - 1, state.eIdx); break;
    case " ":    e.preventDefault(); togglePlay(); break;
  }
}

// ---------- go ----------
init();
