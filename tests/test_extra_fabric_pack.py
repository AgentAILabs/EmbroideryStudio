import csv, hashlib, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from stitchcraft_engine.design import generate
from stitchcraft_engine.dst import write_dst

PACK = ROOT / "testpack" / "v2_extra_fabrics"
class ExtraFabricPack(unittest.TestCase):
    def test_pack_exists_is_unvalidated_and_blank(self):
        m = json.loads((PACK / "MANIFEST.json").read_text()); self.assertFalse(m["physically_validated"]); self.assertEqual(len(m["files"]), 3)
        self.assertEqual({f["file"] for f in m["files"]}, {"23_fabric_satin_fabric.dst", "24_fabric_net.dst", "25_fabric_thick.dst"})
        for r in csv.DictReader(open(PACK / "RESULTS.csv", encoding="utf-8")):
            for c in ("overall_result", "thread_breaks", "puckering", "machine_model", "notes"): self.assertEqual(r[c], "", c)
    def test_files_match_their_projects_and_manifest(self):
        m = {f["file"]: f["sha256"] for f in json.loads((PACK / "MANIFEST.json").read_text())["files"]}
        for name, sha in m.items():
            self.assertEqual(hashlib.sha256((PACK / name).read_bytes()).hexdigest(), sha, name)
            d = json.loads((PACK / name.replace(".dst", ".esproj")).read_text())["doc"]
            p, _, _ = generate(d); from stitchcraft_engine.design import machine
            self.assertEqual(write_dst(p, trim_jumps=machine(d)["trim_jumps"]).sha256, sha, f"{name}: stale against the current engine")
            self.assertIn(d["fabric"], ("satin_fabric", "net", "thick"))
    def test_original_pack_still_has_the_original_six_fabrics(self):
        self.assertEqual(len(list((ROOT / "testpack" / "v2").glob("*_fabric_*.dst"))), 6)
if __name__ == "__main__": unittest.main()
