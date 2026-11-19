"""Simulation data comes from the DST file itself (decoded bytes), not the engine's float plan."""
import json, math, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
import app as server
from stitchcraft_engine import export_pipeline as EP

def lib(n): return json.loads((ROOT / "designs" / "library" / n / f"{n}.esproj").read_text())["doc"]

class DecodedSimulation(unittest.TestCase):
    def test_source_is_the_dst_file_and_matches_the_plan_within_quantisation(self):
        for n in ("kalash", "mandala_rosette", "bride_frame"):
            d = lib(n); plan = server.api_generate(d); dec = server.api_generate(dict(d, decoded=True))
            self.assertEqual((plan["source"], dec["source"]), ("plan", "dst-file"), n)
            self.assertEqual(len(plan["stitches"]), len(dec["stitches"]), n)
            worst = 0.0
            for a, b in zip(plan["stitches"], dec["stitches"]):
                self.assertEqual((a[2], a[3]), (b[2], b[3]), n)                          # same command and thread at every index
                if a[2] in (0, 1): worst = max(worst, math.hypot(a[0] - b[0], a[1] - b[1]))
            self.assertLess(worst, 0.1, f"{n}: decoded positions differ by {worst:.3f} mm")   # 0.1 mm DST unit
            self.assertEqual(len(dec["sha256"]), 64)
    def test_every_stitch_carries_an_object_index(self):
        r = server.api_generate(dict(lib("kalash"), decoded=True)); self.assertTrue(r["objects"])
        self.assertTrue(all(len(s) == 5 for s in r["stitches"])); self.assertTrue(any(s[4] >= 0 for s in r["stitches"]))
        self.assertTrue(all(s[4] < len(r["objects"]) for s in r["stitches"]))
    def test_trims_are_present_as_markers(self):
        r = server.api_generate(dict(lib("mandala_rosette"), decoded=True)); self.assertTrue(any(s[2] == 2 for s in r["stitches"]))
    def test_plan_mode_has_the_same_shape(self):
        r = server.api_generate(lib("kalash")); self.assertTrue(all(len(s) == 5 for s in r["stitches"])); self.assertEqual(r["source"], "plan")
    def test_falls_back_to_the_plan_and_says_so_when_the_file_cannot_be_made(self):
        real = EP.write_dst
        import dataclasses
        def bad(p, *a, **k):
            r = real(p, *a, **k); b = bytearray(r.data); b[512 + 3 * 20] ^= 1; return dataclasses.replace(r, data=bytes(b))
        EP.write_dst = bad
        try: r = server.api_generate(dict(lib("kalash"), decoded=True))
        finally: EP.write_dst = real
        self.assertEqual(r["source"], "plan"); self.assertTrue(any("not a DST file" in n for n in r["notes"]))

if __name__ == "__main__": unittest.main()
