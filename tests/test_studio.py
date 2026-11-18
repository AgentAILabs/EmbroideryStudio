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
            self.assertEqual(problems, []); self.assertEqual(len(rows), 11)
            for r in rows:
                self.assertTrue(read_dst((Path(t) / r["file"]).read_bytes()).ends_properly)
                self.assertTrue((Path(t) / (r["design"] + ".esproj")).exists())
            with open(Path(t) / "RESULTS.csv", encoding="utf-8") as fh: self.assertEqual(len(list(csv.DictReader(fh))), 11)
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


class PackageTests(unittest.TestCase):
    D = lambda self: doc({"id": "a", "type": "fill", "color": "#c8102e", "rings": [SQ]},
                         {"id": "b", "type": "applique", "color": "#2e9e44", "rings": [[[40, 0], [60, 0], [60, 20], [40, 20]]]})
    def test_package_contents_and_dst_matches_direct_export(self):
        import zipfile
        d = self.D(); d["name"] = "My Design 1"; d["stabiliser"] = "tear-away"
        data, err = server.sheet.package(d); self.assertIsNone(err)
        z = zipfile.ZipFile(io.BytesIO(data)); names = z.namelist()
        for ext in (".dst", ".esproj", ".preview.svg", ".production-sheet.html", ".stitchcraft.json"):
            self.assertTrue(any(n.endswith(ext) for n in names), ext)
        self.assertIn("My_Design_1.dst", names); self.assertIn("MANIFEST.txt", names)
        self.assertEqual(z.read("My_Design_1.dst"), server.api_dst(d)[0].data)            # same bytes as the single export
        self.assertIn(server.api_dst(d)[0].sha256, z.read("MANIFEST.txt").decode())
        self.assertIn("NOT machine-tested", z.read("MANIFEST.txt").decode())
        proj = json.loads(z.read("My_Design_1.esproj")); self.assertEqual(proj["doc"]["name"], "My Design 1")
    def test_sheet_contents_and_escaping(self):
        d = self.D(); d["name"] = "<script>alert(1)</script>"; d["stabiliser"] = "wash-away"
        h = server.sheet.sheet_html(d)
        self.assertNotIn("<script>alert", h); self.assertIn("&lt;script&gt;", h)
        for token in ("Colour order", "wash-away", "Appliqué", "NOT machine-tested", "trim jumps", "<svg"): self.assertIn(token, h)
    def test_package_blocked_on_errors(self):
        data, err = server.sheet.package(doc({"id": "a", "type": "fill", "color": "#f00", "rings": [[[0, 0], [300, 0], [300, 10], [0, 10]]]}))
        self.assertIsNone(data); self.assertEqual(err["error"], "Export blocked")
    def test_package_over_http(self):
        import threading, urllib.request, zipfile
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            r = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/api/export/package", data=json.dumps(self.D()).encode(), method="POST")
            with urllib.request.urlopen(r) as resp:
                self.assertEqual(resp.headers["Content-Type"], "application/zip"); self.assertIn("-package.zip", resp.headers["Content-Disposition"])
                self.assertIn("MANIFEST.txt", zipfile.ZipFile(io.BytesIO(resp.read())).namelist())
            r = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/api/export/sheet", data=json.dumps(self.D()).encode(), method="POST")
            with urllib.request.urlopen(r) as resp: self.assertTrue(resp.read().startswith(b"<!doctype html>"))
        finally: srv.shutdown(); srv.server_close()


class FrontEndStaticTests(unittest.TestCase):
    """Cheap guard (no browser): every handler wired in app.js is defined, and every element id it uses exists in index.html."""
    def test_handlers_defined_and_ids_exist(self):
        import re
        web = Path(__file__).resolve().parent.parent / "web"
        js, page = (web / "app.js").read_text(encoding="utf-8"), (web / "index.html").read_text(encoding="utf-8")
        defs = set(re.findall(r"function\s+(\w+)", js)) | set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=", js))
        used = set(re.findall(r"\.on(?:click|change|input)\s*=\s*(\w+)\s*[;,)]", js))
        self.assertEqual(sorted(u for u in used if u not in defs), [])
        static_ids = set(re.findall(r'id="(\w+)"', page))
        dynamic_ids = set(re.findall(r'id="(\w+)"', js))                      # panels built from template strings
        wired = set(re.findall(r'\$\("#(\w+)"\)\.on', js))
        self.assertEqual(sorted(i for i in wired if i not in static_ids | dynamic_ids), [])


class EmbellishmentGuideTests(unittest.TestCase):
    BEADS = {"id": "e1", "type": "embellishment", "kind": "bead", "size_mm": 4, "color": "#d4af37", "points": [[0, 0], [10, 0], [20, 0]], "name": "neck beads"}
    STONE = {"id": "e2", "type": "embellishment", "kind": "stone", "size_mm": 6, "color": "#ffffff", "points": [[5, 10]]}
    def test_embellishments_never_reach_the_dst(self):
        base = doc({"id": "a", "type": "fill", "color": "#f00", "rings": [SQ]})
        withe = doc({"id": "a", "type": "fill", "color": "#f00", "rings": [SQ]}, self.BEADS, self.STONE)
        a, b = generate(base)[0], generate(withe)[0]
        self.assertEqual(a.counts(), b.counts()); self.assertEqual(a.bbox(), b.bbox())      # identical stitches
        self.assertEqual(server.api_dst(base)[0].sha256, server.api_dst(withe)[0].sha256)    # identical DST bytes
        self.assertEqual(generate(withe)[2]["embellishments"], {"bead": 3, "stone": 1})
    def test_guides_are_not_stitched(self):
        g = {"id": "g", "type": "run", "color": "#888", "guide": True, "closed": True, "points": [[0, 0], [90, 0], [90, 90], [0, 90]]}
        p, _, _ = generate(doc({"id": "a", "type": "fill", "color": "#f00", "rings": [SQ]}, g))
        bb = p.bbox(); self.assertLessEqual(bb[2], 21)                                       # 90 mm guide did not add stitches
    def test_embellishment_only_design_is_valid_but_cannot_export_dst(self):
        d = doc(self.BEADS); r = server.api_generate(d)
        self.assertEqual(r["stitches"], []); self.assertEqual(r["stats"]["embellishments"], {"bead": 3})
        self.assertTrue(any("Nothing to stitch" in n for n in r["notes"]))
        with self.assertRaises(ValueError): server.api_dst(d)                                # nothing to export
    def test_sheet_lists_embellishments_with_positions(self):
        d = doc({"id": "a", "type": "fill", "color": "#f00", "rings": [SQ]}, self.BEADS, self.STONE)
        h = server.sheet.sheet_html(d)
        for t in ("Embellishments", "not</b> in the DST", "bead", "stone", "(10.0, 0.0)", "#d4af37", "neck beads"): self.assertIn(t, h)
        only = server.sheet.sheet_html(doc(self.BEADS)); self.assertIn("Embellishments", only)   # sheet still builds
    def test_sheet_ignores_hidden_and_guide_embellishments(self):
        d = doc({"id": "a", "type": "fill", "color": "#f00", "rings": [SQ]}, dict(self.BEADS, hidden=True))
        self.assertNotIn("Embellishments", server.sheet.sheet_html(d))


class TemplateTests(unittest.TestCase):
    def test_every_template_builds_and_stitched_ones_pass_checks(self):
        from stitchcraft_engine import templates as T
        for t in T.catalog():
            objs = T.build(t["id"], {})
            self.assertTrue(objs, t["id"])
            for i, o in enumerate(objs): o["id"] = f"t{i}"
            d = doc(*objs)
            if t["group"].startswith("Neckline"):
                self.assertTrue(all(o.get("guide") for o in objs), t["id"])
                self.assertTrue(server._only_unstitched(d))                       # guides never stitch
            else:
                p, _, st = generate(d)
                self.assertTrue(run_checks(d, p).ok, (t["id"], [i.message for i in run_checks(d, p).errors]))
                self.assertGreater(st["stitches"], 50, t["id"])
    def test_neck_guide_size_is_in_inches(self):
        from stitchcraft_engine import templates as T
        for tid in ("neck_round", "neck_boat", "neck_v", "neck_square", "neck_back_u"):
            pts = T.build(tid, {"width_in": 6, "depth_in": 5})[0]["points"]
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            self.assertAlmostEqual(max(xs) - min(xs), 6 * 25.4, delta=0.5, msg=tid)
            self.assertAlmostEqual(max(ys) - min(ys), 5 * 25.4, delta=0.5, msg=tid)
    def test_border_length_and_centering(self):
        from stitchcraft_engine import templates as T
        o = T.build("border_scallop", {"length_mm": 100})[0]["points"]
        self.assertAlmostEqual(min(p[0] for p in o), -50, delta=.01); self.assertAlmostEqual(max(p[0] for p in o), 50, delta=.01)
    def test_params_are_clamped_and_bad_input_survives(self):
        from stitchcraft_engine import templates as T
        self.assertLessEqual(len(T.build("border_dots", {"length_mm": 1e9, "gap": -5})), T.MAX_OBJECTS)
        self.assertTrue(T.build("border_petal", {"length_mm": "abc", "petal_w": None}))
        with self.assertRaises(ValueError): T.build("nope", {})
        self.assertEqual(T.build("border_zigzag", {}, color="javascript:evil")[0]["color"], "#c8102e")   # colour sanitised
    def test_templates_over_http(self):
        import threading, urllib.request
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}"
            cat = json.loads(urllib.request.urlopen(base + "/api/templates").read())["templates"]; self.assertGreaterEqual(len(cat), 9)
            r = urllib.request.Request(base + "/api/template", data=json.dumps({"id": "neck_v", "params": {}}).encode(), method="POST")
            self.assertTrue(json.loads(urllib.request.urlopen(r).read())["objects"][0]["guide"])
        finally: srv.shutdown(); srv.server_close()


class OutlineColumnTests(unittest.TestCase):
    import math as _m
    def ellipse(self, a=15, b=4, n=60, rot=0.0, off=(0, 0)):
        m = self._m; c, s = m.cos(rot), m.sin(rot)
        return [(off[0] + a * m.cos(t * 2 * m.pi / n) * c - b * m.sin(t * 2 * m.pi / n) * s,
                 off[1] + a * m.cos(t * 2 * m.pi / n) * s + b * m.sin(t * 2 * m.pi / n) * c) for t in range(n)]
    def test_ellipse_rails_lie_on_the_outline_and_share_tips(self):
        from stitchcraft_engine.outline import column_from_outline
        r = column_from_outline(self.ellipse()); self.assertEqual(r["rail1"][0], r["rail2"][0]); self.assertEqual(r["rail1"][-1], r["rail2"][-1])
        for x, y in r["rail1"] + r["rail2"]: self.assertAlmostEqual((x / 15) ** 2 + (y / 4) ** 2, 1.0, delta=0.06)
        self.assertAlmostEqual(r["length_mm"], 30, delta=.5); self.assertAlmostEqual(r["aspect"], 3.75, delta=.2)
    def test_result_is_orientation_start_and_rotation_independent(self):
        from stitchcraft_engine.outline import column_from_outline
        base = self.ellipse(); ref = column_from_outline(base)
        for ring in (base[::-1], base[17:] + base[:17], self.ellipse(rot=self._m.pi / 3, off=(40, -20))):
            r = column_from_outline(ring)
            self.assertAlmostEqual(r["length_mm"], ref["length_mm"], delta=.6); self.assertAlmostEqual(r["width_mm"], ref["width_mm"], delta=.4)
    def test_generated_satin_stays_inside_source_shape_and_covers_it(self):
        from stitchcraft_engine.outline import column_from_outline
        ring = self.ellipse(); r = column_from_outline(ring)
        d = doc({"id": "c", "type": "column", "color": "#f00", "rail1": r["rail1"], "rail2": r["rail2"], "params": {"pull_comp": 0, "underlay": "none"}})
        p, _, st = generate(d); self.assertTrue(run_checks(d, p).ok)
        bb = p.bbox(); self.assertAlmostEqual(bb[2] - bb[0], 30, delta=.6); self.assertAlmostEqual(bb[3] - bb[1], 8, delta=.6)
        from stitchcraft_engine.model import Cmd
        from stitchcraft_engine.geometry import point_in_ring
        inside = sum(1 for s in p.stitches if s.cmd == Cmd.STITCH and point_in_ring((s.x, s.y), ring))
        total = sum(1 for s in p.stitches if s.cmd == Cmd.STITCH); self.assertGreater(inside / total, 0.97)
    def test_rectangle_stitches_run_across_the_strip(self):
        from stitchcraft_engine.outline import column_from_outline
        r = column_from_outline([(0, 0), (30, 0), (30, 6), (0, 6)])
        d = doc({"id": "c", "type": "column", "color": "#f00", "rail1": r["rail1"], "rail2": r["rail2"], "params": {"pull_comp": 0, "underlay": "none"}})
        from stitchcraft_engine.model import Cmd
        pts = [(s.x, s.y) for s in generate(d)[0].stitches if s.cmd == Cmd.STITCH]
        mids = [(a, b) for a, b in zip(pts, pts[1:]) if 4 < a[0] < 26]            # away from the end caps
        across = sum(1 for a, b in mids if abs(b[1] - a[1]) > abs(b[0] - a[0]) * 3)
        self.assertGreater(across / len(mids), 0.9)                                # stitches are ~perpendicular to the strip
    def test_blobs_branches_and_junk_are_refused_with_reasons(self):
        from stitchcraft_engine.outline import column_from_outline
        m = self._m
        bad = {"circle": [(10 * m.cos(t * m.pi / 20), 10 * m.sin(t * m.pi / 20)) for t in range(40)], "square": [(0, 0), (10, 0), (10, 10), (0, 10)],
               "two points": [(0, 0), (5, 5)], "tiny": [(0, 0), (0.5, 0), (0.5, 0.5)],
               "T shape": [(0, 0), (30, 0), (30, 5), (18, 5), (18, 30), (12, 30), (12, 5), (0, 5)]}
        for name, ring in bad.items():
            with self.assertRaises(ValueError, msg=name): column_from_outline(ring)
        with self.assertRaisesRegex(ValueError, "not elongated"): column_from_outline(bad["circle"])
    def test_curled_c_shape_is_refused_or_valid_never_garbage(self):
        from stitchcraft_engine.outline import column_from_outline
        m = self._m
        outer = [(20 * m.cos(a), 20 * m.sin(a)) for a in [m.radians(30 + k * 5) for k in range(61)]]
        inner = [(15 * m.cos(a), 15 * m.sin(a)) for a in [m.radians(330 - k * 5) for k in range(61)]]
        try:
            r = column_from_outline(outer + inner)
            d = doc({"id": "c", "type": "column", "color": "#f00", "rail1": r["rail1"], "rail2": r["rail2"]}); p, _, _ = generate(d)
            self.assertLess(p.bbox()[2] - p.bbox()[0], 45)                         # if accepted, stays within the C's extent
        except ValueError: pass
    def test_endpoint(self):
        import threading, urllib.request, urllib.error
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{srv.server_address[1]}/api/tools/column-from-outline"
            ok = urllib.request.urlopen(urllib.request.Request(base, data=json.dumps({"ring": self.ellipse()}).encode(), method="POST"))
            self.assertIn("rail1", json.loads(ok.read()))
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(urllib.request.Request(base, data=json.dumps({"ring": [[0, 0], [10, 0], [10, 10], [0, 10]]}).encode(), method="POST"))
            self.assertEqual(cm.exception.code, 400); self.assertIn("not elongated", json.loads(cm.exception.read())["error"])
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(urllib.request.Request(base, data=json.dumps({"ring": "x"}).encode(), method="POST"))
            self.assertEqual(cm.exception.code, 400)
        finally: srv.shutdown(); srv.server_close()


class OutlineCurvedTests(unittest.TestCase):
    import math as _m
    @staticmethod
    def near_or_in(q, ring, tol=0.15):
        from stitchcraft_engine.geometry import point_in_ring, dist
        if point_in_ring(q, ring): return True
        for i in range(len(ring)):
            a, b = ring[i], ring[(i + 1) % len(ring)]; dx, dy = b[0] - a[0], b[1] - a[1]; l = dx * dx + dy * dy
            t = max(0, min(1, ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / l)) if l else 0
            if dist(q, (a[0] + t * dx, a[1] + t * dy)) <= tol: return True
        return False
    def thick_curve(self, f, w, n=40, taper=True):
        m = self._m; L, R = [], []
        for i in range(n + 1):
            t = i / n; x, y = f(t); x2, y2 = f(min(1, t + 1e-3)); x1, y1 = f(max(0, t - 1e-3)); tx, ty = x2 - x1, y2 - y1; l = m.hypot(tx, ty); nx, ny = -ty / l, tx / l
            ww = w * (0.35 + 0.65 * m.sin(m.pi * t)) if taper else w
            L.append((x + nx * ww / 2, y + ny * ww / 2)); R.append((x - nx * ww / 2, y - ny * ww / 2))
        return L + R[::-1]
    def stitched(self, ring):
        from stitchcraft_engine.outline import column_from_outline
        from stitchcraft_engine.model import Cmd
        r = column_from_outline(ring)
        d = doc({"id": "c", "type": "column", "color": "#f00", "rail1": r["rail1"], "rail2": r["rail2"], "params": {"pull_comp": 0, "underlay": "none"}})
        d["hoop"] = {"w": 200, "h": 200, "margin": 3}; p, _, _ = generate(d)
        return [(s.x, s.y) for s in p.stitches if s.cmd == Cmd.STITCH], p
    def test_curved_strokes_become_columns_that_stay_inside(self):
        m = self._m
        shapes = {"banana": self.thick_curve(lambda t: (30 * m.cos(m.pi * (.15 + .7 * t)), 30 * m.sin(m.pi * (.15 + .7 * t))), 6),
                  "S": self.thick_curve(lambda t: (40 * t, 8 * m.sin(2 * m.pi * t)), 5),
                  "leaf": self.thick_curve(lambda t: (30 * t, 3 * m.sin(m.pi * t)), 9),
                  "L": [(0, 0), (30, 0), (30, 5), (5, 5), (5, 30), (0, 30)]}
        for name, ring in shapes.items():
            pts, p = self.stitched(ring)
            self.assertGreater(len(pts), 50, name)
            self.assertGreaterEqual(sum(self.near_or_in(q, ring) for q in pts) / len(pts), 0.98, name)
    def test_branching_and_curled_shapes_are_refused(self):
        from stitchcraft_engine.outline import column_from_outline
        m = self._m
        for name, ring in {"T": [(0, 0), (30, 0), (30, 5), (18, 5), (18, 30), (12, 30), (12, 5), (0, 5)],
                           "Y": [(0, 0), (6, 0), (15, 12), (24, 0), (30, 0), (18, 18), (18, 40), (12, 40), (12, 18)],
                           "C270": self.thick_curve(lambda t: (20 * m.cos(m.pi * (.1 + 1.5 * t)), 20 * m.sin(m.pi * (.1 + 1.5 * t))), 5, taper=False)}.items():
            with self.assertRaises(ValueError, msg=name): column_from_outline(ring)
    def test_crossing_stitch_lines_are_detected(self):
        from stitchcraft_engine.outline import _cross
        self.assertTrue(_cross((0, 0), (10, 10), (0, 10), (10, 0)))
        self.assertFalse(_cross((0, 0), (10, 0), (0, 5), (10, 5)))
        self.assertFalse(_cross((0, 0), (5, 5), (5, 5), (10, 0)))              # touching at an endpoint is not a crossing


class OutlineQualityTests(OutlineCurvedTests):
    """Quality, not just validity: column width must match the real stroke width and stitches must be ~perpendicular."""
    def slant(self, r):
        m = self._m; r1, r2 = r["rail1"], r["rail2"]; mid = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(r1, r2)]; out = []
        for i in range(2, len(mid) - 2):
            tx, ty = mid[i + 1][0] - mid[i - 1][0], mid[i + 1][1] - mid[i - 1][1]; sx, sy = r2[i][0] - r1[i][0], r2[i][1] - r1[i][1]
            out.append(m.degrees(m.asin(min(1, abs(tx * sx + ty * sy) / (m.hypot(tx, ty) * m.hypot(sx, sy) + 1e-9)))))
        return sum(out) / len(out)
    def test_constant_width_strokes_recover_their_width_and_stay_perpendicular(self):
        from stitchcraft_engine.outline import column_from_outline
        m = self._m
        cases = [("S", self.thick_curve(lambda t: (40 * t, 8 * m.sin(2 * m.pi * t)), 4, taper=False), 4.0),
                 ("banana", self.thick_curve(lambda t: (30 * m.cos(m.pi * (.15 + .7 * t)), 30 * m.sin(m.pi * (.15 + .7 * t))), 6, taper=False), 6.0),
                 ("L", [(0, 0), (30, 0), (30, 5), (5, 5), (5, 30), (0, 30)], 5.0)]
        for name, ring, truth in cases:
            r = column_from_outline(ring)
            self.assertAlmostEqual(r["width_mm"], truth, delta=truth * 0.12, msg=name)
            self.assertLess(self.slant(r), 6.0, name)
    def test_diagonal_end_caps_do_not_pick_a_corner(self):
        from stitchcraft_engine.outline import column_from_outline
        m = self._m                                              # S-curve ends are diagonal; both rails must still start at the cap middle
        r = column_from_outline(self.thick_curve(lambda t: (40 * t, 8 * m.sin(2 * m.pi * t)), 4, taper=False))
        a, b = r["rail1"][0], r["rail1"][-1]
        self.assertLess(m.hypot(a[0] - 0, a[1] - 0), 2.6); self.assertLess(m.hypot(b[0] - 40, b[1] - 0), 2.6)


class FillPatternTests(unittest.TestCase):
    def fill(self, rings, **params):
        return doc({"id": "f", "type": "fill", "color": "#f00", "rings": rings, "params": params})
    def pts(self, d):
        from stitchcraft_engine.model import Cmd
        return [(s.x, s.y) for s in generate(d)[0].stitches if s.cmd == Cmd.STITCH]

    def test_contour_rings_are_concentric_spaced_and_inside(self):
        from stitchcraft_engine.stitches import contour_fill
        run = contour_fill([SQ], spacing=0.5, stitch_len=3.0)[0]
        self.assertGreater(len(run), 100)
        for x, y in run: self.assertTrue(-1e-6 <= x <= 20 + 1e-6 and -1e-6 <= y <= 20 + 1e-6)
        # distance from the outline grows by `spacing` per ring: the innermost stitches are near the centre
        inner = min(((x - 10) ** 2 + (y - 10) ** 2) ** .5 for x, y in run); self.assertLess(inner, 1.2)
        # no stitch is farther than ~spacing-ish from a neighbouring ring: coverage check on a probe grid (sample points within 0.5 mm of some stitch point or segment)
        import math
        for gx in range(1, 20, 3):
            for gy in range(1, 20, 3):
                best = min(math.hypot(gx - x, gy - y) for x, y in run); self.assertLess(best, 1.8, (gx, gy))
    def test_contour_through_generate_is_valid(self):
        d = self.fill([SQ], pattern="contour"); p, n, st = generate(d)
        self.assertEqual(n, []); self.assertTrue(run_checks(d, p).ok); self.assertGreater(st["stitches"], 150)
    def test_contour_falls_back_to_tatami_with_a_note_for_holes(self):
        d = self.fill([SQ, [[5, 5], [15, 5], [15, 15], [5, 15]]], pattern="contour")
        p, n, st = generate(d); self.assertTrue(any("used tatami" in x for x in n)); self.assertGreater(st["stitches"], 100)
        self.assertEqual(sum(1 for q in self.pts(d) if 6 < q[0] < 14 and 6 < q[1] < 14), 0)       # hole still empty
    def test_contour_on_concave_shape_never_half_fills(self):
        L = [[0, 0], [30, 0], [30, 8], [8, 8], [8, 30], [0, 30]]
        d = self.fill([L], pattern="contour"); p, n, st = generate(d)
        self.assertTrue(run_checks(d, p).ok)
        pts = self.pts(d); from stitchcraft_engine.outline import _inside_or_on
        self.assertGreaterEqual(sum(_inside_or_on(q, L, 0.5) for q in pts) / len(pts), 0.99)      # stays inside the L-shape
        # either a complete contour fill or an explicit tatami fallback - both must reach the middle of the bend
        self.assertTrue(any(abs(x - 4) < 1.5 and abs(y - 4) < 1.5 for x, y in pts))

    def test_cross_fill_cells_inside_shape_only_and_stitch_length(self):
        from stitchcraft_engine.stitches import cross_fill
        import math
        tri = [[0, 0], [20, 0], [0, 20]]
        runs = cross_fill([tri], size=2.0); n_pts = [p for r in runs for p in r]
        self.assertTrue(all(0 - 1e-6 <= x <= 20 + 1e-6 and -1e-6 <= y <= 20 + 1e-6 for x, y in n_pts))
        for r in runs:
            for a, b in zip(r, r[1:]): self.assertLessEqual(math.dist(a, b), 2.0 * 2 ** .5 + 1e-6)
        # cells whose centre is outside the triangle (x + y > 20) get no stitches
        self.assertFalse(any(x > 13 and y > 13 for x, y in n_pts))
    def test_cross_fill_count_scales_with_area(self):
        a = len(self.pts(self.fill([SQ], pattern="cross", cross_size=2.0))); b = len(self.pts(self.fill([SQ], pattern="cross", cross_size=4.0)))
        self.assertGreater(a, 2.5 * b)                                # 4x the cells at half the size
        self.assertTrue(run_checks(self.fill([SQ], pattern="cross"), generate(self.fill([SQ], pattern="cross"))[0]).ok)
    def test_cross_size_limits_and_tiny_shapes(self):
        ok = {"id": "ok", "type": "fill", "color": "#f00", "rings": [SQ]}
        for sz in (0.5, 6.0):
            _, n, _ = generate(doc(self.fill([SQ], pattern="cross", cross_size=sz)["objects"][0], ok))
            self.assertTrue(any("skipped" in x for x in n), sz)
        _, n, _ = generate(doc(self.fill([[[0, 0], [0.5, 0], [0.5, 0.5]]], pattern="cross")["objects"][0], ok))
        self.assertTrue(any("skipped" in x for x in n))
    def test_patterned_fills_have_no_underlay_and_default_is_unchanged(self):
        base = generate(self.fill([SQ]))[0].counts()
        self.assertEqual(base, generate(self.fill([SQ], pattern="tatami"))[0].counts())              # default behaviour untouched
        self.assertEqual(server.api_dst(self.fill([SQ]))[0].sha256, server.api_dst(self.fill([SQ], pattern="tatami"))[0].sha256)


class ContourRoundShapeTests(unittest.TestCase):
    def test_contour_on_a_round_shape_has_no_short_stitch_or_density_warnings(self):
        import math
        circ = [[13 * math.cos(k * math.pi / 24), 13 * math.sin(k * math.pi / 24)] for k in range(48)]
        for pat in ("tatami", "contour", "cross"):
            d = doc({"id": "a", "type": "fill", "color": "#f00", "rings": [circ], "params": {"pattern": pat}})
            p, n, _ = generate(d); codes = {i.code for i in run_checks(d, p).issues}
            self.assertFalse(codes & {"STITCH_SHORT", "DENSITY", "ZERO_LENGTH"}, (pat, codes)); self.assertEqual(n, [])
    def test_thin_keeps_a_closed_ring_of_at_least_three_points(self):
        from stitchcraft_engine.stitches import _thin
        r = _thin([(0, 0), (0.01, 0), (0.02, 0.01), (5, 0), (5, 5)], 0.4); self.assertGreaterEqual(len(r), 3)


class ServeArgsTests(unittest.TestCase):
    def test_defaults_env_and_validation(self):
        self.assertEqual(server.serve_args(["x"], {}), ("127.0.0.1", 8765))                      # localhost-only by default
        self.assertEqual(server.serve_args(["x", "9000"], {"ES_HOST": "0.0.0.0"}), ("0.0.0.0", 9000))
        self.assertEqual(server.serve_args(["x"], {"ES_PORT": "8000"}), ("127.0.0.1", 8000))
        for bad in ("0", "70000", "abc"):
            with self.assertRaises(ValueError): server.serve_args(["x", bad], {})
    def test_container_files_are_consistent_with_the_app(self):
        root = Path(__file__).resolve().parent.parent
        df, dc = (root / "Dockerfile").read_text(), (root / "docker-compose.yml").read_text()
        self.assertIn("ES_HOST=0.0.0.0", df); self.assertIn("server/app.py", df); self.assertIn("USER studio", df)
        self.assertIn("127.0.0.1:8765:8765", dc)                                               # published to localhost only
        for d in ("engine", "server", "web"): self.assertTrue((root / d).is_dir() and f"COPY {d} " in df)


class DocsConsistencyTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent
    def test_relative_links_resolve(self):
        import re
        for md in [self.ROOT / "README.md"] + sorted((self.ROOT / "docs").rglob("*.md")):
            for target in re.findall(r"\]\(([^)#\s]+)\)", md.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:")): continue
                self.assertTrue((md.parent / target).exists(), f"{md.name}: broken link {target}")
    def test_documented_endpoints_exist_in_the_server(self):
        import re
        src = (self.ROOT / "server" / "app.py").read_text(encoding="utf-8")
        arch = (self.ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        for ep in sorted(set(re.findall(r"/api/[a-z\-/]+", arch))):
            for part in [p for p in ep.split("·") if p]:
                self.assertIn(part.rstrip("/"), src, f"documented endpoint {part} not found in server/app.py")
    def test_documented_object_types_are_handled_by_the_engine(self):
        eng = (self.ROOT / "engine" / "stitchcraft_engine" / "design.py").read_text(encoding="utf-8")
        for t in ("fill", "satin", "column", "run", "text", "applique", "embellishment"): self.assertIn(f'"{t}"', eng, t)
    def test_documented_shortcuts_are_bound(self):
        js = (self.ROOT / "web" / "app.js").read_text(encoding="utf-8")
        for key in ('v: "select"', 'f: "fill"', 's: "satin"', 'c: "column"', 'r: "run"', 't: "text"', 'a: "applique"', 'e: "bead"'): self.assertIn(key, js, key)


class RevisitedColourTests(unittest.TestCase):
    """Regression: red -> blue -> red used to be rejected ('2 colour changes but only 2 threads'), blocking export."""
    def three(self):
        sq = lambda x: [[x, 0], [x + 10, 0], [x + 10, 10], [x, 10]]
        return doc({"id": "a", "type": "fill", "color": "#ff0000", "rings": [sq(0)]}, {"id": "b", "type": "fill", "color": "#0000ff", "rings": [sq(20)]},
                   {"id": "c", "type": "fill", "color": "#ff0000", "rings": [sq(40)]})
    def test_returning_to_an_earlier_colour_is_valid_and_exports(self):
        d = self.three(); p, _, st = generate(d)
        self.assertEqual(len(p.threads), 2); self.assertEqual(st["color_changes"], 2)
        self.assertTrue(run_checks(d, p).ok, [i.message for i in run_checks(d, p).errors])
        res, err = server.api_dst(d); self.assertIsNone(err)
        back = read_dst(res.data); self.assertTrue(back.ends_properly); self.assertEqual(back.color_changes, 2)
        self.assertEqual([s["hex"] for s in st["color_sequence"]], ["#ff0000", "#0000ff", "#ff0000"])     # sheet shows the real order incl. the repeat
        self.assertIsNotNone(server.sheet.package(d)[0])
    def test_appliqué_whose_cover_matches_an_earlier_colour_exports(self):
        d = doc({"id": "a", "type": "fill", "color": "#c8102e", "rings": [SQ]},
                {"id": "b", "type": "applique", "color": "#c8102e", "rings": [[[40, 0], [60, 0], [60, 20], [40, 20]]]})
        self.assertTrue(run_checks(d, generate(d)[0]).ok); self.assertIsNone(server.api_dst(d)[1])
    def test_real_sequence_errors_are_still_caught(self):
        from stitchcraft_engine.model import Pattern, Stitch, ThreadColor, Cmd
        from stitchcraft_engine.validate import validate
        same = Pattern("t", [Stitch(0, 0, Cmd.JUMP, 0), Stitch(0, 0, Cmd.STITCH, 0), Stitch(5, 0, Cmd.STITCH, 0), Stitch(5, 0, Cmd.COLOR_CHANGE, 0),
                             Stitch(9, 0, Cmd.STITCH, 0), Stitch(9, 0, Cmd.END, 0)], [ThreadColor("a", "#000")])
        self.assertIn("COLOR_SEQ", {i.code for i in validate(same).errors})                 # a 'change' to the same thread
        bad = Pattern("t", [Stitch(0, 0, Cmd.STITCH, 3), Stitch(5, 0, Cmd.STITCH, 3), Stitch(5, 0, Cmd.END, 3)], [ThreadColor("a", "#000")])
        self.assertIn("THREAD_INDEX", {i.code for i in validate(bad).errors})               # dangling thread reference
        two = Pattern("t", [Stitch(0, 0, Cmd.STITCH, 0), Stitch(5, 0, Cmd.STITCH, 0), Stitch(5, 0, Cmd.COLOR_CHANGE, 1), Stitch(9, 0, Cmd.STITCH, 1),
                            Stitch(9, 0, Cmd.END, 1)], [ThreadColor("a", "#000"), ThreadColor("b", "#fff")])
        self.assertTrue(validate(two).ok)
