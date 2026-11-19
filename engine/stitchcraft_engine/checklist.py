"""Production checklist: the 15 required checks before a DST is released for a machine test.

Every item is evaluated automatically from the design, the generated stitches and the written-and-reopened DST, and returns
PASS / WARN / FAIL / N/A with the evidence. Export is blocked on any FAIL. WARN means "review before stitching".
"""
import math
from typing import Dict, List

from .design import DEFAULTS, THREADS, generate, machine, run_checks
from .dst import read_dst, write_dst
from .geometry import polygon_area
from .model import Cmd
from . import dst_analyze, dst_verify
from .profiles import underlay_shift

PRODUCTION_STITCH_LIMIT = 150_000        # a single garment design above this is unusual; machine memory is far larger


def _item(n, title, level, evidence):
    return {"n": n, "title": title, "level": level, "evidence": evidence}


def _width(o):
    if o["type"] == "satin":
        return float(((o.get("params") or {})).get("width", DEFAULTS["satin"]["width"]))
    r1, r2 = o.get("rail1") or [], o.get("rail2") or []
    n = min(len(r1), len(r2))
    inner = list(zip(r1[1:n - 1], r2[1:n - 1])) or list(zip(r1[:n], r2[:n]))
    return sum(math.dist(a, b) for a, b in inner) / max(1, len(inner))


def _overlap_ratio(pattern, kinds: Dict[str, str], cell: float = 0.5) -> float:
    """Share of the filled area covered by two or more different fill objects (stacked fills)."""
    owners = {}
    for s in pattern.stitches:
        if s.cmd == Cmd.STITCH and kinds.get(str(s.object_id).split(".")[0]) == "fill":
            owners.setdefault((math.floor(s.x / cell), math.floor(s.y / cell)), set()).add(s.object_id)
    if not owners:
        return 0.0
    return sum(1 for v in owners.values() if len(v) > 1) / len(owners)


def evaluate(design: dict) -> dict:
    items: List[dict] = []
    objs = [o for o in design.get("objects", []) if not o.get("hidden") and not o.get("guide") and o.get("type") != "embellishment"]
    m = machine(design)
    hoop = design.get("hoop", {})
    hw, hh = float(hoop.get("w", 100)), float(hoop.get("h", 100))
    k = THREADS.get(design.get("thread") or "40wt", THREADS["40wt"])["k"]
    try:
        pattern, notes, st = generate(design)
    except ValueError as e:
        return {"items": [_item(1, "Design generates stitches", "FAIL", str(e))], "passed": 0, "total": 15, "export_allowed": False}
    rep = run_checks(design, pattern)
    res = write_dst(pattern, trim_jumps=m["trim_jumps"])
    back = read_dst(res.data)
    ver = dst_verify.verify(res.data, (hw, hh), k, 15, design.get("name", "design"))
    ana = dst_analyze.analyze(res.data)
    stage = {s["stage"][0]: s for s in ver["stages"]}

    # 1 reference image cleaned and vectorised
    src = design.get("source") or {}
    if src.get("type") == "raster":
        r = src.get("report") or {}
        ev = f"palette {r.get('colours_used', '?')} colour(s), {r.get('colours_merged', 0)} shade(s) merged, {r.get('dropped_specks', 0)} speck(s) removed" + \
             (f", enhanced {r['enhance']['source_px']}->{r['enhance']['result_px']} px" if isinstance(r.get("enhance"), dict) and r["enhance"].get("result_px") else "")
        items.append(_item(1, "Reference image cleaned and vectorised", "WARN" if r.get("photographic") else "PASS",
                           ev + ("; looks like a photo - result is a flat-colour interpretation" if r.get("photographic") else "")))
    else:
        items.append(_item(1, "Reference image cleaned and vectorised", "N/A", "vector / hand-digitized design (no raster source)"))
    # 2 dimensions within hoop
    errs = [i for i in rep.issues if i.code in ("OUT_OF_HOOP", "HOOP", "OUTSIDE_HOOP") or "hoop" in i.message.lower()]
    lvl = "FAIL" if any(i.severity == "error" for i in errs) else "WARN" if errs else "PASS"
    items.append(_item(2, "Design dimensions within hoop limits", lvl, f"{st['width_mm']} x {st['height_mm']} mm in a {hw:g} x {hh:g} mm hoop (margin {hoop.get('margin', 3)} mm)"))
    # 3 satin widths
    sat = [(o.get("name") or o["id"], _width(o)) for o in objs if o["type"] in ("satin", "column")]
    narrow = [n for n, w in sat if w < 1.0]; wide = [n for n, w in sat if w > 7.0 and m["max_stitch"] > w]
    lvl = "WARN" if narrow or wide else "PASS" if sat else "N/A"
    items.append(_item(3, "Satin columns have suitable widths", lvl,
                       (f"{len(sat)} satin/column object(s), widths {min(w for _, w in sat):.1f}-{max(w for _, w in sat):.1f} mm" if sat else "no satin objects") +
                       (f"; under 1 mm: {', '.join(narrow[:5])}" if narrow else "") + (f"; over 7 mm and not split: {', '.join(wide[:5])}" if wide else "")))
    # 4 fill density vs fabric
    from .profiles import FABRICS
    fk = FABRICS.get((design.get("profile") or {}).get("fabric") or design.get("fabric") or "cotton", FABRICS["cotton"])["k"]
    target = 0.4 * k * fk
    fills = [(o.get("name") or o["id"], float(((o.get("params") or {})).get("spacing", DEFAULTS["fill"]["spacing"] * k))) for o in objs if o["type"] == "fill"]
    off = [f"{n} ({s:.2f})" for n, s in fills if not 0.75 * target <= s <= 1.35 * target]
    items.append(_item(4, "Fill density appropriate for fabric", ("WARN" if off else "PASS") if fills else "N/A",
                       f"target ~{target:.2f} mm line spacing for this fabric + thread" + (f"; outside 0.75-1.35x: {', '.join(off[:5])}" if off else f"; {len(fills)} fill(s) in range")))
    # 5 underlay where required
    need = []
    light = underlay_shift(design) < 0
    fill_min = 60 if light else 25                      # light fabric / saree profile: minimal underlay by design (spec section 3)
    for o in objs:
        p = (o.get("params") or {})
        if o["type"] in ("satin", "column") and _width(o) >= 2.0 and p.get("underlay", "auto") == "none":
            need.append(o.get("name") or o["id"])
        if o["type"] == "fill" and o.get("rings") and abs(polygon_area(o["rings"][0])) >= fill_min and p.get("underlay", "tatami") in ("none", False):
            need.append(o.get("name") or o["id"])
    items.append(_item(5, "Underlay generated where required", "WARN" if need else "PASS",
                       f"missing on: {', '.join(need[:6])}" if need else f"every satin >= 2 mm and fill >= {fill_min} mm2 has underlay"))
    # 6 pull compensation
    nopc = [o.get("name") or o["id"] for o in objs if o["type"] in ("fill", "satin", "column") and not float(((o.get("params") or {})).get("pull_comp", DEFAULTS[o["type"]].get("pull_comp", 0)) or 0)]
    items.append(_item(6, "Pull compensation configured", "WARN" if nopc else "PASS",
                       f"no pull compensation on: {', '.join(nopc[:6])}" if nopc else "set on every fill / satin / column"))
    # 7 overlapping stitches
    kinds = {o["id"]: o["type"] for o in objs}
    ov = _overlap_ratio(pattern, kinds)
    items.append(_item(7, "No excessive overlapping stitches", "WARN" if ov > 0.30 else "PASS",
                       f"{ov * 100:.0f}% of the filled area is covered by more than one fill object" + (" - tick 'Cut hidden layers' on the lower fills (or apply a profile)" if ov > 0.30 else "")))
    # 8 short stitches
    tiny = sum(1 for i in rep.issues if i.code == "STITCH_SHORT")
    items.append(_item(8, "No excessively short stitches", "WARN" if ana["pct_short_clustered"] >= 3.0 or tiny else "PASS",
                       f"{tiny} stitch(es) under {m['min_stitch']:g} mm; {ana['pct_short_clustered']}% in clusters of 2+ stitches < 0.5 mm ({ana['pct_short_lt0.5']}% incl. lone row turns and locks)"))
    # 9 long stitches split
    longest = 0.0; last = None
    for s in pattern.stitches:
        if s.cmd == Cmd.STITCH and last is not None and last.cmd == Cmd.STITCH:
            longest = max(longest, math.hypot(s.x - last.x, s.y - last.y))
        last = s
    items.append(_item(9, "Long stitches appropriately split", "FAIL" if longest > 12.1 else "WARN" if longest > m["max_stitch"] + 0.05 else "PASS",
                       f"longest stitch {longest:.1f} mm (machine profile max {m['max_stitch']:g} mm, DST limit 12.1 mm)"))
    # 10 unintended long jumps (carried thread, no trim)
    carried, prev = [], None
    trimmed = False
    for s in pattern.stitches:
        if s.cmd == Cmd.TRIM:
            trimmed = True
        elif s.cmd == Cmd.JUMP and prev is not None:
            d = math.hypot(s.x - prev[0], s.y - prev[1])
            if d > m["trim_distance"] + 0.05 and not trimmed:
                carried.append(round(d, 1))
        elif s.cmd == Cmd.STITCH:
            trimmed = False
        prev = (s.x, s.y)
    items.append(_item(10, "No unintended long jumps", "WARN" if carried else "PASS",
                       f"{len(carried)} carried jump(s) over {m['trim_distance']:g} mm without a trim: {carried[:5]}" if carried else f"every travel over {m['trim_distance']:g} mm is trimmed ({st['trims']} trims)"))
    # 11 trims and colour stops
    ok_cc = back.color_changes == st["color_changes"]
    items.append(_item(11, "Thread trims and colour stops checked", "PASS" if ok_cc else "FAIL",
                       f"{st['color_changes']} colour stop(s) for {len(st['color_sequence'])} colour block(s); {st['trims']} trims; trim at colour change {'on' if m['trim_at_color_change'] else 'off'}"))
    # 12 tie-in / tie-off
    lock_check = next((c for c in stage["5"]["checks"] if "tied in" in c["what"]), None)
    items.append(_item(12, "Tie-in and tie-off points checked", ("PASS" if m["lock_len"] and lock_check and lock_check["level"] == "PASS" else "WARN"),
                       (f"{st.get('lock_stitches', 0)} lock stitches of {m['lock_len']:g} mm; " if m["lock_len"] else "lock stitches are OFF; ") + (lock_check["evidence"] if lock_check else "")))
    # 13 stitch count
    items.append(_item(13, "Stitch count within production limits", "PASS" if st["stitches"] <= PRODUCTION_STITCH_LIMIT else "WARN",
                       f"{st['stitches']} stitches, ~{st['est_minutes']} min at {st['assumed_spm']:.0f} spm (limit {PRODUCTION_STITCH_LIMIT:,})"))
    # 14 DST header + command sequence
    lv = "FAIL" if "FAIL" in (stage["1"]["result"], stage["2"]["result"]) else "WARN" if "WARN" in (stage["1"]["result"], stage["2"]["result"]) else "PASS"
    items.append(_item(14, "DST header and command sequence validated", lv, f"container {stage['1']['result']}, encoding {stage['2']['result']}; {res.record_count} records, sha256 {res.sha256[:12]}"))
    # 15 reopened and simulated
    n_back = sum(1 for _, _, c in back.records if c == "stitch")
    ok = back.ends_properly and stage["6"]["result"] != "FAIL" and n_back >= st["stitches"]
    items.append(_item(15, "DST reopened and simulated successfully", "PASS" if ok else "FAIL",
                       f"reopened: {n_back} stitch records, ends with END={back.ends_properly}; simulation {stage['6']['result']} ({stage['6']['checks'][0]['evidence']})"))
    passed = sum(1 for i in items if i["level"] in ("PASS", "N/A"))
    return {"items": items, "passed": passed, "total": len(items), "export_allowed": not any(i["level"] == "FAIL" for i in items) and rep.ok,
            "verify_grade": ver["grade"], "stats": {k2: st[k2] for k2 in ("stitches", "color_changes", "trims", "width_mm", "height_mm", "est_minutes")},
            "colour_sequence": st["color_sequence"]}


def colour_report_csv(design: dict, st: dict) -> str:
    """DST carries colour-change positions only, not thread colours: this is the separate thread-sequence report."""
    lines = ["stop,needle,thread_hex,stitches,note"]
    for i, c in enumerate(st["color_sequence"]):
        lines.append(f"{i + 1},,{c['hex']},{c['stitches']},{'start' if i == 0 else 'colour change'}")
    return "\n".join(lines) + "\n"
