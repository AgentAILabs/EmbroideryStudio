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


TRIM_S, JUMP_RECORD_S = 6.0, 60.0 / 700.0      # a trim ~6 s; each DST jump record (<= 12.1 mm) one machine cycle


def machine_seconds(m: Tuple[int, float]) -> float:
    """Time spent on trims + travel for (trims, travel_mm): the quantity the sequencer minimises."""
    return m[0] * TRIM_S + m[1] / 12.1 * JUMP_RECORD_S


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


def _cloud(o, step=1.0):
    """Points along an object's geometry (rails / points / ring edges densified to `step` mm)."""
    lines = [o[k] for k in ("points", "rail1", "rail2") if o.get(k)] + [list(r) + [r[0]] for r in o.get("rings", [])]
    if o.get("type") == "text":
        b = _bbox(o); lines = [[(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3]), (b[0], b[1])]] if b else []
    out = []
    for ln in lines:
        for a, c in zip(ln, ln[1:]):
            n = max(1, int(math.dist(a, c) / step))
            out += [(a[0] + (c[0] - a[0]) * t / n, a[1] + (c[1] - a[1]) * t / n) for t in range(n + 1)]
    return out


def _motifs(objs: List[dict], touch: float = 1.0) -> List[List[int]]:
    """Group objects (indices, original order) into motifs: two objects belong together when their geometry comes within `touch` mm
    (a fern's leaflets and stem, a flower's petals and ring, the pieces of one neckline). Union-find on a spatial hash.
    Inside a motif the sewing order is never changed; separate motifs may be reordered (they do not touch, so layering is unaffected)."""
    n = len(objs); parent = list(range(n))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    grid = {}
    for i, o in enumerate(objs):
        for x, y in _cloud(o):
            gx, gy = int(math.floor(x / touch)), int(math.floor(y / touch))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in grid.get((gx + dx, gy + dy), ()):
                        if j != i:
                            parent[find(i)] = find(j)
            grid.setdefault((gx, gy), set()).add(i)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: g[0])


def _motif_order(objs: List[dict], start) -> List[int]:
    """Order whole motifs (entry = start of its first object, exit = end of its last) by nearest neighbour, then improve the open
    path with 2-opt on the (asymmetric) exit -> entry distances. Returns object indices."""
    groups = _motifs(objs)
    if len(groups) < 2:
        return list(range(len(objs)))
    ent = [_ends(objs[g[0]])[0] for g in groups]
    ext = [_ends(objs[g[-1]])[1] for g in groups]
    m = len(groups)
    cost = lambda a, b: math.dist(ext[a], ent[b])
    first = (lambda a: math.dist(start, ent[a])) if start is not None else (lambda a: 0.0)
    left, order = set(range(m)), []
    cur = None
    while left:
        nxt = min(left, key=lambda a: (first(a) if cur is None else cost(cur, a), a))
        order.append(nxt); left.discard(nxt); cur = nxt
    def total(o):
        return first(o[0]) + sum(cost(a, b) for a, b in zip(o, o[1:]))
    best, improved = total(order), True
    while improved and m <= 400:
        improved = False
        for i in range(m - 1):
            for k in range(i + 1, m):
                cand = order[:i] + order[i:k + 1][::-1] + order[k + 1:]
                t = total(cand)
                if t + 1e-6 < best:
                    order, best, improved = cand, t, True
    return [i for g in order for i in groups[g]]


def optimize_sequence(design: dict) -> Tuple[dict, List[str]]:
    """Try object-level and motif-level orders inside each same-colour block; keep whichever generated file is best
    (fewer trims, then less travel). Never returns a worse design."""
    base = design
    best_d, best_m, best_log = design, None, []
    for mode in ("objects", "motifs"):
        cand, log = _optimize(base, mode)
        if cand is base:
            continue
        try:
            mtr = travel_metrics(cand)
        except ValueError:
            continue
        if best_m is None or machine_seconds(mtr) < machine_seconds(best_m):
            best_d, best_m, best_log = cand, mtr, log
    try:
        before = travel_metrics(design)
    except ValueError:
        return design, []
    if best_m is not None and machine_seconds(best_m) < machine_seconds(before) - 0.5:
        return best_d, [f"sequence optimised ({best_log[0]}): trims {before[0]} -> {best_m[0]}, travel {before[1]:.0f} -> {best_m[1]:.0f} mm (colour order and layering kept)"]
    return design, [f"sequence kept: already optimal for this design (trims {before[0]}, travel {before[1]:.0f} mm)"]


def _optimize(design: dict, mode: str):
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
            order = (_motif_order if mode == "motifs" else _block_order)([objs[k] for k in blk], pos)
            for slot, i in zip(blk, order):
                new[slot] = objs[blk[i]]
        last = new[blk[-1]]; pos = _ends(last)[1]
    return dict(copy.deepcopy(design), objects=copy.deepcopy(new)), [mode]
