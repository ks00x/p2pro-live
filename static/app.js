'use strict';
// P2Pro thermal live view: renders the raw frames from /ws/live, draws the collection points/areas (ROIs) and lets
// the user create, move, resize, rename, lock/unlock and delete them.
// Image coordinates: x = column 0..W-1, y = row 0..H-1, pixel (i,j) covers [i,i+1) x [j,j+1).

const RAW_TO_C = (r) => r / 64 - 273.2;            // same as p2pro.raw_to_celsius
const HEADER_BYTES = 20;                            // '<4sHHId': magic, width, height, frame, ts_ms
const MIN_DRAG_PX = 4;                              // screen px, smaller drags are ignored for rect/circle
const GEOM_KEYS = { point: ['x', 'y'], rect: ['x', 'y', 'w', 'h'], circle: ['cx', 'cy', 'r'] };
const COLOR = { normal: '#ffffff', selected: '#3fb6ff', locked: '#f5b942', preview: '#ffd60a', hot: '#ff7a59' };
const CURSORS = { n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize', nw: 'nwse-resize', se: 'nwse-resize', ne: 'nesw-resize', sw: 'nesw-resize' };

const $ = (id) => document.getElementById(id);
const canvas = $('view');
const ctx = canvas.getContext('2d');
const off = document.createElement('canvas');       // W x H thermal image, scaled onto the view canvas
const offCtx = off.getContext('2d');

const state = {
  W: 256, H: 192,
  raw: null,          // Uint16Array of the newest frame
  msg: null,          // newest frame message (stats + rois)
  pendingMsg: null,   // frame message waiting for its binary frame
  dirty: false,
  tool: 'select',
  drag: null,         // drawing a new shape: {start, cur}
  edit: null,         // moving/resizing: {id, kind, handle, start, orig, geom, moved}
  override: null,     // geometry shown until the server confirms a change: {id, geom, untilFrame}
  form: null,         // label form: {mode: 'create'|'rename', shape | id}
  selected: null,
  hover: null,
  labelHits: [],      // lock icons and labels drawn on the canvas, for clicks
  camera: { connected: false, error: null },
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

// language: saved choice, else the browser language (pt, es, else en)
const savedLang = (() => { try { return localStorage.getItem('p2pro-lang'); } catch { return null; } })();
$('lang').value = I18N[savedLang] ? savedLang : detectLang();
$('lang').addEventListener('change', () => {
  try { localStorage.setItem('p2pro-lang', $('lang').value); } catch { /* storage unavailable */ }
  applyLang($('lang').value);
});
document.addEventListener('langchange', () => {
  $('roi-table').tBodies[0].replaceChildren();  // rows are rebuilt with the new texts
  if (state.form) $('label-submit').textContent = t(state.form.mode === 'create' ? 'form.create' : 'form.rename');
  showState();
  updateTable(true);
  state.dirty = true;
});

// theme: 'system' follows prefers-color-scheme (CSS), 'dark'/'light' set data-theme (also set in <head>)
const savedTheme = (() => { try { return localStorage.getItem('p2pro-theme'); } catch { return null; } })();
$('theme').value = savedTheme === 'dark' || savedTheme === 'light' ? savedTheme : 'system';
$('theme').addEventListener('change', () => {
  const th = $('theme').value;
  if (th === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = th;
  try { localStorage.setItem('p2pro-theme', th); } catch { /* storage unavailable */ }
});

function syncScaleInputs() { $('tmin').disabled = $('tmax').disabled = $('auto').checked; }
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

// ---------- connection / camera state ----------
let serverUp = false;
function showState() {
  const cam = state.camera;
  let cls = 'on', text = t('conn.connected'), overlay = null;
  if (!serverUp) { cls = 'off'; text = t('conn.server_down'); overlay = t('overlay.server_down'); }
  else if (!cam.connected) { cls = 'warn'; text = t('conn.camera_down'); overlay = t('overlay.camera_down'); }
  else if (!state.raw) overlay = t('overlay.waiting');
  $('conn').className = `conn ${cls}`;
  $('conn-text').textContent = text;
  $('conn').title = cam.error || t('conn.title');
  $('nocam').hidden = !overlay;
  if (overlay) { $('nocam-text').textContent = overlay; $('nocam-text').title = cam.error || ''; }
}

function connect() {
  const ws = new WebSocket(`${wsBase}/ws/live`);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => { serverUp = true; showState(); };
  ws.onclose = () => { serverUp = false; showState(); setTimeout(connect, 1000); };
  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') {
      const m = JSON.parse(ev.data);
      if (m.type === 'status') { state.camera = { connected: m.camera_connected, error: m.error }; showState(); }
      else state.pendingMsg = m;
      return;
    }
    const dv = new DataView(ev.data);
    const w = dv.getUint16(4, true), h = dv.getUint16(6, true), frame = dv.getUint32(8, true);
    if (w !== state.W || h !== state.H) { state.W = w; state.H = h; resize(); }
    const first = !state.raw;
    state.raw = new Uint16Array(ev.data, HEADER_BYTES, w * h);
    if (state.pendingMsg && state.pendingMsg.frame % 2 ** 32 === frame) {
      state.msg = state.pendingMsg;
      if (state.override && state.override.untilFrame !== null && state.msg.frame > state.override.untilFrame) state.override = null;
    }
    if (first) showState();
    state.dirty = true;
    state.frames++;
  };
}

let noticeTimer = null;
function notice(text) {
  $('notice').textContent = text;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { $('notice').textContent = ''; }, 5000);
}

// ---------- ROI data ----------
// the ROIs of the newest message, with the geometry being edited/just sent shown instead of the server one
function rois() {
  if (!state.msg) return [];
  return state.msg.rois.map((r) => {
    if (state.edit && state.edit.id === r.id) return { ...r, ...state.edit.geom };
    if (state.override && state.override.id === r.id) return { ...r, ...state.override.geom };
    return r;
  });
}
const findRoi = (id) => rois().find((r) => r.id === id);
const pick = (r, keys) => Object.fromEntries(keys.map((k) => [k, r[k]]));

async function api(method, path, body) {
  try {
    const res = await fetch(path, {
      method, headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = res.status === 204 ? null : await res.json();
    return { ok: res.ok, status: res.status, data, error: data && data.error };
  } catch (e) {
    return { ok: false, status: 0, data: null, error: String(e) };
  }
}
const roiPath = (id) => `/api/rois/${encodeURIComponent(id)}`;
const errText = (r, id) => ([404, 409, 423].includes(r.status) ? t(`err.${r.status}`, { id }) : r.error || `HTTP ${r.status}`);
// the server confirms a change before the next frames carry it: keep showing the new geometry for 2 more frames
const confirmFrame = () => (state.msg ? state.msg.frame + 2 : 0);

async function patchGeometry(id, geom) {
  state.override = { id, geom, untilFrame: null };
  const r = await api('PATCH', roiPath(id), geom);
  if (!r.ok) { state.override = null; notice(t('n.change_failed', { id, error: errText(r, id) })); }
  else state.override.untilFrame = confirmFrame();
  state.dirty = true;
}

async function toggleLock(id) {
  const roi = findRoi(id);
  if (!roi) return;
  const r = await api('PATCH', roiPath(id), { locked: !roi.locked });
  if (!r.ok) notice(t(roi.locked ? 'n.unlock_failed' : 'n.lock_failed', { id, error: errText(r, id) }));
}

async function deleteRoi(id) {
  const roi = findRoi(id);
  if (roi && roi.locked) { notice(t('n.locked_delete', { id })); return; }
  const r = await api('DELETE', roiPath(id));
  if (!r.ok && r.status !== 404) notice(t('n.delete_failed', { id, error: errText(r, id) }));
  if (state.selected === id) state.selected = null;
}

$('clear-all').addEventListener('click', async () => {
  const unlocked = rois().filter((r) => !r.locked).length;
  if (unlocked === 0) { notice(t('n.nothing_to_delete')); return; }
  if (!confirm(t('confirm.clear', { n: unlocked }))) return;
  const r = await api('DELETE', '/api/rois');
  if (r.ok && r.data.kept_locked) notice(t('n.kept', { n: r.data.kept_locked }));
  state.selected = null;
});

// ---------- geometry ----------
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

function handlesOf(r) {
  if (r.type === 'rect') {
    const { x, y, w, h } = r;
    return { nw: [x, y], n: [x + w / 2, y], ne: [x + w, y], e: [x + w, y + h / 2], se: [x + w, y + h], s: [x + w / 2, y + h], sw: [x, y + h], w: [x, y + h / 2] };
  }
  if (r.type === 'circle') return { n: [r.cx, r.cy - r.r], e: [r.cx + r.r, r.cy], s: [r.cx, r.cy + r.r], w: [r.cx - r.r, r.cy] };
  return {};
}

function hitHandle(p, r, tol) {
  for (const [name, [hx, hy]] of Object.entries(handlesOf(r))) if (Math.abs(p.x - hx) <= tol && Math.abs(p.y - hy) <= tol) return name;
  return null;
}

function hitBody(p, tol) {
  const list = rois();
  for (let i = list.length - 1; i >= 0; i--) {
    const r = list[i];
    if (r.type === 'point' && Math.hypot(p.x - (r.x + .5), p.y - (r.y + .5)) <= tol + .5) return r.id;
    if (r.type === 'rect' && p.x >= r.x - tol && p.x <= r.x + r.w + tol && p.y >= r.y - tol && p.y <= r.y + r.h + tol) return r.id;
    if (r.type === 'circle' && Math.hypot(p.x - r.cx, p.y - r.cy) <= r.r + tol) return r.id;
  }
  for (const l of state.labelHits) if (p.sx >= l.x && p.sx <= l.x + l.w && p.sy >= l.y && p.sy <= l.y + l.h) return l.id;  // its label
  return null;
}

function hitLock(p) {
  for (const l of state.labelHits) if (p.sx >= l.x - 2 && p.sx <= l.x + l.lockW && p.sy >= l.y - 2 && p.sy <= l.y + l.h + 2) return l.id;
  return null;
}

// new geometry while moving/resizing (image coordinates p)
function editGeometry(e, p) {
  const { W, H } = state, o = e.orig, dx = p.x - e.start.x, dy = p.y - e.start.y;
  if (e.kind === 'move') {
    if (o.type === 'rect') return { x: clamp(o.x + Math.round(dx), 0, W - o.w), y: clamp(o.y + Math.round(dy), 0, H - o.h), w: o.w, h: o.h };
    if (o.type === 'circle') return { cx: clamp(o.cx + Math.round(dx), 0, W), cy: clamp(o.cy + Math.round(dy), 0, H), r: o.r };
    return { x: clamp(Math.floor(o.x + .5 + dx), 0, W - 1), y: clamp(Math.floor(o.y + .5 + dy), 0, H - 1) };
  }
  if (o.type === 'circle') return { cx: o.cx, cy: o.cy, r: Math.max(0.5, Math.round(Math.hypot(p.x - o.cx, p.y - o.cy) * 10) / 10) };
  let x0 = o.x, y0 = o.y, x1 = o.x + o.w, y1 = o.y + o.h;
  const px = clamp(Math.round(p.x), 0, W), py = clamp(Math.round(p.y), 0, H), h = e.handle;
  if (h.includes('w')) x0 = Math.min(px, x1 - 1);
  if (h.includes('e')) x1 = Math.max(px, x0 + 1);
  if (h.includes('n')) y0 = Math.min(py, y1 - 1);
  if (h.includes('s')) y1 = Math.max(py, y0 + 1);
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

// ---------- tools and pointer ----------
function setTool(tool) {
  state.tool = tool;
  for (const b of document.querySelectorAll('.tools button')) b.classList.toggle('active', b.dataset.tool === tool);
  canvas.style.cursor = tool === 'select' ? 'default' : 'crosshair';
}
for (const b of document.querySelectorAll('.tools button')) b.addEventListener('click', () => setTool(b.dataset.tool));
setTool('select');

const tolerance = (ev) => (ev.pointerType === 'touch' ? 14 : 7) / scale();

canvas.addEventListener('pointerdown', (ev) => {
  if (state.form) return;
  const p = toImage(ev);
  const lockId = hitLock(p);
  if (lockId) { toggleLock(lockId); return; }
  if (state.tool === 'select') {
    const tol = tolerance(ev);
    const sel = state.selected && findRoi(state.selected);
    let handle = null, id = null;
    if (sel && !sel.locked) handle = hitHandle(p, sel, tol);
    if (handle) id = sel.id;
    else id = hitBody(p, tol);
    select(id);
    if (!id) return;
    const roi = findRoi(id);
    if (roi.locked) return;  // locked: selectable, not editable
    canvas.setPointerCapture(ev.pointerId);
    state.edit = { id, kind: handle ? 'resize' : 'move', handle, start: p, orig: roi, geom: pick(roi, GEOM_KEYS[roi.type]), moved: false };
    return;
  }
  canvas.setPointerCapture(ev.pointerId);
  state.drag = { start: p, cur: p };
  state.dirty = true;
});

canvas.addEventListener('pointermove', (ev) => {
  const p = toImage(ev);
  state.hover = p;
  state.dirty = true;
  if (state.edit) {
    const e = state.edit;
    if (!e.moved && Math.hypot(p.sx - e.start.sx, p.sy - e.start.sy) < 3) return;
    e.moved = true;
    e.geom = editGeometry(e, p);
    return;
  }
  if (state.drag) { state.drag.cur = p; return; }
  // cursor feedback
  let cursor = state.tool === 'select' ? 'default' : 'crosshair';
  if (hitLock(p)) cursor = 'pointer';
  else if (state.tool === 'select') {
    const tol = tolerance(ev), sel = state.selected && findRoi(state.selected);
    const handle = sel && !sel.locked ? hitHandle(p, sel, tol) : null;
    if (handle) cursor = CURSORS[handle];
    else {
      const id = hitBody(p, tol);
      if (id) cursor = findRoi(id).locked ? 'not-allowed' : 'move';
    }
  }
  canvas.style.cursor = cursor;
});
canvas.addEventListener('pointerleave', () => { state.hover = null; state.dirty = true; });

canvas.addEventListener('pointerup', (ev) => {
  if (state.edit) {
    const e = state.edit;
    state.edit = null;
    const changed = e.moved && GEOM_KEYS[e.orig.type].some((k) => e.geom[k] !== e.orig[k]);
    if (changed) patchGeometry(e.id, e.geom);
    state.dirty = true;
    return;
  }
  if (!state.drag) return;
  const { start, cur } = state.drag;
  state.drag = null;
  state.dirty = true;
  if (state.tool !== 'point' && Math.hypot(cur.sx - start.sx, cur.sy - start.sy) < MIN_DRAG_PX) return;
  openForm({ mode: 'create', shape: shapeFromDrag(state.tool, start, cur) }, cur);
});
canvas.addEventListener('pointercancel', () => { state.drag = null; state.edit = null; state.dirty = true; });

canvas.addEventListener('dblclick', (ev) => {
  if (state.tool !== 'select' || state.form) return;
  const id = hitBody(toImage(ev), 7 / scale());
  if (id) rename(id, toImage(ev));
});

// ---------- label form (create / rename) ----------
function nextId(type) {
  const prefix = { point: 'P', rect: 'R', circle: 'C' }[type];
  const used = new Set(rois().map((r) => r.id));
  let n = 1;
  while (used.has(prefix + n)) n++;
  return prefix + n;
}

function openForm(form, at) {
  state.form = form;
  const el = $('label-form');
  el.hidden = false;
  const stage = $('stage').getBoundingClientRect();
  el.style.left = `${clamp(at.sx + 12, 4, stage.width - el.offsetWidth - 4)}px`;
  el.style.top = `${clamp(at.sy + 12, 4, stage.height - el.offsetHeight - 4)}px`;
  $('label-error').textContent = '';
  $('label-submit').textContent = t(form.mode === 'create' ? 'form.create' : 'form.rename');
  const input = $('label-input');
  input.value = form.mode === 'create' ? nextId(form.shape.type) : form.id;
  input.focus();
  input.select();
  state.dirty = true;
}
function closeForm() {
  $('label-form').hidden = true;
  state.form = null;
  state.dirty = true;
}
function rename(id, at) {
  const roi = findRoi(id);
  if (!roi) return;
  if (roi.locked) { notice(t('n.locked_rename', { id })); return; }
  if (!at) {  // from the list: next to the object
    const s = scale(), [hx, hy] = roi.type === 'circle' ? [roi.cx, roi.cy] : [roi.x, roi.y];
    at = { sx: hx * s, sy: hy * s };
  }
  select(id);
  openForm({ mode: 'rename', id }, at);
}
$('label-cancel').addEventListener('click', closeForm);
$('label-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const id = $('label-input').value.trim();
  const f = state.form;
  if (!f) return;
  let r;
  if (f.mode === 'create') r = await api('POST', '/api/rois', { id, ...f.shape });
  else if (id === f.id) { closeForm(); return; }
  else r = await api('PATCH', roiPath(f.id), { id });
  if (!r.ok) { $('label-error').textContent = errText(r, f.mode === 'create' ? id : f.id); return; }
  closeForm();
  select(r.data.id);
});

function select(id) { state.selected = id; state.dirty = true; updateTable(true); }

document.addEventListener('keydown', (ev) => {
  if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'SELECT') {
    if (ev.key === 'Escape' && state.form) closeForm();
    return;
  }
  const k = ev.key.toLowerCase(), sel = state.selected && findRoi(state.selected);
  if (k === 'escape') { state.drag = null; state.edit = null; select(null); }
  else if ((ev.key === 'Delete' || ev.key === 'Backspace') && sel) { ev.preventDefault(); deleteRoi(sel.id); }
  else if (ev.key.startsWith('Arrow') && sel) {
    ev.preventDefault();
    if (sel.locked) { notice(t('n.locked', { id: sel.id })); return; }
    const step = ev.shiftKey ? 10 : 1, d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[ev.key];
    const e = { kind: 'move', start: { x: 0, y: 0 }, orig: sel };
    patchGeometry(sel.id, editGeometry(e, { x: d[0], y: d[1] }));
  }
  else if (k === 'l' && sel) toggleLock(sel.id);
  else if ((ev.key === 'F2' || ev.key === 'Enter') && sel) { ev.preventDefault(); rename(sel.id); }
  else if (k === 'v') setTool('select');
  else if (k === 'p') setTool('point');
  else if (k === 'r') setTool('rect');
  else if (k === 'c') setTool('circle');
});

// ---------- side panel ----------
const ICON_LOCKED = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor"/><path d="M5 7V5a3 3 0 0 1 6 0v2" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>';
const ICON_UNLOCKED = '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor"/><path d="M5 7V5a3 3 0 0 1 5.8-1" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>';
const fmt = (v) => (v === undefined || v === null ? '–' : `${v.toFixed(1)} °C`);
const fmtShort = (v) => (v === undefined || v === null ? '–' : `${v.toFixed(1)}°`);  // table cells
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

  const list = rois();
  $('roi-empty').hidden = list.length > 0;
  $('roi-table').hidden = list.length === 0;
  const tbody = $('roi-table').tBodies[0];
  const rows = new Map([...tbody.rows].map((tr) => [tr.dataset.id, tr]));
  list.forEach((r, i) => {
    let tr = rows.get(r.id);
    if (!tr) {
      tr = tbody.insertRow();
      tr.dataset.id = r.id;
      tr.innerHTML = '<td class="id"></td><td class="max"></td><td class="mean"></td><td class="min"></td>' +
        '<td class="acts"><button class="small lock"></button><button class="small edit">✎</button>' +
        '<button class="small danger del">×</button></td>';
      tr.querySelector('.edit').title = t('btn.rename');
      tr.querySelector('.del').title = t('btn.delete');
      const td = tr.querySelector('.id');
      const kind = document.createElement('span');
      kind.className = 'kind';
      kind.textContent = t(`kind.${r.type}`);
      td.append(kind);
      td.append(document.createTextNode(r.id));
      td.title = r.id;
      tr.querySelector('.lock').addEventListener('click', (ev) => { ev.stopPropagation(); toggleLock(r.id); });
      tr.querySelector('.edit').addEventListener('click', (ev) => { ev.stopPropagation(); rename(r.id); });
      tr.querySelector('.del').addEventListener('click', (ev) => { ev.stopPropagation(); deleteRoi(r.id); });
      tr.addEventListener('click', () => select(r.id));
    }
    rows.delete(r.id);
    if (tbody.rows[i] !== tr) tbody.insertBefore(tr, tbody.rows[i] || null);
    const isPt = r.type === 'point';
    tr.querySelector('.max').textContent = fmtShort(isPt ? r.temp : r.max);
    tr.querySelector('.mean').textContent = isPt ? '' : fmtShort(r.mean);
    tr.querySelector('.min').textContent = isPt ? '' : fmtShort(r.min);
    tr.classList.toggle('selected', r.id === state.selected);
    tr.classList.toggle('locked', r.locked);
    const lock = tr.querySelector('.lock');
    if (lock.dataset.locked !== String(r.locked)) {
      lock.dataset.locked = String(r.locked);
      lock.innerHTML = r.locked ? ICON_LOCKED : ICON_UNLOCKED;
      lock.classList.toggle('on', r.locked);
      lock.title = t(r.locked ? 'lock.locked' : 'lock.unlocked');
      lock.setAttribute('aria-pressed', String(r.locked));
      tr.querySelector('.edit').disabled = r.locked;
      tr.querySelector('.del').disabled = r.locked;
    }
  });
  for (const tr of rows.values()) tr.remove();  // deleted ROIs
  if (state.selected && !list.some((r) => r.id === state.selected)) state.selected = null;
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

function drawLockIcon(x, y, locked, color) {  // 12 x 13 px
  ctx.save();
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.6;
  ctx.fillRect(x + 1, y + 6, 10, 7);
  ctx.beginPath();
  if (locked) { ctx.moveTo(x + 3.5, y + 6); ctx.lineTo(x + 3.5, y + 4); ctx.arc(x + 6, y + 4, 2.5, Math.PI, 0); ctx.lineTo(x + 8.5, y + 6); }
  else { ctx.moveTo(x + 3.5, y + 6); ctx.lineTo(x + 3.5, y + 2.5); ctx.arc(x + 6, y + 2.5, 2.5, Math.PI, 0); ctx.lineTo(x + 8.5, y + 3.5); }
  ctx.stroke();
  ctx.restore();
}

// text box on the canvas; with lock: a lock icon in front (clickable). Returns the box
function label(text, x, y, color, lock) {
  ctx.font = '600 12px system-ui, sans-serif';
  const lockW = lock === undefined ? 0 : 18;
  const w = ctx.measureText(text).width + 8 + lockW;
  const cw = canvas.clientWidth, ch = canvas.clientHeight;
  const lx = clamp(x, 0, cw - w), ly = clamp(y, 0, ch - 18);
  ctx.fillStyle = 'rgba(0,0,0,.65)';
  ctx.fillRect(lx, ly, w, 18);
  if (lockW) drawLockIcon(lx + 4, ly + 2, lock, lock ? COLOR.locked : '#9aa3ad');
  ctx.fillStyle = color;
  ctx.fillText(text, lx + 4 + lockW, ly + 13);
  return { x: lx, y: ly, w, h: 18, lockW };
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

function drawHandles(r, s) {
  ctx.save();
  for (const [hx, hy] of Object.values(handlesOf(r))) {
    ctx.fillStyle = '#ffffff';
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = 1;
    ctx.fillRect(hx * s - 4, hy * s - 4, 8, 8);
    ctx.strokeRect(hx * s - 4, hy * s - 4, 8, 8);
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
  state.labelHits = [];
  const m = state.msg;
  if (m) {
    for (const r of rois()) {
      const sel = r.id === state.selected;
      const color = sel ? COLOR.selected : r.locked ? COLOR.locked : COLOR.normal;
      strokeShape(r, s, color, false);
      let lx, ly;
      if (r.type === 'rect') { lx = r.x * s; ly = r.y * s - 19; }
      else if (r.type === 'circle') { lx = (r.cx - r.r) * s; ly = (r.cy - r.r) * s - 19; }
      else { lx = (r.x + 1) * s + 6; ly = (r.y + .5) * s - 20; }
      const val = r.type === 'point' ? r.temp : r.max;
      const box = label(`${r.id}  ${val.toFixed(1)}°`, lx, ly, color, !!r.locked);
      state.labelHits.push({ id: r.id, ...box });
      if (r.type !== 'point' && !(state.edit && state.edit.id === r.id)) {  // hottest pixel of the area
        ctx.fillStyle = COLOR.hot;
        ctx.fillRect((r.max_pos.x + .5) * s - 2, (r.max_pos.y + .5) * s - 2, 4, 4);
      }
      if (sel && !r.locked && state.tool === 'select') drawHandles(r, s);
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
      label(`${t('canvas.max')} ${m.global.max.toFixed(1)}°`, x + 10, y + 8, COLOR.hot);
    }
  }
  const preview = state.drag ? shapeFromDrag(state.tool, state.drag.start, state.drag.cur)
    : state.form && state.form.mode === 'create' ? state.form.shape : null;
  if (preview) strokeShape(preview, s, COLOR.preview, true);
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

applyLang($('lang').value);
resize();
drawScale();
showState();
connect();
requestAnimationFrame(render);
