"""Image fidelity: original preservation, benchmark thresholds (raised as the phases land)."""
import base64, hashlib, io, math, sys, unittest, zipfile
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


@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class DetailInventory(unittest.TestCase):
    """F2/F3/F5: nothing is dropped without a record, a reason and a status."""
    def run_bench(self, q="high", px=1000):
        import detail_bench as D
        els = D.elements(); return D.digitize_image(D.encode(D.plate(els), px), 80, 8, q) if hasattr(D, "digitize_image") else __import__("stitchcraft_engine.raster", fromlist=["digitize_image"]).digitize_image(D.encode(D.plate(els), px), 80, 8, q)
    def test_every_inventory_item_has_a_status_reason_and_stitchability(self):
        r = self.run_bench()
        self.assertTrue(r["inventory"]);
        for it in r["inventory"]:
            self.assertIn(it["status"], ("digitized", "micro_representation", "not_stitchable", "needs_review")); self.assertTrue(it["reason"]); self.assertGreaterEqual(it["stitchability"], 0); self.assertLessEqual(it["stitchability"], 1)
            if it["status"] == "not_stitchable": self.assertIsNone(it["object"])
            else: self.assertTrue(it["object"], it)
    def test_inventory_objects_exist_and_are_unique(self):
        r = self.run_bench(); ids = {o["id"] for o in r["objects"]}; linked = [it["object"] for it in r["inventory"] if it["object"]]
        self.assertEqual(len(linked), len(set(linked))); self.assertTrue(set(linked) <= ids); self.assertEqual(set(linked), ids)          # every object traces to a source region and vice versa
    def test_smallest_dot_is_listed_as_not_stitchable_with_a_reason_never_silently_lost(self):
        r = self.run_bench("high"); bad = [it for it in r["inventory"] if it["status"] == "not_stitchable"]
        self.assertEqual(len(bad), 1); self.assertIn("safe minimum", bad[0]["reason"]); self.assertLess(max(bad[0]["size_mm"]), 0.75)
        self.assertIn("review", " ".join(r["notes"]).lower()); self.assertEqual(r["report"]["unresolved"], [bad[0]["id"]])
    def test_small_blobs_get_a_tack_dot_and_narrow_marks_a_running_line(self):
        r = self.run_bench("high"); strat = {it["strategy"] for it in r["inventory"] if it["status"] == "micro_representation"}
        self.assertTrue(strat & {"tack", "run"}); tacks = [o for o in r["objects"] if o["type"] == "manual"]; self.assertTrue(tacks)
        for o in tacks:
            pts = o["points"]; self.assertEqual(len(pts), 6)
            self.assertGreaterEqual(min(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])), 0.8)       # no micro-stitches inside the tack
    def test_coverage_accounts_for_the_ink(self):
        r = self.run_bench("high"); c = r["report"]["coverage"]
        self.assertGreater(c["stitched_fraction"], 0.99); self.assertIn("rule", c["noise_specks"]); self.assertIn("rule", c["antialiasing_fringe"])
    def test_api_returns_the_inventory_and_dropped_count_matches(self):
        import detail_bench as D
        els = D.elements(); data = D.encode(D.plate(els), 1000)
        r = server.api_raster({"data": base64.b64encode(data).decode(), "width_mm": 80, "colors": 8, "quality": "standard"})
        self.assertTrue(r["inventory"]); self.assertEqual(r["report"]["dropped_specks"], r["report"]["coverage"]["noise_specks"]["count"] + r["report"]["inventory_status"].get("not_stitchable", 0))
    def test_designs_from_the_inventory_still_generate_and_export(self):
        from stitchcraft_engine import export_pipeline as EP
        r = self.run_bench("high"); d = {"name": "inv", "hoop": {"w": 120, "h": 120, "margin": 3}, "objects": [dict(o) for o in r["objects"]]}
        EP.export_dst(d)

if __name__ == "__main__": unittest.main()
