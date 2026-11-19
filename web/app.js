"use strict";
/* EmbroideryStudio front end. The engine (server) is the single source of truth for stitches;
   this file edits the design document and draws whatever the engine returns. */
const $ = (s, r = document) => r.querySelector(s);
const PALETTE = ["#000000","#ffffff","#7f7f7f","#c8102e","#e4572e","#f28c28","#ffc72c","#f6e27a","#9bd13b","#2e9e44","#0b6e4f","#14b8a6","#4cc3ff","#2563eb","#1e3a8a","#6d28d9","#c026d3","#ec4899","#f9a8d4","#7c4a2d","#d2a679","#b08d57","#d4af37","#a8a29e"];
const HOOPS = {"100 × 100 mm":[100,100],"130 × 180 mm":[130,180],"4 × 4 in":[101.6,101.6],"5 × 7 in":[127,177.8],"200 × 300 mm":[200,300],"240 × 150 mm":[240,150]};
const THREADS = {"40wt": "40 wt (standard)", "60wt": "60 wt (fine)", "120": "120/2 (blouse / fine)"};
const FABRICS = {cotton:{pull_comp:.2,spacing:.40},silk:{pull_comp:.3,spacing:.45},georgette:{pull_comp:.35,spacing:.45},velvet:{pull_comp:.4,spacing:.38},denim:{pull_comp:.1,spacing:.40},knit:{pull_comp:.4,spacing:.42},satin_fabric:{pull_comp:.25,spacing:.45},net:{pull_comp:.3,spacing:.50},thick:{pull_comp:.15,spacing:.38}};
const DEF = {fill:{angle:45,spacing:.4,stitch_len:3.5,underlay:"tatami",pull_comp:.2,pattern:"tatami",cross_size:2,regions:true,cut_hidden:false,overlap_mm:.6,push_comp:0,expand_mm:0,comp_x:0,comp_y:0,min_row:0},satin:{width:3,spacing:.4,underlay:"auto",pull_comp:.2,auto_split:true,shorten:false,push_comp:0,style:"satin",corners:false,corner_angle:60,end_at_start:false},run:{stitch_len:2.5,style:"single",motif:"wave",motif_size:4,motif_amp:1.5},manual:{},column:{spacing:.4,underlay:"auto",pull_comp:.2,auto_split:true,shorten:false,push_comp:0,style:"satin",comp_x:0,comp_y:0,end_at_start:false},text:{spacing:1,underlay:"auto",pull_comp:.1,auto_split:true},applique:{width:2.5,spacing:.4,stitch_len:2.5},embellishment:{}};
const TOOLHINT = {select:"Click to select, drag to move, drag the white handles to edit points. Space+drag or right-drag pans, wheel zooms.",fill:"Click points of the shape. Double-click, Enter or click the first point to finish. Esc cancels.",satin:"Click along the centre line of the column. Double-click or Enter to finish.",column:"Draw the FIRST edge (double-click/Enter to finish), then the SECOND edge. Stitches zig-zag between them.",run:"Click points of the line. Double-click or Enter to finish.",rect:"Drag to draw a rectangle.",ellipse:"Drag to draw an ellipse.",text:"Click where the text should start.",bead:"Click to place beads / stones / sequins. They are NOT stitched: they appear on the production sheet. Click again to add more to the same group.",applique:"Click the outline of the appliqué patch. Double-click or Enter to finish."};

const S = { doc: newDoc(), sel: null, tool: "select", view: {x: 0, y: 0, z: 3}, mode: "beginner", vmode: "design",
  gen: null, draft: null, cursor: null, sim: {i: 0, playing: false}, hist: [], hi: -1, color: "#c8102e", font: null, n: 1 };
function newDoc() { return {name: "Untitled design", hoop: {w: 100, h: 100, margin: 3}, fabric: "cotton", objects: []}; }

/* ---------------------------------------------------------------- history / persistence */
function snap() { return JSON.stringify(S.doc); }
function commit() { S.viewDstB64 = null;
  const s = snap();
  if (S.hist[S.hi] === s) return;
  S.hist = S.hist.slice(0, S.hi + 1); S.hist.push(s); if (S.hist.length > 200) S.hist.shift(); S.hi = S.hist.length - 1;
  try { localStorage.setItem("es.autosave", s); } catch (e) {}
  regen();
}
function undo() { if (S.hi > 0) { S.hi--; S.doc = JSON.parse(S.hist[S.hi]); fixSel(); afterDocChange(); } }
function redo() { if (S.hi < S.hist.length - 1) { S.hi++; S.doc = JSON.parse(S.hist[S.hi]); fixSel(); afterDocChange(); } }
function fixSel() { if (!S.doc.objects.find(o => o.id === S.sel)) S.sel = null; if (S.multi) S.multi = new Set([...S.multi].filter(id => S.doc.objects.some(o => o.id === id))); }
function afterDocChange() { try { localStorage.setItem("es.autosave", snap()); } catch (e) {} regen(); renderAll(); }

/* ---------------------------------------------------------------- engine calls */
let regenTimer = null, regenSeq = 0;
function regen() { clearTimeout(regenTimer); regenTimer = setTimeout(doRegen, 200); }
async function doRegen() {
  const seq = ++regenSeq; const keepSim = S._keepSim; S._keepSim = false;
  if (!S.doc.objects.length) { S.gen = null; renderPanels(); draw(); return; }
  try {
    const wantFile = !!($("#sFile") && $("#sFile").checked) && S.vmode !== "design";
    const r = await fetch("/api/generate", {method: "POST", body: JSON.stringify(wantFile ? Object.assign({}, S.doc, {decoded: true}) : S.doc)});
    const j = await r.json(); if (seq !== regenSeq) return;
    if (!r.ok) { S.gen = {error: j.error}; } else { S.gen = j; S.insp = null; showInspector(); S.sim.i = Math.min(S.sim.i, j.stitches.length); if (!keepSim && !S.sim.playing && (S.vmode === "stitch" || S.vmode === "3d")) S.sim.i = j.stitches.length; }
  } catch (e) { S.gen = {error: "Engine not reachable: " + e.message}; }
  renderPanels(); draw();
}
async function post(url, body) {
  const r = await fetch(url, {method: "POST", body: JSON.stringify(body)});
  const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.statusText); return j;
}

/* ---------------------------------------------------------------- geometry helpers */
const clone = o => JSON.parse(JSON.stringify(o));
function allPts(o) {
  if (o.rings) return o.rings.flat();
  if (o.rail1) return o.rail1.concat(o.rail2);
  if (o.points) return o.points;
  if (o.type === "text" && o.path) return textStrokes(o).flat().concat(o.path);
  if (o.type === "text") { const [w, h] = textSize(o); return [[o.x, o.y], [o.x + w, o.y + h]]; }
  return [];
}
function bbox(pts) {
  if (!pts.length) return null; let a = 1e9, b = 1e9, c = -1e9, d = -1e9;
  for (const [x, y] of pts) { a = Math.min(a, x); b = Math.min(b, y); c = Math.max(c, x); d = Math.max(d, y); }
  return [a, b, c, d];
}
function mapPts(o, f) {
  if (o.rings) o.rings = o.rings.map(r => r.map(p => f(p)));
  if (o.points) o.points = o.points.map(p => f(p));
  if (o.rail1) { o.rail1 = o.rail1.map(p => f(p)); o.rail2 = o.rail2.map(p => f(p)); }
  if (o.handles) o.handles = o.handles.map(h => { const a = f([h[0], h[1]]), b = f([h[2], h[3]]); return [a[0], a[1], b[0], b[1]]; });
  if (o.entry) o.entry = f(o.entry);
  if (o.exit) o.exit = f(o.exit);
  if (o.type === "text") { const p = f([o.x, o.y]); o.x = p[0]; o.y = p[1]; if (o.path) o.path = o.path.map(q => f(q)); }
}
function textSize(o) { const f = S.font; if (!f) return [10, o.height || 10]; const k = (o.height || 10) / f.h; let w = 0;
  for (const ch of (o.text || "").toUpperCase()) w += ((ch === " " ? f.w * .7 : f.w) + f.gap) * k * ((o.params || {}).spacing || 1); return [Math.max(w - f.gap * k, 2), o.height || 10]; }
function textStrokes(o) {
  const f = S.font; if (!f) return []; const k = (o.height || 10) / f.h, sp = (o.params || {}).spacing || 1; let x = 0; const out = [];
  for (const ch of (o.text || "").toUpperCase()) {
    if (ch === " ") { x += (f.w * .7 + f.gap) * k * sp; continue; }
    const g = f.glyphs[ch]; if (!g) continue;
    for (const st of g) out.push(st.map(([px, py]) => [o.x + x + px * k, o.y + (f.h - py) * k]));
    x += (f.w + f.gap) * k * sp;
  }
  return o.path && o.path.length >= 2 ? warpToPath(out.map(st => st.map(([a, b]) => [a - o.x, b - o.y])), o.path, o.height || 10, o.align || "center") : out;
}
function warpToPath(strokes, path, h, align) {     // same maths as engine stitches.warp_to_path
  const cum = [0]; for (let i = 1; i < path.length; i++) cum.push(cum[i - 1] + Math.hypot(path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1]));
  const L = cum[cum.length - 1]; if (L < 1e-6) return strokes;
  const xs = strokes.flat().map(p => p[0]); const mn = Math.min(...xs), tw = Math.max(...xs) - mn;
  const off = (align === "start" ? 0 : align === "end" ? L - tw : (L - tw) / 2) - mn;
  const frame = t => { for (let i = 0; i < path.length - 1; i++) { const seg = cum[i + 1] - cum[i]; if ((cum[i + 1] >= t || i === path.length - 2) && seg > 1e-12) { const tx = (path[i + 1][0] - path[i][0]) / seg, ty = (path[i + 1][1] - path[i][1]) / seg, u = t - cum[i]; return [[path[i][0] + tx * u, path[i][1] + ty * u], [ty, -tx]]; } } return [path[0], [0, -1]]; };
  return strokes.map(st => st.map(([x, y]) => { const [[bx, by], [ux, uy]] = frame(x + off); const up = h - y; return [bx + ux * up, by + uy * up]; }));
}
function smooth(P, closed, n = 8) { if (P.length < 3) return P; const m = P.length, seg = closed ? m : m - 1, g = closed ? i => P[((i % m) + m) % m] : i => P[Math.max(0, Math.min(m - 1, i))]; const out = [P[0]];
  for (let i = 0; i < seg; i++) { const [a, b, c, d] = [g(i - 1), g(i), g(i + 1), g(i + 2)]; for (let k = 1; k <= n; k++) { const t = k / n; out.push([0, 1].map(j => .5 * (2 * b[j] + (-a[j] + c[j]) * t + (2 * a[j] - 5 * b[j] + 4 * c[j] - d[j]) * t * t + (-a[j] + 3 * b[j] - 3 * c[j] + d[j]) * t ** 3))); } }
  return closed ? out.slice(0, -1) : out; }
const listsOf = o => o.rings ? o.rings : o.rail1 ? [o.rail1, o.rail2] : [o.points || []];
const nVerts = o => listsOf(o).reduce((a, l) => a + l.length, 0);
function bez(P, H, closed, n = 12) {          // cubic Bezier through the nodes; H[i] = [inX, inY, outX, outY] absolute (same maths as geometry.bezier_flatten)
  const m = P.length; if (m < 2) return P; const seg = closed ? m : m - 1, out = [P[0]];
  for (let i = 0; i < seg; i++) { const a = P[i], d = P[(i + 1) % m], b = [H[i][2], H[i][3]], c = [H[(i + 1) % m][0], H[(i + 1) % m][1]];
    for (let k = 1; k <= n; k++) { const t = k / n, u = 1 - t; out.push([u ** 3 * a[0] + 3 * u * u * t * b[0] + 3 * u * t * t * c[0] + t ** 3 * d[0], u ** 3 * a[1] + 3 * u * u * t * b[1] + 3 * u * t * t * c[1] + t ** 3 * d[1]]); } }
  return closed ? out.slice(0, -1) : out;
}
function handleOffset(o, arr) { let n = 0; for (const l of listsOf(o)) { if (l === arr) return n; n += l.length; } return -1; }
const shown = (o, pts, closed) => {
  if (o.handles && o.handles.length === nVerts(o)) { const off = handleOffset(o, pts); if (off >= 0) return bez(pts, o.handles.slice(off, off + pts.length), closed); }
  return o.smooth ? smooth(pts, closed) : pts;
};
function catmullHandles(P, closed) { const m = P.length; return P.map((b, i) => { const a = (closed || i) ? P[(i - 1 + m) % m] : P[0], c = (closed || i < m - 1) ? P[(i + 1) % m] : P[m - 1], tx = (c[0] - a[0]) / 6, ty = (c[1] - a[1]) / 6; return [b[0] - tx, b[1] - ty, b[0] + tx, b[1] + ty]; }); }
function curveNodes(o) {                       // switch an object to Bezier node editing (starting from the Catmull-Rom curve it already shows)
  const closedOf = arr => o.rings ? true : (arr === o.points ? !!o.closed : false);
  o.handles = listsOf(o).flatMap(l => catmullHandles(l, closedOf(l))); delete o.smooth; commit(); renderAll();
}
const dist2 = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2;
function segDist(p, a, b) { const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy; let t = l ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l : 0; t = Math.max(0, Math.min(1, t)); return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy); }
function inRing(p, r) { let c = false; for (let i = 0, j = r.length - 1; i < r.length; j = i++) { if ((r[i][1] > p[1]) !== (r[j][1] > p[1]) && p[0] < (r[j][0] - r[i][0]) * (p[1] - r[i][1]) / (r[j][1] - r[i][1]) + r[i][0]) c = !c; } return c; }
function hit(o, p, tol) {
  if (o.hidden) return false;
  if (o.type === "fill" || o.type === "applique") return o.rings.reduce((n, r) => n + inRing(p, r), 0) % 2 === 1 || o.rings.some(r => r.some((q, i) => segDist(p, q, r[(i + 1) % r.length]) < tol));
  if (o.type === "embellishment") { const r = Math.max((o.size_mm || 4) / 2, tol); return o.points.some(q => dist2(p, q) <= r * r); }
  if (o.type === "text" && o.path) return textStrokes(o).some(st => st.some((q, i) => i < st.length - 1 && segDist(p, q, st[i + 1]) < Math.max(tol, 1)));
  if (o.type === "satin" || o.type === "run" || o.type === "manual") { const w = o.type === "satin" ? ((o.params || {}).width ?? 3) / 2 : 0; const P = o.points; for (let i = 0; i < P.length - 1; i++) if (segDist(p, P[i], P[i + 1]) < Math.max(tol, w)) return true; return false; }
  if (o.type === "column") { const R = [o.rail1, o.rail2]; if (R.some(r => r.some((q, i) => i < r.length - 1 && segDist(p, q, r[i + 1]) < tol))) return true; const ring = o.rail1.concat(o.rail2.slice().reverse()); return inRing(p, ring); }
  if (o.type === "text") { const [w, h] = textSize(o); return p[0] >= o.x - tol && p[0] <= o.x + w + tol && p[1] >= o.y - tol && p[1] <= o.y + h + tol; }
  return false;
}
const selObj = () => S.doc.objects.find(o => o.id === S.sel);
S.multi = new Set();
const selIds = () => { const ids = new Set(S.multi); if (S.sel) ids.add(S.sel); return ids; };
const selObjs = () => S.doc.objects.filter(o => selIds().has(o.id));
function selectWithGroup(id, additive) {          // selecting a member selects its whole group; additive (Shift/Ctrl) toggles
  const o = S.doc.objects.find(x => x.id === id); if (!o) return;
  const members = o.group ? S.doc.objects.filter(x => x.group === o.group).map(x => x.id) : [id];
  if (additive) { const cur = selIds(); const all = members.every(m => cur.has(m)); members.forEach(m => all ? cur.delete(m) : cur.add(m)); S.multi = cur; S.sel = cur.size ? [...cur][cur.size - 1] : null; if (S.sel) S.multi.delete(S.sel); }
  else { S.sel = id; S.multi = new Set(members.filter(m => m !== id)); }
}
function groupSelected() {
  const ids = selIds(); if (ids.size < 2) { alert("Select two or more objects first (Shift/Ctrl-click in the Objects list or Shift-click on the canvas)."); return; }
  const used = new Set(S.doc.objects.map(o => o.group).filter(Boolean)); let n = 1; while (used.has("group" + n)) n++;
  const gname = "group" + n; S.doc.objects.forEach(o => { if (ids.has(o.id)) o.group = gname; });
  const mem = S.doc.objects.filter(o => o.group === gname), at = S.doc.objects.indexOf(mem[0]);      // keep the group together in stitch order
  S.doc.objects = S.doc.objects.filter(o => o.group !== gname); S.doc.objects.splice(at, 0, ...mem); commit(); renderAll();
}
function ungroupSelected() {
  const gs = new Set(selObjs().map(o => o.group).filter(Boolean)); if (!gs.size) return;
  S.doc.objects.forEach(o => { if (gs.has(o.group)) delete o.group; }); S.multi = new Set(); commit(); renderAll();
}
const P = (o, k) => (o.params && o.params[k] !== undefined) ? o.params[k] : DEF[o.type][k];

/* ---------------------------------------------------------------- canvas */
const cv = $("#cv"), ctx = cv.getContext("2d");
function resize() { const r = cv.getBoundingClientRect(), d = devicePixelRatio || 1; cv.width = r.width * d; cv.height = r.height * d; draw(); }
const toScreen = p => [(p[0] - S.view.x) * S.view.z + cv.clientWidth / 2, (p[1] - S.view.y) * S.view.z + cv.clientHeight / 2];
const toWorld = (sx, sy) => [(sx - cv.clientWidth / 2) / S.view.z + S.view.x, (sy - cv.clientHeight / 2) / S.view.z + S.view.y];
function fit() { const h = S.doc.hoop, r = cv.getBoundingClientRect(); S.view.x = 0; S.view.y = 0; S.view.z = Math.min(r.width / (h.w + 20), r.height / (h.h + 40)) || 3; draw(); }

function pathOf(c, pts, close) { pts.forEach((p, i) => { const q = toScreen(p); i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]); }); if (close) c.closePath(); }
function drawGrid(c) {
  const h = S.doc.hoop, z = S.view.z; const a = toScreen([-h.w / 2, -h.h / 2]), b = toScreen([h.w / 2, h.h / 2]);
  c.fillStyle = "#fff"; c.fillRect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
  c.strokeStyle = "#0001"; c.lineWidth = 1; c.beginPath();
  const step = z > 6 ? 5 : 10; for (let x = Math.ceil(-h.w / 2 / step) * step; x <= h.w / 2; x += step) { const s = toScreen([x, 0]); c.moveTo(s[0], a[1]); c.lineTo(s[0], b[1]); }
  for (let y = Math.ceil(-h.h / 2 / step) * step; y <= h.h / 2; y += step) { const s = toScreen([0, y]); c.moveTo(a[0], s[1]); c.lineTo(b[0], s[1]); } c.stroke();
  c.strokeStyle = "#0003"; c.beginPath(); let s = toScreen([0, -h.h / 2]); c.moveTo(s[0], s[1]); s = toScreen([0, h.h / 2]); c.lineTo(s[0], s[1]);
  s = toScreen([-h.w / 2, 0]); c.moveTo(s[0], s[1]); s = toScreen([h.w / 2, 0]); c.lineTo(s[0], s[1]); c.stroke();
  c.strokeStyle = "#2563eb"; c.lineWidth = 2; c.strokeRect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
  const m = h.margin, a2 = toScreen([-h.w / 2 + m, -h.h / 2 + m]), b2 = toScreen([h.w / 2 - m, h.h / 2 - m]);
  c.setLineDash([5, 4]); c.lineWidth = 1; c.strokeStyle = "#2563eb99"; c.strokeRect(a2[0], a2[1], b2[0] - a2[0], b2[1] - a2[1]); c.setLineDash([]);
}
function drawObjects(c) {
  for (const o of S.doc.objects) {
    if (o.hidden) continue; const on = o.id === S.sel || S.multi.has(o.id);
    c.save(); c.lineJoin = "round"; c.lineCap = "round";
    if (o.guide) { c.setLineDash([6, 4]); c.strokeStyle = "#6b7280"; c.lineWidth = 1.2; c.beginPath(); const pts = o.rings ? null : o.points || []; if (o.rings) o.rings.forEach(r => pathOf(c, r, true)); else pathOf(c, shown(o, pts, !!o.closed), !!o.closed); c.stroke(); }
    else if (o.type === "embellishment") drawEmbellishment(c, o);
    else if (o.type === "fill" || o.type === "applique") {
      c.beginPath(); o.rings.forEach(r => pathOf(c, shown(o, r, true), true));
      c.fillStyle = o.color + (o.type === "applique" ? "99" : "cc"); c.fill("evenodd");
      c.strokeStyle = o.type === "applique" ? "#555" : "#0006"; c.setLineDash(o.type === "applique" ? [6, 4] : []); c.lineWidth = 1; c.stroke();
    } else if (o.type === "satin" || o.type === "run" || o.type === "manual") {
      c.beginPath(); pathOf(c, o.type === "manual" ? o.points : shown(o, o.points, !!o.closed), !!o.closed); c.strokeStyle = o.color + (o.type === "satin" ? "cc" : "ff");
      c.lineWidth = Math.max(1.5, (o.type === "satin" ? P(o, "width") : .5) * S.view.z); c.stroke();
      if (o.type === "manual") { c.fillStyle = o.color; for (const q of o.points) { const t = toScreen(q); c.fillRect(t[0] - 1.5, t[1] - 1.5, 3, 3); } }
    } else if (o.type === "column") {
      const ring = shown(o, o.rail1, false).concat(shown(o, o.rail2, false).slice().reverse()); c.beginPath(); pathOf(c, ring, true); c.fillStyle = o.color + "cc"; c.fill(); c.strokeStyle = "#0006"; c.lineWidth = 1; c.stroke();
      c.strokeStyle = "#fff8"; c.beginPath(); const a = shown(o, o.rail1, false), b = shown(o, o.rail2, false); for (let i = 0; i < a.length; i += 1) { const q = toScreen(a[i]), r = toScreen(b[Math.min(b.length - 1, Math.round(i * (b.length - 1) / Math.max(1, a.length - 1)))]);   /* same direction: rails both run A -> B */ c.moveTo(q[0], q[1]); c.lineTo(r[0], r[1]); } c.stroke();
    } else if (o.type === "text") {
      c.strokeStyle = o.color; c.lineWidth = Math.max(1.5, (P(o, "width") || Math.min(o.height * .16, 4)) * S.view.z);
      for (const st of textStrokes(o)) { c.beginPath(); pathOf(c, st, false); c.stroke(); }
    }
    c.restore();
    if (on) {
      const b = bbox(allPts(o)); if (b) { const a = toScreen([b[0], b[1]]), d = toScreen([b[2], b[3]]); c.strokeStyle = "#2563eb"; c.setLineDash([4, 3]); c.lineWidth = 1; c.strokeRect(a[0] - 4, a[1] - 4, d[0] - a[0] + 8, d[1] - a[1] + 8); c.setLineDash([]); }
      if (o.entry) { const q = toScreen(o.entry); c.fillStyle = "#16a34a"; c.beginPath(); c.arc(q[0], q[1], 6, 0, 7); c.fill(); c.fillStyle = "#fff"; c.font = "bold 9px sans-serif"; c.fillText("S", q[0] - 3, q[1] + 3); }
      if (o.exit) { const q = toScreen(o.exit); c.fillStyle = "#dc2626"; c.fillRect(q[0] - 6, q[1] - 6, 12, 12); c.fillStyle = "#fff"; c.font = "bold 9px sans-serif"; c.fillText("E", q[0] - 3, q[1] + 3); }
      if (o.handles && o.handles.length === nVerts(o) && S.tool === "select") { const pts = listsOf(o).flat(); c.save(); c.lineWidth = 1; o.handles.forEach((h, i) => { const n = toScreen(pts[i]), a = toScreen([h[0], h[1]]), b = toScreen([h[2], h[3]]);
        c.strokeStyle = "#f59e0b"; c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(n[0], n[1]); c.lineTo(b[0], b[1]); c.stroke(); c.fillStyle = "#f59e0b"; for (const q of [a, b]) { c.beginPath(); c.arc(q[0], q[1], 3.5, 0, 7); c.fill(); } }); c.restore(); }
      if (o.type !== "text" && S.tool === "select") for (const p of allPts(o)) { const q = toScreen(p), hollow = o.type === "embellishment"; c.strokeStyle = "#2563eb"; c.lineWidth = 1.5; c.beginPath(); c.rect(q[0] - 4, q[1] - 4, 8, 8); if (!hollow) { c.fillStyle = "#fff"; c.fill(); } c.stroke(); }
    }
  }
}
function drawEmbellishment(c, o) {
  const r = Math.max(2.5, (o.size_mm || 4) / 2 * S.view.z); c.setLineDash([]);
  for (const p of o.points) { const q = toScreen(p); c.beginPath();
    if (o.kind === "stone") { c.moveTo(q[0], q[1] - r); c.lineTo(q[0] + r, q[1]); c.lineTo(q[0], q[1] + r); c.lineTo(q[0] - r, q[1]); c.closePath(); c.fillStyle = o.color + "cc"; c.fill(); c.strokeStyle = "#0008"; c.lineWidth = 1.2; c.stroke(); }
    else { c.arc(q[0], q[1], r, 0, 7); c.fillStyle = o.color; c.fill(); c.strokeStyle = "#0008"; c.lineWidth = 1.2; c.stroke();
      if (o.kind === "sequin") { c.beginPath(); c.arc(q[0], q[1], Math.max(1, r * .22), 0, 7); c.fillStyle = "#fff"; c.fill(); } else { c.beginPath(); c.arc(q[0] - r * .3, q[1] - r * .3, r * .25, 0, 7); c.fillStyle = "#fff9"; c.fill(); } } }
}
function drawStitches(c, upto, thick) {
  const g = S.gen; if (!g || !g.stitches) return; const st = g.stitches; let prev = null, th = st.length ? st[0][3] : 0;
  const lw = Math.max(thick ? 1.2 : .7, .3 * S.view.z); c.lineWidth = lw; c.lineCap = "round"; c.lineJoin = "round";
  const showJumps = $("#sJumps") ? $("#sJumps").checked : true, showTrims = $("#sTrims") ? $("#sTrims").checked : true, jumps = new Path2D(), trims = [];
  const hid = S.simHidden && S.simHidden.size ? S.simHidden : null, ids = g.objects || [];
  let batch = [], bcol = null;
  const flush = () => { if (batch.length) { c.strokeStyle = bcol; c.stroke(batch.path); } batch = []; };
  const mk = col => { flush(); bcol = col; batch = []; batch.path = new Path2D(); };
  mk(g.threads[th] || "#000"); let last = null;
  const n = Math.min(upto, st.length);
  for (let i = 0; i < n; i++) {
    const [x, y, cmd, t, oi] = st[i]; const q = toScreen([x, y]);
    if (cmd === 3) { th = t; mk(g.threads[t] || "#000"); continue; }
    if (cmd === 2) { if (showTrims && prev) trims.push(prev); continue; }
    if (cmd === 4) continue;
    const hide = hid && oi >= 0 && hid.has(ids[oi]);
    if (cmd === 1) { if (prev && showJumps && !hide) { jumps.moveTo(prev[0], prev[1]); jumps.lineTo(q[0], q[1]); } prev = q; continue; }
    if (t !== th) { th = t; mk(g.threads[t]); }
    if (prev && !hide) { batch.path.moveTo(prev[0], prev[1]); batch.path.lineTo(q[0], q[1]); batch.push(1); }
    prev = q; last = q;
  }
  flush();
  if (showJumps) { c.save(); c.strokeStyle = "#9ca3af"; c.lineWidth = 1; c.setLineDash([4, 3]); c.stroke(jumps); c.restore(); }
  if (trims.length) { c.save(); c.strokeStyle = "#f97316"; c.lineWidth = 1.5; for (const q of trims) { c.beginPath(); c.moveTo(q[0] - 4, q[1] - 4); c.lineTo(q[0] + 4, q[1] + 4); c.moveTo(q[0] + 4, q[1] - 4); c.lineTo(q[0] - 4, q[1] + 4); c.stroke(); } c.restore(); }
  if (S.insp != null && st[S.insp]) { const q = toScreen([st[S.insp][0], st[S.insp][1]]); c.save(); c.strokeStyle = "#2563eb"; c.lineWidth = 2; c.beginPath(); c.arc(q[0], q[1], 7, 0, 7); c.stroke(); c.restore(); }
  return n > 0 && n <= st.length ? toScreen([st[Math.min(n, st.length) - 1][0], st[Math.min(n, st.length) - 1][1]]) : null;
}
function drawDensity(c) {
  const g = S.gen; if (!g || !g.stitches) return; const st = g.stitches, n = Math.min(S.sim.i, st.length), cells = new Map(); let prev = null; const shorts = [];
  for (let i = 0; i < n; i++) { const [x, y, cmd] = st[i];
    if (cmd === 0) { const k = Math.floor(x) + "," + Math.floor(y); cells.set(k, (cells.get(k) || 0) + 1); if (prev && Math.hypot(x - prev[0], y - prev[1]) < 0.4) shorts.push([x, y]); prev = [x, y]; }
    else if (cmd === 1) prev = [x, y]; else prev = null; }
  c.save(); const z = S.view.z;
  for (const [k, v] of cells) { if (v <= 10) continue; const [cx, cy] = k.split(",").map(Number), a = toScreen([cx, cy]); c.fillStyle = v > 16 ? "rgba(220,38,38,.55)" : "rgba(245,158,11,.45)"; c.fillRect(a[0], a[1], z, z); }
  c.strokeStyle = "#dc2626"; c.lineWidth = 1.5; for (const p of shorts) { const q = toScreen(p); c.beginPath(); c.arc(q[0], q[1], 4, 0, 7); c.stroke(); }
  c.restore(); S.risk = {dense: [...cells.values()].filter(v => v > 16).length, amber: [...cells.values()].filter(v => v > 10 && v <= 16).length, shorts: shorts.length};
}
function niceStep(z) { const t = 60 / z; for (const s of [1, 2, 5, 10, 20, 50, 100]) if (s >= t) return s; return 200; }
function drawRulers(c) {
  const W = cv.clientWidth, H = cv.clientHeight, step = niceStep(S.view.z), a = toWorld(0, 0), b = toWorld(W, H);
  c.save(); c.fillStyle = "#e2e8f0e6"; c.fillRect(0, 0, W, 16); c.fillRect(0, 0, 16, H); c.fillStyle = "#334155"; c.strokeStyle = "#64748b"; c.font = "10px sans-serif"; c.lineWidth = 1;
  for (let x = Math.ceil(a[0] / step) * step; x <= b[0]; x += step) { const q = toScreen([x, 0])[0]; c.beginPath(); c.moveTo(q, 10); c.lineTo(q, 16); c.stroke(); c.fillText(x + "", q + 2, 9); }
  for (let y = Math.ceil(a[1] / step) * step; y <= b[1]; y += step) { const q = toScreen([0, y])[1]; c.beginPath(); c.moveTo(10, q); c.lineTo(16, q); c.stroke(); c.save(); c.translate(9, q - 2); c.rotate(-Math.PI / 2); c.fillText(y + "", 0, 0); c.restore(); }
  c.fillText("mm", 2, 10); c.restore();
}
function updateSimBar() {
  const g = S.gen, n = g && g.stitches ? g.stitches.length : 0; $("#sPos").max = n; $("#sPos").value = S.sim.i;
  const st = g && g.stats; $("#sInfo").textContent = `${S.sim.i} / ${n}` + (st && st.width_mm ? ` · ${st.width_mm} × ${st.height_mm} mm · ${st.stitches} st · ${st.color_changes} col` : "") + (g && g.source ? (g.source === "dst-file" ? " · from DST file" : " · from plan") : "");
  const box = $("#sObjs"); if (g && g.objects && box.dataset.sig !== g.objects.join("|")) {
    box.dataset.sig = g.objects.join("|"); S.simHidden = new Set([...(S.simHidden || [])].filter(i => g.objects.includes(i)));
    box.innerHTML = g.objects.map(id => { const o = S.doc.objects.find(x => x.id === id); return `<label><input type="checkbox" data-oid="${esc(id)}" ${S.simHidden.has(id) ? "" : "checked"}> ${esc(o && o.name || id)}</label>`; }).join("") || "<small>no objects</small>";
    box.querySelectorAll("input").forEach(cb => cb.onchange = () => { cb.checked ? S.simHidden.delete(cb.dataset.oid) : S.simHidden.add(cb.dataset.oid); draw(); });
  }
}
function inspectAt(sx, sy) {
  const g = S.gen; if (!g || !g.stitches) return; const st = g.stitches, n = Math.min(S.sim.i, st.length); let best = -1, bd = 10 * 10;
  for (let i = 0; i < n; i++) { const c = st[i][2]; if (c !== 0 && c !== 1) continue; const q = toScreen([st[i][0], st[i][1]]), d = (q[0] - sx) ** 2 + (q[1] - sy) ** 2; if (d <= bd) { bd = d; best = i; } }
  S.insp = best < 0 ? null : best; showInspector(); draw();
}
function showInspector() {
  const box = $("#sInspect"), g = S.gen; if (S.insp == null || !g || !g.stitches[S.insp]) { box.hidden = true; return; }
  const i = S.insp, [x, y, c, t, oi] = g.stitches[i]; let len = "-"; for (let k = i - 1; k >= 0; k--) { const p = g.stitches[k]; if (p[2] === 0 || p[2] === 1) { len = Math.hypot(x - p[0], y - p[1]).toFixed(2) + " mm"; break; } }
  const o = oi >= 0 && g.objects ? S.doc.objects.find(q => q.id === g.objects[oi]) : null;
  box.hidden = false; box.innerHTML = `<b>Stitch #${i}</b> (${c === 0 ? "stitch" : "jump"})<br>x ${x.toFixed(2)} mm, y ${y.toFixed(2)} mm<br>length from previous ${len}<br>object ${esc(o ? (o.name || o.id) : (oi >= 0 && g.objects ? g.objects[oi] : "-"))}<br>thread <span style="display:inline-block;width:10px;height:10px;background:${esc(g.threads[t] || "#000")};border:1px solid #fff8"></span> #${t + 1}`;
}
function draw() {
  if (S.vmode === "3d") { feed3d(false); updateSimBar(); return; }
  const d = devicePixelRatio || 1; ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, cv.clientWidth, cv.clientHeight);
  drawGrid(ctx);
  if (S.vmode === "design") { drawObjects(ctx); }
  else if (S.gen && S.gen.stitches) {
    const needle = drawStitches(ctx, S.sim.i, true);
    if ($("#sDens") && $("#sDens").checked) drawDensity(ctx);
    for (const o of S.doc.objects) if (!o.hidden && (o.type === "embellishment" || o.guide)) { ctx.save(); if (o.type === "embellishment" && !o.guide) drawEmbellishment(ctx, o); else if (o.guide) { ctx.setLineDash([6, 4]); ctx.strokeStyle = "#6b7280"; ctx.beginPath(); if (o.rings) o.rings.forEach(r => pathOf(ctx, r, true)); else pathOf(ctx, o.points || [], !!o.closed); ctx.stroke(); } ctx.restore(); }
    if (needle) { ctx.fillStyle = "#ef4444"; ctx.beginPath(); ctx.arc(needle[0], needle[1], 4, 0, 7); ctx.fill(); }
  } else drawObjects(ctx);
  if (S.draft) drawDraft();
  if ($("#sRulers") && $("#sRulers").checked) drawRulers(ctx);
  updateSimBar();
}
function drawDraft() {
  const dr = S.draft, c = ctx; c.save(); c.strokeStyle = "#2563eb"; c.lineWidth = 2; c.setLineDash([5, 3]);
  if (S.colRail) { c.beginPath(); pathOf(c, S.colRail, false); c.setLineDash([]); c.stroke(); c.setLineDash([5, 3]); }
  if (dr.kind === "poly") { const pts = S.cursor ? dr.pts.concat([S.cursor]) : dr.pts; c.beginPath(); pathOf(c, pts, false); c.stroke(); c.setLineDash([]); for (const p of dr.pts) { const q = toScreen(p); c.fillStyle = "#2563eb"; c.fillRect(q[0] - 3, q[1] - 3, 6, 6); } }
  else if (dr.kind === "rect" || dr.kind === "ellipse") { const pts = shapePts(dr.kind, dr.a, dr.b); c.beginPath(); pathOf(c, pts, true); c.stroke(); }
  c.restore();
}
function shapePts(kind, a, b) {
  if (kind === "rect") return [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];
  const cx = (a[0] + b[0]) / 2, cy = (a[1] + b[1]) / 2, rx = Math.abs(b[0] - a[0]) / 2, ry = Math.abs(b[1] - a[1]) / 2;
  return Array.from({length: 48}, (_, k) => [cx + rx * Math.cos(k / 48 * 2 * Math.PI), cy + ry * Math.sin(k / 48 * 2 * Math.PI)]);
}

/* ---------------------------------------------------------------- object creation */
function addObject(o, select = true) {
  o.id = "o" + (S.n++); o.color = o.color || S.color; o.name = o.name || `${o.type[0].toUpperCase() + o.type.slice(1)} ${S.doc.objects.length + 1}`;
  const f = FABRICS[S.doc.fabric]; if (f && (o.type === "fill" || o.type === "satin")) { o.params = Object.assign({pull_comp: f.pull_comp, spacing: f.spacing}, o.params || {}); }
  S.doc.objects.push(o); if (select) S.sel = o.id; commit(); renderAll(); return o;
}
function addMany(objs) {
  objs.forEach(o => { o.id = "o" + (S.n++); o.color = o.color || S.color; o.name = o.name || `${o.type} ${S.n}`; S.doc.objects.push(o); });
  S.sel = objs.length ? objs[0].id : null; commit(); renderAll(); return objs;
}
async function renderTemplates() {
  const el = $("#tpl"); let cat = [];
  try { cat = (await (await fetch("/api/templates")).json()).templates; } catch (e) { el.innerHTML = `<div class="note">Templates unavailable (engine not reachable).</div>`; return; }
  const groups = [...new Set(cat.map(t => t.group))];
  el.innerHTML = `<div class="row"><label>Template</label><select id="tplSel">${groups.map(g => `<optgroup label="${esc(g)}">${cat.filter(t => t.group === g).map(t => `<option value="${t.id}">${esc(t.label)}</option>`).join("")}</optgroup>`).join("")}</select></div><div id="tplArgs"></div><div class="btns"><button id="tplGo">Insert</button></div><div class="note" id="tplNote"></div>`;
  const args = () => { const t = cat.find(x => x.id === $("#tplSel").value); $("#tplArgs").innerHTML = t.params.map(p => `<div class="row"><label>${esc(p.label)}</label><input type="number" data-tp="${p.key}" value="${p.default}" min="${p.min}" max="${p.max}" step="${p.step}"></div>`).join("");
    $("#tplNote").textContent = t.group.startsWith("Neckline") ? "Guide outline only: drawn dashed, never stitched. Generic proportions - adjust to your pattern." : "Stitched objects in the current thread colour."; };
  $("#tplSel").onchange = args; args();
  $("#tplGo").onclick = async () => {
    const params = {}; document.querySelectorAll("[data-tp]").forEach(i => params[i.dataset.tp] = parseFloat(i.value));
    try { const r = await post("/api/template", {id: $("#tplSel").value, params, color: S.color}); const objs = addMany(r.objects);
      const b = bbox(objs.flatMap(allPts)), h = S.doc.hoop; if (b && (b[2] - b[0] > h.w || b[3] - b[1] > h.h)) alert("The template is larger than the current hoop (" + h.w + " × " + h.h + " mm). Choose a bigger hoop under Design, or scale it down.");
    } catch (e) { alert("Template failed: " + e.message); }
  };
}
function finishDraft() {
  const dr = S.draft; S.draft = null; if (!dr) return;
  if (dr.kind === "poly") {
    const pts = dr.pts; const t = S.tool;
    if ((t === "fill" || t === "applique") && pts.length >= 3) addObject({type: t, rings: [pts]});
    else if (t === "satin" && pts.length >= 2) addObject({type: "satin", points: pts});
    else if (t === "run" && pts.length >= 2) addObject({type: "run", points: pts});
    else if (t === "column" && pts.length >= 2) {
      if (!S.colRail) { S.colRail = pts; S.draft = {kind: "poly", pts: []}; $("#hint").textContent = "Now draw the SECOND edge of the column."; draw(); return; }
      addObject({type: "column", rail1: S.colRail, rail2: pts}); S.colRail = null;
    }
  } else if (dr.kind === "rect" || dr.kind === "ellipse") {
    if (Math.abs(dr.a[0] - dr.b[0]) > 1 && Math.abs(dr.a[1] - dr.b[1]) > 1) addObject({type: "fill", rings: [shapePts(dr.kind, dr.a, dr.b)]});
  }
  draw();
}
const snapP = (p, force) => ($("#snap").checked && !force) ? [Math.round(p[0]), Math.round(p[1])] : p;

/* ---------------------------------------------------------------- pointer */
let drag = null, spaceDown = false;
function evP(e) { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
cv.addEventListener("contextmenu", e => e.preventDefault());
cv.addEventListener("wheel", e => { e.preventDefault(); const [sx, sy] = evP(e); const w0 = toWorld(sx, sy); S.view.z = Math.max(.5, Math.min(60, S.view.z * (e.deltaY < 0 ? 1.15 : 1 / 1.15))); const w1 = toWorld(sx, sy); S.view.x += w0[0] - w1[0]; S.view.y += w0[1] - w1[1]; draw(); }, {passive: false});
cv.addEventListener("pointerdown", e => {
  cv.setPointerCapture(e.pointerId); const [sx, sy] = evP(e); const w = toWorld(sx, sy);
  if (e.button === 1 || e.button === 2 || spaceDown) { drag = {type: "pan", sx, sy, vx: S.view.x, vy: S.view.y}; return; }
  const t = S.tool;
  if (S.pick) { const o = selObj(); if (o) { o[S.pick] = snapP(w, e.altKey).map(v => +v.toFixed(2)); commit(); } S.pick = null; renderAll(); return; }
  if (S.vmode === "stitch" && t === "select") { inspectAt(sx, sy); return; }
  if (t === "select") {
    const o = selObj();
    if (o && o.type !== "text") { const tolPx = 8 / S.view.z; const lists = o.rings ? o.rings : o.rail1 ? [o.rail1, o.rail2] : [o.points];
      if (o.handles && o.handles.length === nVerts(o)) for (let gi = 0; gi < o.handles.length; gi++) for (const wh of [0, 2]) if (dist2([o.handles[gi][wh], o.handles[gi][wh + 1]], w) < tolPx * tolPx) {
        if (e.altKey) { const n = lists.flat()[gi]; o.handles[gi][wh] = n[0]; o.handles[gi][wh + 1] = n[1]; commit(); renderAll(); return; }       // Alt-click a handle = make that side a corner
        drag = {type: "handle", gi, wh}; return; }
      let base = 0; for (const arr of lists) { for (let i = 0; i < arr.length; i++) if (dist2(arr[i], w) < tolPx * tolPx) { drag = {type: "vertex", arr, i, gi: base + i}; return; } base += arr.length; } }
    const tol = 5 / S.view.z; let found = null;
    for (let i = S.doc.objects.length - 1; i >= 0; i--) if (hit(S.doc.objects[i], w, tol)) { found = S.doc.objects[i]; break; }
    if (found) selectWithGroup(found.id, e.shiftKey || e.ctrlKey || e.metaKey); else { S.sel = null; S.multi = new Set(); }
    renderAll();
    if (found) drag = {type: "move", last: w, moved: false}; return;
  }
  if (t === "rect" || t === "ellipse") { const p = snapP(w, e.altKey); S.draft = {kind: t, a: p, b: p}; drag = {type: "shape"}; return; }
  if (t === "text") { const p = snapP(w, e.altKey); const o = addObject({type: "text", text: "TEXT", height: 10, x: p[0], y: p[1]}); S.tool = "select"; setTool("select"); return; }
  if (t === "bead") { const p = snapP(w, e.altKey); let o = selObj(); if (!o || o.type !== "embellishment") o = addObject({type: "embellishment", kind: "bead", size_mm: 4, color: "#d4af37", points: []}, true);
    o.points.push([p[0], p[1]]); commit(); renderAll(); return; }
  const p = snapP(w, e.altKey);
  if (!S.draft) S.draft = {kind: "poly", pts: []};
  const pts = S.draft.pts;
  if ((t === "fill" || t === "applique") && pts.length >= 3 && dist2(p, pts[0]) < (8 / S.view.z) ** 2) { finishDraft(); return; }
  if (!pts.length || dist2(p, pts[pts.length - 1]) > 1e-6) pts.push(p); draw();
});
cv.addEventListener("dblclick", e => { if (S.draft && S.draft.kind === "poly") { finishDraft();  /* the 2nd click of a double-click is de-duplicated in pointerdown, so no point to drop */ } });
cv.addEventListener("pointermove", e => {
  const [sx, sy] = evP(e); const w = toWorld(sx, sy); S.cursor = snapP(w, e.altKey);
  $("#hint").textContent = TOOLHINT[S.tool] + `   [${w[0].toFixed(1)}, ${w[1].toFixed(1)} mm]`;
  if (!drag) { if (S.draft) draw(); return; }
  if (drag.type === "pan") { S.view.x = drag.vx - (sx - drag.sx) / S.view.z; S.view.y = drag.vy - (sy - drag.sy) / S.view.z; }
  else if (drag.type === "move") { let dx = w[0] - drag.last[0], dy = w[1] - drag.last[1]; selObjs().forEach(o => mapPts(o, p => [p[0] + dx, p[1] + dy])); drag.last = w; drag.moved = true; }
  else if (drag.type === "vertex") { const p = snapP(w, e.altKey), o = selObj(); const dx = p[0] - drag.arr[drag.i][0], dy = p[1] - drag.arr[drag.i][1];
    if (o && o.handles && o.handles.length === nVerts(o) && drag.gi !== undefined) { const h = o.handles[drag.gi]; h[0] += dx; h[1] += dy; h[2] += dx; h[3] += dy; }     // handles travel with their node
    drag.arr[drag.i][0] = p[0]; drag.arr[drag.i][1] = p[1]; drag.moved = true; }
  else if (drag.type === "handle") { const o = selObj(), p = snapP(w, e.shiftKey), h = o.handles[drag.gi], n = listsOf(o).flat()[drag.gi]; h[drag.wh] = p[0]; h[drag.wh + 1] = p[1];
    if (!e.altKey) { const ow = drag.wh === 0 ? 2 : 0; h[ow] = 2 * n[0] - p[0]; h[ow + 1] = 2 * n[1] - p[1]; } drag.moved = true; }       // smooth node: the opposite handle mirrors (hold Alt for a cusp)
  else if (drag.type === "shape") S.draft.b = S.cursor;
  draw();
});
cv.addEventListener("pointerup", () => {
  if (!drag) return; const d = drag; drag = null;
  if (d.type === "shape") finishDraft(); else if (d.moved) { commit(); renderPanels(); }
  draw();
});
addEventListener("keydown", e => {
  if (!$("#lib").hidden) { if (e.key === "Escape") closeLibrary(); return; }
  const tag = (e.target.tagName || "").toLowerCase(); if (tag === "input" || tag === "select" || tag === "textarea") { if (e.key === "Escape") e.target.blur(); return; }
  if (e.key === " ") { spaceDown = true; e.preventDefault(); return; }
  const k = e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && k === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if ((e.ctrlKey || e.metaKey) && k === "y") { e.preventDefault(); redo(); return; }
  if ((e.ctrlKey || e.metaKey) && k === "s") { e.preventDefault(); saveProject(); return; }
  if ((e.ctrlKey || e.metaKey) && k === "g") { e.preventDefault(); e.shiftKey ? ungroupSelected() : groupSelected(); return; }
  if ((e.ctrlKey || e.metaKey) && k === "d") { e.preventDefault(); duplicate(0, 0); return; }
  if (e.key === "Escape") { S.draft = null; S.colRail = null; S.pick = null; draw(); return; }
  if ((S.vmode === "stitch" || S.vmode === "3d") && (e.key === "ArrowLeft" || e.key === "ArrowRight") && S.gen && S.gen.stitches) {
    e.preventDefault(); S.sim.playing = false; const d = (e.shiftKey ? 10 : 1) * (e.key === "ArrowLeft" ? -1 : 1); S.sim.i = Math.max(0, Math.min(S.gen.stitches.length, S.sim.i + d));
    if (S.insp != null) { S.insp = Math.max(0, Math.min(S.gen.stitches.length - 1, S.sim.i - 1)); showInspector(); } draw(); return;
  }
  if (e.key === "Enter" && S.draft) { finishDraft(); return; }
  if ((e.key === "Delete" || e.key === "Backspace") && S.sel) { deleteSel(); return; }
  const map = {v: "select", f: "fill", s: "satin", c: "column", r: "run", t: "text", a: "applique", e: "bead"};
  if (map[k] && !e.ctrlKey) { setTool(map[k]); return; }
  if (k === "p") { togglePlay(); return; }
  if (e.key === "0") { fit(); return; }
  const o = selObj(); if (o && e.key.startsWith("Arrow")) { e.preventDefault(); const st = e.shiftKey ? 5 : .5; const d = {ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, -st], ArrowDown: [0, st]}[e.key]; mapPts(o, p => [p[0] + d[0], p[1] + d[1]]); commit(); renderAll(); }
});
addEventListener("keyup", e => { if (e.key === " ") spaceDown = false; });

/* ---------------------------------------------------------------- operations */
function deleteSel() { const ids = selIds(); S.doc.objects = S.doc.objects.filter(o => !ids.has(o.id)); S.sel = null; S.multi = new Set(); commit(); renderAll(); }
function duplicate(dx, dy, n = 1) {
  const o = selObj(); if (!o) return; let last = null;
  for (let i = 1; i <= n; i++) { const c = clone(o); c.id = "o" + (S.n++); c.name = o.name + " copy"; mapPts(c, p => [p[0] + (dx || 3) * i, p[1] + (dy || 3) * i]); S.doc.objects.push(c); last = c; }
  S.sel = last.id; commit(); renderAll();
}
function transformSel(fn, textOk = true) {
  const o = selObj(); if (!o) return; if (o.type === "text" && !textOk) { alert("Lettering cannot be flipped or rotated yet; move or resize it instead."); return; }
  const b = bbox(allPts(o)), cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2; mapPts(o, p => fn(p, cx, cy)); commit(); renderAll();
}
function scaleSel(pct) { const o = selObj(); if (!o) return; const f = pct / 100, b = bbox(allPts(o)), cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
  if (o.type === "text") { o.height = +(o.height * f).toFixed(2); } else mapPts(o, p => [cx + (p[0] - cx) * f, cy + (p[1] - cy) * f]);
  if (o.params && o.params.width) o.params.width = +(o.params.width * f).toFixed(2); commit(); renderAll(); }
function rotateSel(deg) { const o = selObj(); if (!o || o.type === "text" || !deg) return; const r = deg * Math.PI / 180, cs = Math.cos(r), sn = Math.sin(r);
  transformSel((p, cx, cy) => [cx + (p[0] - cx) * cs - (p[1] - cy) * sn, cy + (p[0] - cx) * sn + (p[1] - cy) * cs], false); }
function nonUniform(fx, fy) { const o = selObj(); if (!o) return; const b = bbox(allPts(o)), cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
  if (o.type === "text") { o.height = +(o.height * fy).toFixed(2); } else mapPts(o, p => [cx + (p[0] - cx) * fx, cy + (p[1] - cy) * fy]); commit(); renderAll(); }
function convertTargets(o) { return {fill: ["run", "satin", "column (auto rails)"], applique: ["fill", "column (auto rails)"], satin: ["run", "fill"], run: ["satin", "fill"], column: ["fill"]}[o.type] || []; }
async function convertSel(to) {
  const o = selObj(); if (!o) return;
  if (to.startsWith("column")) {
    try { const r = await post("/api/tools/column-from-outline", {ring: o.rings[0]});
      const n = {id: o.id, name: o.name, color: o.color, type: "column", rail1: r.rail1, rail2: r.rail2}; S.doc.objects[S.doc.objects.findIndex(x => x.id === o.id)] = n; commit(); renderAll();
      if (r.width_mm > 7) alert(`Converted. The column averages ${r.width_mm} mm wide; long stitches are split automatically (Pro: Auto-split).`);
    } catch (e) { alert("Cannot make a satin column from this shape:\n" + e.message); renderProps(); }
    return;
  } let n = {id: o.id, name: o.name, color: o.color, type: to};
  const ring = o.rings ? o.rings[0] : o.rail1 ? o.rail1.concat(o.rail2.slice().reverse()) : o.points;
  if (to === "fill") { if (ring.length < 3) { alert("A fill needs at least 3 points."); return; } n.rings = [ring.map(p => p.slice())]; }
  else { n.points = (o.rings ? o.rings[0].concat([o.rings[0][0]]) : ring).map(p => p.slice()); if (to === "satin") n.params = {width: 2.5}; }
  if (o.smooth) n.smooth = true; S.doc.objects[S.doc.objects.findIndex(x => x.id === o.id)] = n; commit(); renderAll();
}
function optimiseColours() {
  const order = []; S.doc.objects.forEach(o => { if (!order.includes(o.color)) order.push(o.color); });
  const sorted = order.flatMap(c => S.doc.objects.filter(o => o.color === c));
  if (sorted.every((o, i) => o === S.doc.objects[i])) { alert("Colour order is already optimal."); return; }
  if (!confirm("Group objects by colour to cut colour changes?\nThis changes stitching order: anything meant to sit on top of another colour may now stitch underneath. Check the Design and Stitches views afterwards (Undo restores).")) return;
  S.doc.objects = sorted; commit(); renderAll();
}
function moveOrder(id, dir) { const a = S.doc.objects, i = a.findIndex(o => o.id === id), j = i + dir; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; commit(); renderAll(); }
function centerAll() { const pts = S.doc.objects.flatMap(allPts), b = bbox(pts); if (!b) return; const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2; S.doc.objects.forEach(o => mapPts(o, p => [p[0] - cx, p[1] - cy])); commit(); renderAll(); }
function outline() { /* convert selected fill to a satin/run border following its first ring */
  const o = selObj(); if (!o || !o.rings) return; const ring = o.rings[0].concat([o.rings[0][0]]);
  addObject({type: "satin", points: ring, color: o.color, params: {width: 2}, name: o.name + " border"}); }

/* ---------------------------------------------------------------- import / project */
function fitObjects(objs, targetW) {
  const b = bbox(objs.flatMap(allPts)); if (!b) return; const w = b[2] - b[0], h = b[3] - b[1], hp = S.doc.hoop;
  let f = targetW ? targetW / w : 1; const mx = hp.w - 2 * hp.margin, my = hp.h - 2 * hp.margin; f = Math.min(f, mx / w, my / h);
  const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
  objs.forEach(o => { mapPts(o, p => [(p[0] - cx) * f, (p[1] - cy) * f]); if (o.params && o.params.width) o.params.width = +(o.params.width * f).toFixed(2); if (o.type === "text") o.height *= f; });
  return f;
}
function askImport() {
  return new Promise(resolve => {
    const dlg = $("#dlgImport"); $("#impW").value = Math.round(S.doc.hoop.w * .7); $("#impReport").hidden = true;
    dlg.onclose = () => resolve(dlg.returnValue === "go" ? {w: parseFloat($("#impW").value), c: parseInt($("#impC").value) || 6, q: $("#impQ").value, e: $("#impE").value} : null);
    dlg.showModal();
  });
}
function importSummary(r, scaled) {
  const l = [];
  l.push("Imported " + ((r.objectsN) || 0) + " objects, " + (r.colours_used || 0) + " colour(s)" + (r.colours_merged ? " (" + r.colours_merged + " near-duplicate shade(s) merged)" : "") + ".");
  if (r.dpi) l.push("Source resolution ≈ " + r.dpi + " dpi at this size" + (r.dpi < 150 ? " – low; edges may be rough, use a larger image." : "."));
  const e = r.enhance;
  if (e) l.push(e.skipped ? "Enhancer: skipped (" + e.skipped + ")." : "Enhancer: " + e.source_px.join("×") + " → " + e.result_px.join("×") + " px (" + e.steps.join(", ") + ")" + (e.photographic ? " – photo: only lightly sharpened." : "."));
  return l;
}
function objArea(o) { if (!o.rings) return null; const ar = r => Math.abs(r.reduce((a, p, i) => { const q = r[(i + 1) % r.length]; return a + p[0] * q[1] - q[0] * p[1]; }, 0) / 2); return Math.max(0, ar(o.rings[0]) - o.rings.slice(1).reduce((a, r) => a + ar(r), 0)); }
function reviewRegions(objs, extent) {      // segmentation review: keep / recolour / merge colours / drop specks BEFORE anything is stitched
  return new Promise(resolve => {
    const dlg = $("#dlgSeg"), by = {}; objs.forEach(o => { const c = (o.color || "#000000").toLowerCase(); (by[c] = by[c] || []).push(o); });
    const cols = Object.keys(by).sort((a, b) => by[b].length - by[a].length);
    $("#segRows").innerHTML = cols.map((c, i) => `<div class="row" data-c="${c}"><label><input type="checkbox" class="sk" checked> <i style="display:inline-block;width:14px;height:14px;background:${c};border:1px solid #0004;vertical-align:middle"></i> ${by[c].length} region(s), ${Math.round(by[c].reduce((a, o) => a + (objArea(o) || 0), 0))} mm²</label><input type="color" class="sc" value="${c}"></div>`).join("");
    const off = new Set(), cvs = $("#segCv"), g = cvs.getContext("2d");
    const pts = objs.flatMap(o => (o.rings ? o.rings.flat() : (o.points || []))), xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
    const x0 = Math.min(...xs), y0 = Math.min(...ys), k = Math.min((cvs.width - 10) / Math.max(1e-6, Math.max(...xs) - x0), (cvs.height - 10) / Math.max(1e-6, Math.max(...ys) - y0));
    const tp = p => [5 + (p[0] - x0) * k, 5 + (p[1] - y0) * k], fp = q => [(q[0] - 5) / k + x0, (q[1] - 5) / k + y0];
    const colOf = o => { const row = [...$("#segRows").querySelectorAll(".row")].find(r => r.dataset.c === (o.color || "#000000").toLowerCase()); return row ? row.querySelector(".sc").value : o.color; };
    const paint = () => { g.clearRect(0, 0, cvs.width, cvs.height); g.fillStyle = "#fff"; g.fillRect(0, 0, cvs.width, cvs.height);
      objs.forEach((o, i) => { const row = [...$("#segRows").querySelectorAll(".row")].find(r => r.dataset.c === (o.color || "#000000").toLowerCase()); const on = !off.has(i) && (!row || row.querySelector(".sk").checked);
        g.globalAlpha = on ? 1 : .15; g.beginPath();
        if (o.rings) { o.rings.forEach(r => r.forEach((p, j) => { const q = tp(p); j ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]); if (j === r.length - 1) g.closePath(); })); g.fillStyle = colOf(o); g.fill("evenodd"); }
        else { (o.points || []).forEach((p, j) => { const q = tp(p); j ? g.lineTo(q[0], q[1]) : g.moveTo(q[0], q[1]); }); g.strokeStyle = colOf(o); g.lineWidth = 2; g.stroke(); } });
      g.globalAlpha = 1; paintStrokes(); };
    const strokes = []; let brush = false, painting = false;
    const syncBrush = () => { $("#segBrush").textContent = "Erase brush: " + (brush ? "on" : "off"); $("#segApply").textContent = `Apply erase (${strokes.length})`; $("#segApply").disabled = !strokes.length; $("#segUndoErase").disabled = !strokes.length; cvs.style.cursor = brush ? "crosshair" : "pointer"; };
    const paintStrokes = () => { g.save(); g.fillStyle = "rgba(220,38,38,.35)"; strokes.forEach(([x, y, r]) => { const q = tp([x, y]); g.beginPath(); g.arc(q[0], q[1], r * k, 0, 7); g.fill(); }); g.restore(); };
    const addStroke = ev => { const r = cvs.getBoundingClientRect(), w = fp([(ev.clientX - r.left) * cvs.width / r.width, (ev.clientY - r.top) * cvs.height / r.height]); strokes.push([+w[0].toFixed(2), +w[1].toFixed(2), +$("#segBrushR").value]); paint(); syncBrush(); };
    $("#segBrush").onclick = () => { brush = !brush; syncBrush(); };
    $("#segUndoErase").onclick = () => { strokes.pop(); paint(); syncBrush(); };
    $("#segApply").onclick = () => { dlg.dataset.redo = JSON.stringify(strokes); dlg.close("redo"); };
    cvs.onpointerdown = ev => { if (!brush) return; painting = true; cvs.setPointerCapture(ev.pointerId); addStroke(ev); };
    cvs.onpointermove = ev => { if (brush && painting) addStroke(ev); };
    cvs.onpointerup = () => { painting = false; };
    cvs.onclick = ev => { if (brush) return; const r = cvs.getBoundingClientRect(), w = fp([(ev.clientX - r.left) * cvs.width / r.width, (ev.clientY - r.top) * cvs.height / r.height]);
      for (let i = objs.length - 1; i >= 0; i--) { const o = objs[i]; let hitIt = false;
        if (o.rings) hitIt = o.rings.reduce((n, rg) => n + inRing(w, rg), 0) % 2 === 1; else { const P = o.points || []; for (let j = 0; j < P.length - 1; j++) if (segDist(w, P[j], P[j + 1]) < 1.5 / Math.max(k, .2) + 1) hitIt = true; }
        if (hitIt) { off.has(i) ? off.delete(i) : off.add(i); break; } }
      sum(); };
    const result = () => { const out = [], min = +$("#segMin").value; $("#segRows").querySelectorAll(".row").forEach(row => { if (!row.querySelector(".sk").checked) return; const nc = row.querySelector(".sc").value;
      by[row.dataset.c].forEach(o => { if (off.has(objs.indexOf(o))) return; const a = objArea(o); if (a !== null && a < min) return; out.push(Object.assign({}, o, {color: nc})); }); }); return out; };
    const sum = () => { $("#segMinV").textContent = $("#segMin").value; const r = result(); $("#segSum").textContent = `${r.length} of ${objs.length} regions will be imported. Click a region in the preview to leave it out (click again to restore).`; paint(); };
    $("#segMin").oninput = sum; $("#segRows").onchange = sum; sum();
    dlg.onclose = () => resolve(dlg.returnValue === "go" ? result() : dlg.returnValue === "redo" ? {redo: JSON.parse(dlg.dataset.redo || "[]")} : null); dlg.showModal();
  });
}
/* ---------------------------------------------------------------- fidelity workspace */
const FID = {mode: "orig", z: 1, x: 0, y: 0, rep: null, imgs: {}};
function fidApply() {
  $("#fidPan").style.transform = `translate(${FID.x}px,${FID.y}px) scale(${FID.z})`;
  const A = $("#fidA"), B = $("#fidB"), m = FID.mode, W = A.naturalWidth || 1, H = A.naturalHeight || 1, scale = 640 / Math.max(W, 1);
  [A, B].forEach(i => { i.style.width = (W * scale) + "px"; i.style.height = (H * scale) + "px"; });
  A.src !== FID.imgs.orig && (A.src = FID.imgs.orig); B.style.left = "0"; B.style.clipPath = "none"; A.style.display = "block"; B.style.display = "block"; $("#fidSlideBox").hidden = m !== "slide";
  const second = m === "diff" ? FID.imgs.diff : FID.imgs.over;
  if (m === "orig") B.style.display = "none"; else { if (B.src !== second) B.src = second; }
  if (m === "over" || m === "diff") A.style.display = "none";
  if (m === "side") { B.style.left = (W * scale + 8) + "px"; }
  if (m === "slide") { const v = +$("#fidSlide").value; B.style.clipPath = `inset(0 0 0 ${v}%)`; }
}
function fidFit() { const st = $("#fidStage"), A = $("#fidA"), W = (A.naturalWidth ? 640 : 640) * (FID.mode === "side" ? 2.02 : 1), H = (A.naturalHeight / Math.max(A.naturalWidth, 1)) * 640; FID.z = Math.min(st.clientWidth / W, st.clientHeight / H) * .98; FID.x = (st.clientWidth - W * FID.z) / 2; FID.y = (st.clientHeight - H * FID.z) / 2; fidApply(); }
function fidHighlight(it) {
  const hi = $("#fidHi"), A = $("#fidA"); if (!it || !FID.rep) { hi.hidden = true; return; } const k = 640 / FID.rep.width_mm, b = it.bbox_mm;
  hi.style.left = (b[0] * k - 3) + "px"; hi.style.top = (b[1] * k - 3) + "px"; hi.style.width = ((b[2] - b[0]) * k + 6) + "px"; hi.style.height = ((b[3] - b[1]) * k + 6) + "px"; hi.hidden = false;
  const st = $("#fidStage"), z = Math.min(8, Math.max(1.5, Math.min(st.clientWidth, st.clientHeight) / Math.max(30, Math.max(b[2] - b[0], b[3] - b[1]) * k * 4)));
  FID.z = z; FID.x = st.clientWidth / 2 - (b[0] + b[2]) / 2 * k * z; FID.y = st.clientHeight / 2 - (b[1] + b[3]) / 2 * k * z; fidApply();
}
function fidRenderInv() {
  const f = $("#fidFilter").value, rows = (FID.rep.inventory || []).filter(r => !f || r.status === f).slice(0, 400);
  $("#fidInv").innerHTML = `<table><tr><th>id</th><th>size mm</th><th>status</th><th>stitch</th><th>reason</th></tr>${rows.map(r => `<tr data-id="${r.id}"><td>${r.id}</td><td>${r.size_mm[0]}×${r.size_mm[1]}</td><td>${esc(r.status)}</td><td>${esc(r.strategy)}</td><td title="${esc(r.reason)}">${esc(r.reason.slice(0, 70))}</td></tr>`).join("")}</table>`;
  $("#fidInv").querySelectorAll("tr[data-id]").forEach(tr => tr.onclick = () => fidHighlight(FID.rep.inventory.find(x => x.id === tr.dataset.id)));
}
async function openFidelity() {
  if (!S.imgSrc) { alert("Import a PNG or JPEG image first - the fidelity report compares the exported DST with the original upload."); return; }
  const dlg = $("#dlgFid"); $("#fidVerdict").innerHTML = "Running the nine validation passes…"; $("#fidPasses").innerHTML = ""; $("#fidRisks").innerHTML = ""; $("#fidInv").innerHTML = ""; dlg.showModal();
  try {
    const o = S.imgSrc.opts, useDoc = S.doc.objects.some(x => /^img\d+$/.test(x.id));
    const rep = await post("/api/image/validate", Object.assign({data: S.imgSrc.b64, width_mm: o.w, colors: o.c, quality: o.q, enhance: o.e, images: true, hoop_w: S.doc.hoop.w, hoop_h: S.doc.hoop.h, name: S.doc.name}, useDoc ? {design: S.doc} : {}));
    FID.rep = rep; FID.imgs = {orig: S.imgSrc.url, over: "data:image/png;base64," + rep.derived_images["overlay.png"], diff: "data:image/png;base64," + rep.derived_images["difference.png"]};
    $("#fidVerdict").innerHTML = `<span class="vd ${rep.software_validation}">Software validation: ${rep.software_validation.replace(/_/g, " ")}</span> <span class="vd FAILED" style="background:#6b7280">Physical machine validation: ${esc(rep.physical_validation.split(" - ")[0])}</span>`;
    $("#fidDisc").textContent = rep.disclaimer;
    $("#fidPasses").innerHTML = rep.passes.map(p => `<div class="fp ${p.result}"><b>${p.pass}. ${p.result}</b><span>${esc(p.name)}<br><small>${esc(p.detail)}</small></span></div>`).join("");
    $("#fidRisks").innerHTML = rep.remaining_risks.map(r => `<li>${esc(r)}</li>`).join("") || "<li>none recorded</li>";
    fidRenderInv(); FID.mode = "orig"; document.querySelectorAll("#fidMode button").forEach(b => b.classList.toggle("on", b.dataset.m === "orig"));
    const A = $("#fidA"); A.onload = () => { fidFit(); }; A.src = FID.imgs.orig; if (A.complete) fidFit();
  } catch (e) { $("#fidVerdict").textContent = "Validation failed: " + e.message; }
}
async function fidelityBundle() {
  const o = S.imgSrc.opts, r = await fetch("/api/image/bundle", {method: "POST", body: JSON.stringify({data: S.imgSrc.b64, width_mm: o.w, colors: o.c, quality: o.q, enhance: o.e, hoop_w: S.doc.hoop.w, hoop_h: S.doc.hoop.h, name: S.doc.name})});
  if (!r.ok) { const j = await r.json().catch(() => ({})); alert("Bundle not produced: " + (j.error || r.statusText)); return; }
  const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = (S.doc.name || "design").replace(/[^\w-]+/g, "_") + "-image-to-dst.zip"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
(() => {
  const st = $("#fidStage"); let drag = null;
  st.addEventListener("wheel", e => { e.preventDefault(); const r = st.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, f = e.deltaY < 0 ? 1.2 : 1 / 1.2; FID.x = mx - (mx - FID.x) * f; FID.y = my - (my - FID.y) * f; FID.z = Math.max(.2, Math.min(40, FID.z * f)); fidApply(); }, {passive: false});
  st.addEventListener("pointerdown", e => { drag = {x: e.clientX - FID.x, y: e.clientY - FID.y}; st.setPointerCapture(e.pointerId); st.style.cursor = "grabbing"; });
  st.addEventListener("pointermove", e => { if (drag) { FID.x = e.clientX - drag.x; FID.y = e.clientY - drag.y; fidApply(); } });
  st.addEventListener("pointerup", () => { drag = null; st.style.cursor = "grab"; });
  document.querySelectorAll("#fidMode button").forEach(b => b.onclick = () => { FID.mode = b.dataset.m; document.querySelectorAll("#fidMode button").forEach(x => x.classList.toggle("on", x === b)); fidApply(); fidFit(); });
  $("#fidSlide").oninput = fidApply; $("#fidFit").onclick = fidFit; $("#fidFilter").onchange = () => FID.rep && fidRenderInv(); $("#fidClose").onclick = () => $("#dlgFid").close(); $("#fidBundle").onclick = fidelityBundle;
})();
async function importFile(file) {
  if (/\.pdf$/i.test(file.name) || file.type === "application/pdf") { alert("PDF import is not currently supported. Please export your artwork as SVG, PNG or JPG."); return; }
  try {
    let res;
    if (/\.svg$/i.test(file.name)) { res = await post("/api/import/svg", {svg: await file.text()}); }
    else {
      const o = await askImport(); if (!o || !o.w) return;
      const buf = new Uint8Array(await file.arrayBuffer()); let bin = ""; for (let i = 0; i < buf.length; i += 8192) bin += String.fromCharCode(...buf.subarray(i, i + 8192));
      S.imgSrc = {name: file.name, b64: btoa(bin), url: URL.createObjectURL(file), opts: o};       // the original stays in memory exactly as uploaded
      let erase = [];
      for (;;) {                                   // review -> (optional) erase pixels in the source image -> re-detect -> review again
        res = await post("/api/import/raster", {data: btoa(bin), width_mm: o.w, colors: o.c, quality: o.q, enhance: o.e, erase});
        if (res.report) { res.report.objectsN = res.objects.length; res.notes = importSummary(res.report).concat(res.notes || []); }
        if (!res.objects.length) break;
        const kept = await reviewRegions(res.objects);
        if (!kept) return;
        if (kept.redo) { erase = erase.concat(kept.redo); continue; }
        res.objects = kept; break;
      }
    }
    if (!res.objects.length) { alert((res.notes || []).join("\n") || "Nothing to digitize. For images, use flat-colour artwork on a plain background."); return; }
    res.objects.forEach(o => { o.id = "o" + (S.n++); o.name = o.name || o.id; });
    const f = fitObjects(res.objects, null); S.doc.objects.push(...res.objects); S.sel = null; commit(); renderAll(); fit();
    const msg = (res.notes || []).concat(f && f < 1 ? ["Artwork was scaled down to fit the hoop."] : []); if (msg.length) alert(msg.join("\n"));
  } catch (e) { alert("Import failed: " + e.message); }
}
function download(name, data, type) { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([data], {type})); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); }
function saveProject() { download((S.doc.name || "design").replace(/[^\w-]+/g, "_") + ".esproj", JSON.stringify({app: "EmbroideryStudio", version: 1, doc: S.doc}, null, 1), "application/json"); }
function loadDoc(d) { S.doc = Object.assign(newDoc(), d); S.doc.hoop = Object.assign({margin: 3}, S.doc.hoop); S.sel = null; S.n = 1 + Math.max(0, ...S.doc.objects.map(o => parseInt(String(o.id).replace(/\D/g, "")) || 0)); S.hist = []; S.hi = -1; commit(); renderAll(); fit(); }
async function exportDst() {
  const r = await fetch("/api/export/dst", {method: "POST", body: JSON.stringify(S.doc)});
  if (!r.ok) { const j = await r.json(); alert("This design cannot be exported yet:\n\n" + (j.issues || [{message: j.error}]).filter(i => !i.severity || i.severity === "error").map(i => "• " + friendlyLine(i)).join("\n")); return; }
  download((S.doc.name || "design").replace(/[^\w-]+/g, "_") + ".dst", await r.arrayBuffer(), "application/octet-stream");
  alert("DST downloaded." + ((S.gen && S.gen.issues || []).some(i => i.severity === "warning") ? " There are warnings (see Checks)." : "") + "\n\nThis software has not been validated on a physical machine yet. Stitch a test sample on your real fabric and stabiliser before production.");
}
function renderPreview(px) {
  const off = document.createElement("canvas"); off.width = off.height = px; const c = off.getContext("2d"), h = S.doc.hoop;
  const v0 = S.view;
  Object.defineProperty(cv, "clientWidth", {value: px, configurable: true}); Object.defineProperty(cv, "clientHeight", {value: px, configurable: true});
  try { S.view = {x: 0, y: 0, z: (px - 40) / Math.max(h.w, h.h)}; c.fillStyle = "#fff"; c.fillRect(0, 0, px, px); drawGrid(c); drawStitches(c, 1e9, false); }
  finally { delete cv.clientWidth; delete cv.clientHeight; S.view = v0; }
  return off;
}
function exportPng() {
  if (!S.gen || !S.gen.stitches) { alert("Nothing to preview yet."); return; }
  renderPreview(1200).toBlob(b => download((S.doc.name || "design").replace(/[^\w-]+/g, "_") + ".preview.png", b, "image/png"));
}
const VKEY = "es.versions";
function versions() { try { return JSON.parse(localStorage.getItem(VKEY) || "[]"); } catch (e) { return []; } }
function saveVersion() { const name = prompt("Version name:", "v" + (versions().length + 1)); if (!name) return;
  try { const v = versions(); v.push({name, time: Date.now(), doc: S.doc}); localStorage.setItem(VKEY, JSON.stringify(v.slice(-30))); } catch (e) { alert("Could not store the version (browser storage full or blocked). Use Save to download the project instead."); } renderVersions(); }
function renderVersions() { const el = $("#vers"); if (!el) return; const all = versions(), v = all.filter(x => x.doc && x.doc.name === S.doc.name);
  el.innerHTML = v.map(x => `<li class="note">${esc(x.name)} · ${new Date(x.time).toLocaleString()} <button data-vi="${all.indexOf(x)}" style="padding:0 6px">Restore</button></li>`).join("") || `<li class="note">No saved versions for this design name.</li>`;
  el.onclick = e => { const i = e.target.dataset.vi; if (i === undefined) return; const x = versions()[+i]; if (x && confirm("Restore version “" + x.name + "”? (Undo returns to the current state.)")) { S.doc = JSON.parse(JSON.stringify(x.doc)); fixSel(); commit(); renderAll(); fit(); } }; }
async function productionSheet() {
  if (!S.doc.objects.length) { alert("Nothing to report yet."); return; }
  const w = window.open("", "_blank"); if (!w) { alert("Allow pop-ups to view the production sheet."); return; }
  w.document.write("<p style='font:14px sans-serif'>Building production sheet…</p>");
  try { const r = await fetch("/api/export/sheet", {method: "POST", body: JSON.stringify(S.doc)}); if (!r.ok) throw new Error((await r.json()).error || r.statusText);
    const html = await r.text(); w.document.open(); w.document.write(html); w.document.close();
  } catch (e) { w.close(); alert("Could not build the production sheet: " + e.message); }
}
async function exportPackage() {
  const r = await fetch("/api/export/package", {method: "POST", body: JSON.stringify(S.doc)});
  if (!r.ok) { const j = await r.json().catch(() => ({})); alert("Package blocked:\n" + ((j.issues || []).filter(i => i.severity === "error").map(i => "• " + i.message).join("\n") || j.error || r.statusText)); return; }
  download((S.doc.name || "design").replace(/[^\w-]+/g, "_") + "-package.zip", await r.arrayBuffer(), "application/zip");
}
async function exportSvg() { if (!S.doc.objects.length) return; const r = await fetch("/api/export/svg", {method: "POST", body: JSON.stringify(S.doc)}); if (!r.ok) { alert("Preview failed"); return; } download((S.doc.name || "design").replace(/[^\w-]+/g, "_") + ".preview.svg", await r.text(), "image/svg+xml"); }
const b64 = buf => { let bin = ""; for (let i = 0; i < buf.length; i += 8192) bin += String.fromCharCode(...buf.subarray(i, i + 8192)); return btoa(bin); };
function renderQuality(j, title) {
  const v = j.verify, a = j.analysis, m = v.metrics || {};
  $("#qTitle").textContent = title;
  $("#qBody").innerHTML = `<div class="grade"><span class="chip ${v.grade}">${v.grade}</span><span>${v.grade === "PASS" ? "Passed every stage." : v.grade === "WARN" ? "Usable, with points to review." : "Do not stitch this until the failures are fixed."}</span></div>
  <div class="met"><span><b>${a.stitches}</b> stitches</span><span><b>${a.colour_blocks}</b> colour block(s)</span><span><b>${a.trims}</b> trims</span><span><b>${a.size_mm[0]} × ${a.size_mm[1]}</b> mm</span><span>≈ <b>${a.est_minutes}</b> min <small>(estimate, not verified)</small></span><span>median stitch <b>${a.len_median}</b> mm</span><span>max density <b>${a.dens_max}</b>/mm²</span></div>` +
    v.stages.map(s => `<div class="stage"><b><span class="chip ${s.result}">${s.result}</span>${esc(s.stage)}</b><div class="chk2">${s.checks.map(c => `<span class="chip ${c.level}" style="font-size:10px;align-self:start">${c.level}</span><span>${esc(c.what)}</span><span class="ev">${esc(c.evidence)}</span>`).join("")}</div></div>`).join("") +
    `<p class="note">Automated checks of the file's structure and stitch data. They cannot replace a test stitch-out on your fabric and stabiliser.</p>`;
}
const PLACEMENTS = [["left", "Left (sleeve / side)", 1], ["right", "Right (true mirror of left)", 1], ["neck", "Neck (front neckline)", 1], ["back_neck", "Back neck", 0], ["front", "Front panel", 0], ["back", "Back panel", 0], ["sleeve_left", "Sleeve - left", 0], ["sleeve_right", "Sleeve - right", 0], ["center", "Centre / single motif", 0]];
function openSet() {
  if (!S.doc.objects.length) { alert("Add or import some artwork first."); return; }
  $("#setRows").innerHTML = PLACEMENTS.map(([id, label, on]) => `<div class="pl"><input type="checkbox" data-pl="${id}" ${on ? "checked" : ""}><span>${label} <small>_${id}.dst</small></span><input type="number" data-w="${id}" min="5" max="500" step="1" placeholder="width mm"></div>`).join("");
  $("#setThread").innerHTML = Object.keys(THREADS).map(k => `<option value="${k}" ${k === (S.doc.thread || "40wt") ? "selected" : ""}>${THREADS[k]}</option>`).join("");
  const nm = (S.doc.name || "design").replace(/[^\w-]+/g, "_"); $("#dlgSet .hint").innerHTML = `Files are named after the design name (<b>${esc(nm)}</b>): <code>${esc(nm)}_left.dst</code>, <code>_right.dst</code>, <code>_neck.dst</code> … Each is auto-corrected and verified. Right is a <b>true mirror image</b> of left, not a rotated copy. Rename the design in the top bar first if needed.`;
  $("#setOut").hidden = true; $("#dlgSet").showModal();
}
async function generateSet() {
  const spec = [...document.querySelectorAll("#setRows input[data-pl]")].filter(c => c.checked).map(c => { const w = parseFloat(document.querySelector(`#setRows input[data-w="${c.dataset.pl}"]`).value); return w ? {id: c.dataset.pl, width_mm: w} : {id: c.dataset.pl}; });
  const out = $("#setOut"); out.hidden = false;
  if (!spec.length) { out.textContent = "Tick at least one placement."; return; }
  out.textContent = "Generating, correcting and verifying…";
  try {
    const r = await fetch("/api/placements", {method: "POST", body: JSON.stringify({design: S.doc, placements: spec, source_side: $("#setSide").value, thread: $("#setThread").value})});
    if (!r.ok) { const j = await r.json().catch(() => ({})); out.textContent = "Not generated: " + (j.error || r.statusText); return; }
    const rep = JSON.parse(atob(r.headers.get("X-Placement-Report") || "W10=")); const buf = await r.arrayBuffer();
    download((S.doc.name || "design").replace(/[^\w-]+/g, "_") + "-placements.zip", buf, "application/zip");
    out.textContent = rep.map(x => (x.status === "ok" ? "✔ " : "✖ ") + x.file + (x.status === "ok" ? `  ${x.grade}, ${x.stitches} stitches` : `  ${x.status}: ${x.reason || ""}`)).join("\n") + "\nZip downloaded (DST + project + preview + production sheet + verification per file).";
  } catch (e) { out.textContent = "Failed: " + e.message; }
}
function checklistHtml(cl) {
  const pct = Math.round(100 * cl.passed / cl.total);
  return `<div class="cl"><div class="clhead"><b>Production checklist ${cl.passed}/${cl.total}</b><span class="bar"><i style="width:${pct}%"></i></span><span class="chip ${cl.export_allowed ? "PASS" : "FAIL"}">${cl.export_allowed ? "export allowed" : "export blocked"}</span></div>` +
    cl.items.map(i => `<div class="cli"><span class="chip ${i.level === "N/A" ? "NA" : i.level}">${i.level}</span><span><b>${i.n}.</b> ${esc(i.title)}<br><small>${esc(i.evidence)}</small></span></div>`).join("") + `</div>`;
}
/* ---------------------------------------------------------------- auto-digitize wizard */
const CATS = {blouse_neck: "Maggam blouse neck", floral: "Maggam floral motif", saree_border: "Saree border / motif", logo: "Logo / lettering"};
const FABS = {cotton: "Cotton (experimental)", blouse: "Blouse fabric (experimental)", silk: "Silk (experimental)", georgette: "Georgette / chiffon (experimental)", velvet: "Velvet (experimental)", stretch: "Stretch / knit (experimental)", denim: "Denim / canvas (experimental)", satin_fabric: "Satin - slippery weave (experimental)", net: "Net / tulle (experimental)", thick: "Thick / heavy fabric (experimental)"};
const WZ = {step: 1, file: null, res: null};
const TESTSTEPS = ["Load the DST on the Ricoma and check the size shown matches the report", "Trace the design outline: it must clear the hoop", "Select needle, thread and stabiliser listed on the production sheet",
  "Stitch on a sample of the real garment fabric", "Watch for thread breaks, puckering, skipped stitches, registration (outlines on fills)", "Note what to change (density, underlay, pull comp) and adjust in the editor",
  "Stitch again after any change", "Approve for production only after a clean sample"];
function wzStep(n) {
  WZ.step = n; document.querySelectorAll("#wzSteps li").forEach((li, i) => li.className = i + 1 < n ? "done" : i + 1 === n ? "on" : "");
  document.querySelectorAll("#dlgWizard .wzp").forEach(p => p.hidden = +p.dataset.p !== n);
}
function openWizard() {
  const sel = (id, obj, v) => $(id).innerHTML = Object.entries(obj).map(([k, l]) => `<option value="${k}" ${k === v ? "selected" : ""}>${esc(l)}</option>`).join("");
  sel("#wzCat", CATS, "blouse_neck"); sel("#wzFab", FABS, "blouse"); sel("#wzThr", THREADS, S.doc.thread || "40wt");
  $("#wzErr").textContent = ""; WZ.res = null; wzStep(1); $("#dlgWizard").showModal();
}
async function wizardRun() {
  const f = $("#wzFile").files[0]; if (!f) { $("#wzErr").textContent = "Choose an image first (PNG or JPG)."; return; }
  if (!/\.(png|jpe?g)$/i.test(f.name)) { $("#wzErr").textContent = "Use a PNG or JPG image. For SVG artwork use Import art."; return; }
  wzStep(2); $("#wzLog").textContent = "Cleaning the image, finding colour regions, choosing stitch types, applying the profile, optimising the sequence, checking…";
  try {
    const data = b64(new Uint8Array(await f.arrayBuffer()));
    const r = await post("/api/autodigitize", {data, name: $("#wzName").value || f.name.replace(/\.[^.]+$/, ""), width_mm: +$("#wzW").value || 80, colors: +$("#wzC").value || 6,
      quality: $("#wzQ").value, enhance: "auto", fabric: $("#wzFab").value, category: $("#wzCat").value, thread: $("#wzThr").value, hoop_w: +$("#wzHW").value || 130, hoop_h: +$("#wzHH").value || 180});
    WZ.res = r; $("#wzLog").textContent = $("#wzLog2").textContent = "• " + r.log.join("\n• ");
    const sv = await fetch("/api/export/svg", {method: "POST", body: JSON.stringify(r.design)});
    $("#wzPrev").innerHTML = sv.ok ? `<img alt="stitch preview" src="${URL.createObjectURL(new Blob([await sv.text()], {type: "image/svg+xml"}))}">` : "Preview not available";
    const st = r.checklist.stats; $("#wzStats").textContent = `${st.stitches} stitches · ${st.color_changes + 1} colour(s) · ${st.trims} trims · ${st.width_mm} × ${st.height_mm} mm · ~${st.est_minutes} min (estimate, not verified)`;
    $("#wzChecks").innerHTML = checklistHtml(r.checklist);
    $("#wzExport").disabled = !r.checklist.export_allowed;
    loadDoc(r.design); setView("stitch");
    wzStep(3);
  } catch (e) { wzStep(1); $("#wzErr").textContent = "Auto-digitize failed: " + e.message; }
}
function renderTestSteps() {
  const key = "es-test-" + (S.doc.name || "design"); let st = {}; try { st = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) {}
  $("#wzTest").innerHTML = TESTSTEPS.map((t, i) => `<label class="tst"><input type="checkbox" data-i="${i}" ${st[i] ? "checked" : ""}> ${i + 1}. ${esc(t)}</label>`).join("");
  $("#wzTest").onchange = e => { const i = e.target.dataset.i; if (i === undefined) return; st[i] = e.target.checked; try { localStorage.setItem(key, JSON.stringify(st)); } catch (er) {} };
}
function openLettering() { $("#mMore").open = false; $("#ltOut").textContent = ""; $("#dlgLetter").showModal(); }
async function lettering() {
  const out = $("#ltOut"); out.textContent = "Shaping and digitizing…";
  try {
    const f = $("#ltFont").files[0]; const font = f ? b64(new Uint8Array(await f.arrayBuffer())) : null;
    const r = await post("/api/lettering", {text: $("#ltText").value, height_mm: +$("#ltH").value || 15, color: $("#ltColor").value, language: $("#ltLang").value || null,
      direction: $("#ltDir").value || null, font});
    if (!r.objects.length) { out.textContent = "Nothing to stitch - check the text and the font."; return; }
    r.objects.forEach(o => { o.id = "o" + (S.n++); }); fitObjects(r.objects, null); S.doc.objects.push(...r.objects); S.sel = null; commit(); renderAll(); fit();
    out.textContent = `Added ${r.objects.length} object(s) - font: ${r.info.font}, shaping: ${r.info.shaping}.` + (r.notes.length ? "\n" + r.notes.join("\n") : "");
  } catch (e) { out.textContent = "Failed: " + e.message; }
}
async function enhanceFile(file) {
  try { const raw = b64(new Uint8Array(await file.arrayBuffer()));
    const j = await post("/api/enhance", {data: raw, scale: 2, mode: "auto"});
    const bin = atob(j.png), u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    download(file.name.replace(/\.[^.]+$/, "") + "_x2.png", u, "image/png");
    alert(`Enhanced ${j.info.source_px.join("×")} → ${j.info.result_px.join("×")} px (${j.info.steps.join(", ")}).\nSharpness ${j.info.sharpness_before} → ${j.info.sharpness_after}.` + (j.info.photographic ? "\nLooks like a photo: only resampled and lightly sharpened." : ""));
  } catch (e) { alert("Enhance failed: " + e.message); }
}
function travelHtml(t) {
  const v = t.verdicts, T = t.totals, bad = (v["missing trim"] || 0) + (v["unnecessary trim"] || 0);
  const rows = Object.entries(v).map(([k, n]) => `<li class="${k === "missing trim" ? "e" : k === "unnecessary trim" ? "w" : "ok"}">${esc(k)}: ${n}</li>`).join("");
  return `<div class="qscore"><h4>Travel and trims</h4><ul>${rows}</ul><p>Jump travel ${T.jump_mm} mm, ${T.trims} trims, ${T.colour_changes} colour changes (minimum possible ${T.minimum_colour_changes}), ${T.carried_over_empty_mm} mm of carried thread over empty fabric. ${bad ? "Review the flagged moves." : ""}<br><small>${esc(t.note)}</small></p></div>`;
}
function qualityScoreHtml(q) {
  const rows = q.categories.map(c => `<tr><td>${esc(c.name)}</td><td><b>${c.score}</b>/100</td><td>${esc(c.detail.join(" "))}</td></tr>`).join("");
  const iss = q.issues.map(i => `<li class="${i.severity === "error" ? "e" : "w"}">${i.severity === "error" ? "✖" : "⚠"} ${esc(i.object)}: ${esc(i.message)} ${esc(i.advice || "")}</li>`).join("");
  return `<div class="qscore"><h4>Software quality score: ${q.score}/100</h4><table>${rows}</table>${iss ? `<ul>${iss}</ul>` : ""}<p><small>${esc(q.disclaimer)}</small></p></div>`;
}
async function qualityCheck() {
  const dlg = $("#dlgQuality"); $("#qBody").textContent = "Running…"; dlg.showModal();
  try {
    let raw, name;
    if (S.viewDstB64) { raw = S.viewDstB64; name = S.viewDstName; }
    else {
      if (!S.doc.objects.length) { $("#qBody").textContent = "Nothing to check yet - add some artwork first."; return; }
      const r = await fetch("/api/export/dst", {method: "POST", body: JSON.stringify(S.doc)});
      if (!r.ok) { const j = await r.json().catch(() => ({})); $("#qBody").innerHTML = "<b>Export is blocked</b>:<br>" + ((j.issues || [{message: j.error}]).filter(i => !i.severity || i.severity === "error").map(i => "• " + esc(i.message)).join("<br>")); return; }
      raw = b64(new Uint8Array(await r.arrayBuffer())); name = S.doc.name || "design";
    }
    const j = await post("/api/dst/report", {data: raw, name, hoop_w: S.doc.hoop.w, hoop_h: S.doc.hoop.h, thread: S.doc.thread || "40wt"});
    renderQuality(j, "Quality check - " + name + (S.viewDstB64 ? " (viewed file)" : ""));
    if (!S.viewDstB64) {
      const cl = await post("/api/checklist", S.doc); $("#qBody").insertAdjacentHTML("afterbegin", checklistHtml(cl));
      const mc = await post("/api/machine/check", S.doc); $("#qBody").insertAdjacentHTML("afterbegin", `<div class="qscore"><h4>Machine profile: ${esc(mc.profile.manufacturer + " " + mc.profile.model)}</h4><p><b>Not validated</b> - ${esc(mc.profile.validation_statement)}</p>${mc.issues.length ? "<ul>" + mc.issues.map(i => `<li class="${i.severity === "error" ? "e" : "w"}">${i.severity === "error" ? "✖" : "⚠"} ${esc(i.message)}</li>`).join("") + "</ul>" : "<p>No profile problems found.</p>"}</div>`);
      const tr = await post("/api/travel", S.doc); $("#qBody").insertAdjacentHTML("afterbegin", travelHtml(tr));
      const qr = await post("/api/quality", S.doc); $("#qBody").insertAdjacentHTML("afterbegin", qualityScoreHtml(qr));
    }
  } catch (e) { $("#qBody").textContent = "Check failed: " + e.message; }
}
async function viewDst(file) {
  try { const buf = new Uint8Array(await file.arrayBuffer()); const bin64 = b64(buf); S.viewDstB64 = bin64; S.viewDstName = file.name; let bin = "";
    const j = await post("/api/import/dst", {data: bin64}); const st = j.stitches; const xs = st.map(s => s[0]), ys = st.map(s => s[1]);
    const w = Math.max(...xs) - Math.min(...xs), h = Math.max(...ys) - Math.min(...ys);
    S.gen = {stitches: st, threads: j.threads, stats: {stitches: st.filter(s => s[2] === 0).length, jumps: st.filter(s => s[2] === 1).length, trims: 0, color_changes: j.color_changes, width_mm: +w.toFixed(1), height_mm: +h.toFixed(1), est_minutes: 0, color_sequence: j.threads.map((hex, i) => ({hex, stitches: st.filter(s => s[2] === 0 && s[3] === i).length}))}, issues: [], notes: ["Viewing " + file.name + " (read-only). Edit the design or press Undo to return to your project."]};
    const hw = Math.max(S.doc.hoop.w, w + 20), hh = Math.max(S.doc.hoop.h, h + 20); S.doc.hoop.w = Math.ceil(hw); S.doc.hoop.h = Math.ceil(hh); S.sim.i = st.length; setView("stitch"); fit(); renderPanels();
  } catch (e) { alert("Could not read DST: " + e.message); }
}
/* ---------------------------------------------------------------- library */
let LIB = null, libCat = "All", libQ = "";
async function openLibrary() {
  $("#lib").hidden = false;
  if (!LIB) { try { LIB = (await (await fetch("/api/library")).json()).designs || []; } catch (e) { LIB = []; } }
  renderLibrary(); $("#libq").focus();
}
function closeLibrary() { $("#lib").hidden = true; }
function renderLibrary() {
  const cats = ["All", ...new Set(LIB.map(d => d.category))];
  $("#libcats").innerHTML = cats.map(c => `<button data-cat="${esc(c)}" class="${c === libCat ? "on" : ""}">${esc(c)}</button>`).join("");
  const q = libQ.trim().toLowerCase();
  const list = LIB.filter(d => (libCat === "All" || d.category === libCat) && (!q || (d.name + " " + d.description + " " + d.category).toLowerCase().includes(q)));
  $("#libgrid").innerHTML = list.map(d => `<div class="card"><img loading="lazy" alt="${esc(d.name)}" src="/api/library/${d.id}/thumb.svg">
    <div class="m"><b>${esc(d.name)}</b>${esc(d.category)} · ${d.width_mm} × ${d.height_mm} mm<br>${d.stitches} stitches · ${d.colours} colour${d.colours > 1 ? "s" : ""} · ~${d.est_minutes} min (est.)<br>${(d.threads || []).map(h => `<span class="sw2" style="background:${esc(h)}"></span>`).join("")}</div>
    <div class="b"><button data-act="open" data-id="${d.id}" title="Open in the editor">Open</button><button data-act="3d" data-id="${d.id}" title="Open and view in 3D">3D</button><a href="/api/library/${d.id}/dst" download="${d.id}.dst" title="Download the DST">DST</a></div></div>`).join("") || `<div class="note" style="padding:20px">${LIB.length ? "No designs match." : "The library is empty or could not be loaded."}</div>`;
}
async function openFromLibrary(id, to3d) {
  const d = (LIB || []).find(x => x.id === id); if (!d) return;
  if (S.doc.objects.length && !confirm(`Replace the current design with “${d.name}”? Save it first if you want to keep it (undo history is cleared).`)) return;
  try {
    const j = await (await fetch(`/api/library/${id}/esproj`)).json(); loadDoc(j.doc); closeLibrary(); await doRegen();
    if (to3d) setView("3d"); else setView("design");
  } catch (e) { alert("Could not open the design: " + e.message); }
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

/* ---------------------------------------------------------------- panels */
function setTool(t) { S.tool = t; S.draft = null; S.colRail = null; document.querySelectorAll("#tools [data-tool]").forEach(b => b.classList.toggle("on", b.dataset.tool === t)); $("#hint").textContent = TOOLHINT[t]; cv.style.cursor = t === "select" ? "default" : "crosshair"; draw(); }
function renderAll() { if (document.activeElement !== $("#docName")) $("#docName").value = S.doc.name; renderPanels(); renderProps(); renderObjs(); draw(); }
function renderPanels() { renderSeq(); renderStats(); renderDesign(); }
function field(label, key, o, opts = {}) {
  const pro = opts.pro && S.mode !== "pro"; if (pro) return "";
  let v = opts.direct ? o[key] : P(o, key);
  if (key === "underlay" && o.type === "fill") v = v === true ? "tatami" : v === false ? "none" : v;
  if (v === undefined && o.type === "text" && key === "width") v = +Math.max(1, Math.min(o.height * .16, 4)).toFixed(2);
  if (opts.type === "check") return `<div class="row"><label>${label}</label><input type="checkbox" data-k="${key}" ${v ? "checked" : ""} ${opts.direct ? "data-d=1" : ""}></div>`;
  if (opts.options) return `<div class="row"><label>${label}</label><select data-k="${key}" ${opts.direct ? "data-d=1" : ""}>${opts.options.map(x => `<option ${x === v ? "selected" : ""}>${x}</option>`).join("")}</select></div>`;
  return `<div class="row"><label title="${opts.tip || ""}">${label}</label><input type="${opts.type || "number"}" data-k="${key}" value="${esc(v ?? "")}" ${opts.step ? `step="${opts.step}"` : ""} ${opts.min !== undefined ? `min="${opts.min}"` : ""} ${opts.direct ? "data-d=1" : ""}></div>`;
}
function renderProps() {
  const el = $("#props"), o = selObj();
  if (!o) { el.innerHTML = `<div class="note">Nothing selected. Pick a tool on the left and draw, or import artwork.</div><div class="note">Default colour</div><div class="sw" id="defsw"></div>`; swatches($("#defsw"), S.color, c => { S.color = c; renderProps(); }); return; }
  let h = `<div class="row"><label>Name</label><input type="text" data-k="name" data-d=1 value="${esc(o.name || "")}"></div>`;
  h += `<div class="note">${o.type === "embellishment" ? "Colour (for the production sheet)" : "Thread colour"}</div><div class="sw" id="osw"></div><div class="row"><label>Custom</label><input type="color" data-k="color" data-d=1 value="${o.color}"></div>`;
  if (o.type === "embellishment") h += field("Type", "kind", o, {options: ["bead", "stone", "sequin"], direct: 1}) + field("Size mm", "size_mm", o, {direct: 1, step: .5, min: 1}) + `<div class="note">${o.points.length} placed · not stitched · listed on the production sheet. Click the canvas with the Bead tool to add more.</div>`;
  else h += field("Guide only (not stitched)", "guide", o, {type: "check", direct: 1});
  if (o.type !== "text" && o.type !== "embellishment") h += field("Smooth curve", "smooth", o, {type: "check", direct: 1});
  if (!["text", "embellishment", "manual"].includes(o.type) && !o.guide) h += `<div class="row"><label title="Drag the orange handles to shape each node. Alt-click a handle = corner on that side; Alt-drag = cusp. Handles are baked into the stitches.">Curve nodes</label><span class="note">${o.handles ? "Bezier handles on" : "off"}</span></div><div class="btns"><button data-op="nodes">${o.handles ? "Reset handles" : "Edit curve nodes"}</button>${o.handles ? '<button data-op="straight">Remove handles</button>' : ""}</div>`;
  if (o.type === "fill") h += field("Pattern", "pattern", o, {options: ["tatami", "contour", "cross"], tip: "tatami = rows · contour = concentric rings · cross = cross-stitch grid"}) + (P(o, "pattern") === "cross" ? field("Cross size mm", "cross_size", o, {step: .5, min: 1}) : "");
  if (o.type === "fill") { const pt = P(o, "pattern");
    if (pt === "tatami") h += field("Direction °", "angle", o, {step: 5, tip: "Stitch angle"});
    if (pt !== "cross") h += field("Row spacing mm", "spacing", o, {step: .05, min: .2, pro: 1, tip: "Smaller = denser"}) + field("Stitch length mm", "stitch_len", o, {step: .5, min: 1, pro: 1});
    if (pt === "tatami") h += field("Underlay", "underlay", o, {options: ["tatami", "edge", "edge+tatami", "none"], pro: 1}) + field("Pull comp mm", "pull_comp", o, {step: .05, min: 0, pro: 1, tip: "Extra length to offset fabric pull-in"}) + field("Region order (fewer trims)", "regions", o, {type: "check", pro: 1}) + field("Cut hidden layers", "cut_hidden", o, {type: "check", pro: 1}) + field("Under-lap mm", "overlap_mm", o, {step: .1, min: .2, pro: 1, tip: "How far this fill still runs under the object on top, so no gap opens"}) + field("Push comp mm", "push_comp", o, {step: .05, min: 0, pro: 1, tip: "Shorten across the rows (fabric pushes out at the ends)"}) + field("Min row mm", "min_row", o, {step: .1, min: 0, pro: 1, tip: "Drop tatami rows shorter than this (spec minimum stitch 0.8-1.0 mm); tips are covered by pull comp / outline"}) + field("Expand outline mm", "expand_mm", o, {step: .05, min: 0, pro: 1, tip: "Fill-object expansion: grow the outline (holes shrink) so the fill meets its outline"}) + field("Horizontal comp mm", "comp_x", o, {step: .05, pro: 1, tip: "Added to the object width (total, both sides), whatever the stitch direction"}) + field("Vertical comp mm", "comp_y", o, {step: .05, pro: 1, tip: "Added to the object height (total)"});
    if (pt !== "tatami") h += `<div class="note">${pt === "contour" ? "Concentric rings; shapes with holes or very complex outlines fall back to tatami (see Checks)." : "Cross-stitch grid; no underlay."}</div>`; }
  if (o.type === "satin") h += field("Width mm", "width", o, {step: .25, min: .8}) + field("Underlay", "underlay", o, {options: ["auto", "none", "center", "edge", "zigzag", "edge+zigzag"], pro: 1}) + field("Curve shortening", "shorten", o, {type: "check", pro: 1}) + field("Split sharp corners", "corners", o, {type: "check", pro: 1}) + (P(o, "corners") ? field("Corner angle °", "corner_angle", o, {step: 5, min: 20, pro: 1, tip: "Turns sharper than this split the satin"}) : "") + field("End where it started", "end_at_start", o, {type: "check", pro: 1, tip: "Underlay runs out, satin comes back: the object ends at its start (fewer trims in petals / leaves)"}) + field("Style", "style", o, {options: ["satin", "zigzag"], pro: 1}) + field("Push comp mm", "push_comp", o, {step: .05, min: 0, pro: 1, tip: "Shorten the column ends"}) + field("Spacing mm", "spacing", o, {step: .05, min: .2, pro: 1}) + field("Pull comp mm", "pull_comp", o, {step: .05, min: 0, pro: 1}) + field("Auto-split long stitches", "auto_split", o, {type: "check", pro: 1, tip: "Splits stitches longer than the machine max stitch so wide satin stays clean"});
  if (o.type === "column") h += field("Horizontal comp mm", "comp_x", o, {step: .05, pro: 1, tip: "Added to the object width (total, both sides), whatever the stitch direction"}) + field("Vertical comp mm", "comp_y", o, {step: .05, pro: 1, tip: "Added to the object height (total)"}) + field("Underlay", "underlay", o, {options: ["auto", "none", "center", "edge", "zigzag", "edge+zigzag"], pro: 1}) + field("Curve shortening", "shorten", o, {type: "check", pro: 1}) + field("End where it started", "end_at_start", o, {type: "check", pro: 1, tip: "Underlay runs out, satin comes back: the object ends at its start"}) + field("Style", "style", o, {options: ["satin", "zigzag"], pro: 1}) + field("Push comp mm", "push_comp", o, {step: .05, min: 0, pro: 1, tip: "Shorten the column ends"}) + field("Spacing mm", "spacing", o, {step: .05, min: .2, pro: 1}) + field("Pull comp mm", "pull_comp", o, {step: .05, min: 0, pro: 1}) + field("Auto-split long stitches", "auto_split", o, {type: "check", pro: 1, tip: "Splits stitches longer than the machine max stitch so wide satin stays clean"}) + `<div class="note">Two-rail satin: stitches run edge to edge. Drag the rail points to reshape.</div>`;
  if (o.type === "run") h += field("Stitch length mm", "stitch_len", o, {step: .5, min: .5}) + field("Closed loop", "closed", o, {type: "check", direct: 1}) + field("Style", "style", o, {options: ["single", "bean", "motif"], tip: "bean = triple stitch: bold raised outline / stem; motif = a small motif repeated along the line"}) +
    (P(o, "style") === "motif" ? field("Motif", "motif", o, {options: ["wave", "zigzag", "scallop", "diamond", "leaf"]}) + field("Repeat length mm", "motif_size", o, {step: .5, min: 1}) + field("Motif width mm", "motif_amp", o, {step: .25, min: 0, tip: "How far the motif swings to each side"}) : "");
  if (o.type === "manual") h += `<div class="note">Manual stitches: ${o.points.length} needle points, sewn exactly as placed (only stitches longer than the max stitch are split). Drag the white handles to move single stitches.</div>`;
  if (o.type === "text") { const paths = S.doc.objects.filter(q => (q.type === "run" || q.type === "satin") && q.points && q.points.length >= 2);
    h += `<div class="row"><label title="Bend the lettering along a running-stitch or satin line (e.g. a neckline)">Follow path</label><select id="txtPath"><option value="">(straight)</option>${paths.map(q => `<option value="${esc(q.id)}">${esc(q.name || q.id)}</option>`).join("")}</select></div>` +
      (o.path ? `<div class="row"><label>Align on path</label><select id="txtAlign">${["start", "center", "end"].map(a => `<option ${a === (o.align || "center") ? "selected" : ""}>${a}</option>`).join("")}</select></div><div class="btns"><button data-op="unpath">Straighten text</button></div>` : ""); }
  if (o.type === "text") h += `<div class="row"><label>Text</label><input type="text" data-k="text" data-d=1 value="${esc(o.text)}"></div>` + field("Height mm", "height", o, {direct: 1, step: .5, min: 3}) + field("Letter spacing", "spacing", o, {step: .1, min: .5}) + field("Stroke width mm", "width", o, {step: .25, min: 1, tip: "Satin column width of each stroke"}) + `<div class="note">Built-in single-line satin font (A–Z, 0–9, - . !). Minimum practical height ≈ 5 mm.</div>`;
  if (o.type === "applique") h += field("Cover width mm", "width", o, {step: .25, min: 1.5}) + `<div class="row"><label title="Thread colour of the satin cover (default: the object colour)">Cover colour</label><input type="color" data-k="cover_color" value="${(o.params || {}).cover_color || o.color}"></div>` + `<div class="note">Stitches: placement line → tack-down → satin cover. The machine pauses at the colour change so you can lay fabric.</div>`;
  if (S.mode === "pro" && !["embellishment", "manual"].includes(o.type) && !o.guide) h += `<div class="btns"><button data-op="manual" title="Replace this object by its actual needle points so single stitches can be moved (stitch-level editing). The DST does not change until you edit.">Convert to manual stitches</button></div>`;
  h += `<div class="btns"><button data-op="dup">Duplicate</button><button data-op="fh">Flip ↔</button><button data-op="fv">Flip ↕</button><button data-op="r90">Rotate 90°</button>${o.rings ? `<button data-op="outline">Add border</button>` : ""}<button data-op="del">Delete</button></div>`;
  if (!["embellishment", "manual", "text"].includes(o.type) && !o.guide) h += `<div class="row"><label title="Preferred start / end of this object. The engine sews it in whichever direction starts nearest the start point and ends nearest the end point (same stitches, no new points).">Start / end</label><span class="note">${o.entry ? "start set" : "auto"} · ${o.exit ? "end set" : "auto"}</span></div><div class="btns"><button data-op="pickEntry">Set start…</button><button data-op="pickExit">Set end…</button><button data-op="clearEE">Clear</button></div>`;
  const bb = bbox(allPts(o)); const bw = bb ? +(bb[2] - bb[0]).toFixed(2) : 0, bh = bb ? +(bb[3] - bb[1]).toFixed(2) : 0;
  h += `<div class="row"><label>Width mm</label><input type="number" id="szW" value="${bw}" step="0.5" min="1"></div><div class="row"><label>Height mm</label><input type="number" id="szH" value="${bh}" step="0.5" min="1"></div><div class="row"><label>Keep proportions</label><input type="checkbox" id="szLock" checked></div>`;
  if (o.type !== "text") h += `<div class="row"><label>Rotate °</label><span style="display:flex;gap:4px"><input type="number" id="rotDeg" value="15" step="5" style="width:50%"><button data-op="rot" style="padding:3px 6px">Apply</button></span></div>`;
  const conv = convertTargets(o); if (conv.length) h += `<div class="row"><label>Convert to</label><select id="convSel"><option value="">stitch type…</option>${conv.map(t => `<option>${t}</option>`).join("")}</select></div>`;
  h += `<div class="row"><label>Scale %</label><input type="number" id="scalePct" value="100" step="5"></div><div class="btns"><button data-op="scale">Apply scale</button></div>`;
  h += `<div class="row"><label>Repeat ×</label><input type="number" id="repN" value="5" min="2" max="200"></div><div class="row"><label>Offset X,Y mm</label><span style="display:flex;gap:4px"><input type="number" id="repX" value="12" step="1" style="width:50%"><input type="number" id="repY" value="0" step="1" style="width:50%"></span></div><div class="btns"><button data-op="repeat">Repeat (border / row)</button></div>`;
  el.innerHTML = h; swatches($("#osw"), o.color, c => { o.color = c; commit(); renderAll(); });
  el.querySelectorAll("[data-k]").forEach(inp => {
    const apply = () => { const k = inp.dataset.k; let v = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? parseFloat(inp.value) : inp.value; if (inp.type === "number" && isNaN(v)) return;
      if (inp.dataset.d) o[k] = v; else { o.params = o.params || {}; o.params[k] = v; } draw(); if (k !== "name") regenSoft(); };
    // fields that add / remove other fields (stitch style, corner splitting, fill pattern) rebuild the panel so the new fields appear at once
    const shapesPanel = ["style", "corners", "pattern"].includes(inp.dataset.k);
    inp.addEventListener("input", apply); inp.addEventListener("change", () => { apply(); commit(); renderObjs(); if (shapesPanel) renderProps(); });
  });
  const sz = which => () => { const w = parseFloat($("#szW").value), hh = parseFloat($("#szH").value); if (!(w > 0) || !(hh > 0)) return;
    const ob = selObj(), b2 = ob && bbox(allPts(ob)); if (!b2) return; const cw = b2[2] - b2[0], ch = b2[3] - b2[1];   // measure NOW so a repeated event is a no-op
    const f = which === "w" ? w / cw : hh / ch; if ($("#szLock").checked) { if (Math.abs(f - 1) > 1e-3) scaleSel(f * 100); } else if (Math.abs(w / cw - 1) > 1e-3 || Math.abs(hh / ch - 1) > 1e-3) nonUniform(w / cw, hh / ch); };
  $("#szW").onchange = sz("w"); $("#szH").onchange = sz("h");
  if ($("#convSel")) $("#convSel").onchange = e => { if (e.target.value) convertSel(e.target.value); };
  if ($("#txtPath")) $("#txtPath").onchange = e => { const src = S.doc.objects.find(q => q.id === e.target.value); const t = selObj(); if (!t) return; if (src) { t.path = clone(src.points); t.align = t.align || "center"; } else delete t.path; commit(); renderAll(); };
  if ($("#txtAlign")) $("#txtAlign").onchange = e => { const t = selObj(); if (t) { t.align = e.target.value; commit(); renderAll(); } };
  el.querySelectorAll("[data-op]").forEach(b => b.onclick = () => ({
    rot: () => rotateSel(parseFloat($("#rotDeg").value) || 0),
    dup: () => duplicate(3, 3), del: deleteSel, outline, scale: () => scaleSel(parseFloat($("#scalePct").value) || 100),
    fh: () => transformSel((p, cx) => [2 * cx - p[0], p[1]], false), fv: () => transformSel((p, cx, cy) => [p[0], 2 * cy - p[1]], false),
    r90: () => transformSel((p, cx, cy) => [cx - (p[1] - cy), cy + (p[0] - cx)], false),
    repeat: () => duplicate(parseFloat($("#repX").value) || 0, parseFloat($("#repY").value) || 0, parseInt($("#repN").value) - 1 || 1),
    nodes: () => { const t = selObj(); if (t) curveNodes(t); },
    straight: () => { const t = selObj(); if (t) { delete t.handles; commit(); renderAll(); } },
    pickEntry: () => { S.pick = "entry"; $("#hint").textContent = "Click on the canvas to set the START point of this object. Esc cancels."; setView("design"); },
    pickExit: () => { S.pick = "exit"; $("#hint").textContent = "Click on the canvas to set the END point of this object. Esc cancels."; setView("design"); },
    clearEE: () => { const t = selObj(); if (t) { delete t.entry; delete t.exit; commit(); renderAll(); } },
    unpath: () => { const t = selObj(); if (t) { delete t.path; commit(); renderAll(); } },
    manual: async () => { const t = selObj(); if (!t) return;
      try { const r = await post("/api/to_manual", {design: S.doc, id: t.id}); const i = S.doc.objects.indexOf(t);
        r.objects.forEach(o => { o.id = "o" + (S.n++); }); S.doc.objects.splice(i, 1, ...r.objects); S.sel = r.objects[0].id; commit(); renderAll();
        alert(`Converted to ${r.objects.length} manual stitch object(s), ${r.stitches} needle points. The DST is unchanged until you move points.`);
      } catch (e) { alert("Could not convert: " + e.message); } }
  })[b.dataset.op]());
}
function regenSoft() { regen(); }
function swatches(el, cur, cb) { el.innerHTML = PALETTE.map(c => `<i style="background:${c}" data-c="${c}" class="${c === cur ? "on" : ""}" title="${c}"></i>`).join(""); el.onclick = e => { if (e.target.dataset.c) cb(e.target.dataset.c); }; }
function renderObjs() {
  $("#objs").innerHTML = S.doc.objects.map(o => `<li data-id="${o.id}" class="${o.id === S.sel || S.multi.has(o.id) ? "on" : ""} ${o.hidden ? "hid" : ""}"><span class="c" style="background:${o.color}"></span><span class="n">${esc(o.name || o.id)} <small>${o.type}${o.group ? " · " + esc(o.group) : ""}</small></span><button data-a="up" title="Stitch earlier">▲</button><button data-a="dn" title="Stitch later">▼</button><button data-a="eye" title="Hide/show">${o.hidden ? "◌" : "◉"}</button></li>`).join("") || `<li class="note">No objects yet.</li>`;
  $("#objs").onclick = e => { const li = e.target.closest("li[data-id]"); if (!li) return; const id = li.dataset.id, a = e.target.dataset.a;
    if (a === "up") return moveOrder(id, -1); if (a === "dn") return moveOrder(id, 1);
    if (a === "eye") { const o = S.doc.objects.find(o => o.id === id); o.hidden = !o.hidden; commit(); return renderAll(); }
    selectWithGroup(id, e.shiftKey || e.ctrlKey || e.metaKey); renderAll(); };
}
function renderDesign() {
  const d = S.doc, el = $("#designProps");
  const html = `<div class="row"><label>Hoop</label><select id="hoopSel">${Object.keys(HOOPS).map(k => `<option ${(Math.abs(HOOPS[k][0] - d.hoop.w) < .2 && Math.abs(HOOPS[k][1] - d.hoop.h) < .2) ? "selected" : ""}>${k}</option>`).join("")}<option ${Object.values(HOOPS).some(h => Math.abs(h[0] - d.hoop.w) < .2 && Math.abs(h[1] - d.hoop.h) < .2) ? "" : "selected"}>Custom</option></select></div>
  <div class="row"><label>Hoop W × H mm</label><span style="display:flex;gap:4px"><input type="number" id="hw" value="${d.hoop.w}" style="width:50%"><input type="number" id="hh" value="${d.hoop.h}" style="width:50%"></span></div>
  <div class="row"><label>Safe margin mm</label><input type="number" id="hm" value="${d.hoop.margin}" step=".5" min="0"></div>
  <div class="row"><label>Stabiliser</label><select id="stab">${["cut-away", "tear-away", "wash-away", "none"].map(k => `<option ${k === (d.stabiliser || "cut-away") ? "selected" : ""}>${k}</option>`).join("")}</select></div>
  <div class="row"><label title="Finer thread needs closer stitch lines. 120/2 blouse thread: 0.22 mm; 40 wt: 0.40 mm">Thread weight</label><select id="thr">${Object.keys(THREADS).map(k => `<option value="${k}" ${k === (d.thread || "40wt") ? "selected" : ""}>${THREADS[k]}</option>`).join("")}</select></div>
  <div class="row"><label>Fabric preset</label><select id="fab">${Object.keys(FABRICS).map(k => `<option value="${k}" ${k === d.fabric ? "selected" : ""}>${k} (experimental)</option>`).join("")}</select></div>
  <div class="row"><label title="Digitizing category: sets running-stitch length and underlay weight">Category</label><select id="pfCat">${Object.entries(CATS).map(([k, l]) => `<option value="${k}" ${k === ((d.profile || {}).category || "blouse_neck") ? "selected" : ""}>${l}</option>`).join("")}</select></div>
  <div class="row"><label title="Experimental: values come from measurements of other files and have not been stitched on a machine">Profile fabric</label><select id="pfFab">${Object.entries(FABS).map(([k, l]) => `<option value="${k}" ${k === ((d.profile || {}).fabric || "cotton") ? "selected" : ""}>${l}</option>`).join("")}</select></div>
  <div class="btns"><button id="pfApply" title="Set density, underlay, pull / push compensation, corners, cut-hidden-layers on every object from the fabric + category + thread (values you set yourself are kept) and optimise the sewing order. Undoable.">Apply profile</button><button id="pfReset" title="Same, but replace values you set yourself too">Apply &amp; overwrite</button><button id="pfSeq" title="Only reorder objects (same colours, same layering) to cut trims and travel">Optimise sequence</button></div>
  <div class="note" id="fabInfo">${(() => { const f = (S.fabrics || []).find(x => x.id === (d.fabric || "cotton")); return f ? esc(f.explanation) + (f.warning ? " ⚠ " + esc(f.warning) : "") : ""; })()}</div>
  <div class="note"><b>Experimental:</b> fabric presets are starting values that have not been tested on a machine. They apply to new objects. <button id="fabApply" style="padding:1px 6px">Apply to all</button></div>
  <div class="row"><label title="Limits the design is checked against. No machine profile is validated: none has been stitched out.">Machine profile</label><select id="mProf">${(S.machines || [{id: "generic_tajima_dst", model: "Generic Tajima-compatible DST"}]).map(m => `<option value="${m.id}" ${m.id === ((d.machine_profile || {}).id || "generic_tajima_dst") ? "selected" : ""}>${esc((m.manufacturer ? m.manufacturer + " " : "") + m.model)}</option>`).join("")}</select></div>
  <div class="row"><label title="Largest hoop of YOUR machine (mm). Blank = not checked.">Machine max hoop W × H</label><span style="display:flex;gap:4px"><input type="number" id="mpW" value="${(((d.machine_profile || {}).overrides || {}).max_hoop || {}).w ?? ""}" style="width:50%" min="10"><input type="number" id="mpH" value="${(((d.machine_profile || {}).overrides || {}).max_hoop || {}).h ?? ""}" style="width:50%" min="10"></span></div>
  <div class="row"><label title="Number of needles / thread colours your machine holds. Blank = not checked.">Machine needles</label><input type="number" id="mpN" value="${((d.machine_profile || {}).overrides || {}).needles ?? ""}" min="1" max="64"></div>
  <div class="note"><b>Not validated:</b> no stitch-out evidence exists for any machine profile. These limits only check the design against the numbers you enter. <button id="bReport" style="padding:1px 6px">Production report</button> <button id="bSplit" style="padding:1px 6px" title="Design bigger than your hoop: one DST per hooping with alignment marks">Split for hoop</button> <button id="bFid" style="padding:1px 6px" title="Compare the exported DST with the original image you imported: nine software validation passes, overlay and difference map, detail inventory">Image fidelity</button></div>
  <div class="row"><label>Max stitch mm</label><input type="number" id="mMax" value="${(d.machine || {}).max_stitch ?? 7}" step=".5" min="1" max="12.1"></div>
  <div class="row"><label title="Jumps longer than this get a trim">Trim above mm</label><input type="number" id="mTrim" value="${(d.machine || {}).trim_distance ?? 3}" step=".5" min=".5"></div>
  <div class="row"><label title="DST has no trim command; machines differ. Confirm on yours.">Trim jumps</label><input type="number" id="mJ" value="${(d.machine || {}).trim_jumps ?? 3}" step="1" min="1" max="6"></div>
  <div class="row"><label title="Tie-in / tie-off stitch length. 0 = no lock stitches">Lock stitch mm</label><input type="number" id="mLock" value="${(d.machine || {}).lock_len ?? 1}" step=".1" min="0" max="1.5"></div>
  <div class="row"><label title="Tie off + trim before every thread colour change">Trim at colour change</label><input type="checkbox" id="mTC" ${((d.machine || {}).trim_at_color_change ?? 1) ? "checked" : ""}></div>
  <div class="row"><label title="Stitch each run from whichever end is nearer when that turns a trim into a carried jump">Smart start direction</label><input type="checkbox" id="mSD" ${((d.machine || {}).smart_direction ?? 1) ? "checked" : ""}></div>
  <div class="row"><label title="Stitches shorter than this are flagged by the checks">Min stitch mm</label><input type="number" id="mMin" value="${(d.machine || {}).min_stitch ?? 0.3}" step=".1" min=".1" max="2"></div>
  <div class="row"><label title="Merge stitches shorter than this into their neighbour (thread-break / nesting risk at petal tips and tiny shapes). 0 = off.">Clean micro-stitches below mm</label><input type="number" id="mClean" value="${(d.machine || {}).micro_clean ?? 0}" step=".1" min="0" max=".8"></div>
  <div class="row"><label title="Tie off + trim before the end of the design">Trim at end</label><input type="checkbox" id="mTE" ${((d.machine || {}).trim_at_end ?? 1) ? "checked" : ""}></div>
  <div class="btns"><button id="bFix" title="Fit to hoop, centre, drop specks, fix hairline columns, remove duplicate points, relieve over-dense areas. Undoable.">Auto-fix</button><button id="bCenter">Centre design</button><button id="bOpt" title="Group objects by thread colour">Optimise colours</button><button id="bVer">Save version…</button></div><ul id="vers" style="list-style:none;margin:0;padding:0"></ul>`;
  const sig = html.replace(/ value="[^"]*"/g, "").replace(/ selected/g, "").replace(/ checked/g, "");
  if (el.dataset.sig === sig) {   // same structure: sync values in place so a click in progress is never lost to a rebuild
    const sync = (id, v) => { const x = $("#" + id); if (x && document.activeElement !== x) x.value = v; };
    sync("stab", d.stabiliser || "cut-away"); sync("hw", d.hoop.w); sync("hh", d.hoop.h); sync("hm", d.hoop.margin); sync("fab", d.fabric); sync("thr", d.thread || "40wt");
    sync("mMax", (d.machine || {}).max_stitch ?? 7); sync("mTrim", (d.machine || {}).trim_distance ?? 3); sync("mJ", (d.machine || {}).trim_jumps ?? 3); sync("mLock", (d.machine || {}).lock_len ?? 1); sync("mMin", (d.machine || {}).min_stitch ?? 0.3); sync("pfFab", (d.profile || {}).fabric || "cotton"); sync("pfCat", (d.profile || {}).category || "blouse_neck");
    for (const [id, k] of [["mTC", "trim_at_color_change"], ["mTE", "trim_at_end"], ["mSD", "smart_direction"]]) { const x = $("#" + id); if (x && document.activeElement !== x) x.checked = !!((d.machine || {})[k] ?? 1); }
    const hs = $("#hoopSel"); if (hs && document.activeElement !== hs) { const k = Object.keys(HOOPS).find(k => Math.abs(HOOPS[k][0] - d.hoop.w) < .2 && Math.abs(HOOPS[k][1] - d.hoop.h) < .2); hs.value = k || "Custom"; }
    renderVersions(); return;
  }
  el.dataset.sig = sig; el.innerHTML = html;
  const mset = (k, el) => el.onchange = () => { S.doc.machine = S.doc.machine || {}; const v = parseFloat(el.value); if (!isNaN(v)) S.doc.machine[k] = v; commit(); renderAll(); };
  mset("max_stitch", $("#mMax")); mset("trim_distance", $("#mTrim")); mset("micro_clean", $("#mClean")); mset("trim_jumps", $("#mJ")); mset("lock_len", $("#mLock"));
  const mflag = (k, el) => el.onchange = () => { S.doc.machine = S.doc.machine || {}; S.doc.machine[k] = el.checked ? 1 : 0; commit(); renderAll(); };
  mflag("trim_at_color_change", $("#mTC")); mflag("trim_at_end", $("#mTE")); mflag("smart_direction", $("#mSD")); mset("min_stitch", $("#mMin"));
  const runProfile = async (body, label) => {
    try { const j = await post("/api/profile", Object.assign({design: S.doc}, body)); const keep = S.doc.name;
      if (!j.log.length) { alert("Nothing to change - the design already matches."); return; }
      S.doc = Object.assign(newDoc(), j.design, {name: keep}); S.sel = null; commit(); renderAll();
      alert(label + " applied (Ctrl+Z undoes it):\n\n• " + j.log.join("\n• "));
    } catch (e) { alert(label + " failed: " + e.message); } };
  const pf = o => Object.assign({fabric: $("#pfFab").value, category: $("#pfCat").value}, o);
  $("#pfApply").onclick = () => runProfile(pf({}), "Profile"); $("#pfReset").onclick = () => { if (confirm("Replace the values you set yourself on every object?")) runProfile(pf({overwrite: true}), "Profile (overwrite)"); };
  $("#pfSeq").onclick = () => runProfile({profile: false}, "Sequence optimisation");
  $("#bFix").onclick = async () => {
    try { const j = await post("/api/autofix", S.doc);
      if (!j.log.length) { alert("Nothing to fix - the design already passes the automatic corrections."); return; }
      const keepName = S.doc.name; S.doc = Object.assign(newDoc(), j.design, {name: keepName}); S.sel = null; commit(); renderAll(); fit();
      alert("Auto-fix applied (Ctrl+Z undoes it):\n\n• " + j.log.join("\n• "));
    } catch (e) { alert("Auto-fix failed: " + e.message); }
  };
  $("#bOpt").onclick = optimiseColours; $("#bVer").onclick = saveVersion; renderVersions();
  const setH = (w, h) => { S.doc.hoop.w = w; S.doc.hoop.h = h; commit(); fit(); renderAll(); };
  $("#hoopSel").onchange = e => { const v = HOOPS[e.target.value]; if (v) setH(v[0], v[1]); };
  $("#hw").onchange = () => setH(+$("#hw").value || 100, S.doc.hoop.h); $("#hh").onchange = () => setH(S.doc.hoop.w, +$("#hh").value || 100);
  $("#hm").onchange = () => { S.doc.hoop.margin = +$("#hm").value || 0; commit(); renderAll(); };
  $("#stab").onchange = e => { S.doc.stabiliser = e.target.value; commit(); };
  $("#thr").onchange = e => { S.doc.thread = e.target.value; commit(); renderAll(); };
  $("#fab").onchange = e => { S.doc.fabric = e.target.value; commit(); };
  $("#fabApply").onclick = () => { const f = FABRICS[S.doc.fabric]; S.doc.objects.forEach(o => { if (o.type === "fill" || o.type === "satin") o.params = Object.assign(o.params || {}, f); }); commit(); renderAll(); };
  $("#bCenter").onclick = centerAll;
  const setMP = fn => { S.doc.machine_profile = S.doc.machine_profile || {id: "generic_tajima_dst"}; S.doc.machine_profile.overrides = S.doc.machine_profile.overrides || {}; fn(S.doc.machine_profile); commit(); renderAll(); };
  $("#mProf").onchange = e => setMP(mp => { mp.id = e.target.value; const pr = (S.machines || []).find(m => m.id === mp.id); if (pr) { S.doc.machine = Object.assign(S.doc.machine || {}, {max_stitch: pr.max_stitch, min_stitch: pr.min_stitch, trim_distance: pr.trim_distance, trim_jumps: pr.trim_jumps, lock_len: pr.lock_len, trim_at_color_change: pr.trim_at_color_change, trim_at_end: pr.trim_at_end}); } });
  const hoopMP = () => setMP(mp => { const w = +$("#mpW").value, h = +$("#mpH").value; if (w > 0 && h > 0) mp.overrides.max_hoop = {w, h}; else delete mp.overrides.max_hoop; });
  $("#mpW").onchange = hoopMP; $("#mpH").onchange = hoopMP;
  $("#mpN").onchange = () => setMP(mp => { const n = parseInt($("#mpN").value); if (n >= 1) mp.overrides.needles = n; else delete mp.overrides.needles; });
  $("#bReport").onclick = downloadReport; $("#bSplit").onclick = splitForHoop; $("#bFid").onclick = openFidelity;
}
async function splitForHoop() {
  if (!S.doc.objects.length) { alert("Nothing to split yet."); return; }
  const r = await fetch("/api/split", {method: "POST", body: JSON.stringify(S.doc)});
  if (!r.ok) { const j = await r.json().catch(() => ({})); alert("Cannot split: " + (j.error || r.statusText)); return; }
  const rep = JSON.parse(atob(r.headers.get("X-Split-Report") || "e30=")), blob = await r.blob(), a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = (S.doc.name || "design").replace(/[^\w-]+/g, "_") + "-split.zip"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  alert(`Split into ${rep.tiles.length} hooping(s) (${rep.grid.cols} x ${rep.grid.rows}).` + (rep.oversize.length ? `\nToo big for one hooping (not cut): ${rep.oversize.join(", ")}` : "") + (rep.tiles.some(t => t.status !== "ok") ? "\nSome tiles were blocked - see split-report.json." : "") + "\nHoop each tile so its grey alignment crosses sit on the crosses already stitched. Not verified on a machine.");
}
async function downloadReport() {
  if (!S.doc.objects.length) { alert("Nothing to report yet."); return; }
  const r = await fetch("/api/report", {method: "POST", body: JSON.stringify(Object.assign({}, S.doc, {html: true}))}), j = await r.json().catch(() => ({}));
  if (!r.ok) { alert("No report: the DST could not be released.\n" + (j.issues || [{message: j.error}]).filter(i => !i.severity || i.severity === "error").map(i => "• " + friendlyLine(i)).join("\n")); return; }
  download((S.doc.name || "design").replace(/[^\w-]+/g, "_") + ".production-report.html", j.html, "text/html");
}
function renderSeq() {
  const g = S.gen; $("#seq").innerHTML = g && g.stats ? g.stats.color_sequence.map((s, i) => `<div class="seqrow"><i style="background:${s.hex}"></i>${i + 1}. ${s.hex} <span class="note">· ${s.stitches} st</span></div>`).join("") : `<div class="note">—</div>`;
}
function renderStats() {
  const g = S.gen, el = $("#stats"), il = $("#issues");
  if (!g) { el.innerHTML = `<span>Add objects to see stitch data.</span>`; il.innerHTML = ""; return; }
  if (g.error) { el.innerHTML = `<span class="e">${esc(g.error)}</span>`; il.innerHTML = ""; return; }
  const s = g.stats; el.innerHTML = `<span>Stitches</span><b>${s.stitches}</b><span>Size</span><b>${s.width_mm} × ${s.height_mm} mm</b><span>Colour changes</span><b>${s.color_changes}</b><span>Trims / jumps</span><b>${s.trims} / ${s.jumps}</b><span title="Calculated from an assumed machine speed; not verified on a machine">Est. time</span><b>~${s.est_minutes} min <small>(estimate, not verified)</small></b>`;
  const items = g.issues.reduce((a, i) => { const k = i.code + i.severity; (a[k] = a[k] || {...i, n: 0}).n++; return a; }, {});
  const lst = Object.values(items).map(i => `<li class="${i.severity === "error" ? "e" : "w"}">${i.severity === "error" ? "✖" : "⚠"} ${esc(friendly(i)[0])}${i.n > 1 ? ` <small>(×${i.n})</small>` : ""}${friendly(i)[1] ? `<span class="advice">${esc(friendly(i)[1])}</span>` : ""}</li>`);
  (g.notes || []).forEach(n => lst.push(`<li class="w">ℹ ${esc(n)}</li>`));
  il.innerHTML = lst.join("") || `<li class="ok">✔ No problems found</li>`;
}
// Plain-language wording for shop owners: what it means + what to do. Numbers from the engine message are kept where they help.
const HELP = {
  HOOP: m => ["The design is too big for the hoop.", "Make it smaller, or pick a bigger hoop in the Design panel. " + (m.match(/\d[\d.]* ?x ?\d[\d.]* mm/) ? "(" + m.match(/\d[\d.]* ?x ?\d[\d.]* mm/)[0] + " does not fit with the safe margin)" : "")],
  DENSITY: m => ["The stitches are packed very tightly in some spots, which can break needles or damage thin fabric.", "Open the stitch spacing a little, or use Auto-fix (Design panel)."],
  STITCH_SHORT: () => ["Some stitches are extremely short.", "Increase row spacing or simplify tiny shapes."],
  STITCH_LONG: () => ["Some stitches are long and may snag or loop.", "Shorten the stitch length or let wide satin columns split automatically."],
  STITCH_TOO_LONG_DST: () => ["A stitch is longer than the DST format allows (12.1 mm).", "Shorten the stitch length."],
  ZERO_LENGTH: () => ["Some points are stitched twice in the same place.", "Auto-fix removes duplicate points."],
  COLOR_SEQ: () => ["A colour change goes to the thread already in use.", "Merge the two objects into one colour, or reorder them."],
  DOUBLE_COLOR: () => ["Two colour changes follow each other.", "Remove the empty colour between them."],
  EMPTY: () => ["There is nothing to stitch yet.", "Draw or import some artwork first."],
  NO_END: () => ["The file does not end properly.", "Try exporting again; if it repeats, report it."],
  MULTI_END: () => ["The file ends more than once.", "Try exporting again; if it repeats, report it."],
  THREAD_INDEX: () => ["A thread colour is missing.", "Check the colours of your objects."],
  MACHINE_HOOP: m => ["The design is larger than the hoop limit of the selected machine profile.", m],
  EXPORT_MISMATCH: () => ["The generated file did not match the stitch plan, so it was not released.", "Nothing was downloaded. Try again; if it repeats, report it with the design file."],
  EXPORT_TRUNCATED: () => ["The generated file was cut short, so it was not released.", "Try again; if it repeats, report it."],
  EXPORT_DIMENSIONS: () => ["The generated file has a different size or orientation than the design, so it was not released.", "Report it with the design file."],
  EXPORT_BAD_HEADER: () => ["The generated file header is inconsistent, so it was not released.", "Report it with the design file."],
  EXPORT_READER_MISMATCH: () => ["An independent DST reader disagrees with the generated file, so it was not released.", "Report it with the design file."]
};
const friendly = i => { const h = HELP[i.code]; return h ? h(i.message || "") : [i.message || "Something needs a look.", ""]; };
const friendlyLine = i => { const [a, b] = friendly(i); return a + (b ? " " + b : ""); };


/* ---------------------------------------------------------------- simulation */
let raf = null;
function togglePlay() {
  if (!S.gen || !S.gen.stitches) return; S.sim.playing = !S.sim.playing; $("#sPlay").textContent = S.sim.playing ? "⏸" : "▶";
  if (S.sim.playing) { setView(simView()); if (S.sim.i >= S.gen.stitches.length) S.sim.i = 0; tick(); }
}
function tick() {
  if (!S.sim.playing) return; const n = S.gen.stitches.length, step = Math.max(1, Math.round(Math.pow(+$("#sSpeed").value / 100, 2.2) * 400));
  S.sim.i = Math.min(n, S.sim.i + step); draw();
  if (S.sim.i >= n) { S.sim.playing = false; $("#sPlay").textContent = "▶"; return; } raf = requestAnimationFrame(tick);
}
function setView(v) {
  if (v === "3d") {
    if (typeof Viewer3D === "undefined" || !Viewer3D.supported() || !Viewer3D.init($("#gl"))) { alert("The 3D view needs WebGL, which this browser or device does not provide. The Stitches view works everywhere."); return; }
  }
  const was = S.vmode;
  S.vmode = v; document.querySelectorAll("#viewSeg button").forEach(b => b.classList.toggle("on", b.dataset.view === v));
  $("#cv").hidden = v === "3d"; $("#gl").hidden = v !== "3d"; $("#v3bar").hidden = v !== "3d"; $("#hint").hidden = v === "3d";
  // entering the stitch/3D view from the design view starts at the finished design; moving between them, or using the
  // simulation controls (which call setView), must NOT move the position - it used to, so Step and the slider read back the end.
  if ((v === "stitch" || v === "3d") && was === "design" && !S.sim.playing && S.gen && S.gen.stitches) S.sim.i = S.gen.stitches.length;
  if (v === "3d") { Viewer3D.resize(); feed3d(true); }
  if ((v === "stitch" || v === "3d") && was === "design" && !S.viewDstB64 && $("#sFile").checked && S.gen && S.gen.source === "plan") { S._keepSim = true; regen(); }
  draw();
}
const simView = () => S.vmode === "3d" ? "3d" : "stitch";      // the simulation controls keep you in the 3D view instead of dropping you back to 2D
function feed3d(force) {
  if (S.vmode !== "3d" || typeof Viewer3D === "undefined") return;
  if (force || S._g3 !== S.gen) { S._g3 = S.gen; Viewer3D.setData(S.gen && S.gen.stitches ? S.gen : {stitches: [], threads: []}); }
  Viewer3D.setProgress(S.sim.i);
}

/* ---------------------------------------------------------------- wiring */
document.querySelectorAll("#tools [data-tool]").forEach(b => b.onclick = () => setTool(b.dataset.tool));
document.querySelectorAll("#viewSeg button").forEach(b => b.onclick = () => setView(b.dataset.view));
document.querySelectorAll("#modeSeg button").forEach(b => b.onclick = () => { S.mode = b.dataset.mode; document.querySelectorAll("#modeSeg button").forEach(x => x.classList.toggle("on", x === b)); renderProps(); });
$("#bLib").onclick = openLibrary; $("#libx").onclick = closeLibrary;
$("#lib").onclick = e => { if (e.target.id === "lib") closeLibrary(); };
$("#libq").oninput = e => { libQ = e.target.value; renderLibrary(); };
$("#libcats").onclick = e => { if (e.target.dataset.cat) { libCat = e.target.dataset.cat; renderLibrary(); } };
$("#libgrid").onclick = e => { const b = e.target.closest("button[data-act]"); if (b) openFromLibrary(b.dataset.id, b.dataset.act === "3d"); };
$("#v3fab").onchange = e => Viewer3D.setFabric(e.target.value); $("#v3reset").onclick = () => Viewer3D.reset();
$("#bFit").onclick = fit; $("#bUndo").onclick = undo; $("#bRedo").onclick = redo; $("#bSave").onclick = saveProject; $("#bExport").onclick = exportDst; $("#bSheet").onclick = productionSheet; $("#bPkg").onclick = exportPackage; $("#bSvg").onclick = exportSvg; $("#bPng").onclick = exportPng; $("#bViewDst").onclick = () => { $("#mMore").open = false; $("#fileDst").click(); }; $("#bQuality").onclick = qualityCheck; $("#sbMore").onclick = () => $("#dlgStatus").showModal(); fetch("/api/formats").then(r => r.json()).then(f => { $("#sbFmt").textContent = f.export.map(x => x.id.toUpperCase()).join(", ") + " only"; }).catch(() => {}); $("#bEnhance").onclick = () => { $("#mMore").open = false; $("#fileEnhance").click(); }; $("#fileEnhance").onchange = e => { const f = e.target.files[0]; if (f) enhanceFile(f); e.target.value = ""; }; $("#bLetter").onclick = openLettering; $("#ltGo").onclick = e => { e.preventDefault(); lettering(); }; $("#bSet").onclick = openSet; $("#bWizard").onclick = openWizard;
$("#wzGo").onclick = e => { e.preventDefault(); wizardRun(); };
$("#dlgWizard").addEventListener("click", e => { const b = e.target.closest("[data-go]"); if (!b) return; e.preventDefault(); const n = +b.dataset.go; if (n > 2 && !WZ.res) return; if (n === 6) renderTestSteps(); wzStep(n); });
$("#wzExport").onclick = e => { e.preventDefault(); exportDst(); };
$("#wzSet").onclick = e => { e.preventDefault(); $("#dlgWizard").close(); openSet(); };
$("#wzEdit").onclick = e => { e.preventDefault(); $("#dlgWizard").close(); const b = document.querySelector('#modeSeg [data-mode="pro"]'); if (b) b.click(); };
$("#wzSheet").onclick = e => { e.preventDefault(); productionSheet(); }; $("#setGo").onclick = e => { e.preventDefault(); generateSet(); };
$("#mMore .pop").addEventListener("click", e => { if (e.target.closest("button")) setTimeout(() => $("#mMore").open = false, 0); });
document.addEventListener("click", e => { const m = $("#mMore"); if (m.open && !m.contains(e.target)) m.open = false; }); $("#fileDst").onchange = e => { const f = e.target.files[0]; if (f) viewDst(f); e.target.value = ""; };
$("#bNew").onclick = () => { if (!S.doc.objects.length || confirm("Discard the current design?")) loadDoc(newDoc()); };
$("#bOpen").onclick = () => $("#fileOpen").click(); $("#bImport").onclick = () => $("#fileImport").click();
$("#fileOpen").onchange = async e => { const f = e.target.files[0]; if (!f) return; try { const j = JSON.parse(await f.text()); if (!j.doc || !Array.isArray(j.doc.objects)) throw new Error("not an EmbroideryStudio project"); loadDoc(j.doc); } catch (err) { alert("Could not open: " + err.message); } e.target.value = ""; };
$("#fileImport").onchange = e => { const f = e.target.files[0]; if (f) importFile(f); e.target.value = ""; };
$("#docName").oninput = e => { S.doc.name = e.target.value; }; $("#docName").onchange = () => commit();
$("#bGroup").onclick = groupSelected; $("#bUngroup").onclick = ungroupSelected; $("#sJumps").onchange = draw; $("#sTrims").onchange = draw; $("#sRulers").onchange = draw; $("#sDens").onchange = () => { draw(); if ($("#sDens").checked && S.risk) $("#hint").textContent = `Density / risk: ${S.risk.dense} cells above 16 penetrations/mm², ${S.risk.amber} above 10, ${S.risk.shorts} stitches under 0.4 mm`; }; $("#sFile").onchange = () => { if (!S.viewDstB64) { S._keepSim = true; regen(); } };
$("#sBack").onclick = () => { S.sim.playing = false; $("#sPlay").textContent = "▶"; setView(simView()); S.sim.i = Math.max(0, S.sim.i - 1); draw(); }; $("#sPlay").onclick = togglePlay; $("#sStep").onclick = () => { S.sim.playing = false; setView(simView()); if (S.gen) S.sim.i = Math.min(S.gen.stitches.length, S.sim.i + 1); draw(); };
$("#sReset").onclick = () => { S.sim.playing = false; $("#sPlay").textContent = "▶"; setView(simView()); S.sim.i = 0; draw(); };
$("#sPos").oninput = e => { const v = +e.target.value;   /* read first: setView() redraws and re-syncs the slider to the old position */
  S.sim.playing = false; $("#sPlay").textContent = "▶"; setView(simView()); S.sim.i = v; draw(); };
addEventListener("resize", () => { resize(); if (S.vmode === "3d") Viewer3D.resize(); });

(async function init() {
  try { S.font = await (await fetch("/api/font")).json(); } catch (e) {}
  try { S.machines = (await (await fetch("/api/machines")).json()).machines; } catch (e) {}
  try { S.fabrics = (await (await fetch("/api/fabrics")).json()).fabrics; renderDesign(); } catch (e) {}
  let saved = null; try { saved = localStorage.getItem("es.autosave"); } catch (e) {}
  resize(); if (saved) { try { const d = JSON.parse(saved); if (d.objects) { S.doc = Object.assign(newDoc(), d); S.n = 1 + Math.max(0, ...S.doc.objects.map(o => parseInt(String(o.id).replace(/\D/g, "")) || 0)); } } catch (e) {} }
  $("#docName").value = S.doc.name; commit(); renderAll(); fit(); setTool("select");
  renderTemplates();
  window.__ES = S; window.__ESapi = {commit, renderAll, toScreen};      // test hooks (e2e)
})();
