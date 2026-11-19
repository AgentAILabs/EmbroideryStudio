"""Photo Stitch Engine: tone -> line spacing, flow direction, density safety, determinism, DST round trip, preview/export consistency."""
import base64, hashlib, io, json, math, sys, time, unittest
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
    from stitchcraft_engine import photo, photo_validation as PV, export_pipeline as EP
    import app as server

def png(a):
    b = io.BytesIO(); Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(b, "PNG"); return b.getvalue()
def ramp(w=400, h=200):       # dark on the left -> light on the right
    return png(np.tile(np.linspace(30, 240, w)[None, :, None], (h, 1, 3)))
def sphere(w=420):
    y, x = np.mgrid[0:w, 0:w]; r = np.hypot(x - w / 2, y - w / 2) / (w * 0.4); s = np.clip(1 - r ** 2, 0, 1) ** 0.6
    img = np.where((r < 1)[..., None], (235 - 170 * s)[..., None] * np.ones(3), 235.0); return png(np.asarray(Image.fromarray(img.astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))))
def pts_all(res): return [p for o in res["objects"] for p in o["points"]]

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Tone(unittest.TestCase):
    def test_darker_areas_get_more_stitches_than_lighter_areas(self):
        r = photo.photo_stitch(ramp(), 80, "grayscale", levels=6, cross_hatch=False, equalize=0.0)
        xs = np.array([p[0] for p in pts_all(r)]); n = [int(((xs >= a) & (xs < a + 20)).sum()) for a in range(0, 80, 20)]
        self.assertGreater(n[0], n[1]); self.assertGreater(n[1], n[2]); self.assertGreater(n[2], n[3]); self.assertGreater(n[0], 2.0 * n[3])
    def test_white_stays_bare_fabric(self):
        a = np.full((200, 200, 3), 250.0); a[60:140, 60:140] = 40
        r = photo.photo_stitch(png(a), 60, "grayscale"); P = pts_all(r)
        self.assertTrue(all(15 <= x <= 45 and 15 <= y <= 45 for x, y in P), "no thread outside the dark square (60 mm wide: square spans 18-42 mm)")
    def test_blank_image_is_refused_with_a_clear_message(self):
        with self.assertRaises(ValueError) as cm: photo.photo_stitch(png(np.full((100, 100, 3), 255.0)), 50, "grayscale")
        self.assertIn("nothing to stitch", str(cm.exception))
    def test_dark_fabric_inverts_the_tone_mapping(self):
        a = np.full((200, 200, 3), 20.0); a[60:140, 60:140] = 230
        r = photo.photo_stitch(png(a), 60, "grayscale", fabric="#141414"); P = pts_all(r)
        self.assertTrue(P and all(15 <= x <= 45 and 15 <= y <= 45 for x, y in P)); self.assertEqual({o["color"] for o in r["objects"]}, {"#f4f4f4"})

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Direction(unittest.TestCase):
    def test_stitches_follow_a_strong_contour(self):
        a = np.full((300, 300, 3), 235.0); im = Image.fromarray(a.astype(np.uint8)); d = ImageDraw.Draw(im)
        d.polygon([(0, 300), (300, 0), (300, 300)], fill=(40, 40, 40)); im = im.filter(ImageFilter.GaussianBlur(1.5))     # dark triangle: edge runs at -45 degrees
        b = io.BytesIO(); im.save(b, "PNG"); r = photo.photo_stitch(b.getvalue(), 60, "grayscale", angle=0.0, cross_hatch=False)
        near = []
        for o in r["objects"]:
            P = o["points"]
            for p, q in zip(P, P[1:]):
                mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
                if abs((mx + my) - 60.0) < 2.5:                                                  # within 2.5 mm of the diagonal edge x + y = 60
                    near.append(math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180)
        self.assertTrue(len(near) > 8); med = float(np.median(near)); self.assertLess(min(abs(med - 135), abs(med - 135 + 180), abs(med - 135 - 180)), 15, med)
    def test_fixed_direction_uses_the_requested_angle(self):
        r = photo.photo_stitch(ramp(), 60, "grayscale", direction="fixed", angle=30.0, cross_hatch=False)
        ang = [math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180 for o in r["objects"] for p, q in zip(o["points"], o["points"][1:]) if math.hypot(q[0] - p[0], q[1] - p[1]) > 1.5]
        self.assertLess(abs(float(np.median(ang)) - 30.0), 6)

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Safety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = photo.photo_stitch(sphere(), 80, "grayscale", levels=6)
    def test_stitch_lengths_and_density_are_within_safe_limits(self):
        rp = self.res["report"]; self.assertGreaterEqual(rp["min_stitch_mm"], photo.MIN_STITCH); self.assertLessEqual(rp["max_stitch_mm"], photo.MAX_STITCH)
        self.assertEqual(rp["stitches_under_0_5mm"], 0); self.assertLessEqual(rp["max_penetrations_per_mm2"], 12)
    def test_deterministic(self):
        again = photo.photo_stitch(sphere(), 80, "grayscale", levels=6)
        self.assertEqual(hashlib.sha256(json.dumps(self.res["objects"]).encode()).hexdigest(), hashlib.sha256(json.dumps(again["objects"]).encode()).hexdigest())
    def test_stitch_budget_coarsens_and_says_so(self):
        r = photo.photo_stitch(sphere(), 80, "grayscale", levels=6, max_stitches=900)
        self.assertGreater(r["report"]["coarsened"], 1.0); self.assertTrue(any("stitch budget" in n for n in r["report"]["notes"])); self.assertLess(r["report"]["stitches"], self.res["report"]["stitches"])
    def test_parameter_validation(self):
        for kw in ({"levels": 1}, {"colors": 0}, {"density": 9}, {"mode": "x"}, {"direction": "x"}, {"gamma": 0.1}, {"dither": 2}, {"stitch_mm": 0.2}):
            with self.assertRaises(ValueError, msg=str(kw)): photo.photo_stitch(sphere(), 80, **{"mode": "grayscale", **kw})
    def test_multicolour_skips_fabric_coloured_areas_and_uses_only_palette_threads(self):
        a = np.full((300, 300, 3), (246, 238, 222), float); a[80:220, 80:220] = (200, 30, 40); a[130:170, 130:170] = (30, 60, 150)
        r = photo.photo_stitch(png(a), 70, "multicolour", colors=4, fabric="#f6eede"); cols = {o["color"] for o in r["objects"]}
        self.assertTrue(cols <= {h for _, h in photo.DEFAULT_PALETTE}); self.assertTrue(any(p.get("skipped") == "same as fabric" for p in r["report"]["palette"]) or len(cols) >= 2)
        self.assertGreaterEqual(len(cols), 2)
        xs = [p[0] for p in pts_all(r)]; ys = [p[1] for p in pts_all(r)]; self.assertGreater(min(xs), 70 * 0.2); self.assertLess(max(xs), 70 * 0.8)
    def test_custom_thread_palette_is_honoured(self):
        a = np.full((200, 200, 3), 250.0); a[50:150, 50:150] = (200, 30, 40)
        r = photo.photo_stitch(png(a), 60, "multicolour", colors=3, thread_palette=["#ffffff", "#aa0000", "#0000aa"], fabric="#fafafa")
        self.assertTrue({o["color"] for o in r["objects"]} <= {"#aa0000", "#0000aa"})

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class DstAndPreview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = server.api_photo_stitch({"data": base64.b64encode(sphere()).decode(), "width_mm": 80, "mode": "grayscale", "levels": 6, "name": "ball"})
    def test_dst_is_validated_and_roundtrips(self):
        a = self.api; self.assertNotIn("error", a); rep = a["dst"]["export_report"]
        self.assertEqual(rep["validation"]["physical_machine"][:8], "NOT DONE"); self.assertEqual(rep["counts"]["end"], 1)
        res = EP.export_dst(a["design"]); self.assertEqual(res.sha256, a["dst"]["sha256"])                # re-export is byte-identical
        recs, pos, hdr = EP.independent_decode(res.data); self.assertTrue(all(abs(dx) <= 121 and abs(dy) <= 121 for dx, dy, _ in recs))
    def test_preview_is_drawn_from_the_decoded_dst_and_matches_the_plan(self):
        a = self.api; sim = EP.decoded_simulation(a["design"]); seg = PV.segments_from_sim(sim["stitches"], sim["threads"])
        decoded_len = sum(math.hypot(x2 - x1, y2 - y1) for v in seg.values() for x1, y1, x2, y2 in v)
        plan_len = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for o in a["design"]["objects"] for p, q in zip(o["points"], o["points"][1:]))
        self.assertAlmostEqual(decoded_len / plan_len, 1.0, delta=0.12)            # locks / cleaned micro-stitches add or remove a little; the path is the same
    def test_validation_is_software_only_and_separate(self):
        v = self.api["validation"]; self.assertEqual(v["verdict"], "PASSED"); self.assertGreater(v["luminance_corr"], 0.8); self.assertIn("Not a measure of stitch-out quality", v["meaning"])
        self.assertTrue(any("PENDING" in h for h in self.api["honesty"])); self.assertNotIn("physical", json.dumps(v["checks"]).lower())
    def test_a_mirrored_preview_fails_the_comparison(self):
        """Mutation: an asymmetric photo; the preview drawn from the real DST matches it, the mirrored preview does not."""
        im = Image.open(io.BytesIO(sphere())).convert("RGB"); ImageDraw.Draw(im).ellipse((60, 70, 150, 160), fill=(20, 20, 20)); b = io.BytesIO(); im.save(b, "PNG"); asym = b.getvalue()
        a = server.api_photo_stitch({"data": base64.b64encode(asym).decode(), "width_mm": 80, "mode": "grayscale", "levels": 6, "name": "asym"})
        prev = Image.open(io.BytesIO(base64.b64decode(a["preview_png"]))).convert("RGB")
        good = PV.compare(asym, prev, 80, "grayscale"); bad = PV.compare(asym, prev.transpose(Image.FLIP_LEFT_RIGHT), 80, "grayscale")
        self.assertEqual(good["verdict"], "PASSED"); self.assertLess(bad["luminance_corr"], good["luminance_corr"] - 0.15); self.assertEqual(bad["verdict"], "WARNING")
    def test_stitch_metrics_from_the_exported_stream(self):
        m = self.api["stitch_metrics"]; self.assertEqual(m["share_under_0_5mm"], 0.0); self.assertEqual(m["share_over_7mm"], 0.0); self.assertLessEqual(m["max_penetrations_per_mm2"], 12)
    def test_api_rejects_bad_input(self):
        good = base64.b64encode(sphere()).decode()
        for bad in ({"data": good, "mode": "x"}, {"data": good, "thread_palette": ["red"]}, {"data": base64.b64encode(b"nope").decode()}, {"data": good, "width_mm": 0}):
            with self.assertRaises(ValueError): server.api_photo_stitch(bad)

@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class Budget(unittest.TestCase):
    def test_large_photo_stays_within_time_and_object_limits(self):
        t = time.time(); r = photo.photo_stitch(sphere(520), 160, "grayscale", levels=6); dt = time.time() - t
        self.assertLess(dt, 40); self.assertLess(len(r["objects"]), 3000); self.assertLessEqual(r["report"]["stitches"], 180000 * 1.0)
if __name__ == "__main__": unittest.main()
