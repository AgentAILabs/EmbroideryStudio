"use strict";
/* EmbroideryStudio front end. The engine (server) is the single source of truth for stitches;
   this file edits the design document and draws whatever the engine returns. */
const $ = (s, r = document) => r.querySelector(s);
const PALETTE = ["#000000","#ffffff","#7f7f7f","#c8102e","#e4572e","#f28c28","#ffc72c","#f6e27a","#9bd13b","#2e9e44","#0b6e4f","#14b8a6","#4cc3ff","#2563eb","#1e3a8a","#6d28d9","#c026d3","#ec4899","#f9a8d4","#7c4a2d","#d2a679","#b08d57","#d4af37","#a8a29e"];
const HOOPS = {"100 × 100 mm":[100,100],"130 × 180 mm":[130,180],"4 × 4 in":[101.6,101.6],"5 × 7 in":[127,177.8],"200 × 300 mm":[200,300],"240 × 150 mm":[240,150]};
const FABRICS = {cotton:{pull_comp:.2,spacing:.40},silk:{pull_comp:.3,spacing:.45},georgette:{pull_comp:.35,spacing:.45},velvet:{pull_comp:.4,spacing:.38},denim:{pull_comp:.1,spacing:.40},knit:{pull_comp:.4,spacing:.42}};
const DEF = {fill:{angle:45,spacing:.4,stitch_len:3.5,underlay:true,pull_comp:.2},satin:{width:3,spacing:.4,underlay:"auto",pull_comp:.2},run:{stitch_len:2.5},text:{spacing:1,underlay:"auto",pull_comp:.1},applique:{width:2.5,spacing:.4,stitch_len:2.5}};
const TOOLHINT = {select:"Click to select, drag to move, drag the white handles to edit points. Space+drag or right-drag pans, wheel zooms.",fill:"Click points of the shape. Double-click, Enter or click the first point to finish. Esc cancels.",satin:"Click along the centre line of the column. Double-click or Enter to finish.",run:"Click points of the line. Double-click or Enter to finish.",rect:"Drag to draw a rectangle.",ellipse:"Drag to draw an ellipse.",text:"Click where the text should start.",applique:"Click the outline of the appliqué patch. Double-click or Enter to finish."};

const S = { doc: newDoc(), sel: null, tool: "select", view: {x: 0, y: 0, z: 3}, mode: "beginner", vmode: "design",
  gen: null, draft: null, cursor: null, sim: {i: 0, playing: false}, hist: [], hi: -1, color: "#c8102e", font: null, n: 1 };
function newDoc() { return {name: "Untitled design", hoop: {w: 100, h: 100, margin: 3}, fabric: "cotton", objects: []}; }

/* ---------------------------------------------------------------- history / persistence */
function snap() { return JSON.stringify(S.doc); }
function commit() {
  const s = snap();
  if (S.hist[S.hi] === s) return;
  S.hist = S.hist.slice(0, S.hi + 1); S.hist.push(s); if (S.hist.length > 200) S.hist.shift(); S.hi = S.hist.length - 1;
  try { localStorage.setItem("es.autosave", s); } catch (e) {}
  regen();
}
function undo() { if (S.hi > 0) { S.hi--; S.doc = JSON.parse(S.hist[S.hi]); fixSel(); afterDocChange(); } }
function redo() { if (S.hi < S.hist.length - 1) { S.hi++; S.doc = JSON.parse(S.hist[S.hi]); fixSel(); afterDocChange(); } }
function fixSel() { if (!S.doc.objects.find(o => o.id === S.sel)) S.sel = null; }
function afterDocChange() { try { localStorage.setItem("es.autosave", snap()); } catch (e) {} regen(); renderAll(); }

/* ---------------------------------------------------------------- engine calls */
let regenTimer = null, regenSeq = 0;
function regen() { clearTimeout(regenTimer); regenTimer = setTimeout(doRegen, 200); }
async function doRegen() {
  const seq = ++regenSeq;
  if (!S.doc.objects.length) { S.gen = null; renderPanels(); draw(); return; }
  try {
    const r = await fetch("/api/generate", {method: "POST", body: JSON.stringify(S.doc)});
    const j = await r.json(); if (seq !== regenSeq) return;
    if (!r.ok) { S.gen = {error: j.error}; } else { S.gen = j; S.sim.i = Math.min(S.sim.i, j.stitches.length); if (!S.sim.playing && S.vmode === "stitch") S.sim.i = j.stitches.length; }
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
  if (o.points) return o.points;
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
  if (o.type === "text") { const p = f([o.x, o.y]); o.x = p[0]; o.y = p[1]; }
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
  return out;
}
function smooth(P, closed, n = 8) { if (P.length < 3) return P; const m = P.length, seg = closed ? m : m - 1, g = closed ? i => P[((i % m) + m) % m] : i => P[Math.max(0, Math.min(m - 1, i))]; const out = [P[0]];
  for (let i = 0; i < seg; i++) { const [a, b, c, d] = [g(i - 1), g(i), g(i + 1), g(i + 2)]; for (let k = 1; k <= n; k++) { const t = k / n; out.push([0, 1].map(j => .5 * (2 * b[j] + (-a[j] + c[j]) * t + (2 * a[j] - 5 * b[j] + 4 * c[j] - d[j]) * t * t + (-a[j] + 3 * b[j] - 3 * c[j] + d[j]) * t ** 3))); } }
  return closed ? out.slice(0, -1) : out; }
const shown = (o, pts, closed) => o.smooth ? smooth(pts, closed) : pts;
const dist2 = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2;
function segDist(p, a, b) { const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy; let t = l ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l : 0; t = Math.max(0, Math.min(1, t)); return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy); }
function inRing(p, r) { let c = false; for (let i = 0, j = r.length - 1; i < r.length; j = i++) { if ((r[i][1] > p[1]) !== (r[j][1] > p[1]) && p[0] < (r[j][0] - r[i][0]) * (p[1] - r[i][1]) / (r[j][1] - r[i][1]) + r[i][0]) c = !c; } return c; }
function hit(o, p, tol) {
  if (o.hidden) return false;
  if (o.type === "fill" || o.type === "applique") return o.rings.reduce((n, r) => n + inRing(p, r), 0) % 2 === 1 || o.rings.some(r => r.some((q, i) => segDist(p, q, r[(i + 1) % r.length]) < tol));
  if (o.type === "satin" || o.type === "run") { const w = o.type === "satin" ? ((o.params || {}).width ?? 3) / 2 : 0; const P = o.points; for (let i = 0; i < P.length - 1; i++) if (segDist(p, P[i], P[i + 1]) < Math.max(tol, w)) return true; return false; }
  if (o.type === "text") { const [w, h] = textSize(o); return p[0] >= o.x - tol && p[0] <= o.x + w + tol && p[1] >= o.y - tol && p[1] <= o.y + h + tol; }
  return false;
}
const selObj = () => S.doc.objects.find(o => o.id === S.sel);
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
    if (o.hidden) continue; const on = o.id === S.sel;
    c.save(); c.lineJoin = "round"; c.lineCap = "round";
    if (o.type === "fill" || o.type === "applique") {
      c.beginPath(); o.rings.forEach(r => pathOf(c, shown(o, r, true), true));
      c.fillStyle = o.color + (o.type === "applique" ? "99" : "cc"); c.fill("evenodd");
      c.strokeStyle = o.type === "applique" ? "#555" : "#0006"; c.setLineDash(o.type === "applique" ? [6, 4] : []); c.lineWidth = 1; c.stroke();
    } else if (o.type === "satin" || o.type === "run") {
      c.beginPath(); pathOf(c, shown(o, o.points, !!o.closed), !!o.closed); c.strokeStyle = o.color + (o.type === "satin" ? "cc" : "ff");
      c.lineWidth = Math.max(1.5, (o.type === "satin" ? P(o, "width") : .5) * S.view.z); c.stroke();
    } else if (o.type === "text") {
      c.strokeStyle = o.color; c.lineWidth = Math.max(1.5, (P(o, "width") || Math.min(o.height * .16, 4)) * S.view.z);
      for (const st of textStrokes(o)) { c.beginPath(); pathOf(c, st, false); c.stroke(); }
    }
    c.restore();
    if (on) {
      const b = bbox(allPts(o)); if (b) { const a = toScreen([b[0], b[1]]), d = toScreen([b[2], b[3]]); c.strokeStyle = "#2563eb"; c.setLineDash([4, 3]); c.lineWidth = 1; c.strokeRect(a[0] - 4, a[1] - 4, d[0] - a[0] + 8, d[1] - a[1] + 8); c.setLineDash([]); }
      if (o.type !== "text" && S.tool === "select") for (const p of allPts(o)) { const q = toScreen(p); c.fillStyle = "#fff"; c.strokeStyle = "#2563eb"; c.lineWidth = 1.5; c.beginPath(); c.rect(q[0] - 4, q[1] - 4, 8, 8); c.fill(); c.stroke(); }
    }
  }
}
function drawStitches(c, upto, thick) {
  const g = S.gen; if (!g || !g.stitches) return; const st = g.stitches; let prev = null, th = st.length ? st[0][3] : 0;
  const lw = Math.max(thick ? 1.2 : .7, .3 * S.view.z); c.lineWidth = lw; c.lineCap = "round"; c.lineJoin = "round";
  let batch = [], bcol = null;
  const flush = () => { if (batch.length) { c.strokeStyle = bcol; c.stroke(batch.path); } batch = []; };
  const mk = col => { flush(); bcol = col; batch = []; batch.path = new Path2D(); };
  mk(g.threads[th] || "#000"); let last = null;
  const n = Math.min(upto, st.length);
  for (let i = 0; i < n; i++) {
    const [x, y, cmd, t] = st[i]; const q = toScreen([x, y]);
    if (cmd === 3) { th = t; prev = prev; mk(g.threads[t] || "#000"); continue; }
    if (cmd === 2 || cmd === 4) continue;
    if (cmd === 1) { prev = q; continue; }
    if (t !== th) { th = t; mk(g.threads[t]); }
    if (prev) { batch.path.moveTo(prev[0], prev[1]); batch.path.lineTo(q[0], q[1]); batch.push(1); }
    prev = q; last = q;
  }
  flush();
  return n > 0 && n <= st.length ? toScreen([st[Math.min(n, st.length) - 1][0], st[Math.min(n, st.length) - 1][1]]) : null;
}
function draw() {
  const d = devicePixelRatio || 1; ctx.setTransform(d, 0, 0, d, 0, 0); ctx.clearRect(0, 0, cv.clientWidth, cv.clientHeight);
  drawGrid(ctx);
  if (S.vmode === "design") { drawObjects(ctx); }
  else if (S.gen && S.gen.stitches) {
    const needle = drawStitches(ctx, S.sim.i, true);
    if (needle) { ctx.fillStyle = "#ef4444"; ctx.beginPath(); ctx.arc(needle[0], needle[1], 4, 0, 7); ctx.fill(); }
  } else drawObjects(ctx);
  if (S.draft) drawDraft();
  const n = S.gen && S.gen.stitches ? S.gen.stitches.length : 0; $("#sPos").max = n; $("#sPos").value = S.sim.i; $("#sInfo").textContent = `${S.sim.i} / ${n}`;
}
function drawDraft() {
  const dr = S.draft, c = ctx; c.save(); c.strokeStyle = "#2563eb"; c.lineWidth = 2; c.setLineDash([5, 3]);
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
function finishDraft() {
  const dr = S.draft; S.draft = null; if (!dr) return;
  if (dr.kind === "poly") {
    const pts = dr.pts; const t = S.tool;
    if ((t === "fill" || t === "applique") && pts.length >= 3) addObject({type: t, rings: [pts]});
    else if (t === "satin" && pts.length >= 2) addObject({type: "satin", points: pts});
    else if (t === "run" && pts.length >= 2) addObject({type: "run", points: pts});
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
  if (t === "select") {
    const o = selObj();
    if (o && o.type !== "text") { const tolPx = 8 / S.view.z; for (let ri = 0; ri < (o.rings ? o.rings.length : 1); ri++) { const arr = o.rings ? o.rings[ri] : o.points; for (let i = 0; i < arr.length; i++) if (dist2(arr[i], w) < tolPx * tolPx) { drag = {type: "vertex", arr, i}; return; } } }
    const tol = 5 / S.view.z; let found = null;
    for (let i = S.doc.objects.length - 1; i >= 0; i--) if (hit(S.doc.objects[i], w, tol)) { found = S.doc.objects[i]; break; }
    S.sel = found ? found.id : null; renderAll();
    if (found) drag = {type: "move", last: w, moved: false}; return;
  }
  if (t === "rect" || t === "ellipse") { const p = snapP(w, e.altKey); S.draft = {kind: t, a: p, b: p}; drag = {type: "shape"}; return; }
  if (t === "text") { const p = snapP(w, e.altKey); const o = addObject({type: "text", text: "TEXT", height: 10, x: p[0], y: p[1]}); S.tool = "select"; setTool("select"); return; }
  const p = snapP(w, e.altKey);
  if (!S.draft) S.draft = {kind: "poly", pts: []};
  const pts = S.draft.pts;
  if ((t === "fill" || t === "applique") && pts.length >= 3 && dist2(p, pts[0]) < (8 / S.view.z) ** 2) { finishDraft(); return; }
  if (!pts.length || dist2(p, pts[pts.length - 1]) > 1e-6) pts.push(p); draw();
});
cv.addEventListener("dblclick", e => { if (S.draft && S.draft.kind === "poly") { if (S.draft.pts.length > 1) S.draft.pts.pop(); finishDraft(); } });
cv.addEventListener("pointermove", e => {
  const [sx, sy] = evP(e); const w = toWorld(sx, sy); S.cursor = snapP(w, e.altKey);
  $("#hint").textContent = TOOLHINT[S.tool] + `   [${w[0].toFixed(1)}, ${w[1].toFixed(1)} mm]`;
  if (!drag) { if (S.draft) draw(); return; }
  if (drag.type === "pan") { S.view.x = drag.vx - (sx - drag.sx) / S.view.z; S.view.y = drag.vy - (sy - drag.sy) / S.view.z; }
  else if (drag.type === "move") { const o = selObj(); let dx = w[0] - drag.last[0], dy = w[1] - drag.last[1]; mapPts(o, p => [p[0] + dx, p[1] + dy]); drag.last = w; drag.moved = true; }
  else if (drag.type === "vertex") { const p = snapP(w, e.altKey); drag.arr[drag.i][0] = p[0]; drag.arr[drag.i][1] = p[1]; drag.moved = true; }
  else if (drag.type === "shape") S.draft.b = S.cursor;
  draw();
});
cv.addEventListener("pointerup", () => {
  if (!drag) return; const d = drag; drag = null;
  if (d.type === "shape") finishDraft(); else if (d.moved) { commit(); renderPanels(); }
  draw();
});
addEventListener("keydown", e => {
  const tag = (e.target.tagName || "").toLowerCase(); if (tag === "input" || tag === "select" || tag === "textarea") { if (e.key === "Escape") e.target.blur(); return; }
  if (e.key === " ") { spaceDown = true; e.preventDefault(); return; }
  const k = e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && k === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if ((e.ctrlKey || e.metaKey) && k === "y") { e.preventDefault(); redo(); return; }
  if ((e.ctrlKey || e.metaKey) && k === "s") { e.preventDefault(); saveProject(); return; }
  if ((e.ctrlKey || e.metaKey) && k === "d") { e.preventDefault(); duplicate(0, 0); return; }
  if (e.key === "Escape") { S.draft = null; draw(); return; }
  if (e.key === "Enter" && S.draft) { finishDraft(); return; }
  if ((e.key === "Delete" || e.key === "Backspace") && S.sel) { deleteSel(); return; }
  const map = {v: "select", f: "fill", s: "satin", r: "run", t: "text", a: "applique"};
  if (map[k] && !e.ctrlKey) { setTool(map[k]); return; }
  if (k === "p") { togglePlay(); return; }
  if (e.key === "0") { fit(); return; }
  const o = selObj(); if (o && e.key.startsWith("Arrow")) { e.preventDefault(); const st = e.shiftKey ? 5 : .5; const d = {ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, -st], ArrowDown: [0, st]}[e.key]; mapPts(o, p => [p[0] + d[0], p[1] + d[1]]); commit(); renderAll(); }
});
addEventListener("keyup", e => { if (e.key === " ") spaceDown = false; });

/* ---------------------------------------------------------------- operations */
function deleteSel() { S.doc.objects = S.doc.objects.filter(o => o.id !== S.sel); S.sel = null; commit(); renderAll(); }
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
async function importFile(file) {
  try {
    let res;
    if (/\.svg$/i.test(file.name)) { res = await post("/api/import/svg", {svg: await file.text()}); }
    else {
      const w = parseFloat(prompt("Real-world width of the artwork in mm (flat colours work best; photos digitize poorly):", String(Math.round(S.doc.hoop.w * .7))));
      if (!w) return; const cols = parseInt(prompt("Maximum number of thread colours (2–12):", "6")) || 6;
      const buf = new Uint8Array(await file.arrayBuffer()); let bin = ""; for (let i = 0; i < buf.length; i += 8192) bin += String.fromCharCode(...buf.subarray(i, i + 8192));
      res = await post("/api/import/raster", {data: btoa(bin), width_mm: w, colors: cols});
    }
    if (!res.objects.length) { alert("Nothing to digitize. For images, use flat-colour artwork on a plain background."); return; }
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
  if (!r.ok) { const j = await r.json(); alert("Export blocked:\n" + (j.issues || [{message: j.error}]).filter(i => !i.severity || i.severity === "error").map(i => "• " + i.message).join("\n")); return; }
  download((S.doc.name || "design").replace(/[^\w-]+/g, "_") + ".dst", await r.arrayBuffer(), "application/octet-stream");
  if ((S.gen && S.gen.issues || []).some(i => i.severity === "warning")) alert("Exported with warnings (see Checks). Stitch a test sample before production use.");
}
function productionSheet() {
  if (!S.gen || !S.gen.stats) { alert("Nothing to report yet."); return; }
  const st = S.gen.stats, off = document.createElement("canvas"); off.width = 600; off.height = 600; const c = off.getContext("2d");
  const save = {v: {...S.view}, cw: Object.getOwnPropertyDescriptor(cv, "clientWidth")};
  const h = S.doc.hoop, v0 = S.view; const z = 560 / Math.max(h.w, h.h);
  const real = {w: cv.clientWidth, h: cv.clientHeight}; Object.defineProperty(cv, "clientWidth", {value: 600, configurable: true}); Object.defineProperty(cv, "clientHeight", {value: 600, configurable: true});
  S.view = {x: 0, y: 0, z}; c.fillStyle = "#fff"; c.fillRect(0, 0, 600, 600); drawGrid(c); drawStitches(c, 1e9, false);
  const img = off.toDataURL("image/png"); delete cv.clientWidth; delete cv.clientHeight; S.view = v0;
  const rows = st.color_sequence.map((s, i) => `<tr><td>${i + 1}</td><td><span style="display:inline-block;width:16px;height:16px;background:${s.hex};border:1px solid #000"></span> ${s.hex}</td><td>${s.stitches}</td></tr>`).join("");
  const emb = S.doc.objects.filter(o => o.type === "applique").length;
  const html = `<!doctype html><title>Production sheet – ${esc(S.doc.name)}</title><style>body{font:14px system-ui;margin:24px;max-width:820px}table{border-collapse:collapse}td,th{border:1px solid #999;padding:4px 10px;text-align:left}h1{margin:0}.m{color:#555}</style>
<h1>${esc(S.doc.name)}</h1><p class="m">EmbroideryStudio production sheet · ${new Date().toLocaleString()}</p><img src="${img}" width="420" style="float:right;border:1px solid #ccc">
<p><b>Design size:</b> ${st.width_mm} × ${st.height_mm} mm<br><b>Hoop:</b> ${h.w} × ${h.h} mm (margin ${h.margin} mm)<br><b>Fabric preset:</b> ${S.doc.fabric} (unverified starting values)<br><b>Stitches:</b> ${st.stitches}<br><b>Colour changes:</b> ${st.color_changes} · <b>Trims:</b> ${st.trims} · <b>Jumps:</b> ${st.jumps}<br><b>Estimated run time:</b> ~${st.est_minutes} min at ${st.assumed_spm} spm (assumed)</p>
<h3>Colour order</h3><table><tr><th>#</th><th>Thread</th><th>Stitches</th></tr>${rows}</table>
${emb ? `<p><b>Appliqué:</b> ${emb} patch(es). At the placement→tack-down colour change, place fabric; trim after tack-down.</p>` : ""}
<div style="clear:both"></div><p class="m">Not machine-tested. Stitch a sample on matching fabric and stabiliser before production use.</p>`;
  const w = window.open("", "_blank"); if (w) { w.document.write(html); w.document.close(); } else alert("Allow pop-ups to view the production sheet.");
}
async function exportSvg() { if (!S.doc.objects.length) return; const r = await fetch("/api/export/svg", {method: "POST", body: JSON.stringify(S.doc)}); if (!r.ok) { alert("Preview failed"); return; } download((S.doc.name || "design").replace(/[^\w-]+/g, "_") + ".preview.svg", await r.text(), "image/svg+xml"); }
async function viewDst(file) {
  try { const buf = new Uint8Array(await file.arrayBuffer()); let bin = ""; for (let i = 0; i < buf.length; i += 8192) bin += String.fromCharCode(...buf.subarray(i, i + 8192));
    const j = await post("/api/import/dst", {data: btoa(bin)}); const st = j.stitches; const xs = st.map(s => s[0]), ys = st.map(s => s[1]);
    const w = Math.max(...xs) - Math.min(...xs), h = Math.max(...ys) - Math.min(...ys);
    S.gen = {stitches: st, threads: j.threads, stats: {stitches: st.filter(s => s[2] === 0).length, jumps: st.filter(s => s[2] === 1).length, trims: 0, color_changes: j.color_changes, width_mm: +w.toFixed(1), height_mm: +h.toFixed(1), est_minutes: 0, color_sequence: j.threads.map((hex, i) => ({hex, stitches: st.filter(s => s[2] === 0 && s[3] === i).length}))}, issues: [], notes: ["Viewing " + file.name + " (read-only). Edit the design or press Undo to return to your project."]};
    const hw = Math.max(S.doc.hoop.w, w + 20), hh = Math.max(S.doc.hoop.h, h + 20); S.doc.hoop.w = Math.ceil(hw); S.doc.hoop.h = Math.ceil(hh); S.sim.i = st.length; setView("stitch"); fit(); renderPanels();
  } catch (e) { alert("Could not read DST: " + e.message); }
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

/* ---------------------------------------------------------------- panels */
function setTool(t) { S.tool = t; S.draft = null; document.querySelectorAll("#tools [data-tool]").forEach(b => b.classList.toggle("on", b.dataset.tool === t)); $("#hint").textContent = TOOLHINT[t]; cv.style.cursor = t === "select" ? "default" : "crosshair"; draw(); }
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
  h += `<div class="note">Thread colour</div><div class="sw" id="osw"></div><div class="row"><label>Custom</label><input type="color" data-k="color" data-d=1 value="${o.color}"></div>`;
  if (o.type !== "text") h += field("Smooth curve", "smooth", o, {type: "check", direct: 1});
  if (o.type === "fill") h += field("Direction °", "angle", o, {step: 5, tip: "Stitch angle"}) + field("Row spacing mm", "spacing", o, {step: .05, min: .2, pro: 1, tip: "Smaller = denser"}) + field("Stitch length mm", "stitch_len", o, {step: .5, min: 1, pro: 1}) + field("Underlay", "underlay", o, {options: ["tatami", "edge", "edge+tatami", "none"], pro: 1}) + field("Pull comp mm", "pull_comp", o, {step: .05, min: 0, pro: 1, tip: "Extra length to offset fabric pull-in"});
  if (o.type === "satin") h += field("Width mm", "width", o, {step: .25, min: .8}) + field("Underlay", "underlay", o, {options: ["auto", "center", "edge", "none"], pro: 1}) + field("Spacing mm", "spacing", o, {step: .05, min: .2, pro: 1}) + field("Pull comp mm", "pull_comp", o, {step: .05, min: 0, pro: 1});
  if (o.type === "run") h += field("Stitch length mm", "stitch_len", o, {step: .5, min: .5}) + field("Closed loop", "closed", o, {type: "check", direct: 1});
  if (o.type === "text") h += `<div class="row"><label>Text</label><input type="text" data-k="text" data-d=1 value="${esc(o.text)}"></div>` + field("Height mm", "height", o, {direct: 1, step: .5, min: 3}) + field("Letter spacing", "spacing", o, {step: .1, min: .5}) + field("Stroke width mm", "width", o, {step: .25, min: 1, tip: "Satin column width of each stroke"}) + `<div class="note">Built-in single-line satin font (A–Z, 0–9, - . !). Minimum practical height ≈ 5 mm.</div>`;
  if (o.type === "applique") h += field("Cover width mm", "width", o, {step: .25, min: 1.5}) + `<div class="note">Stitches: placement line → tack-down → satin cover. The machine pauses at the colour change so you can lay fabric.</div>`;
  h += `<div class="btns"><button data-op="dup">Duplicate</button><button data-op="fh">Flip ↔</button><button data-op="fv">Flip ↕</button><button data-op="r90">Rotate 90°</button>${o.rings ? `<button data-op="outline">Add border</button>` : ""}<button data-op="del">Delete</button></div>`;
  h += `<div class="row"><label>Scale %</label><input type="number" id="scalePct" value="100" step="5"></div><div class="btns"><button data-op="scale">Apply scale</button></div>`;
  h += `<div class="row"><label>Repeat ×</label><input type="number" id="repN" value="5" min="2" max="200"></div><div class="row"><label>Offset X,Y mm</label><span style="display:flex;gap:4px"><input type="number" id="repX" value="12" step="1" style="width:50%"><input type="number" id="repY" value="0" step="1" style="width:50%"></span></div><div class="btns"><button data-op="repeat">Repeat (border / row)</button></div>`;
  el.innerHTML = h; swatches($("#osw"), o.color, c => { o.color = c; commit(); renderAll(); });
  el.querySelectorAll("[data-k]").forEach(inp => {
    const apply = () => { const k = inp.dataset.k; let v = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? parseFloat(inp.value) : inp.value; if (inp.type === "number" && isNaN(v)) return;
      if (inp.dataset.d) o[k] = v; else { o.params = o.params || {}; o.params[k] = v; } draw(); if (k !== "name") regenSoft(); };
    inp.addEventListener("input", apply); inp.addEventListener("change", () => { apply(); commit(); renderObjs(); });
  });
  el.querySelectorAll("[data-op]").forEach(b => b.onclick = () => ({
    dup: () => duplicate(3, 3), del: deleteSel, outline, scale: () => scaleSel(parseFloat($("#scalePct").value) || 100),
    fh: () => transformSel((p, cx) => [2 * cx - p[0], p[1]], false), fv: () => transformSel((p, cx, cy) => [p[0], 2 * cy - p[1]], false),
    r90: () => transformSel((p, cx, cy) => [cx - (p[1] - cy), cy + (p[0] - cx)], false),
    repeat: () => duplicate(parseFloat($("#repX").value) || 0, parseFloat($("#repY").value) || 0, parseInt($("#repN").value) - 1 || 1)
  })[b.dataset.op]());
}
function regenSoft() { regen(); }
function swatches(el, cur, cb) { el.innerHTML = PALETTE.map(c => `<i style="background:${c}" data-c="${c}" class="${c === cur ? "on" : ""}" title="${c}"></i>`).join(""); el.onclick = e => { if (e.target.dataset.c) cb(e.target.dataset.c); }; }
function renderObjs() {
  $("#objs").innerHTML = S.doc.objects.map(o => `<li data-id="${o.id}" class="${o.id === S.sel ? "on" : ""} ${o.hidden ? "hid" : ""}"><span class="c" style="background:${o.color}"></span><span class="n">${esc(o.name || o.id)} <small>${o.type}</small></span><button data-a="up" title="Stitch earlier">▲</button><button data-a="dn" title="Stitch later">▼</button><button data-a="eye" title="Hide/show">${o.hidden ? "◌" : "◉"}</button></li>`).join("") || `<li class="note">No objects yet.</li>`;
  $("#objs").onclick = e => { const li = e.target.closest("li[data-id]"); if (!li) return; const id = li.dataset.id, a = e.target.dataset.a;
    if (a === "up") return moveOrder(id, -1); if (a === "dn") return moveOrder(id, 1);
    if (a === "eye") { const o = S.doc.objects.find(o => o.id === id); o.hidden = !o.hidden; commit(); return renderAll(); }
    S.sel = id; renderAll(); };
}
function renderDesign() {
  const d = S.doc, el = $("#designProps"); if (el.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  el.innerHTML = `<div class="row"><label>Hoop</label><select id="hoopSel">${Object.keys(HOOPS).map(k => `<option ${(Math.abs(HOOPS[k][0] - d.hoop.w) < .2 && Math.abs(HOOPS[k][1] - d.hoop.h) < .2) ? "selected" : ""}>${k}</option>`).join("")}<option ${Object.values(HOOPS).some(h => Math.abs(h[0] - d.hoop.w) < .2 && Math.abs(h[1] - d.hoop.h) < .2) ? "" : "selected"}>Custom</option></select></div>
  <div class="row"><label>Hoop W × H mm</label><span style="display:flex;gap:4px"><input type="number" id="hw" value="${d.hoop.w}" style="width:50%"><input type="number" id="hh" value="${d.hoop.h}" style="width:50%"></span></div>
  <div class="row"><label>Safe margin mm</label><input type="number" id="hm" value="${d.hoop.margin}" step=".5" min="0"></div>
  <div class="row"><label>Fabric preset</label><select id="fab">${Object.keys(FABRICS).map(k => `<option ${k === d.fabric ? "selected" : ""}>${k}</option>`).join("")}</select></div>
  <div class="note">Fabric values are unverified starting points; they apply to new objects. <button id="fabApply" style="padding:1px 6px">Apply to all</button></div>
  <div class="btns"><button id="bCenter">Centre design</button></div>`;
  const setH = (w, h) => { d.hoop.w = w; d.hoop.h = h; commit(); fit(); renderAll(); };
  $("#hoopSel").onchange = e => { const v = HOOPS[e.target.value]; if (v) setH(v[0], v[1]); };
  $("#hw").onchange = () => setH(+$("#hw").value || 100, d.hoop.h); $("#hh").onchange = () => setH(d.hoop.w, +$("#hh").value || 100);
  $("#hm").onchange = () => { d.hoop.margin = +$("#hm").value || 0; commit(); renderAll(); };
  $("#fab").onchange = e => { d.fabric = e.target.value; commit(); };
  $("#fabApply").onclick = () => { const f = FABRICS[d.fabric]; d.objects.forEach(o => { if (o.type === "fill" || o.type === "satin") o.params = Object.assign(o.params || {}, f); }); commit(); renderAll(); };
  $("#bCenter").onclick = centerAll;
}
function renderSeq() {
  const g = S.gen; $("#seq").innerHTML = g && g.stats ? g.stats.color_sequence.map((s, i) => `<div class="seqrow"><i style="background:${s.hex}"></i>${i + 1}. ${s.hex} <span class="note">· ${s.stitches} st</span></div>`).join("") : `<div class="note">—</div>`;
}
function renderStats() {
  const g = S.gen, el = $("#stats"), il = $("#issues");
  if (!g) { el.innerHTML = `<span>Add objects to see stitch data.</span>`; il.innerHTML = ""; return; }
  if (g.error) { el.innerHTML = `<span class="e">${esc(g.error)}</span>`; il.innerHTML = ""; return; }
  const s = g.stats; el.innerHTML = `<span>Stitches</span><b>${s.stitches}</b><span>Size</span><b>${s.width_mm} × ${s.height_mm} mm</b><span>Colour changes</span><b>${s.color_changes}</b><span>Trims / jumps</span><b>${s.trims} / ${s.jumps}</b><span>Est. time</span><b>~${s.est_minutes} min</b>`;
  const items = g.issues.reduce((a, i) => { const k = i.code + i.severity; (a[k] = a[k] || {...i, n: 0}).n++; return a; }, {});
  const lst = Object.values(items).map(i => `<li class="${i.severity === "error" ? "e" : "w"}">${i.severity === "error" ? "✖" : "⚠"} ${esc(HELP[i.code] || i.message)}${i.n > 1 ? ` <small>(×${i.n})</small>` : ""}</li>`);
  (g.notes || []).forEach(n => lst.push(`<li class="w">ℹ ${esc(n)}</li>`));
  il.innerHTML = lst.join("") || `<li class="ok">✔ No problems found</li>`;
}
const HELP = {HOOP: null, STITCH_SHORT: "Some stitches are very short (<0.3 mm). Increase row spacing or simplify tiny shapes.", DENSITY: null, STITCH_LONG: "Some stitches are long and may snag. Shorten stitch length or split wide satin columns.", ZERO_LENGTH: "Duplicate stitch points found."};
Object.keys(HELP).forEach(k => HELP[k] === null && delete HELP[k]);

/* ---------------------------------------------------------------- simulation */
let raf = null;
function togglePlay() {
  if (!S.gen || !S.gen.stitches) return; S.sim.playing = !S.sim.playing; $("#sPlay").textContent = S.sim.playing ? "⏸" : "▶";
  if (S.sim.playing) { setView("stitch"); if (S.sim.i >= S.gen.stitches.length) S.sim.i = 0; tick(); }
}
function tick() {
  if (!S.sim.playing) return; const n = S.gen.stitches.length, step = Math.max(1, Math.round(Math.pow(+$("#sSpeed").value / 100, 2.2) * 400));
  S.sim.i = Math.min(n, S.sim.i + step); draw();
  if (S.sim.i >= n) { S.sim.playing = false; $("#sPlay").textContent = "▶"; return; } raf = requestAnimationFrame(tick);
}
function setView(v) { S.vmode = v; document.querySelectorAll("#viewSeg button").forEach(b => b.classList.toggle("on", b.dataset.view === v)); if (v === "stitch" && !S.sim.playing && S.gen && S.gen.stitches) S.sim.i = S.gen.stitches.length; draw(); }

/* ---------------------------------------------------------------- wiring */
document.querySelectorAll("#tools [data-tool]").forEach(b => b.onclick = () => setTool(b.dataset.tool));
document.querySelectorAll("#viewSeg button").forEach(b => b.onclick = () => setView(b.dataset.view));
document.querySelectorAll("#modeSeg button").forEach(b => b.onclick = () => { S.mode = b.dataset.mode; document.querySelectorAll("#modeSeg button").forEach(x => x.classList.toggle("on", x === b)); renderProps(); });
$("#bFit").onclick = fit; $("#bUndo").onclick = undo; $("#bRedo").onclick = redo; $("#bSave").onclick = saveProject; $("#bExport").onclick = exportDst; $("#bSheet").onclick = productionSheet; $("#bSvg").onclick = exportSvg; $("#bViewDst").onclick = () => $("#fileDst").click(); $("#fileDst").onchange = e => { const f = e.target.files[0]; if (f) viewDst(f); e.target.value = ""; };
$("#bNew").onclick = () => { if (!S.doc.objects.length || confirm("Discard the current design?")) loadDoc(newDoc()); };
$("#bOpen").onclick = () => $("#fileOpen").click(); $("#bImport").onclick = () => $("#fileImport").click();
$("#fileOpen").onchange = async e => { const f = e.target.files[0]; if (!f) return; try { const j = JSON.parse(await f.text()); if (!j.doc || !Array.isArray(j.doc.objects)) throw new Error("not an EmbroideryStudio project"); loadDoc(j.doc); } catch (err) { alert("Could not open: " + err.message); } e.target.value = ""; };
$("#fileImport").onchange = e => { const f = e.target.files[0]; if (f) importFile(f); e.target.value = ""; };
$("#docName").oninput = e => { S.doc.name = e.target.value; }; $("#docName").onchange = () => commit();
$("#sPlay").onclick = togglePlay; $("#sStep").onclick = () => { S.sim.playing = false; setView("stitch"); if (S.gen) S.sim.i = Math.min(S.gen.stitches.length, S.sim.i + 1); draw(); };
$("#sReset").onclick = () => { S.sim.playing = false; $("#sPlay").textContent = "▶"; setView("stitch"); S.sim.i = 0; draw(); };
$("#sPos").oninput = e => { S.sim.playing = false; $("#sPlay").textContent = "▶"; setView("stitch"); S.sim.i = +e.target.value; draw(); };
addEventListener("resize", resize);

(async function init() {
  try { S.font = await (await fetch("/api/font")).json(); } catch (e) {}
  let saved = null; try { saved = localStorage.getItem("es.autosave"); } catch (e) {}
  resize(); if (saved) { try { const d = JSON.parse(saved); if (d.objects) { S.doc = Object.assign(newDoc(), d); S.n = 1 + Math.max(0, ...S.doc.objects.map(o => parseInt(String(o.id).replace(/\D/g, "")) || 0)); } } catch (e) {} }
  $("#docName").value = S.doc.name; commit(); renderAll(); fit(); setTool("select");
  window.__ES = S;
})();
