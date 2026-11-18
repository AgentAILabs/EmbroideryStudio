"""Rule-based vector -> stitch objects. Classification rules are deliberately simple and documented:
  filled closed shape            -> tatami fill (+ perpendicular underlay when area >= 25 mm2)
  stroke 1.0-7.0 mm wide         -> satin column (+ center-walk underlay when >= 2 mm wide)
  any other stroke               -> running stitch"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List
from .builder import StitchObject, build_pattern
from .geometry import polygon_area
from .model import Pattern, ThreadColor
from .stitches import (center_walk_underlay, running_stitch, satin_stitch, tatami_fill, DigitizingError)
from .svg_input import SvgDoc


@dataclass
class Settings:
    fill_angle: float = 45.0
    fill_spacing: float = 0.4
    fill_stitch_len: float = 3.5
    satin_spacing: float = 0.4
    satin_pull_comp: float = 0.0
    running_len: float = 2.5
    underlay: bool = True


def digitize_svg(doc: SvgDoc, s: Settings = Settings(), name: str = "design"):
    threads: List[ThreadColor] = []
    def tid(hexc: str) -> int:
        for i, t in enumerate(threads):
            if t.hex == hexc:
                return i
        threads.append(ThreadColor(f"Thread {len(threads) + 1}", hexc)); return len(threads) - 1
    objs, notes = [], list(doc.warnings)
    for sh in doc.shapes:
        try:
            if sh.fill and sh.closed:
                runs = tatami_fill(sh.rings, s.fill_angle, s.fill_spacing, s.fill_stitch_len)
                under = []
                if s.underlay and sum(polygon_area(r) for r in sh.rings) >= 25:
                    under = tatami_fill(sh.rings, s.fill_angle + 90, 2.0, 3.0)
                objs.append(StitchObject(sh.id, "fill", tid(sh.fill), runs, under))
            if sh.stroke:
                for k, ring in enumerate(sh.rings):
                    path = ring + [ring[0]] if sh.closed else ring
                    oid = sh.id if k == 0 else f"{sh.id}.{k}"
                    if 1.0 <= sh.stroke_width_mm <= 7.0:
                        under = [center_walk_underlay(path, s.running_len)] if s.underlay and sh.stroke_width_mm >= 2 else []
                        objs.append(StitchObject(oid, "satin", tid(sh.stroke),
                                                 [satin_stitch(path, sh.stroke_width_mm, s.satin_spacing, s.satin_pull_comp)], under))
                    else:
                        objs.append(StitchObject(oid, "running", tid(sh.stroke), [running_stitch(path, s.running_len)]))
        except DigitizingError as e:
            notes.append(f"{sh.id}: skipped ({e})")
    return build_pattern(objs, threads, name), notes
