"""Satin-from-outline: turn a closed, elongated shape (petal, leaf, thick stroke) into the two rails of a satin column.
Method (deterministic, pure Python): resample the outline evenly, find the major axis (PCA), take the outline point at
each END of that axis (the middle of a blunt end), and split the outline there into two chains = the rails.
Honest limits: one column per shape - branching shapes (T, Y, stars), blobs and rings are refused, not guessed."""
from __future__ import annotations
import math
from typing import List, Sequence, Tuple
from .geometry import Point, dist, point_in_ring, polyline_length, resample_n, _signed_area

MIN_ASPECT = 1.6          # length / width below this is a blob: use a fill


def _cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Proper intersection of segments ab and cd (touching endpoints do not count)."""
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    d1, d2, d3, d4 = o(c, d, a), o(c, d, b), o(a, b, c), o(a, b, d)
    return d1 * d2 < -1e-12 and d3 * d4 < -1e-12


def _any_cross(r1: Sequence[Point], r2: Sequence[Point]) -> bool:
    lines = list(zip(r1[1:-1], r2[1:-1]))
    return any(_cross(lines[i][0], lines[i][1], lines[j][0], lines[j][1]) for i in range(len(lines)) for j in range(i + 2, len(lines)))


def _inside_or_on(q: Point, ring: Sequence[Point], tol: float = 0.2) -> bool:
    """Inside the polygon, or within tol mm of its boundary (points exactly on an edge are ambiguous for even-odd)."""
    if point_in_ring(q, ring):
        return True
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / l2)) if l2 else 0.0
        if dist(q, (a[0] + t * dx, a[1] + t * dy)) <= tol:
            return True
    return False


def _perpendicular_pairs(r1: List[Point], r2: List[Point]) -> Tuple[List[Point], List[Point]]:
    """Re-pair rail points so each stitch line is ~perpendicular to the column's centre line. Pairing by arc fraction
    slants stitches on strongly curved strokes (outer and inner rails differ in length). Tips stay fixed; any point
    without a clean perpendicular crossing keeps its original partner; positions stay monotone along each rail."""
    n = len(r1) - 1
    mid = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(r1, r2)]
    win = max(4, n // 3)

    def tangent(i):
        a, b = mid[max(i - 1, 0)], mid[min(i + 1, n)]
        l = math.hypot(b[0] - a[0], b[1] - a[1])
        return ((b[0] - a[0]) / l, (b[1] - a[1]) / l) if l > 1e-9 else (1.0, 0.0)

    def cross(rail, i, m, t, lo_bound):
        best, bd = None, 1e18
        for k in range(max(0, i - win), min(len(rail) - 1, i + win)):
            f0 = (rail[k][0] - m[0]) * t[0] + (rail[k][1] - m[1]) * t[1]
            f1 = (rail[k + 1][0] - m[0]) * t[0] + (rail[k + 1][1] - m[1]) * t[1]
            if f0 * f1 <= 0 and f0 != f1:
                u = f0 / (f0 - f1)
                q = (rail[k][0] + (rail[k + 1][0] - rail[k][0]) * u, rail[k][1] + (rail[k + 1][1] - rail[k][1]) * u)
                pos = k + u
                d = dist(q, m)
                if pos >= lo_bound and d < bd:
                    best, bd = (q, pos), d
        return best

    o1, o2 = [r1[0]], [r2[0]]
    p1 = p2 = 0.0
    for i in range(1, n):
        t = tangent(i)
        c1, c2 = cross(r1, i, mid[i], t, p1), cross(r2, i, mid[i], t, p2)
        if c1 and c2:
            (q1, p1), (q2, p2) = c1, c2
            o1.append(q1); o2.append(q2)
        else:
            o1.append(r1[i]); o2.append(r2[i])        # no clean crossing: keep the arc-fraction partner; the monotone bound only follows real crossings
    o1.append(r1[-1]); o2.append(r2[-1])
    return o1, o2


def _resample_closed(ring: Sequence[Point], n: int) -> List[Point]:
    pts = [tuple(p) for p in ring]
    if dist(pts[0], pts[-1]) > 1e-9:
        pts.append(pts[0])
    return resample_n(pts, n)[:-1]


def column_from_outline(ring: Sequence[Point], rail_points: int = 0) -> dict:
    """Returns {rail1, rail2, length_mm, width_mm, aspect}. Raises ValueError when the shape is not suitable."""
    if len(ring) < 3:
        raise ValueError("outline needs at least 3 points")
    if abs(_signed_area(list(ring))) < 1.0:
        raise ValueError("outline is too small")
    N = 240
    P = _resample_closed(ring, N)
    cx, cy = sum(p[0] for p in P) / N, sum(p[1] for p in P) / N
    sxx = sum((p[0] - cx) ** 2 for p in P); syy = sum((p[1] - cy) ** 2 for p in P); sxy = sum((p[0] - cx) * (p[1] - cy) for p in P)
    th = 0.5 * math.atan2(2 * sxy, sxx - syy)                 # major-axis angle
    ux, uy = math.cos(th), math.sin(th)
    proj = [((p[0] - cx) * ux + (p[1] - cy) * uy, -(p[0] - cx) * uy + (p[1] - cy) * ux) for p in P]   # (along, across)
    lo, hi = min(a for a, _ in proj), max(a for a, _ in proj)
    length = hi - lo
    across = max(b for _, b in proj) - min(b for _, b in proj)
    if across < 1e-6 or length / across < MIN_ASPECT:
        raise ValueError(f"shape is not elongated enough for a satin column (length/width = {length / max(across, 1e-6):.1f}, need >= {MIN_ASPECT}); use a fill")

    # Ends: search the outline points near each extreme of the major axis and keep the split whose arc-fraction-paired
    # points are closest overall (= the cleanest column). Picking the single extreme point fails on diagonal end caps.
    def near(extreme: float) -> List[int]:
        c = [i for i, (a_, _) in enumerate(proj) if abs(a_ - extreme) <= 0.12 * length]
        return c[::max(1, len(c) // 24)] or [min(range(N), key=lambda i: abs(proj[i][0] - extreme))]

    def chains(ia: int, ib: int):
        return ([P[(ia + k) % N] for k in range(((ib - ia) % N) + 1)], [P[(ia - k) % N] for k in range(((ia - ib) % N) + 1)])

    def cost(ia: int, ib: int) -> float:
        c1, c2 = chains(ia, ib)
        if min(len(c1), len(c2)) < 4:
            return 1e18
        S = 24
        return sum(dist(c1[round(f * (len(c1) - 1) / S)], c2[round(f * (len(c2) - 1) / S)]) for f in range(1, S)) / (S - 1)

    best = None
    for ia_ in near(lo):
        for ib_ in near(hi):
            if ia_ != ib_:
                c = cost(ia_, ib_)
                if best is None or c < best[0]:
                    best = (c, ia_, ib_)
    if best is None:
        raise ValueError("could not separate the two ends of the shape")
    ia, ib = best[1], best[2]
    chain1 = [P[(ia + k) % N] for k in range(((ib - ia) % N) + 1)]
    chain2 = [P[(ia - k) % N] for k in range(((ia - ib) % N) + 1)]        # the other way round, also A -> B
    if min(len(chain1), len(chain2)) < 4:
        raise ValueError("outline is too coarse to split into rails")
    n = rail_points or max(8, min(40, int(max(polyline_length(chain1), polyline_length(chain2)) / 1.5)))
    r1, r2 = resample_n(chain1, n), resample_n(chain2, n)
    r1[0] = r2[0] = chain1[0]; r1[-1] = r2[-1] = chain1[-1]               # rails share the exact tip points
    q1, q2 = _perpendicular_pairs(r1, r2)
    if not _any_cross(q1, q2):          # all-or-nothing: a partly refined column can fold, so only accept a clean result
        r1, r2 = q1, q2
    width = sum(dist(a, b) for a, b in zip(r1[1:-1], r2[1:-1])) / max(1, n - 1)
    # The real criterion for a usable column: stitch lines (r1[i] -> r2[i]) must not cross each other, and must stay
    # inside the source shape. Curved strokes (banana, S) pass; branching / folded shapes fail.
    lines = list(zip(r1[1:-1], r2[1:-1]))
    if _any_cross(r1, r2):
        raise ValueError("shape curls or branches too much for one column (stitch lines would cross); split it into several columns")
    mids = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in lines]
    outside = sum(1 for m in mids if not _inside_or_on(m, P))
    if lines and outside / len(lines) > 0.08:
        raise ValueError("a satin column would leave the shape (shape is too concave); split it into several columns")
    rd = lambda pts: [[round(x, 3), round(y, 3)] for x, y in pts]
    return {"rail1": rd(r1), "rail2": rd(r2), "length_mm": round(length, 2), "width_mm": round(width, 2), "aspect": round(length / across, 2)}
