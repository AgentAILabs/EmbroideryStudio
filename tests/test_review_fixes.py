"""Regression tests for the code-review findings (2026-11-19)."""
import importlib.util, math, random, sys, time, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine.design import generate, run_checks
from stitchcraft_engine.model import Cmd
from stitchcraft_engine import sequence as SQ, placements as P

def doc(*objs): return {"name": "t", "hoop": {"w": 120, "h": 120, "margin": 3}, "objects": list(objs)}
def longest(p):
    S = [s for s in p.stitches if s.cmd == Cmd.STITCH]
    return max(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(S, S[1:]))


class EndAtStartWithEdgeUnderlay(unittest.TestCase):
    def test_no_full_length_stitch(self):
        for typ in ("column", "satin"):
            o = {"id": "c", "type": "column", "color": "#c00", "rail1": [[0, 0], [30, 0]], "rail2": [[0, 3], [30, 3]], "params": {"underlay": "edge", "end_at_start": True}} \
                if typ == "column" else {"id": "c", "type": "satin", "color": "#c00", "points": [[0, 0], [30, 0]], "params": {"width": 3, "underlay": "edge", "end_at_start": True}}
            d = doc(o); p = generate(d)[0]
            self.assertLess(longest(p), 4.0, typ); self.assertTrue(run_checks(d, p).ok, typ)
    def test_centre_underlay_still_returns(self):
        o = {"id": "c", "type": "column", "color": "#c00", "rail1": [[0, 0], [10, 1], [20, 0]], "rail2": [[0, 0], [10, -1], [20, 0]], "params": {"underlay": "center", "end_at_start": True}}
        S = [s for s in generate(doc(o))[0].stitches if s.cmd == Cmd.STITCH]
        self.assertTrue(any(math.hypot(s.x, s.y) < 1e-6 for s in S[-6:]))


class MotifContainment(unittest.TestCase):
    def test_detail_inside_fill_is_never_moved_before_it(self):
        fill = {"id": "fill", "type": "fill", "color": "#f00", "rings": [[[0, 0], [40, 0], [40, 40], [0, 40]]]}
        detail = {"id": "det", "type": "satin", "color": "#f00", "points": [[18, 20], [22, 20]], "params": {"width": 2}}
        far = {"id": "far", "type": "run", "color": "#f00", "points": [[90, 90], [95, 90]]}
        groups = SQ._motifs([fill, detail, far])
        self.assertIn([0, 1], groups)
        order = SQ._motif_order([fill, detail, far], (20, 20))
        self.assertLess(order.index(0), order.index(1))


class TwoOptPerformance(unittest.TestCase):
    def test_hundreds_of_motifs_are_fast_and_valid(self):
        random.seed(3); objs = []
        for i in range(350):
            x, y = random.uniform(0, 300), random.uniform(0, 300)
            objs.append({"id": f"o{i}", "type": "run", "color": "#f00", "points": [[x, y], [x + 2, y + 1]]})
        t = time.time(); order = SQ._motif_order(objs, (0, 0))
        self.assertLess(time.time() - t, 5.0); self.assertEqual(sorted(order), list(range(350)))
    def test_two_opt_improves_on_nearest_neighbour(self):
        random.seed(7); objs = []
        for i in range(60):
            x, y = random.uniform(0, 200), random.uniform(0, 200)
            objs.append({"id": f"o{i}", "type": "run", "color": "#f00", "points": [[x, y], [x + 1, y]]})
        order = SQ._motif_order(objs, (0, 0))
        length = lambda o: sum(math.dist(objs[a]["points"][-1], objs[b]["points"][0]) for a, b in zip(o, o[1:]))
        self.assertLess(length(order), length(list(range(60))) * 0.5)


class AutofixClosedSatin(unittest.TestCase):
    def test_closed_ring_stays_closed(self):
        ring = [[10 * math.cos(t / 20 * 2 * math.pi), 10 * math.sin(t / 20 * 2 * math.pi)] for t in range(20)]
        d, log = P.autofix(doc({"id": "s", "type": "satin", "color": "#00f", "closed": True, "points": ring, "params": {"width": 0.6}}))
        self.assertEqual(d["objects"][0]["type"], "run"); self.assertTrue(d["objects"][0]["closed"])


class DensityReliefRespectsUserValues(unittest.TestCase):
    def test_default_spaced_objects_are_opened_first(self):
        tight = {"id": "t", "type": "column", "color": "#00f", "rail1": [[i, 0] for i in range(0, 30, 3)], "rail2": [[i, 0.9] for i in range(0, 30, 3)], "params": {"underlay": "none"}}
        user = {"id": "u", "type": "column", "color": "#0a0", "rail1": [[0, 20], [30, 20]], "rail2": [[0, 23], [30, 23]], "params": {"spacing": 0.3}}
        d, log = P.autofix(dict(doc(tight, user), thread="120"))
        u = next(o for o in d["objects"] if o["id"] == "u")
        if any("dense" in l for l in log):
            self.assertEqual(u["params"]["spacing"], 0.3)
        self.assertFalse(any("_autospaced" in o for o in d["objects"]))


class MaggamGenerator(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("mg", ROOT / "tools" / "make_maggam_set.py"); self.M = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.M)
    def test_fern_any_pair_count(self):
        for n in (1, 2, 3, 4, 5):
            b = self.M.B(); self.M.fern(b, 0, 0, 0.0, 18, pairs=n); self.assertEqual(sum(1 for o in b.o if "leaflet" in o["name"]), 2 * n)
        with self.assertRaises(ValueError): self.M.fern(self.M.B(), 0, 0, 0.0, 18, pairs=9)
    def test_mirror_objects_mirrors_fill_angle(self):
        b = self.M.B(); objs = [{"id": "f", "type": "fill", "color": "#f00", "rings": [[[1, 0], [5, 0], [5, 4]]], "params": {"angle": 30}}]
        m = self.M.mirror_objects(objs, b)[0]
        self.assertEqual(m["params"]["angle"], 150.0); self.assertEqual(m["rings"][0][1], [-5.0, 0.0])


class CoveringShapesUseStitchedGeometry(unittest.TestCase):
    def test_expanded_top_cuts_the_base_further(self):
        def base_pts(expand):
            d = doc({"id": "base", "type": "fill", "color": "#f00", "rings": [[[0, 0], [40, 0], [40, 30], [0, 30]]], "params": {"cut_hidden": True, "angle": 0, "underlay": "none"}},
                    {"id": "top", "type": "fill", "color": "#00f", "rings": [[[10, 10], [30, 10], [30, 20], [10, 20]]], "params": {"expand_mm": expand}})
            return [(s.x, s.y) for s in generate(d)[0].stitches if s.cmd == Cmd.STITCH and s.object_id == "base"]
        inside = lambda pts: sum(1 for x, y in pts if 10.0 < x < 30.0 and 12 < y < 18)
        self.assertLess(inside(base_pts(1.0)), inside(base_pts(0.0)))

if __name__ == "__main__":
    unittest.main()
