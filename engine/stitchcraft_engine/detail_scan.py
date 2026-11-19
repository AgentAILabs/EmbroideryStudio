"""Independent multi-scale detail detection on the ORIGINAL image.

The digitizer (raster.py) only sees what survives palette quantisation and label cleaning. This module scans the original separately, at several scales,
so a detail the digitizer lost is still found and reported (it can never disappear silently).

Detector (documented in docs/embroidery/micro-detail-preservation.md):
  * luminance and colour-distance-from-background maps, analysed at <= 1600 px;
  * scale space: difference of Gaussians at sigma = 1, 2, 4, 8 px (feature size ~ 2.83 x sigma);
  * a detection is a local extremum of |DoG| above max(6, 0.25 x p99) with non-maximum suppression (1.5 sigma), located on the subject (colour distance from
    the background >= 25 % of the maximum) - gaps between marks are not details;
  * kind: blob (Hessian eigenvalues of similar size) or line (one dominant eigenvalue);
  * detections of the same location at several scales are merged (strongest wins).
Each detection is matched to the digitizer's detail inventory (image-mm coordinates) and receives the status of the matching item, or
`awaiting_review` when nothing matches. Faint responses are counted, not listed one by one.
"""
from __future__ import annotations
import io
import math
from typing import Dict, List, Optional

SIGMAS = (1.0, 2.0, 4.0, 8.0)
MAX_LISTED = 300
STATUS_MAP = {"digitized": "digitized", "micro_representation": "approximate", "not_stitchable": "not_stitchable", "omitted_by_user": "omitted_by_user", "needs_review": "awaiting_review"}


def _gauss(a, sigma, np):
    r = max(1, int(3 * sigma)); x = np.arange(-r, r + 1); k = np.exp(-x * x / (2 * sigma * sigma)); k /= k.sum()
    pad = np.pad(a, ((0, 0), (r, r)), mode="edge"); t = sum(k[i] * pad[:, i:i + a.shape[1]] for i in range(2 * r + 1))
    pad = np.pad(t, ((r, r), (0, 0)), mode="edge")
    return sum(k[i] * pad[i:i + a.shape[0]] for i in range(2 * r + 1))


def scan(data: bytes, width_mm: float, inventory: Optional[List[dict]] = None, max_px: int = 1600) -> dict:
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return {"ran": False, "reason": "the detail scan needs the optional Pillow and NumPy packages"}
    im = Image.open(io.BytesIO(data)); im.load()
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA"); flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255)); flat.alpha_composite(rgba); im = flat
    im = im.convert("RGB"); sw, sh = im.size
    sc = min(1.0, max_px / max(im.size))
    if sc < 1:
        im = im.resize((max(1, round(sw * sc)), max(1, round(sh * sc))), Image.LANCZOS)
    rgb = np.asarray(im).astype(np.float64); H, W = rgb.shape[:2]
    mm = width_mm / W
    bw = max(2, int(0.04 * min(H, W)))
    border = np.concatenate([rgb[:bw].reshape(-1, 3), rgb[-bw:].reshape(-1, 3), rgb[:, :bw].reshape(-1, 3), rgb[:, -bw:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    f = np.linalg.norm(rgb - bg, axis=2)                               # distance from the background colour (0..441)
    g = rgb @ np.array([0.299, 0.587, 0.114])
    dets: List[dict] = []; faint = 0
    for sigma in SIGMAS:
        if sigma * 6 > min(H, W) / 2:
            continue
        for chan_name, ch in (("colour", f), ("luminance", g)):
            a, b = _gauss(ch, sigma, np), _gauss(ch, sigma * 1.6, np)
            dog = (a - b) * (sigma ** 0.0)
            ab = np.abs(dog)
            T = max(6.0, 0.25 * float(np.percentile(ab, 99.5)))
            # Hessian of the smoothed image for blob / line discrimination
            hxx = np.gradient(np.gradient(a, axis=1), axis=1); hyy = np.gradient(np.gradient(a, axis=0), axis=0); hxy = np.gradient(np.gradient(a, axis=0), axis=1)
            r = max(1, int(round(1.5 * sigma)))
            pad = np.pad(ab, r, mode="constant"); mx = np.zeros_like(ab)
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    mx = np.maximum(mx, pad[r + dy:r + dy + H, r + dx:r + dx + W])
            peak = (ab >= mx) & (ab > T)
            ys, xs = np.nonzero(peak)
            faint += int(((ab >= mx) & (ab > T * 0.5) & (ab <= T)).sum())
            fmax = float(f.max()) or 1.0
            for y, x in zip(ys.tolist(), xs.tolist()):
                if f[max(0, y - 1):y + 2, max(0, x - 1):x + 2].max() < (0.25 if chan_name == "colour" else 0.15) * fmax:
                    continue                                      # a response on the background (the gap between two marks), not on the subject
                tr = hxx[y, x] + hyy[y, x]; det = hxx[y, x] * hyy[y, x] - hxy[y, x] ** 2
                disc = max(tr * tr / 4 - det, 0.0) ** 0.5; l1, l2 = tr / 2 + disc, tr / 2 - disc
                ratio = (min(abs(l1), abs(l2)) / max(abs(l1), abs(l2), 1e-9))
                dets.append({"x_mm": round(x * mm, 2), "y_mm": round(y * mm, 2), "sigma_px": sigma, "size_mm": round(2.83 * sigma * mm, 2), "strength": round(float(ab[y, x]), 1),
                             "polarity": "dark" if dog[y, x] < 0 else "bright", "kind": "blob" if ratio > 0.45 else "line", "channel": chan_name})
    # merge detections of the same location across scales / channels (strongest wins)
    dets.sort(key=lambda d: -d["strength"])
    kept: List[dict] = []
    grid: Dict[tuple, List[int]] = {}
    for d in dets:
        key = (int(d["x_mm"] / 2.0), int(d["y_mm"] / 2.0)); close = False
        for kx in (key[0] - 1, key[0], key[0] + 1):
            for ky in (key[1] - 1, key[1], key[1] + 1):
                for i in grid.get((kx, ky), []):
                    o = kept[i]
                    if math.hypot(o["x_mm"] - d["x_mm"], o["y_mm"] - d["y_mm"]) <= max(0.5, 0.4 * max(o["size_mm"], d["size_mm"])):
                        close = True; break
                if close: break
            if close: break
        if not close:
            grid.setdefault(key, []).append(len(kept)); kept.append(d)
    # match to the inventory
    inv = inventory or []
    counts = {"digitized": 0, "approximate": 0, "not_stitchable": 0, "omitted_by_user": 0, "awaiting_review": 0}
    for i, d in enumerate(kept):
        d["id"] = f"s{i + 1:04d}"
        hit = None
        for it in inv:
            b = it["bbox_mm"]; pad = 0.35
            if b[0] - pad <= d["x_mm"] <= b[2] + pad and b[1] - pad <= d["y_mm"] <= b[3] + pad:
                hit = it; break
        if hit:
            d["status"] = STATUS_MAP.get(hit["status"], "awaiting_review"); d["inventory"] = hit["id"]; d["object"] = hit.get("object")
        else:
            d["status"] = "awaiting_review"; d["inventory"] = None; d["object"] = None
        counts[d["status"]] += 1
    total = len(kept)
    listed = sorted(kept, key=lambda d: (d["status"] == "digitized", -d["strength"]))[:MAX_LISTED]
    matched = total - counts["awaiting_review"]
    return {"ran": True, "scales_px": list(SIGMAS), "feature_sizes_mm": [round(2.83 * s * mm, 2) for s in SIGMAS], "working_px": [W, H], "mm_per_px": round(mm, 4),
            "detections_total": total, "counts": counts, "faint_responses_not_listed": faint, "agreement": round(matched / total, 4) if total else 1.0,
            "listed": len(listed), "detections": listed,
            "rule": "a detection is a local extremum of the difference-of-Gaussians response above max(6, 25 % of the 99.5th percentile); status = status of the inventory item containing it (0.35 mm tolerance), else awaiting_review"}
