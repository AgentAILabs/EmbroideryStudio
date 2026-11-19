"""Source image quality assessment: what the uploaded file can and cannot support, BEFORE anything is digitized.

Pure measurement of the uploaded bytes (the image is never modified). Every metric is documented in docs/testing/image-quality-assessment.md.
Grades are good / fair / poor; recommendations are actionable. Needs Pillow + NumPy (optional): without them `assess` returns {"ran": False, ...}.

Key idea for "upscaling cannot recover detail": the radial power spectrum tells how much REAL detail an image has. An image that was enlarged
(or is simply blurry) has no energy above a cut-off frequency, so its `effective_resolution` is far below its pixel size.
"""
from __future__ import annotations
import io
import math
from typing import Dict, List

ANALYSIS_PX = 1600            # analysis is done on at most this many pixels on the long side (time bound)
MIN_FEATURE_MM = 0.75         # the smallest isolated mark that can be stitched safely (raster.SAFE_MIN_FEATURE_MM)


def _grade(v, good, fair, higher_better=True):
    if higher_better:
        return "good" if v >= good else "fair" if v >= fair else "poor"
    return "good" if v <= good else "fair" if v <= fair else "poor"


def _conv3(a, k, np):
    pad = np.pad(a, 1, mode="edge"); out = np.zeros_like(a)
    for dy in range(3):
        for dx in range(3):
            out += k[dy][dx] * pad[dy:dy + a.shape[0], dx:dx + a.shape[1]]
    return out


def _box(a, r, np):
    """Mean over a (2r+1)^2 window (integral image)."""
    pad = np.pad(a, r, mode="edge"); c = pad.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    n = 2 * r + 1; H, W = a.shape
    return (c[n:n + H, n:n + W] - c[:H, n:n + W] - c[n:n + H, :W] + c[:H, :W]) / (n * n)


def _gauss(a, sigma, np):
    r = max(1, int(3 * sigma)); x = np.arange(-r, r + 1); k = np.exp(-x * x / (2 * sigma * sigma)); k /= k.sum()
    pad = np.pad(a, ((0, 0), (r, r)), mode="edge"); t = sum(k[i] * pad[:, i:i + a.shape[1]] for i in range(2 * r + 1))
    pad = np.pad(t, ((r, r), (0, 0)), mode="edge")
    return sum(k[i] * pad[i:i + a.shape[0]] for i in range(2 * r + 1))


def assess(data: bytes, width_mm: float = 80.0) -> dict:
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return {"ran": False, "reason": "source quality assessment needs the optional Pillow and NumPy packages"}
    im0 = Image.open(io.BytesIO(data)); im0.load()
    src_w, src_h = im0.size
    is_jpeg = data[:3] == b"\xff\xd8\xff"
    im = im0.convert("RGB")
    sc = min(1.0, ANALYSIS_PX / max(im.size))
    if sc < 1:
        im = im.resize((max(1, round(im.width * sc)), max(1, round(im.height * sc))), Image.LANCZOS)
    rgb = np.asarray(im).astype(np.float64)
    g = rgb @ np.array([0.299, 0.587, 0.114]); H, W = g.shape
    mm_per_px_src = width_mm / src_w
    metrics: Dict[str, dict] = {}

    def add(key, value, unit, grade, how):
        metrics[key] = {"value": None if value is None else round(float(value), 4), "unit": unit, "grade": grade, "how": how}

    # ---- resolution
    dpi = src_w / (width_mm / 25.4)
    add("resolution_dpi", dpi, "dpi at the chosen width", _grade(dpi, 250, 120), "source width in px / (design width in inches)")
    # ---- sharpness
    lap = _conv3(g, [[0, 1, 0], [1, -4, 1], [0, 1, 0]], np)
    lapvar = float(lap.var())
    gx = _conv3(g, [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], np); gy = _conv3(g, [[-1, -2, -1], [0, 0, 0], [1, 2, 1]], np)
    mag = np.hypot(gx, gy)
    ten = float((mag ** 2).mean())
    add("sharpness_laplacian_var", lapvar, "variance", _grade(lapvar, 150, 40), "variance of the 3x3 Laplacian of the luminance (higher = sharper)")
    add("sharpness_tenengrad", ten, "mean gradient^2", _grade(ten, 3000, 600), "mean squared Sobel gradient magnitude")
    # ---- blur: edge width of strong edges
    thr = float(np.percentile(mag, 99)) * 0.5
    ys, xs = np.nonzero(mag > max(thr, 1e-6))
    if len(ys) > 50:
        sel = np.random.default_rng(1).choice(len(ys), min(4000, len(ys)), replace=False); ys, xs = ys[sel], xs[sel]
        wins = [g[max(0, y - 3):y + 4, max(0, x - 3):x + 4] for y, x in zip(ys, xs)]
        widths = [(w.max() - w.min()) / max(mag[y, x], 1e-6) * 4.0 for w, y, x in zip(wins, ys, xs)]
        blur_px = float(np.median(widths))
    else:
        blur_px = 0.0
    add("blur_edge_width_px", blur_px, "px", _grade(blur_px, 1.6, 2.8, higher_better=False), "median width of strong edges (contrast / peak gradient); a crisp edge is 1-1.5 px")
    # ---- noise
    hp = g - _box(g, 1, np)
    flat = mag < np.percentile(mag, 30)
    noise = float(np.median(np.abs(hp[flat] - np.median(hp[flat]))) * 1.4826) if flat.any() else 0.0
    add("noise_sigma", noise, "grey levels", _grade(noise, 2.0, 5.0, higher_better=False), "robust sigma (1.4826 x MAD) of the high-pass residual in the flattest 30 % of the image")
    # ---- contrast
    p5, p95 = np.percentile(g, [5, 95]); rms = float(g.std())
    add("contrast_span", p95 - p5, "grey levels (5th-95th percentile)", _grade(p95 - p5, 120, 60), "spread of luminance; low contrast makes regions hard to separate")
    add("contrast_rms", rms, "grey levels", _grade(rms, 45, 25), "standard deviation of luminance")
    # ---- JPEG blockiness
    if W >= 32 and H >= 32:
        dcol = np.abs(np.diff(g, axis=1)); b = dcol[:, 7::8][:, :-1].mean() if dcol[:, 7::8].shape[1] > 1 else 0.0; nb = np.delete(dcol, np.s_[7::8], axis=1).mean()
        block = float(b / max(nb, 1e-6))
    else:
        block = 1.0
    add("jpeg_blockiness", block, "boundary / non-boundary gradient ratio", _grade(block, 1.08, 1.25, higher_better=False), "mean gradient across 8-px block boundaries relative to elsewhere (1.0 = no blocking); only meaningful for JPEG" + ("" if is_jpeg else " (file is not a JPEG)"))
    # ---- effective resolution from the power spectrum (detects upscaled / blurry sources)
    n = min(H, W, 512); y0, x0 = (H - n) // 2, (W - n) // 2
    tile = g[y0:y0 + n, x0:x0 + n]; tile = tile - tile.mean()
    win = np.hanning(n)[:, None] * np.hanning(n)[None, :]
    P = np.abs(np.fft.fftshift(np.fft.fft2(tile * win))) ** 2
    cy = cx = n // 2; yy, xx = np.indices(P.shape); rr = np.hypot(yy - cy, xx - cx).astype(int)
    prof = np.bincount(rr.ravel(), P.ravel()) / np.maximum(np.bincount(rr.ravel()), 1); prof = prof[:n // 2]
    if len(prof) > 8 and prof[1:4].max() > 0:
        floor = float(np.median(prof[int(len(prof) * 0.85):])) + 1e-9
        above = np.nonzero(prof > floor * 20.0)[0]
        cut = (above.max() if len(above) else 1) / (n // 2)
    else:
        cut = 1.0
    eff = max(0.02, min(1.0, float(cut)))
    add("effective_resolution", eff, "fraction of the pixel grid carrying real detail", _grade(eff, 0.55, 0.3),
        "highest spatial frequency whose power is 20x above the noise floor, relative to Nyquist. Well below 1 means the image is blurry or was enlarged: it has fewer real pixels than it appears")
    real_px = src_w * eff
    # ---- small-feature visibility (scale space)
    resp = []
    for s_ in (0.8, 1.6, 3.2, 6.4):
        d = _gauss(g, s_, np) - _gauss(g, s_ * 1.6, np); resp.append(float(np.abs(d).mean()))
    mx = max(resp) or 1.0
    smallest_sigma = next((s_ for s_, r_ in zip((0.8, 1.6, 3.2, 6.4), resp) if r_ >= 0.12 * mx), 6.4)
    feat_px = 2.0 * 1.414 * smallest_sigma / sc                                  # in SOURCE pixels
    feat_mm = feat_px * mm_per_px_src * (1.0 / max(eff, 0.2) if eff < 0.6 else 1.0)
    add("smallest_feature_mm", feat_mm, "mm", _grade(feat_mm, MIN_FEATURE_MM, MIN_FEATURE_MM * 2, higher_better=False),
        f"smallest scale (difference-of-Gaussians) with real contrast energy, converted to mm at this width and enlarged by 1/effective-resolution when the image is soft; stitchable detail needs >= {MIN_FEATURE_MM:g} mm")
    # ---- subject visibility
    bw = max(2, int(0.06 * min(H, W)))
    border = np.concatenate([rgb[:bw].reshape(-1, 3), rgb[-bw:].reshape(-1, 3), rgb[:, :bw].reshape(-1, 3), rgb[:, -bw:].reshape(-1, 3)])
    bcol = np.median(border, axis=0)
    inner = rgb[int(0.1 * H):int(0.9 * H), int(0.1 * W):int(0.9 * W)]
    dist = np.linalg.norm(inner - bcol, axis=2)
    subject = float((dist > 30).mean())
    sep = float(np.percentile(dist, 90))
    add("subject_visibility", subject, "fraction of the centre that differs from the border colour", _grade(subject, 0.08, 0.02), "share of central pixels more than 30 RGB units from the border colour; ~0 = subject indistinguishable from background")
    add("subject_separation", sep, "RGB distance (90th percentile)", _grade(sep, 90, 45), "how strongly the strongest subject pixels differ from the background")
    # ---- classification: artwork vs photograph vs garment photograph
    q = (rgb // 8).astype(np.int32); keys = q[..., 0] * 1024 + q[..., 1] * 32 + q[..., 2]
    uniq, counts = np.unique(keys, return_counts=True)
    top = np.sort(counts)[::-1]; cover64 = float(top[:64].sum() / counts.sum())
    local_sd = np.sqrt(np.maximum(_box(g * g, 2, np) - _box(g, 2, np) ** 2, 0))
    flat_share = float((local_sd < 2.0).mean()); smooth_share = float(((local_sd >= 2.0) & (local_sd < 18.0)).mean())
    dom = float(top[0] / counts.sum())
    photographic = cover64 < 0.80 and smooth_share > 0.25
    dom_cluster = float((np.linalg.norm(rgb - np.median(rgb.reshape(-1, 3), axis=0), axis=2) < 40).mean())
    garment = photographic and dom_cluster >= 0.35
    cls = "garment_photo" if garment else "photo" if photographic else "artwork"
    metrics["classification"] = {"value": cls, "unit": "", "grade": "info",
                                 "how": f"flat artwork = 64 colour bins cover >= 80 % of pixels ({100 * cover64:.0f} % here) and little smooth shading ({100 * smooth_share:.0f} % here); a photo with one dominant colour cluster ({100 * dom_cluster:.0f} %) is treated as a garment photo"}
    # ---- recommendations
    rec: List[str] = []
    if dpi < 120:
        rec.append(f"Resolution is low ({dpi:.0f} dpi at {width_mm:g} mm). Use a larger source image or a smaller design width.")
    if eff < 0.45:
        rec.append(f"The image carries real detail for only ~{100 * eff:.0f} % of its pixel grid (about {real_px:.0f} px across): it is blurry or was enlarged. Enlarging it again will not add detail.")
    if blur_px > 2.8:
        rec.append("Edges are soft (blur). Re-shoot or rescan sharper; sharpening can make edges look crisper but cannot restore lost detail.")
    if noise > 5:
        rec.append("The image is noisy. Denoise (non-destructive option) or use a cleaner source; noise creates false tiny regions.")
    if is_jpeg and block > 1.25:
        rec.append("Strong JPEG compression blocks are visible. Use the original PNG / high-quality JPEG if you have it.")
    if p95 - p5 < 60:
        rec.append("Contrast is low: regions will be hard to separate. Increase contrast (non-destructive) or choose fewer colours.")
    if feat_mm > MIN_FEATURE_MM * 2:
        rec.append(f"The smallest visible detail is about {feat_mm:.2f} mm at this size: finer detail cannot be stitched. Increase the design width or accept a simpler design.")
    if subject < 0.02:
        rec.append("The subject barely differs from the background. Check the background colour or crop to the subject.")
    if cls == "photo":
        rec.append("This is a photograph. Use the Photo stitch workflow (tonal hatching); the vector workflow would reduce it to flat colour blocks.")
    if cls == "garment_photo":
        rec.append("This looks like a photograph of a garment. Use Garment photo: isolate the embroidered motif first, then digitize it as vector artwork (flat motifs) or photo stitch.")
    if cls == "artwork" and eff >= 0.45:
        rec.append("Flat artwork: the Vector artwork workflow is the right choice.")
    if not rec:
        rec.append("No problems found. The source supports detailed digitizing.")
    worst = [k for k, v in metrics.items() if v["grade"] == "poor"]
    return {"ran": True, "source": {"px": [src_w, src_h], "format": "jpeg" if is_jpeg else "png/other", "bytes": len(data), "width_mm": width_mm, "mm_per_px": round(mm_per_px_src, 4)},
            "metrics": metrics, "classification": cls, "workflow": {"artwork": "vector", "photo": "photo", "garment_photo": "garment_photo"}[cls],
            "poor_metrics": worst, "recommendations": rec,
            "effective_pixels_across": round(real_px),
            "note": "Measurements of the uploaded file only. The original is never modified. These grades describe the SOURCE; they say nothing about stitch-out quality."}
