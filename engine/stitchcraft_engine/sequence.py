"""Stitch-sequence optimisation that respects what nearest-neighbour alone ignores.

Rules:
  * colour order is kept (no extra colour changes); only objects inside one consecutive same-colour block move
  * layering is kept: two objects whose outlines overlap (bbox + 0.5 mm) keep their original relative order
  * the candidate order is accepted only if the *generated* file is better: fewer trims, then less travel; otherwise the
    original order is returned unchanged (never makes a design worse)
Entry / exit direction of each run is already chosen by the builder (smart_direction).
"""
import copy, math
from typing import List, Tuple

from .design import _bbox, generate
from .model import Cmd


def _pts(o):
    if o.get("type") == "text":
        b = _bbox(o); return [(b[0], b[1]), (b[2], b[3])] if b else [(0, 0)]
    return [tuple(p) for r in o.get("rings", []) for p in r] + [tuple(p) for k in ("points", "rail1", "rail2") for p in o.get(k, [])]


def _ends(o):
    if o.get("type") == "fill":
        pts = _pts(o); c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)); return c, c
    for k in ("points", "rail1"):
        if o.get(k):
            return tuple(o[k][0]), tuple(o[k][-1])
    pts = _pts(o) or [(0, 0)]
    return pts[0], pts[-1]


def _overlap(a, b, pad=0.5):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def travel_metrics(design) -> Tuple[int, float]:
    p, _, st = generate(design)
    travel, last = 0.0, None
    for s in p.stitches:
        if s.cmd == Cmd.JUMP and last is not None:
            travel += math.hypot(s.x - last[0], s.y - last[1])
        last = (s.x, s.y)
    return st["trims"], round(travel, 1)


def _block_order(objs: List[dict], start) -> List[int]:
    n = len(objs); boxes = [_bbox(o) for o in objs]
    preds = {i: {j for j in range(i) if boxes[i] and boxes[j] and _overlap(boxes[i], boxes[j])} for i in range(n)}
    done, order, cur = set(), [], start
    while len(order) < n:
        ready = [i for i in range(n) if i not in done and preds[i] <= done]
        def cost(i):
            a, b = _ends(objs[i])
            return min(math.dist(cur, a), math.dist(cur, b)) if cur is not None else 0.0
        i = min(ready, key=lambda i: (cost(i), i))
        a, b = _ends(objs[i])
        cur = b if cur is None or math.dist(cur, a) <= math.dist(cur, b) else a
        done.add(i); order.append(i)
    return order


def optimize_sequence(design: dict) -> Tuple[dict, List[str]]:
    objs = design.get("objects", [])
    stitched = [k for k, o in enumerate(objs) if not o.get("hidden") and not o.get("guide") and o.get("type") != "embellishment"]
    if len(stitched) < 3:
        return design, []
    new = list(objs)
    # consecutive blocks of the same colour among stitched objects (placeholders stay where they are)
    blocks, cur = [], [stitched[0]]
    for k in stitched[1:]:
        if (objs[k].get("color") or "").lower() == (objs[cur[-1]].get("color") or "").lower() and objs[k].get("type") != "applique" and objs[cur[-1]].get("type") != "applique":
            cur.append(k)
        else:
            blocks.append(cur); cur = [k]
    blocks.append(cur)
    pos = None
    for blk in blocks:
        if len(blk) >= 3:
            order = _block_order([objs[k] for k in blk], pos)
            for slot, i in zip(blk, order):
                new[slot] = objs[blk[i]]
        last = new[blk[-1]]; pos = _ends(last)[1]
    cand = dict(copy.deepcopy(design), objects=copy.deepcopy(new))
    try:
        before, after = travel_metrics(design), travel_metrics(cand)
    except ValueError:
        return design, []
    if after < before:
        return cand, [f"sequence optimised: trims {before[0]} -> {after[0]}, travel {before[1]:.0f} -> {after[1]:.0f} mm (colour order and layering kept)"]
    return design, [f"sequence kept: already optimal for this design (trims {before[0]}, travel {before[1]:.0f} mm)"]
