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
from .geometry import polygon_area, smooth, inset_ring
from .model import Cmd, Pattern, ThreadColor
from .stitches import (DigitizingError, satin_from_rails, center_walk_underlay, edge_walk_underlay, running_stitch,
                       satin_stitch, tatami_fill)
from .validate import validate

DEFAULTS = {
    "fill": {"angle": 45.0, "spacing": 0.4, "stitch_len": 3.5, "underlay": "tatami", "pull_comp": 0.2},
    "satin": {"width": 3.0, "spacing": 0.4, "underlay": "auto", "pull_comp": 0.2},
    "run": {"stitch_len": 2.5},
    "column": {"spacing": 0.4, "underlay": "auto", "pull_comp": 0.2},
    "text": {"spacing": 1.0, "underlay": "auto", "pull_comp": 0.1},
    "applique": {"width": 2.5, "spacing": 0.4, "stitch_len": 2.5, "cover_color": None},
}
FABRICS = {  # unverified starting points; flagged as such in the UI until stitch-tested
    "cotton": {"pull_comp": 0.2, "spacing": 0.40}, "silk": {"pull_comp": 0.3, "spacing": 0.45},
    "georgette": {"pull_comp": 0.35, "spacing": 0.45}, "velvet": {"pull_comp": 0.4, "spacing": 0.38},
    "denim": {"pull_comp": 0.1, "spacing": 0.40}, "knit": {"pull_comp": 0.4, "spacing": 0.42},
}
SPM = 700.0           # assumed machine speed, stitches per minute
COLOR_CHANGE_S, TRIM_S = 20.0, 6.0


def _p(obj: dict, key: str):
    return obj.get("params", {}).get(key, DEFAULTS.get(obj["type"], {}).get(key))


def _pts(v, ob: Optional[dict] = None, closed: bool = False) -> list:
    pts = [(float(a), float(b)) for a, b in v]
    return smooth(pts, closed) if ob and ob.get("smooth") else pts


def _satin_objs(oid, th, path, width, spacing, pull, underlay, split=0.0):
    if underlay == "auto":
        underlay = "center" if width >= 2.0 else "none"
    under = []
    if underlay == "center":
        under = [center_walk_underlay(path)]
    elif underlay == "edge" and width > 1.0:
        under = [edge_walk_underlay(path, width)]
    return StitchObject(oid, "satin", th, [satin_stitch(path, width, spacing, pull, split)], under)


def _column(oid, th, r1, r2, spacing, pull, underlay, notes, split=0.0):
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
    under = [center_walk_underlay(mid)] if underlay == "center" else \
            [running_stitch(a, 2.5), running_stitch(b[::-1], 2.5)] if underlay == "edge" else []
    return StitchObject(oid, "satin", th, [satin_from_rails(a, b, spacing, split)], under)


MACHINE_DEFAULTS = {"max_stitch": 7.0, "min_stitch": 0.3, "trim_distance": 3.0, "trim_jumps": 3}


def machine(design: dict) -> dict:
    m = dict(MACHINE_DEFAULTS)
    for k, v in (design.get("machine") or {}).items():
        if k in m and isinstance(v, (int, float)) and not isinstance(v, bool):
            m[k] = v
    m["max_stitch"] = min(max(m["max_stitch"], 1.0), 12.1)
    m["trim_distance"] = max(m["trim_distance"], 0.5)
    m["trim_jumps"] = int(min(max(m["trim_jumps"], 1), 6))
    return m


def generate(design: dict, trim_distance: Optional[float] = None):
    """Returns (pattern, notes, stats). Raises ValueError when nothing can be generated."""
    if trim_distance is None:
        trim_distance = machine(design)["trim_distance"]
    threads: List[ThreadColor] = []

    def tid(hexc: str) -> int:
        hexc = (hexc or "#000000").lower()
        for i, t in enumerate(threads):
            if t.hex == hexc:
                return i
        threads.append(ThreadColor(f"Thread {len(threads) + 1}", hexc))
        return len(threads) - 1

    objs: List[StitchObject] = []
    notes: List[str] = []
    mach = machine(design)
    split_of = lambda ob: (mach["max_stitch"] if ob.get("params", {}).get("auto_split", True) else 0.0)
    for ob in design.get("objects", []):
        if ob.get("hidden") or ob.get("guide") or ob.get("type") == "embellishment":
            continue          # guides and embellishment placeholders are never stitched (they go on the production sheet)
        oid, typ = str(ob["id"]), ob["type"]
        try:
            th = tid(ob.get("color"))
            if typ == "fill":
                rings = [_pts(r, ob, True) for r in ob["rings"]]
                runs = tatami_fill(rings, _p(ob, "angle"), _p(ob, "spacing"), _p(ob, "stitch_len"),
                                   pull_comp=_p(ob, "pull_comp") or 0.0)
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
                        under += tatami_fill(rings, _p(ob, "angle") + 90, 2.0, 3.0)
                objs.append(StitchObject(oid, "fill", th, runs, under))
            elif typ == "satin":
                w = _p(ob, "width")
                if w < 1.0:
                    notes.append(f"{oid}: satin {w:g} mm is too narrow (< 1 mm); use a running stitch")
                elif w > split_of(ob) > 0:
                    notes.append(f"{oid}: satin {w:g} mm is wider than the max stitch - long stitches split automatically")
                elif w > 7.0:
                    notes.append(f"{oid}: satin {w:g} mm is loose (> 7 mm); enable auto-split, narrow it, or use a fill")
                objs.append(_satin_objs(oid, th, _pts(ob["points"], ob, bool(ob.get("closed"))), _p(ob, "width"), _p(ob, "spacing"),
                                        _p(ob, "pull_comp") or 0.0, _p(ob, "underlay"), split_of(ob)))
            elif typ == "column":
                objs.append(_column(oid, th, _pts(ob["rail1"], ob), _pts(ob["rail2"], ob), _p(ob, "spacing"),
                                    _p(ob, "pull_comp") or 0.0, _p(ob, "underlay"), notes, split_of(ob)))
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
                objs.append(StitchObject(oid + ".place", "running", place, [running_stitch(ring, sl)]))
                objs.append(StitchObject(oid + ".tack", "running", cover, [running_stitch(ring, sl)]))
                objs.append(StitchObject(oid + ".cover", "satin", cover,
                                         [satin_stitch(ring, _p(ob, "width"), _p(ob, "spacing"), 0.0)]))
                notes.append(f"{oid}: appliqué - machine stops at the placement->tack-down colour change; "
                             "place fabric then, trim after tack-down.")
            else:
                notes.append(f"{oid}: unknown type {typ!r} skipped")
        except (DigitizingError, KeyError, TypeError, ValueError) as e:
            notes.append(f"{oid}: skipped ({e})")
    notes += _order_notes(design)
    pattern = build_pattern(objs, threads, design.get("name", "design"), trim_distance)
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
            if e.get("type") not in ("satin", "run", "column", "text"):
                continue
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
        "embellishments": emb,
        "fabric": (design or {}).get("fabric"), "stabiliser": (design or {}).get("stabiliser"),
        "stitches": c["stitch"], "jumps": c["jump"], "trims": c["trim"], "color_changes": c["color_change"],
        "width_mm": round(bb[2] - bb[0], 2) if bb else 0, "height_mm": round(bb[3] - bb[1], 2) if bb else 0,
        "est_minutes": round(seconds / 60, 1), "assumed_spm": SPM,
        "threads": [{"hex": t.hex, "stitches": per.get(i, 0)} for i, t in enumerate(p.threads)],
        "color_sequence": [{"hex": p.threads[t].hex, "stitches": n} for t, n in sequence],
    }


def run_checks(design: dict, pattern: Pattern):
    hoop = design.get("hoop", {})
    m = machine(design)
    return validate(pattern, float(hoop.get("w", 100)), float(hoop.get("h", 100)), float(hoop.get("margin", 3)),
                    max_stitch=m["max_stitch"], min_stitch=m["min_stitch"])
