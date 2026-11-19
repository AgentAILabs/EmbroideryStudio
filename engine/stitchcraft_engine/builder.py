from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from .geometry import Point, dist
from .model import Cmd, Pattern, Stitch, ThreadColor


@dataclass
class StitchObject:
    id: str
    kind: str                      # running | satin | fill
    thread: int                    # index into thread list
    runs: List[List[Point]]        # top stitching; a gap between runs = JUMP
    underlay_runs: List[List[Point]] = field(default_factory=list)
    fixed: bool = False            # manual stitches: sew exactly in the given direction (no smart reversal)


LOCK_MIN = 0.3      # never emit a lock stitch shorter than this (the validator warns below 0.3 mm)


def _unit(a: Point, b: Point):
    d = dist(a, b)
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d, d) if d > 1e-9 else None


def _tie_off(out: List[Stitch], lock_len: float) -> List[Point]:
    """Back-forth-back lock along the last stitched segment (stays inside the geometry just stitched). Returns the points
    to stitch after the last stitch; [] when locking is off or the last segment is too short to lock reliably."""
    if lock_len <= 0 or not out or out[-1].cmd != Cmd.STITCH:
        return []
    cur = (out[-1].x, out[-1].y)
    prev = None
    for s in reversed(out[:-1]):
        if s.cmd != Cmd.STITCH:
            break
        if dist((s.x, s.y), cur) > 1e-6:
            prev = (s.x, s.y)
            break
    u = _unit(prev, cur) if prev else None
    if not u:
        return []
    l = min(lock_len, 0.5 * u[2])
    if l < LOCK_MIN:
        return []
    back = (cur[0] - u[0] * l, cur[1] - u[1] * l)
    return [back, cur, back]


def _tie_in(start: Point, nxt: Optional[Point], lock_len: float) -> List[Point]:
    """Forward-back lock at a run's first stitch, along the first segment of the run. Sequence: start, fwd, start, ..."""
    if lock_len <= 0 or nxt is None:
        return []
    u = _unit(start, nxt)
    if not u:
        return []
    l = min(lock_len, 0.5 * u[2])
    if l < LOCK_MIN:
        return []
    return [(start[0] + u[0] * l, start[1] + u[1] * l), start]


def build_pattern(objects: Sequence[StitchObject], threads: Sequence[ThreadColor], name: str = "design",
                  trim_distance: float = 3.0, lock_len: float = 0.0, trim_at_color_change: bool = False,
                  trim_at_end: bool = False, choose_direction: bool = False) -> Pattern:
    """Stitch commands for the objects, in order. Defaults reproduce the original behaviour (no locks, trims only on
    long jumps). choose_direction: stitch each run from whichever end is nearer the needle (same stitches, fewer jumps and trims,
    e.g. a satin column after its centre-walk underlay). Professional sequence (lock_len > 0, trims on): ... tie-off, TRIM, [COLOR_CHANGE,] JUMP, first stitch, tie-in ..."""
    out: List[Stitch] = []
    cur: Optional[Point] = None
    cur_thread: Optional[int] = None
    locks = 0
    last_oid: Optional[str] = None

    def finish_thread(oid, trim: bool):
        """Tie off the thread that is about to be cut or changed, then trim (if wanted)."""
        nonlocal cur, locks
        for q in _tie_off(out, lock_len):
            out.append(Stitch(q[0], q[1], Cmd.STITCH, cur_thread if cur_thread is not None else 0, oid)); locks += 1
            cur = q
        if trim and cur is not None:
            out.append(Stitch(cur[0], cur[1], Cmd.TRIM, cur_thread if cur_thread is not None else 0, oid))

    for obj in objects:
        for run in obj.underlay_runs + obj.runs:
            if not run:
                continue
            if choose_direction and not obj.fixed and cur is not None and dist(cur, run[0]) > trim_distance >= dist(cur, run[-1]):
                run = run[::-1]            # only when it turns a trim into a carried jump (a greedy "nearest end" can make the next jump worse)
            cut = cur is None                      # a fresh thread end (design start, after a trim, or a new colour) needs a tie-in
            if cur_thread is not None and obj.thread != cur_thread:
                finish_thread(last_oid, trim_at_color_change)
                out.append(Stitch(cur[0], cur[1], Cmd.COLOR_CHANGE, obj.thread, obj.id))
                cur_thread = obj.thread
                cut = True
            else:
                cur_thread = obj.thread if cur_thread is None else cur_thread
                if cur is not None and dist(cur, run[0]) > trim_distance:
                    finish_thread(last_oid, True)
                    cut = True
            if cur is None or dist(cur, run[0]) > 1e-6:
                out.append(Stitch(run[0][0], run[0][1], Cmd.JUMP, obj.thread, obj.id))
                out.append(Stitch(run[0][0], run[0][1], Cmd.STITCH, obj.thread, obj.id))
            # else: the needle is already at run[0]
            if cut and lock_len > 0:
                nxt = next((q for q in run[1:] if dist(q, run[0]) > 1e-6), None)
                for q in _tie_in(run[0], nxt, lock_len):
                    out.append(Stitch(q[0], q[1], Cmd.STITCH, obj.thread, obj.id)); locks += 1
            out += [Stitch(p[0], p[1], Cmd.STITCH, obj.thread, obj.id) for p in run[1:]]
            cur = run[-1]
            last_oid = obj.id
    if cur is None:
        raise ValueError("no stitches generated")
    finish_thread(last_oid, trim_at_end)
    out.append(Stitch(cur[0], cur[1], Cmd.END, cur_thread or 0, None))
    pat = Pattern(name=name, stitches=out, threads=list(threads))
    pat.lock_stitches = locks
    return pat
