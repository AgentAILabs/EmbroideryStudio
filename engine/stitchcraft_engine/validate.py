from __future__ import annotations
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import List
from .geometry import dist
from .model import Cmd, Pattern


@dataclass
class Issue:
    code: str
    severity: str        # "error" | "warning"
    message: str
    index: int = -1


@dataclass
class Report:
    issues: List[Issue] = field(default_factory=list)

    @property
    def errors(self): return [i for i in self.issues if i.severity == "error"]
    @property
    def warnings(self): return [i for i in self.issues if i.severity == "warning"]
    @property
    def ok(self): return not self.errors


def validate(p: Pattern, hoop_w: float = 100, hoop_h: float = 100, margin: float = 3.0,
             max_stitch: float = 7.0, min_stitch: float = 0.3, max_per_mm2: float = 12.0) -> Report:
    r = Report()
    add = lambda c, s, m, i=-1: r.issues.append(Issue(c, s, m, i))
    S = p.stitches
    if not S:
        add("EMPTY", "error", "Design has no stitches"); return r
    if S[-1].cmd != Cmd.END:
        add("NO_END", "error", "Design does not end with an END command")
    if sum(1 for s in S if s.cmd == Cmd.END) > 1:
        add("MULTI_END", "error", "More than one END command")
    cc = sum(1 for s in S if s.cmd == Cmd.COLOR_CHANGE)
    if p.threads and cc > len(p.threads) - 1:
        add("COLOR_SEQ", "error", f"{cc} colour changes but only {len(p.threads)} threads defined")
    for i in range(1, len(S)):
        if S[i].cmd == Cmd.COLOR_CHANGE and S[i - 1].cmd == Cmd.COLOR_CHANGE:
            add("DOUBLE_COLOR", "error", "Two colour changes in a row", i)
    prev = None
    prev_was_stitch = False
    cells = Counter()
    for i, s in enumerate(S):
        if s.cmd == Cmd.STITCH:
            if prev is not None:
                d = dist(prev, (s.x, s.y))
                if d > 12.1:
                    add("STITCH_TOO_LONG_DST", "error", f"Stitch {d:.1f} mm exceeds DST record limit", i)
                elif d > max_stitch:
                    add("STITCH_LONG", "warning", f"Stitch {d:.1f} mm may snag or break thread", i)
                elif d < 1e-6 and prev_was_stitch:
                    add("ZERO_LENGTH", "warning", "Duplicate stitch (zero length)", i)
                elif 1e-6 <= d < min_stitch:
                    add("STITCH_SHORT", "warning", f"Very short stitch {d:.2f} mm", i)
            cells[(math.floor(s.x), math.floor(s.y))] += 1
        if s.cmd in (Cmd.STITCH, Cmd.JUMP):
            prev = (s.x, s.y)
            prev_was_stitch = s.cmd == Cmd.STITCH
    worst = max(cells.values()) if cells else 0
    if worst > max_per_mm2:
        add("DENSITY", "warning", f"Up to {worst} needle penetrations in one 1 mm square (limit {max_per_mm2:g})")
    bb = p.bbox()
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    if w > hoop_w - 2 * margin or h > hoop_h - 2 * margin:
        add("HOOP", "error", f"Design {w:.1f}x{h:.1f} mm does not fit hoop {hoop_w:g}x{hoop_h:g} mm with {margin:g} mm margin")
    return r
