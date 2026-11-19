"""Machine profiles: the limits a design is checked against before export.

HONESTY RULES
  * Every profile has `validated: False` unless physical stitch-out evidence for THAT machine has been recorded by the user.
    The software never claims that a machine is compatible; it only checks the design against the numbers in the profile.
  * Presets carry only values that come from the DST format itself (12.1 mm per record, DST only) plus conservative engine defaults.
    Anything that depends on the real machine (hoop sizes, needle count, trim behaviour) is `None` / "enter your value" until the user fills it in.
  * Output format is DST only.
"""
from __future__ import annotations
import copy
import math
from typing import Dict, List, Optional

DST_MAX_RECORD_MM = 12.1

_BASE = {
    "format": "dst",
    "max_stitch": 7.0, "min_stitch": 0.3,                 # engine defaults, editable
    "max_hoop": None,                                     # {"w": mm, "h": mm} - unknown until the user enters it
    "needles": None,                                      # number of needles / thread colours the machine holds - unknown until entered
    "trim_distance": 3.0, "trim_jumps": 3, "lock_len": 1.0,
    "trim_at_color_change": 1, "trim_at_end": 1,
    "validated": False,
}
PRESETS: Dict[str, dict] = {
    "generic_tajima_dst": dict(_BASE, id="generic_tajima_dst", manufacturer="Generic", model="Tajima-compatible DST (unspecified machine)",
                               note="Format limits only. Trim emulation (3 zero-move jumps) is a convention that is NOT verified on any specific machine."),
    "ricoma_unvalidated": dict(_BASE, id="ricoma_unvalidated", manufacturer="Ricoma", model="(enter your model)",
                               note="Starting point for a Ricoma. Hoop and needle count are blank: enter the values for YOUR machine. NOT validated - no stitch-out evidence has been recorded."),
    "custom": dict(_BASE, id="custom", manufacturer="", model="Custom machine", note="Your own limits. NOT validated."),
}
EDITABLE = ("manufacturer", "model", "max_stitch", "min_stitch", "max_hoop", "needles", "trim_distance", "trim_jumps", "lock_len", "trim_at_color_change", "trim_at_end")


def catalog() -> List[dict]:
    return [copy.deepcopy(p) for p in PRESETS.values()]


def resolve(design: dict) -> dict:
    """Profile of a design = preset + the user's overrides in design["machine_profile"] = {"id": ..., "overrides": {...}}. Always validated=False
    unless the user recorded evidence (`validated_by` text) - and even then the report says so as the user's statement."""
    mp = design.get("machine_profile") or {}
    p = copy.deepcopy(PRESETS.get(mp.get("id"), PRESETS["generic_tajima_dst"]))
    for k, v in (mp.get("overrides") or {}).items():
        if k not in EDITABLE:
            continue
        if k == "max_hoop":
            if isinstance(v, dict) and all(isinstance(v.get(a), (int, float)) and not isinstance(v.get(a), bool) and v[a] > 0 and math.isfinite(v[a]) for a in ("w", "h")):
                p[k] = {"w": float(v["w"]), "h": float(v["h"])}
        elif k in ("manufacturer", "model"):
            p[k] = str(v)[:80]
        elif k == "needles":
            if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 64:
                p[k] = v
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            p[k] = v
    p["max_stitch"] = min(max(float(p["max_stitch"]), 1.0), DST_MAX_RECORD_MM)
    ev = mp.get("validated_by")
    p["validated"] = False
    p["validation_statement"] = ("NOT VALIDATED: no stitch-out evidence recorded for this machine. The checks below compare the design with the numbers above only."
                                 if not ev else f"User statement (not verified by this software): {str(ev)[:200]}")
    return p


def machine_settings(profile: dict) -> dict:
    """The subset the engine uses (design['machine'])."""
    return {k: profile[k] for k in ("max_stitch", "min_stitch", "trim_distance", "trim_jumps", "lock_len", "trim_at_color_change", "trim_at_end")}


def check_design(design: dict, pattern) -> List[dict]:
    """Design vs the selected profile. Returns issues {code, severity, message}. Errors block export."""
    from .model import Cmd
    p = resolve(design); out: List[dict] = []
    add = lambda c, s, m: out.append({"code": c, "severity": s, "message": m})
    bb = pattern.bbox()
    hoop = p.get("max_hoop")
    if bb and hoop:
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        if w > hoop["w"] or h > hoop["h"]:
            add("MACHINE_HOOP", "error", f"The design ({w:.1f} x {h:.1f} mm) is larger than the hoop limit of this machine profile ({hoop['w']:g} x {hoop['h']:g} mm).")
    elif not hoop:
        add("MACHINE_HOOP_UNKNOWN", "warning", "This machine profile has no maximum hoop size, so the design could not be checked against your machine. Enter it in the profile.")
    prev, longest = None, 0.0
    for s in pattern.stitches:
        if s.cmd == Cmd.STITCH and prev is not None:
            longest = max(longest, math.hypot(s.x - prev[0], s.y - prev[1]))
        prev = (s.x, s.y) if s.cmd in (Cmd.STITCH, Cmd.JUMP) else None
    if longest > p["max_stitch"] + 1e-6:
        add("MACHINE_STITCH_LENGTH", "warning", f"The longest stitch is {longest:.1f} mm; this profile allows {p['max_stitch']:g} mm.")
    n_threads = len({s.thread for s in pattern.stitches if s.cmd == Cmd.STITCH})
    if p.get("needles") and n_threads > p["needles"]:
        add("MACHINE_NEEDLES", "warning", f"The design uses {n_threads} thread colours but this profile has {p['needles']} needles; colours must be re-threaded during the run.")
    elif not p.get("needles"):
        add("MACHINE_NEEDLES_UNKNOWN", "warning", "This machine profile has no needle count; the number of thread colours was not checked.")
    return out
