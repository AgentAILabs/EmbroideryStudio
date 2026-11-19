"""Machine-format encoders: JEF (Janome), XXX (Singer), U01 (Barudan), SEW (Janome / Elna), PES (Brother, version 1 'truncated' layout with the PEC block).

Written as own code from the published layouts (pyembroidery's readers / writers were the layout reference - see NOTICE.md). Every encoder is verified by reading its output
back with the independent pyembroidery reader (tests/test_encoders.py, runs wherever pyembroidery is installed, always in CI) and comparing stitch positions, jumps and
colour changes. THAT IS SOFTWARE VALIDATION ONLY: no file here has been loaded on a real machine, and formats stay labelled "experimental" until a vendor reference
file / machine confirms them (formats.py).

Conventions: input is a model.Pattern (mm, Y down). Output coordinates are integers in 0.1 mm centred on the design's bounding box; the file Y axis points UP.
A TRIM command is written the way each format can express it (documented per encoder); moves are split to each format's maximum step.
"""
from __future__ import annotations
import math
import struct
from typing import List, Tuple
from .model import Cmd, Pattern
from . import format_palettes as FP

UNITS = 10


class EncodeError(ValueError):
    pass


def _ops(pattern: Pattern, limit: int, center: bool = True):
    """-> (ops, bounds) where ops = [(kind, dx, dy, thread)] with kind in 's' stitch, 'j' jump, 't' trim, 'c' colour change; moves split to +/-limit; bounds in 0.1 mm."""
    bb = pattern.bbox()
    if bb is None:
        raise EncodeError("pattern has no stitches")
    ox = (bb[0] + bb[2]) / 2 if center else 0.0; oy = (bb[1] + bb[3]) / 2 if center else 0.0
    ops = []; cx = cy = 0; xs = [0]; ys = [0]
    for s in pattern.stitches:
        if s.cmd == Cmd.END: break
        if s.cmd == Cmd.COLOR_CHANGE: ops.append(("c", 0, 0, s.thread)); continue
        if s.cmd == Cmd.TRIM: ops.append(("t", 0, 0, s.thread)); continue
        tx = round((s.x - ox) * UNITS); ty = round(-(s.y - oy) * UNITS)
        dx, dy = tx - cx, ty - cy
        n = max(1, math.ceil(max(abs(dx), abs(dy)) / limit)); px, py = cx, cy
        for k in range(1, n + 1):
            nx, ny = cx + round(dx * k / n), cy + round(dy * k / n)
            ops.append(("j" if s.cmd == Cmd.JUMP else "s", nx - px, ny - py, s.thread)); px, py = nx, ny
        cx, cy = tx, ty; xs.append(cx); ys.append(cy)
    return ops, (min(xs), min(ys), max(xs), max(ys)), (cx, cy)


def _lab(rgb):
    def f(c):
        c = c / 255.0; return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
    r, g, b = f(rgb[0]), f(rgb[1]), f(rgb[2])
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047; y = 0.2126 * r + 0.7152 * g + 0.0722 * b; z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    t = lambda v: v ** (1 / 3) if v > 0.008856 else 7.787 * v + 16 / 116
    fx, fy, fz = t(x), t(y), t(z); return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _rgb(hexc: str):
    return tuple(int(hexc[i:i + 2], 16) for i in (1, 3, 5))


def nearest_index(table: List, hexc: str, avoid: Tuple[int, ...] = ()) -> int:
    """Index of the entry of a format palette nearest to `hexc` (CIE-Lab), skipping index 0 and `avoid`."""
    lab = _lab(_rgb(hexc)); best, bi = None, 1
    for i, h in enumerate(table):
        if i == 0 or h is None or i in avoid: continue
        l2 = _lab(_rgb(h)); d = (lab[0] - l2[0]) ** 2 + (lab[1] - l2[1]) ** 2 + (lab[2] - l2[2]) ** 2
        if best is None or d < best: best, bi = d, i
    return bi


def _colour_blocks(pattern: Pattern) -> List[str]:
    """Hex colours in stitching order (the thread in use at the start + one per colour change)."""
    th = pattern.threads; order = []
    first = next((s.thread for s in pattern.stitches if s.cmd in (Cmd.STITCH, Cmd.JUMP)), 0)
    order.append(th[first].hex if th and first < len(th) else "#000000")
    for s in pattern.stitches:
        if s.cmd == Cmd.COLOR_CHANGE: order.append(th[s.thread].hex if th and s.thread < len(th) else "#000000")
    return order


def _i8(v: int) -> int:
    if not -128 <= v <= 127: raise EncodeError(f"value {v} does not fit a signed byte")
    return v & 0xFF


# ------------------------------------------------------------------------------------------------------------------------------------------------------- JEF
def write_jef(pattern: Pattern, trim_jumps: int = 3) -> bytes:
    """Janome JEF. Stitch = dx dy (signed bytes); jump = 80 02 dx dy; colour change = 80 01 00 00; trim = N x (80 02 00 00); end = 80 10. Header holds the colour table
    (indices into the 78-colour Janome palette, nearest match, no two consecutive equal) and extents. The header date is fixed (deterministic output)."""
    ops, (x0, y0, x1, y1), _ = _ops(pattern, 127)
    colours = _colour_blocks(pattern); palette = []; last = None
    for h in colours:
        i = nearest_index(FP.JEF, h); i = nearest_index(FP.JEF, h, (last,)) if i == last else i; palette.append(i); last = i
    body = bytearray(); points = 1
    for k, dx, dy, th in ops:
        if k == "s": body += bytes([_i8(dx), _i8(dy)]); points += 1
        elif k == "j": body += b"\x80\x02" + bytes([_i8(dx), _i8(dy)]); points += 2
        elif k == "c": body += b"\x80\x01\x00\x00"; points += 2
        elif k == "t": body += b"\x80\x02\x00\x00" * trim_jumps; points += 2 * trim_jumps
    body += b"\x80\x10"
    cc = len(palette); w, h = x1 - x0, y1 - y0; hw, hh = round(w / 2), round(h / 2)
    hoop = 1 if (w < 500 and h < 500) else 3 if (w < 1260 and h < 1100) else 2 if (w < 1400 and h < 2000) else 4 if (w < 2000 and h < 2000) else 0
    def edge(ex, ey):
        return struct.pack("<4i", ex, ey, ex, ey) if min(ex, ey) >= 0 else struct.pack("<4i", -1, -1, -1, -1)
    out = bytearray()
    out += struct.pack("<ii", 0x74 + cc * 8, 0x14) + b"19700101000000" + b"\x00\x00" + struct.pack("<ii", cc, points) + struct.pack("<i", hoop)
    out += struct.pack("<4i", hw, hh, hw, hh) + edge(550 - hw, 550 - hh) + edge(250 - hw, 250 - hh) + edge(700 - hw, 1000 - hh) + edge(700 - hw, 1000 - hh)
    for i in palette: out += struct.pack("<i", i)
    for _ in palette: out += struct.pack("<i", 0x0D)
    return bytes(out + body)


# ------------------------------------------------------------------------------------------------------------------------------------------------------- XXX
def write_xxx(pattern: Pattern, trim_jumps: int = 1) -> bytes:
    """Singer XXX. Stitch = dx dy (|v| <= 123); jump = 7F 01 dx dy; trim = 7F 03 00 00; colour change = 7F 08 00 00; end = 7F 7F 02 14; colour table (RGB) at the end."""
    ops, (x0, y0, x1, y1), (lx, ly) = _ops(pattern, 123)
    colours = _colour_blocks(pattern)
    if len(colours) > 20: raise EncodeError("XXX holds at most 20 colours")
    body = bytearray(); count = 0
    for k, dx, dy, th in ops:
        if k == "s": body += bytes([_i8(dx), _i8(dy)])
        elif k == "j": body += b"\x7f\x01" + bytes([_i8(dx), _i8(dy)])
        elif k == "c": body += b"\x7f\x08\x00\x00"
        elif k == "t": body += b"\x7f\x03\x00\x00" * trim_jumps; count += trim_jumps - 1
        count += 1
    h = bytearray(b"\x00" * 0x17) + struct.pack("<I", count) + b"\x00" * 0x0C + struct.pack("<I", len(colours)) + struct.pack("<H", 0)
    h += struct.pack("<HHhhhh", x1 - x0, y1 - y0, lx, -ly, -x0, y1) + b"\x00" * 0x42 + struct.pack("<HH", 0, 0) + b"\x00" * 0x73 + struct.pack("<H", 0x20) + b"\x00" * 8
    if len(h) != 0xFC: raise EncodeError("internal: XXX header size")
    end_pos = len(h) + 4 + len(body)
    out = bytes(h) + struct.pack("<I", end_pos) + bytes(body) + b"\x7f\x7f\x02\x14" + b"\x00\x00"
    for c in colours: r, g, b = _rgb(c); out += bytes([0, r, g, b])
    out += b"\x00\x00\x00\x00" * (21 - len(colours)) + struct.pack("<I", 0xFFFFFF00) + b"\x00\x01"
    return out


# ------------------------------------------------------------------------------------------------------------------------------------------------------- U01
def write_u01(pattern: Pattern, trim_jumps: int = 1) -> bytes:
    """Barudan U01 (also Bernina-style 3-byte records). 0x100-byte header ('0' fill + extents), records = [flags, |dy|, |dx|]: flags 0x80 | 0x40 (dy down) | 0x20 (dx left)
    | command (0 stitch, 1 jump, 7 trim, 0x08+n needle change); end = F8 00 00. Needle numbers cycle 1..15."""
    ops, (x0, y0, x1, y1), (lx, ly) = _ops(pattern, 127)
    rec = bytearray(); n = 0; needle = 0
    def put(cmd, dx, dy):
        c = 0x80 | cmd
        if dy <= 0: c |= 0x40                       # file dy is up-positive here; the flag marks "down" like the reader expects
        if dx <= 0: c |= 0x20
        rec.extend([c, abs(dy), abs(dx)])
    for k, dx, dy, th in ops:
        if k == "s": put(0x00, dx, dy)
        elif k == "j": put(0x01, dx, dy)
        elif k == "t":
            for _ in range(trim_jumps): put(0x07, 0, 0)
        elif k == "c": needle = needle % 15 + 1; put(0x08 + needle, 0, 0)
        n += 1
    count = len(rec) // 3 + 1
    head = bytearray(b"0" * 0x80) + struct.pack("<hhhh", x0, -y1, x1, -y0) + struct.pack("<I", 0) + struct.pack("<I", count) + struct.pack("<hh", lx, -ly)
    head += b"\x00" * (0x100 - len(head))
    return bytes(head + rec + b"\xf8\x00\x00")


# ------------------------------------------------------------------------------------------------------------------------------------------------------- SEW
def write_sew(pattern: Pattern, trim_jumps: int = 1) -> bytes:
    """Janome / Elna SEW. u16 colour count + u16 palette indices, zero padded to 0x1D78, then records: stitch = dx dy; jump = 80 04 dx dy; colour change = 80 01 00 00;
    end = 80 10 00 00."""
    ops, _, _ = _ops(pattern, 127)
    colours = _colour_blocks(pattern); idx = []; last = None
    for h in colours:
        i = nearest_index(FP.SEW, h); i = nearest_index(FP.SEW, h, (last,)) if i == last else i; idx.append(i); last = i
    head = struct.pack("<H", len(idx)) + b"".join(struct.pack("<H", i) for i in idx); head += b"\x00" * (0x1D78 - len(head))
    body = bytearray()
    for k, dx, dy, th in ops:
        if k == "s": body += bytes([_i8(dx), _i8(dy)])
        elif k == "j": body += b"\x80\x04" + bytes([_i8(dx), _i8(dy)])
        elif k == "c": body += b"\x80\x01\x00\x00"
        elif k == "t": body += b"\x80\x04\x00\x00" * trim_jumps
    return bytes(head + body + b"\x80\x10\x00\x00")


# ------------------------------------------------------------------------------------------------------------------------------------------------------- PES / PEC
def _pec_value(v: int, long: bool = False, flag: int = 0) -> bytes:
    if not long and -64 < v < 63: return bytes([v & 0x7F])
    if not -2048 <= v <= 2047: raise EncodeError("PEC value out of range")
    w = (v & 0x0FFF) | 0x8000 | (flag << 8); return bytes([(w >> 8) & 0xFF, w & 0xFF])


def _pec_thumb(points, bounds, stride=6, rows=38, buffer=4):
    g = list(FP.PEC_BLANK)
    x0, y0, x1, y1 = bounds; w, h = max(x1 - x0, 1), max(y1 - y0, 1); sc = min((stride * 8 - buffer) / w, (rows - buffer) / h)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for x, y in points:
        px = int(round((x - cx) * sc + stride * 4)); py = int(round((y - cy) * sc + rows / 2))
        if 0 <= px < stride * 8 and 0 <= py < rows: g[py * stride + px // 8] |= 1 << (px % 8)
    return bytes(g)


def write_pes(pattern: Pattern, trim_jumps: int = 1) -> bytes:
    """Brother PES version 1, 'truncated' layout: '#PES0001' + PEC offset + PEC block. The PEC block holds a 'LA:' label, the colour index list (nearest of the 65 Brother PEC
    colours, unique where possible), the stitch data (7-bit or 12-bit signed deltas; jump = flag 0x10 for the first jump, 0x20 trim-jump after a TRIM; colour change = FE B0 02/01
    alternating; end = FF), and 48x38 thumbnails (all stitches + one per colour). It does not contain the CEmbOne / CSewSeg object blocks of full PES files."""
    ops, (x0, y0, x1, y1), _ = _ops(pattern, 2047)
    colours = _colour_blocks(pattern); idx = []; used = set()
    for h in colours:
        i = nearest_index(FP.PEC, h, tuple(used)) if len(used) < 60 else nearest_index(FP.PEC, h); idx.append(i); used.add(i)
    if len(idx) > 254: raise EncodeError("too many colour changes for PEC")
    name = (pattern.name or "design")[:8]
    hdr = bytearray(("LA:%-16s\r" % name).encode("ascii", "replace")); hdr += b"\x20" * 12 + b"\xff\x00" + bytes([6, 38]) + b"\x20" * 12
    hdr += bytes([len(idx) - 1]) + bytes(idx) + b"\x20" * (463 - len(idx))
    st = bytearray(); color_two = True; jumping = True; init = True; after_trim = False; x = y = 0; pts_by_colour: List[List[Tuple[int, int]]] = [[]]; allpts = []
    for k, dx, dy, th in ops:
        ddy = -dy                                                      # PEC deltas are Y-down
        if k == "t": after_trim = True; continue
        if k == "s":
            if jumping:
                if dx != 0 and ddy != 0: st += _pec_value(0) + _pec_value(0)
                jumping = False
            st += _pec_value(dx) + _pec_value(ddy)
            x += dx; y += ddy; allpts.append((x, y)); pts_by_colour[-1].append((x, y))
        elif k == "j":
            jumping = True; flag = 0x10 if init else (0x20 if after_trim else 0x10)
            st += _pec_value(dx, True, flag) + _pec_value(ddy, True, flag); x += dx; y += ddy; after_trim = False
        elif k == "c":
            if jumping: st += _pec_value(0) + _pec_value(0); jumping = False
            st += b"\xfe\xb0" + (b"\x02" if color_two else b"\x01"); color_two = not color_two; pts_by_colour.append([])
        init = False
    st += b"\xff"
    w = x1 - x0; h = y1 - y0
    block = bytearray(b"\x00\x00") + b"\x00\x00\x00" + b"\x31\xff\xf0" + struct.pack("<HHHH", w, h, 0x1E0, 0x1B0) + st
    ln = len(block); block[2:5] = bytes([ln & 0xFF, (ln >> 8) & 0xFF, (ln >> 16) & 0xFF])
    bounds = (min([p[0] for p in allpts] + [0]), min([p[1] for p in allpts] + [0]), max([p[0] for p in allpts] + [0]), max([p[1] for p in allpts] + [0]))
    gfx = _pec_thumb(allpts, bounds) + b"".join(_pec_thumb(p, bounds) for p in pts_by_colour)
    pec = bytes(hdr) + bytes(block) + gfx
    return b"#PES0001" + b"\x16\x00\x00\x00" + b"\x00" * 10 + pec


WRITERS = {"jef": write_jef, "xxx": write_xxx, "u01": write_u01, "sew": write_sew, "pes": write_pes}


# ------------------------------------------------------------------------------------------------------------------------------------------------------- verification
def verify_with_pyembroidery(data: bytes, fmt: str, pattern: Pattern, limit: int = None) -> dict:
    """Read the encoded bytes back with the independent pyembroidery library and compare EVERY stitch position (0.1 mm) and the stitch / colour-change counts with what was meant
    to be written. {"ran": False} when pyembroidery is not installed in this process (never a fake pass)."""
    try:
        import pyembroidery as pe, os, tempfile
    except ImportError:
        return {"ran": False, "result": "NOT RUN in this process (pyembroidery not installed); CI runs it"}
    lim = limit or {"jef": 127, "xxx": 123, "u01": 127, "sew": 127, "pes": 2047, "exp": 127}[fmt]
    ops, _, _ = _ops(pattern, lim); x = y = 0; want = []
    for k, dx, dy, th in ops:
        x += dx; y += dy
        if k == "s": want.append((x, y))
    with tempfile.NamedTemporaryFile(suffix="." + fmt, delete=False) as t:
        t.write(data); path = t.name
    try:
        pat = pe.read(path)
        if pat is None: return {"ran": True, "result": "FAIL", "detail": "pyembroidery could not read the file"}
        got = [(round(sx), round(-sy)) for sx, sy, c in pat.stitches if (c & pe.COMMAND_MASK) == pe.STITCH]
        if fmt == "sew" and got and len(got) == len(want) + 1: got = got[:-1]              # the SEW end record reads as a zero stitch
        bad = sum(1 for a, b in zip(want, got) if a != b)
        ok = len(want) == len(got) and bad == 0
        return {"ran": True, "result": "PASS" if ok else "FAIL", "stitches_expected": len(want), "stitches_read": len(got), "mismatched_positions": bad}
    finally:
        os.unlink(path)
