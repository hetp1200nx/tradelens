/* TradeLens front end: boards, live chart, signals, P&L calculator, trade journal, alerts. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const IST = 19800;
const S = {
  tab: "boards", view: "nifty50", sym: null, tf: "5m", style: "intraday",
  sortK: "strength", sortD: -1, board: null, detail: null, trades: [], lastAlert: 0,
  notify: false, es: null,
};
try { S.notify = localStorage.getItem("tl_notify") === "1" && Notification.permission === "granted"; } catch (e) {}

// ---------------------------------------------------------------- utils
const nf = (n, d = 2) => (n === null || n === undefined || isNaN(n)) ? "–" :
  Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = (n, d = 2) => (n > 0 ? "+" : "") + nf(n, d);
const cls = (n) => n > 0 ? "up" : n < 0 ? "down" : "";
const vol = (v) => !v ? "–" : v >= 1e7 ? nf(v / 1e7, 2) + " Cr" : v >= 1e5 ? nf(v / 1e5, 2) + " L" : v >= 1e3 ? nf(v / 1e3, 1) + " K" : nf(v, 0);
const money = (n) => (n < 0 ? "−₹" : "₹") + nf(Math.abs(n), 0);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const tstr = (t) => new Date(t * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });
const dstr = (t) => new Date(t * 1000).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...opts });
  if (r.status === 401 && !path.startsWith("/api/auth/")) { const j = await r.json().catch(() => ({})); showAuth(j.state || "login"); throw new Error("Please sign in"); }
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

// ---------------------------------------------------------------- live stream
// Live updates: Server-Sent Events when the network allows them, otherwise automatic polling
// (Cloudflare quick tunnels and some proxies block SSE). The choice is remembered per browser.
const HANDLERS = {
  board: (d) => { S.board = d; renderIndices(); if (S.tab === "boards" && !S.sym) renderBoard(); },
  detail: (d) => { S.detail = d; renderDetail(true); },
  trades: (d) => { S.openLive = d; if (S.tab === "journal") renderOpen(); },
  alerts: (d) => d.forEach(alertIn),
  status: (d) => renderStatus(d),
  account: (d) => { S.acct = d; if (S.tab === "account") renderAccount(); },
  radar: (d) => radarIn(d),
  signout: () => { stopStream(); showAuth("login"); },
};
function streamParams() {
  return { view: S.view, sym: S.sym || "", tf: S.tf, since: S.lastAlert || 0, rsince: S.lastRadar || 0,
    acct: S.tab === "account" && !S.sym ? "1" : "0" };
}
function stopStream() {
  if (S.es) { S.es.close(); S.es = null; }
  S.pollGen = (S.pollGen || 0) + 1;
  clearTimeout(S.sseCheck);
}
try { S.usePoll = sessionStorage.getItem("tl_poll") === "1"; } catch (e) {}
function openStream() {
  stopStream();
  if (S.usePoll || !window.EventSource) return startPolling();
  const es = new EventSource("/api/stream?" + new URLSearchParams(streamParams()));
  S.es = es;
  let got = false;
  Object.keys(HANDLERS).forEach(k => es.addEventListener(k, (e) => { got = true; HANDLERS[k](e.data ? JSON.parse(e.data) : {}); }));
  es.onerror = async () => {
    try { const m = await (await fetch("/api/auth/me")).json(); if (m.state !== "ok") { stopStream(); showAuth(m.state, m); return; } } catch (x) {}
  };
  // if nothing arrives in 6 seconds, the live stream is being blocked: switch to polling
  S.sseCheck = setTimeout(() => {
    if (!got && S.es === es) { S.usePoll = true; try { sessionStorage.setItem("tl_poll", "1"); } catch (e) {} startPolling(); }
  }, 6000);
}
async function startPolling() {
  stopStream();
  const gen = S.pollGen, p = streamParams();
  let n = 0;
  while (gen === S.pollGen) {
    const t0 = Date.now();
    try {
      const r = await fetch("/api/poll?" + new URLSearchParams({ ...p, n }), { credentials: "same-origin", cache: "no-store" });
      if (r.status === 401) { const m = await r.json(); stopStream(); showAuth(m.state || "login", m); return; }
      const j = await r.json();
      if (gen !== S.pollGen) return;
      p.since = j.since ?? p.since; p.rsince = j.rsince ?? p.rsince;
      (j.events || []).forEach(([k, d]) => { if (HANDLERS[k]) HANDLERS[k](d); });
    } catch (e) { await new Promise(r => setTimeout(r, 3000)); }
    n++;
    await new Promise(r => setTimeout(r, Math.max(150, 1000 - (Date.now() - t0))));
  }
}

function renderStatus(s) {
  const el = $("#status");
  el.className = "pill " + (s.mode === "demo" ? "demo" : s.status === "live" ? "live" : "");
  el.lastElementChild.textContent = (s.mode === "demo" ? "DEMO · " : "") + s.status.replace(" (demo)", "") + " · " + tstr(s.ts);
  if (s.balance !== undefined && s.balance !== null) $("#walletAmt").textContent = nf(s.balance, 0);
}
$("#walletPill").addEventListener("click", () => setTab("account"));

function renderIndices() {
  const ix = S.board?.indices || {};
  $("#idx").innerHTML = Object.values(ix).map(m =>
    `<span class="it" data-sym="${m.sym}"><b>${esc(m.name)}</b><span class="num">${nf(m.ltp)}</span> <span class="num ${cls(m.chg)}">${sgn(m.chg)}%</span></span>`).join("");
}
$("#idx").addEventListener("click", (e) => { const it = e.target.closest(".it"); if (it) openDetail(it.dataset.sym); });

// ---------------------------------------------------------------- tabs
$$("nav.tabs button[data-tab]").forEach(b => b.addEventListener("click", () => setTab(b.dataset.tab)));
function setTab(t) {
  const prev = S.tab;
  S.tab = t;
  if (S.sym) closeDetail();
  $$("nav.tabs button[data-tab]").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  ["boards", "flow", "wide", "planner", "account", "journal", "radar", "score", "profile", "admin"].forEach(x => $("#tab-" + x).classList.toggle("hidden", x !== t));
  if (t === "journal") loadTrades();
  if (t === "score") loadScore();
  if (t === "planner") loadPlanner();
  if (t === "account") { loadAccount(); }
  if (t === "radar") { loadRadar(); loadPA(); S.radarNew = 0; $("#radarCnt").classList.add("hidden"); }
  if (t === "profile") loadProfile();
  if (t === "admin") loadAdmin();
  if (t === "flow") { $("#flowSeg button.on") ; loadFlow(); }
  $("main").classList.toggle("wide", t === "wide");
  if (t === "wide") loadWide();
  if (t === "boards" && S.layout === "grid") setTimeout(fetchCards, 100);
  if (t === "boards" && S.board) renderBoard();
  if ((prev === "account") !== (t === "account")) openStream();
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------- boards
$$("#viewSeg button").forEach(b => b.addEventListener("click", () => {
  S.view = b.dataset.v;
  $$("#viewSeg button").forEach(x => x.classList.toggle("on", x === b));
  openStream();
}));
$$("#allTable th").forEach(th => th.addEventListener("click", () => {
  const k = th.dataset.k;
  if (S.sortK === k) S.sortD *= -1; else { S.sortK = k; S.sortD = k === "sym" ? 1 : -1; }
  renderBoard();
}));
$("#filter").addEventListener("input", () => renderBoard());

function strengthBar(r) {
  const c = r.direction > 0 ? "var(--up)" : "var(--down)";
  return `<div class="sbar"><i style="width:${r.strength}%;background:${c}"></i></div><div class="sv">${nf(r.strength, 0)}</div>`;
}
function rankList(rows) {
  if (!rows.length) return `<li class="muted" style="cursor:default">No stock qualifies right now</li>`;
  return rows.map((r, i) => `<li data-sym="${r.sym}"><span class="n">${i + 1}</span>
    <span class="s">${esc(r.sym)}<small>Vol ${nf(r.vol_ratio, 1)}× · ${esc(r.oi_signal || (r.pressure > 0 ? "buyers " : "sellers ") + nf(Math.abs(r.pressure) * 100, 0) + "%")}</small></span>
    <span class="p num">${nf(r.ltp)}<small class="${cls(r.chg)}">${sgn(r.chg)}%</small></span>
    <span>${strengthBar(r)}</span></li>`).join("");
}
function renderBoard() {
  const b = S.board; if (!b) return;
  $("#bulls").innerHTML = rankList(b.bulls);
  $("#bears").innerHTML = rankList(b.bears);
  $("#bullCount").textContent = b.bulls.length ? "top " + b.bulls.length : "";
  $("#bearCount").textContent = b.bears.length ? "top " + b.bears.length : "";
  const br = b.breadth; const tot = br.total || 1;
  $("#breadthTxt").innerHTML = `<span class="up">${br.adv} up</span> · <span class="down">${br.dec} down</span>`;
  $("#breadthBar .a").style.width = (br.adv / tot * 100) + "%";
  $("#breadthBar .d").style.width = (br.dec / tot * 100) + "%";
  if (br.mood !== undefined) {
    $("#mood i").style.left = `calc(${br.mood}% - 1px)`;
    $("#mood span").innerHTML = `Mood <b class="${br.mood >= 57 ? "up" : br.mood <= 43 ? "down" : ""}">${br.mood_label}</b>`;
  }
  const wl = b.view === "watchlist";
  $$(".wlonly").forEach(x => x.classList.toggle("hidden", !wl));
  $("#listTitle").textContent = wl ? "Volatile Watchlist" : b.view === "sensex" ? "Sensex stocks" : "Nifty 50 stocks";
  $("#listCount").textContent = `· ${b.rows.length} shares`;
  const grid = S.layout === "grid";
  $("#gridMode").classList.toggle("hidden", !grid);
  $("#listMode").classList.toggle("hidden", grid);
  if (grid) { renderGrid(); return; }
  const f = $("#filter").value.trim().toUpperCase();
  let rows = b.rows.filter(r => !f || r.sym.includes(f));
  const k = S.sortK, d = S.sortD;
  rows.sort((a, z) => {
    let x = a[k], y = z[k];
    if (k === "strength") { x = a.strength * a.direction; y = z.strength * z.direction; }
    return (typeof x === "string" ? String(x).localeCompare(y) : (x - y)) * d;
  });
  $("#allTable tbody").innerHTML = rows.map(r => `<tr class="click" data-sym="${r.sym}">
    <td><b>${esc(r.sym)}</b></td><td class="num">${nf(r.ltp)}</td><td class="num ${cls(r.chg)}">${sgn(r.chg)}%</td>
    <td class="num ${r.vol_ratio >= 1.5 ? "warnc" : ""}">${nf(r.vol_ratio, 1)}×</td>
    <td><span class="press" title="buy ${nf(r.buy_qty, 0)} / sell ${nf(r.sell_qty, 0)}"><i style="width:${(r.pressure + 1) * 50}%"></i></span></td>
    <td class="num hide-m ${cls(r.oi_chg)}">${r.is_fno && r.oi_chg != null ? sgn(r.oi_chg) + "%" : "–"}</td>
    <td class="hide-m">${r.oi_signal ? `<span class="tag ${/Long b|Short c/.test(r.oi_signal) ? "up" : "down"}">${r.oi_signal}</span>` : ""}</td>
    <td class="num">${r.choppy ? '<span class="muted">0</span>' : `<span class="${cls(r.direction)}">${nf(r.strength, 0)}</span>`}</td>
    <td><span class="tag ${r.choppy ? "" : r.direction > 0 ? "up" : "down"}">${r.bias}</span>${wl ? ` <button class="btn sm rm" data-rm="${esc(r.sym)}" title="Remove from watchlist">✕</button>` : ""}</td></tr>`).join("")
    || `<tr><td colspan="9" class="empty">${f ? "No share in this list matches “" + esc(f) + "”." + (wl ? " Use + Add share to add it." : "") : "Loading…"}</td></tr>`;
}
document.addEventListener("click", (e) => {
  const rm = e.target.closest("[data-rm]");
  if (rm) { e.stopPropagation(); watchToggle(rm.dataset.rm, false); return; }
  const el = e.target.closest("[data-sym]");
  if (el && (el.closest("#bulls") || el.closest("#bears") || el.closest("#allTable") || el.closest("#scoreTable") || el.closest(".tc .h")
      || el.closest("#radarList") || el.closest("#paList") || el.closest(".idea .h") || el.closest("#acPos") || el.closest("#acHold")))
    openDetail(el.dataset.sym);
});

// ---------------------------------------------------------------- detail + chart
let chart, cSeries, vSeries, e20S, e50S, vwS, pLines = [], lastBarT = 0;
let FB = null; // backup chart used when the TradingView library can't load (offline)
// ---------------------------------------------------------------- theme colours (dark / light)
function TC() {
  const cs = getComputedStyle(document.documentElement), v = (n) => cs.getPropertyValue(n).trim();
  const light = document.documentElement.dataset.theme === "light";
  return { bg: v("--panel"), bg2: v("--panel2"), grid: light ? "#edf1f5" : "#161d26", line: v("--line"), text: v("--muted"),
    dim: v("--dim"), fg: v("--text"), up: v("--up"), down: v("--down"), warn: v("--warn"), accent: v("--accent"),
    liq: light ? "#7b8794" : "#8a96a6", mine: light ? "#16202b" : "#ffffff", onPrice: light ? "#ffffff" : "#031320",
    upA: (a) => light ? `rgba(12,154,105,${a})` : `rgba(31,201,138,${a})`, downA: (a) => light ? `rgba(221,59,69,${a})` : `rgba(255,92,99,${a})`,
    light };
}
function chartTheme() {
  const c = TC();
  return { layout: { background: { color: c.bg }, textColor: c.text, fontFamily: "JetBrains Mono, monospace", fontSize: 11 },
    grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
    rightPriceScale: { borderColor: c.line }, timeScale: { borderColor: c.line, timeVisible: true, secondsVisible: false } };
}
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("tl_theme", t); } catch (e) {}
  $("#themeBtn").textContent = t === "light" ? "☀" : "☾";
  $("#themeBtn").title = t === "light" ? "Switch to dark mode" : "Switch to light mode";
  const c = TC();
  if (chart) { chart.applyOptions(chartTheme()); cSeries.applyOptions({ upColor: c.up, downColor: c.down, wickUpColor: c.up, wickDownColor: c.down }); drawLines(); }
  if (FB) drawFB();
  if (typeof redrawCards === "function") redrawCards();
  if (typeof drawFlow === "function" && S.flow) drawFlow();
}
$("#themeBtn").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light"));
$("#themeBtn").textContent = document.documentElement.dataset.theme === "light" ? "☀" : "☾";

function makeChart() {
  if (chart) return;
  const el = $("#chart");
  if (!window.LightweightCharts) { FB = FB || { canvas: null }; return; }
  chart = LightweightCharts.createChart(el, {
    ...chartTheme(),
    crosshair: { mode: 0 }, autoSize: true,
  });
  cSeries = chart.addCandlestickSeries({ upColor: "#1fc98a", downColor: "#ff5c63", borderVisible: false, wickUpColor: "#1fc98a", wickDownColor: "#ff5c63" });
  vSeries = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol" });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  e20S = chart.addLineSeries({ color: "#f2b33d", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  e50S = chart.addLineSeries({ color: "#b18cff", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  vwS = chart.addLineSeries({ color: "#4fb3ff", lineWidth: 2, lineStyle: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
}
const ct = (t) => t + IST;
const vbar = (c) => ({ time: ct(c.t), value: c.v, color: c.c >= c.o ? "rgba(31,201,138,.35)" : "rgba(255,92,99,.35)" });

async function loadChart() {
  makeChart();
  const d = await api(`/api/candles/${encodeURIComponent(S.sym)}?tf=${S.tf}`);
  if (d.sym !== S.sym) return;
  if (FB) { S.overlay = d; FB.cs = d.candles.slice(); lastBarT = d.candles.length ? d.candles[d.candles.length - 1].t : 0; drawFB(); return; }
  cSeries.setData(d.candles.map(c => ({ time: ct(c.t), open: c.o, high: c.h, low: c.l, close: c.c })));
  vSeries.setData(d.candles.map(vbar));
  e20S.setData(d.ema20.map(x => ({ time: ct(x.t), value: x.v })));
  e50S.setData(d.ema50.map(x => ({ time: ct(x.t), value: x.v })));
  vwS.setData(d.vwap.map(x => ({ time: ct(x.t), value: x.v })));
  lastBarT = d.candles.length ? d.candles[d.candles.length - 1].t : 0;
  S.overlay = d;
  drawLines();
  chart.timeScale().fitContent();
  if (d.candles.length > 150) chart.timeScale().setVisibleLogicalRange({ from: d.candles.length - 150, to: d.candles.length + 5 });
}

function drawLines() {
  if (FB) return drawFB();
  pLines.forEach(l => cSeries.removePriceLine(l)); pLines = [];
  const add = (price, color, title, style = 2, w = 1) => pLines.push(cSeries.createPriceLine({ price, color, lineWidth: w, lineStyle: style, axisLabelVisible: true, title }));
  const d = S.overlay; if (!d) return;
  d.order_blocks.forEach(o => {
    const c = o.type === "bull" ? "rgba(31,201,138,.75)" : "rgba(255,92,99,.75)";
    add(o.top, c, (o.type === "bull" ? "Bull OB" : "Bear OB") + " top", 0, 1);
    add(o.bottom, c, "", 0, 1);
  });
  d.liquidity.buy_side.forEach(x => add(x.price, TC().liq, x.count > 1 ? "Liq ×" + x.count : "Liq", 1));
  d.liquidity.sell_side.forEach(x => add(x.price, TC().liq, x.count > 1 ? "Liq ×" + x.count : "Liq", 1));
  (S.trades || []).filter(t => t.status === "open" && t.symbol === S.sym && t.segment !== "option").forEach(t => {
    add(+t.entry, TC().mine, "Your entry", 0, 2);
    if (t.sl) add(+t.sl, "#ff5c63", "Your SL", 0, 2);
    if (t.t1) add(+t.t1, "#1fc98a", "Your T1", 0, 2);
    if (t.t2) add(+t.t2, "#1fc98a", "Your T2", 0, 2);
  });
}

function drawFB() {
  const d = S.overlay; if (!FB || !d || !FB.cs) return;
  const box = $("#chart");
  if (!FB.canvas || !box.contains(FB.canvas)) { box.innerHTML = ""; FB.canvas = document.createElement("canvas"); FB.canvas.style.width = "100%"; FB.canvas.style.height = "100%"; FB.canvas.style.display = "block"; box.appendChild(FB.canvas); }
  const cv = FB.canvas, dpr = window.devicePixelRatio || 1, W = box.clientWidth, H = box.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const P = TC();
  g.fillStyle = P.bg; g.fillRect(0, 0, W, H);
  const axis = 64, pw = W - axis, step = 7, n = Math.max(10, Math.min(FB.cs.length, Math.floor(pw / step) - 4));
  const cs = FB.cs.slice(-n), t0 = cs[0].t, bw = Math.max(2, step - 2);
  const priceH = H * 0.8, volTop = H * 0.82, volH = H * 0.16;
  let lo = Math.min(...cs.map(c => c.l)), hi = Math.max(...cs.map(c => c.h));
  const lines = [];
  d.order_blocks.forEach(o => lines.push(o.top, o.bottom));
  [...d.liquidity.buy_side, ...d.liquidity.sell_side].forEach(x => lines.push(x.price));
  const mytr = (S.trades || []).filter(t => t.status === "open" && t.symbol === S.sym && t.segment !== "option");
  mytr.forEach(t => [t.entry, t.sl, t.t1, t.t2].forEach(v => v && lines.push(+v)));
  lines.forEach(v => { if (v > lo - (hi - lo) * 0.6 && v < hi + (hi - lo) * 0.6) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
  const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
  const Y = v => 8 + (hi - v) / (hi - lo) * (priceH - 16);
  const X = i => i * step + step / 2;
  const xt = t => { const i = cs.findIndex(c => c.t >= t); return i < 0 ? null : X(i); };
  g.font = "11px JetBrains Mono, monospace"; g.textBaseline = "middle";
  for (let k = 0; k <= 5; k++) { const v = lo + (hi - lo) * k / 5, y = Y(v); g.strokeStyle = P.grid; g.beginPath(); g.moveTo(0, y); g.lineTo(pw, y); g.stroke(); g.fillStyle = P.text; g.fillText(nf(v), pw + 6, y); }
  d.order_blocks.forEach(o => {
    const x = Math.max(0, o.t < t0 ? 0 : (xt(o.t) ?? pw) - step / 2);
    g.fillStyle = o.type === "bull" ? "rgba(31,201,138,.16)" : "rgba(255,92,99,.16)";
    g.strokeStyle = o.type === "bull" ? "rgba(31,201,138,.7)" : "rgba(255,92,99,.7)";
    g.fillRect(x, Y(o.top), pw - x, Y(o.bottom) - Y(o.top)); g.strokeRect(x, Y(o.top), pw - x, Y(o.bottom) - Y(o.top));
    g.fillStyle = g.strokeStyle; g.fillText(o.type === "bull" ? "Bull OB" : "Bear OB", x + 4, Y(o.top) + 8);
  });
  const hline = (v, color, label, dash, w = 1) => { const y = Y(v); if (y < 0 || y > priceH) return; g.setLineDash(dash); g.strokeStyle = color; g.lineWidth = w; g.beginPath(); g.moveTo(0, y); g.lineTo(pw, y); g.stroke(); g.setLineDash([]); g.lineWidth = 1;
    if (label) { g.fillStyle = color; g.textAlign = "right"; g.fillText(label, pw - 4, y - 7); g.textAlign = "left"; } };
  [...d.liquidity.buy_side, ...d.liquidity.sell_side].forEach(x => hline(x.price, P.liq, x.count > 1 ? "Liq ×" + x.count : "Liq", [2, 3]));
  mytr.forEach(t => { hline(+t.entry, P.mine, "Your entry", [], 2); if (t.sl) hline(+t.sl, "#ff5c63", "Your SL", [], 2); if (t.t1) hline(+t.t1, "#1fc98a", "Your T1", [], 2); if (t.t2) hline(+t.t2, "#1fc98a", "Your T2", [], 2); });
  const maxV = Math.max(...cs.map(c => c.v)) || 1;
  cs.forEach((c, i) => {
    const up = c.c >= c.o, col = up ? "#1fc98a" : "#ff5c63", x = X(i);
    g.fillStyle = up ? "rgba(31,201,138,.35)" : "rgba(255,92,99,.35)"; const vh = c.v / maxV * volH; g.fillRect(x - bw / 2, volTop + volH - vh, bw, vh);
    g.strokeStyle = col; g.beginPath(); g.moveTo(x, Y(c.h)); g.lineTo(x, Y(c.l)); g.stroke();
    g.fillStyle = col; g.fillRect(x - bw / 2, Math.min(Y(c.o), Y(c.c)), bw, Math.max(1, Math.abs(Y(c.o) - Y(c.c))));
  });
  const poly = (arr, color, w, dash) => { const m = new Map(arr.map(p => [p.t, p.v])); g.strokeStyle = color; g.lineWidth = w; g.setLineDash(dash); g.beginPath(); let on = false;
    let pd = null; cs.forEach((c, i) => { const v = m.get(c.t); const dd = Math.floor((c.t + IST) / 86400); if (v === undefined) { on = false; return; } if (dash.length && pd !== null && dd !== pd) on = false; pd = dd; on ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)); on = true; }); g.stroke(); g.setLineDash([]); g.lineWidth = 1; };
  poly(d.ema20, "#f2b33d", 1, []); poly(d.ema50, "#b18cff", 1, []); poly(d.vwap, "#4fb3ff", 2, [5, 4]);
  const last = cs[cs.length - 1], ly = Y(last.c);
  g.fillStyle = last.c >= last.o ? "#1fc98a" : "#ff5c63"; g.fillRect(pw + 1, ly - 9, axis - 2, 18); g.fillStyle = P.onPrice; g.fillText(nf(last.c), pw + 6, ly);
  g.fillStyle = P.dim; const daily = !["1m", "5m", "15m", "1h"].includes(S.tf);
  for (let i = 0; i < cs.length; i += Math.ceil(cs.length / 6)) {
    const dt = new Date(cs[i].t * 1000);
    g.fillText(daily ? dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "Asia/Kolkata" }) : dt.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" }), X(i) - 16, H - 6);
  }
}
window.addEventListener("resize", () => FB && drawFB());

async function openDetail(sym) {
  S.sym = sym; S.detail = null; S.overlay = null; S.calcFilled = false;
  $("#detail").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  $("#dSym").textContent = sym; $("#dPx").textContent = ""; $("#dChg").textContent = "";
  $("#sigBox").innerHTML = '<div class="muted">Loading…</div>';
  $("#btBox").innerHTML = '<span class="muted">Replays the intraday order-block rule on the last ~60 days of 5-minute candles.</span>';
  try { history.pushState({ sym }, "", "#" + encodeURIComponent(sym)); } catch (e) {}
  refreshWatchBtn(sym);
  try { S.trades = await api("/api/trades"); } catch (e) {}
  try { S.detail = await api(`/api/stock/${encodeURIComponent(sym)}`); renderDetail(false); } catch (e) {}
  try { await loadChart(); } catch (e) { console.warn(e); }
  openStream();
}
function closeDetail() {
  S.sym = null; $("#detail").classList.add("hidden"); document.body.style.overflow = "";
  openStream(); if (S.board) renderBoard();
}
$("#backBtn").addEventListener("click", () => history.length > 1 ? history.back() : closeDetail());
window.addEventListener("popstate", () => { if (S.sym) closeDetail(); });

$$("#tfSeg button").forEach(b => b.addEventListener("click", () => {
  S.tf = b.dataset.tf; $$("#tfSeg button").forEach(x => x.classList.toggle("on", x === b));
  loadChart().catch(() => {}); openStream();
}));
$$("#styleSeg button").forEach(b => b.addEventListener("click", () => {
  S.style = b.dataset.s; $$("#styleSeg button").forEach(x => x.classList.toggle("on", x === b));
  renderSignal(); S.calcFilled = false; fillCalc();
}));

function renderDetail(live) {
  const d = S.detail; if (!d || d.quote.sym !== S.sym) return;
  const q = d.quote, m = d.metrics || {};
  $("#dPx").textContent = nf(q.ltp);
  const chg = q.prev_close ? (q.ltp - q.prev_close) / q.prev_close * 100 : 0;
  $("#dChg").innerHTML = `<span class="${cls(chg)}">${sgn(q.ltp - q.prev_close)} (${sgn(chg)}%)</span>`;
  $("#dBias").textContent = m.bias || ""; $("#dBias").className = "tag " + (m.choppy ? "" : m.direction > 0 ? "up" : "down");
  $("#dTime").textContent = "updated " + tstr(q.ts);
  const kv = [
    ["Open", nf(q.open)], ["Prev close", nf(q.prev_close)], ["High", nf(q.high)], ["Low", nf(q.low)],
    ["Volume", vol(q.volume)], ["Vol vs normal", m.vol_ratio ? nf(m.vol_ratio, 1) + "×" : "–"],
    ["Avg price (VWAP)", nf(q.avg_price)], ["Strength", m.choppy ? "0 (choppy)" : nf(m.strength, 0)],
    ["Open interest", q.is_fno && q.oi ? vol(q.oi) : "–"], ["OI change", q.is_fno && q.oi && q.oi_chg != null ? `<span class="${cls(q.oi_chg)}">${sgn(q.oi_chg)}%</span>` : "–"],
    ["OI view", m.oi_signal || "–"], ["Lot size", q.lot || "–"],
    ["Upper circuit", nf(q.uc)], ["Lower circuit", nf(q.lc)], ["52w high", nf(q.w52h)], ["52w low", nf(q.w52l)],
  ];
  $("#quoteKv").innerHTML = kv.map(([k, v]) => `<div><span>${k}</span><b class="num">${v}</b></div>`).join("");
  const tot = (q.buy_qty + q.sell_qty) || 1;
  $("#bsPress i").style.width = (q.buy_qty / tot * 100) + "%";
  $("#bsBuy").textContent = `Buyers ${vol(q.buy_qty)} (${nf(q.buy_qty / tot * 100, 0)}%)`;
  $("#bsSell").textContent = `Sellers ${vol(q.sell_qty)} (${nf(q.sell_qty / tot * 100, 0)}%)`;
  if (q.bids?.length || q.asks?.length) {
    let h = `<tr><th>Orders</th><th>Buy qty</th><th>Bid</th><th>Ask</th><th>Sell qty</th><th>Orders</th></tr>`;
    for (let i = 0; i < 5; i++) {
      const b = q.bids[i] || {}, a = q.asks[i] || {};
      h += `<tr><td class="muted">${b.orders ?? ""}</td><td class="b num">${nf(b.qty, 0)}</td><td class="b num">${nf(b.price)}</td><td class="s num">${nf(a.price)}</td><td class="s num">${nf(a.qty, 0)}</td><td class="muted">${a.orders ?? ""}</td></tr>`;
    }
    $("#depthT").innerHTML = h;
  } else $("#depthT").innerHTML = "";
  renderSignal();
  if (!S.calcFilled) fillCalc();
  if (live && FB && FB.cs && d.bars) {
    d.bars.forEach(c => { const cs = FB.cs; if (cs.length && cs[cs.length - 1].t === c.t) cs[cs.length - 1] = c; else if (!cs.length || c.t > cs[cs.length - 1].t) cs.push(c); });
    drawFB();
  }
  if (live && cSeries && d.bars) {
    d.bars.forEach(c => {
      if (c.t < lastBarT) return;
      cSeries.update({ time: ct(c.t), open: c.o, high: c.h, low: c.l, close: c.c });
      vSeries.update(vbar(c));
      lastBarT = c.t;
    });
    const sig = d.signals.intraday;
    if (["1m", "5m", "15m"].includes(S.tf) && (sig.action === "BUY" || sig.action === "SELL") && d.bars.length) {
      const t = ct(d.bars[d.bars.length - 1].t);
      cSeries.setMarkers([{ time: t, position: sig.action === "BUY" ? "belowBar" : "aboveBar", color: sig.action === "BUY" ? "#1fc98a" : "#ff5c63",
        shape: sig.action === "BUY" ? "arrowUp" : "arrowDown", text: sig.action }]);
    } else cSeries.setMarkers([]);
  }
}

function lvBox(label, val, sub) { return `<div><small>${label}</small><b>${val === null || val === undefined ? "–" : nf(val)}</b>${sub ? `<em>${sub}</em>` : ""}</div>`; }
function renderSignal() {
  const d = S.detail; if (!d) return;
  const s = d.signals[S.style]; if (!s) return;
  const actCls = s.action.replace(/\s/g, "");
  let h = `<div class="act"><span class="badge ${actCls}">${esc(s.action)}</span>
    <div class="conf"><div class="sbar"><i style="width:${s.confidence || 0}%;background:${s.confidence >= 60 ? "var(--up)" : s.confidence >= 40 ? "var(--warn)" : "var(--down)"}"></i></div>
    <small>Confidence ${s.confidence ?? "–"}% · ${s.timeframe || ""} rules</small></div></div>
    <p class="sum">${esc(s.summary || "")}</p>`;
  if (S.style === "option" && s.option) {
    const o = s.option;
    h += `<div class="lv">${lvBox("Contract", null).replace("–", esc(o.symbol))}${lvBox("Premium now", o.premium_now, o.estimated ? "estimate" : "live")}${lvBox("Lot", null).replace("–", o.lot)}${lvBox("Expiry", null).replace("–", esc(o.expiry || "nearest"))}</div>
      <div class="lv">${lvBox("Entry premium", o.entry)}${lvBox("Stop-loss", o.sl)}${lvBox("Target 1", o.t1)}${lvBox("Target 2", o.t2)}</div>
      <div class="lv">${lvBox("Risk / lot", o.per_lot.risk)}${lvBox("T1 gain / lot", o.per_lot.reward_t1)}${lvBox("T2 gain / lot", o.per_lot.reward_t2)}${lvBox("Stock entry", s.underlying.entry)}</div>`;
  } else if (s.entry !== undefined && s.entry !== null) {
    h += `<div class="lv">${lvBox("Entry zone", null).replace("<b>–</b>", `<b style="font-size:12px">${s.zone ? nf(s.zone[0]) + " – " + nf(s.zone[1]) : "–"}</b>`)}
      ${lvBox("Entry", s.entry)}${lvBox("Stop-loss", s.sl, s.risk_per_share ? "risk " + nf(s.risk_per_share) + "/sh" : "")}
      ${lvBox("Target 1", s.t1, s.rr1 ? "1 : " + nf(s.rr1, 1) : "")}</div>
      <div class="lv">${lvBox("Target 2", s.t2, s.rr2 ? "1 : " + nf(s.rr2, 1) : "")}
      ${s.levels?.vwap ? lvBox("VWAP", s.levels.vwap) : lvBox("50-DMA", s.levels?.ema50)}
      ${s.levels?.pdh ? lvBox("Prev day high", s.levels.pdh) : lvBox("200-DMA", s.levels?.ema200)}
      ${s.levels?.pdl ? lvBox("Prev day low", s.levels.pdl) : lvBox("RSI", s.levels?.rsi)}</div>`;
  }
  if (s.reasons?.length) h += `<ul class="why">${s.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>`;
  if (s.warnings?.length) h += `<ul class="why w">${s.warnings.map(w => `<li class="${w.level}">${esc(w.text)}</li>`).join("")}</ul>`;
  $("#sigBox").innerHTML = h;
}

// ---------------------------------------------------------------- P&L calculator
const calcF = () => Object.fromEntries($$("#calcF [name]").map(i => [i.name, i.value]));
function fillCalc(force) {
  const d = S.detail; if (!d) return;
  const s = d.signals[S.style]; const f = $("#calcF");
  const set = (n, v) => { const el = f.querySelector(`[name=${n}]`); if (v !== undefined && v !== null) el.value = v; };
  if (S.style === "option" && s.option) {
    set("segment", "option"); set("side", "BUY"); set("qty", s.option.lot);
    set("entry", s.option.entry); set("sl", s.option.sl); set("t1", s.option.t1); set("t2", s.option.t2);
  } else if (s.entry) {
    set("segment", S.style === "long" ? "delivery" : "intraday");
    set("side", (s.t1 ?? 0) >= (s.entry ?? 0) ? "BUY" : "SELL");
    set("entry", s.entry); set("sl", s.sl); set("t1", s.t1); set("t2", s.t2);
  } else { set("entry", d.quote.ltp); }
  S.calcFilled = true;
  calc();
}
let calcT;
$("#calcF").addEventListener("input", () => { clearTimeout(calcT); calcT = setTimeout(calc, 250); });
$("#fillBtn").addEventListener("click", () => fillCalc(true));
async function calc() {
  const v = calcF();
  if (!v.entry || !v.qty) { $("#calcRes").innerHTML = ""; return; }
  try {
    const r = await api("/api/pnl", { method: "POST", body: JSON.stringify(v) });
    const row = (name, x) => x ? `<tr><td>${name}</td><td class="${cls(x.gross)}">${money(x.gross)}</td><td class="muted">${money(x.charges.total)}</td><td class="${cls(x.net)}"><b>${money(x.net)}</b></td><td class="${cls(x.net)}">${sgn(x.pct_on_capital)}%</td></tr>` : "";
    $("#calcRes").innerHTML = `<table><tr><td class="muted">If price hits…</td><td class="muted" style="text-align:right">Gross</td><td class="muted" style="text-align:right">Charges</td><td class="muted" style="text-align:right">Net</td><td class="muted" style="text-align:right">%</td></tr>
      ${row("Stop-loss", r.sl)}${row("Target 1", r.t1)}${row("Target 2", r.t2)}</table>
      <div class="muted" style="font-size:12px;margin-top:8px">Capital used ${money(r.capital)} · price must move ${nf(r.breakeven_move)} just to cover charges${v.segment === "option" ? "" : ""}.</div>`;
  } catch (e) { $("#calcRes").innerHTML = `<span class="down">${esc(e.message)}</span>`; }
}
$("#addFromCalc").addEventListener("click", async () => {
  const v = calcF(); const d = S.detail; const s = d?.signals[S.style];
  const body = { ...v, symbol: S.sym };
  if (v.segment === "option" && s?.option) { body.opt_strike = s.option.strike; body.opt_type = s.option.type; body.underlying_entry = d.quote.ltp; }
  try { await api("/api/trades", { method: "POST", body: JSON.stringify(body) }); toast("Trade added to My Trades. You'll get alerts at SL / targets.", "t1_hit");
    S.trades = await api("/api/trades"); drawLines(); } catch (e) { toast(e.message, "sl_hit"); }
});

// ---------------------------------------------------------------- backtest
$("#btBtn").addEventListener("click", async () => {
  $("#btBox").innerHTML = '<span class="muted">Running… (live mode downloads 60 days of 5-minute data, about 5 seconds)</span>';
  try {
    const r = await api(`/api/backtest/${encodeURIComponent(S.sym)}`);
    if (r.error || !r.n) { $("#btBox").innerHTML = `<span class="muted">${esc(r.error || r.note)}</span>`; return; }
    $("#btBox").innerHTML = `<div class="lv">${lvBox("Trades", null).replace("–", r.n)}${lvBox("Win rate", null).replace("–", r.win_rate + "%")}
      ${lvBox("Avg R / trade", r.avg_r)}${lvBox("After costs", r.avg_r_net)}</div>
      <div class="lv">${lvBox("Total R", r.total_r)}${lvBox("Profit factor", r.profit_factor)}${lvBox("Worst losing run", null).replace("–", r.max_losing_streak)}${lvBox("Days tested", null).replace("–", r.days)}</div>
      <div class="muted" style="font-size:12px">Source: ${esc(r.source)}. Win rate alone means little: avg R after costs above 0 is what makes money.</div>
      <table style="margin-top:8px"><tr><td class="muted">When</td><td class="muted">Side</td><td class="muted">Entry</td><td class="muted">R</td></tr>
      ${r.trades.slice(0, 12).map(t => `<tr><td>${dstr(t.t)}</td><td>${t.side}</td><td>${nf(t.entry)}</td><td class="${cls(t.r)}">${sgn(t.r)}</td></tr>`).join("")}</table>`;
  } catch (e) { $("#btBox").innerHTML = `<span class="down">${esc(e.message)}</span>`; }
});

// ---------------------------------------------------------------- journal
const tf = $("#tradeForm");
tf.segment.addEventListener("change", () => $$(".optf").forEach(x => x.classList.toggle("hidden", tf.segment.value !== "option")));
let symT;
tf.symbol.addEventListener("input", () => {
  clearTimeout(symT);
  symT = setTimeout(async () => {
    const l = await api("/api/search?q=" + encodeURIComponent(tf.symbol.value));
    $("#symList").innerHTML = l.map(s => `<option value="${esc(s.sym)}">`).join("");
  }, 200);
});
tf.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(tf).entries());
  try { await api("/api/trades", { method: "POST", body: JSON.stringify(body) }); tf.reset(); $$(".optf").forEach(x => x.classList.add("hidden"));
    toast("Trade added. Live tracking started.", "t1_hit"); loadTrades(); } catch (err) { toast(err.message, "sl_hit"); }
});

async function loadTrades() {
  try { S.trades = await api("/api/trades"); } catch (e) { return; }
  S.openLive = S.trades.filter(t => t.status === "open");
  renderOpen(); renderClosed();
}
function tcard(t) {
  const lv = t.live; const p = lv?.pnl;
  const unit = t.segment === "option" ? `${t.symbol} ${t.opt_strike || ""} ${t.opt_type || ""}` : t.symbol;
  return `<div class="panel tc"><div class="h" data-sym="${esc(t.symbol)}" style="cursor:pointer"><b>${esc(unit)}</b>
      <span class="tag ${t.side === "BUY" ? "up" : "down"}">${t.side}</span><span class="tag">${esc(t.segment)}</span>
      <span style="flex:1"></span><span class="muted" style="font-size:12px">${dstr(t.created_at)}</span></div>
    ${lv ? `<div class="pnl ${cls(p.net)}">${money(p.net)} <span style="font-size:13px">(${sgn(p.pct_on_capital)}%)</span></div>
    <div class="row"><span>Now <b>${nf(lv.price)}</b>${lv.estimated ? " (est.)" : ""}</span><span>Entry <b>${nf(+t.entry)}</b></span><span>Qty <b>${t.qty}</b></span><span>Charges <b>${money(p.charges.total)}</b></span></div>
    <div class="row"><span>SL <b>${t.sl || "–"}</b></span><span>T1 <b>${t.t1 || "–"}</b></span><span>T2 <b>${t.t2 || "–"}</b></span>${lv.to_sl !== null ? `<span>Room to SL <b>${nf(lv.to_sl)}</b></span>` : ""}</div>
    <div class="adv ${lv.state}">${esc(lv.advice)}</div>` : `<div class="muted">Waiting for price…</div>`}
    ${t.notes ? `<div class="muted" style="font-size:12px">${esc(t.notes)}</div>` : ""}
    <div class="acts"><button class="btn sm" data-close="${t.id}">Close trade</button><button class="btn sm danger" data-del="${t.id}">Delete</button></div></div>`;
}
function renderOpen() {
  const open = S.openLive || [];
  $("#openTrades").innerHTML = open.length ? open.map(tcard).join("") : `<div class="panel empty">No open trades. Add one above, or from a stock's calculator.</div>`;
  renderStats();
}
function renderClosed() {
  const closed = S.trades.filter(t => t.status === "closed");
  $("#closedTable tbody").innerHTML = closed.length ? closed.map(t => `<tr><td><b>${esc(t.symbol)}</b> ${t.segment === "option" ? esc((t.opt_strike || "") + " " + (t.opt_type || "")) : ""}</td><td>${t.side}</td><td>${esc(t.segment)}</td><td class="num">${t.qty}</td>
    <td class="num">${nf(+t.entry)}</td><td class="num">${nf(+t.exit_price)}</td><td class="num muted">${t.live ? money(t.live.pnl.charges.total) : "–"}</td>
    <td class="num ${cls(t.live?.pnl.net)}"><b>${t.live ? money(t.live.pnl.net) : "–"}</b></td><td><button class="btn sm danger" data-del="${t.id}">✕</button></td></tr>`).join("")
    : `<tr><td colspan="9" class="empty">No closed trades yet</td></tr>`;
  renderStats();
}
function renderStats() {
  const closed = (S.trades || []).filter(t => t.status === "closed" && t.live);
  const open = S.openLive || [];
  const day0 = Math.floor((Date.now() / 1000 + IST) / 86400) * 86400 - IST;
  const realised = closed.reduce((a, t) => a + t.live.pnl.net, 0);
  const today = closed.filter(t => (t.exit_time || t.created_at) >= day0).reduce((a, t) => a + t.live.pnl.net, 0);
  const unreal = open.reduce((a, t) => a + (t.live?.pnl.net || 0), 0);
  const wins = closed.filter(t => t.live.pnl.net > 0).length;
  $("#jstats").innerHTML = [
    ["Open P&L (live)", `<span class="${cls(unreal)}">${money(unreal)}</span>`],
    ["Booked today", `<span class="${cls(today)}">${money(today)}</span>`],
    ["Booked total", `<span class="${cls(realised)}">${money(realised)}</span>`],
    ["Win rate", closed.length ? Math.round(wins / closed.length * 100) + "%" : "–"],
    ["Trades", `${open.length} open · ${closed.length} closed`],
  ].map(([k, v]) => `<div class="panel"><small>${k}</small><b>${v}</b></div>`).join("");
}
document.addEventListener("click", async (e) => {
  const c = e.target.closest("[data-close]"), d = e.target.closest("[data-del]");
  if (c) {
    const t = (S.openLive || []).find(x => x.id === c.dataset.close);
    const px = prompt("Exit price (leave as is to use current price):", t?.live?.price ?? "");
    if (px === null) return;
    await api(`/api/trades/${c.dataset.close}`, { method: "PATCH", body: JSON.stringify({ status: "closed", exit_price: px ? +px : undefined }) });
    loadTrades();
  } else if (d) {
    if (!confirm("Delete this trade permanently?")) return;
    await api(`/api/trades/${d.dataset.del}`, { method: "DELETE" });
    loadTrades();
  }
});

// ---------------------------------------------------------------- scorecard
async function loadScore() {
  const r = await api("/api/scorecard");
  $("#sstats").innerHTML = [
    ["Signals checked", r.total], ["Win rate", r.win_rate !== null ? r.win_rate + "%" : "–"],
    ["Avg R per signal", r.avg_r ?? "–"], ["Total R", r.total_r], ["Running now", r.active.length],
  ].map(([k, v]) => `<div class="panel"><small>${k}</small><b>${v}</b></div>`).join("");
  const rows = [...r.active.map(x => ({ ...x })).reverse(), ...r.recent];
  $("#scoreTable tbody").innerHTML = rows.length ? rows.map(x => `<tr class="click" data-sym="${esc(x.sym)}"><td><b>${esc(x.sym)}</b></td>
    <td><span class="tag ${x.side === "BUY" ? "up" : "down"}">${x.side}</span></td><td class="num">${nf(x.entry)}</td><td class="num">${nf(x.sl)}</td><td class="num">${nf(x.t1)}</td>
    <td><span class="tag ${x.status === "win" ? "up" : x.status === "loss" ? "down" : x.status === "active" ? "" : "warn"}">${x.status}</span></td>
    <td class="num ${cls(x.r)}">${x.r === null || x.r === undefined ? "–" : sgn(x.r)}</td><td class="muted">${dstr(x.t)}</td></tr>`).join("")
    : `<tr><td colspan="8" class="empty">No signals recorded yet. They are collected every 30 seconds from the strongest stocks while the market is open.</td></tr>`;
}
setInterval(() => { if (S.tab === "score" && !S.sym) loadScore().catch(() => {}); }, 15000);

// ---------------------------------------------------------------- alerts
function beep() {
  try {
    const a = new (window.AudioContext || window.webkitAudioContext)();
    const o = a.createOscillator(), g = a.createGain();
    o.connect(g); g.connect(a.destination); o.frequency.value = 880; g.gain.value = 0.08;
    o.start(); o.stop(a.currentTime + 0.18);
  } catch (e) {}
}
function toast(text, kind = "", sym) {
  const el = document.createElement("div");
  el.className = "toast " + kind; el.textContent = text;
  el.onclick = () => { el.remove(); if (sym) openDetail(sym); };
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 12000);
}
function alertIn(a) {
  S.lastAlert = Math.max(S.lastAlert, a.id);
  toast(a.text, a.kind, a.sym); beep();
  if (navigator.vibrate) navigator.vibrate(200);
  if (S.notify && "Notification" in window && Notification.permission === "granted") {
    try { new Notification("TradeLens", { body: a.text, tag: "tl" + a.id }); } catch (e) {}
  }
  if (S.tab === "journal") loadTrades();
}
function renderBell() { $("#bellBtn").textContent = S.notify ? "🔔 Alerts on" : "🔕 Alerts off"; }
$("#bellBtn").addEventListener("click", async () => {
  if (!("Notification" in window)) { toast("This browser doesn't support notifications. Toasts and sound still work.", "eod"); return; }
  if (S.notify) S.notify = false;
  else S.notify = (await Notification.requestPermission()) === "granted";
  try { localStorage.setItem("tl_notify", S.notify ? "1" : "0"); } catch (e) {}
  renderBell();
});

// ---------------------------------------------------------------- live search helper (header + add-share popup)
async function searchShares(q, limit = 20) {
  if (!q.trim()) return [];
  try { return await api(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`); } catch (e) { return []; }
}
function resultRow(r, i, mode) {
  const px = r.ltp ? `<span class="num">${nf(r.ltp)}</span> <span class="num ${cls(r.chg)}">${r.chg !== null && r.chg !== undefined ? sgn(r.chg) + "%" : ""}</span>` : "";
  const right = mode === "add" ? (r.in_watchlist ? `<span class="added">✓ In watchlist</span>` : `<button class="btn sm pri">+ Add</button>`) : "";
  return `<${mode === "add" ? "li" : "div"} data-i="${i}" class="${i === 0 ? "on" : ""}"><b>${esc(r.sym)}</b>${r.fno ? '<span class="tag">F&amp;O</span>' : ""}
    <small>${r.name && r.name !== r.sym ? esc(r.name) : ""}</small><span class="sp"></span>${px} ${right}</${mode === "add" ? "li" : "div"}>`;
}
function keyNav(e, box, onPick) {
  const items = $$("[data-i]", box); if (!items.length) return;
  let i = items.findIndex(x => x.classList.contains("on"));
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); i = (i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((x, k) => x.classList.toggle("on", k === i)); items[i].scrollIntoView({ block: "nearest" }); }
  if (e.key === "Enter") { e.preventDefault(); onPick(Math.max(0, i)); }
}

// header search: open any listed share
let gRes = [], gT;
$("#gq").addEventListener("input", () => {
  clearTimeout(gT);
  gT = setTimeout(async () => {
    gRes = await searchShares($("#gq").value, 12);
    const dd = $("#gdd");
    dd.innerHTML = gRes.length ? gRes.map((r, i) => resultRow(r, i, "open")).join("") : ($("#gq").value.trim() ? '<div class="muted">No listed share matches</div>' : "");
    dd.classList.toggle("hidden", !$("#gq").value.trim());
  }, 120);
});
const gPick = (i) => { const r = gRes[i]; if (!r) return; $("#gq").value = ""; $("#gdd").classList.add("hidden"); openDetail(r.sym); };
$("#gq").addEventListener("keydown", (e) => { if (e.key === "Escape") $("#gdd").classList.add("hidden"); keyNav(e, $("#gdd"), gPick); });
$("#gdd").addEventListener("click", (e) => { const it = e.target.closest("[data-i]"); if (it) gPick(+it.dataset.i); });
document.addEventListener("click", (e) => { if (!e.target.closest(".gsearch")) $("#gdd").classList.add("hidden"); });

// ---------------------------------------------------------------- Volatile Watchlist: add / remove
async function watchToggle(sym, add) {
  if (!add && !confirm(`Remove ${sym} from your Volatile Watchlist?`)) return false;
  try {
    const r = await api("/api/watchlist", { method: "POST", body: JSON.stringify({ sym, action: add ? "add" : "remove" }) });
    toast(add ? (r.already ? `${sym} is already in your watchlist` : `${sym} added to Volatile Watchlist`) : `${sym} removed from watchlist`, add ? "t1_hit" : "");
    if (S.sym === sym) setWatchBtn(add);
    return true;
  } catch (e) { toast(e.message, "sl_hit"); return false; }
}
let aRes = [], aT;
function openAdd() { $("#addModal").classList.remove("hidden"); $("#addQ").value = ""; $("#addRes").innerHTML = '<li class="muted" style="cursor:default">Start typing to search every listed share</li>'; setTimeout(() => $("#addQ").focus(), 50); }
function closeAdd() { $("#addModal").classList.add("hidden"); }
$("#addShareBtn").addEventListener("click", openAdd);
$("#addClose").addEventListener("click", closeAdd);
$("#addModal").addEventListener("click", (e) => { if (e.target.id === "addModal") closeAdd(); });
$("#addQ").addEventListener("input", () => {
  clearTimeout(aT);
  aT = setTimeout(async () => {
    const q = $("#addQ").value;
    aRes = await searchShares(q, 25);
    $("#addRes").innerHTML = aRes.length ? aRes.map((r, i) => resultRow(r, i, "add")).join("")
      : `<li class="muted" style="cursor:default">${q.trim() ? "No listed share matches “" + esc(q) + "”" : "Start typing to search every listed share"}</li>`;
  }, 120);
});
async function aPick(i) {
  const r = aRes[i]; if (!r || r.in_watchlist) return;
  const li = $(`#addRes [data-i="${i}"]`); if (li) li.lastElementChild.outerHTML = '<span class="muted">adding…</span>';
  if (await watchToggle(r.sym, true)) { r.in_watchlist = true; if (li) li.lastElementChild.outerHTML = '<span class="added">✓ In watchlist</span>'; }
}
$("#addQ").addEventListener("keydown", (e) => { if (e.key === "Escape") closeAdd(); keyNav(e, $("#addRes"), aPick); });
$("#addRes").addEventListener("click", (e) => { const it = e.target.closest("[data-i]"); if (it) aPick(+it.dataset.i); });

// stock page: watch + price alert buttons
function setWatchBtn(on) { S.watching = on; $("#dWatch").textContent = on ? "★ Watching" : "☆ Watch"; $("#dWatch").classList.toggle("pri", on); }
async function refreshWatchBtn(sym) {
  const r = (await searchShares(sym, 8)).find(x => x.sym === sym);
  if (S.sym === sym) { setWatchBtn(!!r?.in_watchlist); $("#dWatch").classList.toggle("hidden", !r); }
}
$("#dWatch").addEventListener("click", () => watchToggle(S.sym, !S.watching));
$("#dAlert").addEventListener("click", async () => {
  const ltp = S.detail?.quote?.ltp;
  const v = prompt(`Alert me when ${S.sym} reaches price (now ${nf(ltp)}):`, ltp ? nf(ltp).replace(/,/g, "") : "");
  if (!v) return;
  try { await api("/api/price_alerts", { method: "POST", body: JSON.stringify({ sym: S.sym, price: +v }) }); toast(`Price alert set: ${S.sym} at ${v}`, "t1_hit"); }
  catch (e) { toast(e.message, "sl_hit"); }
});

// ---------------------------------------------------------------- Angel account
async function loadAccount() {
  try { S.acct = await api("/api/account"); renderAccount(); } catch (e) {}
  try { const st = await api("/api/settings"); $("#lossLim").value = st.daily_loss_limit || ""; } catch (e) {}
}
$("#lossSave").addEventListener("click", async () => {
  await api("/api/settings", { method: "POST", body: JSON.stringify({ daily_loss_limit: +$("#lossLim").value || 0 }) });
  toast("Daily loss limit saved", "t1_hit"); loadAccount();
});
function renderAccount() {
  const a = S.acct; if (!a) return;
  $("#acErr").classList.toggle("hidden", !a.error);
  $("#acErr").innerHTML = a.error ? `<b>Angel One:</b> ${esc(a.error)}` : "";
  const f = a.funds || {}, t = a.totals || {};
  $("#acFunds").innerHTML = [
    ["Available balance", money(f.available || 0)], ["Margin used", money(f.used || 0)],
    ["Portfolio value", money(t.value || 0)], ["Portfolio P&L", `<span class="${cls(t.pnl)}">${money(t.pnl || 0)} <small>(${sgn(t.pnl_pct || 0)}%)</small></span>`],
    ["Portfolio today", `<span class="${cls(t.day_pnl)}">${money(t.day_pnl || 0)}</span>`],
    ["Active trades P&L", `<span class="${cls(t.positions_pnl)}">${money(t.positions_pnl || 0)}</span>`],
  ].map(([k, v]) => `<div class="panel"><small>${k}</small><b>${v}</b></div>`).join("");
  const g = a.guard || {};
  const gd = $("#acGuard");
  gd.classList.toggle("hidden", !g.limit);
  if (g.limit) {
    gd.className = "guard " + (g.breached ? "bad" : "ok");
    gd.innerHTML = g.breached ? `⛔ Daily loss limit hit: today ${money(g.today_pnl)} vs limit −₹${nf(g.limit, 0)}. Stop trading for today.`
      : `Daily loss guard: today ${money(g.today_pnl)} · limit −₹${nf(g.limit, 0)}${g.used_pct ? ` · ${g.used_pct}% used` : ""}`;
  }
  const pos = a.positions || [];
  $("#acPosNote").textContent = `${t.open_positions || 0} open · ${a.source || ""}${a.updated ? " · " + tstr(a.updated) : ""}`;
  $("#acPos tbody").innerHTML = pos.length ? pos.map(p => `<tr ${p.kind === "EQ" ? `class="click" data-sym="${esc(p.underlying)}"` : ""}>
    <td><b>${esc(p.symbol)}</b> ${p.kind !== "EQ" ? `<span class="tag">${p.kind}</span>` : ""}${!p.open ? ' <span class="tag">closed</span>' : ""}</td>
    <td>${esc(p.product)}</td><td class="num ${cls(p.netqty)}">${nf(p.netqty, 0)}</td><td class="num">${nf(p.avg || p.buy_avg || p.sell_avg)}</td>
    <td class="num">${nf(p.ltp)}</td><td class="num ${cls(p.pnl)}"><b>${money(p.pnl)}</b></td></tr>`).join("")
    : `<tr><td colspan="6" class="empty">No positions today</td></tr>`;
  const h = a.holdings || [];
  $("#acHoldNote").textContent = `${h.length} shares · invested ${money(t.invested || 0)}`;
  $("#acHold tbody").innerHTML = h.length ? h.map(x => `<tr class="click" data-sym="${esc(x.sym)}"><td><b>${esc(x.sym)}</b></td>
    <td class="num">${nf(x.qty, 0)}</td><td class="num">${nf(x.avg)}</td><td class="num">${nf(x.ltp)}</td>
    <td class="num ${cls(x.day_pnl)}">${money(x.day_pnl)} <small>(${sgn(x.day_pct)}%)</small></td>
    <td class="num">${money(x.invested)}</td><td class="num">${money(x.value)}</td>
    <td class="num ${cls(x.pnl)}"><b>${money(x.pnl)}</b> <small>(${sgn(x.pnl_pct)}%)</small></td></tr>`).join("")
    : `<tr><td colspan="8" class="empty">No holdings</td></tr>`;
  const o = a.orders || [];
  $("#acOrd tbody").innerHTML = o.length ? o.map(x => `<tr><td><b>${esc(x.symbol)}</b></td><td class="${x.side === "BUY" ? "up" : "down"}">${esc(x.side)}</td>
    <td class="num">${nf(x.filled, 0)}/${nf(x.qty, 0)}</td><td class="num">${nf(x.avg || x.price)}</td><td>${esc(x.product)}</td>
    <td><span class="tag ${/complete/i.test(x.status) ? "up" : /reject|cancel/i.test(x.status) ? "down" : "warn"}">${esc(x.status)}</span></td><td class="muted">${esc(x.time || "")}</td></tr>`).join("")
    : `<tr><td colspan="7" class="empty">No orders today</td></tr>`;
}

// ---------------------------------------------------------------- Trade Planner
async function loadPlanner(save) {
  if (save) await api("/api/settings", { method: "POST", body: JSON.stringify({ risk_pct: $("#plRisk").value, max_alloc_pct: $("#plAlloc").value, intraday_leverage: $("#plLev").value }) });
  $("#plSum").innerHTML = '<div class="panel"><small>Working</small><b>Scanning setups…</b></div>';
  const amt = $("#plAmt").value;
  try { renderPlanner(await api("/api/planner" + (amt ? "?amount=" + encodeURIComponent(amt) : ""))); }
  catch (e) { $("#plSum").innerHTML = `<div class="panel"><small>Error</small><b class="down">${esc(e.message)}</b></div>`; }
}
$("#plRun").addEventListener("click", () => loadPlanner(true));
setInterval(() => { if (S.tab === "planner" && !S.sym) loadPlanner(); }, 60000);
function ideaCard(i) {
  const name = i.contract ? `${esc(i.contract)}` : esc(i.sym);
  const sideTag = `<span class="tag ${i.side === "BUY" ? "up" : "down"}">${i.side}${i.contract ? "" : ""}</span>`;
  const ready = i.ready ? '<span class="tag up">Enter now</span>' : `<span class="tag">Limit at ${nf(i.entry)}</span>`;
  return `<div class="panel idea ${i.in_plan ? "inplan" : ""}">
    <div class="h" data-sym="${esc(i.sym)}">${i.in_plan ? "★ " : ""}<b>${name}</b>${sideTag}${ready}<span style="flex:1"></span>
      <span class="muted" style="font-size:11px">conf ${i.confidence ?? "–"}%</span></div>
    <div><span class="ev ${cls(i.ev)}">${money(i.ev)}</span> <span class="muted" style="font-size:12px">expected P&amp;L</span></div>
    <div class="grid">
      <div><small>Qty</small><b>${i.lots ? i.lots + " lot · " : ""}${nf(i.qty, 0)}</b></div><div><small>Entry</small><b>${nf(i.entry)}</b></div>
      <div><small>Stop-loss</small><b>${nf(i.sl)}</b></div><div><small>Target 1 / 2</small><b>${nf(i.t1)} / ${nf(i.t2)}</b></div>
      <div><small>${i.style === "intraday" ? "Margin" : "Capital"}</small><b>${money(i.capital)}</b></div>
      <div><small>Loss at SL</small><b class="down">${money(-i.risk)}</b></div>
      <div><small>Profit T1</small><b class="up">${money(i.profit_t1)}</b></div><div><small>Profit T2</small><b class="up">${money(i.profit_t2)}</b></div>
    </div>
    ${i.contract ? `<div class="p">Stock entry ${nf(i.stock_entry)} · exit if stock breaks ${nf(i.stock_sl)}${i.estimated ? " · premium estimated" : ""}</div>` : ""}
    <div class="sum">${esc(i.summary)}</div>
    ${i.warnings.length ? `<div class="w">! ${i.warnings.map(esc).join(" · ")}</div>` : ""}
    <div class="p">Win chance used: ${Math.round(i.p * 100)}% from ${esc(i.p_source)} · charges ≈ ${money(i.charges)}</div>
  </div>`;
}
function renderPlanner(d) {
  $("#plBal").textContent = money(d.balance);
  $("#plSrc").textContent = d.balance_source ? "· " + d.balance_source : "";
  const st = d.settings || {};
  if (!$("#plRisk").value) $("#plRisk").value = st.risk_pct;
  if (!$("#plAlloc").value) $("#plAlloc").value = st.max_alloc_pct;
  if (!$("#plLev").value) $("#plLev").value = st.intraday_leverage;
  $("#plRecharge").classList.toggle("hidden", !d.recharge);
  $("#plBody").classList.toggle("hidden", !!d.recharge);
  if (d.recharge) {
    $("#plRecharge").innerHTML = `<b>Recharge your wallet</b><br><br>${esc(d.message)}<br><br><span class="muted" style="font-size:13px">Open the Angel One app → Funds → Add funds. Or type an amount above to see a plan for it.</span>`;
    return;
  }
  const p = d.plan || {};
  $("#plSum").innerHTML = [
    ["★ Plan: trades that fit together", `${p.count || 0} trades`], ["Capital / margin used", money(p.capital || 0)],
    ["Expected P&L of plan", `<span class="${cls(p.ev)}">${money(p.ev || 0)}</span>`],
    ["If all hit target 1", `<span class="up">${money(p.best_case || 0)}</span>`], ["If all hit stop-loss", `<span class="down">${money(p.worst_case || 0)}</span>`],
    ["Max loss per trade", money(d.risk_budget || 0)],
  ].map(([k, v]) => `<div class="panel"><small>${k}</small><b>${v}</b></div>`).join("");
  const col = (lst, empty) => lst.length ? lst.map(ideaCard).join("") : `<div class="panel empty">${empty}</div>`;
  $("#plIntraday").innerHTML = col(d.ideas.intraday, "No intraday setup with positive expected P&L right now.");
  $("#plOption").innerHTML = col(d.ideas.option, "No option fits your balance and risk right now.");
  $("#plLong").innerHTML = col(d.ideas.long, "No long-term buy zone right now.");
  $("#plSkipped").innerHTML = d.skipped?.length ? "<b>Skipped:</b> " + d.skipped.map(esc).join(" · ") : "";
}

// ---------------------------------------------------------------- Radar + price alerts
function radarItem(r, isNew) {
  return `<li class="${r.tone} ${isNew ? "new" : ""}" data-sym="${esc(r.sym)}"><span class="tm">${tstr(r.ts)}</span><b>${esc(r.sym)}</b><span>${esc(r.text)}</span></li>`;
}
async function loadRadar() {
  const l = await api("/api/radar").catch(() => []);
  if (l.length) S.lastRadar = Math.max(S.lastRadar || 0, l[0].id);
  $("#radarList").innerHTML = l.length ? l.map(r => radarItem(r)).join("") : '<li class="muted" style="cursor:default">Quiet so far. Events appear here live: volume spikes, new highs/lows with volume, strong trends starting.</li>';
}
function radarIn(list) {
  list.forEach(r => { S.lastRadar = Math.max(S.lastRadar || 0, r.id); });
  if (S.tab === "radar") {
    const ul = $("#radarList"); if (ul.querySelector(".muted")) ul.innerHTML = "";
    ul.insertAdjacentHTML("afterbegin", list.slice().reverse().map(r => radarItem(r, true)).join(""));
  } else {
    S.radarNew = (S.radarNew || 0) + list.length;
    $("#radarCnt").textContent = S.radarNew > 99 ? "99+" : S.radarNew; $("#radarCnt").classList.remove("hidden");
  }
}
async function loadPA() {
  const l = await api("/api/price_alerts").catch(() => []);
  $("#paList").innerHTML = l.length ? l.map(a => `<li class="${a.done ? "up" : ""}" data-sym="${esc(a.sym)}"><span class="tm">${a.done ? "✓ hit" : a.op === "above" ? "▲" : "▼"}</span>
    <b>${esc(a.sym)}</b><span>${a.op === "above" ? "crosses above" : "falls below"} <b class="num" style="width:auto">${nf(a.price)}</b> · now ${nf(a.ltp)}${a.note ? " · " + esc(a.note) : ""}</span>
    <span style="flex:1"></span><button class="btn sm danger" data-pa="${a.id}">✕</button></li>`).join("")
    : '<li class="muted" style="cursor:default">No price alerts. Add one above or from any stock page (🔔 Price alert).</li>';
}
$("#paForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const b = Object.fromEntries(new FormData(e.target).entries());
  try { await api("/api/price_alerts", { method: "POST", body: JSON.stringify(b) }); e.target.reset(); toast("Price alert added", "t1_hit"); loadPA(); }
  catch (err) { toast(err.message, "sl_hit"); }
});
$("#paForm [name=sym]").addEventListener("input", async (e) => {
  const l = await searchShares(e.target.value, 10);
  $("#symList").innerHTML = l.map(s => `<option value="${esc(s.sym)}">`).join("");
});
$("#paList").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-pa]"); if (!b) return;
  e.stopPropagation();
  await api("/api/price_alerts?id=" + b.dataset.pa, { method: "DELETE" }); loadPA();
}, true);

// ---------------------------------------------------------------- sign in / sign up / passcode
const FORMS = { login: "#fLogin", reg1: "#fReg1", reg2: "#fReg2", unlock: "#fUnlock", setpc: "#fSetPc" };
function authView(v) {
  Object.entries(FORMS).forEach(([k, sel]) => $(sel).classList.toggle("hidden", k !== v));
  $$("#auth .err").forEach(x => x.textContent = "");
  const first = $(FORMS[v] + " input:not([type=checkbox])"); if (first && v !== "unlock") setTimeout(() => first.focus(), 60);
}
function showAuth(state, info) {
  stopStream();
  $("#auth").classList.remove("hidden");
  if (state === "passcode") {
    $("#unlockHi").textContent = info?.name ? `Welcome back, ${info.name}` : "Welcome back";
    pcBuf = ""; drawDots(); authView("unlock");
  } else authView("login");
}
function hideAuth() { $("#auth").classList.add("hidden"); }
function showErrs(form, errs) {
  $$(".err", form).forEach(x => x.textContent = "");
  Object.entries(errs || {}).forEach(([k, v]) => { const el = $(`[data-err="${k}"]`, form) || $('[data-err="form"]', form); if (el) el.textContent = v; });
}
async function post(path, body) {
  const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let j = {}; try { j = await r.json(); } catch (e) {}
  return { ok: r.ok, status: r.status, j };
}
document.addEventListener("click", (e) => {
  const go = e.target.closest("[data-go]"); if (go) { e.preventDefault(); authView(go.dataset.go); }
  const eye = e.target.closest(".eye"); if (eye) { const i = eye.previousElementSibling; i.type = i.type === "password" ? "text" : "password"; }
});
$("#fLogin").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, btn = $("button.pri", f);
  btn.disabled = true;
  const { ok, j } = await post("/api/auth/login", { username: f.username.value, password: f.password.value, remember: f.remember.checked });
  btn.disabled = false;
  if (!ok) return showErrs(f, { form: j.error || "Sign in failed" });
  f.password.value = "";
  if (j.need_passcode) { S.pendingUser = j.user; authView("setpc"); return; }
  hideAuth(); start(j.user);
});
// password rules live check
function pwCheck() {
  const f = $("#fReg1"), p = f.password.value, c = f.confirm_password.value;
  const r = { len: p.length >= 8, up: /[A-Z]/.test(p), lo: /[a-z]/.test(p), num: /\d/.test(p), sym: /[^A-Za-z0-9]/.test(p), match: p && p === c };
  $$("#pwRules li").forEach(li => li.classList.toggle("ok", !!r[li.dataset.r]));
  return Object.values(r).every(Boolean);
}
["password", "confirm_password"].forEach(n => $("#fReg1").elements[n].addEventListener("input", pwCheck));
$("#fReg1").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target, v = Object.fromEntries(new FormData(f).entries()), errs = {};
  if (!v.first_name.trim()) errs.first_name = "Required";
  if (!v.last_name.trim()) errs.last_name = "Required";
  if (!/^[A-Za-z0-9_.]{4,20}$/.test(v.username.trim())) errs.username = "4–20 letters, numbers, _ or .";
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.email.trim())) errs.email = "Enter a valid email";
  if (!/^(\+?91)?[6-9]\d{9}$/.test(v.phone.replace(/[\s-]/g, ""))) errs.phone = "Enter a valid 10-digit mobile number";
  const a = ["api_key", "client_code", "pin", "totp_secret"].map(k => (v[k] || "").trim());  // demo: these fields are absent
  if (a.some(Boolean) && !a.every(Boolean)) errs.angel = "Fill all four Angel One fields, or leave all empty to add later";
  if (!pwCheck()) errs.password = "Password must meet every rule below";
  if (Object.keys(errs).length) return showErrs(f, errs);
  S.reg = v; authView("reg2");
});
$("#fReg2").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, btn = $("button.pri", f);
  if (!/^\d{4}$/.test(f.passcode.value)) return showErrs(f, { passcode: "Passcode must be 4 digits" });
  if (f.passcode.value !== f.confirm_passcode.value) return showErrs(f, { confirm_passcode: "Passcodes don't match" });
  btn.disabled = true; btn.textContent = S.reg.api_key ? "Checking Angel One…" : "Creating…";
  const { ok, j } = await post("/api/auth/register", { ...S.reg, passcode: f.passcode.value, confirm_passcode: f.confirm_passcode.value, remember: f.remember.checked });
  btn.disabled = false; btn.textContent = "Create account";
  if (!ok) {
    const step1 = Object.keys(j.errors || {}).filter(k => !["passcode", "confirm_passcode"].includes(k));
    if (step1.length) { authView("reg1"); showErrs($("#fReg1"), j.errors); } else showErrs(f, j.errors || { form: j.error });
    return;
  }
  $("#fReg1").reset(); f.reset(); S.reg = null; hideAuth(); start(j.user);
  toast(`Welcome, ${j.user.first_name}! Your account is ready.`, "t1_hit");
});
// passcode keypad
let pcBuf = "";
function drawDots() { $$("#pcDots i").forEach((d, i) => d.classList.toggle("on", i < pcBuf.length)); }
async function pcPress(k) {
  if (k === "del") pcBuf = pcBuf.slice(0, -1); else if (pcBuf.length < 4) pcBuf += k;
  drawDots();
  if (pcBuf.length === 4) {
    const { ok, j } = await post("/api/auth/unlock", { passcode: pcBuf });
    pcBuf = "";
    if (ok) { drawDots(); hideAuth(); start(j.user); return; }
    $("#pcDots").classList.add("shake"); setTimeout(() => { $("#pcDots").classList.remove("shake"); drawDots(); }, 380);
    showErrs($("#fUnlock"), { form: j.error });
    if (j.state === "login") setTimeout(() => authView("login"), 1400);
  }
}
$("#pcPad").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) pcPress(b.dataset.k || b.textContent); });
document.addEventListener("keydown", (e) => {
  if ($("#fUnlock").classList.contains("hidden") || $("#auth").classList.contains("hidden")) return;
  if (/^\d$/.test(e.key)) pcPress(e.key); else if (e.key === "Backspace") pcPress("del");
});
$("#fSetPc").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const r = await post("/api/profile/passcode", { passcode: f.passcode.value, confirm: f.confirm.value });
  if (!r.ok) return showErrs(f, r.j.errors || { form: r.j.error });
  f.reset(); hideAuth(); start(S.pendingUser);
});

// ---------------------------------------------------------------- profile
async function loadProfile() {
  const p = await api("/api/profile"); S.user = p; renderUser();
  const f = $("#fProfile");
  ["first_name", "last_name", "username", "email", "phone"].forEach(k => f.elements[k].value = p[k] || "");
  const a = p.angel;
  $("#apiBadge").innerHTML = a.connected ? `<span class="tag ${a.status === "connected" ? "up" : a.status === "error" ? "down" : "warn"}">${esc(a.status)}</span>` : '<span class="tag">not added</span>';
  $("#apiInfo").innerHTML = a.connected
    ? `Client ID <b>${esc(a.client_code)}</b> · API key <b class="mono">${esc(a.api_key_masked)}</b> · PIN ${a.pin_masked} · TOTP ${esc(a.totp_masked)}${a.error ? `<br><span class="warnc">${esc(a.error)}</span>` : ""}<br>To replace, fill all four fields below.`
    : "Add your Angel One details to see your real balance, portfolio, positions and orders. They are encrypted; TradeLens never places orders.";
  $("#apiRemove").classList.toggle("hidden", !a.connected);
  $("#fApi").reset();
}
$("#fProfile").addEventListener("submit", async (e) => {
  e.preventDefault();
  const b = Object.fromEntries(new FormData(e.target).entries());
  const r = await post("/api/profile", b);
  if (!r.ok) return showErrs(e.target, r.j.errors);
  toast("Details saved", "t1_hit"); loadProfile();
});
$("#fApi").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("button.pri", e.target); btn.disabled = true; btn.textContent = "Checking with Angel One…";
  const r = await post("/api/profile/angel", Object.fromEntries(new FormData(e.target).entries()));
  btn.disabled = false; btn.textContent = "Save & check";
  if (!r.ok) return showErrs($("#fApi").parentElement, { api: r.j.error });
  showErrs($("#fApi").parentElement, {});
  toast(r.j.restarting ? "Angel One connected. TradeLens is switching to live prices (restarting, about 1 minute)…" : "Angel One details saved", "t1_hit");
  loadProfile();
});
$("#apiRemove").addEventListener("click", async () => {
  if (!confirm("Remove your Angel One API details?")) return;
  await api("/api/profile/angel", { method: "DELETE" }); toast("Angel One details removed", ""); loadProfile();
});
$("#fPw").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await post("/api/profile/password", Object.fromEntries(new FormData(e.target).entries()));
  if (!r.ok) return showErrs(e.target, r.j.errors);
  e.target.reset(); showErrs(e.target, {}); toast("Password changed. Other devices are signed out.", "t1_hit");
});
$("#fPc").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await post("/api/profile/passcode", Object.fromEntries(new FormData(e.target).entries()));
  if (!r.ok) return showErrs(e.target, r.j.errors);
  e.target.reset(); showErrs(e.target, {}); toast("Passcode saved", "t1_hit");
});
$("#logoutBtn").addEventListener("click", async () => { await post("/api/auth/logout", { forget_device: true }); S.user = null; showAuth("login"); });
$("#lockBtn").addEventListener("click", async () => {
  if (!S.user?.has_passcode) { toast("Set a passcode first", "eod"); return; }
  await post("/api/auth/logout", { forget_device: false });
  const m = await (await fetch("/api/auth/me")).json(); showAuth(m.state, m);
});
$("#userChip").addEventListener("click", () => setTab("profile"));
function renderUser() {
  const u = S.user; if (!u) return;
  $("#userAv").textContent = (u.first_name || u.username || "?")[0].toUpperCase();
  $("#userName").textContent = u.role === "admin" ? "Admin" : u.first_name;
  $("#userChip").classList.toggle("admin", u.role === "admin");
  $("#adminTab").classList.toggle("hidden", u.role !== "admin");
}

// ---------------------------------------------------------------- admin dashboard
async function loadAdmin() {
  const d = await api("/api/admin/users");
  S.admin = d;
  const t = d.totals;
  $("#adTotals").innerHTML = [["Users", t.users], ["Signed in today", t.active_today], ["With Angel API", t.with_api],
    ["Total balance", money(t.balance)], ["Total portfolio", money(t.portfolio_value)], ["Trades logged", `${t.trades} · ${t.open_trades} open`]]
    .map(([k, v]) => `<div class="panel"><small>${k}</small><b>${v}</b></div>`).join("");
  $("#adFeed").innerHTML = `Live prices: <b>${d.feed === "demo" ? "demo mode" : esc(d.feed)}</b>.`;
  renderAdminUsers();
  if (S.adSel) loadAdminUser(S.adSel);
}
$("#adRefresh").addEventListener("click", loadAdmin);
$("#adFilter").addEventListener("input", renderAdminUsers);
function renderAdminUsers() {
  const q = $("#adFilter").value.trim().toLowerCase();
  const rows = (S.admin?.users || []).filter(u => !q || [u.first_name, u.last_name, u.username, u.email, u.phone].join(" ").toLowerCase().includes(q));
  $("#adUsers tbody").innerHTML = rows.map(u => {
    const a = u.angel, s = u.stats;
    const api = a.connected ? `<span class="tag ${a.status === "connected" ? "up" : a.status === "error" ? "down" : "warn"}">${esc(a.status)}</span> <span class="mono muted">${esc(a.client_code)} · ${esc(a.api_key_masked || "")}</span>` : '<span class="muted">not added</span>';
    return `<tr class="click ${S.adSel === u.id ? "sel" : ""}" data-uid="${u.id}"><td><b>${esc(u.first_name)} ${esc(u.last_name)}</b>${u.role === "admin" ? ' <span class="tag warn">admin</span>' : ""}${u.data_source ? ' <span class="tag up" title="powers live prices">price feed</span>' : ""}</td>
      <td class="mono">${esc(u.username)}</td><td>${esc(u.email)}</td><td>${esc(u.phone)}</td><td style="text-align:left">${api}</td>
      <td class="num">${s.balance !== null && s.balance !== undefined ? money(s.balance) : "–"}</td><td class="num">${s.portfolio_value ? money(s.portfolio_value) : "–"}</td>
      <td class="num ${cls(s.portfolio_pnl)}">${s.portfolio_pnl ? money(s.portfolio_pnl) : "–"}</td>
      <td class="num">${s.trades} <small class="muted">(${s.open} open)</small></td><td class="muted">${u.last_login ? dstr(u.last_login) : "never"}</td>
      <td>${u.disabled ? '<span class="tag down">disabled</span>' : '<span class="tag up">active</span>'}</td></tr>`;
  }).join("") || '<tr><td colspan="11" class="empty">No users yet</td></tr>';
}
$("#adUsers").addEventListener("click", (e) => { const tr = e.target.closest("[data-uid]"); if (tr) { S.adSel = tr.dataset.uid; renderAdminUsers(); loadAdminUser(tr.dataset.uid); } });
async function loadAdminUser(uid) {
  $("#adDetail").innerHTML = '<div class="panel empty">Loading…</div>';
  let d; try { d = await api("/api/admin/user/" + uid); } catch (e) { $("#adDetail").innerHTML = `<div class="panel empty">${esc(e.message)}</div>`; return; }
  const u = d.user, a = u.angel, acc = d.account, f = acc.funds || {}, t = acc.totals || {};
  const kv = (k, v) => `<div><small>${k}</small>${v}</div>`;
  const tbl = (head, rows, empty) => `<div class="tablewrap" style="max-height:340px"><table class="t"><thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${head.length}" class="empty">${empty}</td></tr>`}</tbody></table></div>`;
  $("#adDetail").innerHTML = `<div class="panel addet">
    <div class="hd"><b>${esc(u.first_name)} ${esc(u.last_name)}</b><span class="mono muted">@${esc(u.username)}</span>${u.disabled ? '<span class="tag down">disabled</span>' : ""}
      <span class="sp"></span>
      ${a.connected && !u.data_source ? '<button class="btn sm" data-act="data_source">Use for live prices</button>' : ""}
      <button class="btn sm" data-act="reset_password">Reset password</button>
      ${u.role !== "admin" ? (u.disabled ? '<button class="btn sm" data-act="enable">Enable</button>' : '<button class="btn sm" data-act="disable">Disable</button>') : ""}
      ${u.role !== "admin" ? '<button class="btn sm danger" data-act="delete">Delete</button>' : ""}</div>
    <div id="adTemp"></div>
    <div class="kvgrid">
      ${kv("Email", esc(u.email || "–"))}${kv("Mobile", esc(u.phone || "–"))}${kv("Joined", dstr(u.created))}${kv("Last login", u.last_login ? dstr(u.last_login) : "never")}
      ${kv("Password", '<span class="muted">hashed: reset only</span>')}${kv("Passcode", u.has_passcode ? "set (hashed)" : "not set")}
      ${kv("Angel client ID", esc(a.client_code || "–"))}${kv("Angel API key", `<span class="mono">${esc(a.api_key_masked || "–")}</span>`)}
      ${kv("Angel PIN / TOTP", a.connected ? "•••• / encrypted" : "–")}${kv("API status", `${esc(a.status)}${a.error ? `<br><small class="warnc" style="text-transform:none;letter-spacing:0">${esc(a.error)}</small>` : ""}`)}
      ${kv("Risk settings", `${d.settings.risk_pct}% loss / ${d.settings.max_alloc_pct}% capital / ${d.settings.intraday_leverage}×`)}${kv("Daily loss limit", d.settings.daily_loss_limit ? money(d.settings.daily_loss_limit) : "off")}
    </div>
    ${acc.error ? `<div class="guard bad" style="margin-bottom:10px">${esc(acc.error)}</div>` : ""}
    <div class="kvgrid">
      ${kv("Available balance", `<b>${money(f.available || 0)}</b>`)}${kv("Margin used", money(f.used || 0))}${kv("Portfolio value", money(t.value || 0))}
      ${kv("Portfolio P&L", `<b class="${cls(t.pnl)}">${money(t.pnl || 0)} (${sgn(t.pnl_pct || 0)}%)</b>`)}${kv("Today", `<span class="${cls(t.day_pnl)}">${money(t.day_pnl || 0)}</span>`)}
      ${kv("Active trades P&L", `<b class="${cls(t.positions_pnl)}">${money(t.positions_pnl || 0)}</b>`)}
    </div>
    <h4>Active trades (Angel positions)</h4>
    ${tbl(["Instrument", "Product", "Net qty", "Avg", "LTP", "P&L"], (acc.positions || []).map(p => `<tr><td><b>${esc(p.symbol)}</b></td><td>${esc(p.product)}</td><td class="num ${cls(p.netqty)}">${nf(p.netqty, 0)}</td><td class="num">${nf(p.avg || p.buy_avg || p.sell_avg)}</td><td class="num">${nf(p.ltp)}</td><td class="num ${cls(p.pnl)}"><b>${money(p.pnl)}</b></td></tr>`).join(""), "No positions")}
    <h4>Portfolio (holdings)</h4>
    ${tbl(["Share", "Qty", "Avg", "LTP", "Invested", "Value", "P&L"], (acc.holdings || []).map(h => `<tr><td><b>${esc(h.sym)}</b></td><td class="num">${nf(h.qty, 0)}</td><td class="num">${nf(h.avg)}</td><td class="num">${nf(h.ltp)}</td><td class="num">${money(h.invested)}</td><td class="num">${money(h.value)}</td><td class="num ${cls(h.pnl)}"><b>${money(h.pnl)}</b> (${sgn(h.pnl_pct)}%)</td></tr>`).join(""), "No holdings")}
    <h4>Today's orders</h4>
    ${tbl(["Instrument", "Side", "Qty", "Price", "Product", "Status", "Time"], (acc.orders || []).map(o => `<tr><td><b>${esc(o.symbol)}</b></td><td class="${o.side === "BUY" ? "up" : "down"}">${esc(o.side)}</td><td class="num">${nf(o.filled, 0)}/${nf(o.qty, 0)}</td><td class="num">${nf(o.avg || o.price)}</td><td>${esc(o.product)}</td><td>${esc(o.status)}</td><td class="muted">${esc(o.time || "")}</td></tr>`).join(""), "No orders")}
    <h4>TradeLens journal (${d.trades.length})</h4>
    ${tbl(["Date", "Share", "Side", "Type", "Qty", "Entry", "SL", "T1", "Status", "Now / exit", "Net P&L"], d.trades.map(x => { const lv = x.live || {}; return `<tr><td class="muted">${dstr(x.created_at)}</td><td><b>${esc(x.symbol)}</b> ${x.segment === "option" ? esc((x.opt_strike || "") + " " + (x.opt_type || "")) : ""}</td><td>${esc(x.side)}</td><td>${esc(x.segment)}</td><td class="num">${esc(x.qty)}</td><td class="num">${nf(+x.entry)}</td><td class="num">${x.sl ? nf(+x.sl) : "–"}</td><td class="num">${x.t1 ? nf(+x.t1) : "–"}</td><td>${esc(x.status)}</td><td class="num">${nf(lv.price)}</td><td class="num ${cls(lv.pnl?.net)}"><b>${lv.pnl ? money(lv.pnl.net) : "–"}</b></td></tr>`; }).join(""), "No trades logged")}
    <h4>Volatile Watchlist (${d.watchlist.length})</h4><div class="chips">${d.watchlist.map(s => `<span>${esc(s)}</span>`).join("")}</div>
    <h4>Price alerts (${d.price_alerts.length})</h4><div class="chips">${d.price_alerts.map(p => `<span>${esc(p.sym)} ${p.op === "above" ? "▲" : "▼"} ${nf(p.price)}${p.done ? " ✓" : ""}</span>`).join("") || '<span class="muted">none</span>'}</div>
  </div>`;
}
$("#adDetail").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  const act = b.dataset.act, uid = S.adSel;
  const msg = { delete: "Delete this user and ALL their data (trades, watchlist, alerts)? This can't be undone.", disable: "Disable this user? They are signed out immediately.",
    reset_password: "Reset this user's password? They are signed out everywhere and get a temporary password.", data_source: "Use this user's Angel API to power live prices for everyone? TradeLens restarts (about 1 minute)." }[act];
  if (msg && !confirm(msg)) return;
  try {
    const r = await api("/api/admin/user/" + uid, { method: "POST", body: JSON.stringify({ action: act }) });
    if (r.temp_password) { $("#adTemp").innerHTML = `<div class="tempbox">Temporary password: <b>${esc(r.temp_password)}</b><br>${esc(r.note)} It won't be shown again.</div>`; return; }
    if (r.deleted) { S.adSel = null; $("#adDetail").innerHTML = ""; }
    if (r.restarting) toast("Switching live prices to this user's API. TradeLens is restarting…", "eod");
    else if (r.note) toast(r.note, "eod");
    loadAdmin();
  } catch (err) { toast(err.message, "sl_hit"); }
});

// ---------------------------------------------------------------- GRID VIEW: one live card per share
try { S.layout = localStorage.getItem("tl_layout") || "list"; } catch (e) { S.layout = "list"; }
S.cardEls = {}; S.cardData = {}; S.cardFetched = {}; S.visible = new Set(); S.gridBias = "all";
function setLayout(l) {
  S.layout = l;
  try { localStorage.setItem("tl_layout", l); } catch (e) {}
  $$("#layoutSeg button").forEach(b => b.classList.toggle("on", b.dataset.l === l));
  renderBoard();
  if (l === "grid") setTimeout(fetchCards, 50);
}
$$("#layoutSeg button").forEach(b => b.addEventListener("click", () => setLayout(b.dataset.l)));
$$("#layoutSeg button").forEach(b => b.classList.toggle("on", b.dataset.l === S.layout));
$("#gridFilter").addEventListener("input", () => renderBoard());
$("#gridSort").addEventListener("change", () => renderBoard());
$$("#gridBias button").forEach(b => b.addEventListener("click", () => {
  S.gridBias = b.dataset.b; $$("#gridBias button").forEach(x => x.classList.toggle("on", x === b)); renderBoard();
}));
$("#addShareBtn2").addEventListener("click", () => openAdd());

const cardObserver = new IntersectionObserver((ents) => {
  let added = false;
  ents.forEach(e => { const sym = e.target.dataset.card; if (e.isIntersecting) { if (!S.visible.has(sym)) added = true; S.visible.add(sym); } else S.visible.delete(sym); });
  if (added) { clearTimeout(S.cardT); S.cardT = setTimeout(fetchCards, 250); }
}, { rootMargin: "300px" });

function cardSkeleton(sym) {
  const el = document.createElement("div");
  el.className = "scard"; el.dataset.card = sym; el.dataset.sym = sym;
  el.innerHTML = `<div class="top"><div class="badge2">${esc(sym.replace(/[^A-Z0-9]/g, "").slice(0, 2))}</div>
    <div class="nm"><b>${esc(sym)}</b><small class="sec"></small></div><canvas class="spark"></canvas></div>
    <div class="px"><b class="p">–</b><span class="c"></span></div>
    <div class="kv2">
      <div><span>Rank</span><b class="rk">–</b></div><div><span>Conv</span><b class="cv"></b></div>
      <div><span>VWAP</span><b class="vw">–</b></div><div><span>OB zone</span><b class="ob">–</b></div>
      <div><span>R1 / R2</span><b class="r1">–</b></div><div><span>S1 / S2</span><b class="s1">–</b></div>
      <div><span>R : R</span><b class="rr">–</b></div><div><span>Signal</span><b class="sigt">–</b></div>
    </div>
    <canvas class="mini"></canvas>
    ${S.board?.view === "watchlist" ? `<button class="btn sm rmx" data-rm="${esc(sym)}" title="Remove from watchlist">✕</button>` : ""}`;
  cardObserver.observe(el);
  return el;
}
function renderGrid() {
  const b = S.board; if (!b) return;
  const f = $("#gridFilter").value.trim().toUpperCase();
  const rankBull = {}, rankBear = {};
  b.bulls.forEach((r, i) => rankBull[r.sym] = i + 1);
  b.bears.forEach((r, i) => rankBear[r.sym] = i + 1);
  let rows = b.rows.filter(r => !f || r.sym.includes(f) || (r.sector || "").toUpperCase().includes(f));
  if (S.gridBias === "bull") rows = rows.filter(r => r.direction > 0 && !r.choppy);
  if (S.gridBias === "bear") rows = rows.filter(r => r.direction < 0 && !r.choppy);
  if (S.gridBias === "signal") rows = rows.filter(r => ["BUY", "SELL"].includes(S.cardData[r.sym]?.sig?.action));
  const k = $("#gridSort").value;
  rows.sort((a, z) => k === "sym" ? a.sym.localeCompare(z.sym) : k === "strength" ? (z.strength - a.strength) : k === "chg" ? (z.chg - a.chg) : (z[k] - a[k]));
  $("#gridCount").textContent = `${rows.length} of ${b.rows.length} shares`;
  const box = $("#gridBox");
  const keep = new Set(rows.map(r => r.sym));
  Object.keys(S.cardEls).forEach(sym => { if (!keep.has(sym) || S.cardEls[sym].dataset.view !== b.view) { cardObserver.unobserve(S.cardEls[sym]); S.cardEls[sym].remove(); delete S.cardEls[sym]; S.visible.delete(sym); } });
  rows.forEach((r, i) => {
    let el = S.cardEls[r.sym];
    if (!el) { el = S.cardEls[r.sym] = cardSkeleton(r.sym); el.dataset.view = b.view; }
    if (box.children[i] !== el) box.insertBefore(el, box.children[i] || null);
    updateCard(el, r, rankBull[r.sym] ? `#${rankBull[r.sym]} bullish` : rankBear[r.sym] ? `#${rankBear[r.sym]} bearish` : r.choppy ? "choppy" : "–");
  });
  if (!rows.length) box.innerHTML = `<div class="panel empty" style="grid-column:1/-1">${f ? "No share matches “" + esc(f) + "”." : "Loading…"}</div>`;
  else { const e = box.querySelector(".empty"); if (e) e.remove(); }
}
function updateCard(el, r, rank) {
  const dir = r.choppy ? "" : r.direction > 0 ? "bull" : r.direction < 0 ? "bear" : "";
  el.classList.toggle("bull", dir === "bull"); el.classList.toggle("bear", dir === "bear");
  const pEl = el.querySelector(".p"), prev = +(el.dataset.ltp || 0);
  if (prev && r.ltp !== prev) { el.classList.remove("flash-up", "flash-down"); void el.offsetWidth; el.classList.add(r.ltp > prev ? "flash-up" : "flash-down"); setTimeout(() => el.classList.remove("flash-up", "flash-down"), 700); }
  el.dataset.ltp = r.ltp;
  pEl.textContent = "₹" + nf(r.ltp);
  const c = el.querySelector(".c"); c.className = "c " + cls(r.chg); c.textContent = `${sgn(r.chg)}% · ${sgn(r.ltp - r.prev_close)}`;
  el.querySelector(".sec").textContent = `${r.sector || ""} · vol ${nf(r.vol_ratio, 1)}×`;
  el.querySelector(".rk").textContent = rank;
  const dots = Math.round((r.strength || 0) / 20);
  el.querySelector(".cv").innerHTML = `${nf(r.strength, 0)} <span class="dots">${[0, 1, 2, 3, 4].map(i => `<i class="${i < dots ? "on" : ""}"></i>`).join("")}</span>`;
  const d = S.cardData[r.sym];
  if (d) fillCard(el, d, r);
}
function fillCard(el, d, r) {
  const sg = d.sig || {};
  el.querySelector(".vw").textContent = d.vwap_now ? nf(d.vwap_now) : "–";
  const ob = (d.obs || []).find(o => o.type === (r?.direction >= 0 ? "bull" : "bear")) || (d.obs || [])[0];
  const dp = (ob && ob.top >= 1000) ? 0 : 2;
  el.querySelector(".ob").textContent = ob ? `${nf(ob.bottom, dp)}–${nf(ob.top, dp)}` : "–";
  el.querySelector(".r1").textContent = d.R.length ? d.R.slice(0, 2).map(x => nf(x)).join(" · ") : "–";
  el.querySelector(".s1").textContent = d.S.length ? d.S.slice(0, 2).map(x => nf(x)).join(" · ") : "–";
  el.querySelector(".rr").textContent = sg.rr1 ? "1 : " + nf(sg.rr1, 1) : "–";
  const st = el.querySelector(".sigt"); st.className = "sigt " + (sg.action || ""); st.textContent = sg.action || "–";
  st.title = sg.summary || "";
  drawMini(el.querySelector("canvas.mini"), d);
  drawSpark(el.querySelector("canvas.spark"), d, r);
}
function sizeCanvas(cv) {
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return null;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  return { g, W, H };
}
function drawSpark(cv, d, r) {
  const s = sizeCanvas(cv); if (!s || !d.candles.length) return;
  const { g, W, H } = s, P = TC(), cl = d.candles.map(c => c[4]);
  const lo = Math.min(...cl), hi = Math.max(...cl), up = (r?.chg ?? 0) >= 0, col = up ? P.up : P.down;
  const X = i => i / Math.max(1, cl.length - 1) * (W - 6) + 2, Y = v => 3 + (hi - v) / ((hi - lo) || 1) * (H - 6);
  g.beginPath(); cl.forEach((v, i) => i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)));
  g.strokeStyle = col; g.lineWidth = 1.4; g.stroke();
  g.lineTo(X(cl.length - 1), H); g.lineTo(X(0), H); g.closePath(); g.fillStyle = up ? P.upA(.12) : P.downA(.12); g.fill();
  g.beginPath(); g.arc(X(cl.length - 1), Y(cl[cl.length - 1]), 2.4, 0, 7); g.fillStyle = col; g.fill();
}
function drawMini(cv, d) {
  const s = sizeCanvas(cv); if (!s) return;
  const { g, W, H } = s, P = TC(), cs = d.candles;
  if (cs.length < 2) { g.fillStyle = P.text; g.font = "11px IBM Plex Sans, sans-serif"; g.fillText("Collecting today's candles…", 10, H / 2); return; }
  const lv = [...d.S, ...d.R].filter(Boolean);
  let lo = Math.min(...cs.map(c => c[3])), hi = Math.max(...cs.map(c => c[2]));
  const span = hi - lo || 1;
  lv.forEach(v => { if (v > lo - span * .5 && v < hi + span * .5) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
  const pad = (hi - lo) * .06; lo -= pad; hi += pad;
  const right = 56, bottom = 14;
  const open0 = Math.floor((cs[0][0] + IST) / 86400) * 86400 - IST + 33300;
  const lastSlot = (cs[cs.length - 1][0] - open0) / 300;
  const slots = Math.min(75, Math.max(24, Math.ceil(lastSlot + 6))), step = (W - right - 6) / slots;
  const X = t => 4 + ((t - open0) / 300 + .5) * step, Y = v => 4 + (hi - v) / (hi - lo) * (H - bottom - 8);
  g.font = "9.5px JetBrains Mono, monospace"; g.textBaseline = "middle";
  // order-block zones
  (d.obs || []).forEach(o => {
    const x0 = Math.max(4, X(Math.max(o.t, open0))), y0 = Y(o.top), y1 = Y(o.bottom);
    g.fillStyle = o.type === "bull" ? P.upA(.14) : P.downA(.14); g.fillRect(x0, y0, W - right - x0, Math.max(2, y1 - y0));
    g.strokeStyle = o.type === "bull" ? P.upA(.6) : P.downA(.6); g.strokeRect(x0, y0, W - right - x0, Math.max(2, y1 - y0));
  });
  // support / resistance
  const lvl = (v, lab, col) => { const y = Y(v); if (y < 2 || y > H - bottom) return; g.setLineDash([3, 3]); g.strokeStyle = col; g.globalAlpha = .7;
    g.beginPath(); g.moveTo(4, y); g.lineTo(W - right, y); g.stroke(); g.setLineDash([]); g.globalAlpha = 1; g.fillStyle = col; g.fillText(`${lab} ${nf(v)}`, W - right + 3, y); };
  d.S.forEach((v, i) => lvl(v, "S" + (i + 1), P.warn));
  d.R.forEach((v, i) => lvl(v, "R" + (i + 1), P.accent));
  // vwap
  g.setLineDash([4, 3]); g.strokeStyle = P.accent; g.globalAlpha = .75; g.beginPath(); let on = false;
  d.vwap.forEach((v, i) => { if (v == null) return; const x = X(cs[i][0]), y = Y(v); on ? g.lineTo(x, y) : g.moveTo(x, y); on = true; });
  g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
  // candles
  const bw = Math.max(1.5, step * .62);
  cs.forEach(c => { const up = c[4] >= c[1], col = up ? P.up : P.down, x = X(c[0]);
    g.strokeStyle = col; g.beginPath(); g.moveTo(x, Y(c[2])); g.lineTo(x, Y(c[3])); g.stroke();
    g.fillStyle = col; g.fillRect(x - bw / 2, Math.min(Y(c[1]), Y(c[4])), bw, Math.max(1, Math.abs(Y(c[1]) - Y(c[4])))); });
  // live price dot
  const last = cs[cs.length - 1], lx = X(last[0]), ly = Y(last[4]);
  g.beginPath(); g.arc(lx, ly, 5, 0, 7); g.fillStyle = P.light ? "rgba(26,115,217,.18)" : "rgba(255,255,255,.18)"; g.fill();
  g.beginPath(); g.arc(lx, ly, 2.6, 0, 7); g.fillStyle = P.fg; g.fill();
  // hours
  g.fillStyle = P.dim;
  const every = slots > 50 ? 3600 : 1800;
  for (let t = open0 - 33300 + 9 * 3600 + 1800; t <= open0 - 33300 + 15.5 * 3600; t += every) { const x = X(t); if (x > 14 && x < W - right - 10) {
    const d = new Date((t + IST) * 1000); g.fillText(`${d.getUTCHours()}:${String(d.getUTCMinutes()).padStart(2, "0")}`, x - 12, H - 6); } }
}
async function fetchCards() {
  if (S.tab !== "boards" || S.layout !== "grid" || S.sym) return;
  const now = Date.now();
  const need = [...S.visible].filter(s => S.cardEls[s] && now - (S.cardFetched[s] || 0) > 9000).slice(0, 40);
  if (!need.length) return;
  need.forEach(s => S.cardFetched[s] = now);
  try {
    const list = await api("/api/grid?syms=" + encodeURIComponent(need.join(",")));
    const rows = Object.fromEntries((S.board?.rows || []).map(r => [r.sym, r]));
    list.forEach(d => { S.cardData[d.sym] = d; const el = S.cardEls[d.sym]; if (el) fillCard(el, d, rows[d.sym]); });
  } catch (e) {}
}
setInterval(fetchCards, 3000);
function redrawCards() {
  const rows = Object.fromEntries((S.board?.rows || []).map(r => [r.sym, r]));
  S.visible.forEach(sym => { const el = S.cardEls[sym], d = S.cardData[sym]; if (el && d) fillCard(el, d, rows[sym]); });
}
window.addEventListener("resize", () => { clearTimeout(S.rzT); S.rzT = setTimeout(() => { redrawCards(); if (S.flow) drawFlow(); if (S.wide && S.tab === "wide") drawWide(); }, 200); });
$("#gridBox").addEventListener("click", (e) => {
  if (e.target.closest("[data-rm]")) return;
  const c = e.target.closest("[data-card]"); if (c) openDetail(c.dataset.card);
});

// ---------------------------------------------------------------- MARKET FLOW (tree view)
S.flowView = "watchlist";
$$("#flowSeg button").forEach(b => b.addEventListener("click", () => {
  S.flowView = b.dataset.v; $$("#flowSeg button").forEach(x => x.classList.toggle("on", x === b)); loadFlow();
}));
async function loadFlow() {
  try { S.flow = await api("/api/flow?view=" + S.flowView); renderFlow(); } catch (e) {}
}
setInterval(() => { if (S.tab === "flow" && !S.sym) loadFlow(); }, 5000);
function vbarsCanvas(cv, vb) {
  const s = sizeCanvas(cv); if (!s) return;
  const { g, W, H } = s, P = TC(), n = Math.max(vb.length, 1), w = W / 24;
  vb.forEach((v, i) => { const h = Math.max(1, Math.abs(v) * (H - 2)); g.fillStyle = v >= 0 ? P.upA(.85) : P.downA(.85); g.fillRect(i * w + (24 - n) * w, H - h, Math.max(1, w - 1), h); });
}
function renderFlow() {
  const f = S.flow; if (!f) return;
  $("#flowLead").innerHTML = f.leading ? `Leading <b>${esc(f.leading.sector)}</b> <span class="${cls(f.leading.chg)}">${sgn(f.leading.chg)}%</span>` : "";
  $("#flowLag").innerHTML = f.lagging ? ` · Lagging <b>${esc(f.lagging.sector)}</b> <span class="${cls(f.lagging.chg)}">${sgn(f.lagging.chg)}%</span>` : "";
  $("#flowBull").textContent = "▲ " + f.bull_count; $("#flowBear").textContent = "▼ " + f.bear_count;
  const maxAbs = Math.max(0.5, ...f.sectors.map(x => Math.abs(x.chg)));
  $("#flowSectors").innerHTML = f.sectors.map(x => `<div class="row ${S.flowSector === x.sector ? "on" : ""}" data-sec="${esc(x.sector)}"><b>${esc(x.sector)}</b><span class="num ${cls(x.chg)}">${sgn(x.chg)}%</span>
    <div class="bb"><i style="width:${x.adv / x.n * 100}%;background:var(--up)"></i><i style="width:${x.dec / x.n * 100}%;background:var(--down)"></i></div></div>`).join("");
  const by = Object.fromEntries(f.items.map(i => [i.sym, i]));
  const card = (sym, i) => { const it = by[sym]; return `<div class="fcard" data-fsym="${esc(sym)}"><b>${esc(sym)}</b><span class="${cls(it.chg)}">${sgn(it.chg)}%</span><em>${String(i + 1).padStart(2, "0")}</em><canvas></canvas></div>`; };
  $("#flowBulls").innerHTML = f.bulls.map(card).join("") || '<span class="muted" style="font-size:12px">No strong buying yet</span>';
  $("#flowBears").innerHTML = f.bears.map(card).join("") || '<span class="muted" style="font-size:12px">No strong selling yet</span>';
  $$(".fcard").forEach(el => vbarsCanvas(el.querySelector("canvas"), by[el.dataset.fsym].vbars));
  drawFlow();
}
$("#flowSectors").addEventListener("click", (e) => {
  const r = e.target.closest("[data-sec]"); if (!r) return;
  S.flowSector = S.flowSector === r.dataset.sec ? null : r.dataset.sec; renderFlow();
});
$("#tab-flow").addEventListener("click", (e) => { const c = e.target.closest("[data-fsym]"); if (c) openDetail(c.dataset.fsym); });
const fy = (v, H) => { const sgnv = v >= 0 ? 1 : -1, t = Math.log1p(Math.abs(v) / 0.35) / Math.log1p(6 / 0.35); return H / 2 - sgnv * Math.min(1, t) * (H / 2 - 18); };
function drawFlow(hover) {
  const f = S.flow, cv = $("#flowCanvas"); if (!f || !cv) return;
  const s = sizeCanvas(cv); if (!s) return;
  const { g, W, H } = s, P = TC(), right = 70, slots = Math.min(f.slots, Math.max(18, f.now_slot + 4));
  S.flowSlots = slots;
  const X = (k) => 34 + k / slots * (W - right - 40);
  g.font = "10px JetBrains Mono, monospace"; g.textBaseline = "middle";
  // scale
  [-5, -3, -2, -1, -0.5, 0, 0.5, 1, 2, 3, 5].forEach(v => { const y = fy(v, H); g.strokeStyle = v === 0 ? P.dim : P.grid; g.lineWidth = v === 0 ? 1.2 : 1;
    g.beginPath(); g.moveTo(30, y); g.lineTo(W - right + 4, y); g.stroke(); g.fillStyle = P.dim; g.fillText((v > 0 ? "+" : "") + v, 2, y); });
  const stepMin = slots > 50 ? 60 : 30;
  for (let m = 15 + stepMin; m <= 375; m += stepMin) { const k = (m - 0) / 5 - 3; if (k > slots) break; const x = X(k);
    const hh = 9 + Math.floor((m + 0) / 60), mm = (m) % 60; g.fillStyle = P.dim; g.fillText(`${hh}:${String(mm).padStart(2, "0")}`, x - 14, H - 6);
    g.strokeStyle = P.grid; g.beginPath(); g.moveTo(x, 10); g.lineTo(x, H - 14); g.stroke(); }
  const nowX = X(f.now_slot + 1); g.strokeStyle = P.accent; g.globalAlpha = .5; g.setLineDash([3, 4]); g.beginPath(); g.moveTo(nowX, 10); g.lineTo(nowX, H - 14); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
  // paths
  const hot = new Set([...f.bulls.slice(0, 6), ...f.bears.slice(0, 6)]);
  const items = f.items.slice().sort((a, b) => (hot.has(a.sym) ? 1 : 0) - (hot.has(b.sym) ? 1 : 0));
  S.flowPts = [];
  items.forEach(it => {
    if (!it.path.length) return;
    const pos = it.chg >= 0, inSec = !S.flowSector || it.sector === S.flowSector, isHover = hover === it.sym;
    g.beginPath(); g.moveTo(X(0), fy(0, H));
    it.path.forEach(([k, v]) => g.lineTo(X(k + 1), fy(v, H)));
    g.strokeStyle = pos ? P.up : P.down;
    g.globalAlpha = isHover ? 1 : !inSec ? .05 : hot.has(it.sym) ? .85 : S.flowSector ? .7 : .22;
    g.lineWidth = isHover ? 2.6 : hot.has(it.sym) || S.flowSector ? 1.5 : 1;
    g.stroke();
    const [k, v] = it.path[it.path.length - 1];
    S.flowPts.push({ sym: it.sym, x: X(k + 1), y: fy(v, H), chg: it.chg, sector: it.sector, path: it.path });
  });
  g.globalAlpha = 1;
  // split brackets at the right: bullish above zero, bearish below
  const bx = W - right + 14, y0 = fy(0, H);
  g.fillStyle = P.upA(.14); g.fillRect(bx, 14, 18, y0 - 16); g.fillStyle = P.downA(.14); g.fillRect(bx, y0 + 2, 18, H - 30 - y0);
  g.fillStyle = P.up; g.font = "bold 13px JetBrains Mono, monospace"; g.fillText(String(f.bull_count), bx + 22, (14 + y0) / 2);
  g.fillStyle = P.down; g.fillText(String(f.bear_count), bx + 22, (y0 + H - 16) / 2);
  S.flowPts.forEach(p => { g.fillStyle = p.chg >= 0 ? P.up : P.down; g.globalAlpha = hot.has(p.sym) ? 1 : .45; g.fillRect(bx + 2, p.y - 1, 14 * Math.min(1, Math.abs(p.chg) / 3) + 2, 1.6); });
  g.globalAlpha = 1;
  if (hover) { const p = S.flowPts.find(q => q.sym === hover); if (p) { g.beginPath(); g.arc(p.x, p.y, 4, 0, 7); g.fillStyle = P.fg; g.fill(); } }
}
$("#flowCanvas").addEventListener("mousemove", (e) => {
  if (!S.flowPts) return;
  const r = e.target.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, H = r.height, W = r.width, right = 70;
  const k = (mx - 34) / (W - right - 40) * (S.flowSlots || S.flow.slots) - 1;
  let best = null, bd = 14;
  S.flowPts.forEach(p => { const pt = p.path.reduce((a, q) => Math.abs(q[0] - k) < Math.abs(a[0] - k) ? q : a, p.path[0]); if (!pt) return;
    const d = Math.abs(fy(pt[1], H) - my); if (d < bd) { bd = d; best = { ...p, at: pt[1] }; } });
  const h = $("#flowHint");
  if (best) { h.style.display = "block"; h.style.left = Math.min(mx + 12, W - 160) + "px"; h.style.top = (my - 10) + "px";
    h.innerHTML = `<b>${esc(best.sym)}</b> · ${esc(best.sector)} · now <span class="${cls(best.chg)}">${sgn(best.chg)}%</span>`; S.flowHover = best.sym; drawFlow(best.sym); }
  else { h.style.display = "none"; if (S.flowHover) { S.flowHover = null; drawFlow(); } }
});
$("#flowCanvas").addEventListener("mouseleave", () => { $("#flowHint").style.display = "none"; S.flowHover = null; drawFlow(); });
$("#flowCanvas").addEventListener("click", () => { if (S.flowHover) openDetail(S.flowHover); });


// ---------------------------------------------------------------- WIDE FLOW (flow lines -> split -> tiered tiles)
S.wfView = "watchlist";
$$("#wfSeg button").forEach(b => b.addEventListener("click", () => {
  S.wfView = b.dataset.v; $$("#wfSeg button").forEach(x => x.classList.toggle("on", x === b)); S.wfSector = null; loadWide();
}));
async function loadWide() {
  if (S.wfBusy) return; S.wfBusy = true;
  try { S.wide = await api("/api/wideflow?view=" + S.wfView); renderWide(); } catch (e) {} finally { S.wfBusy = false; }
}
setInterval(() => { if (S.tab === "wide" && !S.sym && !document.hidden) loadWide(); }, 3000);
$("#wfFull").addEventListener("click", () => {
  const el = $("#tab-wide");
  if (document.fullscreenElement) document.exitFullscreen(); else if (el.requestFullscreen) el.requestFullscreen();
});
document.addEventListener("fullscreenchange", () => { $("#wfFull").textContent = document.fullscreenElement ? "✕ Exit full screen" : "⛶ Full screen"; setTimeout(() => S.wide && drawWide(), 120); });

function wfTile(it, tier) {
  const dn = it.chg < 0, d = dn ? " dn" : "", dim = S.wfSector && it.sector !== S.wfSector ? " dim" : "";
  const alpha = (0.07 + Math.min(1, (it.strength || 0) / 100) * 0.28).toFixed(3);
  const st = `style="--a:${dn ? `rgba(255,92,99,${alpha})` : `rgba(31,201,138,${alpha})`}"`;
  const oi = it.oi_signal ? ` · ${esc(it.oi_signal)}` : "";
  if (tier === "small")
    return `<div class="wt s${d}${dim}" ${st} data-fsym="${esc(it.sym)}" title="${esc(it.sym)} · ${esc(it.sector)} · ${sgn(it.chg)}%"><b>${esc(it.sym)}</b><span>${sgn(it.chg)}%</span><canvas data-vb></canvas></div>`;
  if (tier === "mid")
    return `<div class="wt m${d}${dim}" ${st} data-fsym="${esc(it.sym)}"><div class="h"><b>${esc(it.sym)}</b><em>#${it.rank}</em></div>
      <div class="pc">${sgn(it.chg)}%</div><div class="sub">₹${nf(it.ltp)}${oi}</div><canvas data-sp></canvas></div>`;
  const c = it.card || {}, lv = (k, v) => `<div>${k}<b>${v == null ? "–" : v}</b></div>`;
  const zone = c.zone ? `${nf(c.zone[0])}–${nf(c.zone[1])}` : null;
  const S1 = (c.S || [])[0], R1 = (c.R || [])[0], R2 = (c.R || [])[1];
  const nz = (v) => v == null ? null : nf(v, Math.abs(v) >= 1000 ? 0 : 2);
  const zone2 = c.zone ? `${nz(c.zone[0])}–${nz(c.zone[1])}` : null;
  const act = c.action ? `<span class="tag ${c.action.startsWith("BUY") ? "up" : c.action.startsWith("SELL") ? "down" : ""}">${esc(c.action)}</span>` : "";
  return `<div class="wt b${d}${dim}" data-fsym="${esc(it.sym)}">
    <div class="info">
      <div class="h"><b>${esc(it.sym)}</b><span class="tagc">${dn ? "BEARISH" : "BULLISH"}</span><span class="ring" style="--p:${Math.round(it.strength || 0)}" title="Strength"><span>${Math.round(it.strength || 0)}</span></span></div>
      <div class="pc">${sgn(it.chg)}%</div>
      <div class="px">${act}₹${nf(it.ltp)} ${sgn(it.ab_chg)}${oi} · #${it.rank} ${esc(it.sector)} · strength ${Math.round(it.strength || 0)}</div>
      <div class="lvl">${lv(dn ? "Resist 1" : "Support 1", nz(dn ? R1 : S1))}${lv("Zone", zone2)}${lv(dn ? "Support 1" : "Resist 1", nz(dn ? S1 : R1))}
        ${lv(dn ? "Support 2" : "Resist 2", nz(dn ? (c.S || [])[1] : R2))}${lv("VWAP", it.vwap ? nz(it.vwap) : null)}${lv("Risk:reward", c.rr ? "1:" + nf(c.rr, 1) : null)}</div>
    </div>
    <canvas data-ch></canvas></div>`;
}
function renderWide() {
  const f = S.wide; if (!f) return;
  $("#wfLead").innerHTML = f.leading ? `Leading <b>${esc(f.leading.sector)}</b> <span class="${cls(f.leading.chg)}">${sgn(f.leading.chg)}%</span>` : "";
  $("#wfLag").innerHTML = f.lagging ? ` · Lagging <b>${esc(f.lagging.sector)}</b> <span class="${cls(f.lagging.chg)}">${sgn(f.lagging.chg)}%</span>` : "";
  $("#wfBull").textContent = "▲ " + f.bull_count + " bullish"; $("#wfBear").textContent = "▼ " + f.bear_count + " bearish";
  $("#wfTime").textContent = tstr(f.ts);
  $("#wfSectors").innerHTML = f.sectors.map(x => `<div class="row ${S.wfSector === x.sector ? "on" : ""}" data-sec="${esc(x.sector)}"><b>${esc(x.sector)}</b><span class="num ${cls(x.chg)}">${sgn(x.chg)}%</span>
    <div class="bb"><i style="width:${x.adv / x.n * 100}%;background:var(--up)"></i><i style="width:${(x.n - x.adv - x.dec) / x.n * 100}%"></i><i style="width:${x.dec / x.n * 100}%;background:var(--down)"></i></div></div>`).join("");
  const by = S.wfBy = Object.fromEntries(f.items.map(i => [i.sym, i]));
  const fill = (side, list) => {
    const its = list.map(s => by[s]).filter(Boolean);
    const big = its.filter(i => i.tier === "big"), mid = its.filter(i => i.tier === "mid"), small = its.filter(i => i.tier === "small");
    // mirrored halves: bullish strongest at the top, bearish strongest at the bottom; weakest meet at the middle line
    const sm = side === "Bear" ? small.slice().reverse() : small.slice();
    $(`#wf${side}S`).innerHTML = sm.map(i => wfTile(i, "small")).join("") || "";
    const m = side === "Bear" ? mid.slice().reverse() : mid, b = side === "Bear" ? big.slice().reverse() : big;
    $(`#wf${side}M`).innerHTML = m.map(i => wfTile(i, "mid")).join("");
    $(`#wf${side}B`).innerHTML = b.map(i => wfTile(i, "big")).join("") || `<div class="wf-empty">No ${side === "Bull" ? "bullish" : "bearish"} shares right now</div>`;
  };
  fill("Bull", f.bull_list); fill("Bear", f.bear_list);
  requestAnimationFrame(drawWide);
}
function drawWide(hover) {
  const f = S.wide; if (!f || S.tab !== "wide") return;
  drawWideLines(hover);
  $$("#wf .wt").forEach(el => {
    const it = S.wfBy[el.dataset.fsym]; if (!it) return;
    const vb = el.querySelector("canvas[data-vb]"), sp = el.querySelector("canvas[data-sp]"), ch = el.querySelector("canvas[data-ch]");
    if (vb) wfBars(vb, it.vbars);
    if (sp) wfSpark(sp, it);
    if (ch) wfChart(ch, it);
  });
  drawWideLinks();
}
function wfBars(cv, vb) {
  const s = sizeCanvas(cv); if (!s || !vb) return;
  const { g, W, H } = s, P = TC(), n = vb.length || 1, w = W / Math.max(n, 12);
  vb.forEach((v, i) => { const h = Math.max(1, Math.abs(v) * H); g.fillStyle = v >= 0 ? P.upA(.9) : P.downA(.9); g.fillRect(W - (n - i) * w, H - h, Math.max(1, w - .6), h); });
}
function wfSpark(cv, it) {
  const s = sizeCanvas(cv); if (!s) return;
  const { g, W, H } = s, P = TC(), vb = it.vbars || [], n = vb.length || 1, w = W / Math.max(n, 12);
  vb.forEach((v, i) => { const h = Math.max(1, Math.abs(v) * H * .45); g.fillStyle = v >= 0 ? P.upA(.45) : P.downA(.45); g.fillRect(W - (n - i) * w, H - h, Math.max(1, w - .8), h); });
  const p = it.path || []; if (p.length < 2) return;
  const vals = p.map(q => q[1]), lo = Math.min(0, ...vals), hi = Math.max(0, ...vals), rg = (hi - lo) || 1;
  const X = (i) => i / (p.length - 1) * (W - 2) + 1, Y = (v) => H - 3 - (v - lo) / rg * (H - 6);
  g.strokeStyle = P.dim; g.globalAlpha = .5; g.setLineDash([2, 3]); g.beginPath(); g.moveTo(0, Y(0)); g.lineTo(W, Y(0)); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
  g.beginPath(); vals.forEach((v, i) => i ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)));
  g.strokeStyle = it.chg >= 0 ? P.up : P.down; g.lineWidth = 1.4; g.stroke();
}
function wfChart(cv, it) {
  const s = sizeCanvas(cv); if (!s) return;
  const { g, W, H } = s, P = TC(), c = it.card || {}, cs = c.candles || [];
  if (cs.length < 2) { g.fillStyle = P.dim; g.font = "10px JetBrains Mono, monospace"; g.fillText("waiting for candles…", 4, H / 2); return; }
  const lv = [...(c.S || []), ...(c.R || [])].filter(Boolean);
  let lo = Math.min(...cs.map(q => q[3]), ...lv), hi = Math.max(...cs.map(q => q[2]), ...lv);
  (c.obs || []).forEach(o => { lo = Math.min(lo, o.bottom); hi = Math.max(hi, o.top); });
  const pad = (hi - lo) * .06 || 1; lo -= pad; hi += pad;
  const right = 40, Y = (v) => 4 + (hi - v) / (hi - lo) * (H - 8), w = (W - right) / cs.length, X = (i) => i * w + w / 2;
  (c.obs || []).forEach(o => { const bull = o.kind ? o.kind === "bull" : o.type !== "bear"; g.fillStyle = bull ? P.upA(.16) : P.downA(.16);
    g.fillRect(0, Y(o.top), W - right, Math.max(2, Y(o.bottom) - Y(o.top))); });
  g.font = "9px JetBrains Mono, monospace"; g.textBaseline = "middle";
  const lab = (v, col, t) => { const y = Y(v); g.strokeStyle = col; g.globalAlpha = .7; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(0, y); g.lineTo(W - right, y); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
    g.fillStyle = col; g.fillText(t, W - right + 3, y); };
  (c.S || []).forEach((v, i) => v && lab(v, P.up, "S" + (i + 1)));
  (c.R || []).forEach((v, i) => v && lab(v, P.down, "R" + (i + 1)));
  const vw = (c.vwap || []).slice(-cs.length);
  g.strokeStyle = "#4fb3ff"; g.lineWidth = 1; g.globalAlpha = .8; g.beginPath(); let st = false;
  vw.forEach((v, i) => { if (v == null) return; st ? g.lineTo(X(i), Y(v)) : g.moveTo(X(i), Y(v)); st = true; }); g.stroke(); g.globalAlpha = 1;
  cs.forEach((q, i) => { const up = q[4] >= q[1], x = X(i); g.strokeStyle = g.fillStyle = up ? P.up : P.down;
    g.beginPath(); g.moveTo(x, Y(q[2])); g.lineTo(x, Y(q[3])); g.stroke();
    const y1 = Y(Math.max(q[1], q[4])), y2 = Y(Math.min(q[1], q[4])); g.fillRect(x - Math.max(1, w * .32), y1, Math.max(1.5, w * .64), Math.max(1, y2 - y1)); });
  const last = cs[cs.length - 1][4], y = Y(last); g.fillStyle = it.chg >= 0 ? P.up : P.down; g.fillRect(W - right + 1, y - 7, right - 1, 14);
  g.fillStyle = P.onPrice; g.font = "bold 9px JetBrains Mono, monospace"; g.fillText(nf(last), W - right + 3, y);
}
function drawWideLines(hover) {
  const f = S.wide, cv = $("#wfLines"); if (!f || !cv) return;
  const s = sizeCanvas(cv); if (!s) return;
  const { g, W, H } = s, P = TC(), barW = 12, barX = W - barW - 4, slots = Math.min(f.slots, Math.max(18, f.now_slot + 3));
  const L = 30, R = barX - 34, X = (k) => L + k / slots * (R - L);
  g.font = "9px JetBrains Mono, monospace"; g.textBaseline = "middle";
  [-3, -2, -1, 0, 1, 2, 3].forEach(v => { const y = fy(v, H); g.strokeStyle = v === 0 ? P.dim : P.grid; g.globalAlpha = v === 0 ? .8 : 1;
    g.beginPath(); g.moveTo(L - 4, y); g.lineTo(R, y); g.stroke(); g.globalAlpha = 1; g.fillStyle = P.dim; g.fillText((v > 0 ? "+" : "") + v + "%", 0, y); });
  for (let m = 75; m <= 375; m += 60) { const k = m / 5 - 3; if (k > slots) break; const x = X(k); g.fillStyle = P.dim; g.fillText(`${9 + Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`, x - 12, H - 6); }
  // split bar: bullish share of the list on top, bearish below
  const tot = Math.max(1, f.bull_count + f.bear_count), top = 14, bot = H - 18, mid = top + (bot - top) * f.bull_count / tot;
  S.wfSplit = { x: barX + barW, top, mid, bot };
  const gr1 = g.createLinearGradient(0, top, 0, mid); gr1.addColorStop(0, P.upA(.95)); gr1.addColorStop(1, P.upA(.35));
  const gr2 = g.createLinearGradient(0, mid, 0, bot); gr2.addColorStop(0, P.downA(.35)); gr2.addColorStop(1, P.downA(.95));
  g.fillStyle = gr1; g.fillRect(barX, top, barW, Math.max(0, mid - top - 1)); g.fillStyle = gr2; g.fillRect(barX, mid + 1, barW, Math.max(0, bot - mid - 1));
  g.save(); g.font = "bold 13px JetBrains Mono, monospace"; g.textAlign = "right";
  g.fillStyle = P.up; g.fillText(String(f.bull_count), barX - 4, top + 8); g.fillStyle = P.down; g.fillText(String(f.bear_count), barX - 4, bot - 8); g.restore();
  // lines: each share's path, then a curve into its slot on the split bar (ordered by current move)
  const items = f.items.filter(i => i.path.length).slice().sort((a, b) => b.chg - a.chg);
  const nB = items.filter(i => i.chg >= 0).length, nD = items.length - nB;
  const hot = new Set([...f.bull_list.slice(0, 9), ...f.bear_list.slice(0, 9)]);
  S.wfPts = [];
  let ib = 0, id = 0;
  const order = items.map(it => { const pos = it.chg >= 0; const ty = pos ? top + (mid - top) * ((ib++ + .5) / Math.max(1, nB)) : mid + (bot - mid) * ((id++ + .5) / Math.max(1, nD)); return [it, ty]; });
  order.sort((a, b) => (hot.has(a[0].sym) ? 1 : 0) - (hot.has(b[0].sym) ? 1 : 0));
  order.forEach(([it, ty]) => {
    const pos = it.chg >= 0, inSec = !S.wfSector || it.sector === S.wfSector, isH = hover === it.sym;
    g.beginPath(); g.moveTo(X(0), fy(0, H));
    it.path.forEach(([k, v]) => g.lineTo(X(k + 1), fy(v, H)));
    const [k, v] = it.path[it.path.length - 1], ex = X(k + 1), ey = fy(v, H);
    g.bezierCurveTo(ex + (barX - ex) * .5, ey, ex + (barX - ex) * .5, ty, barX, ty);
    g.strokeStyle = pos ? P.up : P.down;
    g.globalAlpha = isH ? 1 : !inSec ? .04 : hot.has(it.sym) ? .8 : S.wfSector ? .65 : .2;
    g.lineWidth = isH ? 2.4 : hot.has(it.sym) || S.wfSector ? 1.3 : .8; g.stroke();
    S.wfPts.push({ sym: it.sym, sector: it.sector, chg: it.chg, path: it.path });
  });
  g.globalAlpha = 1;
  const nowX = X(f.now_slot + 1); g.strokeStyle = P.accent; g.globalAlpha = .45; g.setLineDash([3, 4]); g.beginPath(); g.moveTo(nowX, 8); g.lineTo(nowX, H - 14); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
  S.wfGeo = { L, R, slots, H, W };
}
function drawWideLinks() {
  const cv = $("#wfLinks"), sp = S.wfSplit; if (!cv || !sp) return;
  const s = sizeCanvas(cv); if (!s) return;
  const { g } = s, P = TC(), box = $("#wf").getBoundingClientRect(), lines = $("#wfLines").getBoundingClientRect();
  const sx = lines.left - box.left + sp.x, bullY = lines.top - box.top + (sp.top + sp.mid) / 2, bearY = lines.top - box.top + (sp.mid + sp.bot) / 2;
  const hubX = sx + 22;
  [[bullY, P.up, P.upA], [bearY, P.down, P.downA]].forEach(([y, col]) => { g.strokeStyle = col; g.globalAlpha = .9; g.lineWidth = 1.6; g.beginPath(); g.moveTo(sx, y); g.lineTo(hubX, y); g.stroke();
    g.beginPath(); g.arc(hubX, y, 3, 0, 7); g.fillStyle = col; g.fill(); });
  $$("#wf .wt").forEach(el => {
    const r = el.getBoundingClientRect(); if (r.height < 4) return;
    const sc = el.closest(".wf-small"); if (sc) { const sr = sc.getBoundingClientRect(); if (r.bottom < sr.top || r.top > sr.bottom) return; }
    const dn = el.classList.contains("dn"), y0 = dn ? bearY : bullY, tx = r.left - box.left, ty = r.top - box.top + r.height / 2;
    const big = el.classList.contains("b"), mid = el.classList.contains("m"), dim = el.classList.contains("dim");
    g.strokeStyle = dn ? P.down : P.up; g.globalAlpha = dim ? .03 : big ? .55 : mid ? .32 : .09; g.lineWidth = big ? 1.4 : mid ? 1 : .6;
    g.beginPath(); g.moveTo(hubX, y0); const cx = hubX + Math.min(60, (tx - hubX) * .35); g.bezierCurveTo(cx, y0, cx, ty, tx, ty); g.stroke();
  });
  g.globalAlpha = 1;
}
$("#wfSectors").addEventListener("click", (e) => {
  const r = e.target.closest("[data-sec]"); if (!r) return;
  S.wfSector = S.wfSector === r.dataset.sec ? null : r.dataset.sec; renderWide();
});
$("#tab-wide").addEventListener("click", (e) => { const c = e.target.closest("[data-fsym]"); if (c) openDetail(c.dataset.fsym); });
$$("#wf .wf-small").forEach(el => el.addEventListener("scroll", () => { cancelAnimationFrame(S.wfRaf); S.wfRaf = requestAnimationFrame(drawWideLinks); }));
$("#wfLines").addEventListener("mousemove", (e) => {
  const G = S.wfGeo; if (!S.wfPts || !G) return;
  const r = e.target.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  const k = (mx - G.L) / (G.R - G.L) * G.slots - 1;
  let best = null, bd = 12;
  S.wfPts.forEach(p => { const pt = p.path.reduce((a, q) => Math.abs(q[0] - k) < Math.abs(a[0] - k) ? q : a, p.path[0]); if (!pt) return;
    const d = Math.abs(fy(pt[1], G.H) - my); if (d < bd) { bd = d; best = p; } });
  const h = $("#wfHint");
  if (best && mx < G.R + 10) { h.style.display = "block"; h.style.left = Math.min(mx + 12, G.W - 170) + "px"; h.style.top = (my - 10) + "px";
    h.innerHTML = `<b>${esc(best.sym)}</b> · ${esc(best.sector)} · <span class="${cls(best.chg)}">${sgn(best.chg)}%</span>`;
    if (S.wfHover !== best.sym) { S.wfHover = best.sym; drawWideLines(best.sym); } }
  else { h.style.display = "none"; if (S.wfHover) { S.wfHover = null; drawWideLines(); } }
});
$("#wfLines").addEventListener("mouseleave", () => { $("#wfHint").style.display = "none"; if (S.wfHover) { S.wfHover = null; drawWideLines(); } });
$("#wfLines").addEventListener("click", () => { if (S.wfHover) openDetail(S.wfHover); });

// ---------------------------------------------------------------- Excel / CSV import into the watchlist
$("#importTpl").href = "data:text/csv;charset=utf-8," + encodeURIComponent("Symbol\nRELIANCE\nTATASTEEL\nIRFC\n");
$("#importBtn").addEventListener("click", () => $("#importFile").click());
$("#importFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  $("#importRes").innerHTML = `Reading <b>${esc(f.name)}</b>…`;
  try {
    const r = await fetch("/api/watchlist/import", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/octet-stream", "X-Filename": f.name }, body: await f.arrayBuffer() });
    const j = await r.json();
    if (!r.ok || !j.ok) throw new Error(j.error || r.statusText);
    $("#importRes").innerHTML = `Found <b>${j.found}</b> names · added <b class="up">${j.added.length}</b> · already in list <b>${j.already.length}</b>`
      + (j.missing_count ? ` · not found <b class="down">${j.missing_count}</b>: ${j.missing.slice(0, 15).map(esc).join(", ")}${j.missing_count > 15 ? "…" : ""}` : "");
    toast(`Imported ${j.added.length} shares into your Volatile Watchlist`, "t1_hit");
  } catch (err) { $("#importRes").innerHTML = `<span class="down">${esc(err.message)}</span>`; }
  e.target.value = "";
});

// ---------------------------------------------------------------- save data: pause live updates while the app is in the background
document.addEventListener("visibilitychange", () => {
  if (document.hidden) { clearTimeout(S.hideT); S.hideT = setTimeout(() => { if (document.hidden && S.user) { stopStream(); S.paused = true; } }, 60000); }
  else { clearTimeout(S.hideT); if (S.paused) { S.paused = false; openStream(); } }
});

// ---------------------------------------------------------------- boot
let started = false;
async function start(user) {
  S.user = user; renderUser();
  try { S.trades = await api("/api/trades"); S.openLive = S.trades.filter(t => t.status === "open"); } catch (e) {}
  openStream();
  if (S.tab !== "boards") setTab(S.tab);
  if (!started) {
    started = true;
    const h = decodeURIComponent(location.hash.slice(1));
    if (h) openDetail(h);
  }
}
async function boot() {
  renderBell();
  let m = { state: "login" };
  try { m = await (await fetch("/api/auth/me", { credentials: "same-origin" })).json(); } catch (e) {}
  if (m.state === "ok") start(m.user); else showAuth(m.state, m);
}
boot();
