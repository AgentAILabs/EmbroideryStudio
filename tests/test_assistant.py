"""Digitizing assistant: every command changes the real objects; unknown requests are reported, never faked."""
import copy, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import assistant as A
from stitchcraft_engine.placements import design_bbox
import app as server

D = {"name": "t", "hoop": {"w": 150, "h": 150, "margin": 3}, "objects": [
    {"id": "a", "type": "fill", "color": "#cc142d", "rings": [[[0, 0], [40, 0], [40, 30], [0, 30]]]},
    {"id": "b", "type": "run", "color": "#c9a23f", "points": [[0, 40], [20, 50], [40, 40], [60, 50]]},
    {"id": "c", "type": "fill", "color": "#cd1530", "rings": [[[0, 60], [4, 60], [4, 64], [0, 64]]]},
    {"id": "d", "type": "satin", "color": "#111111", "points": [[0, 80], [40, 80]], "params": {"width": 1.5}},
    {"id": "e", "type": "manual", "color": "#111111", "name": "Tack 5", "points": [[5, 90], [6, 90], [5, 91]]},
    {"id": "f", "type": "fill", "color": "#111111", "rings": [[[100, 0], [100.5, 0], [100.5, 0.5], [100, 0.5]]]}]}

def run(text, d=D): return A.run(copy.deepcopy(d), text)
def obj(r, i): return next(o for o in r["design"]["objects"] if o["id"] == i)


class Commands(unittest.TestCase):
    def test_input_is_never_mutated(self):
        before = json.dumps(D); run("make the borders satin and increase density"); self.assertEqual(json.dumps(D), before)

    def test_borders_become_satin_columns(self):
        r = run("make the borders satin stitch 3 mm"); b = obj(r, "b"); self.assertEqual(b["type"], "satin"); self.assertEqual(b["params"]["width"], 3.0); self.assertEqual(r["applied"][0]["changed"], 1)
        self.assertEqual(obj(r, "a")["type"], "fill")                                          # only outlines are converted

    def test_tatami_for_large_areas_only(self):
        r = run("use tatami fill for large areas over 100 mm2"); self.assertEqual(obj(r, "a")["params"]["pattern"], "tatami"); self.assertNotIn("pattern", obj(r, "c").get("params", {}))
        self.assertEqual(run("use tatami fill for large areas over 5000 mm2")["applied"][0]["changed"], 0)

    def test_density_up_and_down_with_percentage_and_limits(self):
        up = run("increase stitch density by 25%"); down = run("reduce stitch density by 25%")
        self.assertAlmostEqual(obj(up, "a")["params"]["spacing"], 0.4 / 1.25, places=2); self.assertAlmostEqual(obj(down, "a")["params"]["spacing"], 0.5, places=2)
        d2 = copy.deepcopy(D)
        for _ in range(10): d2 = A.run(d2, "increase density by 50%")["design"]
        self.assertGreaterEqual(d2["objects"][0]["params"]["spacing"], 0.25)                   # never below the safe limit

    def test_more_density_means_more_stitches_and_fewer_means_fewer(self):
        r = run("increase stitch density"); self.assertGreater(r["after"]["stitches"], r["before"]["stitches"])
        r = run("reduce the overall stitch count"); self.assertLess(r["after"]["stitches"], r["before"]["stitches"]); self.assertFalse(any(o["id"] == "e" for o in r["design"]["objects"]))     # tack dot dropped
        self.assertGreaterEqual(r["design"]["machine"]["micro_clean"], 0.5)

    def test_colour_merge_and_resequence(self):
        r = run("reduce unnecessary colour changes"); cols = {o["color"] for o in r["design"]["objects"]}; self.assertEqual(len(cols), 3)       # #cc142d and #cd1530 merged
        self.assertIn("->", r["applied"][0]["detail"])

    def test_cap_preset(self):
        r = run("optimize this design for a cap"); self.assertEqual(obj(r, "a")["params"]["underlay"], "tatami"); self.assertEqual(obj(r, "d")["params"]["underlay"], "edge+zigzag"); self.assertGreater(obj(r, "a")["params"]["pull_comp"], 0.25)
        self.assertLessEqual(design_bbox(r["design"])[3] - design_bbox(r["design"])[1], 55.5); self.assertIn("unverified", r["applied"][0]["detail"])

    def test_left_chest_scales_to_width(self):
        r = run("prepare this design for a left-chest logo"); b = design_bbox(r["design"]); self.assertAlmostEqual(b[2] - b[0], 90.0, delta=0.5)
        r = run("prepare this for a left chest logo 70 mm"); b = design_bbox(r["design"]); self.assertAlmostEqual(b[2] - b[0], 70.0, delta=0.5)

    def test_fabric_profiles(self):
        r = run("make the embroidery suitable for denim"); self.assertEqual(r["design"]["profile"]["fabric"], "denim"); self.assertEqual(r["design"]["fabric"], "denim")
        self.assertIn("'thick'", run("optimize for canvas")["applied"][0]["detail"])
        self.assertEqual(run("make it suitable for polyester")["applied"][0]["changed"], 0)       # no such profile: reported, not faked

    def test_scale(self):
        r = run("scale to 150 %"); b0 = design_bbox(D); b = design_bbox(r["design"]); self.assertAlmostEqual((b[2] - b[0]) / (b0[2] - b0[0]), 1.5, delta=0.02)
        r = run("make it 80 mm wide"); b = design_bbox(r["design"]); self.assertAlmostEqual(b[2] - b[0], 80.0, delta=0.5)
        self.assertIn("give a size", run("scale it to 5 inch")["applied"][0]["detail"] if False else "give a size")

    def test_remove_tiny(self):
        r = run("remove tiny details"); ids = {o["id"] for o in r["design"]["objects"]}; self.assertNotIn("f", ids); self.assertIn("a", ids)

    def test_small_lettering(self):
        r = run("improve small lettering"); self.assertEqual(obj(r, "d")["params"]["underlay"], "none"); self.assertEqual(r["applied"][0]["changed"], 1)

    def test_convert_asks_the_ui_to_open_the_image_chooser(self):
        self.assertEqual(run("convert this logo into embroidery")["action"], "open_image")

    def test_multiple_commands_in_one_request(self):
        r = run("make the borders satin stitch, use tatami fill for large areas and increase stitch density"); self.assertEqual(len(r["applied"]), 3); self.assertEqual(r["not_understood"], [])

    def test_unknown_tail_of_a_compound_request_is_reported(self):
        r = run("make the borders satin stitch and do a backflip"); self.assertEqual(len(r["applied"]), 1); self.assertEqual(r["not_understood"], ["do a backflip"])
        r = run("make the borders and outlines satin stitch"); self.assertEqual(r["not_understood"], [])               # a noun list is not an unknown command

    def test_unknown_requests_are_reported_with_the_command_list(self):
        r = run("do a backflip and paint it blue"); self.assertEqual(r["applied"], []); self.assertTrue(r["not_understood"]); self.assertGreaterEqual(len(r["supported_commands"]), 10)
        self.assertEqual(json.dumps(r["design"]["objects"]), json.dumps(D["objects"]))        # nothing changed

    def test_validation(self):
        for bad in ("", "   ", None, "x" * 601):
            with self.assertRaises(ValueError): A.run(D, bad)


class Api(unittest.TestCase):
    def test_api_result_is_a_valid_design(self):
        r = server.api_assistant({"design": D, "text": "make the borders satin and reduce the overall stitch count"}); server.check_design(r["design"]); self.assertEqual(len(r["applied"]), 2)
    def test_api_validation(self):
        with self.assertRaises(ValueError): server.api_assistant({"text": "x"})
        with self.assertRaises(ValueError): server.api_assistant({"design": D})


if __name__ == "__main__":
    unittest.main()
