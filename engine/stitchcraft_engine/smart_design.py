"""Smart-design helpers for the vector digitizer: shape recognition and stitch-type presets.

Shape recognition (opt-in, `shapes=True`): a traced outline that is, within tolerance, an ellipse / circle or a rectangle is replaced by the ideal shape fitted to it
(clean edges, far fewer points, consistent stitch angles). Everything else is left exactly as traced. Documented limits: only these primitives (ellipse / circle, rectangle / square, rounded rectangle); text is not
recognised; a shape that is merely close (a rounded rectangle, a polygon) stays as traced.

Presets (`preset=`): they only choose WHERE the stitch-type boundaries are (running line / satin column / fill); density, underlay and pull compensation still come from
the fabric profile. Boundaries are in mm of the estimated stroke width (2 x area / perimeter):
  auto        thin < 1.0 -> run, 1.0-5.5 elongated (aspect >= 2.5) -> column, else fill     (the existing behaviour)
  logo_satin  thin < 0.9 -> run, up to 9 mm elongated (aspect >= 1.8) -> column; stroke-like shapes (letters, swooshes, rings, 1-9 mm strokes) get SATIN ALONG THEIR STROKES
              (medial axis -> columns whose width follows the stroke), kept only when the columns cover >= 94 % of the shape and spill <= 14 %; otherwise a fill
  line_art    thin < 2.0 -> run, up to 4 mm -> column                                        drawings made of lines
  fine_detail thin < 0.7 -> run, up to 4 mm -> column, aspect >= 3                           small text / detail kept as lines and narrow columns
  fill_all    no runs / columns: every shape is a fill                                       flat, bold shapes
No Wilcom code or data is used; the preset names and values are this project's own engineering defaults, not Wilcom's.
"""
from __future__ import annotations
import math
from typing import Dict, List, Optional, Tuple

PRESETS: Dict[str, dict] = {
    "auto": {"label": "Auto (default)", "thin_mm": 1.0, "column_max_mm": 5.5, "min_aspect": 2.5},
    "logo_satin": {"label": "Logo - satin along strokes", "thin_mm": 0.9, "column_max_mm": 9.0, "min_aspect": 1.8, "stroke_satin": True},
    "line_art": {"label": "Line art", "thin_mm": 2.0, "column_max_mm": 4.0, "min_aspect": 2.5},
    "fine_detail": {"label": "Fine detail / small text", "thin_mm": 0.7, "column_max_mm": 4.0, "min_aspect": 3.0},
    "fill_all": {"label": "Fills only", "thin_mm": 0.0, "column_max_mm": 0.0, "min_aspect": 99.0},
}


def preset_cfg(name: str) -> dict:
    if name not in PRESETS:
        raise ValueError(f"preset must be one of {sorted(PRESETS)}")
    p = PRESETS[name]
    return {"thin_mm": p["thin_mm"], "column_max_mm": p["column_max_mm"], "min_aspect": p["min_aspect"], "stroke_satin": bool(p.get("stroke_satin"))}


def _area(r):
    return abs(sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))) / 2


def recognize_ring(ring) -> Optional[Tuple[List[List[float]], dict]]:
    """-> (ideal ring, {"kind", ...}) when the closed outline is an ellipse / circle or a rectangle, else None."""
    n = len(ring)
    if n < 8:
        return None
    A = _area(ring)
    if A < 1.0:
        return None
    cx = sum(p[0] for p in ring) / n; cy = sum(p[1] for p in ring) / n
    # area-weighted centroid is better for unevenly sampled outlines
    sx = sy = 0.0
    for i in range(n):
        x0, y0 = ring[i]; x1, y1 = ring[(i + 1) % n]; c = x0 * y1 - x1 * y0; sx += (x0 + x1) * c; sy += (y0 + y1) * c
    signed = sum(ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1] for i in range(n)) / 2
    if abs(signed) > 1e-9:
        cx, cy = sx / (6 * signed), sy / (6 * signed)
    # resample the outline uniformly by arc length (covariance of vertices is biased by vertex density)
    per = sum(math.hypot(ring[(i + 1) % n][0] - ring[i][0], ring[(i + 1) % n][1] - ring[i][1]) for i in range(n))
    m = 180; pts = []; seg = 0; acc = 0.0
    lens = [math.hypot(ring[(i + 1) % n][0] - ring[i][0], ring[(i + 1) % n][1] - ring[i][1]) for i in range(n)]
    for k in range(m):
        target = per * k / m
        while acc + lens[seg] < target and seg < n - 1:
            acc += lens[seg]; seg += 1
        t = (target - acc) / max(lens[seg], 1e-12); a = ring[seg]; b = ring[(seg + 1) % n]
        pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    mx = sum(p[0] for p in pts) / m; my = sum(p[1] for p in pts) / m
    # second moments of the FILLED polygon (Green's theorem): for a filled ellipse var along an axis = (semi-axis)^2 / 4
    Ixx = Iyy = Ixy = 0.0
    for i in range(n):
        x0, y0 = ring[i][0] - cx, ring[i][1] - cy; x1, y1 = ring[(i + 1) % n][0] - cx, ring[(i + 1) % n][1] - cy; c = x0 * y1 - x1 * y0
        Ixx += c * (x0 * x0 + x0 * x1 + x1 * x1); Iyy += c * (y0 * y0 + y0 * y1 + y1 * y1); Ixy += c * (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0)
    sgn = 1.0 if signed >= 0 else -1.0
    sxx, syy, sxy = sgn * Ixx / (12 * A), sgn * Iyy / (12 * A), sgn * Ixy / (24 * A)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy); ca, sa = math.cos(ang), math.sin(ang)
    l1 = sxx * ca * ca + 2 * sxy * ca * sa + syy * sa * sa; l2 = sxx * sa * sa - 2 * sxy * ca * sa + syy * ca * ca
    a_ax, b_ax = 2 * math.sqrt(max(l1, 1e-12)), 2 * math.sqrt(max(l2, 1e-12))
    devs = []
    for p in pts:
        u = (p[0] - cx) * ca + (p[1] - cy) * sa; v = -(p[0] - cx) * sa + (p[1] - cy) * ca
        devs.append(abs(math.sqrt((u / a_ax) ** 2 + (v / b_ax) ** 2) - 1.0))
    if sum(devs) / m <= 0.035 and max(devs) <= 0.08 and 0.93 <= A / (math.pi * a_ax * b_ax) <= 1.07 and min(a_ax, b_ax) >= 0.5:
        circ = abs(a_ax / b_ax - 1) < 0.07
        N = max(24, min(180, int(2 * math.pi * math.sqrt((a_ax ** 2 + b_ax ** 2) / 2) / 0.6)))
        if circ:
            r = math.sqrt(a_ax * b_ax); ring2 = [[cx + r * math.cos(2 * math.pi * i / N), cy + r * math.sin(2 * math.pi * i / N)] for i in range(N)]
            return ring2, {"kind": "circle", "cx": round(cx, 3), "cy": round(cy, 3), "r": round(r, 3)}
        ring2 = []
        for i in range(N):
            t = 2 * math.pi * i / N; u, v = a_ax * math.cos(t), b_ax * math.sin(t); ring2.append([cx + u * ca - v * sa, cy + u * sa + v * ca])
        return ring2, {"kind": "ellipse", "cx": round(cx, 3), "cy": round(cy, 3), "a": round(a_ax, 3), "b": round(b_ax, 3), "angle_deg": round(math.degrees(ang) % 180, 1)}
    # ---- rectangle: minimum-area rotated bounding box
    best = None
    for deg in range(0, 90):
        t = math.radians(deg); c, s = math.cos(t), math.sin(t)
        us = [p[0] * c + p[1] * s for p in pts]; vs = [-p[0] * s + p[1] * c for p in pts]
        w, h = max(us) - min(us), max(vs) - min(vs)
        if best is None or w * h < best[0]: best = (w * h, deg, min(us), max(us), min(vs), max(vs))
    area_box, deg, u0, u1, v0, v1 = best
    if area_box > 0 and A / area_box >= 0.975 and min(u1 - u0, v1 - v0) >= 1.0:
        # every sampled point must lie near the box boundary (rules out diamonds / filled-corner shapes)
        t = math.radians(deg); c, s = math.cos(t), math.sin(t); tol = 0.04 * min(u1 - u0, v1 - v0) + 0.1
        ok = all(min(abs(p[0] * c + p[1] * s - u0), abs(p[0] * c + p[1] * s - u1), abs(-p[0] * s + p[1] * c - v0), abs(-p[0] * s + p[1] * c - v1)) <= tol for p in pts)
        if ok:
            corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            ring2 = [[u * c - v * s, u * s + v * c] for u, v in corners]
            kind = "square" if abs((u1 - u0) / (v1 - v0) - 1) < 0.03 else "rectangle"
            return ring2, {"kind": kind, "w": round(u1 - u0, 3), "h": round(v1 - v0, 3), "angle_deg": float(deg)}
    # ---- rounded rectangle: box fill ratio 0.90-0.975, corner radius from the area deficit, every point within tolerance of the modelled boundary
    if area_box > 0 and 0.88 <= A / area_box < 0.998 and min(u1 - u0, v1 - v0) >= 2.0:
        t = math.radians(deg); c, s = math.cos(t), math.sin(t); w, h = u1 - u0, v1 - v0
        r = math.sqrt(max(area_box - A, 0.0) / (4 - math.pi))
        if 0.3 <= r <= min(w, h) / 2 * 1.0:
            def dist_model(px, py):                       # |signed distance| of a point to the rounded-rectangle outline (box centred at the origin)
                qx, qy = abs(px) - (w / 2 - r), abs(py) - (h / 2 - r)
                return abs(math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r)
            cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
            tol = 0.04 * min(w, h) + 0.1
            if all(dist_model((p[0] * c + p[1] * s) - cu, (-p[0] * s + p[1] * c) - cv) <= tol for p in pts):
                ring2 = []; N = 12
                for (ccx, ccy, a0) in ((w / 2 - r, h / 2 - r, 0), (-(w / 2 - r), h / 2 - r, 90), (-(w / 2 - r), -(h / 2 - r), 180), (w / 2 - r, -(h / 2 - r), 270)):
                    for k in range(N + 1):
                        a = math.radians(a0 + 90 * k / N); ring2.append((ccx + r * math.cos(a), ccy + r * math.sin(a)))
                ring2 = [[(x + cu) * c - (y + cv) * s, (x + cu) * s + (y + cv) * c] for x, y in ring2]
                return ring2, {"kind": "rounded_rectangle", "w": round(w, 3), "h": round(h, 3), "radius": round(r, 3), "angle_deg": float(deg)}
    return None


def recognize_shape(outer, holes):
    """-> (outer, holes, info) with recognised rings replaced; info = {"outer": {...}|None, "holes": [..]}."""
    o = recognize_ring(outer); new_o = o[0] if o else outer
    new_h = []; hinfo = []
    for h in holes:
        r = recognize_ring(h); new_h.append(r[0] if r else h); hinfo.append(r[1] if r else None)
    return new_o, new_h, {"outer": o[1] if o else None, "holes": hinfo}


# ---------------------------------------------------------------------------------------------------------------- stroke satin (letters, logos, swooshes)
def _raster(outer, holes, res):
    import numpy as np
    from PIL import Image, ImageDraw
    xs = [p[0] for p in outer]; ys = [p[1] for p in outer]; x0, y0 = min(xs) - 2 * res, min(ys) - 2 * res
    W = int((max(xs) - x0) / res) + 3; H = int((max(ys) - y0) / res) + 3
    im = Image.new("L", (W, H), 0); d = ImageDraw.Draw(im)
    d.polygon([((x - x0) / res, (y - y0) / res) for x, y in outer], fill=255)
    for h in holes: d.polygon([((x - x0) / res, (y - y0) / res) for x, y in h], fill=0)
    return np.asarray(im) > 127, x0, y0


def _chamfer(mask, np):
    """Distance (in pixels) to the nearest background pixel - 3-4 chamfer, two passes."""
    H, W = mask.shape; INF = 10 ** 6; d = np.where(mask, INF, 0).astype(np.int64)
    for y in range(H):
        row = d[y]; up = d[y - 1] if y else None
        for x in range(W):
            if row[x] == 0: continue
            v = row[x]
            if x: v = min(v, row[x - 1] + 3)
            if up is not None:
                v = min(v, up[x] + 3)
                if x: v = min(v, up[x - 1] + 4)
                if x + 1 < W: v = min(v, up[x + 1] + 4)
            row[x] = v
    for y in range(H - 1, -1, -1):
        row = d[y]; dn = d[y + 1] if y + 1 < H else None
        for x in range(W - 1, -1, -1):
            if row[x] == 0: continue
            v = row[x]
            if x + 1 < W: v = min(v, row[x + 1] + 3)
            if dn is not None:
                v = min(v, dn[x] + 3)
                if x + 1 < W: v = min(v, dn[x + 1] + 4)
                if x: v = min(v, dn[x - 1] + 4)
            row[x] = v
    return d / 3.0


def _thin(mask, np):
    """Zhang-Suen thinning (vectorised)."""
    m = mask.copy(); H, W = m.shape
    def nb(a):
        p = np.pad(a, 1)
        return (p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:], p[2:, 2:], p[2:, 1:-1], p[2:, :-2], p[1:-1, :-2], p[:-2, :-2])        # P2..P9 (N, NE, E, SE, S, SW, W, NW)
    changed = True; it = 0
    while changed and it < 200:
        changed = False; it += 1
        for step in (0, 1):
            P2, P3, P4, P5, P6, P7, P8, P9 = nb(m); B = sum(x.astype(np.int8) for x in (P2, P3, P4, P5, P6, P7, P8, P9))
            seq = [P2, P3, P4, P5, P6, P7, P8, P9, P2]; A = sum(((~seq[i]) & seq[i + 1]).astype(np.int8) for i in range(8))
            c1 = (P2 & P4 & P6) if step == 0 else (P2 & P4 & P8); c2 = (P4 & P6 & P8) if step == 0 else (P2 & P6 & P8)
            kill = m & (B >= 2) & (B <= 6) & (A == 1) & ~c1 & ~c2
            if kill.any(): m = m & ~kill; changed = True
    return m


def _branches(sk, np):
    """Skeleton pixels -> list of (path [(y, x)], end_kinds) between nodes (deg != 2)."""
    H, W = sk.shape; ys, xs = np.nonzero(sk); S = set(zip(ys.tolist(), xs.tolist()))
    def nbs(p):
        out = [(p[0] + dy, p[1] + dx) for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)) if (p[0] + dy, p[1] + dx) in S]
        for dy, dx in ((-1, -1), (-1, 1), (1, -1), (1, 1)):                       # a diagonal neighbour counts only when it is not already reached through an orthogonal one (staircase corners)
            if (p[0] + dy, p[1] + dx) in S and (p[0] + dy, p[1]) not in S and (p[0], p[1] + dx) not in S: out.append((p[0] + dy, p[1] + dx))
        return out
    deg = {p: len(nbs(p)) for p in S}; nodes = {p for p, k in deg.items() if k != 2}
    used = set(); out = []
    starts = sorted(nodes) or ([next(iter(S))] if S else [])
    for n0 in starts:
        for first in nbs(n0):
            if (n0, first) in used: continue
            path = [n0, first]; used.add((n0, first)); used.add((first, n0)); prev, cur = n0, first
            while cur not in nodes:
                nxt = [q for q in nbs(cur) if q != prev and (cur, q) not in used]
                if not nxt: break
                q = nxt[0]; used.add((cur, q)); used.add((q, cur)); path.append(q); prev, cur = cur, q
            out.append((path, (deg[n0], deg.get(cur, 1))))
    return out


def stroke_columns(outer, holes, max_width_mm, res_mm=0.1, min_cov=0.94, max_spill=0.14):
    """Satin along the strokes of a letter / logo shape: the medial axis (thinning of the filled region) is split into branches; each long-enough branch becomes a satin
    column whose width follows the local stroke width (distance transform). Returns a list of {"rail1", "rail2"} (mm) or None when the shape is not stroke-like or the
    columns would not cover it (>= min_cov of the area, <= max_spill outside it) - the caller then keeps the fill."""
    try:
        import numpy as np
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    xs = [p[0] for p in outer]; ys = [p[1] for p in outer]; ext = max(max(xs) - min(xs), max(ys) - min(ys))
    res = max(res_mm, ext / 520.0)
    mask, x0, y0 = _raster(outer, holes, res)
    if mask.sum() < 40: return None
    dtpx = _chamfer(mask, np); maxw = 2 * float(dtpx.max()) * res
    if maxw > 1.4 * max_width_mm or maxw < 1.0: return None                           # not a stroke: fat blob or hairline
    sk = _thin(mask, np); br = _branches(sk, np)
    cols = []
    for path, (d0, d1) in br:
        pts = np.array([(x, y) for y, x in path], dtype=float)
        if len(pts) < 3: continue
        w = np.array([dtpx[y, x] for y, x in path]); length = len(pts) * res                       # w = half-width in pixels
        if length < max(1.2, 1.0 * float(w.mean()) * res): continue                          # spur / junction connector
        k = min(7, len(pts) | 1); ker = np.ones(k) / k
        sm = np.stack([np.convolve(np.pad(pts[:, i], k // 2, mode="edge"), ker, mode="valid") for i in range(2)], 1); sm[0] = pts[0]; sm[-1] = pts[-1]
        wsm = np.convolve(np.pad(w, k // 2, mode="edge"), ker, mode="valid")
        step = max(1, int(round(0.7 / res))); idx = list(range(0, len(sm), step));
        if idx[-1] != len(sm) - 1: idx.append(len(sm) - 1)
        P = sm[idx]; Wd = wsm[idx]
        tang = np.gradient(P, axis=0); nrm = np.stack([-tang[:, 1], tang[:, 0]], 1); nl = np.linalg.norm(nrm, axis=1, keepdims=True); nrm = nrm / np.maximum(nl, 1e-9)
        # extend the ends: free tips by the local half-width (the skeleton stops one half-width short of the outline), junction ends by half of it
        def ext_pt(p, tvec, hw, f): return p + tvec / max(np.linalg.norm(tvec), 1e-9) * hw * f
        a = ext_pt(P[0], P[0] - P[1], Wd[0], 1.05 if d0 == 1 else 0.5); b = ext_pt(P[-1], P[-1] - P[-2], Wd[-1], 1.05 if d1 == 1 else 0.5)
        P = np.vstack([a, P, b]); Wd = np.concatenate([[Wd[0]], Wd, [Wd[-1]]]); nrm = np.vstack([nrm[0], nrm, nrm[-1]])
        hw = np.maximum(Wd * 1.04, 1e-6)
        r1 = P + nrm * hw[:, None]; r2 = P - nrm * hw[:, None]
        if (np.linalg.norm(r1 - r2, axis=1).max() * res) < 0.9: continue            # thinner than a satin can be
        cols.append({"rail1": [[round(x0 + x * res, 3), round(y0 + y * res, 3)] for x, y in r1], "rail2": [[round(x0 + x * res, 3), round(y0 + y * res, 3)] for x, y in r2]})
    if not cols: return None
    # coverage / spill check against the region
    H, Wm = mask.shape; im = Image.new("L", (Wm, H), 0); dr = ImageDraw.Draw(im)
    for c in cols:
        poly = [((x - x0) / res, (y - y0) / res) for x, y in c["rail1"]] + [((x - x0) / res, (y - y0) / res) for x, y in reversed(c["rail2"])]
        dr.polygon(poly, fill=255)
    cov = np.asarray(im) > 127; inter = int((cov & mask).sum()); covered = inter / max(int(mask.sum()), 1); spill = int((cov & ~mask).sum()) / max(int(cov.sum()), 1)
    if covered < min_cov or spill > max_spill: return None
    return cols
