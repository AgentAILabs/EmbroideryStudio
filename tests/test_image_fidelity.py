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
if __name__ == "__main__": unittest.main()
