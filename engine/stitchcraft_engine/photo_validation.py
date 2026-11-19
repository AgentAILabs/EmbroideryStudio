"""Photo stitch preview (thread texture simulation) and photo validation.

The preview is drawn from the stitches DECODED FROM THE EXPORTED DST (export_pipeline.decoded_simulation), not from the generator's floats: each stitch is a
0.38 mm thread line whose brightness follows its direction against a fixed light (anisotropic sheen), over the fabric colour.

Validation compares that simulated thread image with the photograph at the viewing scale (both blurred ~0.7 mm). It measures how closely the
SIMULATED THREAD IMAGE resembles the photo. It does NOT measure stitch-out quality, and it is never combined with physical validation.

Metrics (all documented in docs/testing/stitch-quality-validation.md):
  luminance_mae        mean absolute luminance difference (0..1) after blur
  luminance_corr       Pearson correlation of luminance (scale-invariant: the thread cannot be brighter than the fabric)
  structure_ssim       block-wise (8x8) SSIM-like structure similarity of luminance
  colour_de            mean CIE-Lab distance of the blurred images (meaningful for multicolour)
  histogram_distance   0.5 x L1 distance of the 32-bin luminance histograms after matching their 2nd-98th percentile range
  edge_corr            correlation of Sobel edge magnitudes
"""
from __future__ import annotations
import io
import math
from typing import Dict, List, Tuple

THREAD_MM = 0.38
THRESHOLDS = {"luminance_corr": 0.70, "structure_ssim": 0.40, "histogram_distance": 0.35, "edge_corr": 0.30, "colour_de_grayscale": 999.0, "colour_de_multicolour": 28.0}


def segments_from_sim(sim_stitches, threads_hex):
    """decoded_simulation()['stitches'] -> {hex: [(x1, y1, x2, y2)]} for stitches between consecutive stitch records of the same thread."""
    out: Dict[str, List[Tuple[float, float, float, float]]] = {}
    prev = None
    for x, y, cmd, th, _oi in sim_stitches:
        if cmd == 0:
            if prev is not None and prev[2] == th and (prev[0] != x or prev[1] != y):
                out.setdefault(threads_hex[th] if th < len(threads_hex) else "#000000", []).append((prev[0], prev[1], x, y))
            prev = (x, y, th)
        elif cmd == 1:
            prev = (x, y, th)                                   # a jump moves the needle without drawing; the next stitch starts here
        else:
            prev = None
    return out


def render_preview(segments, width_mm, height_mm, fabric="#ffffff", ppm=6.0, light_deg=35.0):
    """-> PIL RGB image. Thread texture simulation: anisotropic sheen along each stitch."""
    from PIL import Image, ImageDraw
    W, H = max(1, round(width_mm * ppm)), max(1, round(height_mm * ppm))
    fab = tuple(int(fabric[i:i + 2], 16) for i in (1, 3, 5))
    im = Image.new("RGB", (W, H), fab); d = ImageDraw.Draw(im)
    lw = max(1, round(THREAD_MM * ppm)); light = math.radians(light_deg)
    for hx, segs in segments.items():
        base = tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))
        shades = {}
        for x1, y1, x2, y2 in segs:
            a = math.atan2(y2 - y1, x2 - x1); k = round(((a - light) % math.pi) / math.pi * 24)
            if k not in shades:
                sh = 0.80 + 0.30 * math.cos(2 * (k / 24 * math.pi))
                shades[k] = tuple(max(0, min(255, round(c * sh))) for c in base)
            d.line([(x1 * ppm, y1 * ppm), (x2 * ppm, y2 * ppm)], fill=shades[k], width=lw)
    return im


def _gauss(a, sigma, np):
    r = max(1, int(3 * sigma)); x = np.arange(-r, r + 1); k = np.exp(-x * x / (2 * sigma * sigma)); k /= k.sum()
    pad = np.pad(a, ((0, 0), (r, r)), mode="edge"); t = sum(k[i] * pad[:, i:i + a.shape[1]] for i in range(2 * r + 1))
    pad = np.pad(t, ((r, r), (0, 0)), mode="edge")
    return sum(k[i] * pad[i:i + a.shape[0]] for i in range(2 * r + 1))


def compare(original: bytes, preview, width_mm: float, mode: str = "grayscale", fabric: str = "#ffffff", ppm: float = 4.0, blur_mm: float = 0.7) -> dict:
    import numpy as np
    from PIL import Image
    from .raster import _srgb_to_lab
    im = Image.open(io.BytesIO(original)); im.load()
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA"); flat = Image.new("RGBA", rgba.size, tuple(int(fabric[i:i + 2], 16) for i in (1, 3, 5)) + (255,)); flat.alpha_composite(rgba); im = flat
    im = im.convert("RGB")
    W = max(8, round(width_mm * ppm)); H = max(8, round(W * im.height / im.width))
    a = np.asarray(im.resize((W, H), Image.LANCZOS)).astype(np.float64)
    b = np.asarray(preview.resize((W, H), Image.LANCZOS)).astype(np.float64)
    sig = blur_mm * ppm
    A = np.stack([_gauss(a[..., c], sig, np) for c in range(3)], -1); B = np.stack([_gauss(b[..., c], sig, np) for c in range(3)], -1)
    w = np.array([0.299, 0.587, 0.114]); la, lb = (A @ w) / 255.0, (B @ w) / 255.0
    mae = float(np.abs(la - lb).mean())
    corr = float(np.corrcoef(la.ravel(), lb.ravel())[0, 1]) if la.std() > 1e-6 and lb.std() > 1e-6 else 0.0
    # block SSIM-like
    bs = 8; Hc, Wc = (H // bs) * bs, (W // bs) * bs
    ba = la[:Hc, :Wc].reshape(Hc // bs, bs, Wc // bs, bs).transpose(0, 2, 1, 3).reshape(-1, bs * bs); bb = lb[:Hc, :Wc].reshape(Hc // bs, bs, Wc // bs, bs).transpose(0, 2, 1, 3).reshape(-1, bs * bs)
    ma, mb = ba.mean(1), bb.mean(1); va, vb = ba.var(1), bb.var(1); cov = ((ba - ma[:, None]) * (bb - mb[:, None])).mean(1)
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    ssim = float((((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma ** 2 + mb ** 2 + c1) * (va + vb + c2))).mean())
    def hist(x):
        lo, hi = np.percentile(x, 2), np.percentile(x, 98)
        y = np.clip((x - lo) / max(hi - lo, 1e-3), 0, 1); h, _ = np.histogram(y, bins=32, range=(0, 1)); return h / max(h.sum(), 1)
    hd = float(0.5 * np.abs(hist(la) - hist(lb)).sum())
    def edge(x):
        gy, gx = np.gradient(x); return np.hypot(gx, gy)
    ea, eb = edge(la), edge(lb)
    ecorr = float(np.corrcoef(ea.ravel(), eb.ravel())[0, 1]) if ea.std() > 1e-9 and eb.std() > 1e-9 else 0.0
    labA, labB = _srgb_to_lab(A), _srgb_to_lab(B)
    de = float(np.linalg.norm(labA - labB, axis=2).mean())
    th = THRESHOLDS
    checks = {"luminance_corr": corr >= th["luminance_corr"], "structure_ssim": ssim >= th["structure_ssim"], "histogram_distance": hd <= th["histogram_distance"], "edge_corr": ecorr >= th["edge_corr"]}
    if mode == "multicolour":
        checks["colour_de"] = de <= th["colour_de_multicolour"]
    verdict = "PASSED" if all(checks.values()) else "WARNING"
    return {"mode": mode, "grid": [W, H], "blur_mm": blur_mm, "luminance_mae": round(mae, 4), "luminance_corr": round(corr, 4), "structure_ssim": round(ssim, 4), "colour_de": round(de, 2),
            "histogram_distance": round(hd, 4), "edge_corr": round(ecorr, 4), "checks": checks, "thresholds": th, "verdict": verdict,
            "meaning": "How closely the SIMULATED THREAD IMAGE resembles the photograph at viewing scale. Not a measure of stitch-out quality; physical validation is separate and pending."}


def stitch_metrics(sim_stitches, threads_hex) -> dict:
    """Properties of the exported stitch stream that decide thread-break / fabric-damage risk."""
    lens = []; cells: Dict[Tuple[int, int], int] = {}; jumps = trims = cc = 0; prev = None; n = 0; jl = 0.0
    for x, y, cmd, th, _ in sim_stitches:
        if cmd == 0:
            n += 1; cells[(int(math.floor(x)), int(math.floor(y)))] = cells.get((int(math.floor(x)), int(math.floor(y))), 0) + 1
            if prev is not None and prev[2] == "s":
                lens.append(math.hypot(x - prev[0], y - prev[1]))
            prev = (x, y, "s")
        elif cmd == 1:
            jumps += 1
            if prev is not None: jl = max(jl, math.hypot(x - prev[0], y - prev[1]))
            prev = (x, y, "j")
        elif cmd == 2: trims += 1; prev = None
        elif cmd == 3: cc += 1; prev = None
    lens.sort()
    return {"stitches": n, "jumps": jumps, "trims": trims, "colour_changes": cc, "min_stitch_mm": round(lens[0], 3) if lens else None, "max_stitch_mm": round(lens[-1], 3) if lens else None,
            "share_under_0_5mm": round(sum(1 for l in lens if l < 0.5) / max(1, len(lens)), 5), "share_over_7mm": round(sum(1 for l in lens if l > 7.0) / max(1, len(lens)), 5),
            "max_penetrations_per_mm2": max(cells.values()) if cells else 0, "longest_jump_mm": round(jl, 2)}
