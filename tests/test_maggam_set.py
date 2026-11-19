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
        budget = {"test_motif": 8, "front_neck": 50, "back_neck": 50, "sleeve_spray": 16}      # was 34 / 315 / 233 / 30 before the quality rounds
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


class QualityRound2Tests(unittest.TestCase):
    def test_gold_density_and_travel_ratio(self):
        from stitchcraft_engine import dst_analyze as A, dst_verify as V
        from stitchcraft_engine.dst import read_dst
        for n in ("maggam_front_neck", "maggam_back_neck", "maggam_sleeve_left", "maggam_test_motif"):
            data = (OUT / f"{n}.dst").read_bytes(); a = A.analyze(data, n)
            self.assertLess(a["travel_mm"] / a["stitched_mm"], 0.14, n)                 # was 0.11-0.18
            adv, _ = V.satin_advance(V._runs(read_dst(data))); self.assertLessEqual(adv / 2, 0.30, n)   # gold 0.27, red 0.24
    def test_neckline_pieces_chain_without_jumps(self):
        d = MaggamSetTests.d["front_neck"] if hasattr(MaggamSetTests, "d") else M.finish(M.front_neck())[0]
        line = [o for o in d["objects"] if (o.get("name") or "").startswith("Neckline")]
        self.assertTrue(all(o["params"]["underlay"] == "edge" for o in line))
        p = generate(d)[0]; ids = {o["id"] for o in line}
        hops, prev, trims, S = [], None, 0, p.stitches
        for k, s in enumerate(S):
            inside = str(s.object_id) in ids
            if inside and s.cmd == Cmd.JUMP and prev is not None and str(prev.object_id) in ids:
                hops.append(math.hypot(s.x - prev.x, s.y - prev.y))
            if inside and s.cmd == Cmd.TRIM:
                nxt = next((x for x in S[k + 1:] if x.cmd == Cmd.STITCH), None)
                trims += bool(nxt is not None and str(nxt.object_id) in ids)        # a cut followed by more neckline = a break in the band
            if s.cmd == Cmd.STITCH:
                prev = s
        self.assertEqual(trims, 0)                                                      # 10 pieces sewn as one continuous band
        self.assertLess(max(hops), 3.0)                                                 # only tiny carried hops inside a piece (v1: 45 mm per piece)


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
    def test_finishes_exactly_at_its_start_point(self):
        p = generate(self.col(end_at_start=True))[0]
        st = [s for s in p.stitches if s.cmd == Cmd.STITCH and s.object_id == "c"]
        locks = 3
        self.assertTrue(any(math.hypot(s.x, s.y) < 1e-6 for s in st[-locks - 2:]))
    def test_default_unchanged(self):
        a = generate(self.col())[0]; b = generate(self.col(end_at_start=False))[0]
        self.assertEqual([(s.x, s.y, s.cmd) for s in a.stitches], [(s.x, s.y, s.cmd) for s in b.stitches])

if __name__ == "__main__":
    unittest.main()
