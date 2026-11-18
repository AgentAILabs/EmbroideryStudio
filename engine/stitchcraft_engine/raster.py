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
    "high":     {"max_px": 700, "up": 4, "blur": 0.9, "tol_mm": 0.08, "min_area": 1.2, "merge_de": 16.0, "majority": 1},
}
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


def _remove_fringe(labels, k, bg, thin_frac=0.75):
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
    mm = width_mm / (W * up)
    rings = []
    for loop in _loops_fast(hi):
        pts = _simplify_closed([(float(x), float(y)) for x, y in loop], max(1.1, tol_mm / mm))     # floor > 1 hi-res px, else the thresholded pixel staircase survives
        if len(pts) >= 3:
            rings.append([(x * mm, y * mm) for x, y in pts])
    return rings


def _nest(rings):
    """Group rings into outers with their holes (even-odd depth); returns [(outer, [holes])]."""
    from .geometry import point_in_ring
    n = len(rings)
    parent = [None] * n
    depth = [0] * n
    contain = [[j for j in range(n) if j != i and _area(rings[j]) > _area(rings[i]) and point_in_ring(rings[i][0], rings[j])] for i in range(n)]
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
    """Pick the right stitch type for one connected shape: thin -> running line, narrow elongated -> satin column, else fill."""
    from .outline import column_from_outline
    area = _area(outer) - sum(_area(h) for h in holes)
    per = _perim(outer) + sum(_perim(h) for h in holes)
    w = 2 * area / per if per > 0 else 0.0
    if not holes and w < COLUMN_MAX_MM:
        try:
            col = column_from_outline(outer)
        except ValueError:
            col = None
        if col is not None and col["aspect"] >= MIN_ASPECT:
            if w < THIN_MM:
                mid = [[(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] for a, b in zip(col["rail1"], col["rail2"])]
                return {"type": "run", "color": color, "points": _round(mid), "smooth": False, "params": {"stitch_len": 2.0}}, "run"
            if w >= THIN_MM:
                return {"type": "column", "color": color, "rail1": col["rail1"], "rail2": col["rail2"], "params": {"pull_comp": 0.2}}, "column"
    aspect = 1.0
    xs, ys = [p[0] for p in outer], [p[1] for p in outer]
    ang = _major_axis_deg(outer) if (max(xs) - min(xs) > 0 and (max(xs) - min(xs)) / max(1e-9, max(ys) - min(ys)) > 2.0 or max(ys) - min(ys) > 2.0 * (max(xs) - min(xs))) else 45.0
    return {"type": "fill", "color": color, "rings": [_round(outer)] + [_round(h) for h in holes], "params": {"angle": round(ang, 1), "pull_comp": 0.2}}, "fill"


def _photographic(rgb):
    import numpy as np
    from PIL import Image
    t = np.asarray(Image.fromarray(rgb).resize((96, 96), Image.BILINEAR)) >> 4
    return len(np.unique(t.reshape(-1, 3), axis=0)) > 400


def digitize_image(data: bytes, width_mm: float, max_colors: int = 6, quality: str = "standard"):
    """Image -> editable objects with a quality report. Returns {"objects", "notes", "size_mm", "report"}."""
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
    cfg = QUALITY[quality]; t0 = time.time()
    im = Image.open(io.BytesIO(data))
    if im.width * im.height > MAX_PIXELS:
        raise ValueError("image has too many pixels")
    is_jpeg = data[:3] == b"\xff\xd8\xff"
    src_w, src_h = im.size
    notes, report = [], {"quality": quality, "source_px": [src_w, src_h]}
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
    sc = cfg["max_px"] / max(im.size)
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
    if cfg["majority"]:
        labels = _majority(labels, k, cfg["majority"])
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
        labels, report["fringe_colours_removed"] = _remove_fringe(labels, k, bg)
    report["background"] = None if bg is None else "#%02x%02x%02x" % pal[bg]
    mm = width_mm / W; height_mm = H * mm
    # smoothing in source pixels: a coarse source (big pixels) needs more of it, a crisp one almost none (corners stay sharp)
    up = cfg["up"] if cfg["up"] == 1 else max(cfg["up"], min(8, math.ceil(mm / 0.09)))         # coarse source: more up-sampling so hi-res px <= ~0.09 mm
    blur_px = 0 if not cfg["blur"] else cfg["blur"] * (0.7 + 0.9 * min(1.0, max(0.0, (mm - 0.15) / 0.5)))
    objs, kinds, dropped, areas = [], {"fill": 0, "column": 0, "run": 0}, 0, {}
    for ci in range(k):
        if ci == bg or not (labels == ci).any():
            continue
        color = "#%02x%02x%02x" % pal[ci]
        comps = _nest(_contours_mm(labels == ci, up, blur_px, cfg["tol_mm"], width_mm))
        for outer, holes in comps:
            if _area(outer) < cfg["min_area"]:
                dropped += 1; continue
            holes = [h for h in holes if _area(h) >= cfg["min_area"] / 2]
            o, kind = _make_object(outer, holes, color, cfg, report)
            o["_a"] = _area(outer); o["_c"] = ci; o["_kind"] = kind
            objs.append(o); kinds[kind] += 1; areas[ci] = areas.get(ci, 0) + o["_a"]
    # order: colours by total area (largest first = bottom layer), inside a colour fills -> columns -> runs, nearest-neighbour for fewer jumps
    rank = {c: i for i, c in enumerate(sorted(areas, key=lambda c: -areas[c]))}
    krank = {"fill": 0, "column": 1, "run": 2}
    def start(o):
        return tuple(o["rings"][0][0]) if o["type"] == "fill" else tuple(o["rail1"][0]) if o["type"] == "column" else tuple(o["points"][0])
    ordered, cur = [], None
    for key in sorted({(rank[o["_c"]], krank[o["_kind"]]) for o in objs}):
        group = [o for o in objs if (rank[o["_c"]], krank[o["_kind"]]) == key]
        while group:
            nxt = group[0] if cur is None else min(group, key=lambda o: math.dist(start(o), cur))
            group.remove(nxt); ordered.append(nxt); cur = start(nxt)
    for i, o in enumerate(ordered):
        o["id"] = f"img{i + 1}"; o["name"] = f"{o.pop('_kind').capitalize()} {i + 1}"; o.pop("_a"); o.pop("_c")
    report.update({"colours_used": len({o["color"] for o in ordered}), "palette": ["#%02x%02x%02x" % c for c in pal[:k]],
                   "objects": kinds, "dropped_specks": dropped, "work_px": [W, H], "ms": round((time.time() - t0) * 1000)})
    if dropped:
        notes.append(f"{dropped} tiny shape(s) smaller than {cfg['min_area']:g} mm² were left out (specks / noise). Use quality 'high' to keep smaller details.")
    if kinds["run"]:
        notes.append(f"{kinds['run']} thin line(s) under {THIN_MM:g} mm wide became running stitch.")
    if not ordered:
        notes.append("Nothing to digitize. For images, use flat-colour artwork on a plain background.")
    return {"objects": ordered, "notes": notes, "size_mm": (width_mm, height_mm), "report": report}


def digitize_raster(data: bytes, width_mm: float, max_colors: int = 6, min_area_mm2: float = 4.0, simplify_mm: float = 0.25,
                    quality: str = "standard"):
    """Backwards-compatible entry point -> (objects, notes, (width_mm, height_mm)). quality: draft | standard | high | legacy."""
    if quality == "legacy":
        return _digitize_legacy(data, width_mm, max_colors, min_area_mm2, simplify_mm)
    r = digitize_image(data, width_mm, max_colors, quality)
    return r["objects"], r["notes"], r["size_mm"]
