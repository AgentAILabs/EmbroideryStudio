"""Source image quality assessment: each degradation must be detected and explained; the upload is never modified."""
import base64, hashlib, io, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server")); sys.path.insert(0, str(ROOT / "tools"))
try:
    import numpy as np
    from PIL import Image, ImageFilter
    HAVE = True
except ImportError:
    HAVE = False
if HAVE:
    import detail_bench as D
    from stitchcraft_engine import source_quality as SQ
    import app as server

def png(i):
    b = io.BytesIO(); i.save(b, "PNG"); return b.getvalue()

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Assess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.art = D.encode(D.plate(D.elements()), 1000); im = Image.open(io.BytesIO(cls.art)).convert("RGB"); cls.im = im
        rng = np.random.default_rng(0)
        cls.sharp = SQ.assess(cls.art, 80)
        cls.up = SQ.assess(png(im.resize((200, 200), Image.LANCZOS).resize((1000, 1000), Image.BICUBIC)), 80)
        cls.blur = SQ.assess(png(im.filter(ImageFilter.GaussianBlur(4))), 80)
        b = io.BytesIO(); im.save(b, "JPEG", quality=12); cls.jpg = SQ.assess(b.getvalue(), 80)
        cls.noisy = SQ.assess(png(Image.fromarray(np.clip(np.asarray(im).astype(float) + rng.normal(0, 14, (1000, 1000, 3)), 0, 255).astype(np.uint8))), 80)
        x, y = np.meshgrid(np.linspace(0, 1, 800), np.linspace(0, 1, 800))
        ph = np.stack([120 + 80 * np.sin(6 * x) * np.cos(5 * y), 90 + 70 * np.cos(4 * x + y), 60 + 90 * x * y], -1) + rng.normal(0, 3, (800, 800, 3))
        cls.photo = SQ.assess(png(Image.fromarray(np.clip(ph, 0, 255).astype(np.uint8))), 80)
    def m(self, r, k): return r["metrics"][k]["value"]
    def test_sharp_clean_artwork_is_good(self):
        r = self.sharp; self.assertTrue(r["ran"])
        for k in ("resolution_dpi", "sharpness_laplacian_var", "blur_edge_width_px", "noise_sigma"): self.assertEqual(r["metrics"][k]["grade"], "good", k)
        self.assertEqual(r["classification"], "artwork"); self.assertEqual(r["workflow"], "vector")
    def test_blur_and_upscaling_are_detected_and_explained(self):
        for r in (self.up, self.blur):
            self.assertEqual(r["metrics"]["sharpness_laplacian_var"]["grade"], "poor"); self.assertLess(self.m(r, "effective_resolution"), self.m(self.sharp, "effective_resolution"))
        self.assertLess(self.m(self.up, "effective_resolution"), 0.6)
        self.assertTrue(any("enlarged" in x or "blurry" in x for x in self.up["recommendations"]) or any("soft" in x for x in self.up["recommendations"]))
        self.assertGreater(self.m(self.blur, "smallest_feature_mm"), self.m(self.sharp, "smallest_feature_mm"))
    def test_jpeg_blocking_is_detected(self):
        self.assertGreater(self.m(self.jpg, "jpeg_blockiness"), 1.25); self.assertEqual(self.jpg["metrics"]["jpeg_blockiness"]["grade"], "poor"); self.assertTrue(any("JPEG" in x for x in self.jpg["recommendations"]))
        self.assertLess(self.m(self.sharp, "jpeg_blockiness"), 1.1)
    def test_noise_is_measured(self):
        self.assertGreater(self.m(self.noisy, "noise_sigma"), 3.5); self.assertLess(self.m(self.sharp, "noise_sigma"), 1.0)
    def test_low_resolution_is_reported_in_dpi(self):
        r = SQ.assess(self.art, 400); self.assertLess(self.m(r, "resolution_dpi"), 80); self.assertEqual(r["metrics"]["resolution_dpi"]["grade"], "poor"); self.assertTrue(any("Resolution is low" in x for x in r["recommendations"]))
    def test_photo_is_recognised_and_routed_to_the_photo_workflow(self):
        self.assertEqual(self.photo["classification"], "photo"); self.assertEqual(self.photo["workflow"], "photo"); self.assertTrue(any("Photo stitch" in x for x in self.photo["recommendations"]))
    def test_low_contrast_and_invisible_subject(self):
        flat = Image.new("RGB", (400, 400), (128, 128, 128)); d = Image.new("RGB", (100, 100), (134, 128, 128)); flat.paste(d, (150, 150))
        r = SQ.assess(png(flat), 80); self.assertEqual(r["metrics"]["contrast_span"]["grade"], "poor"); self.assertEqual(r["metrics"]["subject_visibility"]["grade"], "poor")
    def test_every_metric_documents_its_calculation(self):
        for k, v in self.sharp["metrics"].items(): self.assertTrue(v["how"], k)
    def test_the_upload_is_not_modified_and_the_report_says_so(self):
        before = bytes(self.art); SQ.assess(self.art, 80); self.assertEqual(self.art, before); self.assertIn("never modified", self.sharp["note"])
    def test_without_pillow_numpy_it_reports_instead_of_failing(self):
        import builtins
        real = builtins.__import__
        def fake(name, *a, **k):
            if name in ("numpy", "PIL"): raise ImportError(name)
            return real(name, *a, **k)
        builtins.__import__ = fake
        try: r = SQ.assess(self.art, 80)
        finally: builtins.__import__ = real
        self.assertFalse(r["ran"]); self.assertIn("Pillow", r["reason"])

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Api(unittest.TestCase):
    def test_endpoint_returns_metrics_and_hash_and_rejects_bad_input(self):
        data = D.encode(D.plate(D.elements()), 600)
        r = server.api_image_quality({"data": base64.b64encode(data).decode(), "width_mm": 80})
        self.assertEqual(r["source_sha256"], hashlib.sha256(data).hexdigest()); self.assertIn("recommendations", r)
        for bad in ({"data": base64.b64encode(b"nope").decode(), "width_mm": 80}, {"data": base64.b64encode(data).decode(), "width_mm": 0}, {"data": 5}):
            with self.assertRaises(ValueError): server.api_image_quality(bad)
        with self.assertRaises(ValueError): server.api_image_quality({"data": base64.b64encode(data[:200]).decode(), "width_mm": 80})
if __name__ == "__main__": unittest.main()
