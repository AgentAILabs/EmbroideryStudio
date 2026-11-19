"""testpack/ricoma_diag: reproducible, structurally clean, never marked validated."""
import hashlib, json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "tools"))
import make_ricoma_diag as M


class Diag(unittest.TestCase):
    def test_manifest_matches_files_and_fresh_build(self):
        man = json.loads((ROOT / "testpack" / "ricoma_diag" / "MANIFEST.json").read_text()); self.assertFalse(man["physically_validated"])
        for f in man["files"]:
            self.assertEqual(f["software_checks"], "no FAILED check"); self.assertFalse(f["physically_validated"])
            self.assertEqual(hashlib.sha256((ROOT / "testpack" / "ricoma_diag" / f["file"]).read_bytes()).hexdigest(), f["sha256"])
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual([f["sha256"] for f in M.build(Path(t))], [f["sha256"] for f in man["files"]])

    def test_names_are_short_uppercase_and_header_is_512_bytes(self):
        for p in (ROOT / "testpack" / "ricoma_diag").glob("*.DST"):
            self.assertRegex(p.stem, r"^[A-Z0-9]{1,8}$"); d = p.read_bytes(); self.assertEqual((len(d) - 512) % 3, 0); self.assertTrue(d.startswith(b"LA:"))
            self.assertEqual(d[-3:], b"\x00\x00\xf3")


if __name__ == "__main__":
    unittest.main()
