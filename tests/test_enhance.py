"""Enhancement is classical, labelled estimated, never replaces the original and never counts as recovered detail."""
import base64, hashlib, io, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server")); sys.path.insert(0, str(ROOT / "tools"))
try:
    import numpy as np
    from PIL import Image
    HAVE = True
except ImportError:
    HAVE = False
if HAVE:
    import detail_bench as D
    from stitchcraft_engine import enhance as E, source_quality as SQ
    import app as server

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Enhance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        art = Image.open(io.BytesIO(D.encode(D.plate(D.elements()), 1000))).convert("RGB")
        b = io.BytesIO(); art.resize((250, 250), Image.LANCZOS).save(b, "PNG"); cls.low = b.getvalue()        # a low-resolution source
    def test_provenance_says_estimated_and_not_recovered(self):
        png, info = E.enhance(self.low, 2.0, "sharpen"); p = info["provenance"]
        self.assertTrue(p["estimated"]); self.assertFalse(p["recovered_detail"]); self.assertIn("not be used as evidence", p["statement"]); self.assertIn("no machine-learning", p["method"])
        self.assertEqual(p["source_sha256"], hashlib.sha256(self.low).hexdigest()); self.assertEqual(p["result_sha256"], hashlib.sha256(png).hexdigest())
    def test_original_bytes_are_never_modified(self):
        before = bytes(self.low); E.enhance(self.low, 2.0, "sharpen", denoise=True, contrast=True); self.assertEqual(self.low, before)
    def test_enlargement_does_not_create_real_detail(self):
        """The measured real detail (width x effective resolution) after 3x enlargement must not exceed the source's by more than measurement slack."""
        png, info = E.enhance(self.low, 3.0, "resample"); p = info["provenance"]
        self.assertLessEqual(p["real_detail_px_after"] / 3.0, p["real_detail_px_before"] * 1.35)
        self.assertEqual(info["result_px"][0], 750)
    def test_options_are_recorded_as_steps(self):
        _, info = E.enhance(self.low, 2.0, "auto", denoise=True, contrast=True)
        self.assertTrue(any("denoise" in s for s in info["steps"])); self.assertIn("provenance", info)
    def test_api_returns_provenance_and_validation_still_uses_the_original(self):
        data = D.encode(D.plate(D.elements()), 600)
        r = server.api_enhance({"data": base64.b64encode(data).decode(), "scale": 2, "mode": "sharpen", "denoise": True})
        self.assertTrue(r["info"]["provenance"]["estimated"])
        imp = server.api_raster({"data": base64.b64encode(data).decode(), "width_mm": 80, "colors": 8, "quality": "high", "enhance": "always"})
        self.assertEqual(imp["source"]["sha256"], hashlib.sha256(data).hexdigest())         # the source record is the ORIGINAL, not the enhanced copy
        self.assertTrue(imp["report"]["enhance"]["provenance"]["estimated"])
if __name__ == "__main__": unittest.main()
