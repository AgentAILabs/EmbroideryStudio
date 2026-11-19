"""Split a design that is larger than the hoop into several hoopings, with stitched alignment marks.

Objects are never cut: each stitched object belongs to the tile that contains the centre of its bounding box. An object bigger than one tile cannot be
split safely and is reported (the operator must scale it or use a bigger frame). Every tile is an ordinary design (own DST, own checks).
Alignment marks: small crosses at the corners of the tile grid, positioned in DESIGN coordinates, so the same physical cross is stitched by the tiles that
share that grid point. They are real stitches (a light, removable thread is the usual choice): hoop tile 2 so that its crosses sit on the crosses already
stitched by tile 1. Nothing here has been verified on a machine.
"""
from __future__ import annotations
import copy
import math
from typing import List, Optional

from .design import _bbox, expand_handles

MARK_COLOR = "#7a7a7a"
MARK_ARM = 4.0


def _stitched(o: dict) -> bool:
    return not o.get("hidden") and not o.get("guide") and o.get("type") != "embellishment"


def _side(v, cut):
    return 0 if v < cut else 1


def _split_poly(pts, axis, cut):
    """Polyline -> pieces on either side of the line coordinate[axis] == cut; each piece ends exactly on the line (the join is an overlap, as in hand-split designs)."""
    pieces, cur, side = [], [pts[0]], _side(pts[0][axis], cut)
    for p, q in zip(pts, pts[1:]):
        sq = _side(q[axis], cut)
        if sq == side:
            cur.append(q); continue
        t = (cut - p[axis]) / (q[axis] - p[axis]) if q[axis] != p[axis] else 0.0
        x = [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]; x[axis] = cut
        cur.append(x); pieces.append(cur); cur = [list(x), q]; side = sq
    pieces.append(cur)
    return [pc for pc in pieces if len(pc) >= 2 and sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pc, pc[1:])) > 0.8]


def _split_column(o, axis, cut):
    r1, r2 = o["rail1"], o["rail2"]
    if len(r1) != len(r2) or len(r1) < 3:
        return [o]
    mid = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(r1, r2)]
    for i in range(1, len(mid) - 1):
        if _side(mid[i][axis], cut) != _side(mid[0][axis], cut):
            a, b = dict(o, rail1=r1[:i + 1], rail2=r2[:i + 1]), dict(o, rail1=r1[i:], rail2=r2[i:])
            return _split_column(a, axis, cut) + _split_column(b, axis, cut)
    return [o]


def _split_object(o, cuts_x, cuts_y):
    """Cut a long run / open satin / column at the interior grid lines so it can belong to several hoopings. Fills and closed shapes are left whole."""
    typ = o.get("type")
    if typ not in ("run", "satin", "column") or o.get("closed"):
        return [o]
    pieces = [o]
    for axis, cuts in ((0, cuts_x[1:-1]), (1, cuts_y[1:-1])):
        for cut in cuts:
            nxt = []
            for q in pieces:
                if typ == "column":
                    nxt += _split_column(q, axis, cut)
                else:
                    nxt += [dict(q, points=pc) for pc in _split_poly([tuple(p) for p in q["points"]], axis, cut)] or [q]
            pieces = nxt
    if len(pieces) > 1:
        pieces = [dict(pc, id=f"{o['id']}_p{i + 1}") for i, pc in enumerate(pieces)]
    return pieces


def _tile_extent(t, axis):
    """Size of a tile's stitched content (objects + alignment marks) along x (0) or y (1)."""
    lo, hi = 1e18, -1e18
    for o in t["design"]["objects"]:
        b = _bbox(o)
        if b:
            lo, hi = min(lo, b[axis]), max(hi, b[axis + 2])
    return hi - lo


def _cell(v, cuts):
    for i in range(len(cuts) - 1):
        if v < cuts[i + 1] or i == len(cuts) - 2:
            return i
    return 0


def _build(design, base_objs, hoop, margin, marks, bounds, cols, rows):
    x0, y0, x1, y1 = bounds
    cuts_x = [x0 + (x1 - x0) * i / cols for i in range(cols + 1)]
    cuts_y = [y0 + (y1 - y0) * i / rows for i in range(rows + 1)]
    pieces = []
    for o in base_objs:
        pieces += _split_object(o, cuts_x, cuts_y)
    usable_w, usable_h = hoop[0] - 2 * margin, hoop[1] - 2 * margin
    buckets, oversize = {}, []
    for o in pieces:
        b = _bbox(o)
        if b[2] - b[0] > usable_w + 1e-6 or b[3] - b[1] > usable_h + 1e-6:
            oversize.append(o["id"])
        buckets.setdefault((_cell((b[0] + b[2]) / 2, cuts_x), _cell((b[1] + b[3]) / 2, cuts_y)), []).append(o)
    tiles = []
    for (c, r), members in sorted(buckets.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        t = {k: v for k, v in design.items() if k != "objects"}
        t["name"] = f"{design.get('name', 'design')}_r{r + 1}c{c + 1}"
        t["hoop"] = {"w": hoop[0], "h": hoop[1], "margin": margin}
        t["objects"] = copy.deepcopy(members)
        if marks:
            n = 0
            for gx in (cuts_x[c], cuts_x[c + 1]):
                for gy in (cuts_y[r], cuts_y[r + 1]):
                    n += 1
                    for k, (a, b) in enumerate((((-MARK_ARM, 0), (MARK_ARM, 0)), ((0, -MARK_ARM), (0, MARK_ARM)))):
                        t["objects"].insert(0, {"id": f"mark_{n}_{k}", "type": "run", "color": MARK_COLOR, "name": f"Alignment mark {n}",
                                                "points": [[round(gx + a[0], 3), round(gy + a[1], 3)], [round(gx + b[0], 3), round(gy + b[1], 3)]], "params": {"stitch_len": 1.5}})
        tb = [min(_bbox(o)[0] for o in members), min(_bbox(o)[1] for o in members), max(_bbox(o)[2] for o in members), max(_bbox(o)[3] for o in members)]
        tiles.append({"name": t["name"], "col": c, "row": r, "design": t, "bbox": tb, "objects": len(members)})
    return cuts_x, cuts_y, tiles, oversize


def split_for_hoop(design: dict, hoop_w: float, hoop_h: float, margin: float = 8.0, marks: bool = True) -> dict:
    """-> {"tiles": [{"name", "col", "row", "design", "bbox", "objects": n}], "grid": {"cols","rows","cuts_x","cuts_y"}, "oversize": [ids], "fits": bool}
    The grid grows (up to 12 hoopings) until every tile, including its alignment marks, fits the usable hoop area."""
    design = expand_handles(design)
    objs = [o for o in design.get("objects", []) if _stitched(o) and _bbox(o)]
    if not objs:
        raise ValueError("nothing to split: the design has no stitched objects")
    bbs = [_bbox(o) for o in objs]
    bounds = (min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs))
    usable_w, usable_h = hoop_w - 2 * margin, hoop_h - 2 * margin
    slack = (2 * (MARK_ARM + 3.0)) if marks else 0.0
    if usable_w - slack <= 20 or usable_h - slack <= 20:
        raise ValueError("the hoop is too small for a split (usable area must be larger than 20 mm)")
    if bounds[2] - bounds[0] <= usable_w and bounds[3] - bounds[1] <= usable_h:
        return {"fits": True, "tiles": [{"name": design.get("name", "design"), "col": 0, "row": 0, "design": design, "bbox": list(bounds), "objects": len(objs)}],
                "grid": {"cols": 1, "rows": 1}, "oversize": []}
    cols = max(1, math.ceil((bounds[2] - bounds[0]) / (usable_w - slack) - 1e-9))
    rows = max(1, math.ceil((bounds[3] - bounds[1]) / (usable_h - slack) - 1e-9))
    while True:
        if cols * rows > 12:
            raise ValueError(f"this would need more than 12 hoopings: use a larger frame or scale the design")
        cuts_x, cuts_y, tiles, oversize = _build(design, objs, (hoop_w, hoop_h), margin, marks, bounds, cols, rows)
        over_w = any(_tile_extent(t, 0) > usable_w - 1.5 for t in tiles)
        over_h = any(_tile_extent(t, 1) > usable_h - 1.5 for t in tiles)
        if not (over_w or over_h):
            break
        if oversize and cols * rows >= 6:                      # an object that is itself too big will never fit: stop and report it
            break
        cols, rows = cols + (1 if over_w else 0), rows + (1 if over_h else 0)
    return {"fits": False, "tiles": tiles, "grid": {"cols": cols, "rows": rows, "cuts_x": cuts_x, "cuts_y": cuts_y}, "oversize": oversize}
