"""Nine-pass image-to-DST validation: passes on a faithful design, FAILS when the design or DST is damaged (mutation tests)."""
import base64, copy, io, json, sys, unittest, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server")); sys.path.insert(0, str(ROOT / "tools"))
try:
    import PIL, numpy  # noqa: F401
    HAVE = True
except ImportError:
    HAVE = False
if HAVE:
    import detail_bench as D
    from stitchcraft_engine.raster import digitize_image
    from stitchcraft_engine import image_validation as V, dst, export_pipeline as EP
    import app as server

def results(rep): return {p["pass"]: p["result"] for p in rep["passes"]}

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Validation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = D.encode(D.plate(D.elements()), 1000)
        cls.imp = digitize_image(cls.data, 80, 8, "high")
        h = 120
        cls.design = {"name": "plate", "hoop": {"w": h, "h": h, "margin": 3}, "thread": "40wt", "objects": [dict(o) for o in cls.imp["objects"]]}
        cls.rep = V.validate(cls.data, 80, cls.imp, cls.design)
    def test_faithful_design_passes_every_mandatory_pass_and_physical_is_pending(self):
        r = results(self.rep)
        for n in (1, 3, 4, 5, 6, 7, 8): self.assertEqual(r[n], "PASSED", (n, [p for p in self.rep["passes"] if p["pass"] == n]))
        self.assertIn(self.rep["software_validation"], ("PASSED", "PASSED_WITH_WARNINGS")); self.assertTrue(self.rep["physical_validation"].startswith("PENDING"))
        self.assertIn("not proof", self.rep["disclaimer"]); self.assertEqual(len(self.rep["passes"]), 9)
    def test_unresolved_details_are_reported_not_hidden(self):
        self.assertEqual(results(self.rep)[2], "WARNING"); self.assertTrue(any("too small" in r for r in self.rep["remaining_risks"]))
    def test_derived_images_are_separate_png_files_and_the_original_is_untouched(self):
        before = bytes(self.data); self.assertEqual(self.data, before)
        for k, v in self.rep["derived_images"].items(): self.assertEqual(base64.b64decode(v)[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(self.rep["source"]["sha256"], __import__("hashlib").sha256(self.data).hexdigest())
    def test_metrics_are_documented_numbers(self):
        m = [p for p in self.rep["passes"] if p["pass"] == 8][0]["metrics"]
        for k in ("ink_recall", "stitched_spill", "boundary_p95_mm", "thread_coverage", "colour_match_min", "thresholds"): self.assertIn(k, m)
        self.assertGreater(m["ink_recall"], 0.97)

    # ---- mutations: the validation must notice
    def test_deleting_half_the_objects_fails(self):
        d = copy.deepcopy(self.design); d["objects"] = d["objects"][::2]
        rep = V.validate(self.data, 80, self.imp, d); r = results(rep)
        self.assertEqual(r[8], "FAILED"); self.assertEqual(r[5], "WARNING"); self.assertEqual(rep["software_validation"], "FAILED"); self.assertTrue(any("no stitching" in x or "removed" in x for x in rep["remaining_risks"]))
    def test_moving_one_object_fails_the_visual_comparison(self):
        d = copy.deepcopy(self.design)
        big = max(d["objects"], key=lambda o: len(o.get("rings", [[]])[0]) if o.get("rings") else 0)
        big["rings"] = [[[x + 4.0, y + 3.0] for x, y in r] for r in big["rings"]]
        rep = V.validate(self.data, 80, self.imp, d); self.assertEqual(results(rep)[8], "FAILED")
    def test_mirrored_design_fails_the_orientation_test(self):
        d = copy.deepcopy(self.design)
        for o in d["objects"]:
            for k in ("rings",):
                if k in o: o[k] = [[[80 - x, y] for x, y in r] for r in o[k]]
            for k in ("points", "rail1", "rail2"):
                if k in o: o[k] = [[80 - x, y] for x, y in o[k]]
        rep = V.validate(self.data, 80, self.imp, d); r = results(rep)
        self.assertEqual(r[7], "FAILED"); self.assertEqual(r[8], "FAILED")
    def test_a_dst_with_swapped_axes_is_refused_so_pass_6_fails(self):
        old = (dst._X_BITS, dst._Y_BITS)
        try:
            dst._X_BITS, dst._Y_BITS = dst._Y_BITS, dst._X_BITS
            rep = V.validate(self.data, 80, self.imp, self.design)
        finally: dst._X_BITS, dst._Y_BITS = old
        self.assertEqual(results(rep)[6], "FAILED"); self.assertEqual(rep["software_validation"], "FAILED"); self.assertIsNone(rep["dst_sha256"])
    def test_ink_that_is_neither_stitched_nor_accounted_fails_pass_2(self):
        imp = copy.deepcopy({k: v for k, v in self.imp.items() if k != "_work"}); imp["_work"] = self.imp["_work"]
        imp["report"]["coverage"]["stitched_area_mm2"] *= 0.5
        self.assertEqual(results(V.validate(self.data, 80, imp, self.design))[2], "FAILED")
    def test_a_translation_or_uniform_scale_of_the_whole_design_is_recognised_as_placement_not_error(self):
        d = copy.deepcopy(self.design)
        for o in d["objects"]:
            for k in ("rings",):
                if k in o: o[k] = [[[x * 0.8 + 5, y * 0.8 + 3] for x, y in r] for r in o[k]]
            for k in ("points", "rail1", "rail2"):
                if k in o: o[k] = [[x * 0.8 + 5, y * 0.8 + 3] for x, y in o[k]]
        rep = V.validate(self.data, 80, self.imp, d); self.assertEqual(results(rep)[8], "PASSED"); tr = [p for p in rep["passes"] if p["pass"] == 5][0]["metrics"]["transform"]
        self.assertAlmostEqual(tr["scale"], 0.8, places=2)

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class ServerPipeline(unittest.TestCase):
    def test_full_autodigitize_pipeline_validates_and_bundle_keeps_the_original_byte_for_byte(self):
        data = D.encode(D.plate(D.elements()), 1000)
        body = {"data": base64.b64encode(data).decode(), "width_mm": 80, "colors": 8, "quality": "high", "hoop_w": 120, "hoop_h": 120, "name": "plate"}
        z, info = server.api_image_bundle(body); self.assertIn(info["software_validation"], ("PASSED", "PASSED_WITH_WARNINGS"))
        zf = zipfile.ZipFile(io.BytesIO(z)); self.assertEqual(zf.read("original/plate.png"), data)
        for n in ("SOURCE.json", "inventory.json", "image-validation.json", "derived/overlay.png", "derived/difference.png", "plate.dst", "plate.production-report.html"): self.assertIn(n, zf.namelist())
        v = json.loads(zf.read("image-validation.json")); self.assertTrue(v["physical_validation"].startswith("PENDING"))
        self.assertEqual(__import__("hashlib").sha256(zf.read("plate.dst")).hexdigest(), info["dst_sha256"])
    def test_validate_endpoint_shape(self):
        data = D.encode(D.plate(D.elements()), 600)
        r = server.api_image_validate({"data": base64.b64encode(data).decode(), "width_mm": 80, "colors": 8, "quality": "standard", "hoop_w": 120, "hoop_h": 120, "images": True})
        self.assertEqual(len(r["passes"]), 9); self.assertIn("overlay.png", r["derived_images"]); self.assertNotIn("_work", json.dumps(r, default=str))
        r2 = server.api_image_validate({"data": base64.b64encode(data).decode(), "width_mm": 80, "colors": 8, "quality": "standard", "hoop_w": 120, "hoop_h": 120})
        self.assertNotIn("derived_images", r2)
if __name__ == "__main__": unittest.main()
