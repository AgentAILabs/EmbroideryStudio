"""Shape recognition + stitch-type presets (smart_design.py) and their integration in the raster digitizer / API."""
import base64, io, math, random, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import smart_design as SD
try:
    import numpy as np
    from PIL import Image, ImageDraw
    HAVE = True
except ImportError:
    HAVE = False
if HAVE:
    from stitchcraft_engine import raster, export_pipeline as EP
    import app as server


def ellipse(a, b, ang=0.0, n=90, noise=0.0, seed=3, cx=10.0, cy=10.0):
    r = random.Random(seed); out = []
    for t in range(n):
        th = 2 * math.pi * t / n; u = (a + r.uniform(-noise, noise)) * math.cos(th); v = (b + r.uniform(-noise, noise)) * math.sin(th)
        out.append([cx + u * math.cos(ang) - v * math.sin(ang), cy + u * math.sin(ang) + v * math.cos(ang)])
    return out


def rect(w, h, ang=0.0, per_side=8):
    corners = [(0, 0), (w, 0), (w, h), (0, h)]; pts = []
    for i in range(4):
        (x0, y0), (x1, y1) = corners[i], corners[(i + 1) % 4]
        for k in range(per_side): pts.append((x0 + (x1 - x0) * k / per_side, y0 + (y1 - y0) * k / per_side))
    return [[10 + x * math.cos(ang) - y * math.sin(ang), 10 + x * math.sin(ang) + y * math.cos(ang)] for x, y in pts]


class Recognition(unittest.TestCase):
    def kind(self, ring):
        r = SD.recognize_ring(ring); return r[1]["kind"] if r else None

    def test_circle_ellipse_rectangle_square(self):
        self.assertEqual(self.kind(ellipse(8, 8)), "circle"); self.assertEqual(self.kind(ellipse(12, 5, 0.5)), "ellipse")
        self.assertEqual(self.kind(rect(30, 10)), "rectangle"); self.assertEqual(self.kind(rect(12, 12, 0.3)), "square")

    def test_fitted_parameters_are_accurate(self):
        r, info = SD.recognize_ring(ellipse(12, 5, 0.5)); self.assertAlmostEqual(info["a"], 12, delta=0.1); self.assertAlmostEqual(info["b"], 5, delta=0.1); self.assertAlmostEqual(info["angle_deg"], math.degrees(0.5), delta=1.0)
        r, info = SD.recognize_ring(rect(16, 6, math.radians(23))); self.assertAlmostEqual(info["w"], 16, delta=0.15); self.assertAlmostEqual(info["h"], 6, delta=0.15)
        _, c = SD.recognize_ring(ellipse(8, 8, cx=3, cy=4)); self.assertAlmostEqual(c["cx"], 3, delta=0.05); self.assertAlmostEqual(c["r"], 8, delta=0.05)

    def test_survives_trace_noise(self):
        self.assertEqual(self.kind(ellipse(12, 5, 0.5, noise=0.25)), "ellipse"); self.assertEqual(self.kind(ellipse(8, 8, noise=0.2)), "circle")

    def test_thin_ellipse(self):
        self.assertEqual(self.kind(ellipse(20, 2, 1.0)), "ellipse")

    def test_things_that_are_not_primitives_are_left_alone(self):
        star = [[10 + (9 if i % 2 == 0 else 4) * math.cos(i * math.pi / 5), 10 + (9 if i % 2 == 0 else 4) * math.sin(i * math.pi / 5)] for i in range(10)]
        trapezoid = [[x, y] for x, y in [(0, 0), (6, 0), (12, 0), (18, 0), (24, 0), (21, 5), (18, 10), (15, 10), (9, 10), (6, 10), (3, 5)]]
        lshape = [[0, 0], [10, 0], [20, 0], [20, 5], [20, 10], [10, 10], [10, 20], [5, 20], [0, 20], [0, 10], [0, 5], [5, 0]]
        rounded = [[x, y] for x, y in [(2, 0), (10, 0), (18, 0), (20, 2), (20, 5), (20, 8), (18, 10), (10, 10), (2, 10), (0, 8), (0, 5), (0, 2)]]
        for name, ring in (("star", star), ("trapezoid", trapezoid), ("L", lshape)):
            self.assertIsNone(SD.recognize_ring(ring), name)
        r = SD.recognize_ring(rounded); self.assertTrue(r is None or r[1]["kind"] in ("rectangle", "square"))      # a rounded rectangle is left alone or a near-rectangle, never a circle / ellipse
        sq45 = [[10, 0], [20, 10], [10, 20], [0, 10]]; sq45 = [[sq45[i][0] + (sq45[(i + 1) % 4][0] - sq45[i][0]) * k / 8, sq45[i][1] + (sq45[(i + 1) % 4][1] - sq45[i][1]) * k / 8] for i in range(4) for k in range(8)]
        self.assertEqual(self.kind(sq45), "square")                                                           # a square turned 45 degrees is still a square

    def test_degenerate_input(self):
        self.assertIsNone(SD.recognize_ring([[0, 0], [1, 0], [1, 1]])); self.assertIsNone(SD.recognize_ring([[0, 0]] * 20))

    def test_replacement_rings_are_clean_and_equal_area(self):
        for ring in (ellipse(12, 5, 0.5, noise=0.2), rect(30, 10, 0.4)):
            new, info = SD.recognize_ring(ring); self.assertAlmostEqual(SD._area(new), SD._area(ring), delta=0.06 * SD._area(ring))
        self.assertEqual(len(SD.recognize_ring(rect(30, 10))[0]), 4); self.assertGreaterEqual(len(SD.recognize_ring(ellipse(8, 8))[0]), 24)

    def test_holes_recognised_independently(self):
        outer, holes, info = SD.recognize_shape(ellipse(20, 20, n=120), [ellipse(8, 8, n=60), [[5, 5], [9, 5], [9, 9]] * 4])
        self.assertEqual(info["outer"]["kind"], "circle"); self.assertEqual(info["holes"][0]["kind"], "circle"); self.assertIsNone(info["holes"][1])


@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class StrokeSatin(unittest.TestCase):
    L = [[0, 0], [3, 0], [3, 17], [14, 17], [14, 20], [0, 20]]
    RING = (ellipse(9, 9, n=90), [ellipse(6, 6, n=90)])

    def covered(self, outer, holes, cols):
        from PIL import Image, ImageDraw
        res = 0.1; W = int(30 / res); im = Image.new("L", (W, W), 0); d = ImageDraw.Draw(im)
        for c in cols: d.polygon([(x / res, y / res) for x, y in c["rail1"] + c["rail2"][::-1]], fill=255)
        ref = Image.new("L", (W, W), 0); d2 = ImageDraw.Draw(ref); d2.polygon([(x / res, y / res) for x, y in outer], fill=255)
        for h in holes: d2.polygon([(x / res, y / res) for x, y in h], fill=0)
        a, b = np.asarray(im) > 127, np.asarray(ref) > 127
        return (a & b).sum() / b.sum(), (a & ~b).sum() / a.sum()

    def test_stroke_shapes_become_columns_that_cover_them(self):
        for outer, holes in ((self.L, []), self.RING):
            cols = SD.stroke_columns(outer, holes, 9.0); self.assertTrue(cols)
            cov, spill = self.covered(outer, holes, cols); self.assertGreaterEqual(cov, 0.94); self.assertLessEqual(spill, 0.14)
            for c in cols: self.assertEqual(len(c["rail1"]), len(c["rail2"]))

    def test_blobs_and_hairlines_are_refused(self):
        self.assertIsNone(SD.stroke_columns(ellipse(9, 9, n=90), [], 9.0))                    # a fat disc is a fill
        self.assertIsNone(SD.stroke_columns([[0, 0], [20, 0], [20, 0.5], [0, 0.5]], [], 9.0))  # thinner than a satin can be

    def test_width_follows_the_stroke(self):
        wedge = [[0, 0], [10, 0], [20, 0], [30, 0], [40, 0], [40, 6], [30, 5.3], [20, 4.5], [10, 3.7], [0, 3]]                 # 3 mm wide at one end, 6 mm at the other
        cols = SD.stroke_columns(wedge, [], 9.0); self.assertTrue(cols)
        c = max(cols, key=lambda c: len(c["rail1"])); w = [math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(c["rail1"], c["rail2"])]
        first, last = sum(w[2:5]) / 3, sum(w[-5:-2]) / 3
        self.assertGreater(max(first, last), 1.5 * min(first, last))                                                         # the column width follows the stroke

    def test_deterministic(self):
        self.assertEqual(SD.stroke_columns(self.L, [], 9.0), SD.stroke_columns(self.L, [], 9.0))


class Presets(unittest.TestCase):
    def test_table_and_validation(self):
        self.assertEqual(set(SD.PRESETS), {"auto", "logo_satin", "line_art", "fine_detail", "fill_all"})
        self.assertEqual(SD.preset_cfg("auto"), {"thin_mm": 1.0, "column_max_mm": 5.5, "min_aspect": 2.5, "stroke_satin": False})
        with self.assertRaises(ValueError): SD.preset_cfg("wilcom")
        for p in SD.PRESETS.values(): self.assertTrue(p["label"]); self.assertGreaterEqual(p["column_max_mm"], 0)


def art():
    im = Image.new("RGB", (400, 300), "white"); d = ImageDraw.Draw(im)
    d.ellipse([30, 30, 130, 130], fill=(0, 0, 0)); d.rectangle([180, 40, 330, 100], fill=(200, 30, 30)); d.ellipse([60, 170, 260, 230], fill=(30, 30, 200))
    d.polygon([(300, 150), (380, 150), (340, 260)], fill=(20, 140, 60)); d.rectangle([20, 250, 380, 262], fill=(0, 0, 0))
    b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()


@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Integration(unittest.TestCase):
    def test_default_is_unchanged_and_deterministic(self):
        a = raster.digitize_image(art(), 80, 5, "high"); b = raster.digitize_image(art(), 80, 5, "high", None, "auto", False)
        self.assertEqual(a["objects"], b["objects"]); self.assertNotIn("shapes", a["report"]); self.assertFalse(a["report"]["shapes_recognised"])

    def test_shapes_are_recognised_and_reported(self):
        r = raster.digitize_image(art(), 80, 5, "high", None, "auto", True)
        self.assertEqual(r["report"]["shapes"], {"circle": 1, "ellipse": 1, "rectangle": 1})
        names = sorted(o["name"].split()[0] for o in r["objects"]); self.assertIn("Circle", names); self.assertIn("Ellipse", names); self.assertIn("Rectangle", names)
        plain = raster.digitize_image(art(), 80, 5, "high")
        rect_o = next(o for o in r["objects"] if o["name"].startswith("Rectangle")); self.assertEqual(len(rect_o["rings"][0]), 4)
        self.assertLess(len(rect_o["rings"][0]), max(len(o["rings"][0]) for o in plain["objects"] if o["type"] == "fill"))

    def test_presets_move_the_stitch_type_boundaries(self):
        def kinds(p): return raster.digitize_image(art(), 80, 5, "high", None, p)["report"]["objects"]
        auto, logo, fills = kinds("auto"), kinds("logo_satin"), kinds("fill_all")
        self.assertEqual(fills["column"] + fills["run"], 0); self.assertGreater(logo["column"], auto["column"]); self.assertEqual(sum(auto.values()), sum(fills.values()))

    def test_logo_satin_lays_satin_along_strokes_and_exports(self):
        im = Image.new("RGB", (500, 260), "white"); d = ImageDraw.Draw(im); d.rectangle([40, 40, 80, 220], fill=(0, 0, 0)); d.arc([120, 40, 320, 220], 30, 330, fill=(0, 0, 0), width=40)     # an 'i'-like stem and a 'c'-like arc
        b = io.BytesIO(); im.save(b, "PNG"); raw = b.getvalue()
        auto = raster.digitize_image(raw, 90, 3, "high", None, "auto", True); logo = raster.digitize_image(raw, 90, 3, "high", None, "logo_satin", True)
        self.assertGreaterEqual(logo["report"].get("stroke_satin", 0), 1); self.assertNotIn("stroke_satin", auto["report"])
        self.assertGreaterEqual(logo["report"]["objects"]["column"], auto["report"]["objects"]["column"])
        d = {"name": "ls", "hoop": {"w": 130, "h": 100, "margin": 3}, "objects": logo["objects"]}; self.assertGreater(EP.export_dst(d).report["counts"]["stitch"], 200)

    def test_recognised_design_exports_a_valid_dst(self):
        r = raster.digitize_image(art(), 80, 5, "high", None, "logo_satin", True)
        d = {"name": "sd", "hoop": {"w": 150, "h": 150, "margin": 3}, "objects": r["objects"]}; ex = EP.export_dst(d)
        self.assertGreater(ex.report["counts"]["stitch"], 500)

    def test_api(self):
        data = base64.b64encode(art()).decode()
        out = server.api_raster({"data": data, "width_mm": 80, "colors": 5, "quality": "high", "preset": "logo_satin", "shapes": True})
        self.assertEqual(out["report"]["preset"], "logo_satin"); self.assertTrue(out["report"]["shapes_recognised"])
        with self.assertRaises(ValueError): server.api_raster({"data": data, "width_mm": 80, "preset": "nope"})
        self.assertEqual({p["id"] for p in server.api_presets()["presets"]}, set(SD.PRESETS))
        auto = server.api_autodigitize({"data": data, "width_mm": 80, "colors": 5, "quality": "high", "preset": "fill_all", "shapes": True, "hoop_w": 130, "hoop_h": 130})
        self.assertFalse(any(o["type"] in ("column", "run") for o in auto["design"]["objects"] if o["type"] != "manual" and not str(o.get("name", "")).startswith("Tack")))


if __name__ == "__main__":
    unittest.main()
