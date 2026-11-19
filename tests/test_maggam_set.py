"""The maggam blouse set: reproducible, symmetric, verified, low-trim (end_at_start + continuous ferns)."""
import importlib.util, json, math, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine.design import generate
from stitchcraft_engine.dst import write_dst
from stitchcraft_engine.model import Cmd
from stitchcraft_engine import checklist

spec = importlib.util.spec_from_file_location("mg", ROOT / "tools" / "make_maggam_set.py"); M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
OUT = ROOT / "designs" / "maggam_set"


class MaggamSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = {f.__name__: M.finish(f())[0] for f in (M.test_motif, M.front_neck, M.back_neck, M.sleeve_spray)}
    def test_committed_files_are_reproducible(self):
        for k in ("test_motif", "front_neck", "back_neck"):
            d = self.d[k]; self.assertEqual(write_dst(generate(d)[0]).data, (OUT / f"{d['name']}.dst").read_bytes(), k)
    def test_every_design_passes_all_fifteen_checks(self):
        for k, d in self.d.items():
            c = checklist.evaluate(d); self.assertTrue(c["export_allowed"], k)
            self.assertEqual(c["passed"], 15, (k, [(i["n"], i["evidence"]) for i in c["items"] if i["level"] not in ("PASS", "N/A")]))
    def test_trim_budget(self):
        budget = {"test_motif": 10, "front_neck": 90, "back_neck": 70, "sleeve_spray": 30}
        for k, d in self.d.items():
            self.assertLessEqual(generate(d)[2]["trims"], budget[k], k)
    def test_front_neck_is_symmetric(self):
        p = generate(self.d["front_neck"])[0]; b = p.bbox(); cx = (b[0] + b[2]) / 2
        cells = {(round((s.x - cx) / 1.5), round(s.y / 1.5)) for s in p.stitches if s.cmd == Cmd.STITCH}
        mirrored = {(-x, y) for x, y in cells}
        self.assertGreater(len(cells & mirrored) / len(cells | mirrored), 0.85)
    def test_two_colours_red_then_gold_and_stones_listed(self):
        for k, d in self.d.items():
            seq = [c["hex"] for c in generate(d)[2]["color_sequence"]]
            self.assertEqual(seq, [M.RED, M.GOLD], k)
            self.assertTrue(any(o["type"] == "embellishment" and o["kind"] == "stone" for o in d["objects"]), k)
    def test_sleeves_are_a_true_mirror_pair(self):
        from stitchcraft_engine.dst import read_dst
        L, R = (read_dst((OUT / f"maggam_sleeve_{s}.dst").read_bytes()) for s in ("left", "right"))
        self.assertEqual(L.color_changes, R.color_changes)
        xl = [p[0] for p in L.positions]; xr = [p[0] for p in R.positions]
        self.assertAlmostEqual(max(xl) - min(xl), max(xr) - min(xr), delta=6)


class EndAtStartTests(unittest.TestCase):
    def col(self, **params):
        return {"name": "t", "hoop": {"w": 100, "h": 100}, "objects": [{"id": "c", "type": "column", "color": "#c00", "rail1": [[0, 0], [5, 1.2], [10, 1.0]],
                "rail2": [[0, 0], [5, -1.2], [10, -1.0]], "params": dict({"underlay": "center"}, **params)}]}
    def test_object_ends_where_it_started_without_a_jump(self):
        p = generate(self.col(end_at_start=True))[0]
        st = [s for s in p.stitches if s.cmd == Cmd.STITCH]
        body = [s for s in p.stitches if s.cmd in (Cmd.STITCH, Cmd.JUMP)]
        self.assertEqual(sum(1 for s in body[2:] if s.cmd == Cmd.JUMP), 0)
        lockless = [s for s in st if math.hypot(s.x, s.y) < 1.6]
        self.assertTrue(lockless)                                     # thread is back near the start (0,0)
    def test_default_unchanged(self):
        a = generate(self.col())[0]; b = generate(self.col(end_at_start=False))[0]
        self.assertEqual([(s.x, s.y, s.cmd) for s in a.stitches], [(s.x, s.y, s.cmd) for s in b.stitches])

if __name__ == "__main__":
    unittest.main()
