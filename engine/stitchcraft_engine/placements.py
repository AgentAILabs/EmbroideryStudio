"""Placement sets and safe auto-correction.

One uploaded design -> the same design for each garment position (left / right / neck / ...), each one:
  transformed (true mirror, rotate, scale to a target size) -> auto-corrected -> generated -> verified -> named.

`autofix` is deliberately conservative: it only makes changes that cannot alter the look of a correct design
(centre / scale to fit the hoop, drop sub-visible specks, turn hairline columns into running stitch, remove duplicate points)
or that trade a little density for safety (spacing relief when needles would cluster). Every change is logged.
"""
import copy, math, re
from typing import Dict, List, Optional, Tuple

from .design import DEFAULTS, THREADS, _bbox, generate, machine, run_checks
from .geometry import polygon_area
from .stitches import polyline_length

# Standard placement names. `mirror` is relative to the side the uploaded artwork was drawn for (`source_side`).
PLACEMENTS = {
    "left":       {"label": "Left sleeve / left side",  "side": "left"},
    "right":      {"label": "Right sleeve / right side", "side": "right"},
    "neck":       {"label": "Neckline (front neck)",    "side": None},
    "back_neck":  {"label": "Back neck",                "side": None},
    "front":      {"label": "Front panel",              "side": None},
    "back":       {"label": "Back panel",               "side": None},
    "sleeve_left":  {"label": "Sleeve - left",          "side": "left"},
    "sleeve_right": {"label": "Sleeve - right",         "side": "right"},
    "center":     {"label": "Centre / single motif",    "side": None},
}
DEFAULT_SET = ["left", "right", "neck"]
MAX_SCALE = 3.0


def slug(s: str, default: str = "design") -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(s or "")).strip("_")[:40]
    return s or default


# ---------------------------------------------------------------- transform
def _pt(p, k, flip, cs, sn):
    x, y = p[0] * k, p[1] * k
    if flip:
        x = -x
    return [round(x * cs - y * sn, 3), round(y * cs + x * sn, 3)]


def transform_design(d: dict, scale: float = 1.0, mirror: bool = False, rotate: float = 0.0) -> dict:
    """Scale -> mirror left-right -> rotate (degrees, clockwise on screen) about the origin. Positions and sizes move; stitch
    parameters that are physical (satin width, spacing, stitch length, bead size) stay as they are. A mirrored tatami fill runs
    in the mirrored direction. Lettering is never mirrored (it would read backwards): only its position is mirrored."""
    d = copy.deepcopy(d)
    a = math.radians(rotate); cs, sn = math.cos(a), math.sin(a)
    for o in d.get("objects", []):
        t = o.get("type")
        if t == "text" and o.get("path"):
            o["height"] = round(float(o.get("height", 10)) * scale, 3)
            pth = [_pt(p, scale, mirror, cs, sn) for p in o["path"]]
            o["path"] = pth[::-1] if mirror else pth            # mirrored path is walked the other way so the text still reads left to right
            continue
        if t == "text":
            b = _bbox(o)
            cx, cy = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) if b else (o.get("x", 0), o.get("y", 0))
            ncx, ncy = _pt((cx, cy), scale, mirror, cs, sn)
            o["height"] = round(float(o.get("height", 10)) * scale, 3)
            nb = _bbox(dict(o, x=0, y=0)); w = (nb[2] - nb[0]) if nb else 0
            o["x"] = round(ncx - w / 2, 3); o["y"] = round(ncy - o["height"] / 2, 3)
            continue
        if t == "fill":
            ang = float(((o.get("params") or {})).get("angle", DEFAULTS["fill"]["angle"]))
            if mirror:
                ang = 180.0 - ang
            o["params"] = dict((o.get("params") or {}), angle=round((ang + rotate) % 180.0, 3))
        if "rings" in o:
            o["rings"] = [[_pt(p, scale, mirror, cs, sn) for p in r] for r in o["rings"]]
        for k in ("points", "rail1", "rail2"):
            if k in o:
                o[k] = [_pt(p, scale, mirror, cs, sn) for p in o[k]]
    return d


def design_bbox(d: dict) -> Optional[Tuple[float, float, float, float]]:
    bs = [_bbox(o) for o in d.get("objects", []) if not o.get("hidden") and not o.get("guide") and o.get("type") != "embellishment"]
    bs = [b for b in bs if b]
    if not bs:
        return None
    return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)


def centre_design(d: dict) -> dict:
    b = design_bbox(d)
    if not b:
        return d
    dx, dy = -(b[0] + b[2]) / 2, -(b[1] + b[3]) / 2
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return d
    d = copy.deepcopy(d)
    for o in d["objects"]:
        if o.get("type") == "text":
            o["x"] = round(o.get("x", 0) + dx, 3); o["y"] = round(o.get("y", 0) + dy, 3)
            if o.get("path"):
                o["path"] = [[round(p[0] + dx, 3), round(p[1] + dy, 3)] for p in o["path"]]
        for k in ("points", "rail1", "rail2"):
            if k in o:
                o[k] = [[round(p[0] + dx, 3), round(p[1] + dy, 3)] for p in o[k]]
        if "rings" in o:
            o["rings"] = [[[round(p[0] + dx, 3), round(p[1] + dy, 3)] for p in r] for r in o["rings"]]
    return d


# ---------------------------------------------------------------- auto-correction
def _dedupe(pts, eps=1e-3):
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > eps or abs(p[1] - out[-1][1]) > eps:
            out.append(p)
    return out


def _finite(pts):
    return all(isinstance(c, (int, float)) and math.isfinite(c) for p in pts for c in p[:2])


def autofix(design: dict, max_rounds: int = 3) -> Tuple[dict, List[str]]:
    """Returns (corrected design, human-readable log). Never raises on a design generate() can handle; never removes anything it
    cannot name in the log."""
    d = copy.deepcopy(design); log: List[str] = []
    hoop = d.setdefault("hoop", {"w": 100, "h": 100, "margin": 3})
    keep = []
    for o in d.get("objects", []):
        name = o.get("name") or o.get("id") or o.get("type")
        t = o.get("type")
        # --- geometry hygiene
        for k in ("points", "rail1", "rail2"):
            if k in o:
                if not _finite(o[k]):
                    log.append(f"removed '{name}': coordinates are not valid numbers"); o = None; break
                n0 = len(o[k]); o[k] = _dedupe(o[k])
                if len(o[k]) < n0:
                    log.append(f"'{name}': removed {n0 - len(o[k])} duplicate point(s)")
        if o is None:
            continue
        if "rings" in o:
            if not all(_finite(r) for r in o["rings"]):
                log.append(f"removed '{name}': coordinates are not valid numbers"); continue
            o["rings"] = [r for r in (_dedupe(r) for r in o["rings"]) if len(r) >= 3]
            if not o["rings"]:
                log.append(f"removed '{name}': fewer than 3 distinct points"); continue
        # --- too small / too thin to stitch
        if t == "fill":
            area = abs(polygon_area(o["rings"][0])) - sum(abs(polygon_area(r)) for r in o["rings"][1:])
            if area < 1.0:
                log.append(f"removed '{name}': fill smaller than 1 mm² (not visible, only adds trims)"); continue
        if t == "column":
            n = min(len(o["rail1"]), len(o["rail2"]))
            if n >= 2:
                w = sum(math.dist(a, b) for a, b in zip(o["rail1"][:n], o["rail2"][:n])) / n
                if w < 0.8:
                    mid = [[(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] for a, b in zip(o["rail1"][:n], o["rail2"][:n])]
                    o = {"id": o["id"], "type": "run", "color": o.get("color"), "name": o.get("name"), "points": mid, "smooth": o.get("smooth", False)}
                    log.append(f"'{name}': column only {w:.2f} mm wide - converted to a running stitch along its centre line")
        if t == "satin" and float(((o.get("params") or {})).get("width", DEFAULTS["satin"]["width"])) < 0.8 and len(o.get("points", [])) >= 2:
            o = {"id": o["id"], "type": "run", "color": o.get("color"), "name": o.get("name"), "points": o["points"], "smooth": o.get("smooth", False),
                 "closed": bool(o.get("closed"))}                       # a closed satin ring stays a closed outline
            log.append(f"'{name}': satin narrower than 0.8 mm - converted to a running stitch")
        keep.append(o)
    d["objects"] = keep
    # --- fit the hoop (scale down only), then centre
    b = design_bbox(d)
    if b:
        w, h = b[2] - b[0], b[3] - b[1]
        m = float(hoop.get("margin", 3))
        aw, ah = float(hoop.get("w", 100)) - 2 * m, float(hoop.get("h", 100)) - 2 * m
        if aw > 0 and ah > 0 and (w > aw + 1e-6 or h > ah + 1e-6):
            k = min(aw / w, ah / h) * 0.995
            d = transform_design(d, scale=k)
            log.append(f"design was {w:.1f} x {h:.1f} mm, larger than the {aw:.0f} x {ah:.0f} mm safe area - scaled to {k * 100:.1f}%")
        d2 = centre_design(d)
        if d2 is not d:
            log.append("centred in the hoop"); d = d2
    # --- dynamic loop: generate, check, relieve density
    for rnd in range(max_rounds):
        try:
            p, notes, st = generate(d)
        except ValueError:
            break
        rep = run_checks(d, p)
        if not any(i.code == "DENSITY" for i in rep.issues):
            break
        th = THREADS.get(d.get("thread") or "40wt", THREADS["40wt"])
        stitched = [o for o in d["objects"] if o.get("type") in ("fill", "satin", "column", "applique") and not o.get("hidden") and not o.get("guide")]
        # values the user chose stay untouched as long as opening the default ones is possible; only then are explicit ones opened (named)
        pool = [o for o in stitched if "spacing" not in ((o.get("params") or {})) or o.get("_autospaced")]
        explicit = False
        if not pool or all(round(min(((o.get("params") or {})).get("spacing", 0.4) * 1.15, 0.7), 3) <= ((o.get("params") or {})).get("spacing", 0.4) + 1e-9 for o in pool):
            pool, explicit = stitched, True
        changed = []
        for o in pool:
            cur = ((o.get("params") or {})).get("spacing")
            base = cur if cur else round(DEFAULTS[o["type"]]["spacing"] * th["k"], 3)
            new = round(min(base * 1.15, 0.7), 3)
            if new > base + 1e-9:
                o["params"] = dict((o.get("params") or {}), spacing=new); o["_autospaced"] = True
                changed.append(o.get("name") or o.get("id"))
        if not changed:
            break
        log.append(f"round {rnd + 1}: needle penetrations too dense - opened stitch spacing by 15% on {len(changed)} object(s)" +
                   (f" incl. user-set values: {', '.join(map(str, changed[:5]))}" if explicit else " (default-spaced objects only)"))
    for o in d["objects"]:
        o.pop("_autospaced", None)
    return d, log


# ---------------------------------------------------------------- placement planning
def plan(spec: List[dict], source_side: str = "left") -> List[dict]:
    """Validate and expand placement requests: [{id, width_mm?, height_mm?, rotate?, mirror?, label?}] -> full plans."""
    if source_side not in ("left", "right"):
        raise ValueError("source_side must be 'left' or 'right'")
    if not spec:
        raise ValueError("choose at least one placement")
    if len(spec) > 12:
        raise ValueError("at most 12 placements per set")
    seen, out = set(), []
    for s in spec:
        pid = slug(s.get("id"), "")
        if pid not in PLACEMENTS and not s.get("custom"):
            raise ValueError(f"unknown placement {s.get('id')!r}; use one of {', '.join(PLACEMENTS)}")
        if pid in seen:
            raise ValueError(f"placement {pid!r} listed twice")
        seen.add(pid)
        side = PLACEMENTS.get(pid, {}).get("side")
        mirror = bool(s["mirror"]) if "mirror" in s else (side is not None and side != source_side)
        rot = float(s.get("rotate", 0) or 0)
        if not -360 <= rot <= 360:
            raise ValueError("rotate must be between -360 and 360 degrees")
        w = float(s["width_mm"]) if s.get("width_mm") else None
        h = float(s["height_mm"]) if s.get("height_mm") else None
        for v in (w, h):
            if v is not None and not 5 <= v <= 500:
                raise ValueError("width/height must be between 5 and 500 mm")
        out.append({"id": pid, "label": s.get("label") or PLACEMENTS.get(pid, {}).get("label", pid), "mirror": mirror, "rotate": rot, "width_mm": w, "height_mm": h})
    return out


def make_variant(design: dict, p: dict) -> Tuple[dict, List[str]]:
    """The design for one placement, auto-corrected. Returns (design, log)."""
    log: List[str] = []
    d = transform_design(design, 1.0, p["mirror"], p["rotate"])
    if p["mirror"]:
        log.append("true mirror image (fill directions mirrored; lettering kept readable)")
    if p["rotate"]:
        log.append(f"rotated {p['rotate']:g} degrees")
    b = design_bbox(d)
    if b and (p["width_mm"] or p["height_mm"]):
        w, h = b[2] - b[0], b[3] - b[1]
        ks = [x for x in (p["width_mm"] / w if p["width_mm"] and w > 0 else None, p["height_mm"] / h if p["height_mm"] and h > 0 else None) if x]
        k = min(ks)
        if not 0.2 <= k <= MAX_SCALE:
            raise ValueError(f"{p['id']}: requested size needs scaling by {k:.2f}x; allowed range is 0.2x-{MAX_SCALE:g}x")
        d = transform_design(d, k)
        log.append(f"scaled to {w * k:.1f} x {h * k:.1f} mm ({k * 100:.0f}%)")
    d["name"] = f"{slug(design.get('name'))}_{p['id']}"
    d, fixlog = autofix(d)
    return d, log + fixlog
