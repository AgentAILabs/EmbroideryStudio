"""Optimization advisor: measures the design and returns recommendations, each with its evidence and - where the assistant can do it - an exact command to apply it.

Everything here is MEASURED from the generated stitch stream and the objects (nothing is invented); thresholds are engineering starting points (documented per item), not
machine-verified limits. `apply()` runs the chosen recommendations through the assistant, so each one is a real edit of the objects.
"""
from __future__ import annotations
import copy
import math
from typing import Dict, List, Optional

from .model import Cmd


def _fill_area(o):
    from .assistant import _fill_area
    return _fill_area(o)


def analyse(design: dict) -> dict:
    from .design import generate
    from .quality import quality_report
    from .travel import travel_report
    from .assistant import _length
    pattern, notes, st = generate(design)
    recs: List[dict] = []
    def add(id_, sev, area, title, evidence, why, command=None):
        recs.append({"id": id_, "severity": sev, "area": area, "title": title, "evidence": evidence, "why": why, "command": command, "can_apply": command is not None})
    # ---- stitch stream measurements
    lens = []; cells: Dict[tuple, int] = {}; prev = None; n = 0
    for s in pattern.stitches:
        if s.cmd == Cmd.STITCH:
            n += 1; k = (int(math.floor(s.x)), int(math.floor(s.y))); cells[k] = cells.get(k, 0) + 1
            if prev is not None: lens.append(math.hypot(s.x - prev[0], s.y - prev[1]))
            prev = (s.x, s.y)
        else: prev = None
    pen = max(cells.values()) if cells else 0
    short = sum(1 for l in lens if l < 0.5) / max(1, len(lens)); long_ = sum(1 for l in lens if l > 7.0) / max(1, len(lens))
    if pen > 12:
        add("density", "high", "density", "Excessive stitch density", f"up to {pen} needle penetrations in 1 mm2 (limit 12)", "very dense areas cause thread breaks, hard fabric and puckering", "reduce stitch density by 15%")
    if short > 0.01:
        add("short_stitches", "medium", "stitch length", "Many very short stitches", f"{100 * short:.1f} % of stitches are shorter than 0.5 mm", "tiny stitches break thread and needle; they are merged by the short-stitch cleaner", "clean short stitches")
    if long_ > 0.01:
        add("long_stitches", "medium", "stitch length", "Long stitches", f"{100 * long_:.1f} % of stitches are longer than 7 mm", "long stitches snag and loop; the generator splits at 7 mm, so check wide satin columns (use tatami fill above ~7 mm)")
    # ---- objects
    nofill = [o for o in design["objects"] if o.get("type") == "fill" and _fill_area(o) >= 20 and (o.get("params") or {}).get("underlay", "tatami") == "none"]
    from .profiles import column_width
    nosat = []
    for o in design["objects"]:
        if o.get("type") in ("satin", "column") and (o.get("params") or {}).get("underlay", "auto") == "none":
            try:
                if column_width(o) >= 2.5: nosat.append(o)
            except Exception: pass
    if nofill or nosat:
        add("underlay", "medium", "underlay", "Missing underlay", f"{len(nofill)} fill(s) >= 20 mm2 and {len(nosat)} satin(s) >= 2.5 mm have no underlay", "underlay stabilises the fabric and keeps stitches from sinking; it also reduces puckering", "add underlay")
    tiny = [o for o in design["objects"] if (o.get("type") == "fill" and _fill_area(o) < 1.5) or (o.get("type") in ("run", "manual") and len(o.get("points") or []) >= 2 and _length(o["points"]) < 1.5)]
    if tiny:
        add("tiny", "low", "details", "Details too small to stitch reliably", f"{len(tiny)} object(s) under 1.5 mm2 / 1.5 mm", "needle + thread are ~0.4 mm wide; smaller marks come out as blobs", "remove tiny details")
    # ---- travel
    tr = travel_report(design, pattern); t = tr["totals"]
    if t.get("avoidable_colour_changes", 0) > 0:
        add("colour_changes", "high", "colours", "Avoidable colour changes", f"{t['colour_changes']} colour changes, minimum possible {t['minimum_colour_changes']}", "every colour change costs machine time and a thread change", "reduce unnecessary colour changes")
    jumps_per_k = 1000.0 * st.get("jumps", 0) / max(1, st["stitches"])
    if st.get("trims", 0) > 25 or jumps_per_k > 40:
        add("trims_jumps", "medium", "path", "Many trims / jumps", f"{st.get('trims', 0)} trims, {st.get('jumps', 0)} jumps ({jumps_per_k:.0f} per 1000 stitches)", "trims cost time and leave thread tails; re-sequencing objects reduces travel", "reduce unnecessary colour changes")
    # ---- size / count
    w, h = st.get("width_mm") or 0, st.get("height_mm") or 0; per_cm2 = st["stitches"] / max(1e-6, (w / 10) * (h / 10)) if w and h else 0
    if per_cm2 > 250:
        add("stitch_count", "medium", "density", "Very high stitch count for the size", f"{per_cm2:.0f} stitches per cm2 of the bounding box (guide: below ~250)", "high counts are slow and stiff; open the spacing or simplify", "reduce the overall stitch count")
    # ---- fabric / pull compensation
    fab = (design.get("profile") or {}).get("fabric") or design.get("fabric")
    if fab in ("knit", "stretch", "velvet", "georgette", "net"):
        pcs = [float((o.get("params") or {}).get("pull_comp", 0.2)) for o in design["objects"] if o.get("type") in ("fill", "satin", "column")]
        if pcs and max(pcs) < 0.3:
            add("pull_comp", "medium", "pull compensation", f"Pull compensation looks low for {fab}", f"largest pull compensation {max(pcs):g} mm", "stretchy / sheer fabrics pull shapes narrower; apply the fabric profile", f"make the embroidery suitable for {fab}")
    # ---- quality-engine issues (geometry / overlap) passed through as information
    q = quality_report(design, pattern, notes)
    for iss in q["issues"][:6]:
        if iss.get("severity") in ("error", "warning") and "overlap" in (iss.get("message", "") + iss.get("code", "")).lower():
            add("overlap_" + str(iss.get("object") or "x"), "low", "overlap", "Overlapping objects", iss["message"], iss.get("advice") or "overlapping objects stack stitches; the generator can cut hidden parts (fill option 'cut hidden')")
    order = {"high": 0, "medium": 1, "low": 2}; recs.sort(key=lambda r: (order[r["severity"]], r["id"]))
    from .report import complexity
    cx = complexity(design, st["stitches"], st.get("color_changes") or 0, st.get("trims") or 0)
    return {"recommendations": recs, "complexity": cx, "metrics": {"stitches": st["stitches"], "max_penetrations_per_mm2": pen, "short_share": round(short, 4), "long_share": round(long_, 4), "trims": st.get("trims"), "jumps": st.get("jumps"),
                                              "colour_changes": st.get("color_changes"), "stitches_per_cm2": round(per_cm2, 1)},
            "software_quality_score": q["score"], "note": "Measured from the generated stitches and objects; thresholds are engineering starting points, not machine-verified limits. Applying a recommendation is a real edit (undoable); re-check afterwards."}


def apply(design: dict, ids: Optional[List[str]] = None) -> dict:
    """Apply the chosen recommendations (default: every one that has a command) through the assistant; returns the edited design + what each did."""
    from . import assistant
    rec = analyse(design)["recommendations"]; todo = [r for r in rec if r["can_apply"] and (ids is None or r["id"] in ids)]
    d = copy.deepcopy(design); done = []; seen = set()
    for r in todo:
        if r["command"] in seen: continue                                                # two findings may share one command
        seen.add(r["command"]); out = assistant.run(d, r["command"]); d = out["design"]
        done.append({"id": r["id"], "command": r["command"], "applied": out["applied"]})
    return {"design": d, "done": done, "skipped": [r["id"] for r in rec if ids is not None and r["id"] in ids and not r["can_apply"]], "after": analyse(d)["metrics"]}
