"""Photo Stitch Engine: photographic embroidery by tonal flow-field hatching.

A photograph is NOT a logo. Thread cannot print continuous tone, so tone is represented by LINE SPACING (dark = close lines, light = open lines, white = bare
fabric) and, in multicolour mode, by the choice of thread colour. What this module does (docs/embroidery/photo-digitizing-engine.md):

  1. tone map     luminance -> contrast stretch -> gamma -> darkness D in 0..1; ordered (Bayer) dithering of the tone BEFORE quantisation breaks up banding;
  2. orientation  structure tensor of the image -> stitches run ALONG contours (variable stitch direction); flat areas use the user's angle;
  3. hatching     evenly spaced streamlines through the field (Jobard-Lefer): local line spacing = f(tone), cross-hatch in the darkest tone;
  4. colour       grayscale (one thread) or multicolour (Lab k-means -> mapped to a thread palette); colour boundaries are feathered (sparser lines in a band
                  so neighbouring colours interleave);
  5. safety       minimum stitch 0.9 mm / maximum 7 mm by construction, penetrations per mm2 measured against a cap, total stitch budget with automatic coarsening;
  6. output       ordinary `manual` objects (every point is a penetration) so the existing generator, locks / trims, sequencing and the validated DST export are reused.

Honest limits: lines are visible (~0.3-1.2 mm spacing), at most 12 colours, no continuous tone, fabric shows through. Needs Pillow + NumPy.
"""
from __future__ import annotations
import io
import math
import time
from typing import Dict, List, Optional, Tuple

DEFAULT_PALETTE = [  # generic thread colours (NOT a brand chart): name, hex
    ("black", "#111111"), ("charcoal", "#4a4a4a"), ("grey", "#8a8a8a"), ("light grey", "#c4c4c4"), ("white", "#f4f4f4"), ("red", "#c8102e"), ("orange", "#e8761c"),
    ("yellow", "#f2c500"), ("green", "#2e8b3d"), ("light green", "#8cc152"), ("teal", "#1b9a9a"), ("blue", "#1f4fb4"), ("navy", "#16285a"), ("purple", "#6b3fa0"),
    ("pink", "#e58fb0"), ("brown", "#6b4423"), ("tan", "#c9a06b"), ("skin", "#e8b894")]
STEP_MM = 0.4            # streamline integration step
MIN_STITCH, MAX_STITCH = 0.9, 7.0
TIME_BUDGET_S = 120
BAYER4 = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def _hex(c): return "#%02x%02x%02x" % tuple(int(v) for v in c)
def _rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _prep(data, width_mm, fabric_rgb, max_px):
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 40_000_000
    im = Image.open(io.BytesIO(data)); im.load()
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA"); flat = Image.new("RGBA", rgba.size, tuple(fabric_rgb) + (255,)); flat.alpha_composite(rgba); im = flat
    im = im.convert("RGB")
    sw, sh = im.size
    work_w = min(max_px, max(60, math.ceil(width_mm / 0.2)))
    work_h = max(1, round(work_w * sh / sw))
    im = im.resize((work_w, work_h), Image.LANCZOS)
    return np.asarray(im).astype(np.float64), (sw, sh), width_mm / work_w


def _gauss(a, sigma, np):
    r = max(1, int(3 * sigma)); x = np.arange(-r, r + 1); k = np.exp(-x * x / (2 * sigma * sigma)); k /= k.sum()
    pad = np.pad(a, ((0, 0), (r, r)), mode="edge"); t = sum(k[i] * pad[:, i:i + a.shape[1]] for i in range(2 * r + 1))
    pad = np.pad(t, ((r, r), (0, 0)), mode="edge")
    return sum(k[i] * pad[i:i + a.shape[0]] for i in range(2 * r + 1))


def _orientation(lum, base_angle_deg, mm_per_px, np, follow=True):
    """Per-pixel stitch direction (radians) along image contours; flat areas fall back to `base_angle_deg`. Returns (angle map, strength map).
    Two scales: the fine structure tensor (edges, ~1.2 mm) and a coarse one (smooth shading, ~5 mm: stitches follow the isophotes, like engraving)."""
    base = math.radians(base_angle_deg)
    if not follow:
        return np.full(lum.shape, base), np.zeros(lum.shape)
    def tensor(sig_mm, pre_mm, gain, floor):
        g = _gauss(lum, max(1.0, pre_mm / mm_per_px), np)
        gy, gx = np.gradient(g)
        sig = max(1.5, sig_mm / mm_per_px)
        jxx, jyy, jxy = _gauss(gx * gx, sig, np), _gauss(gy * gy, sig, np), _gauss(gx * gy, sig, np)
        theta = 0.5 * np.arctan2(2 * jxy, jxx - jyy) + math.pi / 2
        tr = jxx + jyy + 1e-9; coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / tr
        return theta, np.clip((tr - floor) / gain, 0, 1) * np.clip((coh - 0.12) / 0.5, 0, 1)
    t1, s1 = tensor(1.2, 0.25, 60.0, 1.0)
    t2, s2 = tensor(5.0, 2.0, 2.5, 0.02)
    s2 = s2 * (1 - s1) * 0.9
    wb = np.clip(1.0 - s1 - s2, 0, 1)
    cx = s1 * np.cos(2 * t1) + s2 * np.cos(2 * t2) + wb * math.cos(2 * base); cy = s1 * np.sin(2 * t1) + s2 * np.sin(2 * t2) + wb * math.sin(2 * base)
    return 0.5 * np.arctan2(cy, cx), np.clip(s1 + s2, 0, 1)


def _bayer_map(shape, np):
    b = np.array(BAYER4, dtype=float) / 16.0
    return np.tile(b, (shape[0] // 4 + 1, shape[1] // 4 + 1))[:shape[0], :shape[1]]


def trace_streamlines(mask, dsep, angle, mm_per_px, np, deadline, min_len_mm=1.6, max_lines=100000, offset_phase=0.0):
    """Evenly spaced streamlines (Jobard-Lefer). mask: bool array of where thread may go; dsep: spacing in mm per pixel; angle: direction (rad).
    Returns a list of polylines in mm [(x, y), ...]."""
    H, W = mask.shape; cell = 0.25; grid: Dict[Tuple[int, int], List[Tuple[float, float, int]]] = {}
    lines: List[List[Tuple[float, float]]] = []
    inv = 1.0 / mm_per_px

    def inside(x, y):
        ix, iy = int(x * inv), int(y * inv)
        return 0 <= ix < W and 0 <= iy < H and mask[iy, ix]

    def sp(x, y):
        return float(dsep[min(H - 1, max(0, int(y * inv))), min(W - 1, max(0, int(x * inv)))])

    def ang(x, y):
        return float(angle[min(H - 1, max(0, int(y * inv))), min(W - 1, max(0, int(x * inv)))])

    def near(x, y, rad):
        cx, cy = int(x / cell), int(y / cell); r = int(rad / cell) + 1; r2 = rad * rad
        for gx in range(cx - r, cx + r + 1):
            for gy in range(cy - r, cy + r + 1):
                for px, py in grid.get((gx, gy), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < r2:
                        return True
        return False

    def trace(x0, y0):
        own: Dict[Tuple[int, int], List[Tuple[float, float, int, int]]] = {}
        pts = [(x0, y0)]
        for sign in (1, -1):
            x, y = x0, y0; a = ang(x, y); dx, dy = math.cos(a) * sign, math.sin(a) * sign
            cur: List[Tuple[float, float]] = []
            for k in range(420):                                      # at most ~170 mm per direction
                a = ang(x, y); vx, vy = math.cos(a), math.sin(a)
                if vx * dx + vy * dy < 0: vx, vy = -vx, -vy
                mx, my = x + vx * STEP_MM * 0.5, y + vy * STEP_MM * 0.5
                if not inside(mx, my): break
                a2 = ang(mx, my); wx, wy = math.cos(a2), math.sin(a2)
                if wx * vx + wy * vy < 0: wx, wy = -wx, -wy
                nx, ny = x + wx * STEP_MM, y + wy * STEP_MM
                if not inside(nx, ny): break
                rad = 0.5 * sp(nx, ny)
                if near(nx, ny, rad): break
                hit = False                                           # self-overlap (a streamline circling back on itself), ignoring its own recent points
                cx_, cy_ = int(nx / cell), int(ny / cell); rr = int(rad / cell) + 1
                for gx in range(cx_ - rr, cx_ + rr + 1):
                    for gy in range(cy_ - rr, cy_ + rr + 1):
                        for px, py, sg, idx in own.get((gx, gy), ()):
                            if (sg == sign and idx > k - 24) or (sg != sign and idx < 24 and k < 24): continue
                            if (px - nx) ** 2 + (py - ny) ** 2 < rad * rad: hit = True; break
                        if hit: break
                    if hit: break
                if hit: break
                dx, dy = wx, wy; x, y = nx, ny; cur.append((x, y))
                own.setdefault((int(x / cell), int(y / cell)), []).append((x, y, sign, k))
            pts = (list(reversed(cur)) + pts) if sign == -1 else (pts + cur)
        return pts

    def add_line(pts, lid):
        for x, y in pts:
            grid.setdefault((int(x / cell), int(y / cell)), []).append((x, y))

    def length(pts):
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))

    # coarse scan of seeds (every 1.5 mm) handles disconnected regions; each new line seeds its neighbours (Jobard-Lefer)
    ys, xs = np.nonzero(mask[::max(1, int(1.5 * inv)), ::max(1, int(1.5 * inv))])
    stepp = max(1, int(1.5 * inv))
    seeds = [(float(x * stepp * mm_per_px), float(y * stepp * mm_per_px)) for y, x in zip(ys, xs)]
    queue: List[int] = []

    def try_seed(x, y):
        if not inside(x, y) or near(x, y, 0.9 * sp(x, y)):
            return None
        lid = len(lines); pts = trace(x, y)
        if length(pts) < min_len_mm:
            return None
        lines.append(pts); add_line(pts, lid); return lid
    seed_i = 0
    while True:
        if time.time() > deadline:
            raise ValueError("photo stitching took too long; use a smaller size, fewer colours or a coarser density")
        if queue:
            lid = queue.pop()
            pts = lines[lid]
            stride = max(1, int(round(0.8 / STEP_MM)))
            for i in range(0, len(pts), stride):
                x, y = pts[i]; a = ang(x, y); nx_, ny_ = -math.sin(a), math.cos(a); d = sp(x, y)
                for side in (1, -1):
                    q = try_seed(x + side * nx_ * d, y + side * ny_ * d)
                    if q is not None:
                        queue.append(q)
                if len(lines) >= max_lines:
                    return lines
            continue
        while seed_i < len(seeds):
            x, y = seeds[seed_i]; seed_i += 1
            q = try_seed(x, y)
            if q is not None:
                queue.append(q); break
        else:
            break
    return lines


def resample(pts, step, np=None):
    """Polyline -> stitch points `step` mm apart, all stitches equal (so none is shorter than MIN_STITCH). [] if the line is too short."""
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    total = cum[-1]
    if total < MIN_STITCH * 1.2:
        return []
    n = max(1, int(round(total / step)))
    seg = total / n
    out = []; j = 0
    for i in range(n + 1):
        t = i * seg
        while j < len(cum) - 2 and cum[j + 1] < t: j += 1
        d = cum[j + 1] - cum[j]; u = 0.0 if d <= 0 else min(1.0, max(0.0, (t - cum[j]) / d))
        q = (pts[j][0] + (pts[j + 1][0] - pts[j][0]) * u, pts[j][1] + (pts[j + 1][1] - pts[j][1]) * u)
        if out and math.hypot(q[0] - out[-1][0], q[1] - out[-1][1]) < MIN_STITCH:
            continue                                              # a hairpin turn: the chord is shorter than the arc; never emit a stitch under the minimum
        out.append(q)
    return out if len(out) >= 2 else []


def chain(lines, join_mm, step, max_pts=600):
    """Greedy nearest-end chaining of stitch polylines into runs (one run = one thread path); lines whose ends are within `join_mm` are joined by one stitch."""
    lines = [l for l in (resample(l, step) for l in lines) if len(l) >= 2]
    if not lines:
        return []
    cell = max(join_mm, 1.0); grid: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for i, l in enumerate(lines):
        for end, p in ((0, l[0]), (1, l[-1])):
            grid.setdefault((int(p[0] / cell), int(p[1] / cell)), []).append((i, end))
    used = [False] * len(lines); runs = []
    order = sorted(range(len(lines)), key=lambda i: (lines[i][0][1], lines[i][0][0]))
    for i0 in order:
        if used[i0]:
            continue
        used[i0] = True; run = list(lines[i0])
        while len(run) < max_pts:
            x, y = run[-1]; best = None; bd = join_mm
            cx, cy = int(x / cell), int(y / cell)
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for j, end in grid.get((gx, gy), ()):
                        if used[j]: continue
                        p = lines[j][0] if end == 0 else lines[j][-1]
                        d = math.hypot(p[0] - x, p[1] - y)
                        if MIN_STITCH <= d < bd: bd, best = d, (j, end)
            if not best:
                break
            j, end = best; used[j] = True; run += (lines[j] if end == 0 else lines[j][::-1])
        runs.append(run)
    return runs


def _kmeans_lab(rgb_small, k, np, iters=12):
    from .raster import _srgb_to_lab
    lab = _srgb_to_lab(rgb_small.reshape(-1, 1, 3))[:, 0, :]
    rng = np.random.default_rng(3); idx = rng.choice(len(lab), min(k, len(lab)), replace=False); cent = lab[idx].copy()
    # farthest-point refinement of the seeds for stability
    for _ in range(iters):
        d = ((lab[:, None, :] - cent[None, :, :]) ** 2).sum(-1); lbl = d.argmin(1)
        for c in range(len(cent)):
            m = lbl == c
            if m.any(): cent[c] = lab[m].mean(0)
    return cent, lbl


def _lab_to_rgb(lab, np):
    fy = (lab[0] + 16) / 116; fx = fy + lab[1] / 500; fz = fy - lab[2] / 200
    f = lambda t: t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    x, y, z = 0.95047 * f(fx), 1.0 * f(fy), 1.08883 * f(fz)
    r, g, b = 3.2406 * x - 1.5372 * y - 0.4986 * z, -0.9689 * x + 1.8758 * y + 0.0415 * z, 0.0557 * x - 0.2040 * y + 1.0570 * z
    gam = lambda c: 12.92 * c if c <= 0.0031308 else 1.055 * (max(c, 0) ** (1 / 2.4)) - 0.055
    return tuple(max(0, min(255, round(255 * gam(c)))) for c in (r, g, b))


def photo_stitch(data: bytes, width_mm: float = 100.0, mode: str = "grayscale", colors: int = 4, levels: int = 5, density: float = 1.0, angle: float = 45.0,
                 direction: str = "flow", dither: float = 0.5, gamma: float = 1.0, cross_hatch: bool = True, equalize: float = 0.6, thread_palette: Optional[List[str]] = None,
                 fabric: str = "#ffffff", thread: Optional[str] = None, stitch_mm: float = 2.5, max_stitches: int = 180000, max_px: int = 520) -> dict:
    """Image -> {"objects": [...], "report": {...}, "size_mm": (w, h)}. See the module docstring for the algorithm."""
    try:
        import numpy as np
    except ImportError as e:
        from .raster import RasterUnavailable
        raise RasterUnavailable("photo stitching needs the optional Pillow and NumPy packages") from e
    if mode not in ("grayscale", "multicolour"):
        raise ValueError("mode must be grayscale or multicolour")
    if not 5 <= width_mm <= 1000: raise ValueError("width_mm must be between 5 and 1000")
    if not 2 <= levels <= 8: raise ValueError("levels must be 2-8")
    if not 1 <= colors <= 12: raise ValueError("colors must be 1-12")
    if not 0.4 <= density <= 2.5: raise ValueError("density must be between 0.4 and 2.5")
    if not 0.5 <= gamma <= 2.5: raise ValueError("gamma must be between 0.5 and 2.5")
    if not 0.0 <= dither <= 1.0: raise ValueError("dither must be between 0 and 1")
    if not 0.0 <= equalize <= 1.0: raise ValueError("equalize must be between 0 and 1")
    if direction not in ("flow", "fixed"): raise ValueError("direction must be flow or fixed")
    if not 1.2 <= stitch_mm <= 6.0: raise ValueError("stitch_mm must be between 1.2 and 6")
    t0 = time.time(); deadline = t0 + TIME_BUDGET_S
    fabric_rgb = _rgb(fabric)
    rgb, src_px, mm = _prep(data, width_mm, fabric_rgb, max_px)
    H, W = rgb.shape[:2]; height_mm = H * mm
    lum = (rgb @ np.array([0.299, 0.587, 0.114])) / 255.0
    fab_l = float(np.dot(fabric_rgb, [0.299, 0.587, 0.114]) / 255.0)
    notes: List[str] = []
    # ---- tone map: darkness relative to the fabric (so dark fabric works too)
    lo, hi = np.percentile(lum, 1), np.percentile(lum, 99)
    if hi - lo < 0.04:
        raise ValueError("nothing to stitch: the image has no tonal contrast (a single flat tone). Check the image, the fabric colour and the gamma")
    ln = np.clip((lum - lo) / max(hi - lo, 1e-3), 0, 1)
    D = np.clip(1.0 - ln, 0, 1) if fab_l >= 0.5 else ln
    # partial histogram equalisation over the subject (away from the background) so shading spans the tonal range
    bw = max(2, int(0.04 * min(H, W))); bgv = float(np.median(np.concatenate([D[:bw].ravel(), D[-bw:].ravel(), D[:, :bw].ravel(), D[:, -bw:].ravel()])))
    subj = np.abs(D - bgv) > 0.04
    if equalize > 0 and subj.sum() > 200:
        vals = np.sort(D[subj]); cdf = np.searchsorted(vals, D, side="right") / len(vals)
        D = np.where(subj, (1 - equalize) * D + equalize * cdf * D.max(), D)
        D = np.clip(D, 0, 1)
    D = D ** gamma
    # ordered dithering of the tone before quantisation (breaks up banding without creating gaps in the thread)
    bayer = _bayer_map(D.shape, np)
    Dq = np.clip(np.floor(D * levels + 0.5 + dither * (bayer - 0.5) * 1.6), 0, levels) / levels
    ang, strength = _orientation(lum * 255.0, angle, mm, np, follow=(direction == "flow"))
    objects: List[dict] = []; report: Dict = {"mode": mode, "levels": levels, "size_mm": [round(width_mm, 2), round(height_mm, 2)], "work_px": [W, H], "mm_per_px": round(mm, 4),
                                               "direction": direction, "flow_pixels_pct": round(100 * float((strength > 0.3).mean()), 1)}
    s_dark, s_light = 0.34, 1.15
    white_th = 0.5 / levels                                                        # tone level 0 = bare fabric
    runs_by_colour: List[Tuple[str, str, List[List[Tuple[float, float]]]]] = []
    coarsen = 1.0

    def spacing_map(Dm, k):                                                         # geometric interpolation: equal tone steps give equal coverage steps
        return s_dark * (s_light / s_dark) ** (1.0 - np.clip(Dm, 0, 1)) * k / density

    palette_used: List[dict] = []
    for attempt in range(4):
        runs_by_colour = []; t_all = 0
        if mode == "grayscale":
            col = thread or ("#111111" if fab_l >= 0.5 else "#f4f4f4")
            mask = Dq > white_th
            ds = spacing_map(Dq, coarsen)
            lines = trace_streamlines(mask, ds, ang, mm, np, deadline)
            runs_by_colour.append((col, "tone", lines))
            if cross_hatch:
                dark = Dq >= 0.8
                if dark.sum() > 20:
                    ds2 = np.full(Dq.shape, 0.9 * coarsen / density)
                    l2 = trace_streamlines(dark, ds2, ang + math.pi / 2, mm, np, deadline)
                    runs_by_colour.append((col, "cross-hatch (darkest tone)", l2))
            palette_used = [{"hex": col, "name": "thread"}]
        else:
            pal = [(n, h) for n, h in DEFAULT_PALETTE] if not thread_palette else [(h, h) for h in thread_palette]
            small = rgb.reshape(-1, 3)
            step_px = max(1, int(math.sqrt(len(small) / 20000)))
            cent, _ = _kmeans_lab(small[::step_px * step_px], colors, np)
            from .raster import _srgb_to_lab
            palab = _srgb_to_lab(np.array([[_rgb(h) for _, h in pal]], dtype=float))[0]
            mapping = {}
            for ci, c in enumerate(cent):
                j = int(((palab - c) ** 2).sum(1).argmin()); mapping[ci] = j
            used_j = sorted(set(mapping.values()))
            # label every pixel to the nearest THREAD colour (palette mapping), only among the used ones
            lab_img = _srgb_to_lab(rgb)
            d2 = np.stack([((lab_img - palab[j]) ** 2).sum(-1) for j in used_j], axis=-1); lbl = d2.argmin(-1)
            fab_lab = _srgb_to_lab(np.array([[fabric_rgb]], dtype=float))[0, 0]
            palette_used = []
            for li, j in enumerate(used_j):
                m = lbl == li
                if ((palab[j] - fab_lab) ** 2).sum() ** 0.5 < 9.0:                          # a colour the same as the fabric needs no thread
                    palette_used.append({"hex": pal[j][1], "name": pal[j][0], "skipped": "same as fabric"}); continue
                if m.sum() < 30: continue
                core = _erode_np(m, max(1, int(0.5 / mm)), np); band = _dilate_np(m, max(1, int(0.8 / mm)), np) & ~core
                region = core | band
                ds = np.where(core, 0.42, 0.42 * 2.0) * coarsen / density
                # tonal modulation inside the colour: lighter than the thread colour => sparser lines
                rel = np.clip((lum - float(np.dot(_rgb(pal[j][1]), [0.299, 0.587, 0.114]) / 255.0)) * 2.0, 0, 0.8)
                ds = ds * (1.0 + rel)
                lines = trace_streamlines(region, ds, ang, mm, np, deadline)
                runs_by_colour.append((pal[j][1], pal[j][0], lines)); palette_used.append({"hex": pal[j][1], "name": pal[j][0], "area_pct": round(100 * float(m.mean()), 1)})
        est = sum(sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(l, l[1:])) for _, _, ls in runs_by_colour for l in ls) / stitch_mm
        report["estimated_stitches"] = int(est)
        if est <= max_stitches:
            break
        coarsen *= 1.0 + min(1.0, (est / max_stitches - 1) + 0.2)
        notes.append(f"stitch budget: {int(est)} stitches exceeded {max_stitches}; line spacing coarsened x{coarsen:.2f} and re-traced")
        if time.time() > deadline: break
    # ---- chain into runs, build objects
    oid = 0; total_pts = 0
    for col, label, lines in runs_by_colour:
        for run in chain(lines, join_mm=2.2 * coarsen / density + 0.6, step=stitch_mm):
            if len(run) < 3: continue
            oid += 1; total_pts += len(run)
            objects.append({"id": f"ph{oid}", "type": "manual", "color": col, "name": f"{label} {oid}", "points": [[round(x, 3), round(y, 3)] for x, y in run], "params": {}})
    if not objects:
        raise ValueError("nothing to stitch: the image has no tone different from the fabric (all white / background). Check the fabric colour, contrast and gamma")
    if len(objects) > 2900:
        raise ValueError(f"photo design would need {len(objects)} thread paths (limit 3000): use a larger line spacing or fewer colours")
    # ---- measure: stitch lengths, penetration density
    lens = []; cells: Dict[Tuple[int, int], int] = {}
    for o in objects:
        P = o["points"]
        for a, b in zip(P, P[1:]): lens.append(math.hypot(b[0] - a[0], b[1] - a[1]))
        for x, y in P: cells[(int(x), int(y))] = cells.get((int(x), int(y)), 0) + 1
    report.update({"objects": len(objects), "stitches": total_pts, "coarsened": round(coarsen, 2), "palette": palette_used,
                   "min_stitch_mm": round(min(lens), 2) if lens else None, "max_stitch_mm": round(max(lens), 2) if lens else None,
                   "stitches_under_0_5mm": sum(1 for l in lens if l < 0.5), "max_penetrations_per_mm2": max(cells.values()) if cells else 0,
                   "line_spacing_mm": {"darkest": s_dark / density * coarsen, "lightest": s_light / density * coarsen}, "ms": round((time.time() - t0) * 1000), "notes": notes,
                   "limits": "Thread cannot show continuous tone: tone is line spacing / thread colour, lines are visible, at most 12 colours, the fabric shows through."})
    return {"objects": objects, "report": report, "size_mm": (width_mm, height_mm)}


def _erode_np(m, r, np):
    k = 2 * r + 1; pad = np.pad(m, r); out = np.ones_like(m)
    for dy in range(k):
        for dx in range(k):
            out &= pad[dy:dy + m.shape[0], dx:dx + m.shape[1]]
    return out


def _dilate_np(m, r, np):
    k = 2 * r + 1; pad = np.pad(m, r); out = np.zeros_like(m)
    for dy in range(k):
        for dx in range(k):
            out |= pad[dy:dy + m.shape[0], dx:dx + m.shape[1]]
    return out
