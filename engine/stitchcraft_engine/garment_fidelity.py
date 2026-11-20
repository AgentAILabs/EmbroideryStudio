"""Garment-photo fidelity: how much of the thread the photo shows is covered by stitches of the EXPORTED file, and how much stitching has no thread behind it.

For each thread colour:
  recall    = share of the photo's thread pixels that lie within `tol` mm of a stitch of that colour in the decoded DST
  precision = share of stitched pixels that lie within `tol` mm of the photo's thread pixels
  missing   = connected photo regions (>= min_mm2) with < 50 % covered -> listed with position and size for user review
This compares the decoded export with the colour-separated photo (a software similarity measure, not stitch-out quality). The photo mask and the stitches are aligned
by their bounding-box centres (the digitizer centres the design the same way); the best +-3 px shift is used.
"""
from typing import Dict, List
from . import thread_separation as TS, export_pipeline as EP, photo_validation as PV


def _raster(segs, shape, s, x0, y0, np, Image, ImageDraw, width_px=2):
    im = Image.new("L", (shape[1], shape[0]), 0); d = ImageDraw.Draw(im)
    for (a, b, c, e) in segs: d.line([((a - x0) / s, (b - y0) / s), ((c - x0) / s, (e - y0) / s)], fill=255, width=width_px)
    return np.asarray(im) > 127


def measure(data: bytes, design: dict, plan_threads=None, tol_mm: float = 0.9, min_mm2: float = 6.0, width_mm: float = None, region=None) -> Dict:
    np, Image, IF = TS._np()
    from PIL import ImageDraw
    masks, (W, H) = TS.classify(data, plan_threads)
    sim = EP.decoded_simulation(design); segs = PV.segments_from_sim(sim["stitches"], sim["threads"])
    allsegs = [g for v in segs.values() for g in v]
    if not allsegs: return {"error": "no stitches"}
    xs = [q for g in allsegs for q in (g[0], g[2])]; ys = [q for g in allsegs for q in (g[1], g[3])]
    sx, sy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    emb = np.zeros((H, W), bool)
    for m in masks.values(): emb |= m
    yy, xx = np.nonzero(emb)
    if width_mm is None:
        width_mm = (max(xs) - min(xs)) * W / max(1, (xx.max() - xx.min())) if xx.max() > xx.min() else 130.0
    s = width_mm / W
    mx, my = (xx.min() + xx.max()) / 2, (yy.min() + yy.max()) / 2
    x0, y0 = sx - mx * s, sy - my * s; tol = max(1, int(round(tol_mm / s))) | 1
    # alignment: best +-8 px shift of all stitches against all photo thread (bbox centres differ a little when strays were removed)
    allst = _raster(allsegs, (H, W), s, x0, y0, np, Image, ImageDraw); nearm = TS._filt(emb, "dil", tol * 2 + 1, np, Image, IF); neara = TS._filt(allst, "dil", tol * 2 + 1, np, Image, IF)
    best, bs = -1, (0, 0)
    for dy in range(-8, 9, 2):
        for dx in range(-8, 9, 2):
            a = np.roll(np.roll(allst, dy, 0), dx, 1); b = np.roll(np.roll(neara, dy, 0), dx, 1)
            sc = float((emb & b).sum()) / max(int(emb.sum()), 1) + float((a & nearm).sum()) / max(int(a.sum()), 1)
            if sc > best: best, bs = sc, (dx, dy)
    x0 -= bs[0] * s; y0 -= bs[1] * s
    out = {}; review: List[Dict] = []
    for i, t in enumerate(plan_threads or TS.DEFAULT_THREADS):
        hexc = t["hex"] if t["hex"] in segs else (sim["threads"][i] if i < len(sim["threads"]) else t["hex"]); m = masks[t["id"]]; st = _raster(segs.get(hexc, []), (H, W), s, x0, y0, np, Image, ImageDraw)
        near_st = TS._filt(st, "dil", tol * 2 + 1, np, Image, IF); near_m = TS._filt(m, "dil", tol * 2 + 1, np, Image, IF)
        rec = float((m & near_st).sum()) / max(int(m.sum()), 1); pre = float((st & near_m).sum()) / max(int(st.sum()), 1)
        fill = TS._filt(TS._filt(st, "dil", int(round(0.8 / s)) | 1, np, Image, IF), "ero", int(round(0.4 / s)) | 1, np, Image, IF)           # stitches closed into the area they cover
        iou = float((fill & m).sum()) / max(int((fill | m).sum()), 1)
        out[t["id"]] = {"iou": round(iou, 3), "recall": round(rec, 3), "precision": round(pre, 3), "photo_px": int(m.sum()), "stitch_px": int(st.sum())}
        miss = m & ~near_st
        for ys_, xs_ in TS._comps(miss, 1, np):
            a = len(ys_) * s * s
            if a >= min_mm2: review.append({"thread": t["id"], "x_mm": round(float(xs_.mean() * s), 1), "y_mm": round(float(ys_.mean() * s), 1), "area_mm2": round(a, 1)})
    review.sort(key=lambda r: -r["area_mm2"])
    return {"per_thread": out, "missing_regions": review[:40], "missing_count": len(review), "scale_mm_per_px": round(s, 4), "tolerance_mm": tol_mm, "alignment_shift_px": bs,
            "note": "similarity of the decoded DST to the colour-separated photo; not a stitch-out result"}
