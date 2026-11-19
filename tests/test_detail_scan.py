"""Independent multi-scale detail scan: finds details on the ORIGINAL, matches them to the inventory, never lets one disappear."""
import base64, sys, unittest
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
    from stitchcraft_engine import detail_scan as DS
    from stitchcraft_engine.raster import digitize_image
    import app as server

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Scan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.els = D.elements(); cls.data = D.encode(D.plate(cls.els), 1000)
        cls.imp = digitize_image(cls.data, 80, 8, "high"); cls.r = DS.scan(cls.data, 80, cls.imp["inventory"])
    def test_scales_and_feature_sizes_are_reported(self):
        self.assertEqual(self.r["scales_px"], [1.0, 2.0, 4.0, 8.0]); self.assertEqual(len(self.r["feature_sizes_mm"]), 4); self.assertEqual(self.r["feature_sizes_mm"], sorted(self.r["feature_sizes_mm"]))
    def test_isolated_small_elements_are_detected_independently_of_the_digitizer(self):
        """Without any inventory the scan still finds hairlines, dots, leaves, border squares and marks (detector independence)."""
        r = DS.scan(self.data, 80, [])
        self.assertEqual(r["counts"]["awaiting_review"], r["detections_total"])               # nothing matched because there is no inventory
        found = tot = 0
        for e in self.els:
            if e["cls"] not in ("hairline", "dot", "leaf", "border", "mark", "curve"): continue
            ys, xs = np.nonzero(e["mask"]); x0, x1, y0, y1 = xs.min() / 20 - .6, xs.max() / 20 + .6, ys.min() / 20 - .6, ys.max() / 20 + .6; tot += 1
            found += any(x0 <= d["x_mm"] <= x1 and y0 <= d["y_mm"] <= y1 for d in r["detections"])
        self.assertGreaterEqual(found / tot, 0.95, (found, tot))
    def test_every_detection_has_a_status_and_the_smallest_dot_is_not_stitchable(self):
        for d in self.r["detections"]: self.assertIn(d["status"], ("digitized", "approximate", "not_stitchable", "omitted_by_user", "awaiting_review"))
        self.assertEqual(self.r["counts"]["awaiting_review"], 0); self.assertEqual(self.r["counts"]["not_stitchable"], 1); self.assertGreaterEqual(self.r["agreement"], 0.99)
        nd = [d for d in self.r["detections"] if d["status"] == "not_stitchable"][0]; self.assertLess(nd["size_mm"], 0.75)
    def test_gaps_between_marks_are_not_reported_as_details(self):
        ys = [d["y_mm"] for d in self.r["detections"] if 12.0 < d["y_mm"] < 12.9 and 8 < d["x_mm"] < 23]                # the white gap between two hairlines
        self.assertEqual(ys, [])
    def test_a_coarse_digitizer_run_cannot_hide_details(self):
        """Draft quality (260 px, 6 mm2 minimum) loses details; the scan reports them as awaiting_review instead of letting them vanish."""
        imp = digitize_image(self.data, 80, 8, "draft"); r = DS.scan(self.data, 80, imp["inventory"])
        self.assertGreater(r["counts"]["awaiting_review"], 5)
    def test_listing_is_capped_but_counts_are_complete(self):
        self.assertLessEqual(self.r["listed"], DS.MAX_LISTED); self.assertEqual(sum(self.r["counts"].values()), self.r["detections_total"])
    def test_blank_image_has_no_detections_and_no_crash(self):
        im = Image.new("RGB", (300, 300), "white"); import io; b = io.BytesIO(); im.save(b, "PNG")
        self.assertEqual(DS.scan(b.getvalue(), 80, [])["detections_total"], 0)
    def test_validation_pass_2_carries_the_scan_and_warns_on_unreviewed_details(self):
        r = server.api_image_validate({"data": base64.b64encode(self.data).decode(), "width_mm": 80, "colors": 8, "quality": "draft", "hoop_w": 120, "hoop_h": 120})
        p2 = [p for p in r["passes"] if p["pass"] == 2][0]; self.assertEqual(p2["result"], "WARNING"); self.assertIn("detail_scan", p2["metrics"]); self.assertTrue(any("awaiting review" in x for x in r["remaining_risks"]))
if __name__ == "__main__": unittest.main()
