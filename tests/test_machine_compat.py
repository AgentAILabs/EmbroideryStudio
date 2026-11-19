"""Header label / file name safety and the byte-level DST pre-flight (regressions: CR in a name injected a header line; non-ASCII names crashed the export)."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import export_pipeline as EP, machine_compat as MC
import app as server

def design(name): return {"name": name, "hoop": {"w": 100, "h": 100, "margin": 3}, "objects": [{"id": "a", "type": "run", "color": "#000000", "points": [[0, 0], [20, 0], [20, 10]]}]}
BAD = ["my design: v2", "a\rb", "blouse\x1aX", "చీర", "Ünï", "", "x" * 40, "../../etc", "NUL", "a:b\r\n"]


class Names(unittest.TestCase):
    def test_label_is_plain_ascii_and_bounded(self):
        for n in BAD:
            l = MC.label_for(n); self.assertRegex(l, r"^[A-Z0-9 _-]{1,16}$", repr(n))
    def test_filename_rules(self):
        for n in BAD:
            self.assertRegex(MC.filename_for(n), r"^[A-Z0-9]{1,8}\.DST$", repr(n))
    def test_safe_names_unchanged(self):
        self.assertEqual(MC.label_for("01_flower"), "01_FLOWER"); self.assertEqual(MC.filename_for("flower"), "FLOWER.DST")
    def test_non_ascii_names_do_not_collide(self):
        self.assertNotEqual(MC.filename_for("చీర"), MC.filename_for("రవిక"))
    def test_collisions_get_suffix(self):
        self.assertEqual(MC.filename_for("flower", taken=("FLOWER.DST",)), "FLOWER1.DST")


class Export(unittest.TestCase):
    def test_every_hostile_name_exports_and_preflight_passes(self):
        for n in BAD:
            r = EP.export_dst(design(n)); p = MC.preflight(r.data, MC.filename_for(n), {"w": 100, "h": 100})
            self.assertEqual(p["verdict"], "PASSED", (n, [c for c in p["checks"] if c["result"] in ("FAILED", "WARNING")]))
    def test_header_has_exactly_twelve_fields(self):
        r = EP.export_dst(design("a\rb:c")); self.assertEqual(len(r.data[:512].split(b"\x1a")[0].split(b"\r")) - 1, 12)

class Preflight(unittest.TestCase):
    def setUp(self): self.data = EP.export_dst(design("T")).data
    def res(self, data, **kw): return {c["name"]: c["result"] for c in MC.preflight(data, **kw)["checks"]}
    def test_passes_real_file(self): self.assertEqual(MC.preflight(self.data, "T.DST")["verdict"], "PASSED")
    def test_detects_injected_header_line(self):
        bad = self.data.replace(b"LA:T ", b"LA:T\rX ", 1)
        self.assertEqual(MC.preflight(bad)["verdict"], "FAILED")
    def test_detects_missing_end(self): self.assertEqual(MC.preflight(self.data[:-3])["verdict"], "FAILED")
    def test_detects_wrong_colour_count(self):
        self.assertEqual(MC.preflight(self.data.replace(b"CO:  0", b"CO:  3", 1))["verdict"], "FAILED")
    def test_detects_bad_extents(self):
        self.assertEqual(MC.preflight(self.data.replace(b"+X:  100", b"+X:  150", 1))["verdict"], "FAILED")
    def test_bad_filename_is_only_a_warning_labelled_unverified(self):
        p = MC.preflight(self.data, "my-design.dst"); self.assertEqual(p["verdict"], "PASSED_WITH_WARNINGS")
        self.assertEqual(next(c for c in p["checks"] if c["name"].startswith("file name"))["basis"], "unverified advice")
    def test_hoop_overflow(self):
        self.assertEqual(MC.preflight(self.data, hoop={"w": 10, "h": 10})["verdict"], "FAILED")
    def test_truncated(self): self.assertEqual(MC.preflight(self.data[:100])["verdict"], "FAILED")
    def test_never_claims_acceptance(self): self.assertIn("does not prove", MC.preflight(self.data)["note"])

if __name__ == "__main__":
    unittest.main()
