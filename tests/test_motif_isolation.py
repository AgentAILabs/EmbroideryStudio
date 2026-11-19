"""Garment-photo motif isolation on synthetic garments with ground truth (embroidery vs folds, shadows, background)."""
import base64, io, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    HAVE = True
except ImportError:
    HAVE = False
if HAVE:
    from stitchcraft_engine import motif_isolation as MI
    import app as server


def garment(w=420, h=420, shadow=True, fold=True, embroidery=True, seed=3):
    """Maroon silk with weave noise, a soft diagonal shadow, a crease (fold) band, and two embroidered motifs. -> (png bytes, truth mask)."""
    rng = np.random.RandomState(seed)
    y, x = np.mgrid[0:h, 0:w].astype(float)
    base = np.array([110.0, 30.0, 55.0])
    img = np.ones((h, w, 3)) * base + rng.normal(0, 2.5, (h, w, 1))
    if shadow:
        sh = 1 - 0.45 * np.clip((x + y - 380) / 180.0, 0, 1)            # broad soft shadow in the lower-right
        img *= sh[..., None]
    if fold:
        f = 1 - 0.28 * np.exp(-((x - 0.55 * y - 40) / 9.0) ** 2)          # a crease: low-frequency luminance edge
        img *= f[..., None]
    truth = np.zeros((h, w), bool)
    pic = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(pic); m = Image.new("L", (w, h), 0); md = ImageDraw.Draw(m)
    if embroidery:
        for (cx, cy, r, col) in ((130, 130, 52, (214, 170, 70)), (300, 160, 40, (60, 150, 80))):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col); md.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
            for k in range(-r, r, 5):                                     # thread strands: fine dark lines
                d.line([(cx - r, cy + k), (cx + r, cy + k + 6)], fill=tuple(int(c * 0.62) for c in col), width=1)
    arr = np.asarray(pic).astype(float)
    b = io.BytesIO(); Image.fromarray(arr.astype(np.uint8)).save(b, "PNG")
    return b.getvalue(), np.asarray(m) > 0


def mask_from(res, raw, th=None):
    """Rasterise the overlay-independent bbox union? Use the module's own mask for a proper IoU."""
    im, rgb, (sw, sh) = MI._load(raw, 640)
    mask, info = MI._mask(rgb, res["threshold"], 0.03, 0.0008, np)
    return mask


@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class IsolationTest(unittest.TestCase):
    def test_finds_both_motifs_and_ignores_fabric_shadow_fold(self):
        raw, truth = garment()
        res = MI.isolate(raw)
        self.assertTrue(res["ran"]); self.assertGreaterEqual(len(res["motifs"]), 2)
        mk = mask_from(res, raw)
        t = np.asarray(Image.fromarray(truth.astype(np.uint8) * 255).resize((mk.shape[1], mk.shape[0]))) > 127
        iou = (mk & t).sum() / max(1, (mk | t).sum())
        self.assertGreater(iou, 0.55, f"IoU {iou:.2f}")
        outside = (~t); false_pos = (mk & outside).sum() / max(1, outside.sum())
        self.assertLess(false_pos, 0.05, "shadow / fold / plain fabric must not be classified as embroidery")

    def test_fabric_colour_estimated(self):
        raw, _ = garment()
        res = MI.isolate(raw); r, g, b = [int(res["fabric_hex"][i:i + 2], 16) for i in (1, 3, 5)]
        self.assertTrue(r > g and r > b and abs(r - 110) < 70, res["fabric_hex"])

    def test_shadow_and_fold_are_counted_as_suppressed(self):
        raw, _ = garment(); res = MI.isolate(raw)
        self.assertGreater(res["suppressed"]["shadow_fraction"] + res["suppressed"]["fold_fraction"], 0.01)
        raw2, _ = garment(shadow=False, fold=False); res2 = MI.isolate(raw2)
        self.assertLess(res2["suppressed"]["shadow_fraction"] + res2["suppressed"]["fold_fraction"], res["suppressed"]["shadow_fraction"] + res["suppressed"]["fold_fraction"])

    def test_plain_fabric_has_no_motifs_and_warns(self):
        raw, _ = garment(embroidery=False)
        res = MI.isolate(raw)
        self.assertEqual(res["motifs"], []); self.assertTrue(any("Almost nothing" in w for w in res["warnings"]), res["warnings"])
        with self.assertRaises(ValueError): MI.extract(raw)

    def test_threshold_moves_coverage_monotonically(self):
        raw, _ = garment(); c = MI.isolate(raw)["coverage_by_threshold"]; v = [c[k] for k in sorted(c)]
        self.assertTrue(all(a >= b for a, b in zip(v, v[1:])), c)

    def test_region_crop_restricts_analysis(self):
        raw, _ = garment(); res = MI.isolate(raw, region=[0.0, 0.0, 0.5, 0.5])
        self.assertEqual(res["source_px"], [210, 210])
        with self.assertRaises(ValueError): MI.isolate(raw, region=[0.5, 0.5, 0.4, 0.9])
        with self.assertRaises(ValueError): MI.isolate(raw, region=[0, 0, 0.01, 0.01])
        with self.assertRaises(ValueError): MI.isolate(raw, region="x")

    def test_extract_is_derived_original_untouched(self):
        raw, _ = garment(); before = bytes(raw)
        png, info = MI.extract(raw)
        self.assertEqual(raw, before); self.assertTrue(info["derived"]); self.assertIn("original photograph is unchanged", info["statement"])
        im = Image.open(io.BytesIO(png)); self.assertLess(im.width, 420 + 1); self.assertGreater(im.width, 40)
        corner = np.asarray(im.convert("RGB"))[1, 1].astype(int); fab = [int(info["fabric_hex"][i:i + 2], 16) for i in (1, 3, 5)]
        self.assertLess(np.abs(corner - np.array(fab)).max(), 40, "non-motif pixels are filled with the fabric colour")

    def test_select_subset(self):
        raw, _ = garment(); res = MI.isolate(raw); one = res["motifs"][0]["id"]
        png, info = MI.extract(raw, select=[one]); self.assertEqual(info["selected"], [one])
        with self.assertRaises(ValueError): MI.extract(raw, select=["m99"])

    def test_bad_threshold(self):
        raw, _ = garment()
        for t in (0.0, 0.99, -1):
            with self.assertRaises(ValueError): MI.isolate(raw, threshold=t)

    def test_deterministic(self):
        raw, _ = garment(); a = MI.isolate(raw); b = MI.isolate(raw); self.assertEqual(a["motifs"], b["motifs"])

    def test_limits_always_reported(self):
        raw, _ = garment(); res = MI.isolate(raw); self.assertTrue(any("Tone-on-tone" in s for s in res["limits"]))

    def test_api(self):
        raw, _ = garment(); r = server.api_image_isolate({"data": base64.b64encode(raw).decode(), "extract": True})
        self.assertTrue(r["overlay_png"] and r["motif_png"]); self.assertEqual(len(r["source_sha256"]), 64); self.assertEqual(len(r["motif"]["sha256"]), 64)
        with self.assertRaises(ValueError): server.api_image_isolate({"data": base64.b64encode(raw).decode(), "select": ["../x"]})
        with self.assertRaises(ValueError): server.api_image_isolate({"data": base64.b64encode(b"GIF89a....").decode()})

    def test_isolated_motif_feeds_photo_engine(self):
        from stitchcraft_engine import photo
        raw, _ = garment(); png, _ = MI.extract(raw)
        res = photo.photo_stitch(png, 60, mode="multicolour", colors=3)
        self.assertGreater(len(res["objects"]), 0)


if __name__ == "__main__":
    unittest.main()
