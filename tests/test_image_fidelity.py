"""Image fidelity: original preservation, benchmark thresholds (raised as the phases land)."""
import base64, hashlib, io, sys, unittest, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server")); sys.path.insert(0, str(ROOT / "tools"))
from stitchcraft_engine import fidelity
import app as server

try:
    import PIL, numpy  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False

ART = (ROOT / "tools" / "e2e_art.png").read_bytes()

class OriginalPreserved(unittest.TestCase):
    def test_source_record_has_hash_size_and_never_changes_the_bytes(self):
        before = bytes(ART); rec = fidelity.source_record(ART, 60)
        self.assertEqual(ART, before); self.assertEqual(rec["sha256"], hashlib.sha256(ART).hexdigest()); self.assertEqual(rec["bytes"], len(ART)); self.assertEqual(rec["format"], "png")
        if HAVE: self.assertEqual(rec["px"], [200, 200]); self.assertIsNotNone(rec["dpi_at_width"])
    @unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
    def test_pipeline_reports_the_source_of_the_untouched_upload_even_after_erase(self):
        r = server.api_raster({"data": base64.b64encode(ART).decode(), "width_mm": 60, "colors": 4, "erase": [[10, 10, 3]], "enhance": "always"})
        self.assertEqual(r["source"]["sha256"], hashlib.sha256(ART).hexdigest()); self.assertTrue(r["source"]["preserved"])
    def test_bundle_contains_the_original_byte_for_byte(self):
        b = fidelity.make_bundle(ART, {"preview.png": b"x"}, {"report": {"a": 1}}, "art")
        self.assertTrue(fidelity.verify_original_in_bundle(b, ART)); z = zipfile.ZipFile(io.BytesIO(b))
        self.assertIn("SOURCE.json", z.namelist()); self.assertIn("derived/preview.png", z.namelist())
        self.assertFalse(fidelity.verify_original_in_bundle(b, ART + b"\0"))

def hairline_png():
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (300, 300), "white"); d = ImageDraw.Draw(im)
    for y in range(20, 280, 20): d.line((10, y, 290, y), fill=(0, 0, 0), width=1)
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class FineDetailIsNotErased(unittest.TestCase):
    """F4 regression: 13 one-pixel black lines were silently dropped to ZERO objects by smoothing + threshold (standard and high)."""
    def test_one_pixel_lines_survive_every_quality(self):
        for q in ("standard", "high", "maximum"):                    # draft is the deliberately coarse preview mode (260 px, 6 mm2 minimum); its losses are inventoried in P4
            r = server.api_raster({"data": base64.b64encode(hairline_png()).decode(), "width_mm": 80, "colors": 6, "quality": q})
            self.assertEqual(len(r["objects"]), 13, q)
    def test_majority_filter_only_runs_on_noisy_sources(self):
        from stitchcraft_engine.raster import digitize_image
        self.assertFalse(digitize_image(hairline_png(), 80, 6, "standard")["report"]["majority_filter"])
    def test_a_genuine_thin_ink_colour_is_not_treated_as_antialiasing_fringe(self):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (300, 300), "white"); d = ImageDraw.Draw(im); d.rectangle((20, 20, 140, 280), fill=(200, 0, 0))
        for y in range(30, 280, 25): d.line((160, y, 290, y), fill=(0, 0, 160), width=1)
        b = io.BytesIO(); im.save(b, "PNG")
        r = server.api_raster({"data": base64.b64encode(b.getvalue()).decode(), "width_mm": 80, "colors": 4, "quality": "high"})
        self.assertIn("#0000a0", {o["color"] for o in r["objects"]})                   # the blue hairlines are still there

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class MicroDetailBenchmark(unittest.TestCase):
    def test_thresholds(self):
        import detail_bench as D
        got = {}
        for q in ("standard", "high", "maximum"):
            rows, r = D.run(q, 80.0, 1000); got[q] = D.summarise(rows)[1]
        self.assertGreaterEqual(got["standard"], 37); self.assertGreaterEqual(got["high"], 48); self.assertGreaterEqual(got["maximum"], 50)     # baseline / improved
    def test_a_high_resolution_source_is_not_thrown_away(self):
        import detail_bench as D
        from stitchcraft_engine.raster import digitize_image
        els = D.elements(); im = D.plate(els)
        lo = digitize_image(D.encode(im, 400), 80, 8, "high")["report"]["work_px"][0]; hi = digitize_image(D.encode(im, 1600), 80, 8, "high")["report"]["work_px"][0]
        self.assertGreater(hi, lo)                                                       # F1: working resolution follows the source up to the budget

if __name__ == "__main__": unittest.main()
