"""Stitch generators. Each returns point lists in mm; the builder turns them into commands."""
from __future__ import annotations
import math
from typing import List, Sequence, Tuple
from .geometry import Point, dist, polyline_length, resample_n, rotate, point_in_polygon, inset_ring, polygon_area


class DigitizingError(ValueError):
    pass


# ---------------------------------------------------------------- running
def _simplify(pts: Sequence[Point], tol: float) -> List[Point]:
    """Douglas-Peucker: drop vertices that deviate less than tol from the chord (corners are kept)."""
    pts = [tuple(p) for p in pts]
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy)
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x1 * y0 - y1 * x0) / n if n > 1e-12 else dist(pts[i], pts[0])
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [pts[0], pts[-1]]
    return _simplify(pts[:idx + 1], tol)[:-1] + _simplify(pts[idx:], tol)


MIN_VERTEX_GAP = 0.3     # mm; vertices closer than this (smoothed curves) are thinned so they cannot become sub-0.3 mm stitches
CURVE_TOL = 0.08         # mm deviation allowed when thinning


def running_stitch(points: Sequence[Point], stitch_len: float = 2.5, closed: bool = False) -> List[Point]:
    """Keeps every original vertex (corners stay sharp); splits long segments evenly. Paths with very dense vertices
    (e.g. a smoothed curve) are first simplified to within CURVE_TOL so they do not turn into hundreds of tiny stitches;
    paths without such vertices are untouched, so existing designs keep their exact stitches."""
    if stitch_len <= 0:
        raise DigitizingError("stitch_len must be > 0")
    pts = [tuple(p) for p in points]
    if len(pts) < 2:
        raise DigitizingError("running stitch needs at least 2 points")
    if closed and dist(pts[0], pts[-1]) > 1e-9:
        pts.append(pts[0])
    if any(1e-9 < dist(a, b) < MIN_VERTEX_GAP for a, b in zip(pts, pts[1:])):
        pts = _simplify(pts, CURVE_TOL)
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        d = dist(a, b)
        if d < 1e-9:
            continue
        n = max(1, math.ceil(d / stitch_len - 1e-9))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1)]
    return out


# ---------------------------------------------------------------- satin
def rails_from_centerline(path: Sequence[Point], width: float, step: float = 0.5) -> Tuple[List[Point], List[Point]]:
    if width <= 0:
        raise DigitizingError("satin width must be > 0")
    length = polyline_length(path)
    if length < 1e-6:
        raise DigitizingError("satin centerline has zero length")
    s = resample_n(path, max(2, math.ceil(length / step)))
    left, right = [], []
    for i, p in enumerate(s):
        a, b = s[max(i - 1, 0)], s[min(i + 1, len(s) - 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        n = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / n, tx / n
        left.append((p[0] + nx * width / 2, p[1] + ny * width / 2))
        right.append((p[0] - nx * width / 2, p[1] - ny * width / 2))
    return left, right


_SPLIT_PHASE = (0.0, 0.3, -0.3, 0.15, -0.15)


def split_long(a: Point, b: Point, max_len: float, k: int) -> List[Point]:
    """Interior needle points that cut one over-long satin stitch a->b into pieces <= max_len.
    Split points are staggered from stitch to stitch (by k) so they do not line up into a visible ridge."""
    d = dist(a, b)
    if max_len <= 0 or d <= max_len:
        return []
    # staggering stretches the first/last piece by up to (1 + max|phase|) x the even piece, so size for that
    m = math.ceil(d * (1 + max(abs(x) for x in _SPLIT_PHASE)) / max_len - 1e-9)
    ph = _SPLIT_PHASE[k % len(_SPLIT_PHASE)]
    ts = [(j + ph) / m for j in range(1, m)]
    return [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t) for t in ts]


def satin_from_rails(left: Sequence[Point], right: Sequence[Point], spacing: float = 0.4,
                     max_len: float = 0.0) -> List[Point]:
    """Zigzag: one needle penetration every `spacing` mm along the column, alternating rails.
    max_len > 0 enables satin splitting: stitches longer than max_len get staggered interior points."""
    if spacing <= 0:
        raise DigitizingError("satin spacing must be > 0")
    n = max(1, round(max(polyline_length(left), polyline_length(right)) / spacing))
    lp, rp = resample_n(left, n), resample_n(right, n)
    base = [lp[k] if k % 2 == 0 else rp[k] for k in range(n + 1)]
    if max_len <= 0:
        return base
    out = [base[0]]
    for k in range(1, len(base)):
        out += split_long(base[k - 1], base[k], max_len, k)
        out.append(base[k])
    return out


def satin_stitch(path: Sequence[Point], width: float, spacing: float = 0.4, pull_comp: float = 0.0,
                 max_len: float = 0.0) -> List[Point]:
    """pull_comp widens the column (total mm) to offset fabric pull-in; default 0 until machine-tested."""
    left, right = rails_from_centerline(path, width + pull_comp)
    return satin_from_rails(left, right, spacing, max_len)


def center_walk_underlay(path: Sequence[Point], stitch_len: float = 2.5) -> List[Point]:
    return running_stitch(path, stitch_len)


def edge_walk_underlay(path: Sequence[Point], width: float, inset: float = 0.4, stitch_len: float = 2.5) -> List[Point]:
    w = max(width - 2 * inset, 0.2)
    left, right = rails_from_centerline(path, w)
    return running_stitch(left, stitch_len) + running_stitch(right[::-1], stitch_len)[1:]


def _prune_short(run: Sequence[Point], min_len: float) -> List[Point]:
    """Drop points that would create a stitch shorter than min_len (the final point is always kept). Runs that already have
    no such stitch come back unchanged."""
    run = [tuple(p) for p in run]
    if len(run) < 3 or all(dist(a, b) >= min_len for a, b in zip(run, run[1:])):
        return run
    out = [run[0]]
    for p in run[1:-1]:
        if dist(out[-1], p) >= min_len:
            out.append(p)
    last = run[-1]
    while len(out) > 1 and dist(out[-1], last) < min_len:
        out.pop()
    out.append(last)
    return out


# ---------------------------------------------------------------- tatami / fill
def tatami_fill(rings: Sequence[Sequence[Point]], angle_deg: float = 45.0, spacing: float = 0.4,
                stitch_len: float = 3.5, stagger: int = 3, min_stitch: float = 0.3,
                max_connect: float = 3.0, pull_comp: float = 0.0) -> List[List[Point]]:
    """Scanline fill with even-odd holes. Returns a list of runs; consecutive runs need a JUMP.
    Needle penetrations are staggered row to row (`stagger` phases) for the classic tatami texture."""
    if spacing <= 0 or stitch_len <= 0:
        raise DigitizingError("spacing and stitch_len must be > 0")
    ang = math.radians(angle_deg)
    rot = [[rotate(p, -ang) for p in ring] for ring in rings if len(ring) >= 3]
    if not rot:
        raise DigitizingError("fill needs a ring with at least 3 points")
    ys = [p[1] for r in rot for p in r]
    ymin, ymax = min(ys), max(ys)

    segs: List[List[Point]] = []
    j, y = 0, ymin + spacing / 2
    while y < ymax:
        xs = []
        for ring in rot:
            for i in range(len(ring)):
                (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % len(ring)]
                if (y0 <= y < y1) or (y1 <= y < y0):
                    xs.append(x0 + (y - y0) / (y1 - y0) * (x1 - x0))
        xs.sort()
        # pull compensation: lengthen each row along the stitch direction (half per end)
        intervals = [(xs[i] - pull_comp / 2, xs[i + 1] + pull_comp / 2) for i in range(0, len(xs) - 1, 2) if xs[i + 1] - xs[i] > 1e-6]
        intervals = [iv for iv in intervals if iv[1] - iv[0] >= min_stitch]      # a row shorter than the minimum stitch (a pointed tip) adds nothing: neighbours cover it
        forward = j % 2 == 0
        phase = (j % max(stagger, 1)) / max(stagger, 1) * stitch_len
        row = []
        for xa, xb in intervals:
            k = math.ceil((xa + min_stitch - phase) / stitch_len)
            grid = []
            while True:
                x = phase + k * stitch_len
                if x >= xb - min_stitch:
                    break
                grid.append((x, y))
                k += 1
            pts = [(xa, y)] + grid + [(xb, y)]
            row.append(pts if forward else pts[::-1])
        segs += row if forward else row[::-1]
        j += 1
        y += spacing

    runs: List[List[Point]] = []
    cur: List[Point] = []
    for seg in segs:
        if cur:
            a, b = cur[-1], seg[0]
            d = dist(a, b)
            ok = d <= 2.5 * spacing or (d <= max_connect and all(
                point_in_polygon((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), rot)
                for t in (0.25, 0.5, 0.75)))
            if ok:
                cur += seg
                continue
            runs.append(cur)
            cur = []
        cur = list(seg)
    if cur:
        runs.append(cur)
    return [_prune_short([rotate(p, ang) for p in run], min_stitch) for run in runs]



def _thin(ring: Sequence[Point], min_gap: float) -> List[Point]:
    """Drop vertices closer than min_gap to the previous kept one (inset rings of round shapes get very dense)."""
    out = [tuple(ring[0])]
    for p in ring[1:]:
        if dist(out[-1], p) >= min_gap:
            out.append(tuple(p))
    while len(out) > 3 and dist(out[-1], out[0]) < min_gap:
        out.pop()
    return out


# ---------------------------------------------------------------- contour fill (concentric rings)
def contour_fill(rings: Sequence[Sequence[Point]], spacing: float = 0.4, stitch_len: float = 3.0) -> List[List[Point]]:
    """Concentric inset rings stitched as one continuous run. Raises DigitizingError when the shape has holes or is
    too complex to inset reliably all the way to the centre - the caller then falls back to tatami (never half-fills)."""
    if spacing <= 0 or stitch_len <= 0:
        raise DigitizingError("spacing and stitch_len must be > 0")
    if len(rings) != 1:
        raise DigitizingError("contour fill needs a single outline without holes")
    ring = [tuple(p) for p in rings[0]]
    if len(ring) < 3:
        raise DigitizingError("fill needs a ring with at least 3 points")
    out: List[Point] = []
    cur = ring
    levels = 0
    while cur is not None and levels < 2000:
        thin = _thin(cur, 0.4)
        if len(thin) >= 3:
            out += running_stitch(thin, stitch_len, closed=True)
        levels += 1
        nxt = inset_ring(cur, spacing)
        if nxt is None:
            # stopped early? the leftover area must be tiny, otherwise the centre would be left empty
            if polygon_area(cur) > max(6 * spacing * spacing, 2.0):
                raise DigitizingError("shape is too complex for contour fill to reach the centre")
            break
        cur = nxt
    return [out]


# ---------------------------------------------------------------- cross-stitch fill
def cross_fill(rings: Sequence[Sequence[Point]], size: float = 2.0) -> List[List[Point]]:
    """Grid of X stitches (cells whose centre lies inside the shape). Per row: a pass of '/' then a return pass of '\\'."""
    if not 1.0 <= size <= 4.9:
        raise DigitizingError("cross size must be 1.0-4.9 mm (diagonal must stay under 7 mm)")
    rr = [tuple(p) for r in rings for p in r]
    if len(rr) < 3:
        raise DigitizingError("fill needs a ring with at least 3 points")
    xs, ys = [p[0] for p in rr], [p[1] for p in rr]
    x0, y0 = min(xs), min(ys)
    cols, rows = int(math.ceil((max(xs) - x0) / size)), int(math.ceil((max(ys) - y0) / size))
    runs: List[List[Point]] = []
    for j in range(rows):
        top, bot = y0 + j * size, y0 + (j + 1) * size
        chunk: List[int] = []
        chunks: List[List[int]] = []
        for i in range(cols):
            if point_in_polygon((x0 + (i + 0.5) * size, (top + bot) / 2), rings):
                chunk.append(i)
            elif chunk:
                chunks.append(chunk); chunk = []
        if chunk:
            chunks.append(chunk)
        for ch in chunks:
            path: List[Point] = []
            for i in ch:                                   # forward: '/'  bottom-left -> top-right, then down the shared edge
                xl, xr = x0 + i * size, x0 + (i + 1) * size
                path += [(xl, bot), (xr, top), (xr, bot)]
            for i in reversed(ch):                         # return: '\'  bottom-right -> top-left, then down the shared edge
                xl, xr = x0 + i * size, x0 + (i + 1) * size
                path += [(xr, bot), (xl, top), (xl, bot)]
            clean = [path[0]] + [q for a, q in zip(path, path[1:]) if dist(a, q) > 1e-9]
            runs.append(clean)
    if not runs:
        raise DigitizingError("shape is smaller than one cross; reduce the cross size")
    return runs
