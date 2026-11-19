"""testpack/photo_v1: reproducible from the generator, hash-listed, honest (never marked validated)."""
import hashlib, json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "tools"))
try:
    import numpy, PIL; HAVE = True
except ImportError:
    HAVE = False


@unittest.skipUnless(HAVE, "Pillow/NumPy not installed")
class PhotoPack(unittest.TestCase):
    def test_manifest_hashes_match_files_and_a_fresh_build(self):
        import make_photo_testfiles as M
        man = json.loads((ROOT / "testpack" / "photo_v1" / "MANIFEST.json").read_text())
        self.assertFalse(man["physically_validated"])
        for f in man["files"]:
            self.assertFalse(f["physically_validated"])
            self.assertEqual(hashlib.sha256((ROOT / "testpack" / "photo_v1" / f["file"]).read_bytes()).hexdigest(), f["sha256"], f["file"])
        with tempfile.TemporaryDirectory() as t:
            fresh = M.build(Path(t))
        self.assertEqual([f["sha256"] for f in fresh], [f["sha256"] for f in man["files"]], "the committed files are not what the current engine produces - regenerate with tools/make_photo_testfiles.py")

    def test_files_pass_the_independent_dst_checks(self):
        from stitchcraft_engine import sections as SEC
        for p in sorted((ROOT / "testpack" / "photo_v1").glob("*.dst")):
            ms = SEC.dst_checks(p.read_bytes(), {"w": 100, "h": 100, "margin": 3})
            bad = [m for m in ms if m["result"] == "FAILED"]
            self.assertEqual(bad, [], p.name)


if __name__ == "__main__":
    unittest.main()
