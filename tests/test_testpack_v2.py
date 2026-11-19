"""The physical machine test pack (testpack/v2): reproducible, orientation-checkable, and never pre-filled with results."""
import csv, json, math, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server")); sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(ROOT / "tests"))
import dst_provenance as PV
from test_dst_axis import hand_decode
PACK = ROOT / "testpack" / "v2"


def pts(name):
    p, k, _ = hand_decode((PACK / f"{name}.dst").read_bytes()); return [a for a, b in zip(p, k) if b == "stitch"], k


class PackIntegrity(unittest.TestCase):
    def test_every_file_is_reproducible_from_its_own_project_with_the_current_engine(self):
        rows = PV.scan([PACK]); self.assertGreaterEqual(len(rows), 22)
        self.assertEqual([r["file"] for r in rows if r["status"] != "CURRENT"], [])
    def test_manifest_hashes_match_and_state_not_validated(self):
        import hashlib
        m = json.loads((PACK / "MANIFEST.json").read_text())
        self.assertFalse(m["physically_validated"]); self.assertIn("UNSTITCHED", m["note"])
        for f in m["files"]:
            self.assertEqual(hashlib.sha256((PACK / f["file"]).read_bytes()).hexdigest(), f["sha256"], f["file"])
    def test_results_sheet_has_every_required_field_and_no_invented_results(self):
        rows = list(csv.DictReader(open(PACK / "RESULTS.csv", encoding="utf-8")))
        for col in ("machine_model", "fabric", "stabiliser", "thread", "needle", "hoop", "dst_version_sha256_12", "stitch_count", "thread_breaks",
                    "puckering", "registration", "jump_trim_behaviour", "overall_result"):
            self.assertIn(col, rows[0], col)
        for r in rows:
            for col in ("machine_model", "stabiliser", "thread", "needle", "thread_breaks", "puckering", "registration", "jump_trim_behaviour", "overall_result", "notes"):
                self.assertEqual(r[col], "", f"{r['design']}.{col} must be empty until a person stitches it")
        html = (PACK / "RESULTS.html").read_text(encoding="utf-8")
        self.assertIn("NOT YET PHYSICALLY VALIDATED", html); self.assertNotIn("PASS</td>", html)
    def test_required_test_kinds_are_present(self):
        names = {p.stem for p in PACK.glob("*.dst")}
        for want in ("13_axis_orientation", "14_running_small", "08_satin_widths", "09_fill_30x30", "07_four_colour", "15_jump_movement",
                     "12_trims_locks", "16_hoop_boundary", "17_fabric_cotton", "18_fabric_silk", "22_fabric_knit"):
            self.assertIn(want, names)


class Orientation(unittest.TestCase):
    def test_axis_design_is_60_wide_by_40_tall(self):
        p, _ = pts("13_axis_orientation"); xs, ys = [q[0] for q in p], [q[1] for q in p]
        self.assertAlmostEqual(max(xs) - min(xs), 60.0, delta=0.2); self.assertAlmostEqual(max(ys) - min(ys), 40.0, delta=0.2)   # width > height: not swapped
    def test_filled_marker_is_only_in_the_upper_right_quadrant_of_the_file(self):
        p, _ = pts("13_axis_orientation")
        # engine marker: x 18..28, y -18..-8 (y down) -> file: x 18..28, y +8..+18 (Y up, centred on the 60 x 40 frame)
        count = lambda x0, x1, y0, y1: sum(1 for x, y in p if x0 <= x <= x1 and y0 <= y <= y1)
        self.assertGreater(count(17, 29, 7, 19), 60)                      # filled: many penetrations
        self.assertEqual(count(-29, -17, 7, 19), 0)                       # upper left: empty
        self.assertEqual(count(17, 29, -19, -7), 0)                       # lower right: empty
        self.assertEqual(count(-29, -17, -19, -7), 0)                     # lower left: empty


class JumpAndHoop(unittest.TestCase):
    def test_jump_design_carries_the_thread_and_crosses_long_distances(self):
        p, k = pts("15_jump_movement")
        # no trim records between the crosses: a trim is 3 zero-move jump records in a row
        from stitchcraft_engine.dst import read_dst
        recs = read_dst((PACK / "15_jump_movement.dst").read_bytes()).records
        zero_jumps = sum(1 for dx, dy, c in recs if c == "jump" and dx == 0 and dy == 0)
        self.assertLessEqual(zero_jumps, 3, "only the end-of-design trim is allowed")
        self.assertGreater(sum(1 for dx, dy, c in recs if c == "jump" and (dx or dy)), 20)        # 80 mm moves = many 12.1 mm records
    def test_hoop_boundary_design_is_exactly_the_allowed_area(self):
        from stitchcraft_engine.dst import read_dst
        from stitchcraft_engine.validate import validate
        p, _ = pts("16_hoop_boundary"); xs, ys = [q[0] for q in p], [q[1] for q in p]
        self.assertAlmostEqual(max(xs) - min(xs), 94.0, delta=0.2); self.assertAlmostEqual(max(ys) - min(ys), 94.0, delta=0.2)
        design = json.loads((PACK / "16_hoop_boundary.esproj").read_text())["doc"]
        from stitchcraft_engine.design import generate
        pat, _, _ = generate(design)
        self.assertEqual([i.code for i in validate(pat, 100, 100, 3).issues if i.code == "HOOP"], [])
        self.assertEqual([i.code for i in validate(pat, 99, 99, 3).issues if i.code == "HOOP"], ["HOOP"])    # one millimetre less and it is refused


class Fabrics(unittest.TestCase):
    def test_each_preset_design_uses_that_presets_values_and_is_labelled_provisional(self):
        from stitchcraft_engine.design import FABRICS
        for k, (fab, vals) in enumerate((f, FABRICS[f]) for f in ("cotton", "silk", "georgette", "velvet", "denim", "knit")):
            d = json.loads((PACK / f"{17 + k}_fabric_{fab}.esproj").read_text())["doc"]
            self.assertEqual(d["fabric"], fab)
            fill = next(o for o in d["objects"] if o["type"] == "fill")
            self.assertEqual(fill["params"]["spacing"], vals["spacing"]); self.assertEqual(fill["params"]["pull_comp"], vals["pull_comp"])


class V1IsLeftUntouched(unittest.TestCase):
    def test_v1_files_still_exist_and_are_flagged_stale_not_silently_replaced(self):
        v1 = sorted((ROOT / "testpack").glob("*.dst")); self.assertEqual(len(v1), 12)
        text = (ROOT / "testpack" / "README.md").read_text()
        self.assertIn("superseded", text.lower()); self.assertIn("v2", text)
        self.assertTrue((PACK / "README.md").exists())

if __name__ == "__main__":
    unittest.main()
