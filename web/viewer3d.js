"use strict";
/* Viewer3D - zero-dependency WebGL thread viewer. Each stitch is a ribbon shaded like a cylinder (thread) with an anisotropic
   (Kajiya-Kay) sheen along the thread direction; later stitches sit slightly higher, so layering reads correctly. Fabric is a
   procedural weave. Orbit (drag), pan (right-drag / Shift-drag), zoom (wheel), reset (double-click).
   API: Viewer3D.supported() / init(canvas) / setData({stitches,threads}) / setProgress(n) / setFabric(hex) / resize() / reset()
        / stats() / sample(x,y) */
const Viewer3D = (() => {
  let gl = null, cv = null, thread = null, fabric = null, buf = null, fbuf = null;
  let vcount = 0, shown = 0, segEnd = [0], nStitches = 0, bbox = [0, 0, 1, 1];
  const cam = {yaw: 0, pitch: 62 * Math.PI / 180, dist: 150, tx: 0, ty: 0, tz: 0};
  let fabricRGB = [0.05, 0.29, 0.19], rafPending = false, handlers = null;
  const MAX_SEGMENTS = 450000, HALF_W = 0.2, FLOATS = 11;

  const VS = `attribute vec3 aPos;attribute vec2 aTan;attribute vec2 aNrm;attribute float aV;attribute vec3 aCol;
uniform mat4 uVP;varying vec3 vCol;varying vec2 vTan;varying vec2 vNrm;varying float vV;varying vec3 vW;
void main(){vCol=aCol;vTan=aTan;vNrm=aNrm;vV=aV;vW=aPos;gl_Position=uVP*vec4(aPos,1.0);}`;
  const FS = `precision mediump float;varying vec3 vCol;varying vec2 vTan;varying vec2 vNrm;varying float vV;varying vec3 vW;
uniform vec3 uEye;uniform vec3 uLight;
void main(){
  float c=sqrt(max(0.0,1.0-vV*vV));
  vec3 N=normalize(vec3(vNrm*vV,c));vec3 T=normalize(vec3(vTan,0.0));
  vec3 L=normalize(uLight);vec3 V=normalize(uEye-vW);vec3 H=normalize(L+V);
  float diff=max(dot(N,L),0.0)*0.72+0.30;
  float th=dot(T,H);float sheen=pow(sqrt(max(0.0,1.0-th*th)),38.0)*0.55;
  float edge=1.0-0.30*pow(abs(vV),3.0);
  gl_FragColor=vec4(vCol*diff*edge+sheen*mix(vec3(1.0),vCol,0.35),1.0);}`;
  const FVS = `attribute vec3 aPos;uniform mat4 uVP;varying vec2 vP;void main(){vP=aPos.xy;gl_Position=uVP*vec4(aPos,1.0);}`;
  const FFS = `precision mediump float;varying vec2 vP;uniform vec3 uBase;
void main(){float w=0.5+0.5*sin(vP.x*13.0)*sin(vP.y*13.0);float g=0.5+0.5*sin(vP.x*1.3+vP.y*0.7);
  gl_FragColor=vec4(uBase*(0.82+0.14*w+0.04*g),1.0);}`;

  function mat4mul(a, b) { const o = new Float32Array(16); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k]; o[i * 4 + j] = s; } return o; }
  function perspective(fovy, asp, n, f) { const t = 1 / Math.tan(fovy / 2), o = new Float32Array(16); o[0] = t / asp; o[5] = t; o[10] = (f + n) / (n - f); o[11] = -1; o[14] = 2 * f * n / (n - f); return o; }
  function lookAt(e, c, u) {
    const z = norm(sub(e, c)), x = norm(cross(u, z)), y = cross(z, x), o = new Float32Array(16);
    o[0] = x[0]; o[4] = x[1]; o[8] = x[2]; o[12] = -dot(x, e); o[1] = y[0]; o[5] = y[1]; o[9] = y[2]; o[13] = -dot(y, e);
    o[2] = z[0]; o[6] = z[1]; o[10] = z[2]; o[14] = -dot(z, e); o[15] = 1; return o;
  }
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]], dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = a => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
  const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255);

  function program(vs, fs) {
    const mk = (t, src) => { const s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const p = gl.createProgram(); gl.attachShader(p, mk(gl.VERTEX_SHADER, vs)); gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)); return p;
  }
  function supported() { try { const c = document.createElement("canvas"); return !!(c.getContext("webgl") || c.getContext("experimental-webgl")); } catch (e) { return false; } }

  function init(canvas) {
    cv = canvas;
    if (gl) return true;
    try { gl = cv.getContext("webgl", {antialias: true, alpha: false, preserveDrawingBuffer: true}) || cv.getContext("experimental-webgl"); if (!gl) return false;
      thread = program(VS, FS); fabric = program(FVS, FFS); buf = gl.createBuffer(); fbuf = gl.createBuffer(); bind(); }
    catch (e) { console.error("Viewer3D init failed:", e); gl = null; return false; }
    return true;
  }

  function bind() {
    let drag = null;
    const down = e => { cv.setPointerCapture(e.pointerId); drag = {x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey}; };
    const move = e => {
      if (!drag) return; const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.x = e.clientX; drag.y = e.clientY;
      if (drag.pan) { const k = cam.dist * 0.0016; cam.tx -= (dx * Math.cos(cam.yaw) + dy * Math.sin(cam.yaw) * Math.sin(cam.pitch)) * k; cam.ty += (dx * Math.sin(cam.yaw) - dy * Math.cos(cam.yaw) * Math.sin(cam.pitch)) * k; }
      else { cam.yaw -= dx * 0.008; cam.pitch = Math.max(0.12, Math.min(Math.PI / 2, cam.pitch + dy * 0.008)); }
      schedule();
    };
    const up = () => { drag = null; };
    const wheel = e => { e.preventDefault(); cam.dist = Math.max(15, Math.min(1500, cam.dist * (e.deltaY < 0 ? 0.9 : 1.1))); schedule(); };
    const ctx = e => e.preventDefault(), dbl = () => reset();
    cv.addEventListener("pointerdown", down); cv.addEventListener("pointermove", move); cv.addEventListener("pointerup", up); cv.addEventListener("pointercancel", up);
    cv.addEventListener("wheel", wheel, {passive: false}); cv.addEventListener("contextmenu", ctx); cv.addEventListener("dblclick", dbl);
    handlers = {down, move, up, wheel, ctx, dbl};
  }

  function setData(g) {
    if (!gl) return false;
    const st = g && g.stitches ? g.stitches : [], cols = (g && g.threads) || [];
    nStitches = st.length;
    const out = new Float32Array(Math.min(MAX_SEGMENTS, st.length) * 6 * FLOATS);
    let o = 0, nSeg = 0, px = 0, py = 0, pen = false; segEnd = new Array(st.length + 1).fill(0);
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    for (const s of st) if (s[2] === 0) { minX = Math.min(minX, s[0]); maxX = Math.max(maxX, s[0]); minY = Math.min(minY, -s[1]); maxY = Math.max(maxY, -s[1]); }
    if (minX > maxX) { minX = minY = -10; maxX = maxY = 10; }
    bbox = [minX, minY, maxX, maxY];
    let th = st.length ? st[0][3] : 0;
    for (let i = 0; i < st.length; i++) {
      const [x, y0, cmd, t] = st[i], y = -y0;                       // design y points down; the world has y up
      segEnd[i] = o / FLOATS;
      if (cmd === 3) { th = t; pen = false; }
      else if (cmd === 1 || cmd === 2 || cmd === 4) { pen = false; if (cmd === 1) { px = x; py = y; } }
      else if (cmd === 0) {
        if (pen && nSeg < MAX_SEGMENTS && (x !== px || y !== py)) {
          const dx = x - px, dy = y - py, l = Math.hypot(dx, dy), tx = dx / l, ty = dy / l, nx = -ty, ny = tx;
          const z = 0.12 + 0.55 * i / Math.max(1, st.length), c = hex(cols[th] || "#000000"), w = HALF_W;
          const P = [[px + nx * w, py + ny * w, 1], [px - nx * w, py - ny * w, -1], [x + nx * w, y + ny * w, 1], [x - nx * w, y - ny * w, -1]];
          for (const k of [0, 1, 2, 2, 1, 3]) { const p = P[k]; out[o++] = p[0]; out[o++] = p[1]; out[o++] = z; out[o++] = tx; out[o++] = ty; out[o++] = nx; out[o++] = ny; out[o++] = p[2]; out[o++] = c[0]; out[o++] = c[1]; out[o++] = c[2]; }
          nSeg++;
        }
        px = x; py = y; pen = true;
      }
    }
    segEnd[st.length] = o / FLOATS; vcount = o / FLOATS; shown = vcount;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, out.subarray(0, o), gl.STATIC_DRAW);
    const m = 12, fl = new Float32Array([minX - m, minY - m, 0, maxX + m, minY - m, 0, minX - m, maxY + m, 0, minX - m, maxY + m, 0, maxX + m, minY - m, 0, maxX + m, maxY + m, 0]);
    gl.bindBuffer(gl.ARRAY_BUFFER, fbuf); gl.bufferData(gl.ARRAY_BUFFER, fl, gl.STATIC_DRAW);
    reset(); return true;
  }

  function reset() {
    const w = bbox[2] - bbox[0], h = bbox[3] - bbox[1];
    cam.tx = (bbox[0] + bbox[2]) / 2; cam.ty = (bbox[1] + bbox[3]) / 2; cam.tz = 0; cam.yaw = 0; cam.pitch = 62 * Math.PI / 180;
    cam.dist = Math.max(60, Math.max(w, h) * 1.45 / Math.tan(0.35)); schedule();
  }
  function setProgress(n) { if (!gl) return; shown = segEnd[Math.max(0, Math.min(n, segEnd.length - 1))] || 0; schedule(); }
  function setFabric(h) { fabricRGB = hex(h); schedule(); }
  function resize() {
    if (!cv) return; const r = cv.getBoundingClientRect(), d = Math.min(devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(r.width * d)), h = Math.max(1, Math.round(r.height * d));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; } schedule();
  }
  function schedule() { if (rafPending || !gl) return; rafPending = true; requestAnimationFrame(() => { rafPending = false; draw(); }); }

  function draw() {
    if (!gl) return;
    gl.viewport(0, 0, cv.width, cv.height); gl.clearColor(0.09, 0.1, 0.12, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT); gl.enable(gl.DEPTH_TEST);
    const eye = [cam.tx + cam.dist * Math.sin(cam.yaw) * Math.cos(cam.pitch), cam.ty - cam.dist * Math.cos(cam.yaw) * Math.cos(cam.pitch), cam.tz + cam.dist * Math.sin(cam.pitch)];
    const vp = mat4mul(perspective(0.7, cv.width / cv.height, 2, 4000), lookAt(eye, [cam.tx, cam.ty, cam.tz], [0, 0, 1]));
    // fabric
    gl.useProgram(fabric); gl.bindBuffer(gl.ARRAY_BUFFER, fbuf);
    let a = gl.getAttribLocation(fabric, "aPos"); gl.enableVertexAttribArray(a); gl.vertexAttribPointer(a, 3, gl.FLOAT, false, 12, 0);
    gl.uniformMatrix4fv(gl.getUniformLocation(fabric, "uVP"), false, vp); gl.uniform3fv(gl.getUniformLocation(fabric, "uBase"), fabricRGB); gl.drawArrays(gl.TRIANGLES, 0, 6);
    gl.disableVertexAttribArray(a);
    // thread
    if (shown > 0) {
      gl.useProgram(thread); gl.bindBuffer(gl.ARRAY_BUFFER, buf); const S = FLOATS * 4;
      const attr = (n, sz, off) => { const l = gl.getAttribLocation(thread, n); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, sz, gl.FLOAT, false, S, off * 4); return l; };
      const ls = [attr("aPos", 3, 0), attr("aTan", 2, 3), attr("aNrm", 2, 5), attr("aV", 1, 7), attr("aCol", 3, 8)];
      gl.uniformMatrix4fv(gl.getUniformLocation(thread, "uVP"), false, vp); gl.uniform3fv(gl.getUniformLocation(thread, "uEye"), eye); gl.uniform3fv(gl.getUniformLocation(thread, "uLight"), [-0.45, -0.55, 0.85]);
      gl.drawArrays(gl.TRIANGLES, 0, shown); ls.forEach(l => gl.disableVertexAttribArray(l));
    }
  }
  function stats() { return {supported: !!gl, stitches: nStitches, triangles: vcount / 3, drawnTriangles: shown / 3, bbox, yaw: cam.yaw, pitch: cam.pitch, dist: cam.dist}; }
  function sample(fx, fy) {   // read one pixel (fractions of the canvas) for tests; drawn synchronously first
    if (!gl) return null; draw(); const px = new Uint8Array(4); gl.readPixels(Math.round(fx * (cv.width - 1)), Math.round((1 - fy) * (cv.height - 1)), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); return Array.from(px);
  }
  function orbit(dyaw, dpitch) { cam.yaw += dyaw; cam.pitch = Math.max(0.12, Math.min(Math.PI / 2, cam.pitch + dpitch)); schedule(); }
  return {supported, init, setData, setProgress, setFabric, resize, reset, stats, sample, orbit, draw};
})();
