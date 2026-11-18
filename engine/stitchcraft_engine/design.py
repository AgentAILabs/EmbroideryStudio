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
from .geometry import polygon_area, smooth
from .model import Cmd, Pattern, ThreadColor
from .stitches import (DigitizingError, center_walk_underlay, edge_walk_underlay, running_stitch,
                       satin_stitch, tatami_fill)
from .validate import validate

DEFAULTS = {
    "fill": {"angle": 45.0, "spacing": 0.4, "stitch_len": 3.5, "underlay": True, "pull_comp": 0.2},
    "satin": {"width": 3.0, "spacing": 0.4, "underlay": "auto", "pull_comp": 0.2},
    "run": {"stitch_len": 2.5},
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


def _satin_objs(oid, th, path, width, spacing, pull, underlay):
    if underlay == "auto":
        underlay = "center" if width >= 2.0 else "none"
    under = []
    if underlay == "center":
        under = [center_walk_underlay(path)]
    elif underlay == "edge" and width > 1.0:
        under = [edge_walk_underlay(path, width)]
    return StitchObject(oid, "satin", th, [satin_stitch(path, width, spacing, pull)], under)


def generate(design: dict, trim_distance: float = 3.0):
    """Returns (pattern, notes, stats). Raises ValueError when nothing can be generated."""
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
    for ob in design.get("objects", []):
        if ob.get("hidden"):
            continue
        oid, typ = str(ob["id"]), ob["type"]
        try:
            th = tid(ob.get("color"))
            if typ == "fill":
                rings = [_pts(r, ob, True) for r in ob["rings"]]
                runs = tatami_fill(rings, _p(ob, "angle"), _p(ob, "spacing"), _p(ob, "stitch_len"),
                                   pull_comp=_p(ob, "pull_comp") or 0.0)
                under = []
                if _p(ob, "underlay") and sum(polygon_area(r) for r in rings) >= 25:
                    under = tatami_fill(rings, _p(ob, "angle") + 90, 2.0, 3.0)
                objs.append(StitchObject(oid, "fill", th, runs, under))
            elif typ == "satin":
                objs.append(_satin_objs(oid, th, _pts(ob["points"], ob, bool(ob.get("closed"))), _p(ob, "width"), _p(ob, "spacing"),
                                        _p(ob, "pull_comp") or 0.0, _p(ob, "underlay")))
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
                                            _p(ob, "underlay")))
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
    pattern = build_pattern(objs, threads, design.get("name", "design"), trim_distance)
    return pattern, notes, stats(pattern, design)


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
    return {
        "stitches": c["stitch"], "jumps": c["jump"], "trims": c["trim"], "color_changes": c["color_change"],
        "width_mm": round(bb[2] - bb[0], 2) if bb else 0, "height_mm": round(bb[3] - bb[1], 2) if bb else 0,
        "est_minutes": round(seconds / 60, 1), "assumed_spm": SPM,
        "threads": [{"hex": t.hex, "stitches": per.get(i, 0)} for i, t in enumerate(p.threads)],
        "color_sequence": [{"hex": p.threads[t].hex, "stitches": n} for t, n in sequence],
    }


def run_checks(design: dict, pattern: Pattern):
    hoop = design.get("hoop", {})
    return validate(pattern, float(hoop.get("w", 100)), float(hoop.get("h", 100)), float(hoop.get("margin", 3)))
