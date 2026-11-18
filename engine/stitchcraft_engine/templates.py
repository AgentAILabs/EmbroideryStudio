"""Starter templates: stitched border motifs and NON-stitched neckline guides.
Geometry in mm, y down, centred on the origin. Neckline outlines are generic proportions to draw against,
not tailoring standards - adjust to your own pattern. Sizes for necklines are entered in inches (shop convention)."""
from __future__ import annotations
import math
from typing import Callable, Dict, List

IN = 25.4
MAX_OBJECTS = 150


def _clamp(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return min(max(v, lo), hi)


def border_petal(p, color):
    L, w, h = _clamp(p.get("length_mm"), 20, 600, 80), _clamp(p.get("petal_w"), 3, 12, 6), _clamp(p.get("petal_h"), 4, 20, 10)
    n = max(1, min(MAX_OBJECTS, int(L // (w + 3))))
    pitch = L / n
    out = []
    for i in range(n):
        cx = -L / 2 + pitch * (i + 0.5)
        out.append({"type": "column", "color": color, "name": f"Petal {i + 1}",
                    "rail1": [[cx, -h / 2], [cx - w / 2, 0], [cx, h / 2]], "rail2": [[cx, -h / 2], [cx + w / 2, 0], [cx, h / 2]], "smooth": False})
    return out


def border_scallop(p, color):
    L, w, d = _clamp(p.get("length_mm"), 20, 600, 80), _clamp(p.get("scallop_w"), 5, 30, 10), _clamp(p.get("depth"), 1, 12, 4)
    n = max(1, min(MAX_OBJECTS, int(L // w)))
    pitch = L / n
    pts = []
    for i in range(n):
        x0 = -L / 2 + pitch * i
        pts += [[x0, d / 2], [x0 + pitch / 2, -d / 2]]
    pts.append([L / 2, d / 2])
    return [{"type": "run", "color": color, "name": "Scallop", "points": pts, "smooth": True, "params": {"stitch_len": 2.0}}]


def border_zigzag(p, color):
    L, step, amp, w = (_clamp(p.get("length_mm"), 20, 600, 80), _clamp(p.get("step"), 3, 20, 6),
                       _clamp(p.get("amp"), 1, 10, 3), _clamp(p.get("width"), 1, 5, 2))
    n = max(2, min(MAX_OBJECTS * 2, int(L // step)))
    pitch = L / n
    pts = [[-L / 2 + pitch * i, amp if i % 2 else -amp] for i in range(n + 1)]
    return [{"type": "satin", "color": color, "name": "Zigzag", "points": pts, "params": {"width": w}}]


def border_dots(p, color):
    L, d, gap = _clamp(p.get("length_mm"), 20, 600, 80), _clamp(p.get("dot_d"), 2, 8, 3.5), _clamp(p.get("gap"), 5, 30, 8)
    n = max(1, min(MAX_OBJECTS, int(L // gap)))
    pitch = L / n
    out = []
    for i in range(n):
        cx = -L / 2 + pitch * (i + 0.5)
        ring = [[cx + d / 2 * math.cos(k * math.pi / 8), d / 2 * math.sin(k * math.pi / 8)] for k in range(16)]
        out.append({"type": "fill", "color": color, "name": f"Dot {i + 1}", "rings": [ring], "params": {"underlay": "none"}})
    return out


def _guide(name, pts):
    return [{"type": "run", "color": "#6b7280", "name": name, "guide": True, "closed": True, "points": [[round(x, 3), round(y, 3)] for x, y in pts]}]


def _wd(p):
    return _clamp(p.get("width_in"), 2, 20, 7) * IN, _clamp(p.get("depth_in"), 1, 20, 6) * IN


def neck_round(p, color):
    W, D = _wd(p)
    pts = [(-W / 2 * math.cos(t), -D / 2 + D * math.sin(t)) for t in [math.pi * k / 40 for k in range(41)]]
    return _guide("Round neck guide", pts)


def neck_boat(p, color):
    W, D = _wd(p)
    pts = [(x, -D / 2 + D * (1 - abs(2 * x / W) ** 4)) for x in [-W / 2 + W * k / 40 for k in range(41)]]
    return _guide("Boat neck guide", pts)


def neck_v(p, color):
    W, D = _wd(p)
    return _guide("V neck guide", [(-W / 2, -D / 2), (0, D / 2), (W / 2, -D / 2)])


def neck_square(p, color):
    W, D = _wd(p)
    return _guide("Square neck guide", [(-W / 2, -D / 2), (-W / 2, D / 2), (W / 2, D / 2), (W / 2, -D / 2)])


def neck_back_u(p, color):
    W, D = _wd(p)
    r = W / 2
    yc = max(D / 2 - r, -D / 2)
    arc = [(r * math.cos(t), yc + min(r, D / 2 - yc) * math.sin(t)) for t in [math.pi - math.pi * k / 40 for k in range(41)]]
    return _guide("Back U-neck guide", [(-W / 2, -D / 2)] + arc + [(W / 2, -D / 2)])


_LEN = {"key": "length_mm", "label": "Length mm", "default": 80, "min": 20, "max": 600, "step": 5}
_NECK = [{"key": "width_in", "label": "Width (in)", "default": 7, "min": 2, "max": 20, "step": 0.5},
         {"key": "depth_in", "label": "Depth (in)", "default": 6, "min": 1, "max": 20, "step": 0.5}]
TEMPLATES: Dict[str, dict] = {
    "border_petal": {"label": "Petal border (stitched)", "group": "Borders", "params": [_LEN, {"key": "petal_w", "label": "Petal width mm", "default": 6, "min": 3, "max": 12, "step": 0.5}, {"key": "petal_h", "label": "Petal height mm", "default": 10, "min": 4, "max": 20, "step": 0.5}], "fn": border_petal},
    "border_scallop": {"label": "Scallop border (stitched)", "group": "Borders", "params": [_LEN, {"key": "scallop_w", "label": "Scallop width mm", "default": 10, "min": 5, "max": 30, "step": 1}, {"key": "depth", "label": "Depth mm", "default": 4, "min": 1, "max": 12, "step": 0.5}], "fn": border_scallop},
    "border_zigzag": {"label": "Zigzag satin border (stitched)", "group": "Borders", "params": [_LEN, {"key": "step", "label": "Step mm", "default": 6, "min": 3, "max": 20, "step": 1}, {"key": "amp", "label": "Height mm", "default": 3, "min": 1, "max": 10, "step": 0.5}, {"key": "width", "label": "Satin width mm", "default": 2, "min": 1, "max": 5, "step": 0.25}], "fn": border_zigzag},
    "border_dots": {"label": "Dot row (stitched)", "group": "Borders", "params": [_LEN, {"key": "dot_d", "label": "Dot size mm", "default": 3.5, "min": 2, "max": 8, "step": 0.5}, {"key": "gap", "label": "Spacing mm", "default": 8, "min": 5, "max": 30, "step": 1}], "fn": border_dots},
    "neck_round": {"label": "Round neck (guide)", "group": "Neckline guides (not stitched)", "params": _NECK, "fn": neck_round},
    "neck_boat": {"label": "Boat neck (guide)", "group": "Neckline guides (not stitched)", "params": _NECK, "fn": neck_boat},
    "neck_v": {"label": "V neck (guide)", "group": "Neckline guides (not stitched)", "params": _NECK, "fn": neck_v},
    "neck_square": {"label": "Square neck (guide)", "group": "Neckline guides (not stitched)", "params": _NECK, "fn": neck_square},
    "neck_back_u": {"label": "Back U-neck (guide)", "group": "Neckline guides (not stitched)", "params": _NECK, "fn": neck_back_u},
}


def catalog() -> List[dict]:
    return [{"id": k, "label": v["label"], "group": v["group"], "params": v["params"]} for k, v in TEMPLATES.items()]


def build(template_id: str, params: dict, color: str = "#c8102e") -> List[dict]:
    t = TEMPLATES.get(template_id)
    if not t:
        raise ValueError(f"unknown template {template_id!r}")
    if not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
        color = "#c8102e"
    return t["fn"](params or {}, color)
