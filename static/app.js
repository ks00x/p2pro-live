'use strict';
// P2Pro thermal live view: renders the raw frames from /ws/live, draws the ROIs and lets the user create/delete them.
// Image coordinates: x = column 0..W-1, y = row 0..H-1, pixel (i,j) covers [i,i+1) x [j,j+1).

const RAW_TO_C = (r) => r / 64 - 273.2;            // same as p2pro.raw_to_celsius
const HEADER_BYTES = 20;                            // '<4sHHId': magic, width, height, frame, ts_ms
const MIN_DRAG_PX = 4;                              // screen px, smaller drags are ignored for rect/circle

const $ = (id) => document.getElementById(id);
const canvas = $('view');
const ctx = canvas.getContext('2d');
const off = document.createElement('canvas');       // W x H thermal image, scaled onto the view canvas
const offCtx = off.getContext('2d');

const state = {
  W: 256, H: 192,
  raw: null,          // Uint16Array of the newest frame
  msg: null,          // newest JSON message (stats + rois)
  pendingMsg: null,   // JSON message waiting for its binary frame
  dirty: false,
  tool: 'select',
  drag: null,         // {start:{x,y}, cur:{x,y}, sx, sy} while drawing
  pendingShape: null, // shape waiting for its label
  selected: null,     // selected ROI id
  hover: null,        // image coords of the mouse
  lo: 20, hi: 40,     // current color scale
  frames: 0, fpsT: performance.now(),
};

// ---------- colormaps ----------
const CMAPS = {
  iron:    [[0, 0, 0, 0], [.15, 32, 0, 90], [.35, 140, 0, 140], [.55, 220, 60, 30], [.75, 250, 160, 0], [.9, 255, 230, 80], [1, 255, 255, 255]],
  inferno: [[0, 0, 0, 4], [.25, 87, 16, 110], [.5, 188, 55, 84], [.75, 249, 142, 9], [1, 252, 255, 164]],
  turbo:   [[0, 48, 18, 59], [.1, 65, 69, 171], [.2, 70, 117, 237], [.3, 57, 162, 252], [.4, 27, 207, 212], [.5, 36, 236, 166],
            [.6, 97, 252, 108], [.7, 164, 252, 59], [.8, 209, 232, 52], [.9, 243, 198, 58], [.95, 254, 155, 45], [1, 122, 4, 3]],
  jet:     [[0, 0, 0, 128], [.125, 0, 0, 255], [.375, 0, 255, 255], [.625, 255, 255, 0], [.875, 255, 0, 0], [1, 128, 0, 0]],
  gray:    [[0, 0, 0, 0], [1, 255, 255, 255]],
};
function buildLut(stops) {
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    let k = 0;
    while (k < stops.length - 2 && t > stops[k + 1][0]) k++;
    const [t0, ...c0] = stops[k], [t1, ...c1] = stops[k + 1];
    const f = Math.min(1, Math.max(0, (t - t0) / (t1 - t0)));
    for (let c = 0; c < 3; c++) lut[i * 3 + c] = c0[c] + (c1[c] - c0[c]) * f;
  }
  return lut;
}
let lut = buildLut(CMAPS.iron);

// ---------- settings (per browser) ----------
const prefs = (() => { try { return JSON.parse(localStorage.getItem('p2pro-view') || '{}'); } catch { return {}; } })();
function savePrefs() {
  try {
    localStorage.setItem('p2pro-view', JSON.stringify({
      cmap: $('cmap').value, auto: $('auto').checked, tmin: $('tmin').value, tmax: $('tmax').value, hot: $('show-hot').checked,
    }));
  } catch { /* storage unavailable */ }
}
if (prefs.cmap && CMAPS[prefs.cmap]) $('cmap').value = prefs.cmap;
if (typeof prefs.auto === 'boolean') $('auto').checked = prefs.auto;
if (prefs.tmin !== undefined) $('tmin').value = prefs.tmin;
if (prefs.tmax !== undefined) $('tmax').value = prefs.tmax;
if (typeof prefs.hot === 'boolean') $('show-hot').checked = prefs.hot;
lut = buildLut(CMAPS[$('cmap').value]);

function syncScaleInputs() {
  $('tmin').disabled = $('tmax').disabled = $('auto').checked;
}
syncScaleInputs();
$('cmap').addEventListener('change', () => { lut = buildLut(CMAPS[$('cmap').value]); drawScale(); state.dirty = true; savePrefs(); });
for (const id of ['auto', 'tmin', 'tmax', 'show-hot']) {
  $(id).addEventListener('change', () => { syncScaleInputs(); state.dirty = true; savePrefs(); });
}

// ---------- stream URLs ----------
const wsBase = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
$('url-ws').textContent = `${wsBase}/ws/data`;
$('url-sse').textContent = `${location.origin}/api/stream`;
$('url-latest').textContent = `${location.origin}/api/latest`;
$('url-rois').textContent = `${location.origin}/api/rois`;

// ---------- live websocket ----------
function connect() {
  const ws = new WebSocket(`${wsBase}/ws/live`);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => setConn('on', 'conectado');
  ws.onclose = () => { setConn('off', 'desconectado, reconectando…'); setTimeout(connect, 1000); };
  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') { state.pendingMsg = JSON.parse(ev.data); return; }
    const dv = new DataView(ev.data);
    const w = dv.getUint16(4, true), h = dv.getUint16(6, true), frame = dv.getUint32(8, true);
    if (w !== state.W || h !== state.H) { state.W = w; state.H = h; resize(); }
    state.raw = new Uint16Array(ev.data, HEADER_BYTES, w * h);
    $('nocam').hidden = true;
    if (state.pendingMsg && state.pendingMsg.frame % 2 ** 32 === frame) state.msg = state.pendingMsg;
    state.dirty = true;
    state.frames++;
  };
}
function setConn(cls, text) {
  $('conn').className = `conn ${cls}`;
  $('conn-text').textContent = text;
}

// camera status (the websocket can be connected while the camera is not)
async function pollStatus() {
  try {
    const st = await (await fetch('/api/status')).json();
    if (!st.connected) setConn('warn', `câmera indisponível: ${st.error || '?'}`);
    else if ($('conn').classList.contains('warn')) setConn('on', 'conectado');
    if (!st.connected) { $('nocam').hidden = false; $('nocam').textContent = 'Câmera indisponível, tentando reconectar…'; }
  } catch { /* server down, websocket shows it */ }
  setTimeout(pollStatus, 2000);
}

// ---------- geometry helpers ----------
function scale() { return canvas.clientWidth / state.W; }       // screen px per image px
function toImage(ev) {
  const r = canvas.getBoundingClientRect();
  return { x: (ev.clientX - r.left) / r.width * state.W, y: (ev.clientY - r.top) / r.height * state.H, sx: ev.clientX - r.left, sy: ev.clientY - r.top };
}
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function shapeFromDrag(tool, a, b) {
  const { W, H } = state;
  if (tool === 'point') return { type: 'point', x: clamp(Math.floor(b.x), 0, W - 1), y: clamp(Math.floor(b.y), 0, H - 1) };
  if (tool === 'rect') {
    const x0 = clamp(Math.floor(Math.min(a.x, b.x)), 0, W - 1), y0 = clamp(Math.floor(Math.min(a.y, b.y)), 0, H - 1);
    const x1 = clamp(Math.ceil(Math.max(a.x, b.x)), x0 + 1, W), y1 = clamp(Math.ceil(Math.max(a.y, b.y)), y0 + 1, H);
    return { type: 'rect', x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  // circle: center snapped to the pixel center, radius = drag distance
  const cx = clamp(Math.floor(a.x), 0, W - 1) + 0.5, cy = clamp(Math.floor(a.y), 0, H - 1) + 0.5;
  const r = Math.max(0.5, Math.round(Math.hypot(b.x - cx, b.y - cy) * 10) / 10);
  return { type: 'circle', cx, cy, r };
}

function hitTest(p) {
  const rois = state.msg ? state.msg.rois : [];
  const tol = 6 / scale();  // 6 screen px
  for (let i = rois.length - 1; i >= 0; i--) {
    const r = rois[i];
    if (r.type === 'point' && Math.hypot(p.x - (r.x + .5), p.y - (r.y + .5)) <= tol + .5) return r.id;
    if (r.type === 'rect' && p.x >= r.x - tol && p.x <= r.x + r.w + tol && p.y >= r.y - tol && p.y <= r.y + r.h + tol) return r.id;
    if (r.type === 'circle' && Math.hypot(p.x - r.cx, p.y - r.cy) <= r.r + tol) return r.id;
  }
  return null;
}

// ---------- tools ----------
function setTool(tool) {
  state.tool = tool;
  for (const b of document.querySelectorAll('.tools button')) b.classList.toggle('active', b.dataset.tool === tool);
  canvas.classList.toggle('select', tool === 'select');
}
for (const b of document.querySelectorAll('.tools button')) b.addEventListener('click', () => setTool(b.dataset.tool));
setTool('select');

canvas.addEventListener('pointerdown', (ev) => {
  if (!$('label-form').hidden) return;
  const p = toImage(ev);
  if (state.tool === 'select') { select(hitTest(p)); return; }
  canvas.setPointerCapture(ev.pointerId);
  state.drag = { start: p, cur: p };
  state.dirty = true;
});
canvas.addEventListener('pointermove', (ev) => {
  const p = toImage(ev);
  state.hover = p;
  if (state.drag) state.drag.cur = p;
  state.dirty = true;
});
canvas.addEventListener('pointerleave', () => { state.hover = null; state.dirty = true; });
canvas.addEventListener('pointerup', (ev) => {
  if (!state.drag) return;
  const { start, cur } = state.drag;
  state.drag = null;
  state.dirty = true;
  if (state.tool !== 'point' && Math.hypot(cur.sx - start.sx, cur.sy - start.sy) < MIN_DRAG_PX) return;
  askLabel(shapeFromDrag(state.tool, start, cur), cur);
});
canvas.addEventListener('pointercancel', () => { state.drag = null; state.dirty = true; });

function nextId(type) {
  const prefix = { point: 'P', rect: 'R', circle: 'C' }[type];
  const used = new Set((state.msg ? state.msg.rois : []).map((r) => r.id));
  let n = 1;
  while (used.has(prefix + n)) n++;
  return prefix + n;
}

function askLabel(shape, at) {
  state.pendingShape = shape;
  const form = $('label-form');
  form.hidden = false;
  const stage = $('stage').getBoundingClientRect();
  form.style.left = `${clamp(at.sx + 12, 4, stage.width - form.offsetWidth - 4)}px`;
  form.style.top = `${clamp(at.sy + 12, 4, stage.height - form.offsetHeight - 4)}px`;
  $('label-error').textContent = '';
  const input = $('label-input');
  input.value = nextId(shape.type);
  input.focus();
  input.select();
}
function closeLabel() {
  $('label-form').hidden = true;
  state.pendingShape = null;
  state.dirty = true;
}
$('label-cancel').addEventListener('click', closeLabel);
$('label-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const id = $('label-input').value.trim();
  try {
    const res = await fetch('/api/rois', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, ...state.pendingShape }) });
    const body = await res.json();
    if (!res.ok) { $('label-error').textContent = body.error || res.statusText; return; }
    closeLabel();
    select(body.id);
  } catch (e) { $('label-error').textContent = String(e); }
});

async function deleteRoi(id) {
  $('roi-error').textContent = '';
  try {
    const res = await fetch(`/api/rois/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!res.ok && res.status !== 404) throw new Error((await res.json()).error || res.statusText);
    if (state.selected === id) state.selected = null;
  } catch (e) { $('roi-error').textContent = `erro ao apagar ${id}: ${e.message}`; }
}
$('clear-all').addEventListener('click', async () => {
  if (!state.msg || state.msg.rois.length === 0) return;
  if (!confirm(`Apagar todos os ${state.msg.rois.length} pontos/áreas de coleta?`)) return;
  await fetch('/api/rois', { method: 'DELETE' });
  state.selected = null;
});

function select(id) { state.selected = id; state.dirty = true; updateTable(true); }

document.addEventListener('keydown', (ev) => {
  if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'SELECT') {
    if (ev.key === 'Escape' && !$('label-form').hidden) closeLabel();
    return;
  }
  const k = ev.key.toLowerCase();
  if (k === 'escape') { state.drag = null; select(null); }
  else if ((ev.key === 'Delete' || ev.key === 'Backspace') && state.selected) { ev.preventDefault(); deleteRoi(state.selected); }
  else if (k === 'v') setTool('select');
  else if (k === 'p') setTool('point');
  else if (k === 'r') setTool('rect');
  else if (k === 'c') setTool('circle');
});

// ---------- side panel ----------
const fmt = (v) => (v === undefined || v === null ? '–' : `${v.toFixed(1)} °C`);
let lastTable = 0;
function updateTable(force) {
  const now = performance.now();
  if (!force && now - lastTable < 250) return;
  lastTable = now;
  const m = state.msg;
  if (!m) return;
  const g = m.global;
  $('g-max').textContent = fmt(g.max);
  $('g-max-pos').textContent = `(${g.max_pos.x}, ${g.max_pos.y})`;
  $('g-min').textContent = fmt(g.min);
  $('g-min-pos').textContent = `(${g.min_pos.x}, ${g.min_pos.y})`;
  $('g-mean').textContent = fmt(g.mean);

  $('roi-empty').hidden = m.rois.length > 0;
  $('roi-table').hidden = m.rois.length === 0;
  const tbody = $('roi-table').tBodies[0];
  const rows = new Map([...tbody.rows].map((tr) => [tr.dataset.id, tr]));
  const kinds = { point: 'pt', rect: 'ret', circle: 'circ' };
  m.rois.forEach((r, i) => {
    let tr = rows.get(r.id);
    if (!tr) {
      tr = tbody.insertRow();
      tr.dataset.id = r.id;
      tr.innerHTML = '<td class="id"></td><td class="max"></td><td class="mean"></td><td class="min"></td><td><button class="small danger" title="apagar">×</button></td>';
      tr.querySelector('.id').innerHTML = `<span class="kind">${kinds[r.type]}</span>`;
      tr.querySelector('.id').append(document.createTextNode(r.id));
      tr.querySelector('.id').title = r.id;
      tr.querySelector('button').addEventListener('click', (ev) => { ev.stopPropagation(); deleteRoi(r.id); });
      tr.addEventListener('click', () => select(r.id));
    }
    rows.delete(r.id);
    if (tbody.rows[i] !== tr) tbody.insertBefore(tr, tbody.rows[i] || null);
    const isPt = r.type === 'point';
    tr.querySelector('.max').textContent = fmt(isPt ? r.temp : r.max);
    tr.querySelector('.mean').textContent = isPt ? '' : fmt(r.mean);
    tr.querySelector('.min').textContent = isPt ? '' : fmt(r.min);
    tr.classList.toggle('selected', r.id === state.selected);
  });
  for (const tr of rows.values()) tr.remove();  // deleted ROIs
  if (state.selected && !m.rois.some((r) => r.id === state.selected)) state.selected = null;
}

// ---------- rendering ----------
function resize() {
  off.width = state.W;
  off.height = state.H;
  const dpr = window.devicePixelRatio || 1;
  const cssW = $('stage').clientWidth;
  const cssH = cssW * state.H / state.W;
  canvas.style.height = `${cssH}px`;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  state.dirty = true;
}
window.addEventListener('resize', resize);

function drawScale() {
  const c = $('scale'), sctx = c.getContext('2d');
  const img = sctx.createImageData(c.width, 1);
  for (let i = 0; i < c.width; i++) {
    const k = Math.round(i / (c.width - 1) * 255) * 3;
    img.data.set([lut[k], lut[k + 1], lut[k + 2], 255], i * 4);
  }
  for (let y = 0; y < c.height; y++) sctx.putImageData(img, 0, y);
}

function renderImage() {
  const { W, H, raw } = state;
  if (!raw) return;
  let lo, hi;
  if ($('auto').checked && state.msg) { lo = state.msg.global.min; hi = state.msg.global.max; }
  else { lo = parseFloat($('tmin').value); hi = parseFloat($('tmax').value); }
  if (!(hi > lo)) hi = lo + 1;
  state.lo = lo; state.hi = hi;
  const img = offCtx.createImageData(W, H);
  const d = img.data, k = 255 / (hi - lo);
  for (let i = 0; i < W * H; i++) {
    const v = Math.min(255, Math.max(0, Math.round((RAW_TO_C(raw[i]) - lo) * k))) * 3;
    d[i * 4] = lut[v]; d[i * 4 + 1] = lut[v + 1]; d[i * 4 + 2] = lut[v + 2]; d[i * 4 + 3] = 255;
  }
  offCtx.putImageData(img, 0, 0);
  $('scale-lo').textContent = `${lo.toFixed(1)} °C`;
  $('scale-hi').textContent = `${hi.toFixed(1)} °C`;
}

function label(text, x, y, color) {
  ctx.font = '600 12px system-ui, sans-serif';
  const w = ctx.measureText(text).width + 8;
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  const lx = clamp(x, 0, cw - w), ly = clamp(y, 0, ch - 18);
  ctx.fillStyle = 'rgba(0,0,0,.65)';
  ctx.fillRect(lx, ly, w, 18);
  ctx.fillStyle = color;
  ctx.fillText(text, lx + 4, ly + 13);
}

function strokeShape(shape, s, color, dashed) {
  ctx.save();
  if (dashed) ctx.setLineDash([5, 4]);
  for (const [lw, col] of [[3.5, 'rgba(0,0,0,.7)'], [1.6, color]]) {
    ctx.lineWidth = lw;
    ctx.strokeStyle = col;
    ctx.beginPath();
    if (shape.type === 'rect') ctx.rect(shape.x * s, shape.y * s, shape.w * s, shape.h * s);
    else if (shape.type === 'circle') ctx.arc(shape.cx * s, shape.cy * s, shape.r * s, 0, 2 * Math.PI);
    else {  // point: the pixel + crosshair
      const cx = (shape.x + .5) * s, cy = (shape.y + .5) * s, a = Math.max(6, s);
      ctx.rect(shape.x * s, shape.y * s, s, s);
      ctx.moveTo(cx - a - 4, cy); ctx.lineTo(cx - a / 2, cy); ctx.moveTo(cx + a / 2, cy); ctx.lineTo(cx + a + 4, cy);
      ctx.moveTo(cx, cy - a - 4); ctx.lineTo(cx, cy - a / 2); ctx.moveTo(cx, cy + a / 2); ctx.lineTo(cx, cy + a + 4);
    }
    ctx.stroke();
  }
  ctx.restore();
}

function render() {
  requestAnimationFrame(render);
  if (!state.dirty) return;
  state.dirty = false;
  renderImage();
  const cw = canvas.clientWidth, ch = canvas.clientHeight, s = scale();
  ctx.clearRect(0, 0, cw, ch);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(off, 0, 0, cw, ch);
  const m = state.msg;
  if (m) {
    for (const r of m.rois) {
      const sel = r.id === state.selected;
      const color = sel ? '#3fb6ff' : '#ffffff';
      strokeShape(r, s, color, false);
      let lx, ly;
      if (r.type === 'rect') { lx = r.x * s; ly = r.y * s - 19; }
      else if (r.type === 'circle') { lx = (r.cx - r.r) * s; ly = (r.cy - r.r) * s - 19; }
      else { lx = (r.x + 1) * s + 6; ly = (r.y + .5) * s - 20; }
      const val = r.type === 'point' ? r.temp : r.max;
      label(`${r.id}  ${val.toFixed(1)}°`, lx, ly, color);
      if (r.type !== 'point') {  // hottest pixel of the area
        ctx.fillStyle = '#ff7a59';
        ctx.fillRect((r.max_pos.x + .5) * s - 2, (r.max_pos.y + .5) * s - 2, 4, 4);
      }
    }
    if ($('show-hot').checked) {
      const p = m.global.max_pos, x = (p.x + .5) * s, y = (p.y + .5) * s;
      for (const [lw, col] of [[4.5, 'rgba(0,0,0,.75)'], [2, '#ff3b30']]) {  // dark outline: visible on hot colors
        ctx.lineWidth = lw;
        ctx.strokeStyle = col;
        ctx.beginPath();
        ctx.arc(x, y, 7, 0, 2 * Math.PI);
        ctx.moveTo(x - 12, y); ctx.lineTo(x + 12, y); ctx.moveTo(x, y - 12); ctx.lineTo(x, y + 12);
        ctx.stroke();
      }
      label(`máx ${m.global.max.toFixed(1)}°`, x + 10, y + 8, '#ff7a59');
    }
  }
  const preview = state.drag ? shapeFromDrag(state.tool, state.drag.start, state.drag.cur) : state.pendingShape;
  if (preview) strokeShape(preview, s, '#ffd60a', true);
  // mouse readout
  const h = state.hover;
  if (h && state.raw) {
    const x = clamp(Math.floor(h.x), 0, state.W - 1), y = clamp(Math.floor(h.y), 0, state.H - 1);
    $('hover').textContent = `x ${x}, y ${y}: ${RAW_TO_C(state.raw[y * state.W + x]).toFixed(2)} °C`;
  }
  updateTable(false);
}

setInterval(() => {
  const now = performance.now();
  $('fps').textContent = `${(state.frames * 1000 / (now - state.fpsT)).toFixed(1)} fps`;
  state.frames = 0; state.fpsT = now;
}, 1000);

resize();
drawScale();
connect();
pollStatus();
requestAnimationFrame(render);
