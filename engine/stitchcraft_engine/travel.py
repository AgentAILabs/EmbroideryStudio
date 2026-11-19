"""Travel / trim analysis of a generated stitch plan (software analysis; times are estimates, not verified on a machine).

Every needle move between two stitched positions is classified:
  colour change      thread changes here (a trim is machine-option dependent)
  trimmed            thread cut + jump; justified when the jump is longer than half the trim distance
  unnecessary trim   thread cut before a very short jump (wastes machine time, no benefit)
  carried            jump with the thread left attached; fine while shorter than the trim distance
  missing trim       long jump (> trim distance) carried without a trim: a thread strand will lie across the work
A carried jump also reports how much of its path lies over empty fabric (no stitches within 1 mm).
"""
from __future__ import annotations
import math
from typing import Dict, List, Optional

from .model import Cmd, Pattern

JUMP_SECONDS_PER_RECORD = 60.0 / 700.0
TRIM_SECONDS = 6.0


def travel_report(design: dict, pattern: Pattern) -> dict:
    from .design import machine
    m = machine(design); td = m["trim_distance"]
    S = pattern.stitches
    occ = set()
    for s in S:
        if s.cmd == Cmd.STITCH:
            occ.add((int(math.floor(s.x)), int(math.floor(s.y))))

    def empty_len(a, b) -> float:
        d = math.hypot(b[0] - a[0], b[1] - a[1]); n = max(1, int(d / 0.5)); e = 0
        for k in range(n + 1):
            x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
            cx, cy = int(math.floor(x)), int(math.floor(y))
            if not any((cx + i, cy + j) in occ for i in (-1, 0, 1) for j in (-1, 0, 1)):
                e += 1
        return d * e / (n + 1)

    moves: List[dict] = []
    objects: Dict[str, dict] = {}
    last: Optional[tuple] = None          # last stitched / jumped position
    last_oid = None; trimmed = False; colour = False
    for i, s in enumerate(S):
        if s.cmd == Cmd.TRIM:
            trimmed = True
        elif s.cmd == Cmd.COLOR_CHANGE:
            colour = True
        elif s.cmd in (Cmd.JUMP, Cmd.STITCH):
            if s.object_id:
                o = objects.setdefault(s.object_id, {"id": s.object_id, "entry": None, "exit": None, "stitches": 0})
                if s.cmd == Cmd.STITCH:
                    if o["entry"] is None: o["entry"] = [round(s.x, 2), round(s.y, 2)]
                    o["exit"] = [round(s.x, 2), round(s.y, 2)]; o["stitches"] += 1
            if s.cmd == Cmd.JUMP:
                d = math.hypot(s.x - last[0], s.y - last[1]) if last else 0.0
                if last is not None and d > 1e-6 or colour or trimmed:
                    if colour: verdict = "colour change"
                    elif trimmed and d < 0.5 * td: verdict = "unnecessary trim"
                    elif trimmed: verdict = "trimmed"
                    elif d > td + 1e-6: verdict = "missing trim"
                    else: verdict = "carried"
                    mv = {"index": i, "from": last_oid, "to": s.object_id, "distance_mm": round(d, 2), "trimmed": trimmed, "colour_change": colour, "verdict": verdict}
                    if verdict in ("carried", "missing trim") and last is not None:
                        mv["over_empty_mm"] = round(empty_len(last, (s.x, s.y)), 2)
                    moves.append(mv)
                trimmed = colour = False
                last = (s.x, s.y)
            else:
                if trimmed or colour:                                  # colour change / trim with no jump (needle already in place)
                    moves.append({"index": i, "from": last_oid, "to": s.object_id, "distance_mm": 0.0, "trimmed": trimmed, "colour_change": colour,
                                  "verdict": "colour change" if colour else "unnecessary trim"})
                    trimmed = colour = False
                last = (s.x, s.y); last_oid = s.object_id
    # exit -> next entry distances (entry/exit hints)
    order = list(objects.values())
    for a, b in zip(order, order[1:]):
        a["to_next_mm"] = round(math.hypot(b["entry"][0] - a["exit"][0], b["entry"][1] - a["exit"][1]), 2) if a["exit"] and b["entry"] else None
    verdicts: Dict[str, int] = {}
    for mv in moves:
        verdicts[mv["verdict"]] = verdicts.get(mv["verdict"], 0) + 1
    jump_mm = sum(mv["distance_mm"] for mv in moves)
    colours = [s.thread for s in S if s.cmd in (Cmd.STITCH,)]
    distinct = len(set(colours))
    changes = sum(1 for s in S if s.cmd == Cmd.COLOR_CHANGE)
    trims = sum(1 for s in S if s.cmd == Cmd.TRIM)
    over_empty = sum(mv.get("over_empty_mm", 0.0) for mv in moves)
    return {
        "moves": moves, "objects": order, "verdicts": verdicts,
        "totals": {"jump_mm": round(jump_mm, 1), "trims": trims, "colour_changes": changes, "distinct_threads": distinct,
                   "minimum_colour_changes": max(0, distinct - 1), "avoidable_colour_changes": max(0, changes - max(0, distinct - 1)),
                   "carried_over_empty_mm": round(over_empty, 1),
                   "estimated_travel_seconds": round(trims * TRIM_SECONDS + jump_mm / 12.1 * JUMP_SECONDS_PER_RECORD, 1)},
        "trim_distance_mm": td,
        "note": "Software analysis of the stitch plan. Seconds are an estimate, not verified on a machine. Colour changes may be unavoidable because of layering order.",
    }
