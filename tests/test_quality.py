"""Geometry validation + quality score. Each rule has a failing and a passing case."""
import json, math, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import quality as Q, export_pipeline as EP
from stitchcraft_engine.design import generate

def doc(*objs): return {"name": "t", "hoop": {"w": 200, "h": 200, "margin": 3}, "objects": list(objs)}
def fill(rings, **kw): return dict({"id": "f", "type": "fill", "color": "#c00", "rings": rings}, **kw)
def sq(x, y, w, h): return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
def circ(cx, cy, r, n=40): return [[cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)] for k in range(n)]
def codes(d): return {i["code"] for i in Q.validate_geometry(d)}

class Geometry(unittest.TestCase):
    def test_valid_shapes_have_no_issues(self):
        self.assertEqual(codes(doc(fill([circ(0, 0, 20), circ(0, 0, 8)]))), set())
        self.assertEqual(codes(doc(fill([sq(0, 0, 30, 30), sq(5, 5, 10, 10)]))), set())
    def test_hole_crossing_outline(self): self.assertIn("GEO_RING_CROSS", codes(doc(fill([sq(0, 0, 30, 30), sq(20, 20, 20, 20)]))))
    def test_hole_outside_outline_is_flagged(self): self.assertIn("GEO_DISJOINT_RING", codes(doc(fill([sq(0, 0, 30, 30), sq(60, 0, 10, 10)]))))
    def test_hole_in_hole(self): self.assertIn("GEO_HOLE_IN_HOLE", codes(doc(fill([sq(0, 0, 60, 60), sq(10, 10, 40, 40), sq(20, 20, 10, 10)]))))
    def test_duplicate_ring_is_error_and_fixable(self):
        g = [i for i in Q.validate_geometry(doc(fill([sq(0, 0, 30, 30), sq(0, 0, 30, 30)]))) if i["code"] == "GEO_DUPLICATE_RING"]
        self.assertTrue(g and g[0]["severity"] == "error" and g[0]["fixable"])
    def test_zero_area_and_too_few_points(self):
        self.assertIn("GEO_ZERO_AREA", codes(doc(fill([[[0, 0], [10, 0], [20, 0]]]))))
        self.assertIn("GEO_TOO_FEW_POINTS", codes(doc(fill([[[0, 0], [10, 0]]]))))
    def test_self_intersection_bowtie(self): self.assertIn("GEO_SELF_INTERSECT", codes(doc(fill([[[0, 0], [30, 25], [30, 0], [0, 10], [0, 30]]]))))
    def test_tiny_fill_warns(self): self.assertIn("GEO_TINY", codes(doc(fill([sq(0, 0, 0.5, 0.5)]))))
    def test_non_finite(self): self.assertIn("GEO_NON_FINITE", codes(doc(fill([[[0, 0], [float("nan"), 3], [5, 5]]]))))
    def test_crossing_satin_rails(self):
        self.assertIn("GEO_RAIL_CROSS", codes(doc({"id": "c", "type": "column", "color": "#000", "rail1": [[0, 0], [20, 10]], "rail2": [[0, 10], [20, 0]]})))
        self.assertEqual(codes(doc({"id": "c", "type": "column", "color": "#000", "rail1": [[0, 0], [20, 0]], "rail2": [[0, 5], [20, 5]]})), set())
    def test_run_with_one_point_and_zero_length(self):
        self.assertIn("GEO_TOO_FEW_POINTS", codes(doc({"id": "r", "type": "run", "color": "#000", "points": [[0, 0]]})))
        self.assertIn("GEO_ZERO_LENGTH", codes(doc({"id": "r", "type": "run", "color": "#000", "points": [[1, 1], [1, 1]]})))
    def test_errors_block_export(self):
        with self.assertRaises(EP.ExportError) as cm: EP.export_dst(doc(fill([sq(0, 0, 30, 30), sq(20, 20, 20, 20)])))
        self.assertEqual(cm.exception.stage in ("geometry", "validate"), True)

class Runtime(unittest.TestCase):
    def test_wide_row_spacing_creates_a_coverage_gap(self):
        d = doc(fill([sq(0, 0, 40, 30)], params={"spacing": 4.0, "underlay": "none"})); p, _, _ = generate(d)
        self.assertTrue(any(i["code"] == "Q_COVERAGE_GAP" for i in Q.quality_report(d, p)["issues"]))
    def test_normal_fill_has_no_gap_and_no_outside_stitches(self):
        d = doc(fill([circ(0, 0, 20)])); p, _, _ = generate(d); r = Q.quality_report(d, p)
        self.assertEqual([i["code"] for i in r["issues"]], []); self.assertEqual(r["checks"]["boundary"]["outside"], 0)
    def test_stitches_far_outside_the_object_are_reported(self):
        d = doc(fill([sq(0, 0, 30, 30)])); p, _, _ = generate(d)
        d2 = doc(fill([sq(0, 0, 10, 10)]))                       # the plan belongs to the bigger shape
        self.assertTrue(any(i["code"] == "Q_OUTSIDE_BOUNDARY" for i in Q.quality_report(d2, p)["issues"]))

class Score(unittest.TestCase):
    def test_eight_categories_with_wording(self):
        d = doc(fill([circ(0, 0, 20)])); p, _, _ = generate(d); r = Q.quality_report(d, p)
        self.assertEqual([c["id"] for c in r["categories"]], [k for k, _ in Q.CATEGORIES]); self.assertEqual(len(r["categories"]), 8)
        self.assertTrue(all(0 <= c["score"] <= 100 and c["detail"] for c in r["categories"]))
        self.assertEqual(r["score"], round(sum(c["score"] for c in r["categories"]) / 8)); self.assertIn("not a prediction", r["disclaimer"])
    def test_hoop_overflow_scores_zero_in_hoop_category(self):
        d = doc(fill([sq(0, 0, 150, 20)])); d["hoop"] = {"w": 100, "h": 100, "margin": 3}; p, _, _ = generate(d)
        self.assertEqual([c for c in Q.quality_report(d, p)["categories"] if c["id"] == "hoop"][0]["score"], 0)
    def test_geometry_error_lowers_score(self):
        good = doc(fill([sq(0, 0, 30, 30)])); bad = doc(fill([[[0, 0], [30, 25], [30, 0], [0, 10], [0, 30]]]))
        pg, _, _ = generate(good); pb, _, _ = generate(bad)
        self.assertLess(Q.quality_report(bad, pb)["categories"][0]["score"], Q.quality_report(good, pg)["categories"][0]["score"])
    def test_library_designs_have_no_geometry_errors(self):
        for f in sorted((ROOT / "designs" / "library").glob("*/*.esproj")):
            d = json.loads(f.read_text())["doc"]
            self.assertEqual([i for i in Q.validate_geometry(d) if i["severity"] == "error"], [], f.name)

if __name__ == "__main__": unittest.main()


class Wiring(unittest.TestCase):
    def test_export_report_and_api_carry_the_score(self):
        import app as server
        d = doc(fill([circ(0, 0, 20)]))
        rep = EP.export_dst(d).report["quality"]
        self.assertEqual(set(rep["categories"]), {k for k, _ in Q.CATEGORIES}); self.assertIn("not a prediction", rep["disclaimer"])
        self.assertEqual(server.api_quality(d)["score"], rep["score"])
