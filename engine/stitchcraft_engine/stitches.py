"""Stitch generators. Each returns point lists in mm; the builder turns them into commands."""
from __future__ import annotations
import math
from typing import List, Sequence, Tuple
from .geometry import Point, dist, polyline_length, resample_n, rotate, point_in_polygon


class DigitizingError(ValueError):
    pass


# ---------------------------------------------------------------- running
def running_stitch(points: Sequence[Point], stitch_len: float = 2.5, closed: bool = False) -> List[Point]:
    """Keeps every original vertex (corners stay sharp); splits long segments evenly."""
    if stitch_len <= 0:
        raise DigitizingError("stitch_len must be > 0")
    pts = [tuple(p) for p in points]
    if len(pts) < 2:
        raise DigitizingError("running stitch needs at least 2 points")
    if closed and dist(pts[0], pts[-1]) > 1e-9:
        pts.append(pts[0])
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


def satin_from_rails(left: Sequence[Point], right: Sequence[Point], spacing: float = 0.4) -> List[Point]:
    """Zigzag: one needle penetration every `spacing` mm along the column, alternating rails."""
    if spacing <= 0:
        raise DigitizingError("satin spacing must be > 0")
    n = max(1, round(max(polyline_length(left), polyline_length(right)) / spacing))
    lp, rp = resample_n(left, n), resample_n(right, n)
    return [lp[k] if k % 2 == 0 else rp[k] for k in range(n + 1)]


def satin_stitch(path: Sequence[Point], width: float, spacing: float = 0.4, pull_comp: float = 0.0) -> List[Point]:
    """pull_comp widens the column (total mm) to offset fabric pull-in; default 0 until machine-tested."""
    left, right = rails_from_centerline(path, width + pull_comp)
    return satin_from_rails(left, right, spacing)


def center_walk_underlay(path: Sequence[Point], stitch_len: float = 2.5) -> List[Point]:
    return running_stitch(path, stitch_len)


def edge_walk_underlay(path: Sequence[Point], width: float, inset: float = 0.4, stitch_len: float = 2.5) -> List[Point]:
    w = max(width - 2 * inset, 0.2)
    left, right = rails_from_centerline(path, w)
    return running_stitch(left, stitch_len) + running_stitch(right[::-1], stitch_len)[1:]


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
    return [[rotate(p, ang) for p in run] for run in runs]
