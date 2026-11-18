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


def build_pattern(objects: Sequence[StitchObject], threads: Sequence[ThreadColor], name: str = "design",
                  trim_distance: float = 3.0) -> Pattern:
    out: List[Stitch] = []
    cur: Optional[Point] = None
    cur_thread: Optional[int] = None
    for obj in objects:
        for run in obj.underlay_runs + obj.runs:
            if not run:
                continue
            if cur_thread is not None and obj.thread != cur_thread:
                out.append(Stitch(cur[0], cur[1], Cmd.COLOR_CHANGE, obj.thread, obj.id))
                cur_thread = obj.thread
                need_jump = True
            else:
                cur_thread = obj.thread if cur_thread is None else cur_thread
                need_jump = cur is None or dist(cur, run[0]) > 1e-6
                if cur is not None and need_jump and dist(cur, run[0]) > trim_distance:
                    out.append(Stitch(cur[0], cur[1], Cmd.TRIM, obj.thread, obj.id))
            pts = run
            if cur is not None and dist(cur, run[0]) <= 1e-6:
                pts = run[1:]
            elif need_jump:
                out.append(Stitch(run[0][0], run[0][1], Cmd.JUMP, obj.thread, obj.id))
            out += [Stitch(p[0], p[1], Cmd.STITCH, obj.thread, obj.id) for p in pts]
            cur = run[-1]
    if cur is None:
        raise ValueError("no stitches generated")
    out.append(Stitch(cur[0], cur[1], Cmd.END, cur_thread or 0, None))
    return Pattern(name=name, stitches=out, threads=list(threads))
