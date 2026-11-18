"""Flat-colour raster -> editable fill objects (Phase 4a, optional: needs numpy + Pillow).
Quantise to <= N colours, drop the background, trace pixel-boundary loops per colour, simplify.
Honest limits: works for logos / flat artwork; photos and gradients give poor results and are warned about."""
from __future__ import annotations
import io
from collections import defaultdict
from typing import List, Tuple

MAX_PIXELS = 25_000_000


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


def digitize_raster(data: bytes, width_mm: float, max_colors: int = 6, min_area_mm2: float = 4.0,
                    simplify_mm: float = 0.25):
    try:
        import numpy as np
        from PIL import Image
    except ImportError as e:  # pragma: no cover
        raise RasterUnavailable("raster import needs numpy and Pillow") from e
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    im = Image.open(io.BytesIO(data))
    if im.width * im.height > MAX_PIXELS:
        raise ValueError("image has too many pixels")
    notes = []
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    im = im.convert("RGB")
    scale_down = 320 / max(im.size)
    if scale_down < 1:
        im = im.resize((max(1, round(im.width * scale_down)), max(1, round(im.height * scale_down))), Image.LANCZOS)
    q = im.quantize(colors=max(2, min(max_colors, 12)), method=Image.MEDIANCUT, dither=Image.NONE)
    idx = np.asarray(q)
    pal = np.asarray(q.getpalette()[:3 * (idx.max() + 1)]).reshape(-1, 3)
    uniq = len(np.unique(idx))
    if uniq >= max_colors and max_colors <= 12:
        notes.append("Image may have more colours than the limit; shaded/photographic art digitizes poorly.")
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
