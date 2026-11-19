"""Thread management: user-imported brand palettes, CIEDE2000 colour matching, colour replacement and thread-consumption estimates.

No brand chart data is bundled (it is licensed): palettes come from the user's own CSV / JSON files. The only built-in palette is a small GENERIC one, labelled as such.
Consumption is an ESTIMATE (documented formula), not a measurement.
"""
from __future__ import annotations
import csv
import io
import json
import math
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
MAX_COLOURS = 2000
GENERIC_ID = "generic"
GENERIC = [("black", "#111111"), ("charcoal", "#4a4a4a"), ("grey", "#8a8a8a"), ("light grey", "#c4c4c4"), ("white", "#f4f4f4"), ("red", "#c8102e"), ("orange", "#e8761c"), ("yellow", "#f2c500"),
           ("green", "#2e8b3d"), ("light green", "#8cc152"), ("teal", "#1b9a9a"), ("blue", "#1f4fb4"), ("navy", "#16285a"), ("purple", "#6b3fa0"), ("pink", "#e58fb0"), ("brown", "#6b4423"),
           ("tan", "#c9a06b"), ("gold", "#c9a23f")]


def palette_dir() -> Path:
    d = Path(os.environ.get("ES_PALETTE_DIR") or (ROOT / "palettes")); d.mkdir(parents=True, exist_ok=True); return d


def _lab(hexc: str):
    def f(c):
        c = c / 255.0; return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
    r, g, b = (f(int(hexc[i:i + 2], 16)) for i in (1, 3, 5))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047; y = 0.2126 * r + 0.7152 * g + 0.0722 * b; z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    t = lambda v: v ** (1 / 3) if v > 0.008856 else 7.787 * v + 16 / 116
    fx, fy, fz = t(x), t(y), t(z); return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e2000(l1, l2) -> float:
    """CIEDE2000 colour difference of two Lab triples."""
    L1, a1, b1 = l1; L2, a2, b2 = l2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2); Cm = (C1 + C2) / 2; G = 0.5 * (1 - math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2; C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1 = math.degrees(math.atan2(b1, a1p)) % 360 if C1p else 0.0; h2 = math.degrees(math.atan2(b2, a2p)) % 360 if C2p else 0.0
    dL = L2 - L1; dC = C2p - C1p
    dh = 0.0
    if C1p * C2p:
        dh = h2 - h1
        if dh > 180: dh -= 360
        elif dh < -180: dh += 360
    dH = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh / 2)); Lm = (L1 + L2) / 2; Cmp = (C1p + C2p) / 2
    if C1p * C2p == 0: hm = h1 + h2
    elif abs(h1 - h2) <= 180: hm = (h1 + h2) / 2
    else: hm = (h1 + h2 + 360) / 2 if h1 + h2 < 360 else (h1 + h2 - 360) / 2
    T = 1 - 0.17 * math.cos(math.radians(hm - 30)) + 0.24 * math.cos(math.radians(2 * hm)) + 0.32 * math.cos(math.radians(3 * hm + 6)) - 0.20 * math.cos(math.radians(4 * hm - 63))
    dTheta = 30 * math.exp(-(((hm - 275) / 25) ** 2)); Rc = 2 * math.sqrt(Cmp ** 7 / (Cmp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lm - 50) ** 2 / math.sqrt(20 + (Lm - 50) ** 2); Sc = 1 + 0.045 * Cmp; Sh = 1 + 0.015 * Cmp * T; Rt = -math.sin(math.radians(2 * dTheta)) * Rc
    return math.sqrt((dL / Sl) ** 2 + (dC / Sc) ** 2 + (dH / Sh) ** 2 + Rt * (dC / Sc) * (dH / Sh))


# --------------------------------------------------------------------------------------------------------------------------------------------------------- palettes
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "palette"


def parse_palette(text: str, fmt: str = "auto") -> Tuple[List[dict], List[str]]:
    """CSV or JSON text -> (colours [{code, name, hex}], rejected-row messages). Raises ValueError when nothing usable is found."""
    if len(text) > 2_000_000: raise ValueError("palette file too large (limit 2 MB)")
    text = text.lstrip("﻿"); rows: List[dict] = []; rej: List[str] = []
    if fmt == "json" or (fmt == "auto" and text.lstrip()[:1] in "[{"):
        try: data = json.loads(text)
        except ValueError as e: raise ValueError(f"not valid JSON: {e}") from e
        if isinstance(data, dict): data = data.get("colours") or data.get("colors") or []
        if not isinstance(data, list): raise ValueError("JSON must be a list of colours")
        rows = [r for r in data if isinstance(r, dict)]
    else:
        sample = text[:2000]; delim = max(",;\t", key=lambda c: sample.count(c))
        rd = csv.DictReader(io.StringIO(text), delimiter=delim); rd.fieldnames = [(h or "").strip().lower() for h in (rd.fieldnames or [])]
        rows = list(rd)
    out = []; seen = set()
    for i, r in enumerate(rows, 1):
        r = {str(k).strip().lower(): v for k, v in r.items()}
        hx = str(r.get("hex") or r.get("colour") or r.get("color") or "").strip()
        if not hx and all(k in r for k in ("r", "g", "b")):
            try: hx = "#%02x%02x%02x" % tuple(int(float(r[k])) for k in ("r", "g", "b"))
            except (ValueError, TypeError): hx = ""
        if hx and not hx.startswith("#"): hx = "#" + hx
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", hx): rej.append(f"row {i}: no valid colour"); continue
        code = str(r.get("code") or r.get("number") or r.get("id") or "").strip()[:32]; name = str(r.get("name") or "").strip()[:80]
        if not code and not name: rej.append(f"row {i}: needs a code or a name"); continue
        key = (code, hx.lower())
        if key in seen: continue
        seen.add(key); out.append({"code": code, "name": name, "hex": hx.lower()})
        if len(out) > MAX_COLOURS: raise ValueError(f"too many colours (limit {MAX_COLOURS})")
    if not out: raise ValueError("no usable colours found (need code / name and hex or r,g,b columns)")
    return out, rej[:20]


def save_palette(name: str, brand: str, colours: List[dict]) -> dict:
    pid = _slug(name)
    if pid == GENERIC_ID: raise ValueError("that name is reserved")
    rec = {"id": pid, "name": name.strip()[:60], "brand": (brand or "").strip()[:40], "source": "imported", "colours": colours}
    (palette_dir() / f"{pid}.json").write_text(json.dumps(rec, indent=1)); return rec


def get_palette(pid: str) -> dict:
    if pid == GENERIC_ID:
        return {"id": GENERIC_ID, "name": "Generic basic colours", "brand": "", "source": "builtin-generic",
                "note": "18 generic colours, NOT a thread-brand chart", "colours": [{"code": str(i + 1), "name": n, "hex": h} for i, (n, h) in enumerate(GENERIC)]}
    if not re.fullmatch(r"[a-z0-9_]{1,40}", pid or ""): raise ValueError("invalid palette id")
    p = palette_dir() / f"{pid}.json"
    if not p.exists(): raise ValueError("unknown palette")
    return json.loads(p.read_text())


def list_palettes() -> List[dict]:
    out = [{"id": GENERIC_ID, "name": "Generic basic colours", "brand": "", "source": "builtin-generic", "count": len(GENERIC)}]
    for p in sorted(palette_dir().glob("*.json")):
        try: r = json.loads(p.read_text()); out.append({"id": r["id"], "name": r["name"], "brand": r.get("brand", ""), "source": "imported", "count": len(r["colours"])})
        except (OSError, ValueError, KeyError): continue
    return out


def delete_palette(pid: str) -> bool:
    if pid == GENERIC_ID or not re.fullmatch(r"[a-z0-9_]{1,40}", pid or ""): raise ValueError("cannot delete that palette")
    p = palette_dir() / f"{pid}.json"
    if p.exists(): p.unlink(); return True
    return False


# --------------------------------------------------------------------------------------------------------------------------------------------------------- matching
def match(hexc: str, palette: dict, n: int = 3) -> List[dict]:
    lab = _lab(hexc); scored = []
    for c in palette["colours"]:
        scored.append((delta_e2000(lab, _lab(c["hex"])), c))
    scored.sort(key=lambda t: t[0])
    return [dict(c, delta_e=round(d, 2)) for d, c in scored[:n]]


def design_colours(design: dict) -> List[str]:
    seen = []; 
    for o in design.get("objects", []):
        for k in ("color", "cover_color"):
            c = o.get(k) if k == "color" else (o.get("params") or {}).get(k)
            if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) and c.lower() not in seen: seen.append(c.lower())
    return seen


def match_design(design: dict, palette: dict) -> dict:
    rows = []
    for c in design_colours(design):
        m = match(c, palette); best = m[0]
        rows.append({"hex": c, "best": best, "alternatives": m[1:], "quality": "close" if best["delta_e"] <= 3 else "acceptable" if best["delta_e"] <= 8 else "poor"})
    return {"palette": {k: palette.get(k) for k in ("id", "name", "brand", "source")}, "rows": rows, "note": "CIEDE2000 distance; <= 3 close, <= 8 acceptable, above that a visibly different thread. Screen colours are not thread colours - check against the physical thread."}


def _recolour(design: dict, mapping: Dict[str, str]) -> int:
    n = 0
    for o in design.get("objects", []):
        c = o.get("color")
        if isinstance(c, str) and c.lower() in mapping: o["color"] = mapping[c.lower()]; n += 1
        p = o.get("params") or {}
        cc = p.get("cover_color")
        if isinstance(cc, str) and cc.lower() in mapping: p["cover_color"] = mapping[cc.lower()]; n += 1
    return n


def apply_palette(design: dict, palette: dict) -> Tuple[dict, dict]:
    """Snap every design colour to its nearest palette colour (design copy returned; `thread_map` records code / name / delta E)."""
    import copy
    d = copy.deepcopy(design); mp = {}; tm = []
    for c in design_colours(d):
        best = match(c, palette, 1)[0]; mp[c] = best["hex"]; tm.append({"from": c, "hex": best["hex"], "code": best["code"], "name": best["name"], "delta_e": best["delta_e"], "palette": palette["id"]})
    n = _recolour(d, mp); d["thread_map"] = tm
    return d, {"objects_recoloured": n, "map": tm}


def replace_colour(design: dict, old: str, new: str) -> Tuple[dict, int]:
    import copy
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", old or "") or not re.fullmatch(r"#[0-9a-fA-F]{6}", new or ""): raise ValueError("colours must be #rrggbb")
    d = copy.deepcopy(design); n = _recolour(d, {old.lower(): new.lower()}); return d, n


# --------------------------------------------------------------------------------------------------------------------------------------------------------- consumption
TOP_FACTOR = 1.25            # top thread laid per mm of stitch path (satin / fill zig-zag, thread take-up, penetration depth) - estimate
BOBBIN_RATIO = 0.35          # bobbin thread as a share of the top thread - estimate (depends on tension and balance)
MM_PER_PENETRATION = 1.2     # extra thread per needle penetration (fabric + stabiliser thickness, both threads pass through) - estimate


def consumption(pattern, threads_hex: Optional[List[str]] = None) -> dict:
    """Estimated thread use per colour: sum of stitch lengths x TOP_FACTOR + MM_PER_PENETRATION per stitch; bobbin = BOBBIN_RATIO of that; jump / trim travel reported
    separately (carried thread). ESTIMATE ONLY - real use depends on thread, tension, fabric and stabiliser."""
    from .model import Cmd
    per: Dict[int, dict] = {}; prev = None; travel = 0.0
    hexes = threads_hex or [t.hex for t in pattern.threads]
    for s in pattern.stitches:
        if s.cmd == Cmd.STITCH:
            r = per.setdefault(s.thread, {"stitches": 0, "path_mm": 0.0})
            r["stitches"] += 1
            if prev is not None and prev[2] == s.thread: r["path_mm"] += math.hypot(s.x - prev[0], s.y - prev[1])
            prev = (s.x, s.y, s.thread)
        elif s.cmd == Cmd.JUMP:
            if prev is not None: travel += math.hypot(s.x - prev[0], s.y - prev[1])
            prev = (s.x, s.y, s.thread)
        elif s.cmd in (Cmd.TRIM, Cmd.COLOR_CHANGE): prev = None
    rows = []
    for t, r in sorted(per.items()):
        top = (r["path_mm"] * TOP_FACTOR + r["stitches"] * MM_PER_PENETRATION) / 1000.0
        rows.append({"thread": t, "hex": hexes[t] if t < len(hexes) else "#000000", "stitches": r["stitches"], "path_m": round(r["path_mm"] / 1000, 3), "top_m": round(top, 2), "bobbin_m": round(top * BOBBIN_RATIO, 2)})
    return {"rows": rows, "top_total_m": round(sum(r["top_m"] for r in rows), 2), "bobbin_total_m": round(sum(r["bobbin_m"] for r in rows), 2), "travel_m": round(travel / 1000, 2),
            "formula": f"top = path x {TOP_FACTOR} + {MM_PER_PENETRATION} mm per stitch; bobbin = {int(BOBBIN_RATIO * 100)} % of top",
            "note": "ESTIMATE, not measured. Real consumption depends on thread weight, tension, fabric and stabiliser."}
