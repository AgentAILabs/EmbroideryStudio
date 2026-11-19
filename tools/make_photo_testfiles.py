#!/usr/bin/env python3
"""Generate the Photo Stitch physical-test files (testpack/photo_v1): deterministic DSTs from synthetic images (a tone ramp, a shaded sphere, a 5-colour picture).
Usage: python3 tools/make_photo_testfiles.py [outdir]   (default testpack/photo_v1). Needs Pillow + NumPy. Nothing here has been stitched: MANIFEST.json says so."""
import hashlib, io, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from stitchcraft_engine import photo, export_pipeline as EP


def png(a):
    b = io.BytesIO(); Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(b, "PNG"); return b.getvalue()


def ramp():            # 5-step tone wedge + continuous ramp: shows the tone range the thread can reach
    w, h = 400, 200; a = np.tile(np.linspace(20, 245, w)[None, :, None], (h // 2, 1, 3))
    steps = np.repeat(np.linspace(20, 245, 5), w // 5)[None, :, None] * np.ones((h // 2, 1, 3)); return png(np.vstack([a, steps]))


def sphere():
    return (ROOT / "tools" / "e2e_photo.png").read_bytes()


def colour5():
    im = Image.new("RGB", (400, 400), (255, 255, 255)); d = ImageDraw.Draw(im)
    d.ellipse([60, 60, 340, 340], fill=(200, 30, 40)); d.ellipse([120, 120, 280, 280], fill=(240, 190, 40)); d.ellipse([170, 170, 230, 230], fill=(30, 110, 200)); d.rectangle([20, 340, 380, 380], fill=(40, 140, 70))
    return png(np.asarray(im.filter(ImageFilter.GaussianBlur(2.0))))


CASES = [("P1_tone_ramp", ramp, dict(mode="grayscale", levels=6), 60), ("P2_sphere_grayscale", sphere, dict(mode="grayscale", levels=6), 60),
         ("P3_sphere_dense", sphere, dict(mode="grayscale", levels=6, density=1.6), 60), ("P4_colour5", colour5, dict(mode="multicolour", colors=5), 60)]


def build(out: Path):
    out.mkdir(parents=True, exist_ok=True); man = []
    for name, src, kw, w in CASES:
        data = src(); res = photo.photo_stitch(data, w, **kw); wmm, hmm = res["size_mm"]
        d = {"name": name, "hoop": {"w": max(100, int(wmm + 20)), "h": max(100, int(hmm + 20)), "margin": 3}, "machine": {"micro_clean": 0.4}, "objects": res["objects"]}
        ex = EP.export_dst(d); (out / f"{name}.dst").write_bytes(ex.data); (out / f"{name}.esproj").write_text(json.dumps({"app": "EmbroideryStudio", "version": 1, "doc": d}))
        man.append({"file": f"{name}.dst", "sha256": ex.sha256, "stitches": ex.report["counts"]["stitch"], "records": ex.record_count, "size_mm": [round(wmm, 1), round(hmm, 1)], "params": dict(kw, width_mm=w), "physically_validated": False})
    (out / "MANIFEST.json").write_text(json.dumps({"pack": "photo_v1", "physically_validated": False, "note": "Generated from synthetic images by tools/make_photo_testfiles.py. Never stitched. Record results with the Machine test dialog (docs/testing/physical-machine-test-plan.md).", "files": man}, indent=1))
    return man


if __name__ == "__main__":
    for m in build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "testpack" / "photo_v1"):
        print(m["file"], m["stitches"], "stitches", m["sha256"][:12])
