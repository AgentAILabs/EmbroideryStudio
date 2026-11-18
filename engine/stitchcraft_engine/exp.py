"""Melco EXP writer (no header, no palette: colour is only a 'colour change' command, so there is nothing vendor-specific to get wrong).
Record layout (units 0.1 mm, +Y up like DST):
    stitch        dx dy                      two signed bytes
    jump          0x80 0x04 dx dy
    trim          0x80 0x02 0x00 0x00
    colour change 0x80 0x01 0x00 0x00
Moves are limited to +/-127 per axis (0x80 is the escape byte, so -128 is never written); longer moves are split.
VALIDATION: tests pin hand-written byte vectors, and tests/test_crosscheck.py compares the result with pyembroidery's reader in CI.
Anything the cross-check disagrees with is a bug here, not there."""
from __future__ import annotations
import math
from typing import List
from .model import Cmd, Pattern

UNITS_PER_MM = 10
MAX_STEP = 127
ESC = 0x80


class ExpError(ValueError):
    pass


def _b(v: int) -> int:
    if not -MAX_STEP <= v <= MAX_STEP:
        raise ExpError(f"delta {v} outside +/-{MAX_STEP}")
    return v & 0xFF


def write_exp(pattern: Pattern, center: bool = True) -> bytes:
    bb = pattern.bbox()
    if bb is None:
        raise ExpError("pattern has no stitches")
    ox = (bb[0] + bb[2]) / 2 if center else 0.0
    oy = (bb[1] + bb[3]) / 2 if center else 0.0
    out = bytearray()
    cx = cy = 0
    for s in pattern.stitches:
        if s.cmd == Cmd.END:
            break
        if s.cmd == Cmd.COLOR_CHANGE:
            out += bytes([ESC, 0x01, 0x00, 0x00]); continue
        if s.cmd == Cmd.TRIM:
            out += bytes([ESC, 0x02, 0x00, 0x00]); continue
        tx = round((s.x - ox) * UNITS_PER_MM)
        ty = round(-(s.y - oy) * UNITS_PER_MM)
        dx, dy = tx - cx, ty - cy
        n = max(1, math.ceil(max(abs(dx), abs(dy)) / MAX_STEP))
        px, py = cx, cy
        for k in range(1, n + 1):
            nx, ny = cx + round(dx * k / n), cy + round(dy * k / n)
            if s.cmd == Cmd.JUMP:
                out += bytes([ESC, 0x04, _b(nx - px), _b(ny - py)])
            else:
                out += bytes([_b(nx - px), _b(ny - py)])
            px, py = nx, ny
        cx, cy = tx, ty
    return bytes(out)


def read_exp(data: bytes):
    """Independent minimal reader for tests: returns [(kind, dx, dy)] with kind in stitch/jump/trim/color_change."""
    recs, i = [], 0
    sb = lambda v: v - 256 if v > 127 else v
    while i < len(data):
        if data[i] == ESC:
            if i + 3 >= len(data):
                raise ExpError("truncated control record")
            code = data[i + 1]
            kind = {0x01: "color_change", 0x02: "trim", 0x04: "jump"}.get(code)
            if kind is None:
                raise ExpError(f"unknown control code 0x{code:02x}")
            recs.append((kind, sb(data[i + 2]), sb(data[i + 3])) if kind == "jump" else (kind, 0, 0)); i += 4
        else:
            if i + 1 >= len(data):
                raise ExpError("truncated stitch record")
            recs.append(("stitch", sb(data[i]), sb(data[i + 1]))); i += 2
    return recs
