"""Structural validation of a design document at the API boundary.

Anything that is not the right type or is not a finite number is refused with a clear message (HTTP 400) instead of crashing deep inside the engine
(found by fuzzing: 120 distinct 500-errors from wrong types, NaN/inf, absurd parameter values). Geometry that is merely poor (self-crossing, tiny)
is NOT rejected here - quality.validate_geometry explains those to the user.
"""
from __future__ import annotations
import math

TYPES = {"fill", "satin", "column", "run", "text", "manual", "applique", "embellishment"}
MAX_COORD = 100_000.0
SCALAR = (int, float, str, bool, type(None))
RANGES = {  # parameter -> (min, max); outside = refused (these values make the engine allocate without bound or divide by ~0)
    "spacing": (0.05, 20), "stitch_len": (0.2, 50), "width": (0.1, 200), "pull_comp": (-5, 5), "push_comp": (-5, 5), "overlap_mm": (0, 20),
    "cross_size": (0.5, 50), "min_row": (0, 50), "expand_mm": (-20, 20), "comp_x": (-20, 20), "comp_y": (-20, 20), "corner_angle": (1, 179),
}


def _num(v, what, lo=-MAX_COORD, hi=MAX_COORD):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f"{what} must be a finite number between {lo:g} and {hi:g}")
    return float(v)


def _pt(p, what):
    if not isinstance(p, (list, tuple)) or len(p) != 2:
        raise ValueError(f"{what}: each point must be [x, y]")
    _num(p[0], f"{what} x"); _num(p[1], f"{what} y")


def _pts(v, what):
    if not isinstance(v, list):
        raise ValueError(f"{what} must be a list of [x, y] points")
    for p in v:
        _pt(p, what)


def validate_design(d) -> None:
    if not isinstance(d, dict):
        raise ValueError("the design must be a JSON object")
    for k in ("name", "thread", "fabric", "stabiliser"):
        if d.get(k) is not None and not isinstance(d[k], str):
            raise ValueError(f"{k} must be text")
    if isinstance(d.get("name"), str) and len(d["name"]) > 200:
        raise ValueError("name is too long (limit 200)")
    if "hoop" in d:
        h = d["hoop"]
        if not isinstance(h, dict):
            raise ValueError("hoop must be {w, h, margin}")
        _num(h.get("w", 100), "hoop width", 5, 5000); _num(h.get("h", 100), "hoop height", 5, 5000); _num(h.get("margin", 3), "hoop margin", 0, 500)
    for k in ("machine", "profile"):
        v = d.get(k)
        if v is not None:
            if not isinstance(v, dict):
                raise ValueError(f"{k} must be an object")
            for kk, vv in v.items():
                if not isinstance(vv, SCALAR) or (isinstance(vv, float) and not math.isfinite(vv)):
                    raise ValueError(f"{k}.{kk} must be a number or text")
    mp = d.get("machine_profile")
    if mp is not None:
        if not isinstance(mp, dict) or not isinstance(mp.get("overrides", {}), dict) or (mp.get("id") is not None and not isinstance(mp["id"], str)):
            raise ValueError("machine_profile must be {id, overrides}")
    objs = d.get("objects", [])
    if not isinstance(objs, list):
        raise ValueError("objects must be a list")
    seen = set()
    for n, o in enumerate(objs):
        if not isinstance(o, dict):
            raise ValueError(f"object {n + 1} must be an object")
        oid = o.get("id")
        if not isinstance(oid, str) or not oid or len(oid) > 100:
            raise ValueError(f"object {n + 1} needs a text id")
        if oid in seen:
            raise ValueError(f"duplicate object id {oid!r}")
        seen.add(oid)
        w = f"object {oid}"
        if o.get("type") not in TYPES:
            raise ValueError(f"{w}: unknown type {o.get('type')!r}")
        for k in ("color", "name", "group"):
            if o.get(k) is not None and (not isinstance(o[k], str) or len(o[k]) > 200):
                raise ValueError(f"{w}: {k} must be short text")
        for k in ("hidden", "guide", "smooth", "closed"):
            if o.get(k) is not None and not isinstance(o[k], (bool, int)):
                raise ValueError(f"{w}: {k} must be true or false")
        for k in ("entry", "exit"):
            if o.get(k) is not None:
                _pt(o[k], f"{w} {k}")
        p = o.get("params")
        if p is not None:
            if not isinstance(p, dict):
                raise ValueError(f"{w}: params must be an object")
            for k, v in p.items():
                if not isinstance(v, SCALAR) or (isinstance(v, float) and not math.isfinite(v)):
                    raise ValueError(f"{w}: parameter {k} must be a number or text")
                if k in RANGES and not isinstance(v, (bool, str, type(None))):
                    lo, hi = RANGES[k]
                    if not lo <= v <= hi:
                        raise ValueError(f"{w}: parameter {k} must be between {lo:g} and {hi:g}")
        t = o["type"]
        if t in ("fill", "applique"):
            if not isinstance(o.get("rings", []), list):
                raise ValueError(f"{w}: rings must be a list of outlines")
            for r in o.get("rings", []):
                _pts(r, f"{w} outline")
        if t in ("satin", "run", "manual", "embellishment"):
            _pts(o.get("points", []), f"{w} points")
        if t == "column":
            _pts(o.get("rail1", []), f"{w} rail 1"); _pts(o.get("rail2", []), f"{w} rail 2")
        if t == "text":
            if not isinstance(o.get("text", ""), str) or len(o.get("text", "")) > 500:
                raise ValueError(f"{w}: text must be at most 500 characters")
            _num(o.get("x", 0), f"{w} x"); _num(o.get("y", 0), f"{w} y"); _num(o.get("height", 10), f"{w} height", 1, 1000)
            if o.get("path") is not None:
                _pts(o["path"], f"{w} path")
        if t == "embellishment" and o.get("size_mm") is not None:
            _num(o["size_mm"], f"{w} size", 0.1, 100)
        if o.get("handles") is not None:
            if not isinstance(o["handles"], list):
                raise ValueError(f"{w}: handles must be a list")
            for hd in o["handles"]:
                if not isinstance(hd, list) or len(hd) != 4:
                    raise ValueError(f"{w}: each handle must be [inX, inY, outX, outY]")
                for v in hd:
                    _num(v, f"{w} handle")
