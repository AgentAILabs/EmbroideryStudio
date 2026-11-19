"""Optimization advisor: measured findings, each applicable one is a real edit that improves the measured value."""
import copy, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import advisor as V, assistant as A
import app as server

def doc(*objs, **kw): return dict({"name": "t", "hoop": {"w": 150, "h": 150, "margin": 3}, "objects": list(objs)}, **kw)
def sq(x, y, w, h): return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
def fill(i, r, col="#cc142d", **p): return {"id": i, "type": "fill", "color": col, "rings": [r], "params": p}
ids = lambda r: {x["id"] for x in r["recommendations"]}


class Findings(unittest.TestCase):
    def test_clean_design_has_no_recommendations(self):
        r = V.analyse(doc(fill("a", sq(0, 0, 40, 30)))); self.assertEqual(r["recommendations"], []); self.assertIn("not machine-verified", r["note"])

    def test_density_is_measured_and_fixed(self):
        d = doc(fill("a", sq(0, 0, 40, 30), spacing=0.1)); r = V.analyse(d)
        if "density" in ids(r):
            out = V.apply(d, ["density"]); self.assertLess(out["after"]["max_penetrations_per_mm2"], r["metrics"]["max_penetrations_per_mm2"])
        else: self.assertLessEqual(r["metrics"]["max_penetrations_per_mm2"], 12)

    def test_missing_underlay_found_and_added(self):
        d = doc(fill("a", sq(0, 0, 40, 30), underlay="none")); r = V.analyse(d); self.assertIn("underlay", ids(r))
        out = V.apply(d, ["underlay"]); self.assertEqual(out["design"]["objects"][0]["params"]["underlay"], "tatami"); self.assertNotIn("underlay", ids(V.analyse(out["design"])))

    def test_avoidable_colour_changes_reduced(self):
        d = doc(fill("a", sq(0, 0, 20, 20), "#cc142d"), fill("b", sq(30, 0, 20, 20), "#1f4fb4"), fill("c", sq(60, 0, 20, 20), "#cc142d"), fill("e", sq(90, 0, 20, 20), "#1f4fb4"))
        r = V.analyse(d); self.assertIn("colour_changes", ids(r)); out = V.apply(d, ["colour_changes"]); self.assertLess(out["after"]["colour_changes"], r["metrics"]["colour_changes"])

    def test_tiny_details_found_and_removed(self):
        d = doc(fill("a", sq(0, 0, 40, 30)), fill("t", sq(100, 0, 0.5, 0.5))); self.assertIn("tiny", ids(V.analyse(d)))
        out = V.apply(d, ["tiny"]); self.assertEqual([o["id"] for o in out["design"]["objects"]], ["a"])

    def test_pull_comp_recommendation_for_stretchy_fabric(self):
        d = doc(fill("a", sq(0, 0, 40, 30), pull_comp=0.1), fabric="knit"); self.assertIn("pull_comp", ids(V.analyse(d)))

    def test_findings_carry_evidence_and_severity(self):
        r = V.analyse(doc(fill("a", sq(0, 0, 40, 30), underlay="none")))
        for x in r["recommendations"]: self.assertIn(x["severity"], ("high", "medium", "low")); self.assertTrue(x["evidence"] and x["why"])


class Grouping(unittest.TestCase):
    def test_layering_of_overlapping_objects_is_never_changed(self):
        d = doc(fill("a", sq(0, 0, 20, 20), "#cc142d"), fill("b", sq(10, 10, 20, 20), "#1f4fb4"), fill("c", sq(20, 20, 20, 20), "#cc142d"))     # red under blue under red: must stay in this order
        out, before, after = A.group_by_colour(d); self.assertEqual([o["id"] for o in out["objects"]], ["a", "b", "c"]); self.assertEqual((before, after), (2, 2))

    def test_independent_objects_are_grouped(self):
        d = doc(fill("a", sq(0, 0, 10, 10), "#cc142d"), fill("b", sq(30, 0, 10, 10), "#1f4fb4"), fill("c", sq(60, 0, 10, 10), "#cc142d"), fill("e", sq(90, 0, 10, 10), "#1f4fb4"))
        out, before, after = A.group_by_colour(d); self.assertEqual((before, after), (3, 1)); self.assertEqual([o["color"] for o in out["objects"]], ["#cc142d", "#cc142d", "#1f4fb4", "#1f4fb4"])

    def test_partial_overlap_groups_what_it_can(self):
        d = doc(fill("a", sq(0, 0, 20, 20), "#cc142d"), fill("b", sq(10, 10, 20, 20), "#1f4fb4"), fill("c", sq(100, 0, 10, 10), "#cc142d"))
        out, before, after = A.group_by_colour(d); order = [o["id"] for o in out["objects"]]; self.assertLess(order.index("a"), order.index("b")); self.assertLessEqual(after, before)

    def test_does_not_mutate_or_drop_objects(self):
        d = doc(fill("a", sq(0, 0, 10, 10), "#cc142d"), fill("b", sq(30, 0, 10, 10), "#1f4fb4"), fill("c", sq(60, 0, 10, 10), "#cc142d")); before = json.dumps(d)
        out, _, _ = A.group_by_colour(d); self.assertEqual(json.dumps(d), before); self.assertEqual(sorted(o["id"] for o in out["objects"]), ["a", "b", "c"])


class Apply(unittest.TestCase):
    def test_apply_all_never_mutates_the_input_and_returns_log(self):
        d = doc(fill("a", sq(0, 0, 40, 30), underlay="none"), fill("t", sq(100, 0, 0.5, 0.5))); before = json.dumps(d)
        out = V.apply(d); self.assertEqual(json.dumps(d), before); self.assertTrue(out["done"]); server.check_design(out["design"])

    def test_unknown_ids_apply_nothing(self):
        d = doc(fill("a", sq(0, 0, 40, 30), underlay="none")); out = V.apply(d, ["nope"]); self.assertEqual(out["done"], []); self.assertEqual(out["design"]["objects"][0]["params"]["underlay"], "none")

    def test_new_assistant_commands(self):
        r = A.run(doc(fill("a", sq(0, 0, 40, 30), underlay="none")), "add underlay and clean short stitches"); self.assertEqual(len(r["applied"]), 2); self.assertEqual(r["design"]["machine"]["micro_clean"], 0.5)


class Api(unittest.TestCase):
    def test_api(self):
        d = doc(fill("a", sq(0, 0, 40, 30), underlay="none"))
        self.assertIn("underlay", ids(server.api_advisor({"design": d}))); self.assertTrue(server.api_advisor({"design": d, "ids": ["underlay"]}, apply=True)["done"])
        for bad in ({}, {"design": doc()}, {"design": d, "ids": "x"}, {"design": d, "ids": ["a"] * 50}):
            with self.assertRaises(ValueError): server.api_advisor(bad, apply="ids" in bad)


if __name__ == "__main__":
    unittest.main()
