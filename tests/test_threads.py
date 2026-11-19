"""Thread libraries: CIEDE2000 (against published reference values), palette parsing / storage, matching, apply / replace, consumption, API."""
import json, math, os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import threads as T
from stitchcraft_engine.design import generate
import app as server

D = {"name": "t", "hoop": {"w": 100, "h": 100, "margin": 3}, "objects": [{"id": "a", "type": "fill", "color": "#cc142d", "rings": [[[0, 0], [30, 0], [30, 20], [0, 20]]]}, {"id": "b", "type": "run", "color": "#c9a23f", "points": [[0, 30], [30, 30]]}]}
CSV = "code,name,hex\n1000,Black,#000000\n1147,Red,#d02a34\n1033,Gold,c9a23f\nbad,,zz\n"


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); os.environ["ES_PALETTE_DIR"] = self.tmp.name
    def tearDown(self):
        os.environ.pop("ES_PALETTE_DIR", None); self.tmp.cleanup()


class Maths(unittest.TestCase):
    def test_ciede2000_matches_published_reference_pairs(self):          # Sharma, Wu, Dalal (2005) test data
        for a, b, want in (((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425), ((50, 3.1571, -77.2803), (50, 0, -82.7485), 2.8615), ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
                           ((50, 2.5, 0), (50, 0, -2.5), 4.3065), ((2.0776, 0.0795, -1.135), (0.9033, -0.0636, -0.5514), 0.9082)):
            self.assertAlmostEqual(T.delta_e2000(a, b), want, places=3)
    def test_identity_and_symmetry(self):
        a, b = T._lab("#cc142d"), T._lab("#c9a23f"); self.assertEqual(T.delta_e2000(a, a), 0.0); self.assertAlmostEqual(T.delta_e2000(a, b), T.delta_e2000(b, a), places=6)


class Palettes(Setup):
    def test_parse_csv_json_rgb_and_rejects(self):
        cols, rej = T.parse_palette(CSV); self.assertEqual([c["code"] for c in cols], ["1000", "1147", "1033"]); self.assertEqual(len(rej), 1)
        cols, _ = T.parse_palette(json.dumps([{"code": "1", "name": "x", "hex": "#112233"}])); self.assertEqual(cols[0]["hex"], "#112233")
        cols, _ = T.parse_palette("code;name;r;g;b\n7;Blue;0;0;255"); self.assertEqual(cols[0]["hex"], "#0000ff")
        for bad in ("", "nothing,here\n1,2", "[1,2,3]", "code,name,hex\n,,#fff"):
            with self.assertRaises(ValueError): T.parse_palette(bad)
    def test_save_list_get_delete(self):
        cols, _ = T.parse_palette(CSV); rec = T.save_palette("My Brand 40wt", "me", cols)
        self.assertEqual(rec["id"], "my_brand_40wt"); ids = [p["id"] for p in T.list_palettes()]; self.assertEqual(ids, ["generic", "my_brand_40wt"])
        self.assertEqual(len(T.get_palette("my_brand_40wt")["colours"]), 3); self.assertTrue(T.delete_palette("my_brand_40wt")); self.assertEqual([p["id"] for p in T.list_palettes()], ["generic"])
        with self.assertRaises(ValueError): T.get_palette("../etc/passwd")
        with self.assertRaises(ValueError): T.delete_palette("generic")
        with self.assertRaises(ValueError): T.save_palette("generic", "", cols)
    def test_generic_is_labelled_not_a_brand_chart(self):
        g = T.get_palette("generic"); self.assertIn("NOT a thread-brand chart", g["note"]); self.assertEqual(len(g["colours"]), 18)
    def test_repo_ships_no_brand_palettes(self):
        os.environ.pop("ES_PALETTE_DIR", None); self.assertEqual(list((ROOT / "palettes").glob("*.json")), [])


class Matching(Setup):
    def setUp(self):
        super().setUp(); cols, _ = T.parse_palette(CSV); self.pal = T.save_palette("Test", "t", cols)
    def test_nearest_and_quality(self):
        r = T.match_design(D, self.pal); self.assertEqual(r["rows"][0]["best"]["code"], "1147"); self.assertEqual(r["rows"][1]["best"]["code"], "1033"); self.assertEqual(r["rows"][1]["quality"], "close")
        far = T.match_design({"objects": [{"color": "#00ff00"}]}, self.pal); self.assertEqual(far["rows"][0]["quality"], "poor")
    def test_apply_snaps_colours_and_records_codes_without_mutating_the_input(self):
        before = json.dumps(D); out, info = T.apply_palette(D, self.pal)
        self.assertEqual(json.dumps(D), before); self.assertEqual(out["objects"][0]["color"], "#d02a34"); self.assertEqual(out["thread_map"][0]["code"], "1147"); self.assertEqual(info["objects_recoloured"], 2)
    def test_replace_colour(self):
        out, n = T.replace_colour(D, "#CC142D", "#0000ff"); self.assertEqual(n, 1); self.assertEqual(out["objects"][0]["color"], "#0000ff"); self.assertEqual(D["objects"][0]["color"], "#cc142d")
        with self.assertRaises(ValueError): T.replace_colour(D, "red", "#fff")
    def test_applique_cover_colour_is_included(self):
        d = {"objects": [{"id": "x", "type": "applique", "color": "#cc142d", "params": {"cover_color": "#cc142d"}}]}; out, n = T.replace_colour(d, "#cc142d", "#000000"); self.assertEqual(n, 2)


class Consumption(unittest.TestCase):
    def test_estimate_scales_with_stitches_and_reports_its_formula(self):
        p = generate(D)[0]; c = T.consumption(p)
        self.assertEqual(len(c["rows"]), 2); self.assertGreater(c["top_total_m"], 0); self.assertAlmostEqual(c["bobbin_total_m"], c["top_total_m"] * T.BOBBIN_RATIO, delta=0.05)
        self.assertIn("ESTIMATE", c["note"]); self.assertIn("per stitch", c["formula"])
        big = json.loads(json.dumps(D)); big["objects"][0]["rings"] = [[[0, 0], [60, 0], [60, 40], [0, 40]]]
        self.assertGreater(T.consumption(generate(big)[0])["rows"][0]["top_m"], c["rows"][0]["top_m"] * 2)
    def test_path_length_of_a_known_run(self):
        d = {"name": "r", "hoop": {"w": 100, "h": 100, "margin": 3}, "objects": [{"id": "r", "type": "run", "color": "#000000", "points": [[0, 0], [50, 0]], "params": {"stitch_len": 2.5}}], "machine": {"lock_len": 0}}
        c = T.consumption(generate(d)[0]); self.assertAlmostEqual(c["rows"][0]["path_m"], 0.05, delta=0.0015)


class Api(Setup):
    def test_import_match_apply_replace_consumption_delete(self):
        r = server.api_threads_import({"name": "Brand A", "brand": "A", "text": CSV}); self.assertEqual(r["count"], 3); self.assertEqual(len(r["rejected"]), 1)
        m = server.api_threads_apply({"design": D, "palette": "brand_a"}, snap=False); self.assertEqual(m["rows"][0]["best"]["code"], "1147")
        a = server.api_threads_apply({"design": D, "palette": "brand_a"}); self.assertEqual(a["design"]["thread_map"][1]["code"], "1033")
        self.assertEqual(server.api_threads_replace({"design": D, "from": "#cc142d", "to": "#123456"})["replaced"], 1); self.assertGreater(server.api_threads_consumption({"design": D})["top_total_m"], 0)
    def test_validation(self):
        for bad in ({"name": "", "text": CSV}, {"name": "x"}, {"name": "x", "text": "junk"}):
            with self.assertRaises(ValueError): server.api_threads_import(bad)
        with self.assertRaises(ValueError): server.api_threads_apply({"design": D, "palette": "nope"})
        with self.assertRaises(ValueError): server.api_threads_apply({"palette": "generic"})


if __name__ == "__main__":
    unittest.main()
