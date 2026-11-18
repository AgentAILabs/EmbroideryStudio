"""Image -> stitches quality benchmark. Artwork is drawn at 1600 px so the TRUTH is exact; test inputs are degraded copies
(antialiased downscale, JPEG, low resolution, noise, transparency). The score compares the shapes that would be stitched with the truth.
    python3 tools/image_bench.py [--quality legacy|draft|standard|high] [--width 80]
Needs Pillow + NumPy (optional dependencies). Used by tests/test_studio.py (thresholds) and for before/after evidence."""
import io, json, math, sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine.design import generate, run_checks        # noqa: E402

S = 1600                                   # truth canvas (px)
RED, BLUE, GREEN, GOLD, BLACK = (200, 16, 46), (30, 58, 138), (46, 158, 68), (212, 175, 55), (20, 20, 20)
WHITE = (255, 255, 255)


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                     # old Pillow: bitmap font only
        return ImageFont.load_default()


def _canvas():
    return Image.new("RGB", (S, S), WHITE), None


def art_logo():
    im, _ = _canvas(); d = ImageDraw.Draw(im)
    d.ellipse((150, 150, 750, 750), fill=RED)
    d.ellipse((330, 330, 570, 570), fill=WHITE)                              # hole
    d.rounded_rectangle((850, 150, 1450, 750), 90, fill=BLUE)
    d.rounded_rectangle((950, 250, 1350, 650), 60, fill=WHITE)               # hole
    d.polygon([(450, 950), (520, 1180), (760, 1180), (570, 1320), (640, 1550), (450, 1410), (260, 1550), (330, 1320), (140, 1180), (380, 1180)], fill=GREEN)
    d.polygon([(1150, 900), (1450, 1500), (850, 1500)], fill=GOLD)
    return im


def art_text():
    im, _ = _canvas(); d = ImageDraw.Draw(im)
    d.fontmode = "1"                                                         # no glyph antialiasing: the truth must be exactly flat colours
    d.text((120, 500), "BRIDE", fill=BLUE, font=_font(520))
    d.rectangle((120, 1250, 1480, 1330), fill=RED)
    return im


def art_strokes():
    im, _ = _canvas(); d = ImageDraw.Draw(im)
    for k, w_mm in enumerate((0.8, 1.5, 3.0, 6.0)):                         # at 80 mm / 1600 px = 20 px per mm
        y = 150 + k * 260; d.rectangle((150, y, 1450, y + int(w_mm * 20)), fill=RED)
    d.arc((300, 1150, 1300, 1950), 200, 340, fill=BLUE, width=50)            # curved 2.5 mm stroke
    return im


def art_touching():
    im, _ = _canvas(); d = ImageDraw.Draw(im)
    d.rectangle((150, 150, 800, 1450), fill=RED); d.rectangle((800, 150, 1450, 1450), fill=BLUE)
    d.ellipse((520, 520, 1080, 1080), fill=GOLD)
    return im


def art_ring():
    im, _ = _canvas(); d = ImageDraw.Draw(im)
    d.ellipse((200, 200, 1400, 1400), fill=BLACK); d.ellipse((500, 500, 1100, 1100), fill=WHITE); d.ellipse((720, 720, 880, 880), fill=RED)
    return im


ARTWORKS = {"logo": art_logo, "text": art_text, "strokes": art_strokes, "touching": art_touching, "ring": art_ring}


def truth_masks(im):
    """colour -> bool mask at S x S (exact colours: drawn without antialiasing)."""
    a = np.asarray(im); out = {}
    for c in {tuple(int(v) for v in px) for px in np.unique(a.reshape(-1, 3), axis=0)}:
        if c == WHITE:
            continue
        out[c] = np.all(a == np.array(c), axis=2)
    if len(out) > 8:                                                         # a truth with hundreds of colours means the drawing was antialiased
        raise AssertionError(f"ground truth has {len(out)} colours - draw without antialiasing")
    return out


def variants(im, w_px=400):
    aa = im.resize((w_px, w_px), Image.LANCZOS)
    buf = io.BytesIO(); aa.save(buf, "JPEG", quality=55); jpg = buf.getvalue()
    lo = im.resize((120, 120), Image.LANCZOS)
    rng = np.random.default_rng(5); n = np.asarray(aa).copy()
    for _ in range(160):                                                      # salt-and-pepper specks (1-2 px)
        x, y = rng.integers(0, w_px - 2, 2); n[y:y + int(rng.integers(1, 3)), x:x + int(rng.integers(1, 3))] = (0, 0, 0) if rng.random() < .5 else (255, 255, 0)
    noisy = Image.fromarray(n)
    def png(i):
        b = io.BytesIO(); i.save(b, "PNG"); return b.getvalue()
    return {"aa": png(aa), "jpeg": jpg, "lowres": png(lo), "noisy": png(noisy)}


def raster_objects(objs, width_mm, height_mm, ppm=4):
    """Rasterise the shapes that would be stitched, per colour (hex): fills (holes cut out), column bodies, running lines."""
    W, H = max(1, round(width_mm * ppm)), max(1, round(height_mm * ppm)); out = {}
    for o in objs:
        im = Image.new("L", (W, H), 0); d = ImageDraw.Draw(im)
        P = lambda pts: [(x * ppm, y * ppm) for x, y in pts]
        if o["type"] == "fill":
            for k, r in enumerate(o["rings"]):
                if len(r) >= 3: d.polygon(P(r), fill=255 if k == 0 else 0)
        elif o["type"] == "column":
            d.polygon(P(o["rail1"] + o["rail2"][::-1]), fill=255)
        elif o["type"] in ("run", "satin"):
            d.line(P(o["points"]), fill=255, width=max(1, round(0.5 * ppm)))
        a = np.asarray(im) > 0
        out[o["color"]] = out.get(o["color"], np.zeros_like(a)) | a
    return out


def _hex2rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def score(objs, truth, width_mm, height_mm, ppm=4):
    """Area-weighted IoU between the stitched shapes and the truth, plus structure counts."""
    W, H = max(1, round(width_mm * ppm)), max(1, round(height_mm * ppm))
    got = raster_objects(objs, width_mm, height_mm, ppm)
    gotrgb = {h: _hex2rgb(h) for h in got}
    tot_i = tot_u = 0.0; per = {}
    for c, m in truth.items():
        t = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).resize((W, H), Image.NEAREST)) > 0
        mine = np.zeros((H, W), bool)
        for h, rgb in gotrgb.items():
            nearest = min(truth, key=lambda tc: sum((a - b) ** 2 for a, b in zip(tc, rgb)))
            if nearest == c: mine |= got[h]
        i, u = (t & mine).sum(), (t | mine).sum()
        per[c] = i / u if u else 1.0; tot_i += i; tot_u += u
    kinds = {k: sum(1 for o in objs if o["type"] == k) for k in ("fill", "column", "run")}
    return {"iou": tot_i / tot_u if tot_u else 1.0, "per_colour": per, "objects": len(objs), **kinds}


def cusp_fraction(objs, thresh_deg=55):
    """Staircase/jaggedness: share of outline vertices (largest fill) that turn sharply. A smooth curve has few."""
    fills = [o for o in objs if o["type"] == "fill"]
    if not fills:
        return 0.0
    r = max(fills, key=lambda o: abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(o["rings"][0], o["rings"][0][1:] + o["rings"][0][:1]))))["rings"][0]
    n = len(r); sharp = 0
    for i in range(n):
        a, b, c = r[i - 1], r[i], r[(i + 1) % n]
        v1, v2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9: continue
        ang = math.degrees(math.acos(max(-1, min(1, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))))
        sharp += ang > thresh_deg
    return sharp / n


def ring_deviation(objs, cx=40.0, cy=40.0, r=30.0):
    """RMS and max radial error (mm) of the outer outline of the big circle in art_ring() against the true circle (centre 40,40, r 30 at 80 mm)."""
    fills = [o for o in objs if o["type"] == "fill"]
    if not fills:
        return None
    big = max(fills, key=lambda o: abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(o["rings"][0], o["rings"][0][1:] + o["rings"][0][:1]))))
    ring = big["rings"][0]; n = len(ring); dev = []
    for i in range(n):                                       # sample along the edges too: vertices alone hide chord error
        a, b = ring[i], ring[(i + 1) % n]
        for t in (0.0, 0.25, 0.5, 0.75):
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            dev.append(math.hypot(x - cx, y - cy) - r)
    rms = math.sqrt(sum(d * d for d in dev) / len(dev))
    return {"rms": rms, "max": max(abs(d) for d in dev), "vertices": n}


def stitch_quality(objs, width_mm, height_mm):
    for o in objs:                                          # centre like the app does on import
        pass
    d = {"name": "bench", "hoop": {"w": max(100, math.ceil(width_mm + 20)), "h": max(100, math.ceil(height_mm + 20)), "margin": 3},
         "objects": objs}
    try:
        p, notes, st = generate(d)
    except ValueError as e:
        return {"error": str(e)}
    rep = run_checks(d, p)
    return {"stitches": st["stitches"], "colours": st["color_changes"] + 1, "trims": st["trims"], "minutes": st["est_minutes"],
            "warnings": len([i for i in rep.issues if i.severity == "warning"]), "errors": len(rep.errors), "notes": len(notes)}


def run(quality="standard", width_mm=80.0, colors=8, only=None):
    from stitchcraft_engine.raster import digitize_raster
    rows = []
    for name, fn in ARTWORKS.items():
        if only and name not in only: continue
        im = fn(); truth = truth_masks(im)
        for vname, data in variants(im).items():
            objs, notes, (w, h) = digitize_raster(data, width_mm, colors, quality=quality)      # "legacy" = the original tracer, explicitly
            sc = score(objs, truth, w, h); sq = stitch_quality(objs, w, h)
            rows.append({"art": name, "input": vname, **sc, "cusp": cusp_fraction(objs), **sq})
            if name == "ring":
                dv = ring_deviation(objs); rows[-1].update({"dev_rms": dv["rms"], "dev_max": dv["max"], "verts": dv["vertices"]} if dv else {})
    return rows


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--quality", default="standard"); ap.add_argument("--width", type=float, default=80.0)
    a = ap.parse_args()
    rows = run(a.quality, a.width)
    print(f"quality={a.quality}")
    print(f"{'art':9}{'input':8}{'IoU':>6}{'objs':>5}{'fill':>5}{'col':>4}{'run':>4}{'cusp%':>6}{'stitch':>7}{'warn':>5}{'trims':>6}{'min':>6}")
    for r in rows:
        print(f"{r['art']:9}{r['input']:8}{r['iou']:6.3f}{r['objects']:5}{r['fill']:5}{r['column']:4}{r['run']:4}{r['cusp'] * 100:6.1f}{r.get('stitches', 0):7}{r.get('warnings', 0):5}{r.get('trims', 0):6}{r.get('minutes', 0):6.1f}")
    for r in rows:
        if "dev_rms" in r: print(f"  ring/{r['input']:7} outline error vs true circle: RMS {r['dev_rms']:.3f} mm  max {r['dev_max']:.3f} mm  vertices {r['verts']}")
    ok = [r["iou"] for r in rows]
    print(f"MEAN IoU {sum(ok) / len(ok):.3f}  MIN {min(ok):.3f}  total warnings {sum(r.get('warnings', 0) for r in rows)}  total trims {sum(r.get('trims', 0) for r in rows)}")
