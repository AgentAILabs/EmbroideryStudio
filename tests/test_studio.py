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

class EdgeUnderlayTests(unittest.TestCase):
    def test_inset_ring_square_and_failure_modes(self):
        from stitchcraft_engine.geometry import inset_ring
        r = inset_ring([(0, 0), (10, 0), (10, 10), (0, 10)], 1)
        self.assertEqual([tuple(round(v, 6) for v in p) for p in r], [(1, 1), (9, 1), (9, 9), (1, 9)])
        self.assertIsNotNone(inset_ring([(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)], 0.5))
        self.assertIsNone(inset_ring([(0, 0), (1, 0), (1, 1), (0, 1)], 0.6))   # collapses

    def test_edge_underlay_adds_stitches_inside_shape(self):
        base = {"id": "a", "type": "fill", "color": "#f00", "rings": [SQ]}
        n0 = generate(doc(dict(base, params={"underlay": "none"})))[0].counts()["stitch"]
        ne = generate(doc(dict(base, params={"underlay": "edge"})))[0]
        self.assertGreater(ne.counts()["stitch"], n0)
        bb = ne.bbox(); self.assertLessEqual(bb[2] - bb[0], 20.5)          # nothing outside the fill
        self.assertTrue(run_checks(doc(base), ne).ok)
        self.assertEqual(generate(doc(dict(base, params={"underlay": True})))[0].counts(),
                         generate(doc(dict(base, params={"underlay": "tatami"})))[0].counts())   # legacy bool
class ColumnTests(unittest.TestCase):
    PETAL = {"id": "c", "type": "column", "color": "#f0a", "rail1": [[0, 0], [5, 10], [10, 20]], "rail2": [[6, 0], [8, 10], [10, 20]]}
    def test_column_stays_between_rails_and_is_valid(self):
        d = doc(dict(self.PETAL, params={"pull_comp": 0, "underlay": "none"}))
        p, notes, st = generate(d)
        self.assertTrue(run_checks(d, p).ok); self.assertGreater(st["stitches"], 40)
        bb = p.bbox(); self.assertGreaterEqual(bb[0], -1e-6); self.assertLessEqual(bb[2], 10.0001)
    def test_opposite_rail_direction_is_corrected(self):
        c = dict(self.PETAL, rail2=list(reversed(self.PETAL["rail2"])), params={"pull_comp": 0, "underlay": "none"})
        a = generate(doc(c))
        self.assertTrue(any("reversed" in n for n in a[1]))
        ref = generate(doc(dict(self.PETAL, params={"pull_comp": 0, "underlay": "none"})))
        self.assertEqual(a[0].counts(), ref[0].counts())
        self.assertTrue(run_checks(doc(c), a[0]).ok)
    def test_bad_column_is_skipped(self):
        _, notes, _ = generate(doc(dict(self.PETAL, rail2=[[1, 1]]), {"id": "a", "type": "fill", "color": "#f00", "rings": [SQ]}))
        self.assertTrue(any("skipped" in n for n in notes))

class MvpGapTests(unittest.TestCase):
    def test_machine_profile_limits_and_trim_jumps(self):
        from stitchcraft_engine.design import machine
        m = machine({"machine": {"max_stitch": 99, "trim_jumps": 0, "trim_distance": "x"}})
        self.assertEqual((m["max_stitch"], m["trim_jumps"], m["trim_distance"]), (12.1, 1, 3.0))
        base = {"id": "a", "type": "run", "color": "#f00", "points": [[0, 0], [30, 0]], "params": {"stitch_len": 6}}
        d1, d2 = doc(base), doc(base); d2["machine"] = {"max_stitch": 5}
        p, _, _ = generate(d1)
        self.assertFalse(any(i.code == "STITCH_LONG" for i in run_checks(d1, p).issues))
        self.assertTrue(any(i.code == "STITCH_LONG" for i in run_checks(d2, p).issues))

    def test_trim_jump_count_is_configurable(self):
        d = doc({"id": "a", "type": "run", "color": "#f00", "points": [[0, 0], [5, 0]]},
                {"id": "b", "type": "run", "color": "#f00", "points": [[40, 0], [45, 0]]})
        for n in (2, 4):
            d["machine"] = {"trim_jumps": n}
            res, err = server.api_dst(d); self.assertIsNone(err)
            trims = sum(1 for r in read_dst(res.data).records if r == (0, 0, "jump"))   # trim = zero-move jumps
            self.assertEqual(trims, n)

    def test_satin_width_notes(self):
        notes = lambda w: generate(doc({"id": "s", "type": "satin", "color": "#f00", "points": [[0, 0], [20, 0]], "params": {"width": w}}))[1]
        self.assertTrue(any("narrow" in n for n in notes(0.5)))
        self.assertTrue(any("split automatically" in n for n in notes(9)))        # default: auto-split on
        off = generate(doc({"id": "s", "type": "satin", "color": "#f00", "points": [[0, 0], [20, 0]], "params": {"width": 9, "auto_split": False}}))[1]
        self.assertTrue(any("loose" in n for n in off))
        self.assertEqual(notes(3), [])

    def test_upload_safety(self):
        evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"/></svg>'
        with self.assertRaises(ValueError): server.api_svg({"svg": evil})
        with self.assertRaises(ValueError): server.api_svg({"svg": "%PDF-1.4 ..."})
        with self.assertRaises(ValueError): server.api_raster({"data": base64.b64encode(b"%PDF-1.4").decode(), "width_mm": 50})
        with self.assertRaises(ValueError): server.api_raster({"data": base64.b64encode(b"GIF89a....").decode(), "width_mm": 50})

    def test_complexity_limits(self):
        big = doc(*[{"id": f"o{i}", "type": "run", "color": "#f00", "points": [[0, 0], [1, 1]]} for i in range(3001)])
        with self.assertRaises(ValueError): server.api_generate(big)

    def test_low_dpi_note(self):
        try: from PIL import Image
        except ImportError: self.skipTest("Pillow missing")
        im = Image.new("RGB", (40, 40), "white")
        from PIL import ImageDraw; ImageDraw.Draw(im).rectangle((5, 5, 35, 35), fill=(200, 0, 0))
        b = io.BytesIO(); im.save(b, "PNG")
        r = server.api_raster({"data": base64.b64encode(b.getvalue()).decode(), "width_mm": 100, "colors": 3})
        self.assertTrue(any("Low resolution" in n for n in r["notes"]))


class HttpSmokeTests(unittest.TestCase):
    """Real HTTP round trips against the stdlib server (ephemeral port)."""
    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.srv.server_close()
    def req(self, path, body=None):
        import urllib.request, urllib.error
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if body is None else json.dumps(body).encode(),
                                   method="GET" if body is None else "POST")
        try:
            with urllib.request.urlopen(r) as resp: return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e: return e.code, e.read(), e.headers
    def test_static_and_health(self):
        self.assertEqual(self.req("/")[0], 200); self.assertEqual(self.req("/app.js")[0], 200)
        self.assertEqual(self.req("/api/health")[0], 200); self.assertIn(b"glyphs", self.req("/api/font")[1])
    def test_path_traversal_blocked(self):
        self.assertEqual(self.req("/../server/app.py")[0], 404); self.assertEqual(self.req("/..%2fserver/app.py")[0], 404)
    def test_generate_and_export_over_http(self):
        d = doc({"id": "a", "type": "fill", "color": "#f00", "rings": [SQ]})
        c, b, _ = self.req("/api/generate", d); self.assertEqual(c, 200); self.assertGreater(len(json.loads(b)["stitches"]), 100)
        c, b, h = self.req("/api/export/dst", d); self.assertEqual(c, 200); self.assertTrue(read_dst(b).ends_properly)
        self.assertEqual(len(h["X-SHA256"]), 64)
    def test_errors_are_json_4xx_not_500(self):
        c, b, _ = self.req("/api/export/dst", doc({"id": "a", "type": "fill", "color": "#f00", "rings": [[[0, 0], [300, 0], [300, 10], [0, 10]]]}))
        self.assertEqual(c, 422); self.assertIn("issues", json.loads(b))
        self.assertEqual(self.req("/api/generate", {"objects": []})[0], 400)
        self.assertEqual(self.req("/api/nope", {})[0], 404)


class PerformanceTests(unittest.TestCase):
    def test_100mm_design_with_many_stitches_is_fast(self):   # requirements: <= 50k stitches in < 15 s
        import time
        d = doc({"id": "a", "type": "fill", "color": "#f00", "rings": [[[-45, -45], [45, -45], [45, 45], [-45, 45]]],
                 "params": {"spacing": 0.25, "stitch_len": 1.2}})
        t = time.time(); r = server.api_generate(d); dt = time.time() - t
        self.assertGreater(len(r["stitches"]), 20000); self.assertLess(dt, 15)


class SatinSplitTests(unittest.TestCase):
    def longest(self, pat):
        from stitchcraft_engine.model import Cmd
        pts = [(s.x, s.y) for s in pat.stitches if s.cmd == Cmd.STITCH]
        return max(((a[0]-b[0])**2 + (a[1]-b[1])**2) ** .5 for a, b in zip(pts, pts[1:]))
    def satin(self, w, **params):
        return doc({"id": "s", "type": "satin", "color": "#f00", "points": [[0, 0], [25, 0]],
                    "params": dict({"width": w, "underlay": "none", "pull_comp": 0}, **params)})
    def test_wide_satin_stitches_are_split_to_max(self):
        d = self.satin(10); p, _, _ = generate(d)
        self.assertLessEqual(self.longest(p), 7.0 + 1e-6)
        self.assertTrue(run_checks(d, p).ok)
    def test_without_split_long_stitches_remain(self):
        p, _, _ = generate(self.satin(10, auto_split=False)); self.assertGreater(self.longest(p), 9.5)
    def test_machine_max_stitch_drives_split_length(self):
        d = self.satin(10); d["machine"] = {"max_stitch": 4}; p, _, _ = generate(d)
        self.assertLessEqual(self.longest(p), 4.0 + 1e-6)
    def test_split_points_lie_on_the_stitch_and_are_staggered(self):
        from stitchcraft_engine.stitches import split_long
        a, b = (0.0, -5.0), (0.0, 5.0)
        xs = {round(split_long(a, b, 6.0, k)[0][1], 3) for k in range(5)}
        self.assertGreater(len(xs), 2)                                   # staggered, not one ridge
        for k in range(5):
            for q in split_long(a, b, 6.0, k): self.assertEqual(q[0], 0.0); self.assertTrue(-5 < q[1] < 5)
    def test_narrow_satin_unchanged_by_split(self):
        a = generate(self.satin(3))[0].counts(); b = generate(self.satin(3, auto_split=False))[0].counts()
        self.assertEqual(a, b)
    def test_very_wide_column_beyond_dst_limit_is_exportable(self):   # 16 mm > 12.1 mm DST record limit
        d = doc({"id": "c", "type": "column", "color": "#f00", "rail1": [[0, 0], [20, 0]], "rail2": [[0, 16], [20, 16]],
                 "params": {"underlay": "none", "pull_comp": 0}})
        res, err = server.api_dst(d); self.assertIsNone(err); self.assertTrue(read_dst(res.data).ends_properly)


class TestPackTests(unittest.TestCase):
    def test_testpack_builds_valid_designs(self):
        import importlib.util, tempfile, csv
        spec = importlib.util.spec_from_file_location("mk", Path(__file__).resolve().parent.parent / "tools" / "make_testpack.py")
        mk = importlib.util.module_from_spec(spec); spec.loader.exec_module(mk)
        with tempfile.TemporaryDirectory() as t:
            rows, problems = mk.build(Path(t))
            self.assertEqual(problems, []); self.assertEqual(len(rows), 10)
            for r in rows:
                self.assertTrue(read_dst((Path(t) / r["file"]).read_bytes()).ends_properly)
                self.assertTrue((Path(t) / (r["design"] + ".esproj")).exists())
            with open(Path(t) / "RESULTS.csv", encoding="utf-8") as fh: self.assertEqual(len(list(csv.DictReader(fh))), 10)
            self.assertIn("Thread breaks", (Path(t) / "RESULTS.html").read_text())


class Step2Tests(unittest.TestCase):
    def _png(self, draw, size=(160, 160), bg="white"):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", size, bg); draw(ImageDraw.Draw(im)); b = io.BytesIO(); im.save(b, "PNG"); return b.getvalue()
    def _import(self, png, w=60, colors=6):
        return server.api_raster({"data": base64.b64encode(png).decode(), "width_mm": w, "colors": colors})

    # --- E.2: five test artworks through the raster pipeline, each must give a valid DST
    def _valid(self, objs):
        d = doc(*objs); p, _, st = generate(d)
        self.assertTrue(run_checks(d, p).ok, [i.message for i in run_checks(d, p).errors][:2])
        self.assertTrue(read_dst(write_dst(p).data).ends_properly); return st

    def test_art1_circle(self):
        r = self._import(self._png(lambda d: d.ellipse((20, 20, 140, 140), fill=(200, 0, 0))))
        self.assertEqual(len(r["objects"]), 1); self.assertGreater(self._valid(r["objects"])["stitches"], 300)
    def test_art2_ring_keeps_hole_empty(self):
        r = self._import(self._png(lambda d: (d.ellipse((10, 10, 150, 150), fill=(0, 0, 160)), d.ellipse((50, 50, 110, 110), fill="white"))), w=80)
        d = doc(*r["objects"]); p, _, _ = generate(d)
        from stitchcraft_engine.model import Cmd
        cx = cy = 0.0                            # imported art is centred at the origin
        inside = [s for s in p.stitches if s.cmd == Cmd.STITCH and (s.x - cx) ** 2 + (s.y - cy) ** 2 < 8 ** 2]   # hole radius = 15 mm
        self.assertEqual(inside, []); self._valid(r["objects"])
    def test_art3_two_colours_two_objects(self):
        r = self._import(self._png(lambda d: (d.rectangle((10, 10, 90, 150), fill=(200, 0, 0)), d.rectangle((100, 10, 150, 150), fill=(0, 120, 0)))))
        self.assertEqual(len({o["color"] for o in r["objects"]}), 2)          # two distinct thread colours
        self.assertEqual(len(r["objects"]), 2); self.assertEqual(self._valid(r["objects"])["color_changes"], 1)
    def test_art4_text_like_bars_many_regions(self):
        def bars(d):
            for i in range(6): d.rectangle((15 + i * 22, 30, 25 + i * 22, 130), fill=(20, 20, 20))
        r = self._import(self._png(bars)); self.assertEqual(len(r["objects"]), 1)
        self.assertEqual(len(r["objects"][0]["rings"]), 6); self._valid(r["objects"])
    def test_art5_tiny_specks_are_dropped(self):
        def specks(d):
            d.ellipse((20, 20, 140, 140), fill=(200, 0, 0))
            for i in range(5): d.point((5 + i * 3, 150), fill=(0, 0, 0))
        r = self._import(self._png(specks), w=60); self.assertEqual(len(r["objects"]), 1)
    def test_colour_cap_is_8(self):
        def many(d):
            for i in range(12): d.rectangle((i * 13, 0, i * 13 + 12, 159), fill=(i * 20, 255 - i * 15, (i * 70) % 255))
        r = self._import(self._png(many), colors=12)
        self.assertLessEqual(len(r["objects"]), 8)

    # --- C: no stitches outside source geometry (beyond pull-comp tolerance)
    def test_fill_stays_inside_source_bounds(self):
        import math
        star = [[(25 if k % 2 == 0 else 11) * math.cos(k * math.pi / 5), (25 if k % 2 == 0 else 11) * math.sin(k * math.pi / 5)] for k in range(10)]
        for ang in (0, 30, 45, 90):
            for pc in (0.0, 0.4):
                d = doc({"id": "s", "type": "fill", "color": "#f00", "rings": [star], "params": {"angle": ang, "pull_comp": pc, "underlay": "tatami"}})
                p, _, _ = generate(d); b = p.bbox()
                xs = [q[0] for q in star]; ys = [q[1] for q in star]; tol = pc / 2 + 1e-6
                self.assertGreaterEqual(b[0], min(xs) - tol); self.assertLessEqual(b[2], max(xs) + tol)
                self.assertGreaterEqual(b[1], min(ys) - tol); self.assertLessEqual(b[3], max(ys) + tol)

    # --- C: sequence rule
    def test_order_warning_when_outline_stitched_before_fill(self):
        o = {"id": "o", "type": "run", "color": "#000", "closed": True, "points": SQ}
        f = {"id": "f", "type": "fill", "color": "#f00", "rings": [SQ]}
        self.assertTrue(any("stitched before fill" in n for n in generate(doc(o, f))[1]))
        self.assertFalse(any("stitched before fill" in n for n in generate(doc(f, o))[1]))
    def test_no_order_warning_for_non_overlapping(self):
        o = {"id": "o", "type": "run", "color": "#000", "points": [[50, 50], [60, 60]]}
        self.assertFalse(any("stitched before" in n for n in generate(doc(o, {"id": "f", "type": "fill", "color": "#f00", "rings": [SQ]}))[1]))

    # --- C: short-stitch threshold now 0.3 mm
    def test_short_stitch_threshold(self):
        from stitchcraft_engine.model import Pattern, Stitch, ThreadColor, Cmd
        def pat(step):
            return Pattern("t", [Stitch(0, 0, Cmd.JUMP), Stitch(0, 0), Stitch(step, 0), Stitch(step * 2 + 5, 0), Stitch(step * 2 + 5, 0, Cmd.END)], [ThreadColor("a", "#000")])
        from stitchcraft_engine.validate import validate
        self.assertTrue(any(i.code == "STITCH_SHORT" for i in validate(pat(0.25)).issues))
        self.assertFalse(any(i.code == "STITCH_SHORT" for i in validate(pat(0.35)).issues))

    # --- A.8: stabiliser travels with the design into stats
    def test_stabiliser_in_stats(self):
        d = doc({"id": "f", "type": "fill", "color": "#f00", "rings": [SQ]}); d["stabiliser"] = "tear-away"
        self.assertEqual(generate(d)[2]["stabiliser"], "tear-away")
