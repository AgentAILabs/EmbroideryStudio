"""Fabric- and category-aware digitizing profiles.

`apply_profile(design)` turns the professional digitizing rules into explicit per-object parameters, so the result is visible
and editable in the editor (Expert mode) and reproducible in the file. It only fills parameters an object does not set itself,
unless `overwrite=True`. Starting values, not certified settings: fabric, thread, needle and machine decide the final ones.

Rules (each is logged with the object it changed):
  * density   - line spacing = 0.40 mm x thread factor x fabric factor x width factor (automatic satin spacing:
                narrow columns open up to 0.45 to avoid needle crowding; spec range 0.40-0.45 for 40 wt on cotton), clamped 0.18-0.60 mm
  * underlay  - satin / column by width: <1.5 none, 1.5-3 centre run, 3-4.5 edge run, 4.5-6 zig-zag, >=6 edge run + zig-zag;
                fill by area: <25 mm2 none, <400 tatami, larger edge run + tatami; light fabrics one step lighter, pile / stretch one heavier
  * pull comp - per fabric (0.15-0.40 mm), capped at 10 % of a narrow satin's width
  * shortening- on for every satin / column (inner side of tight curves)
  * running   - stitch length per category (2.0-2.5 mm)
  * overlap   - fills do not sew what later objects cover (0.6 mm under-lap kept)
  * push comp - stretch fabrics: fills and satins shortened 0.2 mm across the stitches
"""
import copy, math
from typing import List, Tuple

from .design import DEFAULTS, THREADS
from .geometry import polygon_area

FABRICS = {
    "cotton":    {"label": "Cotton",                                 "k": 1.00, "pull": 0.20, "under": 0},
    "blouse":    {"label": "Blouse fabric (raw silk / cotton silk)", "k": 1.00, "pull": 0.25, "under": 0},
    "silk":      {"label": "Silk",                                   "k": 1.10, "pull": 0.25, "under": -1},
    "georgette": {"label": "Georgette / chiffon",                    "k": 1.12, "pull": 0.30, "under": -1},
    "velvet":    {"label": "Velvet",                                 "k": 0.95, "pull": 0.30, "under": 1},
    "stretch":   {"label": "Stretch / knit",                         "k": 1.00, "pull": 0.40, "under": 1, "push": 0.2},
    "denim":     {"label": "Denim / canvas",                         "k": 1.00, "pull": 0.15, "under": 0},
    # Added in the enterprise upgrade - ALL EXPERIMENTAL starting points, no stitch-out evidence (see docs/embroidery/fabric-profile-guide.md)
    "satin_fabric": {"label": "Satin (slippery weave)",               "k": 1.10, "pull": 0.25, "under": -1},
    "net":       {"label": "Net / tulle",                            "k": 1.15, "pull": 0.30, "under": -1},
    "thick":     {"label": "Thick / heavy fabric",                   "k": 0.95, "pull": 0.15, "under": 1},
}
FABRIC_INFO = {
    "cotton": "Stable woven base case.", "blouse": "Raw silk / cotton-silk blouse cloth.", "silk": "Fine and slippery; lighter underlay, firm stabiliser.",
    "georgette": "Sheer and shifting; needs stabiliser, light underlay.", "velvet": "Pile crushes; heavier underlay so stitches do not sink.",
    "stretch": "Stretches during stitching; push compensation and heavier underlay.", "denim": "Firm and thick; small pull compensation.",
    "satin_fabric": "Smooth, slippery, shows needle holes. Use a firm stabiliser; keep underlay light.",
    "net": "Open mesh: dense fills cut or sink into it. Needs water-soluble or tear-away backing; prefer satin and open fills.",
    "thick": "Heavy cloth needs more underlay and a suitable needle; stitches tend to sink.",
}
FABRIC_WARNINGS = {
    "net": "Net / tulle: stitch-outs on this material need a stabiliser on both sides or a water-soluble backing. Dense fills will cut the net.",
    "satin_fabric": "Satin fabric shows needle holes and puckers easily: stitch a test sample first.",
    "thick": "Thick fabric: check needle size and hooping before production.",
}


def fabric_catalog():
    """Every fabric profile, honestly labelled: all are experimental and none is validated on a machine."""
    return [{"id": k, "label": v["label"], "experimental": True, "validated": False, "explanation": FABRIC_INFO.get(k, ""),
             "warning": FABRIC_WARNINGS.get(k, ""), "pull_comp": v["pull"], "underlay_shift": v["under"], "density_factor": v["k"]} for k, v in FABRICS.items()]
CATEGORIES = {
    "blouse_neck":  {"label": "Maggam blouse neck",      "run_len": 2.0, "under": 0,  "detail": "high"},
    "floral":       {"label": "Maggam floral motif",     "run_len": 2.0, "under": 0,  "detail": "high"},
    "saree_border": {"label": "Saree border / motif",    "run_len": 2.5, "under": -1, "detail": "medium-high"},
    "logo":         {"label": "Logo / lettering",        "run_len": 2.5, "under": 0,  "detail": "high"},
}
SATIN_LADDER = ["none", "center", "edge", "zigzag", "edge+zigzag"]
FILL_LADDER = ["none", "edge", "tatami", "edge+tatami"]
SPACING_MIN, SPACING_MAX = 0.18, 0.60


def width_factor(w: float) -> float:
    """Automatic satin spacing inside the spec's 0.40-0.45 mm starting range (for 40 wt on cotton): narrow columns open up to
    0.45 (fewer penetrations where they crowd), everything else stays at 0.40. Thread and fabric factors scale the whole range."""
    return 1.125 if w < 2.0 else 1.06 if w < 3.0 else 1.0


def satin_underlay(w: float, shift: int) -> str:
    base = 0 if w < 1.5 else 1 if w <= 3.0 else 2 if w <= 4.5 else 3 if w < 6.0 else 4
    lvl = max(0, min(4, base + shift))
    if w < 1.2:
        lvl = 0                                   # nothing fits under a sub-1.2 mm column
    if w < 2.2 and lvl > 1:
        lvl = 1                                   # edge run / zig-zag need room inside the column
    if w >= 2.0 and lvl < 1:
        lvl = 1                                   # "minimal" underlay on light fabrics still means a centre run, never none
    return SATIN_LADDER[lvl]


def fill_underlay(area: float, shift: int) -> str:
    if area < (10 if shift > 0 else 60 if shift < 0 else 25):
        return "none"
    if shift < 0:
        return "edge" if area < 900 else "edge+tatami"
    if shift > 0:
        return "edge+tatami"
    return "tatami" if area < 400 else "edge+tatami"


def column_width(o: dict) -> float:
    if o["type"] == "satin":
        return float(((o.get("params") or {})).get("width", DEFAULTS["satin"]["width"]))
    r1, r2 = o["rail1"], o["rail2"]
    n = min(len(r1), len(r2))
    inner = list(zip(r1[1:n - 1], r2[1:n - 1])) or list(zip(r1[:n], r2[:n]))
    return sum(math.dist(a, b) for a, b in inner) / max(1, len(inner))


def underlay_shift(design: dict) -> int:
    """-1 lighter / 0 standard / +1 heavier underlay, from the design's fabric and category (the same rule apply_profile uses)."""
    prof = design.get("profile") or {}
    F = FABRICS.get(prof.get("fabric") or design.get("fabric") or "cotton", FABRICS["cotton"])
    C = CATEGORIES.get(prof.get("category") or "blouse_neck", CATEGORIES["blouse_neck"])
    return max(-1, min(1, F["under"] + C["under"]))


def apply_profile(design: dict, fabric: str = None, category: str = None, overwrite: bool = False) -> Tuple[dict, List[str]]:
    d = copy.deepcopy(design)
    prof = dict(d.get("profile") or {})
    fabric = fabric or prof.get("fabric") or d.get("fabric") or "cotton"
    category = category or prof.get("category") or "blouse_neck"
    if fabric not in FABRICS:
        raise ValueError(f"unknown fabric {fabric!r}; use one of {', '.join(FABRICS)}")
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; use one of {', '.join(CATEGORIES)}")
    F, C = FABRICS[fabric], CATEGORIES[category]
    tk = THREADS.get(d.get("thread") or "40wt", THREADS["40wt"])["k"]
    shift = max(-1, min(1, F["under"] + C["under"]))
    d["profile"] = {"fabric": fabric, "category": category}
    d["fabric"] = fabric if fabric in ("cotton", "silk", "georgette", "velvet", "denim", "satin_fabric", "net", "thick") else d.get("fabric", "cotton")
    m = dict(d.get("machine") or {}); m.setdefault("max_stitch", 7.0); d["machine"] = m
    log = [f"profile: {C['label']} on {F['label']}, thread {d.get('thread') or '40wt'} (starting values - confirm with a stitch-out)"]
    if fabric in FABRIC_WARNINGS:
        log.append("warning: " + FABRIC_WARNINGS[fabric])
    counts = {}

    def put(o, k, v):
        p = dict((o.get("params") or {}))
        if overwrite or k not in p:
            if p.get(k) != v:
                p[k] = v; o["params"] = p; counts[k] = counts.get(k, 0) + 1

    for o in d.get("objects", []):
        t = o.get("type")
        if o.get("hidden") or o.get("guide"):
            continue
        if t in ("satin", "column"):
            try:
                w = column_width(o)
            except (KeyError, IndexError, TypeError):
                continue
            sp = 0.4 * tk * F["k"] * width_factor(w)
            put(o, "spacing", round(min(SPACING_MAX, max(SPACING_MIN, sp)), 3))
            put(o, "underlay", satin_underlay(w, shift))
            put(o, "pull_comp", round(min(F["pull"], max(0.05, 0.1 * w)), 2))
            put(o, "shorten", True)
            if t == "satin":
                put(o, "corners", True)                 # split sharp corners into overlapping pieces (no folded satin)
            if F.get("push") and w >= 2.0:
                put(o, "push_comp", F["push"])
        elif t == "fill":
            rings = o.get("rings") or []
            if not rings:
                continue
            area = abs(polygon_area(rings[0])) - sum(abs(polygon_area(r)) for r in rings[1:])
            put(o, "spacing", round(min(SPACING_MAX, max(SPACING_MIN, 0.4 * tk * F["k"])), 3))
            put(o, "underlay", fill_underlay(area, shift))
            put(o, "pull_comp", F["pull"])
            put(o, "cut_hidden", True)              # do not sew what a later object covers (keeps a 0.6 mm under-lap)
            put(o, "min_row", 0.8)                  # spec minimum stitch: no tatami row shorter than 0.8 mm (tips are covered by pull comp / outline)
            if F.get("push"):
                put(o, "push_comp", F["push"])
        elif t == "run":
            put(o, "stitch_len", C["run_len"])
        elif t == "applique":
            put(o, "spacing", round(min(SPACING_MAX, max(SPACING_MIN, 0.4 * tk * F["k"])), 3))
    if counts:
        log.append("set " + ", ".join(f"{k} on {v} object(s)" for k, v in sorted(counts.items())))
    return d, log
