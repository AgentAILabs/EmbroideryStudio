import json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from stitchcraft_engine import export_pipeline as EP
SET = ROOT / "designs" / "blue_set"
NAMES = ["blue_daisy_large", "blue_daisy_small", "blue_copper_sprig", "blue_floral_vine_spray", "blue_peacock_pair", "blue_neck_border_band", "blue_front_neck_full", "blue_peacock_single_left", "blue_peacock_single_right"]

class BlueSet(unittest.TestCase):
    def test_every_element_has_its_own_dst_that_is_the_current_engine_output(self):
        for n in NAMES:
            d = json.loads((SET / f"{n}.esproj").read_text())["doc"]
            self.assertEqual(EP.export_dst(d).data, (SET / f"{n}.dst").read_bytes(), f"{n}: stale - rerun tools/make_blue_set.py")
    def test_reports_never_claim_machine_validation(self):
        for n in NAMES:
            r = json.loads((SET / f"{n}.production-report.json").read_text())
            self.assertIn("NOT DONE", r["validation"]["3_physical_machine"]["result"]); self.assertFalse(r["machine_profile"]["validated"])
    def test_mirror_pair_is_a_true_mirror(self):
        from stitchcraft_engine.dst import read_dst
        a, b = read_dst((SET / "blue_peacock_single_left.dst").read_bytes()), read_dst((SET / "blue_peacock_single_right.dst").read_bytes())
        self.assertLess(abs(len(a.records) - len(b.records)), 0.01 * len(a.records))        # a mirror quantises differently by a record or two
if __name__ == "__main__": unittest.main()
