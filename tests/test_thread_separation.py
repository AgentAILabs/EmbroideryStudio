"""Thread-colour separation digitizing: classification by hue, rosette detection, border line, strays, leaf angles, API."""
import base64, io, math, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
try:
    import numpy as np
    from PIL import Image, ImageDraw
    HAVE = True
except ImportError:
    HAVE = False
if HAVE:
    from stitchcraft_engine import thread_separation as TS
    import app as server

RED, GOLD, PINK = (205, 25, 45), (196, 154, 58), (218, 130, 150)


def garment(border=True, ring=True, leaves=True, w=420, h=520):
    im = Image.new("RGB", (w, h), PINK); d = ImageDraw.Draw(im)
    if ring: d.ellipse([60, 60, 160, 160], fill=GOLD); d.ellipse([90, 90, 130, 130], fill=PINK)             # gold ring with a hole
    d.ellipse([250, 70, 300, 120], fill=GOLD)                                                                  # solid rosette
    if leaves:
        for k in range(5): d.polygon([(60 + k * 70, 260), (80 + k * 70, 215), (100 + k * 70, 260), (80 + k * 70, 300)], fill=RED)   # leaves
    d.polygon([(10, 5), (14, 9), (10, 12)], fill=RED)                                                          # a stray speck
    if border:
        for x in range(20, w - 20): d.rectangle([x, int(440 + 6 * math.sin(x / 14)), x + 1, int(440 + 6 * math.sin(x / 14)) + 10], fill=GOLD)
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Separation(unittest.TestCase):
    def test_classification_by_hue(self):
        masks, (W, H) = TS.classify(garment())
        self.assertGreater(masks["red"].sum(), 5000); self.assertGreater(masks["gold"].sum(), 20000)
        self.assertEqual(int((masks["red"] & masks["gold"]).sum()), 0, "a pixel belongs to one thread")
        # fabric (pink) is neither
        yy, xx = 30 * 2, 380 * 2; self.assertFalse(masks["red"][yy, xx] or masks["gold"][yy, xx])

    def test_round_gold_becomes_rosettes_with_the_real_hole(self):
        plan = TS.prepare(garment(border=False), 50)
        self.assertGreaterEqual(plan["counts"]["rosettes"], 2)
        rin = sorted(r[4] for r in plan["rosettes"]); self.assertGreater(rin[-1], 2.0, "the ring keeps its hole (~2.4 mm radius)")
        self.assertAlmostEqual(rin[0], 1.6, delta=0.1, msg="a solid rosette gets the 1.6 mm stone seat")
        for _, _, _, Re, ri in plan["rosettes"]: self.assertLess(ri, Re)

    def test_border_is_one_smooth_line(self):
        plan = TS.prepare(garment(), 120)
        self.assertGreaterEqual(plan["counts"]["border_lines"], 1)
        pts = plan["border_lines"][0][1]; self.assertGreater(len(pts), 20)
        ys = [p[1] for p in pts]; self.assertLess(max(ys) - min(ys), 40, "no spikes: the fitted line follows the scallop only")
        self.assertTrue(all(abs(ys[i + 1] - ys[i]) < 12 for i in range(len(ys) - 1)))

    def test_no_border_found_when_absent(self):
        self.assertEqual(TS.prepare(garment(border=False), 120)["counts"]["border_lines"], 0)
        self.assertEqual(TS.prepare(garment(), 120, border=False)["counts"]["border_lines"], 0)

    def test_blank_image_refused(self):
        b = io.BytesIO(); Image.new("RGB", (200, 200), PINK).save(b, "PNG")
        with self.assertRaises(ValueError): TS.prepare(b.getvalue(), 100)
        with self.assertRaises(ValueError): TS.prepare(garment(), 0.5)

    def test_run_labelling_matches_a_reference(self):
        rng = np.random.RandomState(1); m = rng.rand(60, 80) > 0.55
        got = sorted(len(ys) for ys, xs in TS._comps(m, 1, np))
        # reference: flood fill
        seen = np.zeros_like(m); ref = []
        for y in range(60):
            for x in range(80):
                if m[y, x] and not seen[y, x]:
                    st = [(y, x)]; seen[y, x] = True; n = 0
                    while st:
                        cy, cx = st.pop(); n += 1
                        for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                            if 0 <= ny < 60 and 0 <= nx < 80 and m[ny, nx] and not seen[ny, nx]: seen[ny, nx] = True; st.append((ny, nx))
                    ref.append(n)
        self.assertEqual(got, sorted(ref))


@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Api(unittest.TestCase):
    def setUp(self):
        self.r = server.api_garment_digitize({"data": base64.b64encode(garment()).decode(), "width_mm": 120, "name": "Test Garment"})

    def test_result_shape_and_honesty(self):
        r = self.r; self.assertNotIn("error", r)
        self.assertEqual(r["preflight"]["verdict"], "PASSED"); self.assertRegex(r["dst"]["filename"], r"^[A-Z0-9]{1,8}\.DST$")
        self.assertEqual([s["id"] for s in r["sections"]["sections"]][-1], "physical"); self.assertEqual(r["sections"]["sections"][-1]["verdict"], "PENDING")
        self.assertTrue(any("PENDING" in h for h in r["honesty"]))

    def test_design_has_rosette_columns_border_satin_and_no_strays(self):
        objs = self.r["design"]["objects"]
        self.assertTrue(any(o["id"].startswith("ros") and o["type"] == "column" for o in objs)); self.assertTrue(any(o["id"].startswith("scal") and o["type"] == "satin" for o in objs))
        self.assertGreaterEqual(self.r["separation"]["strays_removed"], 1); self.assertEqual(self.r["design"]["machine"]["trim_distance"], 6.0)

    def test_leaf_fills_get_angle_underlay_and_spacing(self):
        fills = [o for o in self.r["design"]["objects"] if o["type"] == "fill"]
        self.assertTrue(fills); self.assertTrue(all(o["params"]["spacing"] == 0.46 and o["params"]["cut_hidden"] for o in fills))
        self.assertGreaterEqual(self.r["separation"]["leaf_fills_angled"], 1)

    def test_dst_is_valid_and_deterministic(self):
        r2 = server.api_garment_digitize({"data": base64.b64encode(garment()).decode(), "width_mm": 120, "name": "Test Garment"})
        self.assertEqual(self.r["dst"]["sha256"], r2["dst"]["sha256"])

    def test_threads_param_validation(self):
        data = base64.b64encode(garment()).decode()
        for bad in ([], "x", [{"id": "A B", "hex": "#fff", "hue": [0, 10]}], [{"id": "a", "hex": "#aabbcc", "hue": [0, 999]}], [{"id": "a", "hex": "#aabbcc", "hue": [0, 10], "sat_min": 5}]):
            with self.assertRaises(ValueError): server.api_garment_digitize({"data": data, "width_mm": 100, "threads": bad})
        with self.assertRaises(ValueError): server.api_garment_digitize({"data": base64.b64encode(b"GIF89a....").decode()})


if __name__ == "__main__":
    unittest.main()
