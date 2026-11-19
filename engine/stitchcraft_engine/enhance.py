"""Non-destructive source enhancement with provenance.

Enhancement is classical (Lanczos resampling, edge-preserving smoothing, contrast stretch, unsharp mask). It can make edges look cleaner and
help tracing, but it cannot recover detail that is not in the source. Therefore every result carries a `provenance` block that says so, records the
effective detail before and after (measured, see source_quality), and the fidelity validation always compares against the ORIGINAL upload.
"""
from __future__ import annotations
import hashlib
import io

from .raster import RasterUnavailable, enhance_image

STATEMENT = ("ESTIMATED: pixels added by enlargement or sharpening are interpolated, not recovered from the subject. "
             "Detail that was absent from the original is still absent; this image must not be used as evidence of source detail.")


def enhance(data: bytes, scale: float = 2.0, mode: str = "auto", denoise: bool = False, contrast: bool = False):
    """-> (png_bytes, info). `info` = enhance_image's info + `provenance`. The input bytes are never modified."""
    try:
        import numpy as np
        from PIL import Image, ImageFilter
    except ImportError as e:
        raise RasterUnavailable("the image enhancer needs the optional Pillow and NumPy packages") from e
    from . import source_quality as SQ
    png, info = enhance_image(data, scale, mode)
    steps = list(info.get("steps", []))
    if denoise or contrast:
        im = Image.open(io.BytesIO(png)).convert("RGB")
        if denoise:                                   # edge-preserving: blend a blurred copy only where the local gradient is small
            blur = im.filter(ImageFilter.GaussianBlur(1.2)); a = np.asarray(im).astype(float); b = np.asarray(blur).astype(float)
            g = np.asarray(im.convert("L")).astype(float); gx = np.abs(np.diff(g, axis=1, prepend=g[:, :1])); gy = np.abs(np.diff(g, axis=0, prepend=g[:1]))
            w = np.clip(1.0 - (gx + gy) / 24.0, 0, 1)[..., None]
            im = Image.fromarray((a * (1 - w) + b * w).astype(np.uint8)); steps.append("edge-preserving denoise")
        if contrast:
            a = np.asarray(im).astype(float); lo, hi = np.percentile(a, 1), np.percentile(a, 99)
            if hi - lo > 30:
                im = Image.fromarray((np.clip((a - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)); steps.append("contrast stretch (1st-99th percentile)")
        buf = io.BytesIO(); im.save(buf, "PNG", optimize=True); png = buf.getvalue()
    src_q = SQ.assess(data, 80.0); out_q = SQ.assess(png, 80.0 * 1.0)
    sw = info["source_px"][0]; ow = info["result_px"][0]
    real_before = src_q["metrics"]["effective_resolution"]["value"] * sw if src_q.get("ran") else None
    real_after = out_q["metrics"]["effective_resolution"]["value"] * ow if out_q.get("ran") else None
    info["steps"] = steps
    info["provenance"] = {"method": "classical (Lanczos resample + edge-preserving filters); no machine-learning model", "factor": scale, "steps": steps,
                          "estimated": True, "recovered_detail": False, "statement": STATEMENT,
                          "source_sha256": hashlib.sha256(data).hexdigest(), "result_sha256": hashlib.sha256(png).hexdigest(),
                          "real_detail_px_before": None if real_before is None else round(real_before), "real_detail_px_after": None if real_after is None else round(real_after),
                          "note": "real_detail_px = image width x effective resolution (power-spectrum measure). After enlargement it is expected to be about the same, or lower, relative to the original - never evidence of new detail."}
    return png, info
