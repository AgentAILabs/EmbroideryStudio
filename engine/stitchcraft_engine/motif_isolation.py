"""Garment-photo motif isolation (semi-automatic, heuristic, honest about its limits).

A photograph of a finished garment contains the embroidery AND fabric, folds, shadows, skin, background. This module estimates where the embroidery is so
that only that part is passed on to the vector or photo workflow. It does not "know" what embroidery is; it scores each pixel with three cues:

  colour      distance of the pixel's Lab ab-chroma from the fabric chroma (the fabric colour = the dominant colour cluster of the picture)
  detail      local high-pass luminance energy relative to the fabric weave (thread has fine, high-contrast texture; plain fabric does not)
  coherence   structure-tensor coherence of that detail (thread sheen runs in oriented strands)

  probability = clip(0.65 colour + 0.45 detail + 0.10 coherence x detail)

Suppression (documented in docs/embroidery/photo-digitizing-engine.md):
  shadow  the pixel has the fabric's chroma, is darker than the smoothed illumination of the fabric around it, and has no fine texture -> probability x 0.15
  fold    same chroma, no fine texture, but a strong LOW-frequency luminance gradient (a crease edge)                                     -> probability x 0.15
The mask = probability >= threshold (user adjustable), smoothed, small specks removed; nearby parts are grouped into motifs (connected components of the
dilated mask) which the user can switch on/off. Output: a mask overlay, the motif list, and a DERIVED cropped image (original untouched, non-motif pixels filled
with the fabric colour).

Known limits (reported with every result): tone-on-tone embroidery (thread colour = fabric colour, little texture) is missed; deep shadows over bright coloured
thread can be kept or dropped; a garment whose colour changes (print, ombre) confuses the fabric-colour estimate; a strongly textured fabric (brocade) is
read as embroidery. Always inspect the overlay.
"""
from __future__ import annotations
import io
import math
from typing import Dict, List, Optional, Tuple

MAX_MOTIFS = 40


def _lazy():
    import numpy as np
    from PIL import Image
    return np, Image


def crop_region(data: bytes, region) -> bytes:
    """Optional user crop (fractions x0,y0,x1,y1 of the picture) applied before analysis: the semi-automatic answer to a busy background. -> PNG bytes."""
    if region is None:
        return data
    np, Image = _lazy()
    if not (isinstance(region, (list, tuple)) and len(region) == 4 and all(isinstance(v, (int, float)) for v in region)):
        raise ValueError("region must be four numbers [x0, y0, x1, y1] (fractions of the picture)")
    x0, y0, x1, y1 = [float(v) for v in region]
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1) or (x1 - x0) < 0.05 or (y1 - y0) < 0.05:
        raise ValueError("region must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1 and be at least 5 % wide and high")
    im = Image.open(io.BytesIO(data)); im.load(); im = im.convert("RGB"); w, h = im.size
    buf = io.BytesIO(); im.crop((int(x0 * w), int(y0 * h), max(int(x1 * w), int(x0 * w) + 8), max(int(y1 * h), int(y0 * h) + 8))).save(buf, "PNG")
    return buf.getvalue()


def _gauss(a, sigma, np):
    """Gaussian blur; large sigmas are computed on a block-averaged copy (speed)."""
    if sigma > 8:
        f = max(2, int(sigma // 5)); H, W = a.shape
        Hc, Wc = (H // f) * f, (W // f) * f
        small = a[:Hc, :Wc].reshape(Hc // f, f, Wc // f, f).mean(axis=(1, 3))
        b = _gauss(small, sigma / f, np)
        up = np.repeat(np.repeat(b, f, axis=0), f, axis=1)
        return np.pad(up, ((0, H - Hc), (0, W - Wc)), mode="edge")
    r = max(1, int(3 * sigma)); x = np.arange(-r, r + 1); k = np.exp(-x * x / (2 * sigma * sigma)); k /= k.sum()
    pad = np.pad(a, ((0, 0), (r, r)), mode="edge"); t = sum(k[i] * pad[:, i:i + a.shape[1]] for i in range(2 * r + 1))
    pad = np.pad(t, ((r, r), (0, 0)), mode="edge")
    return sum(k[i] * pad[i:i + a.shape[0]] for i in range(2 * r + 1))


def _load(data: bytes, max_px: int):
    np, Image = _lazy()
    im = Image.open(io.BytesIO(data)); im.load()
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA"); flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255)); flat.alpha_composite(rgba); im = flat
    im = im.convert("RGB"); sw, sh = im.size
    sc = min(1.0, max_px / max(im.size))
    small = im.resize((max(8, round(sw * sc)), max(8, round(sh * sc))), Image.LANCZOS) if sc < 1 else im
    return im, np.asarray(small).astype(np.float64), (sw, sh)


def _fabric(lab, np):
    """Dominant colour cluster (coarse Lab bins, central 90 %) -> mean Lab of its pixels."""
    H, W = lab.shape[:2]; my, mx = int(H * 0.05), int(W * 0.05)
    c = lab[my:H - my, mx:W - mx].reshape(-1, 3)
    key = (np.floor(c[:, 0] / 10).astype(int) * 10000 + np.floor((c[:, 1] + 128) / 8).astype(int) * 100 + np.floor((c[:, 2] + 128) / 8).astype(int))
    vals, counts = np.unique(key, return_counts=True)
    top = vals[np.argmax(counts)]
    return c[key == top].mean(axis=0), float(counts.max() / len(key))


def probability_map(rgb, np):
    """-> dict(prob, colour, detail, coherence, shadow, fold, fabric_lab, ...) at the working resolution."""
    from .raster import _srgb_to_lab
    H, W = rgb.shape[:2]; m = min(H, W)
    lab = _srgb_to_lab(rgb); L = lab[..., 0]
    fab, fab_share = _fabric(lab, np)
    dC = np.hypot(lab[..., 1] - fab[1], lab[..., 2] - fab[2])
    col = 1 - np.exp(-(dC / 14.0) ** 2)
    s1 = max(1.2, 0.012 * m)
    hp = L - _gauss(L, s1, np)
    en = _gauss(np.abs(hp), s1, np)
    base = max(float(np.median(en)), 0.4)
    det = np.clip((en / base - 1.6) / 3.0, 0, 1)
    gy, gx = np.gradient(_gauss(L, 1.0, np))
    jxx, jyy, jxy = _gauss(gx * gx, s1 * 1.5, np), _gauss(gy * gy, s1 * 1.5, np), _gauss(gx * gy, s1 * 1.5, np)
    coh = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2) / (jxx + jyy + 1e-6)
    prob = np.clip(0.65 * col + 0.45 * det + 0.10 * coh * det, 0, 1)
    # illumination of the fabric-like pixels (normalised convolution), then shadow / fold tests
    w = (col < 0.3).astype(np.float64); s2 = max(6.0, 0.08 * m)
    den = _gauss(w, s2, np); num = _gauss(L * w, s2, np)
    Lbg = np.where(den > 0.05, num / np.maximum(den, 1e-3), _gauss(L, s2, np))
    sameChroma = dC < 7.0; flat = en < 1.8 * base
    shadow = sameChroma & flat & (L < Lbg - 4.0)
    glow = _gauss(L, max(3.0, 0.03 * m), np); gy2, gx2 = np.gradient(glow); low_grad = np.hypot(gx2, gy2)
    fold = sameChroma & flat & ~shadow & (low_grad > 0.35)
    prob = np.where(shadow | fold, prob * 0.15, prob)
    return {"prob": prob, "colour": col, "detail": det, "coherence": coh, "shadow": shadow, "fold": fold, "fabric_lab": fab, "fabric_share": fab_share, "s1": s1}


def _label(mask, np):
    """4-connected component labelling by union-find on a (small) boolean grid -> int labels (0 = background), count."""
    H, W = mask.shape; lab = np.zeros((H, W), dtype=np.int32); parent = [0]
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    nxt = 1; m = mask.tolist()
    rows = [[0] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            if not m[y][x]: continue
            up = rows[y - 1][x] if y else 0; lf = rows[y][x - 1] if x else 0
            if up and lf:
                a, b = find(up), find(lf)
                if a != b: parent[max(a, b)] = min(a, b)
                rows[y][x] = min(a, b)
            elif up or lf:
                rows[y][x] = up or lf
            else:
                parent.append(nxt); rows[y][x] = nxt; nxt += 1
    roots = {}
    arr = np.array(rows, dtype=np.int32)
    out = np.zeros_like(arr)
    for v in np.unique(arr):
        if v == 0: continue
        out[arr == v] = roots.setdefault(find(int(v)), len(roots) + 1)
    return out, len(roots)


def isolate(data: bytes, threshold: float = 0.65, group_mm_frac: float = 0.03, min_area_frac: float = 0.0008, max_px: int = 640, region=None) -> dict:
    """Locate probable embroidery in a garment photo. Returns motifs, suppression counts, warnings; the mask is rebuilt by `mask_for` from the same parameters."""
    try:
        np, _ = _lazy()
    except ImportError:
        return {"ran": False, "reason": "motif isolation needs the optional Pillow and NumPy packages"}
    if not 0.05 <= threshold <= 0.95:
        raise ValueError("threshold must be between 0.05 and 0.95")
    data = crop_region(data, region)
    im, rgb, (sw, sh) = _load(data, max_px)
    mask, info = _mask(rgb, threshold, group_mm_frac, min_area_frac, np)
    sm = _gauss(info["prob"], 1.2, np); cov_sweep = {f"{t:.2f}": round(float((sm >= t).mean()), 4) for t in (0.4, 0.5, 0.6, 0.7, 0.8)}
    H, W = mask.shape
    motifs = []
    for k in range(1, info["n"] + 1):
        ys, xs = np.nonzero(info["groups"] == k)
        if len(ys) == 0: continue
        sel = info["mask_raw"][info["groups"] == k]
        motifs.append({"id": f"m{k}", "group": k, "bbox_frac": [round(float(xs.min()) / W, 4), round(float(ys.min()) / H, 4), round(float(xs.max() + 1) / W, 4), round(float(ys.max() + 1) / H, 4)],
                       "bbox_px": [int(xs.min() * sw / W), int(ys.min() * sh / H), int((xs.max() + 1) * sw / W), int((ys.max() + 1) * sh / H)],
                       "embroidery_area_frac": round(float(sel.sum()) / (H * W), 4), "mean_probability": round(float(info["prob"][info["mask_raw"] & (info["groups"] == k)].mean()) if sel.any() else 0.0, 3)})
    motifs.sort(key=lambda m: -m["embroidery_area_frac"])
    motifs = motifs[:MAX_MOTIFS]
    for i, m in enumerate(motifs): m["id"] = f"m{i + 1}"; m["confidence"] = "high" if m["mean_probability"] >= 0.7 else "medium" if m["mean_probability"] >= 0.55 else "low"
    cover = float(info["mask_raw"].mean()); sh_frac = float(info["shadow"].mean()); fo_frac = float(info["fold"].mean())
    warn = []
    if cover > 0.6: warn.append("More than 60 % of the picture was classified as embroidery: the fabric colour was probably estimated wrongly (printed / multi-coloured fabric or a close-up). Check the overlay and raise the threshold.")
    if cover < 0.003: warn.append("Almost nothing was classified as embroidery: tone-on-tone thread cannot be separated from the fabric by colour. Lower the threshold or crop manually.")
    if sh_frac > 0.25: warn.append("A large part of the picture looks like shadow; bright thread inside deep shadow may have been lost.")
    if info["fabric_share"] < 0.2: warn.append("No dominant fabric colour was found (largest colour cluster under 20 % of the picture): the garment may be multi-coloured or the background busy.")
    fab = info["fabric_lab"]
    return {"ran": True, "threshold": round(threshold, 3), "coverage_by_threshold": cov_sweep, "working_px": [W, H], "source_px": [sw, sh], "fabric_hex": _lab_hex(fab, np), "fabric_share": round(info["fabric_share"], 3), "motifs": motifs,
            "embroidery_fraction": round(cover, 4), "suppressed": {"shadow_fraction": round(sh_frac, 4), "fold_fraction": round(fo_frac, 4)}, "warnings": warn,
            "region": region, "limits": ["Heuristic: colour distance from the dominant fabric colour + fine-texture energy + thread-sheen coherence; shadows and folds are suppressed by rule.",
                       "Tone-on-tone embroidery, deep shadows over bright thread, printed fabric and strongly textured weaves can fail - always inspect the overlay.",
                       "The original photograph is never modified; the cropped motif image is a derived copy."]}


def _mask(rgb, threshold, group_frac, min_area_frac, np):
    pm = probability_map(rgb, np); H, W = pm["prob"].shape
    sm = _gauss(pm["prob"], max(1.0, pm["s1"] * 0.8), np)
    raw = sm >= threshold
    # drop specks (area < min_area_frac of the picture) on a coarse grid; group nearby parts by dilation
    step = max(1, int(round(max(H, W) / 200))); h2, w2 = H // step, W // step
    coarse = raw[:h2 * step, :w2 * step].reshape(h2, step, w2, step).mean(axis=(1, 3)) >= 0.3
    r = max(1, int(round(group_frac * max(h2, w2))))
    dil = coarse.copy()
    for _ in range(r):
        p = np.pad(dil, 1); dil = p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
    lab, n = _label(dil, np)
    groups = np.zeros((H, W), dtype=np.int32); keep = 0; remap = {}
    areas = {k: int(((lab == k) & coarse).sum()) for k in range(1, n + 1)}
    for k in sorted(areas, key=lambda z: -areas[z]):
        if areas[k] * step * step / (H * W) < min_area_frac or keep >= MAX_MOTIFS: continue
        keep += 1; remap[k] = keep
    big = np.zeros((H, W), dtype=np.int32)
    for k, v in remap.items():
        m = np.repeat(np.repeat(lab == k, step, axis=0), step, axis=1)
        big[:m.shape[0], :m.shape[1]][m] = v
    groups = big
    mask_raw = raw & (groups > 0)
    return mask_raw, {"n": keep, "groups": groups, "mask_raw": mask_raw, "prob": pm["prob"], "shadow": pm["shadow"], "fold": pm["fold"], "fabric_lab": pm["fabric_lab"], "fabric_share": pm["fabric_share"]}


def _lab_hex(lab, np):
    L, a, b = [float(v) for v in lab]
    fy = (L + 16) / 116; fx = fy + a / 500; fz = fy - b / 200
    def inv(t): return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787
    X, Y, Z = inv(fx) * 0.95047, inv(fy), inv(fz) * 1.08883
    r = 3.2406 * X - 1.5372 * Y - 0.4986 * Z; g = -0.9689 * X + 1.8758 * Y + 0.0415 * Z; bl = 0.0557 * X - 0.2040 * Y + 1.0570 * Z
    def gm(c): c = max(0.0, min(1.0, c)); return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return "#%02x%02x%02x" % tuple(round(255 * gm(c)) for c in (r, g, bl))


def overlay(data: bytes, threshold: float = 0.65, select: Optional[List[str]] = None, max_px: int = 640, region=None) -> bytes:
    """PNG: the photograph with everything that is NOT selected embroidery dimmed, selected motifs outlined and numbered (for the review dialog)."""
    np, Image = _lazy()
    from PIL import ImageDraw
    data = crop_region(data, region)
    im, rgb, (sw, sh) = _load(data, max_px)
    res = isolate(data, threshold, max_px=max_px); threshold = res["threshold"]
    mask, info = _mask(rgb, threshold, 0.03, 0.0008, np)
    H, W = mask.shape
    chosen = {m["id"] for m in res["motifs"]} if select is None else set(select)
    ids = {m["id"]: i + 1 for i, m in enumerate(res["motifs"])}
    keepm = np.zeros((H, W), dtype=bool)
    for mid in chosen:
        if mid in ids: keepm |= mask & (info["groups"] == next(z for z in res["motifs"] if z["id"] == mid)["group"])
    out = rgb.copy(); out[~keepm] = out[~keepm] * 0.35 + np.array([40, 40, 60]) * 0.65
    pic = Image.fromarray(out.astype(np.uint8)); d = ImageDraw.Draw(pic)
    for m in res["motifs"]:
        x0, y0, x1, y1 = [m["bbox_frac"][0] * W, m["bbox_frac"][1] * H, m["bbox_frac"][2] * W, m["bbox_frac"][3] * H]
        on = m["id"] in chosen; col = (255, 210, 0) if on else (150, 150, 150)
        d.rectangle([x0, y0, x1, y1], outline=col, width=2); d.text((x0 + 3, y0 + 2), m["id"], fill=col)
    buf = io.BytesIO(); pic.save(buf, "PNG"); return buf.getvalue()


def extract(data: bytes, threshold: float = 0.65, select: Optional[List[str]] = None, pad_frac: float = 0.03, max_px: int = 640, region=None) -> Tuple[bytes, dict]:
    """Derived motif image: crop to the selected motifs (default all), pixels outside the embroidery mask replaced by the fabric colour. -> (png, info)."""
    np, Image = _lazy()
    data = crop_region(data, region)
    res = isolate(data, threshold, max_px=max_px)
    if not res.get("ran") or not res["motifs"]:
        raise ValueError("no embroidery motif was found at this threshold - lower the threshold or crop the photograph manually")
    threshold = res["threshold"]
    im, rgb, (sw, sh) = _load(data, max_px)
    mask, info = _mask(rgb, threshold, 0.03, 0.0008, np)
    H, W = mask.shape
    chosen = [m for m in res["motifs"] if select is None or m["id"] in select]
    if not chosen:
        raise ValueError("no motif selected")
    keepm = np.zeros((H, W), dtype=bool)
    for m in chosen: keepm |= mask & (info["groups"] == m["group"])
    x0 = min(m["bbox_frac"][0] for m in chosen); y0 = min(m["bbox_frac"][1] for m in chosen); x1 = max(m["bbox_frac"][2] for m in chosen); y1 = max(m["bbox_frac"][3] for m in chosen)
    x0, y0, x1, y1 = max(0.0, x0 - pad_frac), max(0.0, y0 - pad_frac), min(1.0, x1 + pad_frac), min(1.0, y1 + pad_frac)
    # soft mask at source resolution
    fm = Image.fromarray((_gauss(keepm.astype(np.float64), 1.5, np) * 255).clip(0, 255).astype(np.uint8)).resize((sw, sh), Image.BILINEAR)
    src = np.asarray(im).astype(np.float64); a = (np.asarray(fm).astype(np.float64) / 255.0)[..., None]
    fabric = np.array([int(res["fabric_hex"][i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64)
    outp = src * a + fabric * (1 - a)
    box = (int(x0 * sw), int(y0 * sh), max(int(x1 * sw), int(x0 * sw) + 8), max(int(y1 * sh), int(y0 * sh) + 8))
    pic = Image.fromarray(outp.clip(0, 255).astype(np.uint8)).crop(box)
    buf = io.BytesIO(); pic.save(buf, "PNG")
    return buf.getvalue(), {"derived": True, "selected": [m["id"] for m in chosen], "crop_px": list(box), "size_px": list(pic.size), "fabric_hex": res["fabric_hex"], "threshold": threshold,
                            "statement": "Derived crop of the selected motifs; everything outside the embroidery mask is filled with the estimated fabric colour. The original photograph is unchanged."}
