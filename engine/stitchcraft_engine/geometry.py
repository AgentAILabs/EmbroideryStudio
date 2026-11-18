from __future__ import annotations
import math
from typing import List, Sequence, Tuple

Point = Tuple[float, float]


def dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def polyline_length(pts: Sequence[Point]) -> float:
    return sum(dist(a, b) for a, b in zip(pts, pts[1:]))


def resample_n(pts: Sequence[Point], n: int) -> List[Point]:
    """n equal arc-length segments -> n+1 points (endpoints preserved)."""
    if n < 1:
        raise ValueError("n must be >= 1")
    total = polyline_length(pts)
    if total < 1e-12:
        return [tuple(pts[0])] * (n + 1)
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + dist(a, b))
    out, seg = [], 0
    for k in range(n + 1):
        t = total * k / n
        while seg < len(pts) - 2 and cum[seg + 1] < t:
            seg += 1
        seglen = cum[seg + 1] - cum[seg]
        u = 0.0 if seglen < 1e-12 else (t - cum[seg]) / seglen
        a, b = pts[seg], pts[seg + 1]
        out.append((a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u))
    return out


def rotate(p: Point, ang: float) -> Point:
    c, s = math.cos(ang), math.sin(ang)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def point_in_ring(p: Point, ring: Sequence[Point]) -> bool:
    x, y = p
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def point_in_polygon(p: Point, rings: Sequence[Sequence[Point]]) -> bool:
    """Even-odd rule over all rings (outer boundaries and holes)."""
    return sum(point_in_ring(p, r) for r in rings) % 2 == 1


def polygon_area(ring: Sequence[Point]) -> float:
    return abs(sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1]
                   for i in range(len(ring)))) / 2


def smooth(pts: Sequence[Point], closed: bool = False, n: int = 8) -> List[Point]:
    """Catmull-Rom spline through the control points (curve mode). Passes through every point."""
    P = [tuple(p) for p in pts]
    if len(P) < 3:
        return P
    m = len(P)
    seg = m if closed else m - 1
    g = (lambda i: P[i % m]) if closed else (lambda i: P[max(0, min(m - 1, i))])
    out = [P[0]]
    for i in range(seg):
        p0, p1, p2, p3 = g(i - 1), g(i), g(i + 1), g(i + 2)
        for k in range(1, n + 1):
            t = k / n
            out.append(tuple(0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t + (-a + 3 * b - 3 * c + d) * t ** 3)
                             for a, b, c, d in zip(p0, p1, p2, p3)))
    return out[:-1] if closed else out
