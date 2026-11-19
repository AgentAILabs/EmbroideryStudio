"""Flat-colour raster -> editable fill objects (Phase 4a, optional: needs numpy + Pillow).
Quantise to <= N colours, drop the background, trace pixel-boundary loops per colour, simplify.
Honest limits: works for logos / flat artwork; photos and gradients give poor results and are warned about."""
from __future__ import annotations
import io
from collections import defaultdict
from typing import List, Tuple

MAX_PIXELS = 25_000_000
MAX_COLORS = 8          # requirements A.2: flat artwork, <= 8 colours


class RasterUnavailable(RuntimeError):
    pass


def _dp(pts, eps):
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    n = (dx * dx + dy * dy) ** 0.5 or 1e-9
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x1 * y0 - y1 * x0) / n
        if d > best:
            best, idx = d, i
    if best <= eps:
        return [pts[0], pts[-1]]
    return _dp(pts[:idx + 1], eps)[:-1] + _dp(pts[idx:], eps)


def _loops(mask) -> List[List[Tuple[int, int]]]:
    import numpy as np
    h, w = mask.shape
    m = np.pad(mask, 1)
    nxt = defaultdict(list)
    ys, xs = np.nonzero(m)
    for y, x in zip(ys.tolist(), xs.tolist()):
        X, Y = x - 1, y - 1
        if not m[y - 1, x]: nxt[(X, Y)].append((X + 1, Y))          # top edge, left->right
        if not m[y, x + 1]: nxt[(X + 1, Y)].append((X + 1, Y + 1))  # right edge, down
        if not m[y + 1, x]: nxt[(X + 1, Y + 1)].append((X, Y + 1))  # bottom edge, right->left
        if not m[y, x - 1]: nxt[(X, Y + 1)].append((X, Y))          # left edge, up
    loops = []
    while nxt:
        start = next(iter(nxt))
        cur, loop = start, [start]
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            n = outs.pop()
            if not outs:
                del nxt[cur]
            if n == start:
                break
            loop.append(n)
            cur = n
        if len(loop) >= 4:
            loops.append(loop)
    return loops


def _digitize_legacy(data: bytes, width_mm: float, max_colors: int = 6, min_area_mm2: float = 4.0,
                     simplify_mm: float = 0.25):
    # Pure-Python validation first, so a bad file is always reported as such - even where the optional libraries are absent.
    if not (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"):
        raise ValueError("unsupported image type: only PNG and JPEG are accepted")
    if width_mm <= 0 or width_mm > 1000:
        raise ValueError("width_mm must be between 0 and 1000")
    try:
        import numpy as np
        from PIL import Image
    except ImportError as e:
        raise RasterUnavailable("image import needs the optional Pillow and NumPy packages (SVG import and everything else work without them)") from e
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    im = Image.open(io.BytesIO(data))
    if im.width * im.height > MAX_PIXELS:
        raise ValueError("image has too many pixels")
    notes = []
    dpi = im.width / (width_mm / 25.4)
    if dpi < 100:
        notes.append(f"Low resolution: about {dpi:.0f} DPI at {width_mm:g} mm wide. Edges will be jagged; use a larger image.")
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    im = im.convert("RGB")
    scale_down = 320 / max(im.size)
    if scale_down < 1:
        im = im.resize((max(1, round(im.width * scale_down)), max(1, round(im.height * scale_down))), Image.LANCZOS)
    max_colors = max(2, min(int(max_colors), MAX_COLORS))
    q = im.quantize(colors=max_colors, method=Image.MEDIANCUT, dither=Image.NONE)
    idx = np.asarray(q)
    pal = np.asarray(q.getpalette()[:3 * (idx.max() + 1)]).reshape(-1, 3)
    uniq = len(np.unique(idx))
    if uniq >= max_colors:
        notes.append(f"Image used the full {max_colors}-colour limit; shaded or photographic art digitizes poorly. Use flat-colour artwork.")
    corners = [idx[0, 0], idx[0, -1], idx[-1, 0], idx[-1, -1]]
    bg_i = max(set(int(c) for c in corners), key=[int(c) for c in corners].count)
    mm = width_mm / idx.shape[1]
    objs = []
    for ci in range(len(pal)):
        if ci == bg_i or not (idx == ci).any():
            continue
        rings = []
        for loop in _loops(idx == ci):
            fl = [(float(x), float(y)) for x, y in loop]
            eps, h = max(0.6, simplify_mm / mm), len(fl) // 2
            pts = _dp(fl[:h + 1], eps)[:-1] + _dp(fl[h:] + [fl[0]], eps)[:-1]  # closed loop: split in two
            pts = [(x * mm, y * mm) for x, y in pts]
            if len(pts) >= 3:
                a = abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                            for i in range(len(pts)))) / 2
                if a >= min_area_mm2:
                    rings.append(([[round(x, 3), round(y, 3)] for x, y in pts], a))
        if rings:
            r, g, b = (int(v) for v in pal[ci])
            objs.append({"type": "fill", "color": f"#{r:02x}{g:02x}{b:02x}", "rings": [x[0] for x in rings],
                         "_area": sum(x[1] for x in rings)})
    objs.sort(key=lambda o: -o.pop("_area"))
    for i, o in enumerate(objs):
        o["id"] = f"img{i + 1}"
        o["name"] = f"Region {i + 1}"
    return objs, notes, (idx.shape[1] * mm, idx.shape[0] * mm)



# ====================================================================================================================
#  Quality pipeline (default).  The legacy path above is kept for comparison (quality="legacy").
# ====================================================================================================================
import math, time
from dataclasses import dataclass, field

QUALITY = {
    #            max source px | up-sampling | blur (src px) | outline tolerance mm | min area mm2 | palette merge dE | majority passes
    "draft":    {"max_px": 260, "up": 1, "blur": 0.0, "tol_mm": 0.30, "min_area": 6.0, "merge_de": 28.0, "majority": 0},
    "standard": {"max_px": 420, "up": 3, "blur": 0.8, "tol_mm": 0.12, "min_area": 2.5, "merge_de": 20.0, "majority": 1},
    "high":     {"max_px": 700, "up": 4, "blur": 0.9, "tol_mm": 0.08, "min_area": 1.2, "merge_de": 16.0, "majority": 1, "adaptive": True},
    # maximum: analyse at up to MAX_WORK_PX (no destructive downscale), no majority smoothing (it erases 1-px lines), finest outline tolerance
    "maximum":  {"max_px": 1000, "up": 3, "blur": 0.6, "tol_mm": 0.05, "min_area": 0.25, "merge_de": 14.0, "majority": 0, "adaptive": True},
}
SAFE_MIN_FEATURE_MM = 0.75   # an isolated mark smaller than this cannot be stitched safely (needle + thread ~0.4 mm, stitches >= 0.4 mm): listed as not_stitchable
NOISE_FLOOR_MM = 0.30        # below one thread width a blob is image noise / antialiasing dust: counted (count + area), not listed one by one
NOISE_AREA_MM2 = 0.15        # ... and so is anything with less area than this (a 0.45 mm dot is 0.16 mm2)
MIN_FILL_MM2 = 1.0          # below this a tatami fill cannot form rows (auto-fix removes fills under 1 mm2): smaller shapes get a micro strategy instead
TACK_MAX_EQ_DIAMETER_MM = 2.2   # small blobs up to this equivalent diameter become a tack dot (3-stitch star) instead of a fill
INVENTORY_LIMIT = 2500
MAX_HIRES_PX = 3300          # longest side of the up-sampled mask used for contour tracing (time / memory budget)
TIME_BUDGET_S = 150          # a single import is stopped with a clear message after this long
MAX_WORK_PX = 1600          # memory / time budget for the working image (longest side)
DETAIL_MM_PER_PX = 0.08     # adaptive working resolution aims for <= this many mm per working pixel
THIN_MM = 1.0            # estimated width below this -> running stitch along the middle
COLUMN_MAX_MM = 5.5      # width up to this (and elongated, no holes) -> satin column
MIN_ASPECT = 2.5


def _loops_fast(mask):
    """Boundary loops of a boolean mask as vertex lists (pixel-corner coordinates). Vectorised edge detection; only boundary edges
    are visited in Python."""
    import numpy as np
    m = np.pad(mask, 1)
    c = m[1:-1, 1:-1]
    nxt = {}
    def add(sel, off):
        ys, xs = np.nonzero(sel)
        for x, y in zip(xs.tolist(), ys.tolist()):
            a, b = off(x, y)
            nxt.setdefault(a, []).append(b)
    add(c & ~m[:-2, 1:-1], lambda x, y: ((x, y), (x + 1, y)))                    # top edge, left -> right
    add(c & ~m[1:-1, 2:], lambda x, y: ((x + 1, y), (x + 1, y + 1)))             # right edge, down
    add(c & ~m[2:, 1:-1], lambda x, y: ((x + 1, y + 1), (x, y + 1)))             # bottom edge, right -> left
    add(c & ~m[1:-1, :-2], lambda x, y: ((x, y + 1), (x, y)))                    # left edge, up
    loops = []
    while nxt:
        start = next(iter(nxt)); cur, loop = start, [start]
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            n = outs.pop()
            if not outs:
                del nxt[cur]
            if n == start:
                break
            loop.append(n); cur = n
        if len(loop) >= 4:
            loops.append(loop)
    return loops


def _dp_iter(pts, eps):
    """Iterative Douglas-Peucker (no recursion limit) on an open polyline."""
    n = len(pts)
    if n < 3:
        return list(pts)
    keep = [False] * n; keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i0, i1 = stack.pop()
        (x0, y0), (x1, y1) = pts[i0], pts[i1]
        dx, dy = x1 - x0, y1 - y0; l = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for i in range(i0 + 1, i1):
            d = abs(dy * pts[i][0] - dx * pts[i][1] + x1 * y0 - y1 * x0) / l if l > 1e-12 else math.hypot(pts[i][0] - x0, pts[i][1] - y0)
            if d > best:
                best, idx = d, i
        if best > eps and idx > 0:
            keep[idx] = True; stack += [(i0, idx), (idx, i1)]
    return [p for p, k in zip(pts, keep) if k]


def _simplify_closed(pts, eps):
    n = len(pts)
    if n < 6:
        return pts
    far = max(range(n), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
    a = _dp_iter(pts[:far + 1], eps); b = _dp_iter(pts[far:] + [pts[0]], eps)
    return a[:-1] + b[:-1]


def _area(r):
    return abs(sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))) / 2


def _perim(r):
    return sum(math.dist(r[i], r[(i + 1) % len(r)]) for i in range(len(r)))


def _srgb_to_lab(rgb):
    import numpy as np
    c = rgb.astype(np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def _palette(rgb, max_colors, merge_de, report):
    """Palette by median cut, then merge perceptually identical colours (JPEG/antialiasing variants) and tiny populations."""
    import numpy as np
    from PIL import Image
    H, W, _ = rgb.shape
    q = Image.fromarray(rgb).quantize(colors=min(32, max(max_colors * 3, 12)), method=Image.MEDIANCUT, dither=Image.NONE)
    idx = np.asarray(q).reshape(-1)
    n = int(idx.max()) + 1
    flat = rgb.reshape(-1, 3).astype(np.float64)
    counts = np.bincount(idx, minlength=n).astype(np.float64)
    cent = np.stack([np.bincount(idx, weights=flat[:, k], minlength=n) / np.maximum(counts, 1) for k in range(3)], axis=1)
    live = [i for i in range(n) if counts[i] > 0]
    cent = {i: cent[i] for i in live}; cnt = {i: counts[i] for i in live}
    lab = lambda c: _srgb_to_lab(np.array([c]))[0]
    merged = 0
    def merge(a, b):                                   # merge a into b
        nonlocal merged
        total = cnt[a] + cnt[b]; cent[b] = (cent[a] * cnt[a] + cent[b] * cnt[b]) / total; cnt[b] = total; del cent[a], cnt[a]; merged += 1
    total_px = float(H * W)
    while True:
        keys = list(cent)
        if len(keys) < 2:
            break
        L = {k: lab(cent[k]) for k in keys}
        best = None
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                de = float(np.linalg.norm(L[a] - L[b]))
                if best is None or de < best[0]:
                    best = (de, a, b)
        small = [k for k in keys if cnt[k] / total_px < 0.002]
        if small:                                       # tiny population: fold into its nearest colour
            k = min(small, key=lambda k: cnt[k]); near = min((o for o in keys if o != k), key=lambda o: float(np.linalg.norm(L[k] - L[o]))); merge(k, near); continue
        if best[0] < merge_de or len(keys) > max_colors:
            a, b = (best[1], best[2]) if cnt[best[1]] <= cnt[best[2]] else (best[2], best[1]); merge(a, b); continue
        break
    keys = sorted(cent, key=lambda k: -cnt[k])
    pal = np.array([cent[k] for k in keys])
    labs = _srgb_to_lab(pal)
    px = _srgb_to_lab(rgb.reshape(-1, 3))
    out = np.empty(px.shape[0], dtype=np.int16)
    for s in range(0, px.shape[0], 200000):
        out[s:s + 200000] = np.argmin(((px[s:s + 200000, None, :] - labs[None, :, :]) ** 2).sum(-1), axis=1)
    report["colours_found"] = n; report["colours_merged"] = merged
    return out.reshape(H, W), [tuple(int(round(v)) for v in c) for c in pal]


def _isolated_fraction(labels):
    """Share of pixels whose 8 neighbours all carry a different label: salt-and-pepper noise. Clean artwork (even with 1-px lines) has almost none."""
    import numpy as np
    pad = np.pad(labels, 1, mode="edge"); same = np.zeros(labels.shape, dtype=np.int8)
    for dy in range(3):
        for dx in range(3):
            if dy == 1 and dx == 1:
                continue
            same += (pad[dy:dy + labels.shape[0], dx:dx + labels.shape[1]] == labels)
    return float((same == 0).mean())


def _majority(labels, k, passes):
    import numpy as np
    for _ in range(passes):
        pad = np.pad(labels, 1, mode="edge"); counts = np.zeros(labels.shape + (k,), dtype=np.int16)
        for dy in range(3):
            for dx in range(3):
                win = pad[dy:dy + labels.shape[0], dx:dx + labels.shape[1]]
                for c in range(k):
                    counts[..., c] += (win == c)
        new = counts.argmax(-1).astype(labels.dtype)
        keep = counts[np.arange(labels.shape[0])[:, None], np.arange(labels.shape[1])[None, :], labels] >= counts.max(-1)   # a tie keeps the old label
        labels = np.where(keep, labels, new)
    return labels


def _is_mix(pal, c, k, bg, tol=14.0):
    """True when palette colour `c` is (within `tol` Lab dE) a blend of two other palette colours - mixed either in sRGB or in linear light, the two ways
    resamplers blend edge pixels: an antialiasing blend, not a real ink."""
    import numpy as np
    P = np.array(pal, dtype=float)
    ts = np.linspace(0.1, 0.9, 9)[:, None]
    lin = lambda v: np.where(v / 255.0 > 0.04045, ((v / 255.0 + 0.055) / 1.055) ** 2.4, v / 255.0 / 12.92)
    unlin = lambda v: np.where(v > 0.0031308, 1.055 * np.power(np.maximum(v, 1e-12), 1 / 2.4) - 0.055, 12.92 * v) * 255.0
    target = _srgb_to_lab(P[c][None, None, :])[0, 0]
    others = [i for i in range(k) if i != c]
    for a in range(len(others)):
        for b in range(a + 1, len(others)):
            A, B_ = P[others[a]], P[others[b]]
            for blend in (A + ts * (B_ - A), unlin(lin(A) + ts * (lin(B_) - lin(A)))):
                labs = _srgb_to_lab(np.clip(blend, 0, 255)[None, :, :])[0]
                if float(np.min(np.linalg.norm(labs - target, axis=1))) <= tol:
                    return True
    return False


def _remove_fringe(labels, k, bg, thin_frac=0.75, pal=None):
    """Antialiasing leaves thin slivers of in-between colours along every edge. A label whose pixels mostly disappear under a
    3x3 opening is such a fringe (or noise): hand its pixels to the dominant neighbouring label. Returns (labels, removed)."""
    import numpy as np
    removed = 0
    for c in range(k):
        if c == bg:
            continue
        mask = labels == c
        total = int(mask.sum())
        if total == 0:
            continue
        pad = np.pad(mask, 1)
        eroded = np.ones_like(mask)
        for dy in range(3):
            for dx in range(3):
                eroded &= pad[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
        padE = np.pad(eroded, 1); opened = np.zeros_like(mask)
        for dy in range(3):
            for dx in range(3):
                opened |= padE[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
        if (mask & ~opened).sum() / total <= thin_frac:
            continue
        if pal is not None and not _is_mix(pal, c, k, bg):      # a genuine thin ink (hairline colour) is not a blend of two other colours: keep it
            continue
        pad_l = np.pad(labels, 2, mode="edge"); counts = np.zeros(mask.shape + (k,), dtype=np.int16)
        for dy in range(5):
            for dx in range(5):
                win = pad_l[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
                for o in range(k):
                    if o != c:
                        counts[..., o] += (win == o)
        labels = np.where(mask, counts.argmax(-1).astype(labels.dtype), labels); removed += 1
    return labels, removed


def _contours_mm(mask, up, blur, tol_mm, width_mm):
    """Smooth sub-pixel outlines of a boolean mask in mm: upsample + blur + threshold, trace, simplify."""
    import numpy as np
    from PIL import Image, ImageFilter
    H, W = mask.shape
    im = Image.fromarray((mask * 255).astype(np.uint8))
    if up > 1:
        im = im.resize((W * up, H * up), Image.BICUBIC)
    if blur > 0:
        im = im.filter(ImageFilter.GaussianBlur(radius=max(0.3, blur * up)))          # sigma in hi-res px = blur (source px) x up-sampling
    hi = np.asarray(im) > 127
    if blur > 0:
        # smoothing + thresholding erases structures thinner than the blur (1-2 px lines, tiny dots). Pixels that vanish under a 3x3 opening ARE such thin
        # structures: put them back (up-sampled, un-blurred) so no ink is lost; the outline tolerance below tidies the staircase.
        pad = np.pad(mask, 1); er = np.ones_like(mask)
        for dy in range(3):
            for dx in range(3):
                er &= pad[dy:dy + H, dx:dx + W]
        padE = np.pad(er, 1); op = np.zeros_like(mask)
        for dy in range(3):
            for dx in range(3):
                op |= padE[dy:dy + H, dx:dx + W]
        thin = mask & ~op
        if thin.any():
            thin_hi = np.kron(thin.astype(np.uint8), np.ones((up, up), dtype=np.uint8)) > 0 if up > 1 else thin
            hi = hi | thin_hi
    mm = width_mm / (W * up)
    rings = []
    for loop in _loops_fast(hi):
        pts = _simplify_closed([(float(x), float(y)) for x, y in loop], max(1.1, tol_mm / mm))     # floor > 1 hi-res px, else the thresholded pixel staircase survives
        if len(pts) >= 3:
            rings.append([(x * mm, y * mm) for x, y in pts])
    return rings


def _nest(rings):
    """Group rings into outers with their holes (even-odd depth); returns [(outer, [holes])].
    Areas are computed once and a bounding-box test (numpy) selects the few candidate containers, so thousands of rings stay fast (was O(n^2) area sums:
    244 s for 1,600 tiny rings of a 2,400 px artwork)."""
    import numpy as np
    from .geometry import point_in_ring
    n = len(rings)
    if n == 0:
        return []
    areas = [_area(r) for r in rings]
    bb = np.array([[min(p[0] for p in r), min(p[1] for p in r), max(p[0] for p in r), max(p[1] for p in r)] for r in rings])
    ar = np.array(areas)
    parent = [None] * n
    depth = [0] * n
    contain = []
    for i in range(n):
        cand = np.nonzero((ar > ar[i]) & (bb[:, 0] <= bb[i, 0]) & (bb[:, 1] <= bb[i, 1]) & (bb[:, 2] >= bb[i, 2]) & (bb[:, 3] >= bb[i, 3]))[0]
        contain.append([int(j) for j in cand if j != i and point_in_ring(rings[i][0], rings[int(j)])])
    for i in range(n):
        depth[i] = len(contain[i])
        if contain[i]:
            parent[i] = max(contain[i], key=lambda j: len(contain[j]))
    comps = {i: (rings[i], []) for i in range(n) if depth[i] % 2 == 0}
    for i in range(n):
        if depth[i] % 2 == 1 and parent[i] in comps:
            comps[parent[i]][1].append(rings[i])
    return list(comps.values())


def _major_axis_deg(ring):
    n = len(ring); cx = sum(p[0] for p in ring) / n; cy = sum(p[1] for p in ring) / n
    sxx = sum((p[0] - cx) ** 2 for p in ring); syy = sum((p[1] - cy) ** 2 for p in ring); sxy = sum((p[0] - cx) * (p[1] - cy) for p in ring)
    return math.degrees(0.5 * math.atan2(2 * sxy, sxx - syy)) % 180.0


def _round(r):
    return [[round(x, 3), round(y, 3)] for x, y in r]


def _make_object(outer, holes, color, quality_cfg, report):
    """Pick the right stitch type for one connected shape: thin -> running line, narrow elongated -> satin column, else fill.
    The boundaries come from the stitch-type preset (smart_design.PRESETS; default = THIN_MM / COLUMN_MAX_MM / MIN_ASPECT); with cfg['shapes'] a fill whose outline is an
    ellipse / circle / rectangle is replaced by the ideal shape."""
    from .outline import column_from_outline
    thin_mm = quality_cfg.get("thin_mm", THIN_MM); col_max = quality_cfg.get("column_max_mm", COLUMN_MAX_MM); min_asp = quality_cfg.get("min_aspect", MIN_ASPECT)
    area = _area(outer) - sum(_area(h) for h in holes)
    per = _perim(outer) + sum(_perim(h) for h in holes)
    w = 2 * area / per if per > 0 else 0.0
    if not holes and w < col_max:
        try:
            col = column_from_outline(outer)
        except ValueError:
            col = None
        if col is not None and col["aspect"] >= min_asp:
            if w < thin_mm:
                mid = [[(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] for a, b in zip(col["rail1"], col["rail2"])]
                return {"type": "run", "color": color, "points": _round(mid), "smooth": False, "params": {"stitch_len": 2.0}}, "run"
            if w >= thin_mm:
                return {"type": "column", "color": color, "rail1": col["rail1"], "rail2": col["rail2"], "params": {"pull_comp": 0.2}}, "column"
    if quality_cfg.get("stroke_satin") and thin_mm <= w <= col_max and area >= 2.0:
        from .smart_design import stroke_columns
        cols = stroke_columns(outer, holes, col_max)
        if cols:
            mk = lambda c: {"type": "column", "color": color, "rail1": _round(c["rail1"]), "rail2": _round(c["rail2"]), "params": {"pull_comp": 0.2}}
            first = mk(cols[0]); first["_strokes"] = True; first["_extra"] = [mk(c) for c in cols[1:]]
            report["stroke_satin"] = report.get("stroke_satin", 0) + 1
            return first, "column"
    aspect = 1.0
    shape_name = None
    if quality_cfg.get("shapes"):
        from .smart_design import recognize_shape
        outer, holes, sinfo = recognize_shape(outer, holes)
        if sinfo["outer"]:
            shape_name = sinfo["outer"]["kind"]; cnt = report.setdefault("shapes", {}); cnt[shape_name] = cnt.get(shape_name, 0) + 1
        for hi in sinfo["holes"]:
            if hi:
                cnt = report.setdefault("shapes", {}); cnt["hole_" + hi["kind"]] = cnt.get("hole_" + hi["kind"], 0) + 1
    xs, ys = [p[0] for p in outer], [p[1] for p in outer]
    ang = _major_axis_deg(outer) if (max(xs) - min(xs) > 0 and (max(xs) - min(xs)) / max(1e-9, max(ys) - min(ys)) > 2.0 or max(ys) - min(ys) > 2.0 * (max(xs) - min(xs))) else 45.0
    fo = {"type": "fill", "color": color, "rings": [_round(outer)] + [_round(h) for h in holes], "params": {"angle": round(ang, 1), "pull_comp": 0.2}}
    if shape_name:
        fo["name"] = shape_name.capitalize()
    return fo, "fill"


def _shape_coverage(outer, holes, obj, width_mm=0.45):
    """-> (coverage, residual_components). Coverage = share of the component's area that the generated line / column covers; a thin line with a bead on its
    end (or two lines that touch at a tip) is classed as one line by its average width and would lose part of the shape. The residual (the uncovered part,
    after removing slivers thinner than 0.3 mm) is returned as components so it can be stitched too. Rasterised locally at 10 px/mm; (1.0, []) if unmeasurable."""
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return 1.0, []
    x0, y0, x1, y1 = _bbox_mm(outer); k = 10.0; pad = 1.0
    W, H = int((x1 - x0 + 2 * pad) * k) + 2, int((y1 - y0 + 2 * pad) * k) + 2
    if W * H > 4_000_000:
        return 1.0, []
    P = lambda pts: [((x - x0 + pad) * k, (y - y0 + pad) * k) for x, y in pts]
    poly = Image.new("L", (W, H), 0); d = ImageDraw.Draw(poly); d.polygon(P(outer), fill=255)
    for h in holes:
        d.polygon(P(h), fill=0)
    got = Image.new("L", (W, H), 0); g = ImageDraw.Draw(got)
    if obj["type"] == "run":
        g.line(P(obj["points"]), fill=255, width=max(1, round(width_mm * k)))
    elif obj["type"] == "column":
        g.polygon(P(obj["rail1"] + obj["rail2"][::-1]), fill=255)
    else:
        return 1.0, []
    got = got.filter(ImageFilter.MaxFilter(5))                 # 0.2 mm positional tolerance
    pa = np.asarray(poly) > 0
    area = int(pa.sum())
    if not area:
        return 1.0, []
    res = pa & ~(np.asarray(got) > 0)
    cov = 1.0 - res.sum() / area
    if cov >= 0.995:
        return cov, []
    r = Image.fromarray(res.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))      # drop 1-2 px slivers along the edges
    rm = np.asarray(r) > 0
    rings = []
    for loop in _loops_fast(rm):
        pts = _simplify_closed([(float(px), float(py)) for px, py in loop], 1.0)
        if len(pts) >= 3:
            ring = [(px / k + x0 - pad, py / k + y0 - pad) for px, py in pts]
            if _area(ring) >= NOISE_AREA_MM2:
                rings.append(ring)
    return float(cov), _nest(rings)


def _split_thick_thin(outer, holes, min_width_mm=0.7):
    """A component that joins broad areas with thin lines (e.g. copper lines touching a sprig) cannot be one fill: a tatami fill leaves the narrow strips empty.
    Split it by morphological opening: the part wider than `min_width_mm` stays a region, the rest are thin pieces. -> (thick_components, thin_components) or None
    when the thin part is negligible. Rasterised locally at 10 px/mm; contours smoothed to 0.12 mm."""
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return None
    x0, y0, x1, y1 = _bbox_mm(outer); k = 10.0; pad = 1.0
    W, H = int((x1 - x0 + 2 * pad) * k) + 2, int((y1 - y0 + 2 * pad) * k) + 2
    if W * H > 6_000_000:
        return None
    P = lambda pts: [((x - x0 + pad) * k, (y - y0 + pad) * k) for x, y in pts]
    im = Image.new("L", (W, H), 0); d = ImageDraw.Draw(im); d.polygon(P(outer), fill=255)
    for h in holes:
        d.polygon(P(h), fill=0)
    ks = 2 * int(min_width_mm * k / 2) + 1
    thick = im.filter(ImageFilter.MinFilter(ks)).filter(ImageFilter.MaxFilter(ks))
    tk = np.asarray(thick) > 0; whole = np.asarray(im) > 0
    grown = np.asarray(thick.filter(ImageFilter.MaxFilter(3))) > 0
    thin = whole & ~grown
    thin = np.asarray(Image.fromarray(thin.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))) > 0
    a_thin, a_thick, a_all = thin.sum() / k / k, tk.sum() / k / k, whole.sum() / k / k
    if a_thin < max(1.0, 0.04 * a_all) or a_thick < 1.0:
        return None
    def comps(mask):
        rings = []
        for loop in _loops_fast(mask):
            pts = _simplify_closed([(float(px), float(py)) for px, py in loop], 1.2)
            if len(pts) >= 3:
                ring = [(px / k + x0 - pad, py / k + y0 - pad) for px, py in pts]
                if _area(ring) >= NOISE_AREA_MM2:
                    rings.append(ring)
        return _nest(rings)
    return comps(tk), comps(thin)


def _force_fill(outer, holes, color):
    xs, ys = [p[0] for p in outer], [p[1] for p in outer]
    ang = _major_axis_deg(outer) if (max(xs) - min(xs)) > 2.0 * (max(ys) - min(ys)) or (max(ys) - min(ys)) > 2.0 * (max(xs) - min(xs)) else 45.0
    return {"type": "fill", "color": color, "rings": [_round(outer)] + [_round(h) for h in holes], "params": {"angle": round(ang, 1), "pull_comp": 0.2}}


def _bbox_mm(ring):
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _tack_dot(cx, cy, diameter, color):
    """Smallest valid mark for a tiny blob: three diameters through the centre (a six-point asterisk, one continuous path). With r >= 0.5 mm every stitch
    is >= 0.86 mm, so it never creates the sub-0.4 mm stitches that cause thread breaks. Manual object = every point is a needle penetration."""
    r = max(0.5, min(diameter / 2.0, 1.0)); h = 0.866 * r
    A = [(cx + r, cy), (cx + r / 2, cy + h), (cx - r / 2, cy + h), (cx - r, cy), (cx - r / 2, cy - h), (cx + r / 2, cy - h)]
    pts = [A[0], A[3], A[1], A[4], A[2], A[5]]
    return {"type": "manual", "color": color, "points": _round(pts), "params": {}}


def _classify_small(outer, holes, color, cfg, report):
    """Strategy for a component below the fill threshold. -> (object | None, kind, status, reason, stitchability)."""
    from .outline import column_from_outline
    x0, y0, x1, y1 = _bbox_mm(outer); ext = max(x1 - x0, y1 - y0)
    area = _area(outer) - sum(_area(h) for h in holes)
    eq_d = 2 * math.sqrt(max(area, 0.0) / math.pi)
    if ext < SAFE_MIN_FEATURE_MM:
        return None, "none", "not_stitchable", f"only {ext:.2f} mm across - below the {SAFE_MIN_FEATURE_MM:g} mm safe minimum for a needle penetration; closest alternative: a single tack stitch, left out until you review it", 0.0
    if not holes:
        try:
            col = column_from_outline(outer)
        except ValueError:
            col = None
        if col is not None and col["aspect"] >= MIN_ASPECT:
            mid = [[(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] for a, b in zip(col["rail1"], col["rail2"])]
            w = 2 * area / max(_perim(outer), 1e-9)
            params = {"stitch_len": 1.6, "style": "bean"} if w < 0.35 else {"stitch_len": 1.8}
            return {"type": "run", "color": color, "points": _round(mid), "smooth": False, "params": params}, "run", "micro_representation", \
                f"narrow mark ({w:.2f} mm wide, {ext:.1f} mm long): running line along its centre" + (" with bean stitch" if w < 0.35 else ""), min(1.0, 0.5 + w)
    if eq_d <= TACK_MAX_EQ_DIAMETER_MM:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        return _tack_dot(cx, cy, eq_d, color), "tack", "micro_representation", f"small blob ({eq_d:.2f} mm across): tack dot (6-stitch star) instead of a fill that would need stitches shorter than 0.4 mm", 0.6
    o, kind = _make_object(outer, holes, color, cfg, report)
    return o, kind, "micro_representation", f"small shape ({area:.2f} mm2, below the {cfg['min_area']:g} mm2 fill threshold) stitched as a {kind}", 0.8


def _photographic(rgb):
    import numpy as np
    from PIL import Image
    t = np.asarray(Image.fromarray(rgb).resize((96, 96), Image.BILINEAR)) >> 4
    return len(np.unique(t.reshape(-1, 3), axis=0)) > 400


def digitize_image(data: bytes, width_mm: float, max_colors: int = 6, quality: str = "standard", decisions=None, preset: str = "auto", shapes: bool = False):
    """Image -> editable objects with a quality report. Returns {"objects", "notes", "size_mm", "report", "inventory"}.
    `decisions` = {inventory id: "tack" | "omit"}: the user's review of details that are too small to stitch safely (tack = force a tack dot, omit = accept leaving it out).
    A run that exceeds TIME_BUDGET_S stops with a clear message instead of tying up the server."""
    if not (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"):
        raise ValueError("unsupported image type: only PNG and JPEG are accepted")
    if not 0 < width_mm <= 1000:
        raise ValueError("width_mm must be between 0 and 1000")
    if quality not in QUALITY:
        raise ValueError(f"quality must be one of {sorted(QUALITY)}")
    try:
        import numpy as np
        from PIL import Image, ImageFilter
    except ImportError as e:
        raise RasterUnavailable("image import needs the optional Pillow and NumPy packages (SVG import and everything else work without them)") from e
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    from .smart_design import preset_cfg
    cfg = dict(QUALITY[quality]); cfg.update(preset_cfg(preset)); cfg["shapes"] = bool(shapes); t0 = time.time()
    im = Image.open(io.BytesIO(data))
    if im.width * im.height > MAX_PIXELS:
        raise ValueError("image has too many pixels")
    is_jpeg = data[:3] == b"\xff\xd8\xff"
    src_w, src_h = im.size
    notes, report = [], {"quality": quality, "source_px": [src_w, src_h], "preset": preset, "shapes_recognised": bool(shapes)}
    dpi = src_w / (width_mm / 25.4); report["dpi"] = round(dpi)
    if dpi < 100:
        notes.append(f"Low resolution: about {dpi:.0f} DPI at {width_mm:g} mm wide. Edges will be rougher; use a larger image.")
    alpha_bg = None
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA"); a = np.asarray(rgba)[..., 3]
        if a.min() < 250:
            alpha_bg = a < 128
        flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255)); flat.alpha_composite(rgba); im = flat
    im = im.convert("RGB")
    work_px = cfg["max_px"]
    if cfg.get("adaptive"):                                    # enough resolution for the finest feature the page size can hold, within the budget
        work_px = min(MAX_WORK_PX, max(work_px, math.ceil(width_mm / DETAIL_MM_PER_PX)))
    sc = work_px / max(im.size)
    if sc < 1:
        im = im.resize((max(1, round(im.width * sc)), max(1, round(im.height * sc))), Image.LANCZOS)
        if alpha_bg is not None:
            alpha_bg = np.asarray(Image.fromarray(alpha_bg.astype(np.uint8) * 255).resize(im.size, Image.NEAREST)) > 0
    if is_jpeg:
        im = im.filter(ImageFilter.MedianFilter(3))                      # JPEG block noise
    rgb = np.asarray(im).copy()
    H, W, _ = rgb.shape
    if _photographic(rgb):
        report["photographic"] = True
        notes.append("This looks like a photograph or shaded artwork (many smooth colours). It will be reduced to flat colour regions and will not look like the photo - use flat-colour artwork or a vector (SVG).")
    max_colors = max(2, min(int(max_colors), MAX_COLORS))
    labels, pal = _palette(rgb, max_colors, cfg["merge_de"], report)
    k = len(pal)
    iso = _isolated_fraction(labels); report["noise_isolated_px"] = round(iso, 6)
    if cfg["majority"] and (is_jpeg or iso > 2e-4):            # the 3x3 majority filter erases 1-px lines: only run it when the source is actually noisy
        labels = _majority(labels, k, cfg["majority"])
        report["majority_filter"] = True
    else:
        report["majority_filter"] = False
    # background: transparent pixels, else the label that dominates the image border
    bg = None
    if alpha_bg is not None:
        labels = np.where(alpha_bg, k, labels); k += 1; bg = k - 1; pal = pal + [(255, 255, 255)]
    else:
        border = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
        top = int(np.bincount(border, minlength=k).argmax())
        if (border == top).mean() >= 0.5:
            bg = top
    if cfg["majority"]:
        labels, report["fringe_colours_removed"] = _remove_fringe(labels, k, bg, pal=pal[:k] if len(pal) >= k else None)
    report["background"] = None if bg is None else "#%02x%02x%02x" % pal[bg]
    mm = width_mm / W; height_mm = H * mm
    # smoothing in source pixels: a coarse source (big pixels) needs more of it, a crisp one almost none (corners stay sharp)
    up = cfg["up"] if cfg["up"] == 1 else max(cfg["up"], min(8, math.ceil(mm / 0.09)))         # coarse source: more up-sampling so hi-res px <= ~0.09 mm
    up = max(1, min(up, MAX_HIRES_PX // max(W, H)))                                              # time / memory budget: the up-sampled mask is at most MAX_HIRES_PX on its long side
    blur_px = 0 if not cfg["blur"] else cfg["blur"] * (0.7 + 0.9 * min(1.0, max(0.0, (mm - 0.15) / 0.5)))
    objs, kinds, areas = [], {"fill": 0, "column": 0, "run": 0, "tack": 0}, {}
    inventory, noise = [], {"count": 0, "area_mm2": 0.0}
    fringe = {"count": 0, "area_mm2": 0.0}; residual_pieces = {"count": 0}; split_n = {"count": 0}
    mixes = {ci: _is_mix(pal[:k], ci, k, bg) for ci in range(k) if ci != bg} if k >= 3 else {}
    ink_area = covered_area = 0.0; holes_filled = {"count": 0, "area_mm2": 0.0}
    for ci in range(k):
        if ci == bg or not (labels == ci).any():
            continue
        color = "#%02x%02x%02x" % pal[ci]
        comps = _nest(_contours_mm(labels == ci, up, blur_px, cfg["tol_mm"], width_mm))
        queue = [(o_, h_, None) for o_, h_ in comps]
        while queue:
            outer, holes, is_resid = queue.pop(0)
            if time.time() - t0 > TIME_BUDGET_S:
                raise ValueError(f"this image took longer than {TIME_BUDGET_S} s to analyse; use a smaller width, lower quality, or a simpler image")
            x0, y0, x1, y1 = _bbox_mm(outer); ext = max(x1 - x0, y1 - y0); a_out = _area(outer)
            if is_resid is None: ink_area += a_out
            kept_holes = []
            for h in holes:
                if _area(h) >= cfg["min_area"] / 2: kept_holes.append(h)
                else: holes_filled["count"] += 1; holes_filled["area_mm2"] += _area(h)          # tiny hole filled in: counted, not silent
            holes = kept_holes
            w_est = 2 * a_out / max(_perim(outer), 1e-9)
            if mixes.get(ci) and w_est < 0.5 and a_out < 6.0 and not holes:         # thin sliver in a colour that is a blend of two others: antialiasing fringe, not artwork
                fringe["count"] += 1; fringe["area_mm2"] += a_out; continue
            if ext < NOISE_FLOOR_MM or a_out < NOISE_AREA_MM2:
                noise["count"] += 1; noise["area_mm2"] += a_out; continue
            if a_out >= max(cfg["min_area"], MIN_FILL_MM2):
                o, kind = _make_object(outer, holes, color, cfg, report); status, reason, score = "digitized", f"{kind} ({a_out:.1f} mm2)", 1.0
            else:
                o, kind, status, reason, score = _classify_small(outer, holes, color, cfg, report)
            if o is not None and kind == "fill" and a_out >= 3.0 and is_resid is None:
                sp = _split_thick_thin(outer, holes)
                if sp:
                    queue.extend((ro, rh, "split") for ro, rh in sp[0] + sp[1]); split_n["count"] += 1
                    continue                                      # the parts are recorded individually (they partition this region)
            if o is not None and kind in ("run", "column") and a_out >= 0.6 and is_resid is None and not o.get("_strokes"):
                cov_, resid = _shape_coverage(outer, holes, o)
                if cov_ < 0.95:                                  # a line / column would leave part of the shape unstitched (a bead on a line end, two lines meeting at a tip)
                    if resid and len(resid) <= 12:
                        queue.extend((ro, rh, "resid") for ro, rh in resid); residual_pieces["count"] += len(resid)
                        reason += f"; plus {len(resid)} extra piece(s) for the {100 * (1 - cov_):.0f} % the line does not cover"
                    elif cov_ < 0.88:
                        o, kind = _force_fill(outer, holes, color), "fill"
                        reason = f"fill (a line / column would have covered only {100 * cov_:.0f} % of this shape)"; score = min(score, 0.9)
            rid = f"d{len(inventory) + 1:03d}"
            dec = (decisions or {}).get(rid)
            if status == "not_stitchable" and dec == "tack":
                cx_, cy_ = (x0 + x1) / 2, (y0 + y1) / 2
                o, kind, status, reason, score = _tack_dot(cx_, cy_, max(ext, 1.0), color), "tack", "micro_representation", f"{reason.split(';')[0]}; you chose a tack dot", 0.4
            elif status == "not_stitchable" and dec == "omit":
                status, reason = "omitted_by_user", f"{reason.split(';')[0]}; you accepted leaving it out"
            rec = {"id": rid, "colour": color, "bbox_mm": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)], "size_mm": [round(x1 - x0, 2), round(y1 - y0, 2)],
                   "area_mm2": round(a_out, 2), "strategy": kind, "status": status, "reason": reason, "stitchability": round(score, 2), "object": None}
            if len(inventory) < INVENTORY_LIMIT: inventory.append(rec)
            if o is None:
                continue
            o["_a"] = a_out; o["_c"] = ci; o["_kind"] = kind; o["_inv"] = rec["id"]; o.pop("_strokes", None)
            objs.append(o); kinds[kind] = kinds.get(kind, 0) + 1; areas[ci] = areas.get(ci, 0) + o["_a"]
            for ex_ in o.pop("_extra", []):                                         # the other stroke columns of the same letter / logo shape
                ex_.update({"_a": 0.0, "_c": ci, "_kind": "column", "_inv": rec["id"]}); objs.append(ex_); kinds["column"] = kinds.get("column", 0) + 1
            if is_resid != "resid": covered_area += a_out
    # order: colours by total area (largest first = bottom layer), inside a colour fills -> columns -> runs, nearest-neighbour for fewer jumps
    rank = {c: i for i, c in enumerate(sorted(areas, key=lambda c: -areas[c]))}
    krank = {"fill": 0, "column": 1, "run": 2, "tack": 3}
    def start(o):
        return tuple(o["rings"][0][0]) if o["type"] == "fill" else tuple(o["rail1"][0]) if o["type"] == "column" else tuple(o["points"][0])
    ordered, cur = [], None
    for key in sorted({(rank[o["_c"]], krank[o["_kind"]]) for o in objs}):
        group = [o for o in objs if (rank[o["_c"]], krank[o["_kind"]]) == key]
        while group:
            nxt = group[0] if cur is None else min(group, key=lambda o: math.dist(start(o), cur))
            group.remove(nxt); ordered.append(nxt); cur = start(nxt)
    by_id = {rec["id"]: rec for rec in inventory}
    for i, o in enumerate(ordered):
        inv_id = o.pop("_inv", None)
        o["id"] = f"img{i + 1}"; kind_ = o.pop("_kind"); o["name"] = f"{o['name']} {i + 1}" if o.get("name") else f"{kind_.capitalize()} {i + 1}"; o.pop("_a"); o.pop("_c")
        if inv_id in by_id:
            by_id[inv_id]["object"] = o["id"]
    status_n = {}
    for rec in inventory:
        status_n[rec["status"]] = status_n.get(rec["status"], 0) + 1
    unresolved = [r["id"] for r in inventory if r["status"] in ("not_stitchable", "needs_review")]       # omitted_by_user is a resolved decision
    coverage = {"ink_area_mm2": round(ink_area, 2), "stitched_area_mm2": round(covered_area, 2),
                "stitched_fraction": round(covered_area / ink_area, 4) if ink_area else 1.0,
                "noise_specks": {"count": noise["count"], "area_mm2": round(noise["area_mm2"], 3), "rule": f"under {NOISE_FLOOR_MM:g} mm across or {NOISE_AREA_MM2:g} mm2 in area (below one thread width)"},
                "residual_pieces": residual_pieces["count"], "split_thick_thin": split_n["count"],
                "antialiasing_fringe": {"count": fringe["count"], "area_mm2": round(fringe["area_mm2"], 3), "rule": "thin sliver (< 0.5 mm wide, < 6 mm2) in a colour that is a Lab blend of two other palette colours"},
                "holes_filled": {"count": holes_filled["count"], "area_mm2": round(holes_filled["area_mm2"], 3)}}
    report.update({"colours_used": len({o["color"] for o in ordered}), "palette": ["#%02x%02x%02x" % c for c in pal[:k]],
                   "objects": kinds, "dropped_specks": noise["count"] + status_n.get("not_stitchable", 0), "work_px": [W, H], "ms": round((time.time() - t0) * 1000),
                   "inventory_status": status_n, "unresolved": unresolved, "coverage": coverage})
    if status_n.get("not_stitchable"):
        notes.append(f"{status_n['not_stitchable']} detail(s) are too small to stitch safely (under {SAFE_MIN_FEATURE_MM:g} mm). They are listed in the detail inventory with the reason - review them before export.")
    if status_n.get("micro_representation"):
        notes.append(f"{status_n['micro_representation']} small detail(s) were given the closest valid stitch (tack dot, short running line or small fill) - see the detail inventory.")
    if noise["count"]:
        notes.append(f"{noise['count']} speck(s) smaller than {NOISE_FLOOR_MM:g} mm (image noise / antialiasing dust, {noise['area_mm2']:.2f} mm2 in total) were not stitched.")
    if holes_filled["count"]:
        notes.append(f"{holes_filled['count']} tiny hole(s) were filled in ({holes_filled['area_mm2']:.2f} mm2 in total).")
    if kinds["run"]:
        notes.append(f"{kinds['run']} thin line(s) became running stitch.")
    if not ordered:
        notes.append("Nothing to digitize. For images, use flat-colour artwork on a plain background.")
    return {"objects": ordered, "notes": notes, "size_mm": (width_mm, height_mm), "report": report, "inventory": inventory,
            "_work": {"labels": labels, "pal": pal[:k], "bg": bg, "mm_per_px": mm}}


def digitize_raster(data: bytes, width_mm: float, max_colors: int = 6, min_area_mm2: float = 4.0, simplify_mm: float = 0.25,
                    quality: str = "standard"):
    """Backwards-compatible entry point -> (objects, notes, (width_mm, height_mm)). quality: draft | standard | high | legacy."""
    if quality == "legacy":
        return _digitize_legacy(data, width_mm, max_colors, min_area_mm2, simplify_mm)
    r = digitize_image(data, width_mm, max_colors, quality)
    return r["objects"], r["notes"], r["size_mm"]


# ---------------------------------------------------------------- image enhancer (upscale + clean-up)
def sharpness(im) -> float:
    """Blur metric: variance of the Laplacian on a grey copy normalised to 256 px wide (higher = sharper)."""
    import numpy as np
    from PIL import Image
    g = im.convert("L"); g = g.resize((256, max(1, round(256 * g.height / g.width))), Image.BILINEAR)
    a = np.asarray(g, dtype=float)
    lap = a[1:-1, 1:-1] * 4 - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return float(lap.var())


_ENH = {"blur": 0.6, "amount": 60, "radius": 1.4, "gain": 6.0}     # tuned on tools/image_bench.py (blurred + low-res variants)


def enhance_image(data: bytes, scale: float = 2.0, mode: str = "auto"):
    """Upscale a PNG/JPEG (default 200 %) and clean it up for tracing. Returns (png_bytes, info).
    Honest limits: no method invents detail that is not in the picture. For flat-colour artwork (logos, lettering) this
    gives sharp, noise-free edges at the new size; photos are only resampled and gently sharpened.
    mode: auto (clean-up only if the image is blurry or low-resolution; crisp images are just resampled) | sharpen (always) | resample (plain high-quality resize)."""
    if not (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"):
        raise ValueError("unsupported image type: only PNG and JPEG are accepted")
    if not 1.0 <= scale <= 4.0:
        raise ValueError("scale must be between 1 and 4 (100 % - 400 %)")
    if mode not in ("auto", "sharpen", "resample"):
        raise ValueError("mode must be auto, sharpen or resample")
    try:
        import io
        import numpy as np
        from PIL import Image, ImageFilter
    except ImportError as e:
        raise RasterUnavailable("the image enhancer needs the optional Pillow and NumPy packages") from e
    Image.MAX_IMAGE_PIXELS = 40_000_000
    im = Image.open(io.BytesIO(data)); is_jpeg = data[:3] == b"\xff\xd8\xff"
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA"); bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    w, h = im.size
    if w * h * scale * scale > 36_000_000:
        raise ValueError("result would exceed 36 megapixels; use a smaller scale or a smaller image")
    s0 = sharpness(im)
    arr = np.asarray(im.resize((96, max(1, round(96 * h / w))))); photo = len({(int(p[0]) >> 4, int(p[1]) >> 4, int(p[2]) >> 4) for p in arr.reshape(-1, 3)}) > 400
    lowres = max(w, h) < 500
    soft = s0 < 60.0 or lowres                     # blurry, or too few pixels to hold crisp edges
    info = {"source_px": [w, h], "sharpness_before": round(s0, 1), "jpeg": is_jpeg, "photographic": photo, "soft": soft, "low_resolution": lowres}
    clean = mode == "sharpen" or (mode == "auto" and soft and not photo)
    nw, nh = round(w * scale), round(h * scale)
    out = im.resize((nw, nh), Image.LANCZOS)
    steps = ["Lanczos resample %.0f%%" % (scale * 100)]
    if clean and not photo:
        # light smoothing, mild unsharp mask, levels stretch, then a sigmoid tone curve that steepens soft edges (flat art only)
        out = out.filter(ImageFilter.GaussianBlur(_ENH["blur"] * scale / 2))
        amount = _ENH["amount"]
        out = out.filter(ImageFilter.UnsharpMask(radius=_ENH["radius"] * scale, percent=amount, threshold=2))
        a = np.asarray(out).astype(float); lo, hi = np.percentile(a, 0.5), np.percentile(a, 99.5)
        if hi - lo > 40:
            a = np.clip((a - lo) / (hi - lo), 0, 1)
            if _ENH["gain"]:                                   # steepen soft edges (sigmoid tone curve) - flat art only
                g = _ENH["gain"]; a = 1 / (1 + np.exp(-g * (a - 0.5))); a = (a - a.min()) / max(1e-6, a.max() - a.min())
            out = Image.fromarray((a * 255).astype("uint8"))
        steps += ["noise smoothing", "edge sharpening (unsharp %d%%)" % amount, "levels stretch", "edge steepening"]
    elif mode != "resample" and photo:
        out = out.filter(ImageFilter.UnsharpMask(radius=1.0 * scale, percent=60, threshold=3)); steps.append("light sharpening (photo)")
    info.update({"steps": steps, "result_px": [nw, nh], "sharpness_after": round(sharpness(out), 1)})
    buf = io.BytesIO(); out.save(buf, "PNG", optimize=True)
    return buf.getvalue(), info
