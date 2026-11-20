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
# Switchable motif features. Measured on the pink-silk photos (decoded DST vs photo, PINK3): thin-line tracing lowered gold IoU .54 -> .48, fern / small-flower rebuilds lowered red IoU .61 -> .59,
# so those three are OFF by default (opt in per request); petals, serrated teeth, uniform sizes and leaf area matching are ON.
FEATURES = {"thin": False, "petals": True, "ferns": False, "small": False, "uniform": True, "teeth": True}


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
        yy = np.where(np.abs(yy - med) > 3.0, med, yy); sm = np.convolve(np.pad(yy, 10, mode="edge"), np.ones(21) / 21, mode="valid"); sm = np.convolve(np.pad(sm, 5, mode="edge"), np.ones(11) / 11, mode="valid")
        sg = sg[6:-6]; sm = sm[6:-6]
        if len(sg) < 40: continue
        lines.append([(q[0], float(y)) for q, y in zip(sg, sm)][::6])
        for q in sg: band[max(0, int(q[1] - t / 2 - 4)):int(q[1] + t / 2 + 4), q[0]] = True
    if sum(len(l) for l in lines) * 6 < 0.35 * W: return [], 0.0, None
    return lines, t, band


def uniform_sizes(rs):
    """Make the gold flowers uniform: split them into a large and a small size class at the biggest gap in radius (when the classes differ by > 35 %) and give every flower the
    class median radius (and median open-centre radius). Centres are kept; a flower is only changed within +-30 % so a really different one stays different."""
    if len(rs) < 3: return rs
    R = sorted(r[2] for r in rs); gaps = [(R[i + 1] / R[i], i) for i in range(len(R) - 1)]; g, i = max(gaps)
    classes = [[r for r in rs if r[2] <= R[i]], [r for r in rs if r[2] > R[i]]] if g > 1.35 else [list(rs)]
    out = []
    for c in classes:
        med = sorted(r[2] for r in c)[len(c) // 2]; mi = sorted(r[3] for r in c)[len(c) // 2]
        for (cx, cy, Re, ri) in c:
            if abs(Re - med) <= 0.3 * med: Re, ri = med, min(max(mi, 1.5), med - 1.2)
            out.append((cx, cy, Re, ri))
    return out


def thin_lines(mask, s, np=None, Image=None, IF=None, min_mm=6.0):
    """Thin line-like parts of a thread mask (scalloped neckline borders, thin stems to the stones) -> ([(polyline px, width mm)], mask of what they cover).
    Thin = what an opening with a ~2.4 mm kernel removes; each thin component is thinned to its medial axis and every branch of at least `min_mm` is kept."""
    np, Image, IF = _np()
    from .smart_design import _thin, _branches
    k = int(round(2.4 / s)) | 1
    op = _filt(_filt(mask, "ero", k, np, Image, IF), "dil", k, np, Image, IF)
    thin = _clean(mask & ~_filt(op, "dil", 5, np, Image, IF), 3, 40, np, Image, IF)
    out, cover = [], np.zeros_like(mask); H, W = mask.shape
    for ys, xs in _comps(thin, 40, np):
        y0, y1, x0, x1 = max(0, ys.min() - 2), min(H, ys.max() + 3), max(0, xs.min() - 2), min(W, xs.max() + 3)
        sub = np.zeros((y1 - y0, x1 - x0), bool); sub[ys - y0, xs - x0] = True
        sk = _thin(sub, np); brs = _branches(sk, np); skpx = max(int(sk.sum()), 1); width = min(max(float(sub.sum()) / skpx * s, 1.2), 2.2)
        for path, _k in brs:
            if len(path) * s < min_mm: continue
            pts = np.array([(x + x0, y + y0) for y, x in path], float); kk = 9; ker = np.ones(kk) / kk
            sm = np.stack([np.convolve(np.pad(pts[:, i], kk // 2, mode="edge"), ker, mode="valid") for i in range(2)], 1); sm[0] = pts[0]; sm[-1] = pts[-1]
            step = max(1, int(round(0.8 / s))); idx = list(range(0, len(sm), step))
            if idx[-1] != len(sm) - 1: idx.append(len(sm) - 1)
            out.append(([(float(sm[i][0]), float(sm[i][1])) for i in idx], width)); cover[ys, xs] = True
    return out, cover


def prepare(data: bytes, width_mm: float, threads=None, border: bool = True, max_px: int = 700) -> dict:
    """Separate threads and build the layer picture for the vector digitizer. Returns everything `finish` needs."""
    np, Image, IF = _np()
    threads = threads or DEFAULT_THREADS
    if not 5 <= width_mm <= 1000: raise ValueError("width_mm must be between 5 and 1000")
    masks, (W, H) = classify(data, threads, max_px); s = width_mm / W
    emb = np.zeros((H, W), bool)
    for m in masks.values(): emb |= m
    if emb.sum() < 400: raise ValueError("no thread colour was found (check the picture, or set the thread hue windows)")
    ros, lines, thin, covered = [], [], [], np.zeros_like(emb); t_px = 0.0
    for t in threads:
        if not t.get("rosette"): continue
        m = masks[t["id"]]
        if border:
            ln, tpx, band = border_line(m)
            if ln:
                lines = [(t["id"], l) for l in ln]; t_px = tpx; m = m & ~band
                m[int(0.80 * H):, :int(0.035 * W)] = False; m[int(0.80 * H):, int(0.965 * W):] = False; masks[t["id"]] = m
        rs, cover = rosettes(m, s); rs = uniform_sizes(rs) if FEATURES["uniform"] else rs; ros += [(t["id"],) + r for r in rs]; covered |= cover
        if border and FEATURES["thin"]:
            try:
                tl, tcov = thin_lines(m & ~_filt(cover, "dil", 5, np, Image, IF), s)
            except (ImportError, MemoryError):
                tl, tcov = [], None
            if tl:
                thin += [(t["id"], pl, w) for pl, w in tl]; m = m & ~_filt(tcov, "dil", 5, np, Image, IF); masks[t["id"]] = m
    layer = np.full((H, W, 3), 255, np.uint8)
    for t in threads:
        c = tuple(int(t["hex"][i:i + 2], 16) for i in (1, 3, 5)); m = masks[t["id"]]
        if t.get("rosette"): m = m & ~_filt(covered, "dil", 5, np, Image, IF)
        layer[m] = c
    present = (layer != 255).any(2); yy, xx = np.nonzero(present)
    if len(yy) < 50: raise ValueError("nothing left to digitize after separation")
    buf = io.BytesIO(); Image.fromarray(layer).save(buf, "PNG")
    return {"layer_png": buf.getvalue(), "scale": s, "centre_mm": ((xx.min() + xx.max()) / 2 * s, (yy.min() + yy.max()) / 2 * s), "rosettes": ros, "border_lines": lines, "thin_lines": thin,
            "border_thickness_mm": t_px * s, "size_px": (W, H), "threads": threads,
            "counts": {"thread_pixels": {k: int(v.sum()) for k, v in masks.items()}, "rosettes": len(ros), "border_lines": len(lines), "thin_lines": len(thin)}}


def _area(r): return abs(sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))) / 2


def _diag(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def _pca(pts):
    import numpy as np
    a = np.array(pts); c = a.mean(0); u, s, vt = np.linalg.svd(a - c, full_matrices=False)
    return math.degrees(math.atan2(vt[0][1], vt[0][0])) % 180, float(s[0] / max(s[1], 1e-6))


def _circle(cx, cy, r, n=72): return [[round(cx + r * math.cos(2 * math.pi * i / n), 3), round(cy + r * math.sin(2 * math.pi * i / n), 3)] for i in range(n + 1)]


def _lens(cx, cy, ang_deg, L, W, n=14, teeth=0):
    """Pointed leaf / petal as two satin rails from tip to tip: half-width follows sin(pi t)^0.8, stitches run across the leaf.
    teeth > 0 gives a serrated edge: `teeth` saw teeth per side, each rising slowly and dropping sharply towards the tip."""
    a = math.radians(ang_deg); ux, uy = math.cos(a), math.sin(a); nx, ny = -uy, ux; r1, r2 = [], []
    if teeth: n = max(n, teeth * 4)
    for i in range(n + 1):
        t = i / n; h = (W / 2) * (math.sin(math.pi * t) ** 0.8); c = (t - 0.5) * L
        if teeth: ph = (t * teeth) % 1.0; h *= 1.0 - 0.20 * ph * math.sin(math.pi * t) ** 0.5 + 0.02
        r1.append([round(cx + ux * c + nx * h, 3), round(cy + uy * c + ny * h, 3)]); r2.append([round(cx + ux * c - nx * h, 3), round(cy + uy * c - ny * h, 3)])
    return r1, r2


def _extent(pts, ang_deg):
    a = math.radians(ang_deg); ux, uy = math.cos(a), math.sin(a); u = [p[0] * ux + p[1] * uy for p in pts]; v = [-p[0] * uy + p[1] * ux for p in pts]
    return min(u), max(u), min(v), max(v)


def _centroid(r):
    return sum(p[0] for p in r) / len(r), sum(p[1] for p in r) / len(r)


def _poly(o):
    if o.get("type") == "column" and o.get("rail1") and o.get("rail2"): return [tuple(p) for p in o["rail1"]] + [tuple(p) for p in o["rail2"]][::-1]
    if o.get("type") == "fill" and o.get("rings"): return [tuple(p) for p in o["rings"][0]]
    return None


def _avoid_overlap(objs, tries=4, factor=0.9):
    """Leaves (ids leaf*) that overlap another thread area (leaf, petal, rosette, fill) are scaled down about their centre until the overlap is gone (<= `tries` times).
    Shapes are shrunk, never dropped. Returns how many leaves were changed."""
    from .geometry import point_in_polygon
    polys = {id(o): _poly(o) for o in objs}; boxes = {}
    for o in objs:
        pl = polys[id(o)]
        if pl: xs = [p[0] for p in pl]; ys = [p[1] for p in pl]; boxes[id(o)] = (min(xs), min(ys), max(xs), max(ys))
    changed = 0; leaves = [o for o in objs if str(o.get("id", "")).startswith("leaf") and polys[id(o)]]; seen_leaf = set()
    for lf in leaves:
        for _ in range(tries):
            pl = polys[id(lf)]; b = boxes[id(lf)]; mid = [((a[0] + c[0]) / 2, (a[1] + c[1]) / 2) for a, c in zip(lf["rail1"], lf["rail2"])][1:-1]
            hit = False
            for o in objs:
                if o is lf or id(o) not in boxes or (str(o.get("id", "")).startswith("leaf") and id(o) not in seen_leaf): continue
                ob = boxes[id(o)]
                if ob[2] < b[0] or ob[0] > b[2] or ob[3] < b[1] or ob[1] > b[3]: continue
                if any(point_in_polygon(q, [polys[id(o)]]) for q in mid) or any(point_in_polygon(q, [pl]) for q in polys[id(o)][::2]): hit = True; break
            if not hit: break
            cx = sum(p[0] for p in pl) / len(pl); cy = sum(p[1] for p in pl) / len(pl)
            for k in ("rail1", "rail2"): lf[k] = [[round(cx + (x - cx) * factor, 3), round(cy + (y - cy) * factor, 3)] for x, y in lf[k]]
            polys[id(lf)] = _poly(lf); xs = [p[0] for p in polys[id(lf)]]; ys = [p[1] for p in polys[id(lf)]]; boxes[id(lf)] = (min(xs), min(ys), max(xs), max(ys))
            if _ == 0: changed += 1
        seen_leaf.add(id(lf))
    return changed


def motifs(design: dict, plan: dict, ox: float, oy: float) -> dict:
    """Replace detected red leaf blobs by pointed satin leaves along their axis and rebuild the six-petal flower inside every large gold ring. Mutates design['objects']."""
    s = plan["scale"]; red_hex = next((t["hex"] for t in plan["threads"] if not t.get("rosette")), None); stats = {"leaves": 0, "flowers": 0, "small_flowers": 0, "ferns": 0, "stones": []}
    if red_hex is None: return stats
    objs = design["objects"]; out = []
    rings = [(px * s + ox, py * s + oy, ri) for (_t, px, py, Re, ri) in plan["rosettes"] if ri >= 2.6]
    dead = set()
    for k, (cx, cy, ri) in enumerate(rings, 1):                                    # six-petal flower in the ring hole, stone seat left open in the middle
        R = ri * 0.88; rho0 = max(0.9, ri * 0.22); L = R - rho0; W = max(1.6, L * 0.62)
        for o in objs:
            if o["type"] == "fill" and o.get("color") == red_hex and o.get("rings") and math.hypot(*[a - b for a, b in zip(_centroid(o["rings"][0]), (cx, cy))]) < ri * 0.95: dead.add(o["id"])
        for j in range(6):
            ang = j * 60 + 30; mid = rho0 + L / 2
            r1, r2 = _lens(cx + math.cos(math.radians(ang)) * mid, cy + math.sin(math.radians(ang)) * mid, ang, L, W)
            out.append({"id": f"fl{k}p{j + 1}", "type": "column", "color": red_hex, "name": f"flower {k} petal {j + 1}", "rail1": r1, "rail2": r2, "params": {"spacing": 0.4, "underlay": "none", "pull_comp": 0.12}})
        stats["flowers"] += 1
    kept = []; n = 0; nf = 0; nfern = 0
    for o in objs:
        if o["id"] in dead: continue
        if o["type"] == "fill" and o.get("color") == red_hex and o.get("rings") and len(o["rings"]) == 1:
            r = o["rings"][0]; A = _area(r); ang, ratio = _pca(r)
            ccx, ccy = _centroid(r); rmax = max(math.hypot(p[0] - ccx, p[1] - ccy) for p in r)
            if FEATURES["small"] and ratio < 1.35 and 2.2 <= rmax <= 7.0 and A / (math.pi * rmax ** 2) >= 0.5:         # small standalone red flower (stone in the middle): six satin petals
                nf += 1; R = rmax * 1.02; rho0 = max(0.8, R * 0.22); Lp = R - rho0; Wp = max(1.5, Lp * 0.66)
                for j in range(6):
                    a2 = j * 60 + 30; mid = rho0 + Lp / 2
                    r1, r2 = _lens(ccx + math.cos(math.radians(a2)) * mid, ccy + math.sin(math.radians(a2)) * mid, a2, Lp, Wp)
                    out.append({"id": f"sf{nf}p{j + 1}", "type": "column", "color": red_hex, "name": f"small flower {nf} petal {j + 1}", "rail1": r1, "rail2": r2, "params": {"spacing": 0.4, "underlay": "none", "pull_comp": 0.12}})
                stats["stones"].append((ccx, ccy)); continue
            if FEATURES["ferns"] and A >= 14 and ratio >= 1.6:
                u0, u1, v0, v1 = _extent(r, ang); L, W = u1 - u0, v1 - v0
                if (L > 14.5 or W > 7.5) and 12.0 <= L <= 45.0 and W >= 4.0:                       # fern sprig: stem along the axis, leaflet pairs pointing to the tip
                    a = math.radians(ang); ux, uy = math.cos(a), math.sin(a); nx, ny = -uy, ux
                    def wid(lo, hi):
                        vs = [(-p[0] * uy + p[1] * ux) for p in r if lo <= (p[0] * ux + p[1] * uy) <= hi]; return (max(vs) - min(vs)) if vs else 0
                    sgn = 1 if wid(u0, u0 + L * 0.3) >= wid(u1 - L * 0.3, u1) else -1             # +1: base at u0, tip at u1
                    base = u0 if sgn > 0 else u1; vc = (v0 + v1) / 2
                    def at(u, v): return (u * ux - v * uy, u * uy + v * ux)
                    stem = [list(map(lambda q: round(q, 3), at(base + sgn * L * t, vc))) for t in (0.0, 0.25, 0.5, 0.75, 0.97)]
                    nfern += 1
                    out.append({"id": f"fern{nfern}s", "type": "satin", "color": red_hex, "name": f"fern {nfern} stem", "points": stem, "params": {"width": 1.0, "spacing": 0.4, "underlay": "none", "pull_comp": 0.1}})
                    nl = max(3, int(L / 2.8))
                    for q in range(nl):
                        t = 0.10 + 0.82 * q / max(nl - 1, 1); ll = max(2.2, (W / 2) * (1.05 - 0.55 * t)); u = base + sgn * L * t
                        for side in (1, -1):
                            ra = math.radians(ang + (0 if sgn > 0 else 180) + side * 52)
                            px0, py0 = at(u, vc); cxl, cyl = px0 + math.cos(ra) * ll / 2, py0 + math.sin(ra) * ll / 2
                            r1, r2 = _lens(cxl, cyl, math.degrees(ra), ll, 1.7)
                            out.append({"id": f"fern{nfern}l{q}{'a' if side > 0 else 'b'}", "type": "column", "color": red_hex, "name": f"fern {nfern} leaflet", "rail1": r1, "rail2": r2, "params": {"spacing": 0.4, "underlay": "none", "pull_comp": 0.1}})
                    continue
            if A >= 5 and ratio >= 1.3:
                u0, u1, v0, v1 = _extent(r, ang); L, W = u1 - u0, v1 - v0
                if 5.0 <= L <= 14.5 and 2.0 <= W <= 7.5 and 0.6 <= A / (0.64 * L * W) <= 1.35:
                    a = math.radians(ang); uc, vc = (u0 + u1) / 2, (v0 + v1) / 2
                    cx = uc * math.cos(a) - vc * math.sin(a); cy = uc * math.sin(a) + vc * math.cos(a)
                    tt = (3 if L >= 8 else 2) if FEATURES["teeth"] else 0; r1, r2 = _lens(cx, cy, ang, L, W, teeth=tt); n += 1
                    for _ in range(2):                                                          # match the stitched area to the photo's area (width only; clamp 0.85 - 1.25)
                        al = _area(r1 + r2[::-1]); f = min(1.25, max(0.85, A / max(al, 1e-6)))
                        if abs(f - 1) < 0.03: break
                        W *= f; r1, r2 = _lens(cx, cy, ang, L, W, teeth=tt)
                    out.append({"id": f"leaf{n}", "type": "column", "color": red_hex, "name": f"leaf {n}", "rail1": r1, "rail2": r2, "params": {"spacing": 0.42, "underlay": "auto", "pull_comp": 0.12}}); continue
        kept.append(o)
    stats["shrunk"] = _avoid_overlap(out + kept)
    stats["leaves"] = n; stats["small_flowers"] = nf; stats["ferns"] = nfern; design["objects"] = kept + out; return stats


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
    for j, (tid, pl, w) in enumerate(plan.get("thin_lines", [])):
        design["objects"].append({"id": f"thin{j}", "type": "satin", "color": hexes[tid], "name": f"{'border' if len(pl) * 0.8 > 25 else 'stem'} line {j + 1}", "points": [[round(px * s + ox, 3), round(py * s + oy, 3)] for px, py in pl],
                                  "params": {"width": round(w, 2), "spacing": 0.42, "underlay": "center", "pull_comp": 0.15}})
    stones = []
    for k, (tid, px, py, Re, r_in) in enumerate(plan["rosettes"], 1):
        cx, cy = round(px * s + ox, 3), round(py * s + oy, 3)
        np_ = (8 if Re < 4.5 else (10 if Re < 6.5 else 12)) if FEATURES["petals"] else 0                         # individual petals: one radial satin column per petal, scalloped outer edge
        for j in range(np_):
            t0 = 2 * math.pi * j / np_; t1 = 2 * math.pi * (j + 1) / np_ - math.radians(3.0); m = 7
            r1 = [[round(cx + r_in * math.cos(t0 + (t1 - t0) * i / m), 3), round(cy + r_in * math.sin(t0 + (t1 - t0) * i / m), 3)] for i in range(m + 1)]
            r2 = []
            for i in range(m + 1):
                f = i / m; rr = Re * (0.90 + 0.10 * math.sin(math.pi * f) ** 0.6); ang = t0 + (t1 - t0) * f
                r2.append([round(cx + rr * math.cos(ang), 3), round(cy + rr * math.sin(ang), 3)])
            design["objects"].append({"id": f"ros{k}p{j + 1}", "type": "column", "color": hexes[tid], "name": f"rosette {k} petal {j + 1}", "rail1": r1, "rail2": r2,
                                      "params": {"spacing": 0.42, "underlay": "auto", "pull_comp": 0.2}})
        if not np_:
            design["objects"].append({"id": f"ros{k}", "type": "column", "color": hexes[tid], "name": f"rosette {k}", "rail1": _circle(cx, cy, r_in), "rail2": _circle(cx, cy, Re), "params": {"spacing": 0.42, "underlay": "auto", "pull_comp": 0.2}})
        stones.append((cx, cy))
    mo = motifs(design, plan, ox, oy)
    sp = stones + [(round(x, 3), round(y, 3)) for x, y in mo["stones"]]
    if sp:
        design["objects"].append({"id": "stones", "type": "embellishment", "kind": "stone", "color": "#e8e8f0", "size_mm": 4.0, "name": f"stones - place by hand ({len(sp)})", "points": [[round(x, 3), round(y, 3)] for x, y in sp]})
    order = {t["hex"]: i for i, t in enumerate(plan["threads"])}
    design["objects"].sort(key=lambda o: order.get(o.get("color"), 99))                 # exactly one colour block per thread (stable: red first, gold on top)
    src = dict(design.get("source") or {}); src["thread_separation"] = dict(plan["counts"], strays_removed=removed, leaf_fills_angled=angled, leaf_motifs=mo["leaves"], flower_motifs=mo["flowers"], leaves_shrunk=mo.get("shrunk", 0), small_flowers=mo["small_flowers"], ferns=mo["ferns"], stone_places=len(sp), thin_lines=len(plan.get("thin_lines", []))); design["source"] = src
    return design
