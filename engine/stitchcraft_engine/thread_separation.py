"""Thread-colour separation digitizing for photos of embroidered garments (rosettes, leaves, scalloped borders).

Pipeline (docs/embroidery/photo-digitizing-engine.md, "Thread separation"):
  1. classify pixels into thread classes by HUE windows and a saturation floor (default: red thread and gold thread; hue separates them from pink / cream silk even
     when the thread is pale) - a heuristic, tuned on pink silk, NOT a general colour segmentation;
  2. gold-like classes flagged `rosette` are split into ROUND blobs (flowers, rings: area / circle through the farthest point >= 0.70, radius 2.2-9 mm) and everything else;
     round blobs become RADIAL SATIN columns (inner radius = real hole, or 1.6 mm stone seat) - the rest goes to the normal vector digitizer;
  3. optional `border`: a long near-horizontal thread line in the lower part of the picture is fitted as ONE smooth satin line (low-envelope of the line, outlier-rejected);
  4. finish(): stray objects removed (< 3 mm2 fills, short runs / tack stitches < 5 mm), leaf fills angled across their long axis, lighter density, underlay on larger shapes,
     trim distance 6 mm.
Stones / beads are NOT stitched. Needs Pillow + NumPy.
"""
from __future__ import annotations
import io
import math
from typing import Dict, List, Optional

DEFAULT_THREADS = [
    {"id": "red", "hex": "#cc142d", "hue": [348, 14], "sat_min": 0.66, "val_min": 0.35, "min_px": 90, "rosette": False},
    {"id": "gold", "hex": "#c49a3a", "hue": [26, 62], "sat_min": 0.17, "val_min": 0.38, "min_px": 140, "rosette": True},
]
UP = 2


def _np():
    import numpy as np
    from PIL import Image, ImageFilter
    return np, Image, ImageFilter


def _comps(m, minpx, np):
    """4-connected components with >= minpx pixels -> [(ys, xs)] (numpy arrays). Run-length labelling with union-find: work is proportional to the number of runs, not pixels."""
    H, W = m.shape; parent = []; runs = []                      # runs: (y, x0, x1, id)
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    prev = []
    for y in range(H):
        row = m[y]
        if not row.any():
            prev = []; continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0]))); st = np.nonzero(d == 1)[0]; en = np.nonzero(d == -1)[0]
        cur = []; pi = 0
        for a, b in zip(st.tolist(), en.tolist()):
            rid = len(parent); parent.append(rid); runs.append((y, a, b)); cur.append((a, b, rid))
            while pi < len(prev) and prev[pi][1] <= a: pi += 1
            k = pi
            while k < len(prev) and prev[k][0] < b:
                ra, rb = find(prev[k][2]), find(rid)
                if ra != rb: parent[max(ra, rb)] = min(ra, rb)
                k += 1
        prev = cur
    groups = {}
    for rid, (y, a, b) in enumerate(runs): groups.setdefault(find(rid), []).append((y, a, b))
    out = []
    for g in groups.values():
        if sum(b - a for _, a, b in g) < minpx: continue
        ys = np.concatenate([np.full(b - a, y) for y, a, b in g]); xs = np.concatenate([np.arange(a, b) for _, a, b in g]); out.append((ys, xs))
    return out


def _filt(m, kind, k, np, Image, IF):
    f = IF.MaxFilter(k) if kind == "dil" else IF.MinFilter(k)
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(f)) > 127


def _clean(m, k, minpx, np, Image, IF):
    m2 = _filt(_filt(m, "ero", k, np, Image, IF), "dil", k, np, Image, IF); keep = np.zeros_like(m2)
    for ys, xs in _comps(m2, minpx, np):
        keep[ys, xs] = True
    return keep


def _fill_holes(m, np):
    H, W = m.shape; bg = ~m; seen = np.zeros_like(m)
    pts = [(0, x) for x in range(W)] + [(H - 1, x) for x in range(W)] + [(y, 0) for y in range(H)] + [(y, W - 1) for y in range(H)]
    st = [p for p in pts if bg[p]]
    for p in st: seen[p] = True
    while st:
        y, x = st.pop()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < H and 0 <= nx < W and bg[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True; st.append((ny, nx))
    return m | (bg & ~seen)


def classify(data: bytes, threads=None, max_px: int = 700):
    """-> (masks {id: bool array}, size (W, H) of the working grid, scale_up)."""
    np, Image, IF = _np()
    threads = threads or DEFAULT_THREADS
    im = Image.open(io.BytesIO(data)); im.load()
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA"); flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255)); flat.alpha_composite(rgba); im = flat
    im = im.convert("RGB"); sc = min(1.0, max_px / max(im.size))
    if sc < 1: im = im.resize((max(8, round(im.width * sc)), max(8, round(im.height * sc))), Image.LANCZOS)
    im = im.resize((im.width * UP, im.height * UP), Image.LANCZOS).filter(IF.GaussianBlur(0.8))
    a = np.asarray(im).astype(float) / 255; mx = a.max(2); mn = a.min(2); d = mx - mn + 1e-9; sat = d / (mx + 1e-9); r, g, b = a[..., 0], a[..., 1], a[..., 2]
    hue = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    masks: Dict[str, object] = {}
    for t in threads:
        lo, hi = t["hue"]; inh = ((hue >= lo) | (hue <= hi)) if lo > hi else ((hue >= lo) & (hue <= hi))
        m = inh & (sat > t["sat_min"]) & (mx > t["val_min"])
        masks[t["id"]] = _clean(m, 3, int(t["min_px"]), np, Image, IF)
    ids = [t["id"] for t in threads]
    for i, k in enumerate(ids):                                      # earlier classes win overlaps
        for j in ids[:i]: masks[k] = masks[k] & ~masks[j]
    return masks, (im.width, im.height)


def _blobs(mask, s, use_close, np, Image, IF):
    import math as _m
    closed = (_filt(_filt(mask, "dil", 13, np, Image, IF), "ero", 13, np, Image, IF) | mask) if use_close else mask   # closing: petal gaps / stone holes no longer break a textured flower
    core = _clean(closed, 3, 60, np, Image, IF); core = _filt(_filt(core, "ero", 15, np, Image, IF), "dil", 15, np, Image, IF)
    out = []; cover = np.zeros_like(mask); H, W = mask.shape
    for ys, xs in _comps(core, 700, np):
        y0, y1, x0, x1 = max(0, ys.min() - 14), min(H, ys.max() + 15), max(0, xs.min() - 14), min(W, xs.max() + 15)       # work on the blob's own window (speed)
        sub = mask[y0:y1, x0:x1]; csub = closed[y0:y1, x0:x1]; m = np.zeros_like(sub); m[ys - y0, xs - x0] = True
        full = csub & _filt(m, "dil", 5, np, Image, IF); filled = _fill_holes(full, np)
        A = int(filled.sum()); hole = int((filled & ~sub).sum()) if not use_close else int((filled & ~csub).sum()); Re = _m.sqrt(A / _m.pi) * s
        if not (2.2 < Re < 9.0): continue
        yy, xx = np.nonzero(filled); rr = np.hypot(xx - xx.mean(), yy - yy.mean()) * s
        if A / (_m.pi * (rr.max() / s) ** 2) < (0.58 if use_close else 0.70): continue
        r_in = _m.sqrt(hole / _m.pi) * s if hole > 0.05 * A else 1.6
        r_in = min(max(r_in, 1.5), Re - 1.2)
        out.append((float(xx.mean() + x0), float(yy.mean() + y0), Re, r_in)); cover[y0:y1, x0:x1] |= filled
    return out, cover


def rosettes(mask, scale_mm_per_px: float, np=None, Image=None, IF=None):
    """Round blobs of a thread mask -> ([(cx_px, cy_px, outer_r_mm, inner_r_mm)], mask of what they cover). Two passes: the plain mask, then the gap-closed mask
    (textured flowers with stone holes); a blob from the second pass is kept only if it does not overlap one from the first."""
    np, Image, IF = _np(); s = scale_mm_per_px
    a, ca = _blobs(mask, s, False, np, Image, IF); b, cb = _blobs(mask, s, True, np, Image, IF)
    out = list(a); cover = ca.copy()
    for (cx, cy, Re, ri) in b:
        if all(math.hypot(cx - ax, cy - ay) * s > 0.7 * max(Re, aRe) for ax, ay, aRe, _ in a): out.append((cx, cy, Re, ri))
    for (cx, cy, Re, ri) in out[len(a):]:
        yy, xx = np.ogrid[:mask.shape[0], :mask.shape[1]]; cover |= (xx - cx) ** 2 + (yy - cy) ** 2 <= (Re / s) ** 2
    return out, cover


def border_line(mask, np=None):
    """Fit ONE smooth line to a long near-horizontal thread line in the lower 30 % of the picture. -> (list of polylines in px, thickness px, band mask) or ([], 0, None)."""
    np, Image, IF = _np()
    H, W = mask.shape; y0 = int(0.70 * H); cols = {}; runs = []
    for x in range(W):
        col = np.nonzero(mask[y0:, x])[0]
        if len(col) == 0: continue
        ym = col.max() + y0; k = 0
        while ym - k >= 0 and mask[ym - k, x]: k += 1
        cols[x] = (ym, k); runs.append(k)
    if len(cols) < 0.3 * W: return [], 0.0, None
    t = min(max(float(np.percentile(runs, 40)), 8.0), 20.0)
    ally = [v[0] for v in cols.values() if v[0] >= 0.80 * H]
    if not ally: return [], 0.0, None
    gm = float(np.median(ally))
    xs = [x for x in sorted(cols) if abs(cols[x][0] - gm) < 2.0 * t and 0.03 * W < x < 0.97 * W and cols[x][0] >= 0.80 * H]
    segs, cur = [], []
    for x in xs:
        if cur and x - cur[-1][0] > 10: segs.append(cur); cur = []
        cur.append((x, cols[x][0] - t / 2))
    if cur: segs.append(cur)
    lines = []; band = np.zeros_like(mask)
    for sg in segs:
        if len(sg) < 60: continue
        yy = np.array([q[1] for q in sg]); med = np.array([np.median(yy[max(0, i - 7):i + 8]) for i in range(len(yy))])
        yy = np.where(np.abs(yy - med) > 3.0, med, yy); sm = np.convolve(np.pad(yy, 4, mode="edge"), np.ones(9) / 9, mode="valid")
        sg = sg[6:-6]; sm = sm[6:-6]
        if len(sg) < 40: continue
        lines.append([(q[0], float(y)) for q, y in zip(sg, sm)][::6])
        for q in sg: band[max(0, int(q[1] - t / 2 - 4)):int(q[1] + t / 2 + 4), q[0]] = True
    if sum(len(l) for l in lines) * 6 < 0.35 * W: return [], 0.0, None
    return lines, t, band


def prepare(data: bytes, width_mm: float, threads=None, border: bool = True, max_px: int = 700) -> dict:
    """Separate threads and build the layer picture for the vector digitizer. Returns everything `finish` needs."""
    np, Image, IF = _np()
    threads = threads or DEFAULT_THREADS
    if not 5 <= width_mm <= 1000: raise ValueError("width_mm must be between 5 and 1000")
    masks, (W, H) = classify(data, threads, max_px); s = width_mm / W
    emb = np.zeros((H, W), bool)
    for m in masks.values(): emb |= m
    if emb.sum() < 400: raise ValueError("no thread colour was found (check the picture, or set the thread hue windows)")
    ros, lines, covered = [], [], np.zeros_like(emb); t_px = 0.0
    for t in threads:
        if not t.get("rosette"): continue
        m = masks[t["id"]]
        if border:
            ln, tpx, band = border_line(m)
            if ln:
                lines = [(t["id"], l) for l in ln]; t_px = tpx; m = m & ~band
                m[int(0.80 * H):, :int(0.035 * W)] = False; m[int(0.80 * H):, int(0.965 * W):] = False; masks[t["id"]] = m
        rs, cover = rosettes(m, s); ros += [(t["id"],) + r for r in rs]; covered |= cover
    layer = np.full((H, W, 3), 255, np.uint8)
    for t in threads:
        c = tuple(int(t["hex"][i:i + 2], 16) for i in (1, 3, 5)); m = masks[t["id"]]
        if t.get("rosette"): m = m & ~_filt(covered, "dil", 5, np, Image, IF)
        layer[m] = c
    present = (layer != 255).any(2); yy, xx = np.nonzero(present)
    if len(yy) < 50: raise ValueError("nothing left to digitize after separation")
    buf = io.BytesIO(); Image.fromarray(layer).save(buf, "PNG")
    return {"layer_png": buf.getvalue(), "scale": s, "centre_mm": ((xx.min() + xx.max()) / 2 * s, (yy.min() + yy.max()) / 2 * s), "rosettes": ros, "border_lines": lines,
            "border_thickness_mm": t_px * s, "size_px": (W, H), "threads": threads,
            "counts": {"thread_pixels": {k: int(v.sum()) for k, v in masks.items()}, "rosettes": len(ros), "border_lines": len(lines)}}


def _area(r): return abs(sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))) / 2


def _diag(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def _pca(pts):
    import numpy as np
    a = np.array(pts); c = a.mean(0); u, s, vt = np.linalg.svd(a - c, full_matrices=False)
    return math.degrees(math.atan2(vt[0][1], vt[0][0])) % 180, float(s[0] / max(s[1], 1e-6))


def _circle(cx, cy, r, n=72): return [[round(cx + r * math.cos(2 * math.pi * i / n), 3), round(cy + r * math.sin(2 * math.pi * i / n), 3)] for i in range(n + 1)]


def finish(design: dict, plan: dict) -> dict:
    """Add rosette columns and the border line, remove strays, angle leaf fills. Mutates + returns `design`; adds design['source']['thread_separation'] (counts)."""
    s = plan["scale"]; hexes = {t["id"]: t["hex"] for t in plan["threads"]}
    xs, ys = [], []
    for o in design["objects"]:
        for rg in (o.get("rings") or [o.get("points") or []]):
            for p in rg: xs.append(p[0]); ys.append(p[1])
    cx0, cy0 = plan["centre_mm"]; ox = (min(xs) + max(xs)) / 2 - cx0; oy = (min(ys) + max(ys)) / 2 - cy0
    kept, removed = [], 0
    for o in design["objects"]:
        if o["type"] == "fill" and o.get("rings") and _area(o["rings"][0]) < 3.0: removed += 1; continue
        if o["type"] in ("run", "manual") and _diag(o.get("points") or [[0, 0], [0, 0]]) < 5.0: removed += 1; continue
        kept.append(o)
    design["objects"] = kept; angled = 0
    for o in kept:
        if o["type"] == "fill" and o.get("rings"):
            o["params"].update({"spacing": 0.46, "pull_comp": 0.12, "cut_hidden": True, "overlap_mm": 0.4})
            if _area(o["rings"][0]) > 14: o["params"]["underlay"] = "tatami"
            ang, ratio = _pca(o["rings"][0])
            if ratio > 1.5: o["params"]["angle"] = round((ang + 68) % 180, 1); angled += 1
    mach = dict(design.get("machine") or {}); mach["trim_distance"] = 6.0; design["machine"] = mach
    for j, (tid, line) in enumerate(plan["border_lines"]):
        design["objects"].append({"id": f"scal{j}", "type": "satin", "color": hexes[tid], "name": f"scalloped border {j + 1}", "points": [[round(px * s + ox, 3), round(py * s + oy, 3)] for px, py in line],
                                  "params": {"width": 1.8, "spacing": 0.42, "underlay": "center", "pull_comp": 0.2}})
    for k, (tid, px, py, Re, r_in) in enumerate(plan["rosettes"], 1):
        cx, cy = round(px * s + ox, 3), round(py * s + oy, 3)
        design["objects"].append({"id": f"ros{k}", "type": "column", "color": hexes[tid], "name": f"rosette {k}", "rail1": _circle(cx, cy, r_in), "rail2": _circle(cx, cy, Re),
                                  "params": {"spacing": 0.42, "underlay": "auto", "pull_comp": 0.2}})
    src = dict(design.get("source") or {}); src["thread_separation"] = dict(plan["counts"], strays_removed=removed, leaf_fills_angled=angled); design["source"] = src
    return design
