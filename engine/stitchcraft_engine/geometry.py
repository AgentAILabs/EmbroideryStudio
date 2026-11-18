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


def _signed_area(r: Sequence[Point]) -> float:
    return sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r))) / 2


def inset_ring(ring: Sequence[Point], d: float, miter_limit: float = 2.5):
    """Move every edge of a closed ring inwards by d mm (miter joins). Pure-Python, for underlay only.
    Returns None when the result is not trustworthy (collapsed, self-folded, or outside the original),
    so callers fall back instead of stitching a bad path."""
    P = [tuple(p) for p in ring]
    if len(P) > 1 and P[0] == P[-1]:
        P = P[:-1]
    n = len(P)
    if n < 3 or d <= 0:
        return None
    a0 = _signed_area(P)
    if abs(a0) < 4 * d * d:
        return None
    sgn = 1.0 if a0 > 0 else -1.0
    out = []
    for i in range(n):
        p0, p1, p2 = P[i - 1], P[i], P[(i + 1) % n]
        e1, e2 = (p1[0] - p0[0], p1[1] - p0[1]), (p2[0] - p1[0], p2[1] - p1[1])
        l1, l2 = math.hypot(*e1), math.hypot(*e2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        # inward normals (interior on the left for positive area in y-up maths; sgn handles orientation)
        n1 = (-e1[1] / l1 * sgn, e1[0] / l1 * sgn)
        n2 = (-e2[1] / l2 * sgn, e2[0] / l2 * sgn)
        bx, by = n1[0] + n2[0], n1[1] + n2[1]
        dot = 1 + n1[0] * n2[0] + n1[1] * n2[1]          # = 2 cos^2(theta/2)
        if dot < 1e-6:
            return None
        out.append((p1[0] + bx * d / dot, p1[1] + by * d / dot))   # miter vertex
        if math.hypot(out[-1][0] - p1[0], out[-1][1] - p1[1]) > d * miter_limit:
            return None
    if len(out) < 3 or abs(_signed_area(out)) >= abs(a0) or (_signed_area(out) > 0) != (a0 > 0):
        return None
    if not all(point_in_ring(q, P) for q in out):
        return None
    return out


def rotate_closed(path: Sequence[Point], frac: float) -> List[Point]:
    """A closed path (first point repeated at the end) re-started at `frac` (0..1) of its perimeter. Same outline, new
    start/end point - used to stagger the thread cuts of layered passes so their lock stitches do not pile up."""
    pts = [tuple(p) for p in path]
    if len(pts) < 3 or dist(pts[0], pts[-1]) > 1e-9:
        return pts
    total = polyline_length(pts)
    frac = frac % 1.0
    if total < 1e-9 or frac < 1e-9:
        return pts
    target, acc = total * frac, 0.0
    for i in range(len(pts) - 1):
        seg = dist(pts[i], pts[i + 1])
        if acc + seg >= target:
            t = (target - acc) / seg if seg > 1e-12 else 0.0
            cut = (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t)
            body = pts[:-1]                                   # distinct points of the ring
            new = [cut] + body[i + 1:] + body[:i + 1] + [cut]
            return [q for k, q in enumerate(new) if k == 0 or dist(q, new[k - 1]) > 1e-9]
        acc += seg
    return pts


def ring_self_intersections(ring: Sequence[Point], limit: int = 3) -> int:
    """Number of proper crossings between non-adjacent edges of a closed ring (capped at `limit`). 0 = a simple polygon."""
    P = [tuple(p) for p in ring]
    if len(P) > 1 and P[0] == P[-1]:
        P = P[:-1]
    n = len(P)
    if n < 4:
        return 0

    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    found = 0
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue                                    # edges that share a vertex
            c, d = P[j], P[(j + 1) % n]
            d1, d2, d3, d4 = o(c, d, a), o(c, d, b), o(a, b, c), o(a, b, d)
            if d1 * d2 < -1e-12 and d3 * d4 < -1e-12:
                found += 1
                if found >= limit:
                    return found
    return found
