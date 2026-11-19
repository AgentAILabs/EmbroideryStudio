"""Digitizing assistant: a rule-based natural-language command interpreter that EDITS the design objects.

No external AI service, model or network access is used: requests are split into clauses and each clause is matched against a documented set of embroidery commands
(see COMMANDS). Every recognised command changes real object parameters / types / geometry and reports what changed; clauses it does not understand are returned
as `not_understood` with the list of supported commands - it never pretends. The caller applies the returned design as one undoable edit.
Values used by the presets (cap, left chest, denim ...) are engineering starting points, NOT verified settings.
"""
from __future__ import annotations
import copy
import math
import re
from typing import Callable, Dict, List, Optional, Tuple

COMMANDS = [
    ("make the borders / outlines satin stitch [2 mm]", "converts running-stitch outlines to satin columns"),
    ("use tatami fill for large areas [over 40 mm2]", "sets pattern tatami + tatami underlay on large fills"),
    ("increase / decrease stitch density [by 20 %]", "scales row spacing of fills, satins and columns"),
    ("reduce unnecessary colour changes", "re-sequences objects and merges near-identical colours"),
    ("improve small lettering", "tighter spacing, lighter underlay and compensation for text and narrow columns"),
    ("optimize this design for a cap", "cap starting values: more pull compensation, edge+zigzag / tatami underlay, height limit"),
    ("prepare this design for a left-chest logo [90 mm]", "scales to left-chest width, centres, cleans micro stitches"),
    ("reduce the overall stitch count", "opens fill / satin spacing, longer fill stitches, short-stitch cleaning, drops tack dots"),
    ("make the embroidery suitable for denim | cotton | silk | georgette | velvet | knit | net | thick | canvas", "applies the fabric profile"),
    ("scale to 120 % | make it 80 mm wide | 3 inch wide", "scales the whole design"),
    ("add underlay", "tatami under large fills, centre / edge+zigzag under satins that have none"),
    ("clean short stitches", "sets the short-stitch cleaning limit (0.5 mm)"),
    ("remove tiny details / specks", "deletes objects too small to stitch reliably"),
    ("convert this logo / image into embroidery", "opens the image chooser (an image must be uploaded)"),
]


class Ctx:
    def __init__(self, design: dict):
        self.d = copy.deepcopy(design); self.log: List[dict] = []; self.action: Optional[str] = None


def _area(r):
    return abs(sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))) / 2


def _fill_area(o):
    rings = o.get("rings") or []
    return (_area(rings[0]) - sum(_area(h) for h in rings[1:])) if rings else 0.0


def _length(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def _num(text: str, pat: str, default: float) -> float:
    m = re.search(pat, text)
    return float(m.group(1)) if m else default


def _params(o):
    o["params"] = dict(o.get("params") or {}); return o["params"]


def _set_spacing(o, factor, lo=0.25, hi=1.2):
    from .design import DEFAULTS
    p = _params(o); cur = float(p.get("spacing", DEFAULTS.get(o["type"], {}).get("spacing", 0.4)))
    new = round(min(hi, max(lo, cur * factor)), 3)
    if new != cur: p["spacing"] = new; return True
    return False


# ------------------------------------------------------------------------------------------------------------------------------------------------------------ handlers
def h_border_satin(c: Ctx, t: str):
    w = _num(t, r"(\d+(?:\.\d+)?)\s*mm", 2.2); n = 0
    for o in c.d["objects"]:
        if o.get("type") == "run" and len(o.get("points") or []) >= 3 and _length(o["points"]) >= 8:
            o["type"] = "satin"; p = _params(o)
            for k in ("stitch_len", "style", "motif", "motif_size", "motif_amp"): p.pop(k, None)
            p.update({"width": w, "underlay": "auto"}); o.pop("smooth", None); n += 1
    return n, f"{n} outline(s) converted from running stitch to {w:g} mm satin" if n else "no running-stitch outlines (3+ points, 8 mm+) found"


def h_tatami_large(c: Ctx, t: str):
    thr = _num(t, r"(?:over|above|larger than|bigger than|>)\s*(\d+(?:\.\d+)?)\s*(?:mm2|mm\^2|sq)", 40.0); n = 0
    for o in c.d["objects"]:
        if o.get("type") == "fill" and _fill_area(o) >= thr:
            p = _params(o); before = (p.get("pattern"), p.get("underlay")); p.update({"pattern": "tatami", "underlay": "tatami"})
            n += 1 if before != ("tatami", "tatami") else 0
    return n, f"{n} large fill(s) (>= {thr:g} mm2) set to tatami fill with tatami underlay"


def h_density(c: Ctx, t: str, up: bool):
    pct = _num(t, r"(\d+(?:\.\d+)?)\s*%", 15.0) / 100.0; f = 1 / (1 + pct) if up else (1 + pct); n = 0
    for o in c.d["objects"]:
        if o.get("type") in ("fill", "satin", "column") and _set_spacing(o, f): n += 1
    return n, f"row spacing {'reduced' if up else 'increased'} by about {pct * 100:g} % on {n} object(s) ({'denser' if up else 'lighter'}; limits 0.25-1.2 mm)"


def group_by_colour(d: dict) -> Tuple[dict, int, int]:
    """Re-order objects so each colour is stitched in as few blocks as possible WITHOUT changing the layering of objects that overlap (an object stays after everything it
    covers / is covered by in the original order). Greedy topological ordering: keep taking available objects of the current colour; switch colour only when none is available.
    -> (design, colour changes before, after). The result is adopted only when it has fewer colour changes."""
    from .sequence import _overlap
    from .placements import _bbox
    objs = d["objects"]; n = len(objs); boxes = [_bbox(o) for o in objs]
    def changes(order): return sum(1 for a, b in zip(order, order[1:]) if (objs[a].get("color") or "").lower() != (objs[b].get("color") or "").lower())
    before = changes(list(range(n)))
    pred = [set() for _ in range(n)]
    for j in range(n):
        for i in range(j):
            if boxes[i] and boxes[j] and (objs[i].get("color") or "").lower() != (objs[j].get("color") or "").lower() and _overlap(boxes[i], boxes[j], 0.3): pred[j].add(i)
    placed = []; done = set(); cur = None
    while len(placed) < n:
        avail = [i for i in range(n) if i not in done and pred[i] <= done]
        pick = next((i for i in avail if (objs[i].get("color") or "").lower() == cur), None)
        if pick is None: pick = avail[0]; cur = (objs[pick].get("color") or "").lower()
        placed.append(pick); done.add(pick)
    after = changes(placed)
    if after < before:
        d = copy.deepcopy(d); d["objects"] = [d["objects"][i] for i in placed]
    return d, before, min(before, after)


def h_colour_changes(c: Ctx, t: str):
    from .sequence import optimize_sequence
    from . import threads
    cols = threads.design_colours(c.d); before = len(cols); merged = 0
    mp = {}; keep: List[str] = []
    for col in cols:
        lab = threads._lab(col); hit = next((k for k in keep if threads.delta_e2000(lab, threads._lab(k)) <= 6.0), None)
        if hit: mp[col] = hit; merged += 1
        else: keep.append(col)
    if mp: threads._recolour(c.d, mp)
    c.d, lg = optimize_sequence(c.d)
    c.d, cc0, cc1 = group_by_colour(c.d)
    after = len(threads.design_colours(c.d))
    return merged + (cc0 - cc1), f"colours {before} -> {after} ({merged} near-identical merged, dE2000 <= 6); colour changes in the sewing order {cc0} -> {cc1} (objects regrouped by colour where their layering allows; travel re-optimised)"


def h_small_lettering(c: Ctx, t: str):
    n = 0
    for o in c.d["objects"]:
        if o.get("type") == "text":
            p = _params(o); p.update({"spacing": 0.35, "pull_comp": 0.15, "underlay": "auto"}); n += 1
        elif o.get("type") in ("satin", "column"):
            from .profiles import column_width
            try: w = column_width(o)
            except Exception: w = 99
            if w < 2.0:
                p = _params(o); p.update({"underlay": "none", "spacing": 0.33, "pull_comp": 0.12}); n += 1
    return n, f"{n} lettering / narrow object(s): spacing 0.33-0.35 mm, pull compensation 0.12-0.15, light or no underlay (narrow columns)"


CAP_FACTS = "cap starting values (unverified): pull compensation +0.1, satin underlay edge+zigzag, fill underlay tatami, design height <= 55 mm"


def h_cap(c: Ctx, t: str):
    n = 0
    for o in c.d["objects"]:
        ty = o.get("type"); p = _params(o)
        if ty in ("fill", "satin", "column"):
            p["pull_comp"] = round(min(1.0, float(p.get("pull_comp", 0.2)) + 0.1), 3); n += 1
        if ty == "fill": p["underlay"] = "tatami"
        elif ty in ("satin", "column"): p["underlay"] = "edge+zigzag"
    from .placements import design_bbox, transform_design, centre_design
    b = design_bbox(c.d); extra = ""
    if b and b[3] - b[1] > 55:
        k = 55 / (b[3] - b[1]); c.d = centre_design(transform_design(c.d, scale=k)); extra = f"; scaled to {k * 100:.0f} % so the height is 55 mm"
    c.d.setdefault("hoop", {"w": 130, "h": 60, "margin": 3}); h = dict(c.d["hoop"]); h["h"] = min(float(h.get("h", 60)), 60.0); c.d["hoop"] = h
    return n, f"{n} object(s) adjusted ({CAP_FACTS}){extra}; hoop height limited to 60 mm - set your real cap frame size"


def h_left_chest(c: Ctx, t: str):
    from .placements import design_bbox, transform_design, centre_design
    w_t = _num(t, r"(\d+(?:\.\d+)?)\s*mm", 90.0)
    b = design_bbox(c.d)
    if not b: return 0, "the design is empty"
    k = max(0.25, min(4.0, w_t / max(b[2] - b[0], 1e-6)))
    c.d = centre_design(transform_design(c.d, scale=k)); m = dict(c.d.get("machine") or {}); m["micro_clean"] = 0.4; c.d["machine"] = m
    h = dict(c.d.get("hoop") or {}); h.update({"w": max(100, float(h.get("w", 100))), "h": max(100, float(h.get("h", 100)))}); c.d["hoop"] = h
    return 1, f"scaled x{k:.2f} to a {w_t:g} mm wide left-chest logo, centred, micro-stitch cleaning 0.4 mm (check lettering stays >= 5 mm high)"


def h_reduce_count(c: Ctx, t: str):
    n = 0; dropped = 0; keep = []
    for o in c.d["objects"]:
        if o.get("type") == "manual" and str(o.get("name", "")).lower().startswith("tack"): dropped += 1; continue
        keep.append(o)
        if o.get("type") in ("fill", "satin", "column") and _set_spacing(o, 1.15): n += 1
        if o.get("type") == "fill": p = _params(o); p["stitch_len"] = min(4.5, max(float(p.get("stitch_len", 3.5)), 4.0))
    c.d["objects"] = keep; m = dict(c.d.get("machine") or {}); m["micro_clean"] = max(float(m.get("micro_clean", 0)), 0.5); c.d["machine"] = m
    return n + dropped, f"row spacing +15 % on {n} object(s), fill stitch length 4 mm, micro-stitch cleaning 0.5 mm, {dropped} tack dot(s) removed"


def h_fabric(c: Ctx, t: str, fab: str):
    from .profiles import apply_profile, FABRICS
    alias = {"canvas": "thick", "polyester": None, "cotton": "cotton"}
    f = alias.get(fab, fab)
    if f is None: return 0, f"no '{fab}' profile exists (profiles: {', '.join(FABRICS)}); nothing changed"
    if f not in FABRICS: return 0, f"unknown fabric {fab!r}"
    c.d, lg = apply_profile(c.d, f, None, overwrite=True)
    note = " ('canvas' uses the heavy 'thick' profile)" if fab == "canvas" else ""
    return 1, f"fabric profile '{f}' applied to all objects{note}: " + (lg[0] if lg else "")


def h_scale(c: Ctx, t: str):
    from .placements import design_bbox, transform_design, centre_design
    b = design_bbox(c.d)
    if not b: return 0, "the design is empty"
    w = b[2] - b[0]; m = re.search(r"(\d+(?:\.\d+)?)\s*%", t); mm = re.search(r"(\d+(?:\.\d+)?)\s*(mm|cm|inch|inches|in)\b", t)
    if m: k = float(m.group(1)) / 100.0
    elif mm:
        v = float(mm.group(1)) * {"mm": 1.0, "cm": 10.0}.get(mm.group(2), 25.4); k = v / max(w, 1e-6)
    else: return 0, "give a size, e.g. 'scale to 120 %' or 'make it 80 mm wide'"
    if not 0.1 <= k <= 10: return 0, f"scale factor {k:.2f} is outside 0.1-10"
    c.d = centre_design(transform_design(c.d, scale=k)); return 1, f"design scaled x{k:.2f} (width {w:.1f} -> {w * k:.1f} mm); stitch parameters keep their physical values"


def h_remove_tiny(c: Ctx, t: str):
    n0 = len(c.d["objects"]); keep = []
    for o in c.d["objects"]:
        ty = o.get("type")
        if ty == "fill" and _fill_area(o) < 1.0: continue
        if ty in ("run", "manual") and len(o.get("points") or []) >= 2 and _length(o["points"]) < 1.5: continue
        keep.append(o)
    c.d["objects"] = keep; return n0 - len(keep), f"{n0 - len(keep)} object(s) too small to stitch reliably removed (fills < 1 mm2, lines < 1.5 mm)"


def h_underlay(c: Ctx, t: str):
    from .profiles import column_width
    n = 0
    for o in c.d["objects"]:
        ty = o.get("type"); p = _params(o)
        if ty == "fill" and _fill_area(o) >= 20 and p.get("underlay", "tatami") == "none": p["underlay"] = "tatami"; n += 1
        elif ty in ("satin", "column"):
            try: w = column_width(o)
            except Exception: w = 0
            if w >= 2.5 and p.get("underlay", "auto") == "none": p["underlay"] = "center" if w < 4 else "edge+zigzag"; n += 1
    return n, f"underlay added to {n} object(s): tatami under fills >= 20 mm2, centre run (2.5-4 mm) or edge + zig-zag (wider) under satins"


def h_short_stitches(c: Ctx, t: str):
    m = dict(c.d.get("machine") or {}); old = float(m.get("micro_clean", 0)); m["micro_clean"] = max(old, 0.5); c.d["machine"] = m
    return (1 if m["micro_clean"] != old else 0), f"short-stitch cleaning set to {m['micro_clean']:g} mm (stitches shorter than this are merged into the previous one)"


def h_convert(c: Ctx, t: str):
    c.action = "open_image"; return 1, "choose the image: it will be analysed, digitized into editable objects and opened (Instant smart design)"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------ dispatch
NOUNS = r"border|outline|stitch|satin|fill|tatami|area|density|colou?r|text|letter|lettering|logo|object|design|embroider|thread|detail|underlay"
FABRIC_WORDS = r"(cotton|silk|georgette|velvet|knit|stretch|denim|jeans|net|tulle|thick|canvas|polyester|satin fabric)"


def _rules() -> List[Tuple[str, Callable]]:
    return [
        (r"(border|outline).*satin|satin.*(border|outline)", h_border_satin),
        (r"tatami.*(large|big)|(large|big).*(area|fill|tatami)", h_tatami_large),
        (r"(increase|raise|higher|denser|more)\b.*density|density.*(increase|higher|more)", lambda c, t: h_density(c, t, True)),
        (r"(decrease|reduce|lower|less|lighter)\b.*density|density.*(decrease|lower|less)", lambda c, t: h_density(c, t, False)),
        (r"(reduce|fewer|minimi[sz]e|optimi[sz]e|cut).*(colou?r change|thread change|colou?rs)|colou?r change", h_colour_changes),
        (r"(improve|fix|better|clean).*(small|tiny).*(letter|text|font)|small (letter|text)", h_small_lettering),
        (r"\b(cap|hat|baseball)\b", h_cap),
        (r"left.?chest|chest logo|pocket logo", h_left_chest),
        (r"(reduce|lower|cut|fewer|minimi[sz]e).*(stitch count|stitches|stitch total)|fewer stitches", h_reduce_count),
        (r"(suitable|optimi[sz]e|prepare|ready|good|for).*\b" + FABRIC_WORDS + r"\b", None),     # handled specially (needs the fabric word)
        (r"(add|improve|fix|use|apply).*underlay|underlay.*(missing|add|improve)", h_underlay),
        (r"(clean|remove|filter|merge|fix).*(short|micro|tiny).*stitch", h_short_stitches),
        (r"(remove|delete|clean up|drop).*(tiny|small|stray|speck|detail|noise)", h_remove_tiny),
        (r"(scale|resize|enlarge|shrink|make it)\b.*\d+(?:\.\d+)?\s*(?:%|(?:mm|cm|inch|inches|in)\b)", h_scale),
        (r"(convert|digiti[sz]e|turn|make).*(logo|image|artwork|picture|photo|drawing).*(embroider|stitch)?|convert this", h_convert),
    ]


def run(design: dict, text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("write a request, e.g. 'make the borders satin and reduce colour changes'")
    if len(text) > 600: raise ValueError("request too long (limit 600 characters)")
    c = Ctx(design); before = _metrics(c.d)
    clauses = [x.strip() for x in re.split(r"\s*(?:,|;|\.|\bthen\b|\band also\b)\s*", text.lower()) if x and x.strip()]
    applied, unknown = [], []
    def find(cl):
        for pat, fn in _rules():
            if re.search(pat, cl): return fn
        return False
    for cl in clauses:
        parts = [x.strip() for x in re.split(r"\s+and\s+", cl) if x.strip()]; pending = ""
        for part in parts:
            test = (pending + " and " + part) if pending else part
            fn = find(test)
            if fn is False:
                pending = test; continue
            if fn is None:
                fab = re.search(FABRIC_WORDS, test).group(1); fab = {"jeans": "denim", "tulle": "net", "stretch": "knit", "satin fabric": "satin_fabric"}.get(fab, fab)
                n, detail = h_fabric(c, test, fab)
            else:
                n, detail = fn(c, test)
            applied.append({"request": test, "changed": n, "detail": detail}); pending = ""
        if pending: unknown.append(pending)
    after = _metrics(c.d)
    return {"design": c.d, "applied": applied, "not_understood": unknown, "action": c.action, "before": before, "after": after,
            "supported_commands": [{"say": a, "does": b} for a, b in COMMANDS],
            "note": "Rule-based interpreter (no external AI). Presets are starting values, not verified settings; check the result and stitch a sample."}


def _metrics(d: dict) -> dict:
    try:
        from .design import generate
        p, notes, st = generate(d)
        return {"stitches": st["stitches"], "colour_changes": st.get("color_changes"), "trims": st.get("trims"), "objects": len(d.get("objects", []))}
    except Exception as e:                                                       # an empty / invalid intermediate design has no stitches
        return {"stitches": None, "objects": len(d.get("objects", [])), "error": str(e)[:80]}
