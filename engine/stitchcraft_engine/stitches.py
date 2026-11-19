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


MIN_VERTEX_GAP = 0.6     # mm; vertices closer than this (smoothed curves, round-shape inset rings) are thinned so no stitch is 0.3-0.6 mm long
CURVE_TOL = 0.1          # mm deviation allowed when thinning


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
    return _prune_short(out, 0.35)          # a corner vertex right next to another (inset rings) would make a sub-0.3 mm stitch


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
                     max_len: float = 0.0, shorten: bool = False) -> List[Point]:
    """Zigzag: one needle penetration every `spacing` mm along the column, alternating rails.
    max_len > 0 enables satin splitting: stitches longer than max_len get staggered interior points."""
    if spacing <= 0:
        raise DigitizingError("satin spacing must be > 0")
    n = max(1, round(max(polyline_length(left), polyline_length(right)) / spacing))
    lp, rp = resample_n(left, n), resample_n(right, n)
    pts = [lp[k] if k % 2 == 0 else rp[k] for k in range(n + 1)]
    if shorten:
        pts = _shorten_inner(pts, lp, rp, spacing)
    base = _prune_short(pts, 0.3)      # tapering tips: drop sub-0.3 mm stitches
    if max_len <= 0:
        return base
    out = [base[0]]
    for k in range(1, len(base)):
        out += split_long(base[k - 1], base[k], max_len, k)
        out.append(base[k])
    return out


def satin_stitch(path: Sequence[Point], width: float, spacing: float = 0.4, pull_comp: float = 0.0,
                 max_len: float = 0.0, shorten: bool = False) -> List[Point]:
    """pull_comp widens the column (total mm) to offset fabric pull-in; default 0 until machine-tested."""
    left, right = rails_from_centerline(path, width + pull_comp)
    return satin_from_rails(left, right, spacing, max_len, shorten)


def _shorten_inner(pts: List[Point], lp: Sequence[Point], rp: Sequence[Point], spacing: float) -> List[Point]:
    """Stitch shortening: on the inside of a tight curve the penetrations of one rail crowd together (same-side gap much smaller
    than the nominal 2 x spacing). Every second crowded penetration is pulled a third of the way towards the opposite rail, so the
    needle does not hit the same spot over and over (bunching, thread breaks). Straight sections are untouched."""
    out = list(pts)
    nominal = 2.0 * spacing
    crowded_count = {0: 0, 1: 0}
    for k in range(2, len(pts)):
        side = k % 2
        if dist(pts[k], pts[k - 2]) < 0.55 * nominal:
            crowded_count[side] += 1
            if crowded_count[side] % 2 == 0:
                a = lp[k] if side == 0 else rp[k]
                b = rp[k] if side == 0 else lp[k]
                w = dist(a, b)
                if w > 1.2:                      # never shorten a stitch below ~0.8 mm
                    t = 1.0 / 3.0
                    out[k] = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        else:
            crowded_count[side] = 0
    return out


def zigzag_underlay(left: Sequence[Point], right: Sequence[Point], inset: float = 0.5, advance: float = 1.0) -> List[Point]:
    """Zig-zag underlay for satin columns > ~3.5 mm: an open zig-zag inside the column (inset from both edges) that lifts the
    satin and grips the fabric. advance = distance along the column per underlay stitch."""
    n = min(len(left), len(right))
    a, b = [], []
    for p, q in zip(left[:n], right[:n]):
        w = dist(p, q)
        if w < 1e-9:
            a.append(tuple(p)); b.append(tuple(q)); continue
        t = min(inset, 0.25 * w) / w
        a.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
        b.append((q[0] + (p[0] - q[0]) * t, q[1] + (p[1] - q[1]) * t))
    return satin_from_rails(a, b, advance)


def center_walk_underlay(path: Sequence[Point], stitch_len: float = 2.5) -> List[Point]:
    return running_stitch(path, stitch_len)


def edge_walk_underlay(path: Sequence[Point], width: float, inset: float = 0.4, stitch_len: float = 2.5) -> List[Point]:
    w = max(width - 2 * inset, 0.2)
    left, right = rails_from_centerline(path, w)
    return running_stitch(left, stitch_len) + running_stitch(right[::-1], stitch_len)[1:]


def _prune_short(run: Sequence[Point], min_len: float) -> List[Point]:  # noqa: E302
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


END_MIN = 0.7       # shortest end stitch of a tatami row (mm); measured production files have < 1 % stitches under 0.5 mm


def underlay_path(points: Sequence[Point], tol: float = 0.1) -> List[Point]:
    """Densely sampled rails/midlines (every 0.5 mm) -> a path with few vertices, so underlay running stitches are ~stitch_len long
    instead of one needle penetration every 0.5 mm. Deviation from the original line is at most `tol` mm."""
    pts = [tuple(p) for p in points]
    return _simplify(pts, tol) if len(pts) > 2 else pts


# ---------------------------------------------------------------- tatami / fill
def tatami_fill(rings: Sequence[Sequence[Point]], angle_deg: float = 45.0, spacing: float = 0.4,
                stitch_len: float = 3.5, stagger: int = 3, min_stitch: float = 0.3,
                max_connect: float = 3.0, pull_comp: float = 0.0, regions: bool = False,
                exclude: Sequence[Sequence[Sequence[Point]]] = (), exclude_margin: float = 0.6,
                push_comp: float = 0.0, min_row: float = 0.0) -> List[List[Point]]:
    """Scanline fill with even-odd holes. Returns a list of runs; consecutive runs need a JUMP.
    Needle penetrations are staggered row to row (`stagger` phases) for the classic tatami texture.
    exclude: shapes (each a list of rings, even-odd) stitched ON TOP later - the part of this fill hidden under them is not sewn,
    except an under-lap of `exclude_margin` mm along each cut edge so no gap can open. push_comp: shorten the fill by this much
    across the rows (half at each side), against the fabric pushing out perpendicular to the stitches."""
    if spacing <= 0 or stitch_len <= 0:
        raise DigitizingError("spacing and stitch_len must be > 0")
    ang = math.radians(angle_deg)
    rot = [[rotate(p, -ang) for p in ring] for ring in rings if len(ring) >= 3]
    if not rot:
        raise DigitizingError("fill needs a ring with at least 3 points")
    ys = [p[1] for r in rot for p in r]
    ymin, ymax = min(ys), max(ys)
    push = max(0.0, min(push_comp, (ymax - ymin) / 3))
    ex_rot = [[[rotate(p, -ang) for p in ring] for ring in shape if len(ring) >= 3] for shape in exclude]
    ex_rot = [sh for sh in ex_rot if sh]

    segs: List[List[Point]] = []
    rows_iv = []
    j, y = 0, ymin + spacing / 2 + push / 2
    while y < ymax - push / 2:
        xs = []
        for ring in rot:
            for i in range(len(ring)):
                (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % len(ring)]
                if (y0 <= y < y1) or (y1 <= y < y0):
                    xs.append(x0 + (y - y0) / (y1 - y0) * (x1 - x0))
        xs.sort()
        # pull compensation: lengthen each row along the stitch direction (half per end)
        intervals = [(xs[i] - pull_comp / 2, xs[i + 1] + pull_comp / 2) for i in range(0, len(xs) - 1, 2) if xs[i + 1] - xs[i] > 1e-6]
        if ex_rot:
            intervals = _subtract(intervals, [iv for sh in ex_rot for iv in _scan(sh, y, -exclude_margin)])
            intervals = [iv for iv in intervals if iv[1] - iv[0] >= 1.0]        # no slivers left beside a cut-out
        intervals = [iv for iv in intervals if iv[1] - iv[0] >= max(min_stitch, min_row)]      # a row shorter than the minimum stitch (a pointed tip) adds nothing: neighbours cover it
        forward = j % 2 == 0
        phase = (j % max(stagger, 1)) / max(stagger, 1) * stitch_len
        row = []
        rows_iv.append((j, y, intervals, phase))
        for xa, xb in intervals:
            end_min = max(min_stitch, END_MIN)       # no 0.3-0.5 mm stubs at the row ends: the end stitch absorbs them
            k = math.ceil((xa + end_min - phase) / stitch_len)
            grid = []
            while True:
                x = phase + k * stitch_len
                if x >= xb - end_min:
                    break
                grid.append((x, y))
                k += 1
            pts = [(xa, y)] + grid + [(xb, y)]
            row.append(pts if forward else pts[::-1])
        segs += row if forward else row[::-1]
        j += 1
        y += spacing

    if regions:
        segs = _region_order(rows_iv, stitch_len, min_stitch)
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



def _scan(rings, y, grow=0.0):
    """Even-odd intervals of `rings` on the scanline y, each grown by `grow` mm per end (negative = shrunk)."""
    xs = []
    for ring in rings:
        for i in range(len(ring)):
            (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % len(ring)]
            if (y0 <= y < y1) or (y1 <= y < y0):
                xs.append(x0 + (y - y0) / (y1 - y0) * (x1 - x0))
    xs.sort()
    return [(xs[i] - grow, xs[i + 1] + grow) for i in range(0, len(xs) - 1, 2) if xs[i + 1] - xs[i] + 2 * grow > 1e-6]


def _subtract(ivs, cuts):
    out = list(ivs)
    for ca, cb in cuts:
        nxt = []
        for a, b in out:
            if cb <= a or ca >= b:
                nxt.append((a, b)); continue
            if ca > a:
                nxt.append((a, ca))
            if cb < b:
                nxt.append((cb, b))
        out = nxt
    return out


def _row_points(xa, xb, y, phase, stitch_len, min_stitch, forward):
    end_min = max(min_stitch, END_MIN)
    k = math.ceil((xa + end_min - phase) / stitch_len)
    grid = []
    while True:
        x = phase + k * stitch_len
        if x >= xb - end_min:
            break
        grid.append((x, y)); k += 1
    pts = [(xa, y)] + grid + [(xb, y)]
    return pts if forward else pts[::-1]


def _region_order(rows_iv, stitch_len, min_stitch):
    """Split the scanline intervals into regions (an interval continues a region only when exactly one interval of the previous
    row overlaps it and vice versa), then stitch each region completely, back and forth, before moving on. A ring with a hole,
    a U or a C shape is sewn as a few connected blocks instead of jumping across the gap on every row (one trim per row)."""
    regions, active = [], []                     # active: list of (region index, (xa, xb)) from the previous row
    for j, y, ivs, phase in rows_iv:
        new_active = []
        for iv in ivs:
            prev = [a for a in active if a[1][0] < iv[1] and iv[0] < a[1][1]]
            if len(prev) == 1 and sum(1 for o in ivs if prev[0][1][0] < o[1] and o[0] < prev[0][1][1]) == 1:
                r = prev[0][0]
            else:
                r = len(regions); regions.append([])
            regions[r].append((y, iv, phase)); new_active.append((r, iv))
        active = new_active
    out, cur = [], None
    left = list(range(len(regions)))
    while left:
        def entry_cost(r):
            y, (xa, xb), _ = regions[r][0]
            return 0.0 if cur is None else min(dist(cur, (xa, y)), dist(cur, (xb, y)))
        r = min(left, key=lambda r: (entry_cost(r), r)); left.remove(r)
        y0, (xa0, xb0), _ = regions[r][0]
        forward = cur is None or dist(cur, (xa0, y0)) <= dist(cur, (xb0, y0))
        for y, (xa, xb), phase in regions[r]:
            seg = _row_points(xa, xb, y, phase, stitch_len, min_stitch, forward)
            out.append(seg); forward = not forward
        cur = out[-1][-1]
    return out


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



# ---------------------------------------------------------------- motif run (decorative repeat along a path)
MOTIFS = {
    "wave":    [(k / 8, math.sin(2 * math.pi * k / 8)) for k in range(9)],
    "zigzag":  [(0, 0), (0.25, 1), (0.75, -1), (1, 0)],
    "scallop": [(k / 8, math.sin(math.pi * k / 8)) for k in range(9)],
    "diamond": [(0, 0), (0.5, 1), (1, 0), (0.5, -1), (0, 0), (1, 0)],
    "leaf":    [(k / 8, math.sin(math.pi * k / 8)) for k in range(9)] + [(1 - k / 8, -math.sin(math.pi * (1 - k / 8))) for k in range(1, 9)] + [(1, 0)],
}


def motif_run(path: Sequence[Point], kind: str = "wave", size: float = 4.0, amp: float = 1.5, stitch_len: float = 2.0) -> List[Point]:
    """A small motif repeated along a path as one continuous running stitch (decorative borders, maggam-style edges).
    size = length of one repeat along the path, amp = how far the motif swings to each side (mm)."""
    if kind not in MOTIFS:
        raise DigitizingError(f"unknown motif {kind!r}; use one of {', '.join(MOTIFS)}")
    if size <= 0.5 or amp < 0:
        raise DigitizingError("motif size must be > 0.5 mm and amplitude >= 0")
    pts = [tuple(p) for p in path]
    L = polyline_length(pts)
    if L < 1e-6:
        raise DigitizingError("motif run needs a path with some length")
    n = max(1, round(L / size)); step = L / n
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + dist(a, b))

    def at(t):
        t = max(0.0, min(L, t))
        for i in range(len(pts) - 1):
            if cum[i + 1] >= t - 1e-12 and cum[i + 1] - cum[i] > 1e-12:
                u = (t - cum[i]) / (cum[i + 1] - cum[i]); a, b = pts[i], pts[i + 1]
                d = cum[i + 1] - cum[i]; tx, ty = (b[0] - a[0]) / d, (b[1] - a[1]) / d
                return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u), (-ty, tx)
        a, b = pts[-2], pts[-1]; d = dist(a, b) or 1.0
        return b, (-(b[1] - a[1]) / d, (b[0] - a[0]) / d)
    out: List[Point] = []
    for r in range(n):
        for u, v in MOTIFS[kind]:
            (x, y), (nx, ny) = at((r + u) * step)
            q = (x + nx * v * amp, y + ny * v * amp)
            if not out or dist(out[-1], q) > 1e-6:
                out.append(q)
    return running_stitch(out, stitch_len)


def exact_stitches(points: Sequence[Point], max_len: float = 7.0) -> List[Point]:
    """Manual stitches: every point is a needle penetration, exactly where it was placed. Only segments longer than max_len are
    split (DST / machine limit). No simplification, no resampling - this is stitch-level editing."""
    pts = [tuple(p) for p in points]
    if len(pts) < 2:
        raise DigitizingError("manual stitches need at least 2 points")
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        d = dist(a, b)
        if d < 1e-9:
            continue
        n = max(1, math.ceil(d / max_len - 1e-9))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1)]
    return out


def warp_to_path(strokes: Sequence[Sequence[Point]], path: Sequence[Point], height: float, align: str = "center") -> List[List[Point]]:
    """Text on a path: lettering strokes laid out on a straight baseline (x along, y down, baseline at y = height) are bent onto
    `path`: x becomes the distance along the path, the height above the baseline goes along the path's upward normal."""
    pts = [tuple(p) for p in path]
    L = polyline_length(pts)
    if L < 1e-6:
        raise DigitizingError("text path has no length")
    xs = [p[0] for st in strokes for p in st]
    tw = (max(xs) - min(xs)) if xs else 0.0
    off = {"start": 0.0, "end": L - tw, "center": (L - tw) / 2}.get(align, (L - tw) / 2) - (min(xs) if xs else 0.0)
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + dist(a, b))

    def frame(t):
        for i in range(len(pts) - 1):
            seg = cum[i + 1] - cum[i]
            if (cum[i + 1] >= t or i == len(pts) - 2) and seg > 1e-12:
                tx, ty = (pts[i + 1][0] - pts[i][0]) / seg, (pts[i + 1][1] - pts[i][1]) / seg
                u = (t - cum[i]) / seg
                return (pts[i][0] + tx * u * seg, pts[i][1] + ty * u * seg), (ty, -tx)     # up = left of travel on a y-down canvas
        return pts[0], (0.0, -1.0)
    out = []
    for st in strokes:
        w = []
        for x, y in st:
            (bx, by), (ux, uy) = frame(x + off)
            up = height - y
            w.append((bx + ux * up, by + uy * up))
        out.append(w)
    return out
