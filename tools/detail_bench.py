"""Micro-detail benchmark: a plate of many SMALL elements with exact ground truth (hairlines, dots, tiny flowers / leaves, closely spaced
curves, small border, text-like marks). Reports, per element class, how many truth elements are reproduced by the digitized objects.
    python3 tools/detail_bench.py [--quality standard|high|maximum] [--width 80] [--px 1000]
An element counts as FOUND when >= 50 % of its true area is covered by stitched shapes (fills, column bodies, running lines at 0.5 mm width).
Needs Pillow + NumPy (optional). Used by tests/test_image_fidelity.py and for before/after evidence."""
import io, json, math, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))

S = 1600                         # truth canvas px; 80 mm wide => 20 px per mm
PPM = S / 80.0
RED, BLUE, GREEN, GOLD, BLACK = (200, 16, 46), (30, 58, 138), (46, 158, 68), (212, 175, 55), (20, 20, 20)
WHITE = (255, 255, 255)


def elements():
    """-> list of dicts {cls, name, colour, mask(S x S bool), size_mm}. Every element is drawn on its own mask so the truth is exact."""
    els = []

    def add(cls, name, colour, draw, size_mm):
        m = Image.new("L", (S, S), 0); draw(ImageDraw.Draw(m), 255)
        els.append({"cls": cls, "name": name, "colour": colour, "mask": np.asarray(m) > 0, "size_mm": size_mm})
    mm = lambda v: v * PPM
    # hairlines: 0.3 / 0.5 / 0.8 / 1.2 mm wide, 20 mm long
    for k, w in enumerate((0.3, 0.5, 0.8, 1.2)):
        y = 4 + k * 3.2
        add("hairline", f"line {w} mm", RED, lambda d, f, y=y, w=w: d.rectangle((mm(6), mm(y), mm(26), mm(y + w)), fill=f), w)
    # dots 0.5 / 0.8 / 1.2 / 2.0 mm
    for k, dia in enumerate((0.5, 0.8, 1.2, 2.0)):
        cx, cy = 34 + k * 5, 6
        add("dot", f"dot {dia} mm", BLUE, lambda d, f, cx=cx, cy=cy, dia=dia: d.ellipse((mm(cx - dia / 2), mm(cy - dia / 2), mm(cx + dia / 2), mm(cy + dia / 2)), fill=f), dia)
    # tiny flowers: six petals + centre of a second colour, radius 2.0 / 3.0 / 4.0 mm
    for k, R in enumerate((2.0, 3.0, 4.0)):
        cx, cy = 10 + k * 11, 24
        for p in range(6):
            a = math.pi / 3 * p
            px, py = cx + math.cos(a) * R * 0.62, cy + math.sin(a) * R * 0.62
            add("flower_petal", f"flower R{R} petal {p + 1}", GREEN, lambda d, f, px=px, py=py, r=R * 0.36: d.ellipse((mm(px - r), mm(py - r), mm(px + r), mm(py + r)), fill=f), R * 0.72)
        add("flower_centre", f"flower R{R} centre", GOLD, lambda d, f, cx=cx, cy=cy, r=R * 0.26: d.ellipse((mm(cx - r), mm(cy - r), mm(cx + r), mm(cy + r)), fill=f), R * 0.52)
    # tiny leaves: ellipses 1.5 x 3.5 mm at an angle
    for k in range(4):
        cx, cy, a = 8 + k * 6.5, 38, math.radians(20 + k * 35)
        pts = [(cx + math.cos(t) * 1.75 * math.cos(a) - math.sin(t) * 0.75 * math.sin(a), cy + math.cos(t) * 1.75 * math.sin(a) + math.sin(t) * 0.75 * math.cos(a)) for t in np.linspace(0, 2 * math.pi, 40)]
        add("leaf", f"leaf {k + 1}", GREEN, lambda d, f, pts=pts: d.polygon([(mm(x), mm(y)) for x, y in pts], fill=f), 1.5)
    # closely spaced parallel arcs, 0.7 mm wide, 0.7 mm gap
    for k in range(4):
        r = 14 + k * 1.4
        add("curve", f"arc {k + 1}", BLACK, lambda d, f, r=r: d.arc((mm(55 - r), mm(46 - r), mm(55 + r), mm(46 + r)), 200, 340, fill=f, width=int(mm(0.7))), 0.7)
    # small border: a row of 1.4 mm squares with 1 mm gaps
    for k in range(10):
        x = 6 + k * 2.4
        add("border", f"border square {k + 1}", RED, lambda d, f, x=x: d.rectangle((mm(x), mm(54), mm(x + 1.4), mm(55.4)), fill=f), 1.4)
    # text-like marks: three 4 mm glyph-ish shapes (L, T, O)
    add("mark", "mark L", BLUE, lambda d, f: (d.rectangle((mm(40), mm(52), mm(41), mm(57)), fill=f), d.rectangle((mm(40), mm(56), mm(43.5), mm(57)), fill=f)), 1.0)
    add("mark", "mark T", BLUE, lambda d, f: (d.rectangle((mm(46), mm(52), mm(50), mm(53)), fill=f), d.rectangle((mm(47.5), mm(52), mm(48.5), mm(57)), fill=f)), 1.0)
    add("mark", "mark O", BLUE, lambda d, f: (d.ellipse((mm(53), mm(52), mm(57), mm(57)), fill=f), d.ellipse((mm(54), mm(53), mm(56), mm(56)), fill=0)), 1.0)
    # overlapping shapes: two overlapping discs of different colours
    add("overlap", "disc A", GOLD, lambda d, f: d.ellipse((mm(62), mm(30), mm(70), mm(38)), fill=f), 8.0)
    add("overlap", "disc B", RED, lambda d, f: d.ellipse((mm(66), mm(33), mm(74), mm(41)), fill=f), 8.0)
    return els


def plate(els):
    """Render the elements to one RGB image (later elements paint over earlier ones, like layers)."""
    im = np.full((S, S, 3), 255, np.uint8)
    for e in els:
        im[e["mask"]] = e["colour"]
    return Image.fromarray(im)


def encode(im, px, kind="png"):
    r = im.resize((px, px), Image.LANCZOS); b = io.BytesIO()
    r.save(b, "JPEG", quality=80) if kind == "jpeg" else r.save(b, "PNG")
    return b.getvalue()


def stitched_masks(objs, width_mm, height_mm, ppm=PPM / 2):
    """Rasterise what would be stitched (fills with holes, column bodies, runs/satin lines at 0.5 mm) per colour; all at ppm px per mm."""
    W, H = max(1, round(width_mm * ppm)), max(1, round(height_mm * ppm)); out = {}
    for o in objs:
        m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m); P = lambda pts: [(x * ppm, y * ppm) for x, y in pts]
        if o["type"] == "fill":
            for k, r in enumerate(o["rings"]):
                if len(r) >= 3: d.polygon(P(r), fill=255 if k == 0 else 0)
        elif o["type"] == "column":
            d.polygon(P(o["rail1"] + o["rail2"][::-1]), fill=255)
        elif o["type"] in ("run", "satin"):
            d.line(P(o["points"]), fill=255, width=max(1, round(0.5 * ppm)))
        elif o["type"] == "manual":
            d.line(P(o["points"]), fill=255, width=max(1, round(0.5 * ppm)))
        out[o["color"]] = out.get(o["color"], np.zeros((H, W), bool)) | (np.asarray(m) > 0)
    return out, (W, H)


def hexrgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def evaluate(objs, els, width_mm, height_mm, thresh=0.5):
    got, (W, H) = stitched_masks(objs, width_mm, height_mm)
    allmask = np.zeros((H, W), bool)
    for m in got.values(): allmask |= m
    rows = []
    for e in els:
        t = np.asarray(Image.fromarray(e["mask"].astype(np.uint8) * 255).resize((W, H), Image.BILINEAR)) > 100
        if not t.any():                      # element smaller than one evaluation pixel: judge it on the any-coverage of its centre
            ys, xs = np.nonzero(e["mask"]); cy, cx = int(ys.mean() * H / S), int(xs.mean() * W / S)
            rows.append({**{k: e[k] for k in ("cls", "name", "size_mm")}, "recall": float(allmask[min(H - 1, cy), min(W - 1, cx)]), "found": bool(allmask[min(H - 1, cy), min(W - 1, cx)])}); continue
        # colour-aware: covered by an object whose colour is nearest to the truth colour
        same = np.zeros((H, W), bool)
        for h, m in got.items():
            nearest = min(els, key=lambda x: sum((a - b) ** 2 for a, b in zip(x["colour"], hexrgb(h))))["colour"]
            if nearest == e["colour"]: same |= m
        if e["size_mm"] < 1.5:                       # thin / tiny elements: a thread line is ~0.4 mm wide, so allow 0.3 mm positional tolerance
            from PIL import ImageFilter
            k = 2 * max(1, round(0.3 * W / width_mm)) + 1
            same = np.asarray(Image.fromarray(same.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(k))) > 0
        rec = float((t & same).sum() / t.sum())
        rows.append({**{k: e[k] for k in ("cls", "name", "size_mm")}, "recall": rec, "found": rec >= thresh})
    return rows


def run(quality="standard", width_mm=80.0, px=1000, kind="png", colors=8):
    from stitchcraft_engine.raster import digitize_image
    els = elements(); im = plate(els)
    r = digitize_image(encode(im, px, kind), width_mm, colors, quality)
    rows = evaluate(r["objects"], els, r["size_mm"][0], r["size_mm"][1])
    return rows, r


def summarise(rows):
    out = {}
    for row in rows:
        c = out.setdefault(row["cls"], {"n": 0, "found": 0}); c["n"] += 1; c["found"] += row["found"]
    tot = sum(c["n"] for c in out.values()); fnd = sum(c["found"] for c in out.values())
    return out, fnd, tot


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--quality", default="standard"); ap.add_argument("--width", type=float, default=80.0); ap.add_argument("--px", type=int, default=1000)
    ap.add_argument("--kind", default="png"); a = ap.parse_args()
    rows, r = run(a.quality, a.width, a.px, a.kind)
    by, fnd, tot = summarise(rows)
    print(f"quality={a.quality} source={a.px}px {a.kind}  objects={len(r['objects'])}  report.dropped={r['report'].get('dropped_specks')}")
    for k, v in by.items(): print(f"  {k:14} {v['found']:2}/{v['n']:2} found")
    print(f"TOTAL {fnd}/{tot} elements reproduced ({100 * fnd / tot:.0f} %)")
    for row in rows:
        if not row["found"]: print(f"  LOST  {row['name']:24} size {row['size_mm']:.2f} mm  recall {row['recall']:.2f}")
