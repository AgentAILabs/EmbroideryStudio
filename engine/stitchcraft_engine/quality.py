"""Stitch-quality engine: geometry validation (before stitching) and a transparent 8-category quality score (after).

IMPORTANT WORDING RULE: everything here is SOFTWARE validation of the design and the generated stitch plan.
It is not a prediction of how the design will stitch on a machine. The score never claims physical reliability.

validate_geometry(design)  -> [issue]        issue = {code, severity, object, message, advice, fixable}
quality_report(design, pattern, notes=None) -> {score, categories[8], issues, checks, disclaimer}
"""
from __future__ import annotations
import math
from typing import Dict, List, Optional, Sequence, Tuple

from .geometry import point_in_ring, polygon_area, ring_self_intersections
from .model import Cmd, Pattern

DISCLAIMER = ("Software validation only. This score describes the design and the generated stitch plan; "
              "it is not a prediction of stitch-out quality on any machine, fabric or thread.")
MIN_AREA_MM2 = 0.05          # below this a ring has no usable area
TINY_AREA_MM2 = 1.0          # below this a fill is a speck that will stitch as a knot
CATEGORIES = [("geometry", "Geometry"), ("stitch_length", "Stitch length"), ("density", "Density"), ("underlay", "Underlay"),
              ("path", "Path optimisation"), ("jump_trim", "Jumps and trims"), ("hoop", "Hoop fit"), ("dst_format", "DST format")]


def _issue(code, severity, obj, message, advice="", fixable=False):
    return {"code": code, "severity": severity, "object": obj, "message": message, "advice": advice, "fixable": fixable}


def _finite_pts(v) -> Optional[List[Tuple[float, float]]]:
    try:
        pts = [(float(p[0]), float(p[1])) for p in v]
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return pts if all(math.isfinite(a) and math.isfinite(b) for a, b in pts) else None


def _seg_cross(a, b, c, d) -> bool:
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return o(c, d, a) * o(c, d, b) < -1e-12 and o(a, b, c) * o(a, b, d) < -1e-12


def _rings_cross(r1, r2) -> bool:
    for i in range(len(r1)):
        a, b = r1[i], r1[(i + 1) % len(r1)]
        for j in range(len(r2)):
            if _seg_cross(a, b, r2[j], r2[(j + 1) % len(r2)]):
                return True
    return False


def _same_ring(a, b) -> bool:
    if len(a) != len(b):
        return False
    sa, sb = sorted(a), sorted(b)
    return all(abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6 for p, q in zip(sa, sb))


def _polylines_cross(a, b) -> bool:
    return any(_seg_cross(a[i], a[i + 1], b[j], b[j + 1]) for i in range(len(a) - 1) for j in range(len(b) - 1))


# ---------------------------------------------------------------- geometry
def validate_geometry(design: dict) -> List[dict]:
    """Structural checks that stop a design from stitching wrongly. Errors block export; warnings do not."""
    out: List[dict] = []
    for ob in design.get("objects", []):
        oid, typ = str(ob.get("id")), ob.get("type")
        if typ == "fill":
            out += _fill_geometry(oid, ob)
        elif typ == "column":
            r1, r2 = _finite_pts(ob.get("rail1", [])), _finite_pts(ob.get("rail2", []))
            if r1 is None or r2 is None:
                out.append(_issue("GEO_NON_FINITE", "error", oid, "A column rail has a missing or non-numeric coordinate.", "Redraw the column.")); continue
            if len(r1) < 2 or len(r2) < 2:
                out.append(_issue("GEO_TOO_FEW_POINTS", "error", oid, "A satin column needs at least 2 points on each rail.", "Add points to both rails.")); continue
            if _polylines_cross(r1, r2):
                out.append(_issue("GEO_RAIL_CROSS", "error", oid, "The two rails of this satin column cross each other, so the stitches fold over.",
                                  "Redraw the rails so they do not cross, or split the column in two."))
        elif typ in ("satin", "run"):
            pts = _finite_pts(ob.get("points", []))
            if pts is None:
                out.append(_issue("GEO_NON_FINITE", "error", oid, "A point has a missing or non-numeric coordinate.", "Redraw the object.")); continue
            if len(pts) < 2:
                out.append(_issue("GEO_TOO_FEW_POINTS", "error", oid, f"A {typ} needs at least 2 points.", "Add a second point or delete the object.")); continue
            if all(abs(p[0] - pts[0][0]) < 1e-9 and abs(p[1] - pts[0][1]) < 1e-9 for p in pts):
                out.append(_issue("GEO_ZERO_LENGTH", "error", oid, f"All points of this {typ} are in the same place.", "Delete it or move a point.")); continue
            if typ == "satin" and not ob.get("closed") and _self_crossing_path(pts):
                out.append(_issue("GEO_SATIN_SELF_CROSS", "warning", oid, "The centre line of this satin crosses itself; the columns will overlap there.", "Split it into two satins."))
    return out


def _self_crossing_path(pts) -> bool:
    for i in range(len(pts) - 1):
        for j in range(i + 2, len(pts) - 1):
            if _seg_cross(pts[i], pts[i + 1], pts[j], pts[j + 1]):
                return True
    return False


def _fill_geometry(oid, ob) -> List[dict]:
    out: List[dict] = []
    raw = ob.get("rings")
    if not isinstance(raw, list) or not raw:
        return [_issue("GEO_TOO_FEW_POINTS", "error", oid, "This fill has no outline.", "Draw the outline again.")]
    rings, keep = [], []
    for k, r in enumerate(raw):
        pts = _finite_pts(r)
        if pts is None:
            out.append(_issue("GEO_NON_FINITE", "error", oid, f"Outline {k + 1} has a missing or non-numeric coordinate.", "Redraw the shape.")); continue
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            out.append(_issue("GEO_TOO_FEW_POINTS", "error", oid, f"Outline {k + 1} has fewer than 3 points.", "Add points or delete the ring.", True)); continue
        if abs(polygon_area(pts)) < MIN_AREA_MM2:
            out.append(_issue("GEO_ZERO_AREA", "error", oid, f"Outline {k + 1} has no area (its points are in a line or the same place).", "Delete the ring.", True)); continue
        rings.append(pts); keep.append(k)
    seen: List[int] = []
    for a in range(len(rings)):                              # duplicate rings cancel each other under the even-odd rule -> a hole appears
        if any(_same_ring(rings[a], rings[b]) for b in seen):
            out.append(_issue("GEO_DUPLICATE_RING", "error", oid, f"Outline {keep[a] + 1} is an exact copy of another outline. Two identical outlines cancel out and leave a hole.",
                              "Remove the duplicate outline.", True))
        else:
            seen.append(a)
    uniq = [rings[a] for a in seen]
    for a, r in zip(seen, uniq):
        if ring_self_intersections(r):
            out.append(_issue("GEO_SELF_INTERSECT", "error", oid, f"Outline {keep[a] + 1} crosses itself, so the fill would overlap or leave gaps.", "Redraw it as a simple shape (use Auto-fix or Weld)."))
    for i in range(len(uniq)):
        for j in range(i + 1, len(uniq)):
            if _rings_cross(uniq[i], uniq[j]):
                out.append(_issue("GEO_RING_CROSS", "error", oid, f"Outlines {keep[seen[i]] + 1} and {keep[seen[j]] + 1} cross each other (a hole that touches or crosses the outline).",
                                  "Move the hole fully inside the outline, or merge the shapes."))
    # hierarchy via containment depth (even-odd): depth 1 = hole, depth 2 = island inside a hole
    if len(uniq) > 1:
        for i, r in enumerate(uniq):
            probe = r[0]
            depth = sum(1 for j, o in enumerate(uniq) if j != i and point_in_ring(probe, o) and abs(polygon_area(o)) > abs(polygon_area(r)))
            if depth >= 2:
                out.append(_issue("GEO_HOLE_IN_HOLE", "warning", oid, f"Outline {keep[seen[i]] + 1} sits inside a hole, so it will stitch as a separate island.", "Check that this is intended."))
            elif depth == 0 and i != 0 and not point_in_ring(uniq[0][0], r) and not point_in_ring(probe, uniq[0]):
                out.append(_issue("GEO_DISJOINT_RING", "warning", oid, f"Outline {keep[seen[i]] + 1} lies outside the first outline; it will stitch as a separate piece, not a hole.",
                                  "If it should be a hole, move it inside the first outline."))
    total = sum(abs(polygon_area(r)) for r in uniq)
    if uniq and total < TINY_AREA_MM2:
        out.append(_issue("GEO_TINY", "warning", oid, f"This fill is only {total:.2f} mm2 - it will stitch as a knot.", "Delete it or make it a running stitch or a bead."))
    return out


# ---------------------------------------------------------------- runtime checks on the generated stitch plan
def _seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    d2 = dx * dx + dy * dy
    t = 0.0 if d2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / d2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _dist_to_rings(p, rings) -> float:
    return min(_seg_dist(p, r[i], r[(i + 1) % len(r)]) for r in rings for i in range(len(r)))


def _object_points(pattern: Pattern) -> Dict[str, List[Tuple[float, float]]]:
    by: Dict[str, List[Tuple[float, float]]] = {}
    for s in pattern.stitches:
        if s.cmd == Cmd.STITCH and s.object_id:
            by.setdefault(s.object_id, []).append((s.x, s.y))
    return by


def boundary_check(design: dict, pattern: Pattern, max_points: int = 4000) -> dict:
    """Stitches that land outside the object they belong to (beyond compensation tolerance). Returns {checked, outside, issues}."""
    by = _object_points(pattern)
    issues, checked, outside = [], 0, 0
    for ob in design.get("objects", []):
        oid = str(ob.get("id")); pts = by.get(oid)
        if not pts or ob.get("type") not in ("fill", "satin", "column"):
            continue
        prm = ob.get("params", {})
        tol = 1.2 + abs(float(prm.get("pull_comp", 0) or 0)) + abs(float(prm.get("push_comp", 0) or 0)) + float(prm.get("overlap_mm", 0) or 0)
        step = max(1, len(pts) // max_points); sample = pts[::step]
        bad = 0
        try:
            if ob["type"] == "fill":
                rings = [r[:-1] if len(r) > 1 and tuple(r[0]) == tuple(r[-1]) else r for r in (_finite_pts(r) or [] for r in ob["rings"])]
                rings = [r for r in rings if len(r) >= 3]
                if not rings:
                    continue
                if ob.get("smooth"):                                    # smoothing moves the outline; a looser tolerance avoids false alarms
                    tol += 1.0
                for p in sample:
                    if not (sum(point_in_ring(p, r) for r in rings) % 2) and _dist_to_rings(p, rings) > tol:
                        bad += 1
            elif ob["type"] == "satin":
                path = _finite_pts(ob.get("points", [])) or []
                if len(path) < 2:
                    continue
                half = float(prm.get("width", 3) or 3) / 2 + tol + (1.0 if ob.get("smooth") else 0)
                for p in sample:
                    if min(_seg_dist(p, path[i], path[i + 1]) for i in range(len(path) - 1)) > half:
                        bad += 1
            else:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        checked += len(sample); outside += bad
        if bad:
            issues.append(_issue("Q_OUTSIDE_BOUNDARY", "warning", oid, f"{bad} of {len(sample)} sampled stitches land outside this object by more than {tol:.1f} mm.",
                                 "Check overlap / compensation settings or the outline."))
    return {"checked": checked, "outside": outside, "issues": issues}


def coverage_check(design: dict, pattern: Pattern, max_cells: int = 90000, max_stitches: int = 200000) -> dict:
    """Raster check for unstitched gaps inside fills. A stitch 'covers' the cell it passes through and its 8 neighbours.
    Cells hidden under a later object are covered by that object's stitches, so overlap removal does not cause false gaps."""
    fills = [ob for ob in design.get("objects", []) if ob.get("type") == "fill" and ob.get("rings")]
    n_st = sum(1 for s in pattern.stitches if s.cmd == Cmd.STITCH)
    if not fills:
        return {"ran": True, "gap_fraction": 0.0, "cell_mm": None, "issues": [], "note": "no fills"}
    if n_st > max_stitches:
        return {"ran": False, "reason": f"design has {n_st} stitches (> {max_stitches}); coverage check skipped", "issues": []}
    rings_by: Dict[str, list] = {}
    xs0, ys0, xs1, ys1, area = 1e9, 1e9, -1e9, -1e9, 0.0
    for ob in fills:
        rs = [r for r in (_finite_pts(r) for r in ob["rings"]) if r and len(r) >= 3]
        if not rs:
            continue
        rings_by[str(ob["id"])] = rs
        for r in rs:
            for x, y in r:
                xs0, ys0, xs1, ys1 = min(xs0, x), min(ys0, y), max(xs1, x), max(ys1, y)
        area += abs(sum(polygon_area(r) for r in rs))
    if not rings_by:
        return {"ran": True, "gap_fraction": 0.0, "cell_mm": None, "issues": [], "note": "no valid fills"}
    cell = max(0.5, math.sqrt(max((xs1 - xs0) * (ys1 - ys0), 1.0) / max_cells))
    covered = set()
    prev = None
    for s in pattern.stitches:
        if s.cmd != Cmd.STITCH:
            prev = None; continue
        cur = (s.x, s.y)
        if prev is not None:
            n = max(1, int(math.hypot(cur[0] - prev[0], cur[1] - prev[1]) / (cell * 0.5)))
            for k in range(n + 1):
                x = prev[0] + (cur[0] - prev[0]) * k / n; y = prev[1] + (cur[1] - prev[1]) * k / n
                cx, cy = int(math.floor(x / cell)), int(math.floor(y / cell))
                for a in (-1, 0, 1):
                    for b in (-1, 0, 1):
                        covered.add((cx + a, cy + b))
        else:
            cx, cy = int(math.floor(cur[0] / cell)), int(math.floor(cur[1] / cell))
            covered.add((cx, cy))
        prev = cur
    issues, total_in, total_gap = [], 0, 0
    for ob in fills:
        oid = str(ob["id"]); rs = rings_by.get(oid)
        if not rs or (ob.get("params", {}).get("pattern") in ("contour", "cross")):
            continue                                                  # patterned fills are not row-based; a raster gap check would be misleading
        bx0 = min(p[0] for r in rs for p in r); bx1 = max(p[0] for r in rs for p in r)
        by0 = min(p[1] for r in rs for p in r); by1 = max(p[1] for r in rs for p in r)
        inside = gap = 0
        c = int(math.floor(bx0 / cell))
        while c * cell <= bx1:
            d = int(math.floor(by0 / cell))
            while d * cell <= by1:
                cx_, cy_ = (c + 0.5) * cell, (d + 0.5) * cell
                if sum(point_in_ring((cx_, cy_), r) for r in rs) % 2 == 1:
                    # only interior cells: all four neighbours inside too, so edge pixels do not create false gaps
                    if all(sum(point_in_ring((cx_ + dx * cell, cy_ + dy * cell), r) for r in rs) % 2 == 1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                        inside += 1
                        if (c, d) not in covered:
                            gap += 1
                d += 1
            c += 1
        total_in += inside; total_gap += gap
        if inside and gap / inside > 0.03:
            issues.append(_issue("Q_COVERAGE_GAP", "warning", oid, f"About {100 * gap / inside:.0f}% of this fill's interior has no stitches within ~{cell * 1.5:.1f} mm (rows too far apart or the shape was cut away).",
                                 "Reduce the row spacing or check overlap removal."))
    return {"ran": True, "gap_fraction": (total_gap / total_in) if total_in else 0.0, "cell_mm": round(cell, 2), "interior_cells": total_in, "issues": issues}


# ---------------------------------------------------------------- score
def _clamp(v: float) -> int:
    return int(max(0, min(100, round(v))))


def quality_report(design: dict, pattern: Pattern, notes: Optional[List[str]] = None) -> dict:
    from .design import machine, run_checks, _p
    m = machine(design)
    geo = validate_geometry(design)
    rep = run_checks(design, pattern)
    bnd = boundary_check(design, pattern)
    cov = coverage_check(design, pattern)
    S = pattern.stitches
    cats: Dict[str, dict] = {}

    def cat(key, score, detail):
        cats[key] = {"id": key, "name": dict(CATEGORIES)[key], "score": _clamp(score), "detail": detail}

    # 1 geometry: errors -30, warnings -8 (floor 0) plus boundary/coverage warnings -6 each
    ge = [g for g in geo if g["severity"] == "error"]; gw = [g for g in geo if g["severity"] != "error"] + bnd["issues"] + cov["issues"]
    cat("geometry", 100 - 30 * len(ge) - 8 * len([g for g in geo if g["severity"] != "error"]) - 6 * (len(bnd["issues"]) + len(cov["issues"])),
        [f"{len(ge)} geometry error(s), {len(gw)} warning(s)", f"boundary check: {bnd['outside']} of {bnd['checked']} sampled stitches outside their object",
         ("coverage check: " + (f"{100 * cov['gap_fraction']:.1f}% of fill interior unstitched (grid {cov.get('cell_mm')} mm)" if cov.get("ran") else cov.get("reason", "not run")))])
    # 2 stitch length: each 1% of out-of-range stitches costs 10 points
    lens = []
    prev = None
    for s in S:
        if s.cmd == Cmd.STITCH and prev is not None:
            lens.append(math.hypot(s.x - prev[0], s.y - prev[1]))
        prev = (s.x, s.y) if s.cmd in (Cmd.STITCH, Cmd.JUMP) else None
    bad_len = sum(1 for d in lens if d > m["max_stitch"] + 1e-6 or d < m["min_stitch"] - 1e-6)
    frac = bad_len / len(lens) if lens else 0.0
    cat("stitch_length", 100 - 1000 * frac, [f"{bad_len} of {len(lens)} stitches outside {m['min_stitch']:g}-{m['max_stitch']:g} mm (each 1% costs 10 points)"])
    # 3 density: 1 mm grid, penetrations above the limit
    from .design import THREADS
    k = THREADS.get(design.get("thread") or "40wt", THREADS["40wt"])["k"]
    limit = round(16.0 / k, 1)
    grid: Dict[Tuple[int, int], int] = {}
    for s in S:
        if s.cmd == Cmd.STITCH:
            key = (int(math.floor(s.x)), int(math.floor(s.y))); grid[key] = grid.get(key, 0) + 1
    over = sum(1 for v in grid.values() if v > limit)
    f2 = over / len(grid) if grid else 0.0
    cat("density", 100 - 500 * f2, [f"{over} of {len(grid)} occupied 1 mm cells exceed {limit:g} penetrations/mm2 (each 1% of cells costs 5 points)"])
    # 4 underlay (advisory): share of large fills / wide satins that have no underlay
    miss, elig = [], 0
    for ob in design.get("objects", []):
        try:
            if ob.get("type") == "fill" and _p(ob, "pattern") not in ("contour", "cross"):
                if sum(abs(polygon_area(r)) for r in (_finite_pts(r) for r in ob.get("rings", [])) if r) >= 25:
                    elig += 1
                    if _p(ob, "underlay") in ("none", False, None): miss.append(str(ob["id"]))
            elif ob.get("type") in ("satin", "column") and _p(ob, "style") != "zigzag" and float(_p(ob, "width") or 3) >= 2.5:
                elig += 1
                if _p(ob, "underlay") in ("none", False, None): miss.append(str(ob["id"]))
        except (TypeError, ValueError, KeyError):
            pass
    cat("underlay", 100 * (1 - len(miss) / elig) if elig else 100,
        [f"{len(miss)} of {elig} large fill/wide satin object(s) have no underlay (advisory; depends on fabric): " + ", ".join(miss[:6])] if miss else [f"all {elig} large fills / wide satins have underlay"])
    # 5 path: jump length relative to stitched length
    jl = sl = 0.0
    prev = None
    for s in S:
        if s.cmd in (Cmd.STITCH, Cmd.JUMP):
            if prev is not None:
                d = math.hypot(s.x - prev[0], s.y - prev[1])
                if s.cmd == Cmd.JUMP: jl += d
                else: sl += d
            prev = (s.x, s.y)
        elif s.cmd == Cmd.COLOR_CHANGE:
            pass
    ratio = jl / (sl + 1.0)
    cat("path", 100 * (1 - min(1.0, ratio * 2)), [f"travel {jl:.0f} mm of jumps vs {sl:.0f} mm stitched (ratio {ratio:.2f}; ratio 0.5 scores 0)"])
    # 6 jumps/trims: long jump carried without a trim (-10 each); needless trim of a tiny jump (-2 each)
    long_untrimmed = tiny_trim = 0
    for i, s in enumerate(S):
        if s.cmd == Cmd.JUMP and i > 0:
            j = i - 1
            while j >= 0 and S[j].cmd not in (Cmd.STITCH, Cmd.JUMP, Cmd.TRIM, Cmd.COLOR_CHANGE):
                j -= 1
            if j >= 0 and S[j].cmd in (Cmd.STITCH, Cmd.JUMP):
                d = math.hypot(s.x - S[j].x, s.y - S[j].y)
                trimmed = i >= 1 and S[i - 1].cmd == Cmd.TRIM
                if d > m["trim_distance"] + 1e-6 and not trimmed and S[j].cmd == Cmd.STITCH:
                    long_untrimmed += 1
        if s.cmd == Cmd.TRIM and i + 1 < len(S) and S[i + 1].cmd == Cmd.JUMP:
            pj = next((S[j] for j in range(i - 1, -1, -1) if S[j].cmd in (Cmd.STITCH, Cmd.JUMP)), None)
            if pj is not None and math.hypot(S[i + 1].x - pj.x, S[i + 1].y - pj.y) < 0.5 * m["trim_distance"]:
                tiny_trim += 1
    cat("jump_trim", 100 - 10 * long_untrimmed - 2 * tiny_trim, [f"{long_untrimmed} jump(s) longer than {m['trim_distance']:g} mm carried without a trim; {tiny_trim} trim(s) before a very short jump"])
    # 7 hoop
    hoop = design.get("hoop", {}); hw, hh, mg = float(hoop.get("w", 100)), float(hoop.get("h", 100)), float(hoop.get("margin", 3))
    bb = pattern.bbox()
    if bb is None:
        cat("hoop", 0, ["no stitches"])
    else:
        w, h = bb[2] - bb[0], bb[3] - bb[1]; fw, fh = hw - 2 * mg, hh - 2 * mg
        use = max(w / fw if fw > 0 else 9, h / fh if fh > 0 else 9)
        cat("hoop", 0 if use > 1 else 100 if use <= 0.95 else 85, [f"design {w:.1f} x {h:.1f} mm uses {100 * use:.0f}% of the usable hoop area {fw:.0f} x {fh:.0f} mm"])
    # 8 dst format
    codes = {i.code for i in rep.issues if i.severity == "error"}
    fmt_bad = codes & {"STITCH_TOO_LONG_DST", "NO_END", "MULTI_END", "THREAD_INDEX", "EMPTY"}
    cat("dst_format", 100 - 50 * len(fmt_bad), ["format rules satisfied (record movement <= 12.1 mm, one END, thread indices valid)" if not fmt_bad else "format problems: " + ", ".join(sorted(fmt_bad))])
    order = [k for k, _ in CATEGORIES]
    categories = [dict(cats[k], weight=1) for k in order]
    score = _clamp(sum(c["score"] for c in categories) / len(categories))
    issues = geo + bnd["issues"] + cov["issues"]
    return {"score": score, "scale": "0-100, unweighted mean of 8 categories; any geometry error also blocks export", "categories": categories, "issues": issues,
            "checks": {"boundary": {"checked": bnd["checked"], "outside": bnd["outside"]}, "coverage": {k: v for k, v in cov.items() if k != "issues"}},
            "blocking": bool(ge), "disclaimer": DISCLAIMER}
