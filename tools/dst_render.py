#!/usr/bin/env python3
"""Render a DST to PNG with Pillow (thread-coloured stitches, jumps dashed red) - for inspection / before-after sheets.
Usage: dst_render.py in.dst out.png [px_per_mm] [x0 y0 x1 y1 crop in mm]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from stitchcraft_engine.dst import read_dst
from PIL import Image, ImageDraw
PAL = ["#b3122b", "#1d6b3a", "#1f3fa8", "#c98a00", "#5a2a8a", "#00808a", "#222222", "#d0488a"]

def render(data, scale=6.0, crop=None, bg="#f7f4ee"):
    f = read_dst(data); pos = [(0, 0)] + f.positions
    xs = [p[0] / 10 for p in pos]; ys = [-p[1] / 10 for p in pos]
    x0, y0, x1, y1 = crop or (min(xs) - 2, min(ys) - 2, max(xs) + 2, max(ys) + 2)
    W, H = int((x1 - x0) * scale) + 1, int((y1 - y0) * scale) + 1
    im = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(im); ci = 0
    for i, (dx, dy, c) in enumerate(f.records):
        a = ((xs[i] - x0) * scale, (ys[i] - y0) * scale); b = ((xs[i + 1] - x0) * scale, (ys[i + 1] - y0) * scale)
        if c == "stitch": d.line([a, b], fill=PAL[ci % len(PAL)], width=max(1, int(scale * 0.22)))
        elif c == "jump" and (dx or dy): d.line([a, b], fill="#ff9aa8", width=1)
        elif c == "color_change": ci += 1
    return im

if __name__ == "__main__":
    a = sys.argv
    crop = tuple(map(float, a[4:8])) if len(a) >= 8 else None
    render(Path(a[1]).read_bytes(), float(a[3]) if len(a) > 3 else 6.0, crop).save(a[2])
