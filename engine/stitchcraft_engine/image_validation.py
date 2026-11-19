"""Image-to-DST validation: nine independent software passes comparing an uploaded artwork with the exported DST.

EVERYTHING HERE IS SOFTWARE MEASUREMENT. A high score is not proof of stitch-out quality; physical validation is always reported as PENDING.
Needs Pillow + NumPy (optional dependencies); without them `validate` returns a clear "not run" report.

Frames: the import works in image millimetres (origin top-left, width = the width the user chose). The design may later be scaled / centred (auto-fix);
the transform image-mm -> design-mm is recovered from objects that survive with the same id and verified by its residual. The DST is decoded
(`export_pipeline.decoded_simulation`) and drawn with a thread width of 0.45 mm; that raster is what gets compared with the original.

Metrics (all measured on a common grid of PPM pixels per mm):
  ink_recall        share of the original's ink (non-background palette pixels) that lies under a stitched shape of the same colour (0.25 mm tolerance)
  stitched_spill    share of the stitched area that is NOT on original ink (extra stitching)
  boundary_p95_mm   the distance (0.1 / 0.25 / 0.5 / 1 / 2 mm steps) within which 95 % of the ink boundary pixels have a stitched boundary (and vice versa; the larger of the two)
  thread_coverage   share of the stitched shapes that real thread lines (decoded DST) actually cover after a 0.35 mm closing (gaps / unstitched holes)
  colour_match_min  for every ink colour: the share of its ink that has thread of the matching colour under it; the smallest of these (colour-region correspondence)
  spill tolerance   0.5 mm: a thread is 0.45 mm wide and pull compensation adds ~0.2-0.25 mm, so thread legitimately extends that far beyond the shape edge
  micro_coverage    share of inventoried details that were stitched (digitized or micro_representation); the rest is listed with its reason
"""
from __future__ import annotations
import base64
import io
import math
from typing import Dict, List, Optional

PPM = 4.0                      # comparison pixels per mm
THREAD_MM = 0.45
THRESHOLDS = {"ink_recall": 0.97, "stitched_spill": 0.04, "boundary_p95_mm": 0.5, "dst_boundary_p95_mm": 0.75, "spill_tolerance_mm": 0.5, "thread_coverage": 0.85, "colour_match_min": 0.93, "micro_coverage_review": 1.0,
              "unexplained_ink": 0.01, "mapping_residual_mm": 0.6, "optimisation_area_delta": 0.03}
DISCLAIMER = ("Software measurement only: these numbers compare the digitized design and the decoded DST with the uploaded image. "
              "They are not proof of stitch-out quality, and physical machine validation is PENDING.")


def _np():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    return np, Image, ImageDraw, ImageFilter


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _nearest(colour, palette):
    return min(range(len(palette)), key=lambda i: sum((a - b) ** 2 for a, b in zip(colour, palette[i])))


def _dilate(mask, px, np, Image, ImageFilter):
    if px <= 0:
        return mask
    k = 2 * px + 1
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(k))) > 0


def _erode(mask, px, np, Image, ImageFilter):
    if px <= 0:
        return mask
    k = 2 * px + 1
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(k))) > 0


def _boundary(mask, np, Image, ImageFilter):
    return mask & ~_erode(mask, 1, np, Image, ImageFilter)


def _object_masks(objs, W, H, ppm, np, Image, ImageDraw, tf=lambda p: p):
    """Per-colour raster of the shapes that are stitched (fills with holes, column bodies, run / manual lines at 0.45 mm)."""
    out = {}
    for o in objs:
        m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m)
        P = lambda pts: [(tf(p)[0] * ppm, tf(p)[1] * ppm) for p in pts]
        t = o.get("type")
        if t == "fill":
            for k, r in enumerate(o["rings"]):
                if len(r) >= 3:
                    d.polygon(P(r), fill=255 if k == 0 else 0)
        elif t == "column":
            d.polygon(P(o["rail1"] + o["rail2"][::-1]), fill=255)
        elif t in ("run", "satin", "manual"):
            d.line(P(o["points"]), fill=255, width=max(1, round(THREAD_MM * ppm)))
        elif t == "applique":
            continue
        c = o.get("color", "#000000")
        out[c] = out.get(c, np.zeros((H, W), bool)) | (np.asarray(m) > 0)
    return out


def recover_transform(before: List[dict], after: List[dict]) -> dict:
    """Similarity (scale + translation) from image-mm to design-mm using objects that kept their id. Verified by the residual of object-box centres."""
    def box(o):
        pts = [p for r in o.get("rings", []) for p in r] + list(o.get("points", [])) + list(o.get("rail1", [])) + list(o.get("rail2", []))
        if not pts:
            return None
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)
    A = {o["id"]: box(o) for o in before if box(o)}; B = {o["id"]: box(o) for o in after if box(o)}
    common = [i for i in A if i in B]
    if not common:
        return {"ok": False, "reason": "no object kept its id; the frame cannot be recovered", "scale": 1.0, "dx": 0.0, "dy": 0.0, "residual_mm": None, "common": 0}
    ua = [min(A[i][0] for i in common), min(A[i][1] for i in common), max(A[i][2] for i in common), max(A[i][3] for i in common)]
    ub = [min(B[i][0] for i in common), min(B[i][1] for i in common), max(B[i][2] for i in common), max(B[i][3] for i in common)]
    wa, ha, wb, hb = ua[2] - ua[0], ua[3] - ua[1], ub[2] - ub[0], ub[3] - ub[1]
    sx, sy = (wb / wa if wa > 1e-9 else 1.0), (hb / ha if ha > 1e-9 else 1.0)
    s = (sx + sy) / 2 if wa > 1e-9 and ha > 1e-9 else (sx if wa > 1e-9 else sy)
    dx, dy = ub[0] - s * ua[0], ub[1] - s * ua[1]
    res = max(math.hypot(s * (A[i][0] + A[i][2]) / 2 + dx - (B[i][0] + B[i][2]) / 2, s * (A[i][1] + A[i][3]) / 2 + dy - (B[i][1] + B[i][3]) / 2) for i in common)
    return {"ok": True, "scale": round(s, 6), "dx": round(dx, 4), "dy": round(dy, 4), "residual_mm": round(res, 3), "common": len(common), "anisotropy": round(abs(sx - sy), 5)}


def _png(arr, np, Image):
    b = io.BytesIO(); Image.fromarray(arr).save(b, "PNG"); return b.getvalue()


def validate(original: bytes, width_mm: float, imp: dict, design: Optional[dict] = None, export=None, ppm: float = PPM) -> dict:
    """Run the nine passes. `imp` = the digitize_image() result (needs its `_work` label map); `design` = the final design (default: the imported objects as they are);
    `export` = an ExportResult (default: exported here)."""
    try:
        np, Image, ImageDraw, ImageFilter = _np()
    except ImportError:
        return {"ran": False, "reason": "image validation needs the optional Pillow and NumPy packages", "physical_validation": "PENDING", "disclaimer": DISCLAIMER}
    from . import fidelity, export_pipeline as EP, quality as Q
    work = imp.get("_work")
    if not work:
        raise ValueError("import result has no working label map; run digitize_image() from this version")
    objs_before = imp["objects"]; inventory = imp.get("inventory", []); rep = imp["report"]
    W, H = max(1, round(width_mm * ppm)), max(1, round(imp["size_mm"][1] * ppm))
    passes: List[dict] = []
    risks: List[str] = []

    def add(n, name, result, detail, metrics=None):
        passes.append({"pass": n, "name": name, "result": result, "detail": detail, "metrics": metrics or {}})

    # ---- design + DST
    if design is None:
        h = max(100, math.ceil(max(width_mm, imp["size_mm"][1]) + 20))
        design = {"name": "image", "hoop": {"w": h, "h": h, "margin": 3}, "objects": [dict(o) for o in objs_before], "thread": "40wt"}
    tr = recover_transform(objs_before, design.get("objects", []))
    tf = (lambda p: ((p[0] - tr["dx"]) / tr["scale"], (p[1] - tr["dy"]) / tr["scale"])) if tr["ok"] and tr["scale"] else (lambda p: p)     # design-mm -> image-mm
    exp_err = None
    try:
        res = export or EP.export_dst(design)
    except EP.ExportError as e:
        res, exp_err = None, e
    # ---- 1 source completeness
    src = fidelity.source_record(original, width_mm)
    wk = rep.get("work_px", [0, 0]); sp = rep.get("source_px", [0, 0])
    aspect_ok = bool(sp[0] and wk[0] and abs(sp[0] / sp[1] - wk[0] / wk[1]) < 0.02)
    add(1, "Source image completeness", "PASSED" if aspect_ok and src["preserved"] else "FAILED",
        f"original {sp[0]}x{sp[1]} px (SHA-256 {src['sha256'][:12]}), analysed whole at {wk[0]}x{wk[1]} px working resolution ({imp['size_mm'][0] / max(wk[0], 1):.3f} mm/px); aspect preserved: {aspect_ok}",
        {"source": src, "working_px": wk, "mm_per_px": round(work["mm_per_px"], 4)})
    # ---- 2 segmentation completeness (ink accounting)
    cov = rep["coverage"]; not_st = sum(r["area_mm2"] for r in inventory if r["status"] == "not_stitchable")
    unexplained = max(0.0, cov["ink_area_mm2"] - cov["stitched_area_mm2"] - not_st - cov["noise_specks"]["area_mm2"] - cov["antialiasing_fringe"]["area_mm2"])
    un_frac = unexplained / cov["ink_area_mm2"] if cov["ink_area_mm2"] else 0.0
    unresolved = rep.get("unresolved", [])
    r2 = "FAILED" if un_frac > THRESHOLDS["unexplained_ink"] else ("WARNING" if unresolved else "PASSED")
    add(2, "Segmentation completeness", r2,
        f"{len(inventory)} regions inventoried; ink {cov['ink_area_mm2']} mm2 = stitched {cov['stitched_area_mm2']} + not stitchable {round(not_st, 2)} + noise {cov['noise_specks']['area_mm2']} + fringe {cov['antialiasing_fringe']['area_mm2']}; "
        f"unexplained {100 * un_frac:.2f} % (limit {100 * THRESHOLDS['unexplained_ink']:g} %); {len(unresolved)} detail(s) need review",
        {"inventory": len(inventory), "status": rep.get("inventory_status"), "unexplained_fraction": round(un_frac, 5), "unresolved": unresolved})
    if unresolved:
        risks.append(f"{len(unresolved)} detail(s) are too small to stitch safely and were left out; review them in the inventory")
    # ---- ink masks of the ORIGINAL (from the label map of the full-resolution analysis), common grid
    labels, pal, bg = work["labels"], [tuple(c) for c in work["pal"]], work["bg"]
    lh, lw = labels.shape
    ink_by = {}
    for ci in range(len(pal)):
        if ci == bg:
            continue
        m = np.asarray(Image.fromarray((labels == ci).astype(np.uint8) * 255).resize((W, H), Image.NEAREST)) > 0
        ink_by[pal[ci]] = m
    ink_all = np.zeros((H, W), bool)
    for m in ink_by.values():
        ink_all |= m
    # ---- 3 geometry (vector model vs the original ink)
    om = _object_masks(objs_before, W, H, ppm, np, Image, ImageDraw)
    obj_all = np.zeros((H, W), bool)
    for m in om.values():
        obj_all |= m
    tol = max(1, round(0.25 * ppm))

    def p95_distance(a, b):
        """Smallest step d (mm) such that >= 95 % of the boundary pixels of mask a lie within d of mask b."""
        ba = _boundary(a, np, Image, ImageFilter)
        n = int(ba.sum())
        if n == 0:
            return 0.0
        for d_mm in (0.1, 0.25, 0.5, 0.75, 1.0, 2.0):
            near = _dilate(b, max(1, round(d_mm * ppm)), np, Image, ImageFilter)
            if (ba & near).sum() / n >= 0.95:
                return d_mm
        return 99.0
    near_obj = _dilate(obj_all, tol, np, Image, ImageFilter)
    recall_vec = float((ink_all & near_obj).sum() / ink_all.sum()) if ink_all.any() else 1.0
    dev_vec = max(p95_distance(ink_all, obj_all), p95_distance(obj_all, ink_all))
    exp_w, exp_h = width_mm, imp["size_mm"][1]
    add(3, "Geometry validation", "PASSED" if dev_vec <= THRESHOLDS["boundary_p95_mm"] and recall_vec >= THRESHOLDS["ink_recall"] else "FAILED",
        f"vector objects vs original ink: recall {100 * recall_vec:.2f} % (min {100 * THRESHOLDS['ink_recall']:g} %), boundary within {dev_vec:g} mm for 95 % of the outline (max {THRESHOLDS['boundary_p95_mm']:g} mm); size {exp_w:g} x {exp_h:.1f} mm",
        {"ink_recall_vector": round(recall_vec, 4), "boundary_p95_mm_vector": dev_vec, "size_mm": [round(exp_w, 2), round(exp_h, 2)]})
    # ---- 4 stitch generation
    if res is not None and exp_err is None:
        from .design import generate
        pattern, notes, st = generate(design)
        q = Q.quality_report(design, pattern, notes)
        from .checklist import evaluate
        cl = evaluate(design)
        r4 = "FAILED" if (q["blocking"] or not cl["export_allowed"]) else ("WARNING" if q["issues"] or cl["passed"] < cl["total"] else "PASSED")
        add(4, "Stitch generation", r4, f"{st['stitches']} stitches, quality score {q['score']}/100 (software), checklist {cl['passed']}/{cl['total']}, {len(q['issues'])} quality issue(s)",
            {"stitches": st["stitches"], "quality_score": q["score"], "checklist": f"{cl['passed']}/{cl['total']}", "stats": {k: st[k] for k in ("stitches", "jumps", "trims", "color_changes", "width_mm", "height_mm", "est_minutes")}})
    else:
        add(4, "Stitch generation", "FAILED", f"the design could not be exported: {exp_err}")
        risks.append(f"export refused: {exp_err}")
    # ---- 5 optimisation (objects before vs after, measured)
    after = design.get("objects", [])
    ids_b = {o["id"] for o in objs_before}; ids_a = {o["id"] for o in after}
    removed = sorted(ids_b - ids_a); added = sorted(ids_a - ids_b)
    am = _object_masks([o for o in after if o["id"] in ids_b], W, H, ppm, np, Image, ImageDraw, tf)
    after_all = np.zeros((H, W), bool)
    for m in am.values():
        after_all |= m
    area_b, area_a = int(obj_all.sum()), int(after_all.sum())
    delta = abs(area_a - area_b) / area_b if area_b else 0.0
    r5 = "PASSED" if not removed and delta <= THRESHOLDS["optimisation_area_delta"] else "WARNING"
    add(5, "Optimisation validation", r5, f"{len(removed)} object(s) removed, {len(added)} added, stitched-shape area change {100 * delta:.2f} % (limit {100 * THRESHOLDS['optimisation_area_delta']:g} %)",
        {"removed": removed, "added": added, "area_delta": round(delta, 5), "transform": tr})
    if removed:
        risks.append(f"optimisation removed {len(removed)} object(s): {', '.join(removed[:8])}")
    if not tr["ok"] or (tr["residual_mm"] is not None and tr["residual_mm"] > THRESHOLDS["mapping_residual_mm"]):
        risks.append("the image-to-design frame could not be verified; the comparison below may be misaligned")
    # ---- 6 DST export + independent re-import
    if res is not None:
        rr = res.report
        ir = rr["validation"]["independent_reader"]
        add(6, "DST export and independent re-import", "PASSED", f"SHA-256 {res.sha256[:12]}, {rr['records']} records; decode-compare passed; independent reader: {ir}",
            {"sha256": res.sha256, "records": rr["records"], "independent_reader": ir, "stages": [s["stage"] + ":" + str(s["result"]) for s in rr["stages"]]})
        if not str(ir).startswith("PASSED"):
            risks.append("the independent DST reader (pyembroidery) was not available in this run")
    else:
        add(6, "DST export and independent re-import", "FAILED", str(exp_err))
    # ---- 7 coordinates / movement, 8 visual comparison need the decoded DST
    thread_mask = np.zeros((H, W), bool); colour_masks: Dict[tuple, "np.ndarray"] = {}
    if res is not None:
        sim = EP.decoded_simulation(design)
        pat_threads = [_hex(h) for h in sim["threads"]]
        by_thread = {}
        prev = None
        for x, y, cmd, th, oi in sim["stitches"]:
            if cmd == 0 and prev is not None and prev[3] == th:
                by_thread.setdefault(th, []).append(((prev[0], prev[1]), (x, y)))
            prev = (x, y, cmd, th) if cmd in (0, 1) else None
        wpx = max(1, round(THREAD_MM * ppm))
        for th, segs in by_thread.items():
            m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m)
            for a, b in segs:
                ia, ib = tf(a), tf(b)
                d.line([(ia[0] * ppm, ia[1] * ppm), (ib[0] * ppm, ib[1] * ppm)], fill=255, width=wpx)
            arr = np.asarray(m) > 0
            colour_masks[pat_threads[th] if th < len(pat_threads) else (0, 0, 0)] = colour_masks.get(pat_threads[th] if th < len(pat_threads) else (0, 0, 0), np.zeros((H, W), bool)) | arr
            thread_mask |= arr
        # orientation: the stitched raster must correlate better with the ink than with its mirror images
        def corr(a, b):
            a, b = a.astype(float), b.astype(float)
            return float((a * b).sum() / max(1.0, math.sqrt(a.sum() * b.sum())))
        cl_mask = _dilate(thread_mask, tol, np, Image, ImageFilter)
        orient = {"identity": corr(cl_mask, ink_all), "mirror_x": corr(cl_mask[:, ::-1], ink_all), "mirror_y": corr(cl_mask[::-1, :], ink_all), "transpose": corr(cl_mask.T[:H, :W], ink_all) if H == W else None}
        best = max((k for k, v in orient.items() if v is not None), key=lambda k: orient[k])
        rr = res.report
        add(7, "Coordinate and movement validation", "PASSED" if best == "identity" and rr["size_mm"] else "FAILED",
            f"decoded design {rr['size_mm'][0]} x {rr['size_mm'][1]} mm; max movement per record <= 12.1 mm and positions matched the plan within 0.06 mm (decode-compare); orientation test: best match with '{best}' "
            f"(identity {orient['identity']:.2f}, mirror-x {orient['mirror_x']:.2f}, mirror-y {orient['mirror_y']:.2f})",
            {"orientation": {k: (None if v is None else round(v, 3)) for k, v in orient.items()}, "best": best, "size_mm": rr["size_mm"], "counts": rr["counts"]})
        # ---- 8 visual comparison
        thread_closed = _dilate(_erode(_dilate(thread_mask, max(1, round(0.35 * ppm)), np, Image, ImageFilter), 0, np, Image, ImageFilter), 0, np, Image, ImageFilter)
        stitched_shapes = np.zeros((H, W), bool)
        am_all = _object_masks(after, W, H, ppm, np, Image, ImageDraw, tf)
        for m in am_all.values():
            stitched_shapes |= m
        near_thread = _dilate(thread_mask, tol, np, Image, ImageFilter)
        spill_px = max(1, round(THRESHOLDS["spill_tolerance_mm"] * ppm))
        recall = float((ink_all & near_thread).sum() / ink_all.sum()) if ink_all.any() else 1.0
        spill = float((near_thread & ~_dilate(ink_all, spill_px, np, Image, ImageFilter)).sum() / max(1, near_thread.sum()))
        dev = max(p95_distance(ink_all, near_thread), p95_distance(near_thread, ink_all))
        tcov = float((stitched_shapes & thread_closed).sum() / max(1, stitched_shapes.sum()))
        total_ink = max(1, int(ink_all.sum()))
        match_min, match_detail = 1.0, {}
        for c, m in ink_by.items():
            if not m.any():
                continue
            if ('#%02x%02x%02x' % c) not in {o.get('color') for o in objs_before}:
                continue                                  # a palette colour that produced no object is only antialiasing / noise dust; it is accounted in the inventory coverage
            same = np.zeros((H, W), bool)
            for k_, mm_ in colour_masks.items():
                if sum((a_ - b_) ** 2 for a_, b_ in zip(k_, c)) < 40 ** 2:
                    same |= mm_
            val = float((m & _dilate(same, tol, np, Image, ImageFilter)).sum() / m.sum())
            match_detail["#%02x%02x%02x" % c] = round(val, 4); match_min = min(match_min, val)
        ok8 = recall >= THRESHOLDS["ink_recall"] and spill <= THRESHOLDS["stitched_spill"] and dev <= THRESHOLDS["dst_boundary_p95_mm"] and tcov >= THRESHOLDS["thread_coverage"] and match_min >= THRESHOLDS["colour_match_min"]
        add(8, "Visual comparison (original vs decoded DST)", "PASSED" if ok8 else "FAILED",
            f"decoded-DST thread raster vs original ink: recall {100 * recall:.2f} % (min {100 * THRESHOLDS['ink_recall']:g}), spill {100 * spill:.2f} % (max {100 * THRESHOLDS['stitched_spill']:g}, tolerance {THRESHOLDS['spill_tolerance_mm']:g} mm), "
            f"boundary within {dev:g} mm for 95 % (max {THRESHOLDS['dst_boundary_p95_mm']:g}), thread coverage of stitched shapes {100 * tcov:.1f} % (min {100 * THRESHOLDS['thread_coverage']:g}), worst colour match {100 * match_min:.1f} % (min {100 * THRESHOLDS['colour_match_min']:g})",
            {"ink_recall": round(recall, 4), "stitched_spill": round(spill, 4), "boundary_p95_mm": dev, "thread_coverage": round(tcov, 4), "colour_match_min": round(match_min, 4), "colour_match": match_detail,
             "thresholds": {k_: THRESHOLDS[k_] for k_ in ("ink_recall", "stitched_spill", "dst_boundary_p95_mm", "thread_coverage", "colour_match_min", "spill_tolerance_mm")}})
        # derived images (never the original): overlay and difference map
        base = np.asarray(Image.fromarray(np.asarray(Image.open(io.BytesIO(original)).convert("RGB"))).resize((W, H), Image.LANCZOS)).astype(float)
        over = (base * 0.35 + 255 * 0.65).astype(np.uint8)
        for c, m in colour_masks.items():
            over[m] = c
        diff = np.full((H, W, 3), 255, np.uint8)
        diff[ink_all & near_thread] = (90, 190, 120)                                   # green: ink with thread
        diff[ink_all & ~near_thread] = (220, 38, 38)                                   # red: ink with no stitching (missing)
        diff[near_thread & ~_dilate(ink_all, spill_px, np, Image, ImageFilter)] = (37, 99, 235)   # blue: stitching with no ink (extra)
        derived = {"overlay.png": _png(over, np, Image), "difference.png": _png(diff, np, Image)}
        if recall < THRESHOLDS["ink_recall"]:
            risks.append(f"{100 * (1 - recall):.1f} % of the original's ink has no stitching under it (red in the difference map)")
        if spill > THRESHOLDS["stitched_spill"]:
            risks.append(f"{100 * spill:.1f} % of the stitching lies outside the original's ink (blue in the difference map)")
    else:
        add(7, "Coordinate and movement validation", "FAILED", "no DST was produced")
        add(8, "Visual comparison (original vs decoded DST)", "FAILED", "no DST was produced")
        derived = {}
    # ---- micro-detail coverage is reported inside pass 9 (final) with the rest
    stitched_items = sum(1 for r in inventory if r["status"] in ("digitized", "micro_representation"))
    micro_cov = stitched_items / len(inventory) if inventory else 1.0
    if rep.get("photographic"):
        risks.append("the source looks like a photograph or shaded artwork: it was reduced to flat colour regions and cannot match the photo; check every region")
    if rep.get("dpi", 999) < 150:
        risks.append(f"low source resolution (about {rep['dpi']} dpi at this size): fine detail that is not in the source cannot be recovered")
    mandatory = [p for p in passes if p["pass"] in (1, 2, 3, 4, 5, 6, 7, 8)]
    failed = [p["pass"] for p in mandatory if p["result"] == "FAILED"]
    warn = [p["pass"] for p in mandatory if p["result"] == "WARNING"]
    verdict = "FAILED" if failed else ("PASSED_WITH_WARNINGS" if warn or unresolved else "PASSED")
    add(9, "Final production validation", "FAILED" if failed else ("WARNING" if warn or unresolved or risks else "PASSED"),
        f"software validation {verdict}; micro-detail coverage {100 * micro_cov:.1f} % ({stitched_items}/{len(inventory)} inventoried details stitched); {len(risks)} remaining risk(s); physical machine validation PENDING",
        {"micro_coverage": round(micro_cov, 4), "failed_passes": failed, "warning_passes": warn})
    return {"ran": True, "software_validation": verdict, "physical_validation": "PENDING - no stitch-out evidence exists for this file", "passes": passes, "remaining_risks": risks,
            "thresholds": THRESHOLDS, "disclaimer": DISCLAIMER, "derived_images": {k: base64.b64encode(v).decode() for k, v in derived.items()},
            "source": src, "dst_sha256": res.sha256 if res is not None else None}
