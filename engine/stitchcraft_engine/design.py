"""Design document (editable objects) -> stitches. This is the contract the Studio UI edits.
All geometry in mm, y down. Object types:
  fill     rings=[[ [x,y],... ]]            tatami fill (even-odd holes)
  satin    points=[[x,y],...]               satin column along a centre line, params.width
  run      points=[[x,y],...]               running stitch (closed=true to loop)
  text     text, height, x, y               single-stroke satin lettering
  applique rings=[[...]]                    placement line + tack-down + satin cover border
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .builder import StitchObject, build_pattern
from .font import layout_text
from .geometry import polygon_area, smooth, inset_ring, rotate_closed, ring_self_intersections, trim_polyline
from .model import Cmd, Pattern, ThreadColor
from .stitches import (DigitizingError, satin_from_rails, contour_fill, cross_fill, center_walk_underlay, edge_walk_underlay, running_stitch,
                       satin_stitch, tatami_fill, underlay_path, zigzag_underlay, rails_from_centerline)
from .validate import validate

DEFAULTS = {
    "fill": {"angle": 45.0, "spacing": 0.4, "stitch_len": 3.5, "underlay": "tatami", "pull_comp": 0.2, "pattern": "tatami", "cross_size": 2.0,
             "regions": True, "cut_hidden": False, "overlap_mm": 0.6, "push_comp": 0.0},          # stitch holes / U-shapes region by region instead of jumping the gap on every row
    "satin": {"width": 3.0, "spacing": 0.4, "underlay": "auto", "pull_comp": 0.2, "push_comp": 0.0, "style": "satin"},
    "run": {"stitch_len": 2.5},
    "column": {"spacing": 0.4, "underlay": "auto", "pull_comp": 0.2, "push_comp": 0.0, "style": "satin"},
    "text": {"spacing": 1.0, "underlay": "auto", "pull_comp": 0.1},
    "applique": {"width": 2.5, "spacing": 0.4, "stitch_len": 2.5, "cover_color": None},
}
FABRICS = {  # unverified starting points; flagged as such in the UI until stitch-tested
    "cotton": {"pull_comp": 0.2, "spacing": 0.40}, "silk": {"pull_comp": 0.3, "spacing": 0.45},
    "georgette": {"pull_comp": 0.35, "spacing": 0.45}, "velvet": {"pull_comp": 0.4, "spacing": 0.38},
    "denim": {"pull_comp": 0.1, "spacing": 0.40}, "knit": {"pull_comp": 0.4, "spacing": 0.42},
}
# Thread-weight presets. `spacing` is the stitch-line spacing in mm (a satin advances this far per stitch); a line of thread covers
# about its own diameter, so finer thread needs closer lines: 40 wt (~0.35-0.4 mm) -> 0.40, 60 wt -> 0.30, 120/2 (~0.2 mm) -> 0.22.
# Derived from measuring 20 commercial blouse-work DST files (median 0.21 mm advance, 1.0 mm tie-in) - see docs/dst-analysis.md.
THREADS = {
    "40wt":  {"label": "40 wt (standard)", "k": 1.0,  "lock_len": None},
    "60wt":  {"label": "60 wt (fine)",     "k": 0.75, "lock_len": 0.8},
    "120":   {"label": "120/2 (blouse / zari-fine)", "k": 0.55, "lock_len": 1.0},
}
MIN_SPACING = 0.18
SPM = 700.0           # assumed machine speed, stitches per minute
COLOR_CHANGE_S, TRIM_S = 20.0, 6.0


def _p(obj: dict, key: str):
    return obj.get("params", {}).get(key, DEFAULTS.get(obj["type"], {}).get(key))


def _pts(v, ob: Optional[dict] = None, closed: bool = False) -> list:
    pts = [(float(a), float(b)) for a, b in v]
    return smooth(pts, closed) if ob and ob.get("smooth") else pts


def _covering_shapes(objs, idx):
    """Outlines of the stitched objects sewn AFTER objs[idx] (they lie on top of it): fills / appliqué as their rings,
    columns as rail1 + reversed rail2, satins as their stitched band."""
    out = []
    for o in objs[idx + 1:]:
        if o.get("hidden") or o.get("guide") or o.get("type") in ("embellishment", "run", "text"):
            continue
        try:
            if o["type"] in ("fill", "applique"):
                out.append([[(float(a), float(b)) for a, b in r] for r in o["rings"]])
            elif o["type"] == "column":
                out.append([[(float(a), float(b)) for a, b in o["rail1"]] + [(float(a), float(b)) for a, b in o["rail2"]][::-1]])
            elif o["type"] == "satin" and not o.get("closed"):
                l, r = rails_from_centerline([(float(a), float(b)) for a, b in o["points"]], float(_p(o, "width")))
                out.append([l + r[::-1]])
        except (KeyError, TypeError, ValueError, DigitizingError):
            continue
    return out


UNDERLAYS = ("auto", "none", "center", "edge", "zigzag", "edge+zigzag")


def _satin_objs(oid, th, path, width, spacing, pull, underlay, split=0.0, shorten=False):
    if underlay == "auto":
        underlay = "center" if width >= 2.0 else "none"
    under = []
    if underlay == "center":
        under = [center_walk_underlay(path)]
    elif underlay in ("edge", "edge+zigzag") and width > 1.0:
        under = [edge_walk_underlay(path, width)]
    if underlay in ("zigzag", "edge+zigzag") and width > 2.0:
        l, r = rails_from_centerline(path, width)
        under.append(zigzag_underlay(l, r))
    return StitchObject(oid, "satin", th, [satin_stitch(path, width, spacing, pull, split, shorten)], under)


def _column(oid, th, r1, r2, spacing, pull, underlay, notes, split=0.0, shorten=False):
    """Two-rail satin: stitches zig-zag between the rails. Rails are resampled by arc length, so
    unequal rail lengths simply stretch the stitch angle. pull_comp pushes each rail outwards."""
    from .geometry import dist, polyline_length, resample_n
    if len(r1) < 2 or len(r2) < 2:
        raise DigitizingError("column needs two rails with at least 2 points each")
    if dist(r1[0], r2[0]) + dist(r1[-1], r2[-1]) > dist(r1[0], r2[-1]) + dist(r1[-1], r2[0]):
        r2 = r2[::-1]                       # rails drawn in opposite directions: flip the second
        notes.append(f"{oid}: second rail direction reversed to match the first")
    n = max(2, int(max(polyline_length(r1), polyline_length(r2)) / 0.5))
    a, b = resample_n(r1, n), resample_n(r2, n)
    width = sum(dist(p, q) for p, q in zip(a, b)) / len(a)
    if width < 1.0:
        notes.append(f"{oid}: column is very narrow ({width:.1f} mm)")
    elif width > split > 0:
        notes.append(f"{oid}: column averages {width:.1f} mm wide - long stitches were split automatically")
    elif width > 7.0 and not split:
        notes.append(f"{oid}: column averages {width:.1f} mm wide - loose satin, enable auto-split or use a fill")
    if pull:
        a, b = [(p[0] + (p[0] - q[0]) / max(dist(p, q), 1e-9) * pull / 2, p[1] + (p[1] - q[1]) / max(dist(p, q), 1e-9) * pull / 2) for p, q in zip(a, b)], \
               [(q[0] + (q[0] - p[0]) / max(dist(p, q), 1e-9) * pull / 2, q[1] + (q[1] - p[1]) / max(dist(p, q), 1e-9) * pull / 2) for p, q in zip(a, b)]
    mid = [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in zip(a, b)]
    if underlay == "auto":
        underlay = "center" if width >= 2.0 else "none"
    under = [center_walk_underlay(underlay_path(mid))] if underlay == "center" else \
            [running_stitch(underlay_path(a), 2.5), running_stitch(underlay_path(b[::-1]), 2.5)] if underlay in ("edge", "edge+zigzag") else []
    if underlay in ("zigzag", "edge+zigzag") and width > 2.0:
        under.append(zigzag_underlay(a, b))
    return StitchObject(oid, "satin", th, [satin_from_rails(a, b, spacing, split, shorten)], under)


MACHINE_DEFAULTS = {"max_stitch": 7.0, "min_stitch": 0.3, "trim_distance": 3.0, "trim_jumps": 3,
                    "lock_len": 1.0,              # tie-in / tie-off stitch length in mm (0 = no lock stitches); production files use 1.0 mm
                    "trim_at_color_change": 1, "trim_at_end": 1,
                    "smart_direction": 1}         # start a run at its nearer end when that turns a trim into a carried jump


def machine(design: dict) -> dict:
    m = dict(MACHINE_DEFAULTS)
    for k, v in (design.get("machine") or {}).items():
        if k in m and isinstance(v, (int, float)) and not isinstance(v, bool):
            m[k] = v
    m["max_stitch"] = min(max(m["max_stitch"], 1.0), 12.1)
    m["trim_distance"] = max(m["trim_distance"], 0.5)
    m["trim_jumps"] = int(min(max(m["trim_jumps"], 1), 6))
    m["lock_len"] = 0.0 if m["lock_len"] <= 0 else min(max(m["lock_len"], 0.4), 1.5)      # a lock shorter than 0.4 mm is useless
    m["trim_at_color_change"] = 1 if m["trim_at_color_change"] else 0
    m["trim_at_end"] = 1 if m["trim_at_end"] else 0
    m["smart_direction"] = 1 if m["smart_direction"] else 0
    return m


def generate(design: dict, trim_distance: Optional[float] = None):
    """Returns (pattern, notes, stats). Raises ValueError when nothing can be generated."""
    if trim_distance is None:
        trim_distance = machine(design)["trim_distance"]
    threads: List[ThreadColor] = []

    import re as _re

    def tid(hexc: str) -> int:
        h = hexc.strip() if isinstance(hexc, str) else None
        if h is not None and _re.fullmatch(r"#[0-9a-fA-F]{3}", h):
            h = "#" + "".join(c * 2 for c in h[1:])                      # #f00 -> #ff0000
        if h is None or not _re.fullmatch(r"#[0-9a-fA-F]{6}", h):
            if hexc is not None:
                notes.append(f"invalid colour {str(hexc)[:20]!r} replaced by black")
            h = "#000000"
        hexc = h.lower()
        for i, t in enumerate(threads):
            if t.hex == hexc:
                return i
        threads.append(ThreadColor(f"Thread {len(threads) + 1}", hexc))
        return len(threads) - 1

    objs: List[StitchObject] = []
    notes: List[str] = []
    mach = machine(design)
    th = THREADS.get(design.get("thread") or "40wt")
    if th is None:
        raise ValueError("unknown thread preset %r (use %s)" % (design.get("thread"), ", ".join(THREADS)))
    if th["k"] != 1.0:                                   # closer stitch lines for finer thread, unless an object sets its own
        design = dict(design, objects=[
            dict(ob, params=dict(ob.get("params") or {}, spacing=max(MIN_SPACING, round(DEFAULTS[ob["type"]]["spacing"] * th["k"], 3))))
            if ob.get("type") in ("fill", "satin", "column", "applique") and "spacing" not in (ob.get("params") or {}) else ob
            for ob in design.get("objects", [])])
    if th["lock_len"] and "lock_len" not in (design.get("machine") or {}):
        mach["lock_len"] = th["lock_len"]
    split_of = lambda ob: (mach["max_stitch"] if ob.get("params", {}).get("auto_split", True) else 0.0)
    all_objs = design.get("objects", [])
    for idx, ob in enumerate(all_objs):
        if ob.get("hidden") or ob.get("guide") or ob.get("type") == "embellishment":
            continue          # guides and embellishment placeholders are never stitched (they go on the production sheet)
        oid, typ = str(ob["id"]), ob["type"]
        try:
            th = tid(ob.get("color"))
            if typ == "fill":
                rings = [_pts(r, ob, True) for r in ob["rings"]]
                bad = [k for k, r in enumerate(rings) if ring_self_intersections(r)]
                if bad:
                    notes.append(f"{oid}: outline crosses itself - the fill will overlap or leave gaps; redraw it as a simple shape")
                pattern_kind = _p(ob, "pattern")
                runs = None
                if pattern_kind == "contour":
                    try:
                        runs = contour_fill(rings, _p(ob, "spacing"), _p(ob, "stitch_len"))
                    except DigitizingError as e:
                        notes.append(f"{oid}: contour fill not possible ({e}); used tatami instead")
                elif pattern_kind == "cross":
                    runs = cross_fill(rings, float(_p(ob, "cross_size")))
                if runs is not None:
                    objs.append(StitchObject(oid, "fill", th, runs, []))      # patterned fills carry no underlay
                    continue
                cover = _covering_shapes(all_objs, idx) if _p(ob, "cut_hidden") else []
                ov = float(_p(ob, "overlap_mm") or 0.6)
                runs = tatami_fill(rings, _p(ob, "angle"), _p(ob, "spacing"), _p(ob, "stitch_len"),
                                   pull_comp=_p(ob, "pull_comp") or 0.0, regions=bool(_p(ob, "regions")),
                                   exclude=cover, exclude_margin=ov, push_comp=float(_p(ob, "push_comp") or 0.0))
                under = []
                mode = _p(ob, "underlay")
                mode = "tatami" if mode is True else "none" if mode in (False, None) else mode
                if mode != "none" and sum(polygon_area(r) for r in rings) >= 25:
                    if mode in ("edge", "edge+tatami"):
                        edge = [inset_ring(r, 0.5) for r in rings]
                        if all(edge):
                            under += [running_stitch(e, 2.5, closed=True) for e in edge]
                        else:
                            notes.append(f"{oid}: edge underlay skipped (shape too small or too complex to inset safely)")
                    if mode in ("tatami", "edge+tatami") or (mode == "edge" and not under):
                        under += tatami_fill(rings, _p(ob, "angle") + 90, 2.0, 3.0, regions=bool(_p(ob, "regions")),
                                            exclude=cover, exclude_margin=ov + 0.4)
                objs.append(StitchObject(oid, "fill", th, runs, under))
            elif typ == "satin":
                w = _p(ob, "width")
                if w < 1.0:
                    notes.append(f"{oid}: satin {w:g} mm is too narrow (< 1 mm); use a running stitch")
                elif w > split_of(ob) > 0:
                    notes.append(f"{oid}: satin {w:g} mm is wider than the max stitch - long stitches split automatically")
                elif w > 7.0:
                    notes.append(f"{oid}: satin {w:g} mm is loose (> 7 mm); enable auto-split, narrow it, or use a fill")
                path = _pts(ob["points"], ob, bool(ob.get("closed")))
                push = float(_p(ob, "push_comp") or 0.0)
                if push > 0 and not ob.get("closed"):
                    path = trim_polyline(path, push / 2, push / 2)
                zz = _p(ob, "style") == "zigzag"
                objs.append(_satin_objs(oid, th, path, _p(ob, "width"), max(_p(ob, "spacing"), 1.2) if zz else _p(ob, "spacing"),
                                        _p(ob, "pull_comp") or 0.0, "none" if zz else _p(ob, "underlay"), split_of(ob), bool(_p(ob, "shorten")) and not zz))
            elif typ == "column":
                r1, r2 = _pts(ob["rail1"], ob), _pts(ob["rail2"], ob)
                push = float(_p(ob, "push_comp") or 0.0)
                if push > 0:
                    r1, r2 = trim_polyline(r1, push / 2, push / 2), trim_polyline(r2, push / 2, push / 2)
                zz = _p(ob, "style") == "zigzag"
                objs.append(_column(oid, th, r1, r2, max(_p(ob, "spacing"), 1.2) if zz else _p(ob, "spacing"),
                                    _p(ob, "pull_comp") or 0.0, "none" if zz else _p(ob, "underlay"), notes, split_of(ob), bool(_p(ob, "shorten")) and not zz))
            elif typ == "run":
                pts = _pts(ob["points"], ob, bool(ob.get("closed")))
                objs.append(StitchObject(oid, "running", th,
                                         [running_stitch(pts, _p(ob, "stitch_len"), bool(ob.get("closed")))]))
            elif typ == "text":
                h = float(ob.get("height", 10))
                width = _p(ob, "width") or max(1.0, min(h * 0.16, 4.0))
                ox, oy = float(ob.get("x", 0)), float(ob.get("y", 0))
                for k, st in enumerate(layout_text(ob.get("text", ""), h, _p(ob, "spacing"))):
                    path = [(ox + a, oy + b) for a, b in st]
                    if len(path) == 2 and abs(path[0][0] - path[1][0]) + abs(path[0][1] - path[1][1]) < 0.5:
                        continue  # dots handled as tiny satin below
                    objs.append(_satin_objs(f"{oid}.{k}", th, path, width, 0.4, _p(ob, "pull_comp") or 0.0,
                                            _p(ob, "underlay"), split_of(ob)))
            elif typ == "applique":
                rings = [_pts(r, ob, True) for r in ob["rings"]]
                ring = rings[0] + [rings[0][0]]
                cover = tid(_p(ob, "cover_color") or ob.get("color"))
                place = tid("#9ca3af")
                sl = _p(ob, "stitch_len")
                # Three passes cut the thread at their start/end points: start each one a third of the way round the outline
                # from the previous so tie-in/tie-off stitches do not stack into one dense, needle-breaking spot.
                tack_ring, cover_ring = rotate_closed(ring, 1 / 3), rotate_closed(ring, 2 / 3)
                objs.append(StitchObject(oid + ".place", "running", place, [running_stitch(ring, sl)]))
                objs.append(StitchObject(oid + ".tack", "running", cover, [running_stitch(tack_ring, sl)]))
                objs.append(StitchObject(oid + ".cover", "satin", cover,
                                         [satin_stitch(cover_ring, _p(ob, "width"), _p(ob, "spacing"), 0.0)]))
                notes.append(f"{oid}: appliqué - machine stops at the placement->tack-down colour change; "
                             "place fabric then, trim after tack-down.")
            else:
                notes.append(f"{oid}: unknown type {typ!r} skipped")
        except (DigitizingError, KeyError, TypeError, ValueError) as e:
            notes.append(f"{oid}: skipped ({e})")
    notes += _order_notes(design)
    pattern = build_pattern(objs, threads, design.get("name", "design"), trim_distance, lock_len=mach["lock_len"],
                            trim_at_color_change=bool(mach["trim_at_color_change"]), trim_at_end=bool(mach["trim_at_end"]),
                            choose_direction=bool(mach["smart_direction"]))
    return pattern, notes, stats(pattern, design)


def empty_stats(design: Optional[dict] = None) -> dict:
    """Stats for a design with nothing to stitch (e.g. only embellishment placeholders / guides)."""
    base = stats(Pattern("empty", [], []), design)
    return base


def _bbox(ob: dict):
    pts = [p for r in ob.get("rings", []) for p in r] + list(ob.get("points", [])) + list(ob.get("rail1", [])) + list(ob.get("rail2", []))
    if ob.get("type") == "text":
        h = float(ob.get("height", 10)); pts = [(ob.get("x", 0), ob.get("y", 0)), (ob.get("x", 0) + max(2, len(ob.get("text", "")) * 0.9 * h), ob.get("y", 0) + h)]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _order_notes(design: dict) -> List[str]:
    """Rule C: underlay -> fill -> satin borders -> details. Warn when a satin/run/column/text is stitched BEFORE a
    fill it overlaps (the fill will bury it)."""
    objs = [o for o in design.get("objects", []) if not o.get("hidden") and not o.get("guide")]
    out = []
    for i, f in enumerate(objs):
        if f.get("type") != "fill":
            continue
        fb = _bbox(f)
        for e in objs[:i]:
            if e.get("type") not in ("satin", "run", "text"):      # outlines / lettering only: columns are body shapes (petals, feathers) that
                continue                                            # are legitimately covered by a later centre / stone fill
            eb = _bbox(e)
            if fb and eb and min(fb[2], eb[2]) > max(fb[0], eb[0]) and min(fb[3], eb[3]) > max(fb[1], eb[1]):
                out.append(f"{e['id']}: stitched before fill {f['id']} which overlaps it - the fill will cover it. Move it after the fill.")
    return out


def stats(p: Pattern, design: Optional[dict] = None) -> dict:
    c = p.counts()
    bb = p.bbox()
    per: Dict[int, int] = {}
    for s in p.stitches:
        if s.cmd == Cmd.STITCH:
            per[s.thread] = per.get(s.thread, 0) + 1
    seconds = c["stitch"] / SPM * 60 + c["color_change"] * COLOR_CHANGE_S + c["trim"] * TRIM_S
    sequence = []
    for i, s in enumerate(p.stitches):
        if s.cmd == Cmd.STITCH and (not sequence or sequence[-1][0] != s.thread):
            sequence.append([s.thread, 0])
        if s.cmd == Cmd.STITCH:
            sequence[-1][1] += 1
    emb: Dict[str, int] = {}
    for o in (design or {}).get("objects", []):
        if o.get("type") == "embellishment" and not o.get("hidden") and not o.get("guide"):
            emb[o.get("kind", "bead")] = emb.get(o.get("kind", "bead"), 0) + len(o.get("points", []))
    return {
        "lock_stitches": p.lock_stitches,
        "embellishments": emb,
        "fabric": (design or {}).get("fabric"), "thread": (design or {}).get("thread") or "40wt", "stabiliser": (design or {}).get("stabiliser"),
        "stitches": c["stitch"], "jumps": c["jump"], "trims": c["trim"], "color_changes": c["color_change"],
        "width_mm": round(bb[2] - bb[0], 2) if bb else 0, "height_mm": round(bb[3] - bb[1], 2) if bb else 0,
        "est_minutes": round(seconds / 60, 1), "assumed_spm": SPM,
        "threads": [{"hex": t.hex, "stitches": per.get(i, 0)} for i, t in enumerate(p.threads)],
        "color_sequence": [{"hex": p.threads[t].hex, "stitches": n} for t, n in sequence],
    }


def run_checks(design: dict, pattern: Pattern):
    hoop = design.get("hoop", {})
    m = machine(design)
    k = THREADS.get(design.get("thread") or "40wt", THREADS["40wt"])["k"]
    return validate(pattern, float(hoop.get("w", 100)), float(hoop.get("h", 100)), float(hoop.get("margin", 3)),
                    max_stitch=m["max_stitch"], min_stitch=m["min_stitch"], max_per_mm2=round(16.0 / k, 1))   # finer thread -> closer lines -> more penetrations per mm2
