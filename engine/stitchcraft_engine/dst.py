"""Tajima DST writer and an independent reader (used for round-trip validation).
Units: DST = 0.1 mm, Y up. Engine = mm, Y down. One record = 3 bytes, max +/-121 units per axis."""
from __future__ import annotations
import hashlib, math
from dataclasses import dataclass, field
from typing import List, Tuple
from .model import Cmd, Pattern

UNITS_PER_MM = 10
MAX_DELTA = 121          # 1+3+9+27+81 per axis
HEADER_SIZE = 512
DEFAULT_TRIM_JUMPS = 3   # DST has no trim opcode; trims are emulated by consecutive jumps. MACHINE-DEPENDENT: verify.

_WEIGHTS = (1, 3, 9, 27, 81)
# Tajima DST record layout (weight -> (byte, plus_bit, minus_bit)), +Y = up (north).
#   byte 0: x+1 0x01  x-1 0x02  x+9 0x04  x-9 0x08  |  y-1 0x40  y+1 0x80  y-9 0x10  y+9 0x20
#   byte 1: x+3 0x01  x-3 0x02  x+27 0x04 x-27 0x08 |  y-3 0x40  y+3 0x80  y-27 0x10 y+27 0x20
#   byte 2: x+81 0x04 x-81 0x08 |  y-81 0x10 y+81 0x20 |  always 0x03 | 0x80 = jump, 0xC0 = colour change, 0xF0 = end
# BUG HISTORY: the first version had the X and Y tables swapped (found only when CI compared our output with the
# independent pyembroidery reader - our own reader used the same table, so round trips could not see it).
# tests/test_engine.py now pins hand-written byte vectors that do not depend on these tables.
_X_BITS = {1: (0, 0x01, 0x02), 3: (1, 0x01, 0x02), 9: (0, 0x04, 0x08), 27: (1, 0x04, 0x08), 81: (2, 0x04, 0x08)}
_Y_BITS = {1: (0, 0x80, 0x40), 3: (1, 0x80, 0x40), 9: (0, 0x20, 0x10), 27: (1, 0x20, 0x10), 81: (2, 0x20, 0x10)}
FLAG_JUMP, FLAG_COLOR, FLAG_END = 0x80, 0xC0, 0xF0


class DstError(ValueError):
    pass


def _ternary(v: int) -> List[int]:
    if abs(v) > MAX_DELTA:
        raise DstError(f"delta {v} exceeds +/-{MAX_DELTA}")
    digits = []
    for _ in _WEIGHTS:
        r = v % 3
        d = 0 if r == 0 else (1 if r == 1 else -1)
        digits.append(d)
        v = (v - d) // 3
    assert v == 0
    return digits


def encode_record(dx: int, dy_up: int, flag: int = 0) -> bytes:
    b = [0, 0, 0x03]
    for axis, table in ((dx, _X_BITS), (dy_up, _Y_BITS)):
        for w, d in zip(_WEIGHTS, _ternary(axis)):
            if d:
                byte, plus, minus = table[w]
                b[byte] |= plus if d > 0 else minus
    b[2] |= flag
    return bytes(b)


def decode_record(rec: bytes) -> Tuple[int, int, str]:
    dx = dy = 0
    for w in _WEIGHTS:
        for table, name in ((_X_BITS, "x"), (_Y_BITS, "y")):
            byte, plus, minus = table[w]
            v = (w if rec[byte] & plus else 0) - (w if rec[byte] & minus else 0)
            if name == "x":
                dx += v
            else:
                dy += v
    # byte 2 also carries the x+/-81 bits (0x20/0x10), so only trust the high flag bits (0xC0) and treat
    # END (0xF3) / colour change (0xC3) as control records only when they carry no movement.
    f = rec[2] & 0xC0
    if dx == 0 and dy == 0 and (rec[2] & 0xF0) == FLAG_END:
        cmd = "end"
    elif f == 0xC0 and dx == 0 and dy == 0:
        cmd = "color_change"
    elif f == FLAG_JUMP:
        cmd = "jump"
    else:
        cmd = "stitch"
    return dx, dy, cmd


@dataclass
class DstResult:
    data: bytes
    sha256: str
    record_count: int
    extents_units: Tuple[int, int, int, int]  # +x, -x, +y, -y
    warnings: List[str] = field(default_factory=list)


def write_dst(pattern: Pattern, center: bool = True, trim_jumps: int = DEFAULT_TRIM_JUMPS) -> DstResult:
    bb = pattern.bbox()
    if bb is None:
        raise DstError("pattern has no stitches")
    ox = (bb[0] + bb[2]) / 2 if center else 0.0
    oy = (bb[1] + bb[3]) / 2 if center else 0.0
    warnings: List[str] = []
    recs: List[bytes] = []
    cx = cy = 0          # absolute DST units, origin = design centre
    colors = 0
    xs, ys = [0], [0]
    ended = False

    for s in pattern.stitches:
        if s.cmd == Cmd.END:
            recs.append(encode_record(0, 0, FLAG_END))
            ended = True
            break
        if s.cmd == Cmd.COLOR_CHANGE:
            recs.append(encode_record(0, 0, FLAG_COLOR))
            colors += 1
            continue
        if s.cmd == Cmd.TRIM:
            recs += [encode_record(0, 0, FLAG_JUMP)] * trim_jumps
            continue
        tx = round((s.x - ox) * UNITS_PER_MM)
        ty = round(-(s.y - oy) * UNITS_PER_MM)
        dx, dy = tx - cx, ty - cy
        n = max(1, math.ceil(max(abs(dx), abs(dy)) / MAX_DELTA))
        if n > 1 and s.cmd == Cmd.STITCH:
            warnings.append(f"stitch longer than 12.1 mm was split into {n} records")
        px, py = cx, cy
        for k in range(1, n + 1):
            nx, ny = cx + round(dx * k / n), cy + round(dy * k / n)
            recs.append(encode_record(nx - px, ny - py, FLAG_JUMP if s.cmd == Cmd.JUMP else 0))
            px, py = nx, ny
        cx, cy = tx, ty
        xs.append(cx); ys.append(cy)
    if not ended:
        raise DstError("pattern has no END command")

    ext = (max(xs), -min(xs), max(ys), -min(ys))
    from .machine_compat import label_for
    label = label_for(pattern.name)
    header = (f"LA:{label:<16}\rST:{len(recs):7d}\rCO:{colors:3d}\r+X:{ext[0]:5d}\r-X:{ext[1]:5d}\r"
              f"+Y:{ext[2]:5d}\r-Y:{ext[3]:5d}\rAX:+{0:5d}\rAY:+{0:5d}\rMX:+{0:5d}\rMY:+{0:5d}\rPD:******\r").encode("ascii")
    header += b"\x1a"
    header = header.ljust(HEADER_SIZE, b" ")
    data = header + b"".join(recs)
    return DstResult(data, hashlib.sha256(data).hexdigest(), len(recs), ext, warnings)


@dataclass
class DstFile:
    header: dict
    records: List[Tuple[int, int, str]]
    positions: List[Tuple[int, int]]       # absolute (x, y_up) in 0.1 mm after each record
    color_changes: int
    ends_properly: bool


def read_dst(data: bytes) -> DstFile:
    if len(data) < HEADER_SIZE + 3:
        raise DstError("file too short for DST")
    header = {}
    for line in data[:HEADER_SIZE].split(b"\x1a")[0].split(b"\r"):
        if b":" in line:
            k, v = line.decode("ascii", "replace").split(":", 1)
            header[k.strip()] = v.strip()
    body = data[HEADER_SIZE:]
    # Real files (Wilcom, Pulse, Tajima DGML ...) put a lone 0x1A end-of-file byte after the END record. Accept that, but a
    # record area that is cut off before END is still an error.
    end_at = next((i for i in range(0, len(body) - 2, 3) if decode_record(body[i:i + 3])[2] == "end"), None)
    if end_at is not None:
        extra = body[end_at + 3:]
        if extra.strip(b"\x1a\x00"):
            raise DstError("unexpected data after the END record")
        body = body[:end_at + 3]
    elif len(body) % 3:
        raise DstError("record area is not a multiple of 3 bytes")
    recs, pos, x, y, cc, ended = [], [], 0, 0, 0, False
    for i in range(0, len(body), 3):
        dx, dy, cmd = decode_record(body[i:i + 3])
        recs.append((dx, dy, cmd))
        x += dx; y += dy
        pos.append((x, y))
        if cmd == "color_change":
            cc += 1
        if cmd == "end":
            ended = i + 3 == len(body)
            break
    return DstFile(header, recs, pos, cc, ended)
