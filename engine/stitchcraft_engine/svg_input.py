"""Minimal, strict SVG reader. Unsupported features raise or warn - never silently distort."""
from __future__ import annotations
import math, re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional
from .geometry import Point


class UnsupportedSvg(ValueError):
    pass


@dataclass
class Shape:
    id: str
    rings: List[List[Point]]
    closed: bool
    fill: Optional[str]
    stroke: Optional[str]
    stroke_width_mm: float


@dataclass
class SvgDoc:
    shapes: List[Shape] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0


NAMED = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000", "blue": "#0000ff",
         "yellow": "#ffff00", "orange": "#ffa500", "pink": "#ffc0cb", "purple": "#800080", "brown": "#a52a2a",
         "gray": "#808080", "grey": "#808080", "gold": "#ffd700", "maroon": "#800000"}
_UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4, "px": 25.4 / 96, "pt": 25.4 / 72, "": 25.4 / 96}
_NUM = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"


def _len_mm(v: Optional[str]) -> Optional[float]:
    if not v:
        return None
    m = re.fullmatch(rf"\s*({_NUM})\s*([a-z]*)\s*", v)
    if not m or m.group(2) not in _UNITS:
        return None
    return float(m.group(1)) * _UNITS[m.group(2)]


def _color(v: Optional[str], warn: List[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip().lower()
    if v in ("none", "transparent"):
        return None
    if re.fullmatch(r"#[0-9a-f]{6}", v):
        return v
    if re.fullmatch(r"#[0-9a-f]{3}", v):
        return "#" + "".join(c * 2 for c in v[1:])
    if v in NAMED:
        return NAMED[v]
    warn.append(f"Unsupported colour {v!r}; using black")
    return "#000000"


def _bez(p0, p1, p2, p3, n=16):
    return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * d
                  for a, b, c, d in zip(p0, p1, p2, p3)) for t in (i / n for i in range(1, n + 1))]


def parse_path(d: str):
    toks = re.findall(rf"[MmLlHhVvCcQqZzSsTtAa]|{_NUM}", d)
    i, cmd, x, y, sx, sy = 0, None, 0.0, 0.0, 0.0, 0.0
    rings, cur, closed_flags = [], [], []
    def num():
        nonlocal i
        v = float(toks[i]); i += 1; return v
    while i < len(toks):
        if re.fullmatch(r"[A-Za-z]", toks[i]):
            cmd = toks[i]; i += 1
            if cmd in "Zz":
                if cur:
                    rings.append(cur); closed_flags.append(True); cur = []
                x, y = sx, sy
                continue
        if cmd in "SsTtAa":
            raise UnsupportedSvg(f"path command {cmd!r} not supported; convert to cubic curves/lines")
        rel = cmd.islower(); c = cmd.upper()
        if c == "M":
            if cur:
                rings.append(cur); closed_flags.append(False)
            nx, ny = num(), num()
            x, y = (x + nx, y + ny) if rel else (nx, ny)
            sx, sy = x, y; cur = [(x, y)]
            cmd = "l" if rel else "L"
        elif c == "L":
            nx, ny = num(), num(); x, y = (x + nx, y + ny) if rel else (nx, ny); cur.append((x, y))
        elif c == "H":
            nx = num(); x = x + nx if rel else nx; cur.append((x, y))
        elif c == "V":
            ny = num(); y = y + ny if rel else ny; cur.append((x, y))
        elif c == "C":
            v = [num() for _ in range(6)]
            if rel: v = [v[k] + (x if k % 2 == 0 else y) for k in range(6)]
            cur += _bez((x, y), (v[0], v[1]), (v[2], v[3]), (v[4], v[5])); x, y = v[4], v[5]
        elif c == "Q":
            v = [num() for _ in range(4)]
            if rel: v = [v[k] + (x if k % 2 == 0 else y) for k in range(4)]
            p0 = (x, y); c1 = (p0[0] + 2 / 3 * (v[0] - p0[0]), p0[1] + 2 / 3 * (v[1] - p0[1]))
            c2 = (v[2] + 2 / 3 * (v[0] - v[2]), v[3] + 2 / 3 * (v[1] - v[3]))
            cur += _bez(p0, c1, c2, (v[2], v[3])); x, y = v[2], v[3]
    if cur:
        rings.append(cur); closed_flags.append(False)
    return rings, closed_flags


def parse_svg(text: str) -> SvgDoc:
    root = ET.fromstring(text)
    doc = SvgDoc()
    vb = root.get("viewBox")
    w, h = _len_mm(root.get("width")), _len_mm(root.get("height"))
    scale = _UNITS[""]
    if vb:
        vx, vy, vw, vh = [float(v) for v in re.split(r"[ ,]+", vb.strip())]
        if w:
            scale = w / vw
        doc.width_mm, doc.height_mm = vw * scale, vh * scale
    else:
        doc.width_mm, doc.height_mm = (w or 0), (h or 0)
    strip = lambda t: t.split("}")[-1]

    def walk(el, inherited):
        tag = strip(el.tag)
        st = dict(inherited)
        style = dict(kv.split(":", 1) for kv in (el.get("style") or "").split(";") if ":" in kv)
        for k in ("fill", "stroke", "stroke-width"):
            v = style.get(k, el.get(k))
            if v is not None:
                st[k] = v.strip()
        if el.get("transform"):
            doc.warnings.append(f"<{tag}> has a transform which is not applied; flatten transforms in your vector editor")
        rings, closed, default_fill = None, True, "black"
        try:
            if tag == "path":
                rings, flags = parse_path(el.get("d", "")); closed = all(flags) if flags else False
            elif tag in ("polygon", "polyline"):
                n = [float(v) for v in re.findall(_NUM, el.get("points", ""))]
                rings = [list(zip(n[0::2], n[1::2]))]; closed = tag == "polygon"
                default_fill = "black" if closed else "none"
            elif tag == "rect":
                x, y, rw, rh = (float(el.get(k, 0)) for k in ("x", "y", "width", "height"))
                if el.get("rx") or el.get("ry"):
                    raise UnsupportedSvg("rounded rect not supported")
                rings = [[(x, y), (x + rw, y), (x + rw, y + rh), (x, y + rh)]]
            elif tag in ("circle", "ellipse"):
                cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
                rx = float(el.get("r", el.get("rx", 0))); ry = float(el.get("r", el.get("ry", 0)))
                rings = [[(cx + rx * math.cos(2 * math.pi * k / 48), cy + ry * math.sin(2 * math.pi * k / 48)) for k in range(48)]]
            elif tag == "line":
                rings = [[(float(el.get("x1", 0)), float(el.get("y1", 0))), (float(el.get("x2", 0)), float(el.get("y2", 0)))]]
                closed, default_fill = False, "none"
        except UnsupportedSvg as e:
            raise UnsupportedSvg(f"{el.get('id', tag)}: {e}")
        if rings:
            fill = _color(st.get("fill", default_fill), doc.warnings) if closed else _color(st.get("fill", "none"), doc.warnings)
            if not closed:
                fill = None
            stroke = _color(st.get("stroke"), doc.warnings)
            sw = (_len_mm(st.get("stroke-width", "1")) or 0) / _UNITS[""] * scale if stroke else 0.0
            if fill or stroke:
                doc.shapes.append(Shape(el.get("id") or f"{tag}{len(doc.shapes) + 1}",
                                        [[(px * scale, py * scale) for px, py in r] for r in rings if len(r) >= 2],
                                        closed, fill, stroke, sw))
        for ch in el:
            walk(ch, st)
    walk(root, {})
    return doc
