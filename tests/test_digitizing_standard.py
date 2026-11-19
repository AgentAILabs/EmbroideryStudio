"""Professional digitizing standard: underlay ladder, stitch shortening, fabric/category profiles, region-ordered fills,
sequence optimisation, 15-item production checklist, auto-digitize pipeline and export gating."""
import base64, copy, io, json, math, sys, unittest, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
for sub in ("engine", "server"):
    sys.path.insert(0, str(ROOT / sub))
from stitchcraft_engine import profiles as PR, sequence as SQ, checklist as CL
from stitchcraft_engine.design import generate, run_checks
from stitchcraft_engine.model import Cmd
from stitchcraft_engine.stitches import tatami_fill, satin_from_rails, zigzag_underlay
from stitchcraft_engine.geometry import point_in_polygon
import app as server
import sheet

def lib(n): return json.loads((ROOT / "designs" / "library" / n / f"{n}.esproj").read_text())["doc"]
def doc(*objs, **kw): return dict({"name": "t", "hoop": {"w": 120, "h": 120, "margin": 3}, "objects": list(objs)}, **kw)
def col(w, n=12, oid="c", **params):
    return {"id": oid, "type": "column", "color": "#c00", "rail1": [[i * 3.0, 0] for i in range(n)], "rail2": [[i * 3.0, w] for i in range(n)], "params": params}
def ring(r1=30, r2=12, n1=48, n2=36):
    return [[(r1 * math.cos(2 * math.pi * t / n1), r1 * math.sin(2 * math.pi * t / n1)) for t in range(n1)],
            [(r2 * math.cos(-2 * math.pi * t / n2), r2 * math.sin(-2 * math.pi * t / n2)) for t in range(n2)]]
def stitches(p): return [(s.x, s.y) for s in p.stitches if s.cmd == Cmd.STITCH]


class UnderlayTests(unittest.TestCase):
    def test_zigzag_stays_inside_the_column(self):
        z = zigzag_underlay([(i, 0) for i in range(20)], [(i, 5) for i in range(20)])
        self.assertTrue(all(0.49 <= y <= 4.51 for _, y in z)); self.assertGreater(len(z), 10)
    def test_ladder_adds_underlay_stitches(self):
        n = {u: generate(doc(col(5.0, underlay=u)))[2]["stitches"] for u in ("none", "center", "edge", "zigzag", "edge+zigzag")}
        self.assertLess(n["none"], n["center"]); self.assertLess(n["edge"], n["edge+zigzag"]); self.assertLess(n["zigzag"], n["edge+zigzag"])
        for u in ("zigzag", "edge+zigzag"):
            d = doc(col(5.0, underlay=u)); self.assertTrue(run_checks(d, generate(d)[0]).ok)
    def test_satin_object_supports_zigzag(self):
        s = {"id": "s", "type": "satin", "color": "#00f", "points": [[0, 0], [40, 0]], "params": {"width": 5, "underlay": "zigzag"}}
        a = generate(doc(s))[2]["stitches"]; s["params"]["underlay"] = "none"; self.assertGreater(a, generate(doc(s))[2]["stitches"])


class ShorteningTests(unittest.TestCase):
    def arc(self, shorten):
        r_in, r_out = 2.0, 6.0
        left = [(r_in * math.cos(t / 30 * math.pi), r_in * math.sin(t / 30 * math.pi)) for t in range(31)]
        right = [(r_out * math.cos(t / 30 * math.pi), r_out * math.sin(t / 30 * math.pi)) for t in range(31)]
        return satin_from_rails(left, right, 0.4, 0, shorten)
    def test_inner_curve_penetrations_are_spread(self):
        on_inner_edge = lambda pts: sum(1 for x, y in pts if math.hypot(x, y) < 2.3)      # inner rail radius 2 mm
        a, b = self.arc(False), self.arc(True)
        self.assertEqual(len(a), len(b)); self.assertLess(on_inner_edge(b), 0.7 * on_inner_edge(a))
        self.assertGreater(min(math.dist(p, q) for p, q in zip(b, b[1:])), 0.5)          # shortening never makes micro stitches
    def test_straight_column_is_untouched(self):
        l, r = [(i, 0) for i in range(20)], [(i, 3) for i in range(20)]
        self.assertEqual(satin_from_rails(l, r, 0.4, 0, True), satin_from_rails(l, r, 0.4, 0, False))


class ProfileTests(unittest.TestCase):
    def test_satin_ladder(self):
        self.assertEqual([PR.satin_underlay(w, 0) for w in (1.0, 2.0, 4.0, 5.0, 7.0)], ["none", "center", "edge", "zigzag", "edge+zigzag"])
        self.assertEqual(PR.satin_underlay(5.0, -1), "edge"); self.assertEqual(PR.satin_underlay(3.0, 0), "center"); self.assertEqual(PR.satin_underlay(2.0, 1), "center")      # no room for edge in 2 mm
    def test_fill_ladder(self):
        self.assertEqual([PR.fill_underlay(a, 0) for a in (10, 100, 900)], ["none", "tatami", "edge+tatami"])
        self.assertEqual(PR.fill_underlay(100, -1), "edge"); self.assertEqual(PR.fill_underlay(15, 1), "edge+tatami")
    def test_light_fabric_is_lighter_than_pile(self):
        d = lib("kalash")
        silk = generate(PR.apply_profile(d, "silk", "floral", overwrite=True)[0])[2]["stitches"]
        velvet = generate(PR.apply_profile(d, "velvet", "floral", overwrite=True)[0])[2]["stitches"]
        self.assertLess(silk, velvet)
    def test_explicit_params_win_unless_overwrite(self):
        d = doc(col(3.0, spacing=0.5, underlay="none"))
        a, _ = PR.apply_profile(d, "cotton", "logo"); self.assertEqual(a["objects"][0]["params"]["spacing"], 0.5)
        self.assertEqual(a["objects"][0]["params"]["underlay"], "none"); self.assertTrue(a["objects"][0]["params"]["shorten"])
        b, _ = PR.apply_profile(d, "cotton", "logo", overwrite=True); self.assertEqual(b["objects"][0]["params"]["underlay"], "center")
    def test_auto_spacing_by_width_and_clamps(self):
        d, _ = PR.apply_profile(doc(col(1.2, oid="n"), col(6.5, oid="w")), "cotton", "logo")
        sp = {o["id"]: o["params"]["spacing"] for o in d["objects"]}; self.assertGreater(sp["n"], sp["w"])
        d, _ = PR.apply_profile(doc(col(6.5)), "velvet", "logo"); d["thread"] = "120"
        d, _ = PR.apply_profile(dict(d, objects=[col(6.5)]), "velvet", "logo"); self.assertGreaterEqual(d["objects"][0]["params"]["spacing"], PR.SPACING_MIN)
    def test_unknown_values_rejected_and_logged(self):
        with self.assertRaises(ValueError): PR.apply_profile(doc(col(3)), "plastic", "logo")
        with self.assertRaises(ValueError): PR.apply_profile(doc(col(3)), "silk", "pizza")
        _, log = PR.apply_profile(doc(col(3)), "silk", "saree_border"); self.assertIn("Saree", log[0])
    def test_every_library_design_stays_clean_under_every_fabric(self):
        for n in ("peacock_arch", "kalash", "lotus_bloom", "paisley_pair"):
            for fab in PR.FABRICS:
                d, _ = PR.apply_profile(lib(n), fab, "blouse_neck", overwrite=True); p = generate(d)[0]
                self.assertTrue(run_checks(d, p).ok, (n, fab))


class RegionFillTests(unittest.TestCase):
    def test_same_points_fewer_runs(self):
        a = tatami_fill(ring(), 45, 0.4, 3.5, regions=False); b = tatami_fill(ring(), 45, 0.4, 3.5, regions=True)
        self.assertEqual(sorted((round(x, 6), round(y, 6)) for r in a for x, y in r), sorted((round(x, 6), round(y, 6)) for r in b for x, y in r))
        self.assertLess(len(b), len(a) / 2)
    def test_ring_trims_drop_and_hole_stays_empty(self):
        def trims(reg):
            d = doc({"id": "f", "type": "fill", "color": "#c00", "rings": ring(), "params": {"regions": reg}})
            p, _, st = generate(d); return st["trims"], p
        t_off, _ = trims(False); t_on, p = trims(True)
        self.assertLess(t_on, t_off / 3)
        self.assertEqual([1 for x, y in stitches(p) if math.hypot(x, y) < 11.5], [])
    def test_convex_shape_unchanged(self):
        sq = [[(0, 0), (30, 0), (30, 20), (0, 20)]]
        self.assertEqual(tatami_fill(sq, 30, 0.4, 3.5, regions=False), tatami_fill(sq, 30, 0.4, 3.5, regions=True))


class SequenceTests(unittest.TestCase):
    def test_never_worse_and_colours_kept(self):
        for n in ("bride_frame", "floral_vine_border", "temple_border", "mandala_rosette", "scroll_pair"):
            d = lib(n); nd, log = SQ.optimize_sequence(d)
            self.assertLessEqual(SQ.travel_metrics(nd), SQ.travel_metrics(d), n)
            self.assertEqual(generate(nd)[2]["color_sequence"], generate(d)[2]["color_sequence"], n)
            self.assertEqual(sorted(o["id"] for o in nd["objects"]), sorted(o["id"] for o in d["objects"]))
    def test_overlapping_objects_keep_layer_order(self):
        objs = [{"id": "base", "type": "fill", "color": "#f00", "rings": [[[0, 0], [20, 0], [20, 20], [0, 20]]]},
                {"id": "far", "type": "fill", "color": "#f00", "rings": [[[80, 80], [90, 80], [90, 90], [80, 90]]]},
                {"id": "top", "type": "fill", "color": "#f00", "rings": [[[5, 5], [15, 5], [15, 15], [5, 15]]]},
                {"id": "near", "type": "fill", "color": "#f00", "rings": [[[25, 0], [35, 0], [35, 10], [25, 10]]]}]
        nd, _ = SQ.optimize_sequence(doc(*objs)); ids = [o["id"] for o in nd["objects"]]
        self.assertLess(ids.index("base"), ids.index("top"))


class MotifSequencingTests(unittest.TestCase):
    def test_touching_objects_form_one_motif_and_far_ones_do_not(self):
        a = {"id": "a", "type": "run", "color": "#f00", "points": [[0, 0], [10, 0]]}
        b = {"id": "b", "type": "run", "color": "#f00", "points": [[10.5, 0], [20, 0]]}
        c = {"id": "c", "type": "run", "color": "#f00", "points": [[50, 0], [60, 0]]}
        self.assertEqual(SQ._motifs([a, b, c]), [[0, 1], [2]])
    def test_motif_inner_order_is_kept(self):
        objs = [{"id": f"p{i}", "type": "run", "color": "#f00", "points": [[i * 0.8, 0], [i * 0.8 + 0.7, 0]]} for i in range(5)] + \
               [{"id": "far", "type": "run", "color": "#f00", "points": [[90, 0], [95, 0]]}]
        order = SQ._motif_order(objs, (100, 0))
        self.assertEqual(order, [5, 0, 1, 2, 3, 4])                                  # far motif first (nearest), petals in their order
    def test_objective_is_machine_time_and_never_worse(self):
        self.assertAlmostEqual(SQ.machine_seconds((1, 0.0)), 6.0)
        for n in ("bride_frame", "temple_border", "peacock_arch", "lotus_bloom"):
            d = lib(n); nd, _ = SQ.optimize_sequence(d)
            self.assertLessEqual(SQ.machine_seconds(SQ.travel_metrics(nd)), SQ.machine_seconds(SQ.travel_metrics(d)) + 1e-6, n)


class ChecklistTests(unittest.TestCase):
    def test_fifteen_items_and_library_is_exportable(self):
        for n in ("peacock_arch", "kalash", "lotus_bloom"):
            r = CL.evaluate(lib(n))
            self.assertEqual([i["n"] for i in r["items"]], list(range(1, 16))); self.assertTrue(r["export_allowed"], n)
            self.assertTrue(all(i["level"] in ("PASS", "WARN", "FAIL", "N/A") and i["evidence"] for i in r["items"]))
    def test_oversize_design_fails_item_2_and_export_is_blocked(self):
        d = doc({"id": "f", "type": "fill", "color": "#f00", "rings": [[[0, 0], [200, 0], [200, 50], [0, 50]]]})
        r = CL.evaluate(d); self.assertEqual(r["items"][1]["level"], "FAIL"); self.assertFalse(r["export_allowed"])
        res, err = server.api_dst(d); self.assertIsNone(res); self.assertIn("error", err)
    def test_missing_underlay_and_pull_comp_are_flagged(self):
        d = doc(col(4.0, underlay="none", pull_comp=0))
        r = CL.evaluate(d); lv = {i["n"]: i["level"] for i in r["items"]}
        self.assertEqual(lv[5], "WARN"); self.assertEqual(lv[6], "WARN"); self.assertTrue(r["export_allowed"])
    def test_colour_report(self):
        p, _, st = generate(lib("kalash")); csv = CL.colour_report_csv(lib("kalash"), st).splitlines()
        self.assertEqual(csv[0], "stop,needle,thread_hex,stitches,note"); self.assertEqual(len(csv) - 1, len(st["color_sequence"]))
        z, _ = sheet.package(lib("kalash")); self.assertIn("kalash.colours.csv", zipfile.ZipFile(io.BytesIO(z)).namelist())


class AutoDigitizeTests(unittest.TestCase):
    def png(self):
        try:
            from PIL import Image, ImageDraw
            import numpy  # noqa: F401
        except Exception:
            self.skipTest("Pillow/NumPy not available")
        im = Image.new("RGB", (800, 600), "white"); d = ImageDraw.Draw(im)
        d.ellipse((100, 100, 500, 500), fill=(170, 20, 40)); d.ellipse((220, 220, 380, 380), fill=(230, 180, 30))
        d.rectangle((560, 80, 600, 520), fill=(20, 110, 60)); d.line((620, 100, 760, 500), fill=(20, 110, 60), width=6)
        b = io.BytesIO(); im.save(b, "PNG"); return base64.b64encode(b.getvalue()).decode()
    def test_pipeline(self):
        r = server.api_autodigitize({"data": self.png(), "width_mm": 90, "colors": 4, "fabric": "silk", "category": "blouse_neck", "thread": "120",
                                     "hoop_w": 130, "hoop_h": 180, "name": "Neck 1"})
        d = r["design"]; self.assertEqual(d["profile"], {"fabric": "silk", "category": "blouse_neck"}); self.assertEqual(d["source"]["type"], "raster")
        c = r["checklist"]; self.assertEqual(c["total"], 15); self.assertTrue(c["export_allowed"]); self.assertEqual(c["items"][0]["level"], "PASS")
        st = generate(d)[2]; self.assertLess(st["trims"], 40)                          # regions + sequencing (was 93 trims)
        self.assertTrue(any("profile:" in l for l in r["log"]))
    def test_bad_inputs(self):
        data = self.png()
        for bad in ({"fabric": "plastic"}, {"category": "pizza"}, {"thread": "x"}):
            with self.assertRaises(ValueError): server.api_autodigitize(dict({"data": data, "width_mm": 60}, **bad))
    def test_profile_api(self):
        r = server.api_profile({"design": lib("kalash"), "fabric": "velvet", "category": "floral", "overwrite": True})
        self.assertEqual(r["design"]["profile"]["fabric"], "velvet"); self.assertTrue(r["log"])

if __name__ == "__main__":
    unittest.main()


class SpecComplianceAuditTests(unittest.TestCase):
    """Regression guard for the section-by-section audit against the specification (docs/digitizing-standard.md)."""
    def img(self):
        try:
            from PIL import Image, ImageDraw
            import numpy  # noqa: F401
        except Exception:
            self.skipTest("Pillow/NumPy not available")
        im = Image.new("RGB", (800, 600), "white"); d = ImageDraw.Draw(im)
        d.ellipse((60, 60, 420, 540), fill=(170, 20, 40)); d.ellipse((180, 200, 300, 400), fill=(230, 180, 30))
        d.rectangle((470, 60, 520, 540), fill=(20, 110, 60)); d.line((560, 80, 760, 520), fill=(20, 20, 120), width=5)
        b = io.BytesIO(); im.save(b, "PNG"); return base64.b64encode(b.getvalue()).decode()
    def run_ad(self, fabric, category, data):
        return server.api_autodigitize({"data": data, "width_mm": 80, "colors": 5, "fabric": fabric, "category": category, "thread": "40wt", "hoop_w": 130, "hoop_h": 180})
    def test_profile_really_applies_in_auto_digitize(self):
        data = self.img()
        silk, denim = self.run_ad("silk", "blouse_neck", data)["design"], self.run_ad("denim", "logo", data)["design"]
        pc = lambda d: {o["params"].get("pull_comp") for o in d["objects"] if o["type"] == "fill"}
        self.assertEqual(pc(silk), {0.25}); self.assertEqual(pc(denim), {0.15})
        runs = lambda d: {o["params"].get("stitch_len") for o in d["objects"] if o["type"] == "run"}
        self.assertEqual(runs(silk), {2.0}); self.assertEqual(runs(denim), {2.5})
        self.assertTrue(all(o["params"].get("min_row") == 0.8 for o in silk["objects"] if o["type"] == "fill"))
    def test_cotton_40wt_densities_inside_spec_range(self):
        d = self.run_ad("cotton", "blouse_neck", self.img())["design"]
        for o in d["objects"]:
            if o["type"] in ("fill", "satin", "column"):
                self.assertTrue(0.40 <= o["params"]["spacing"] <= 0.45, (o["type"], o["params"]["spacing"]))
    def test_light_fabric_never_drops_satin_underlay(self):
        self.assertEqual(PR.satin_underlay(2.5, -1), "center"); self.assertEqual(PR.satin_underlay(1.6, -1), "none")
    def test_matrix_all_fifteen_checks_pass(self):
        data = self.img()
        for fab in ("cotton", "silk", "velvet", "stretch"):
            for cat in ("blouse_neck", "saree_border"):
                c = self.run_ad(fab, cat, data)["checklist"]
                self.assertTrue(c["export_allowed"], (fab, cat)); self.assertEqual(c["passed"], 15, (fab, cat, [(i["n"], i["evidence"]) for i in c["items"] if i["level"] != "PASS"]))
