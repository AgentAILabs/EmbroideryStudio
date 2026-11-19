"""Overlap removal (cut hidden layers), push compensation, zig-zag style - the last open items of the digitizing standard."""
import json, math, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from stitchcraft_engine.design import generate, run_checks
from stitchcraft_engine.geometry import trim_polyline, polyline_length
from stitchcraft_engine.model import Cmd
from stitchcraft_engine.stitches import tatami_fill
from stitchcraft_engine import checklist as CL, profiles as PR

BASE = [[0, 0], [40, 0], [40, 30], [0, 30]]
TOP = [[10, 10], [30, 10], [30, 20], [10, 20]]
def doc(*objs): return {"name": "t", "hoop": {"w": 120, "h": 120, "margin": 3}, "objects": list(objs)}
def stitched(p, oid=None): return [(s.x, s.y) for s in p.stitches if s.cmd == Cmd.STITCH and (oid is None or str(s.object_id).split(".")[0] == oid)]


class OverlapTests(unittest.TestCase):
    def layered(self, cut, top_type="fill"):
        top = {"id": "top", "type": "fill", "color": "#00f", "rings": [TOP]} if top_type == "fill" else \
              {"id": "top", "type": "column", "color": "#00f", "rail1": [[10, 14], [30, 14]], "rail2": [[10, 17], [30, 17]]}
        return doc({"id": "base", "type": "fill", "color": "#f00", "rings": [BASE], "params": {"cut_hidden": cut, "angle": 0}}, top)
    def test_hidden_core_is_not_sewn_and_underlap_is_kept(self):
        on, off = generate(self.layered(True))[0], generate(self.layered(False))[0]
        core = lambda p: [q for q in stitched(p, "base") if 11.2 < q[0] < 28.8 and 11.2 < q[1] < 18.8]
        self.assertGreater(len(core(off)), 50); self.assertEqual(core(on), [])
        lap = [q for q in stitched(on, "base") if 10.0 < q[0] < 10.7 and 11 < q[1] < 19]      # still runs ~0.6 mm under the edge
        self.assertTrue(lap)
        self.assertLess(len(stitched(on, "base")), len(stitched(off, "base")))
        d = self.layered(True); self.assertTrue(run_checks(d, generate(d)[0]).ok)
    def test_column_on_top_is_cut_out_too(self):
        on = generate(self.layered(True, "column"))[0]
        self.assertEqual([q for q in stitched(on, "base") if 11.2 < q[0] < 28.8 and 15.1 < q[1] < 15.9], [])
    def test_objects_before_are_never_cut(self):
        d = doc({"id": "top", "type": "fill", "color": "#00f", "rings": [TOP]}, {"id": "base", "type": "fill", "color": "#f00", "rings": [BASE], "params": {"cut_hidden": True}})
        a = generate(d)[0]; d["objects"][1]["params"]["cut_hidden"] = False
        self.assertEqual(stitched(a, "base"), stitched(generate(d)[0], "base"))
    def test_checklist_overlap_drops(self):
        def ov(cut):
            return next(i for i in CL.evaluate(self.layered(cut))["items"] if i["n"] == 7)["evidence"]
        pct = lambda e: int(e.split("%")[0])
        self.assertLess(pct(ov(True)), pct(ov(False)))
    def test_profile_turns_it_on(self):
        d, _ = PR.apply_profile(self.layered(False), "cotton", "floral")
        self.assertFalse(d["objects"][0]["params"]["cut_hidden"])                 # explicit user value wins
        d2 = self.layered(False); del d2["objects"][0]["params"]["cut_hidden"]
        self.assertTrue(PR.apply_profile(d2, "cotton", "floral")[0]["objects"][0]["params"]["cut_hidden"])
    def test_tatami_exclude_math(self):
        a = tatami_fill([BASE], 0, 0.4, 3.5); b = tatami_fill([BASE], 0, 0.4, 3.5, exclude=[[TOP]], exclude_margin=0.6)
        self.assertLess(sum(map(len, b)), sum(map(len, a)))
        self.assertEqual(tatami_fill([BASE], 0, 0.4, 3.5, exclude=[]), a)


class PushTests(unittest.TestCase):
    def test_trim_polyline(self):
        p = [(0, 0), (10, 0), (10, 10)]
        self.assertAlmostEqual(polyline_length(trim_polyline(p, 1, 2)), 17.0)
        self.assertEqual(trim_polyline(p, 0, 0), p); self.assertAlmostEqual(polyline_length(trim_polyline(p, 99, 99)), 20 / 3, places=6)
    def test_fill_push_shortens_across_rows(self):
        def span(push):
            p = generate(doc({"id": "f", "type": "fill", "color": "#f00", "rings": [BASE], "params": {"angle": 0, "push_comp": push, "underlay": "none"}}))[0]
            ys = [q[1] for q in stitched(p)]; return max(ys) - min(ys)
        self.assertAlmostEqual(span(0) - span(1.0), 1.0, delta=0.45)
    def test_column_push_shortens_length(self):
        def length(push):
            c = {"id": "c", "type": "column", "color": "#c00", "rail1": [[0, 0], [30, 0]], "rail2": [[0, 3], [30, 3]], "params": {"push_comp": push, "underlay": "none"}}
            xs = [q[0] for q in stitched(generate(doc(c))[0])]; return max(xs) - min(xs)
        self.assertAlmostEqual(length(0) - length(0.6), 0.6, delta=0.45)
    def test_stretch_profile_sets_push(self):
        d, _ = PR.apply_profile(doc({"id": "f", "type": "fill", "color": "#f00", "rings": [BASE]}), "stretch", "logo")
        self.assertEqual(d["objects"][0]["params"]["push_comp"], 0.2)
        d, _ = PR.apply_profile(doc({"id": "f", "type": "fill", "color": "#f00", "rings": [BASE]}), "cotton", "logo")
        self.assertNotIn("push_comp", d["objects"][0]["params"])


class ZigzagStyleTests(unittest.TestCase):
    def test_zigzag_is_open_and_has_no_underlay(self):
        c = {"id": "c", "type": "column", "color": "#c00", "rail1": [[0, 0], [30, 0]], "rail2": [[0, 4], [30, 4]], "params": {"underlay": "edge+zigzag"}}
        sat = generate(doc(c))[2]["stitches"]; c["params"]["style"] = "zigzag"; zz = generate(doc(c))[2]["stitches"]
        self.assertLess(zz, sat / 3)
        s = {"id": "s", "type": "satin", "color": "#00f", "points": [[0, 0], [30, 0]], "params": {"width": 3, "style": "zigzag"}}
        d = doc(s); p = generate(d)[0]; self.assertTrue(run_checks(d, p).ok)


class DeliveredFilesUnchanged(unittest.TestCase):
    def test_library_and_peacock_dsts_unchanged(self):
        import hashlib
        from stitchcraft_engine.dst import write_dst
        idx = json.loads((ROOT / "designs" / "library" / "index.json").read_text())
        for e in idx["designs"]:
            d = json.loads((ROOT / "designs" / "library" / e["id"] / f"{e['id']}.esproj").read_text())["doc"]
            self.assertEqual(hashlib.sha256(write_dst(generate(d)[0]).data).hexdigest(), e["sha256"], e["id"])

if __name__ == "__main__":
    unittest.main()


class ExpansionAndAxisCompTests(unittest.TestCase):
    def bbox(self, **params):
        d = doc({"id": "f", "type": "fill", "color": "#f00", "rings": [[[0, 0], [20, 0], [20, 10], [0, 10]]], "params": dict({"angle": 0, "pull_comp": 0, "underlay": "none"}, **params)})
        p = generate(d)[0]; self.assertTrue(run_checks(d, p).ok); return p.bbox()
    def test_fill_expansion_grows_outline(self):
        a, b = self.bbox(), self.bbox(expand_mm=0.3)
        self.assertAlmostEqual(a[0] - b[0], 0.3, delta=0.05); self.assertAlmostEqual(b[2] - a[2], 0.3, delta=0.05)
        self.assertLessEqual(b[1], a[1] - 0.1)
    def test_expansion_shrinks_holes(self):
        from stitchcraft_engine.geometry import point_in_ring
        hole = [[8, 3], [8, 7], [12, 7], [12, 3]]
        def reach(e):
            d = doc({"id": "f", "type": "fill", "color": "#f00", "rings": [[[0, 0], [20, 0], [20, 10], [0, 10]], hole], "params": {"angle": 0, "expand_mm": e, "underlay": "none"}})
            return max(x for x, y in stitched(generate(d)[0]) if x < 10 and 4 < y < 6)       # right end of the rows left of the hole
        self.assertAlmostEqual(reach(0.4) - reach(0), 0.4, delta=0.05)                    # the fill now reaches 0.4 mm further into the hole
    def test_axis_compensation_is_independent_of_direction(self):
        for ang in (0, 45, 90):
            a, b = self.bbox(angle=ang), self.bbox(angle=ang, comp_x=0.8, comp_y=0.8)
            # rows are 0.4 mm apart, so the dimension across the rows moves in 0.4 mm steps: tolerance 0.41
            self.assertAlmostEqual((b[2] - b[0]) - (a[2] - a[0]), 0.8, delta=0.41, msg=ang)
            self.assertAlmostEqual((b[3] - b[1]) - (a[3] - a[1]), 0.8, delta=0.41, msg=ang)
    def test_column_axis_comp(self):
        c = {"id": "c", "type": "column", "color": "#c00", "rail1": [[0, 0], [30, 0]], "rail2": [[0, 3], [30, 3]], "params": {"underlay": "none", "pull_comp": 0}}
        h0 = generate(doc(c))[0].bbox(); c["params"]["comp_y"] = 0.4; h1 = generate(doc(c))[0].bbox()
        self.assertAlmostEqual((h1[3] - h1[1]) - (h0[3] - h0[1]), 0.4, delta=0.05)
    def test_sharp_shape_falls_back_safely(self):
        spike = [[0, 0], [30, 0.2], [0, 0.4], [-1, 0.2]]
        d = doc({"id": "f", "type": "fill", "color": "#f00", "rings": [spike], "params": {"expand_mm": 1.0}})
        try:
            p, notes, _ = generate(d)
        except ValueError:
            return
        self.assertTrue(run_checks(d, p).ok)
