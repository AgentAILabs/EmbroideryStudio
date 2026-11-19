"""Bezier node handles: engine flattening, equivalence with the editor, and that every stage sees the flattened outline."""
import copy, json, math, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine.geometry import bezier_flatten, smooth
from stitchcraft_engine.design import generate, expand_handles
from stitchcraft_engine import quality, export_pipeline as EP, placements
from stitchcraft_engine.schema import validate_design

def catmull_handles(P, closed):
    m = len(P); out = []
    for i in range(m):
        a, b, c = P[(i - 1) % m] if closed or i else P[0], P[i], P[(i + 1) % m] if closed or i < m - 1 else P[-1]
        tx, ty = (c[0] - a[0]) / 6.0, (c[1] - a[1]) / 6.0
        out.append([b[0] - tx, b[1] - ty, b[0] + tx, b[1] + ty])
    return out
def curve_fill(h=None):
    ring = [[0, 0], [30, 0], [30, 30], [0, 30]]
    ob = {"id": "f", "type": "fill", "color": "#c00", "rings": [ring]}
    ob["handles"] = h if h is not None else catmull_handles(ring, True)
    return {"name": "t", "hoop": {"w": 100, "h": 100}, "objects": [ob]}

class Flatten(unittest.TestCase):
    def test_zero_length_handles_are_straight_lines(self):
        P = [(0, 0), (10, 0), (10, 10)]; out = bezier_flatten(P, [[x, y, x, y] for x, y in P], False, 4)
        self.assertEqual(out[0], (0, 0)); self.assertEqual(out[-1], (10, 10)); self.assertTrue(all(abs(y) < 1e-9 for x, y in out[:5]))   # first segment stays on y = 0
    def test_curve_passes_through_every_node_and_is_smooth(self):
        P = [(0, 0), (10, 5), (20, 0), (30, 8)]; h = catmull_handles(P, False); out = bezier_flatten(P, h, False, 10)
        for p in P: self.assertTrue(any(math.hypot(p[0] - q[0], p[1] - q[1]) < 1e-9 for q in out))
        self.assertEqual(len(out), 3 * 10 + 1)
    def test_catmull_handles_reproduce_the_editors_smooth_curve(self):
        P = [(0, 0), (10, 8), (22, 3), (30, 15), (18, 24)]
        a = bezier_flatten(P, catmull_handles(P, True), True, 8); b = smooth(P, True, 8)
        self.assertEqual(len(a), len(b)); self.assertLess(max(math.hypot(x[0] - y[0], x[1] - y[1]) for x, y in zip(a, b)), 1e-6)
    def test_wrong_handle_count_is_ignored_safely(self):
        P = [(0, 0), (5, 5), (9, 0)]; self.assertEqual(bezier_flatten(P, [[0, 0, 0, 0]], False), P)

class Pipeline(unittest.TestCase):
    def test_designs_without_handles_are_returned_unchanged(self):
        d = {"objects": [{"id": "a", "type": "run", "points": [[0, 0], [1, 1]]}]}; self.assertIs(expand_handles(d), d)
    def test_curved_fill_stitches_inside_its_curve_and_exports(self):
        d = curve_fill(); r = EP.export_dst(d); self.assertEqual(r.report["validation"]["physical_machine"][:8], "NOT DONE")
        flat = expand_handles(d)["objects"][0]["rings"][0]; self.assertGreater(len(flat), 40); self.assertNotIn("handles", expand_handles(d)["objects"][0])
        q = quality.quality_report(d, generate(d)[0]); self.assertEqual(q["checks"]["boundary"]["outside"], 0)
        self.assertEqual([i for i in quality.validate_geometry(d) if i["severity"] == "error"], [])
    def test_curve_differs_from_the_polygon(self):
        poly = copy.deepcopy(curve_fill()); del poly["objects"][0]["handles"]
        a = generate(poly)[0]; b = generate(curve_fill())[0]
        self.assertNotEqual([(s.x, s.y) for s in a.stitches], [(s.x, s.y) for s in b.stitches])
    def test_handles_on_runs_satins_and_columns(self):
        P = [[0, 0], [10, 6], [20, 0]]
        for ob in ({"id": "r", "type": "run", "color": "#000", "points": P, "handles": catmull_handles(P, False)},
                   {"id": "s", "type": "satin", "color": "#000", "points": P, "handles": catmull_handles(P, False)},
                   {"id": "c", "type": "column", "color": "#000", "rail1": [[0, 0], [10, 6], [20, 0]], "rail2": [[0, 5], [10, 11], [20, 5]], "handles": catmull_handles(P, False) + catmull_handles([[0, 5], [10, 11], [20, 5]], False)}):
            d = {"name": "t", "hoop": {"w": 100, "h": 100}, "objects": [ob]}; EP.export_dst(d)
    def test_placement_transforms_bake_the_curve(self):
        d = placements.transform_design(curve_fill(), mirror=True); self.assertNotIn("handles", d["objects"][0]); self.assertGreater(len(d["objects"][0]["rings"][0]), 40)
    def test_schema_accepts_good_and_refuses_bad_handles(self):
        validate_design(curve_fill())
        for bad in ([[1, 2, 3]], "x", [[1, 2, 3, "a"]], [[1, 2, 3, float("nan")]]):
            with self.assertRaises(ValueError): validate_design(curve_fill(bad))
if __name__ == "__main__": unittest.main()
