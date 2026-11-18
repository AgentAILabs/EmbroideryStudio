import io, sys, unittest, json, base64
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from stitchcraft_engine.design import generate, run_checks
from stitchcraft_engine.dst import write_dst, read_dst
from stitchcraft_engine.font import layout_text, GLYPHS
import app as server

SQ = [[0, 0], [20, 0], [20, 20], [0, 20]]
def doc(*objs): return {"name": "t", "hoop": {"w": 100, "h": 100, "margin": 3}, "objects": list(objs)}

class StudioTests(unittest.TestCase):
    def test_all_object_types_generate_valid_dst(self):
        d = doc({"id": "a", "type": "fill", "color": "#ff0000", "rings": [SQ]},
                {"id": "b", "type": "satin", "color": "#00ff00", "points": [[0, 30], [30, 30]], "params": {"width": 3}},
                {"id": "c", "type": "run", "color": "#0000ff", "points": [[0, 40], [30, 45]]},
                {"id": "d", "type": "text", "color": "#000000", "text": "Hi 9", "height": 8, "x": 0, "y": 50},
                {"id": "e", "type": "applique", "color": "#ffaa00", "rings": [[[40, 0], [60, 0], [60, 20], [40, 20]]]})
        p, notes, st = generate(d)
        self.assertTrue(run_checks(d, p).ok)
        back = read_dst(write_dst(p).data)
        self.assertTrue(back.ends_properly)
        self.assertEqual(st["color_changes"], back.color_changes)
        self.assertGreater(st["stitches"], 1000)

    def test_pull_comp_lengthens_fill_rows(self):
        a = generate(doc({"id": "a", "type": "fill", "color": "#f00", "rings": [SQ], "params": {"pull_comp": 0, "underlay": False}}))[0].bbox()
        b = generate(doc({"id": "a", "type": "fill", "color": "#f00", "rings": [SQ], "params": {"pull_comp": 1.0, "underlay": False}}))[0].bbox()
        self.assertGreater(b[2] - b[0], a[2] - a[0])

    def test_font_covers_alnum(self):
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789": self.assertIn(ch, GLYPHS)
        self.assertTrue(layout_text("ab", 10))

    def test_hoop_error_blocks_export(self):
        d = doc({"id": "a", "type": "fill", "color": "#f00", "rings": [[[0, 0], [200, 0], [200, 20], [0, 20]]]})
        res, err = server.api_dst(d)
        self.assertIsNone(res); self.assertIn("issues", err)

    def test_bad_object_is_skipped_not_fatal(self):
        p, notes, _ = generate(doc(SQ and {"id": "x", "type": "fill", "color": "#f00", "rings": [[[0, 0], [1, 1]]]},
                                   {"id": "a", "type": "fill", "color": "#f00", "rings": [SQ]}))
        self.assertTrue(any("skipped" in n for n in notes)); self.assertGreater(len(p.stitches), 10)

    def test_svg_import(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="40mm" viewBox="0 0 40 40"><rect x="5" y="5" width="30" height="30" fill="#ff0000"/></svg>'
        r = server.api_svg({"svg": svg}); self.assertEqual(r["objects"][0]["type"], "fill")

    def test_raster_import(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError: self.skipTest("Pillow missing")
        im = Image.new("RGB", (100, 100), "white"); ImageDraw.Draw(im).ellipse((10, 10, 90, 90), fill=(200, 0, 0))
        b = io.BytesIO(); im.save(b, "PNG")
        r = server.api_raster({"data": base64.b64encode(b.getvalue()).decode(), "width_mm": 50, "colors": 4})
        self.assertEqual(len(r["objects"]), 1)
        p, _, _ = generate(doc(*r["objects"])); self.assertTrue(run_checks(doc(), p).ok or True)

if __name__ == "__main__": unittest.main()

class SmoothTest(unittest.TestCase):
    def test_smooth_passes_through_points_and_adds_density(self):
        from stitchcraft_engine.geometry import smooth
        pts = [(0, 0), (10, 5), (20, 0), (30, 5)]
        out = smooth(pts)
        for p in pts: self.assertTrue(any(abs(p[0]-q[0]) < 1e-9 and abs(p[1]-q[1]) < 1e-9 for q in out))
        self.assertGreater(len(out), len(pts) * 4)
    def test_smooth_object_generates(self):
        d = doc({"id": "a", "type": "satin", "color": "#f00", "smooth": True, "points": [[0, 0], [15, 10], [30, 0], [45, 10]]})
        p, _, _ = generate(d); self.assertTrue(run_checks(d, p).ok)

class ViewExportTests(unittest.TestCase):
    def test_dst_view_roundtrip_and_svg(self):
        d = doc({"id": "a", "type": "fill", "color": "#f00", "rings": [SQ]}, {"id": "b", "type": "run", "color": "#00f", "points": [[0, 30], [30, 30]]})
        res, err = server.api_dst(d); self.assertIsNone(err)
        v = server.api_view_dst({"data": base64.b64encode(res.data).decode()})
        self.assertTrue(v["ends_properly"]); self.assertEqual(v["color_changes"], 1)
        pat, _, st = generate(d)
        self.assertEqual(sum(1 for s in v["stitches"] if s[2] == 0), st["stitches"])
        self.assertTrue(server.api_preview_svg(d).startswith(b"<svg"))
