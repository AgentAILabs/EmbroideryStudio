import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from stitchcraft_engine.design import generate
from stitchcraft_engine.model import Cmd

def d(**extra):
    ob = {"id": "f", "type": "fill", "color": "#c00", "rings": [[[0, 0], [30, 0], [30, 20], [0, 20]]]}; ob.update(extra)
    return {"name": "t", "hoop": {"w": 100, "h": 100}, "objects": [ob]}
def first_stitch(design):
    p, notes, _ = generate(design); return next(s for s in p.stitches if s.cmd == Cmd.STITCH), p, notes
def run(points, **extra):
    ob = {"id": "r", "type": "run", "color": "#000", "points": points}; ob.update(extra)
    return {"name": "t", "hoop": {"w": 100, "h": 100}, "objects": [ob]}

class EntryExit(unittest.TestCase):
    def test_entry_chooses_the_nearer_orientation_without_changing_the_stitches(self):
        base, pa, _ = first_stitch(d()); b, pb, nb = first_stitch(d(entry=[0, 0]))
        dbase = (base.x ** 2 + base.y ** 2) ** .5; db = (b.x ** 2 + b.y ** 2) ** .5
        self.assertLess(db, dbase); self.assertLess(db, 5); self.assertTrue(any("reverse" in n for n in nb))
        key = lambda p: sorted((round(s.x, 3), round(s.y, 3)) for s in p.stitches if s.cmd == Cmd.STITCH)
        self.assertEqual(len(key(pa)), len(key(pb)))                       # same number of penetrations
    def test_a_run_starts_at_the_end_nearest_the_entry_and_finishes_near_the_exit(self):
        s, p, _ = first_stitch(run([[0, 0], [40, 0]], entry=[40, 0])); self.assertGreater(s.x, 20)
        st = [x for x in p.stitches if x.cmd == Cmd.STITCH]; self.assertLess(st[-1].x, 20)
        s2, p2, _ = first_stitch(run([[0, 0], [40, 0]], exit=[0, 0])); st2 = [x for x in p2.stitches if x.cmd == Cmd.STITCH]; self.assertLess(st2[-1].x, 20)
    def test_no_hint_means_no_change_and_invalid_hint_is_reported_not_fatal(self):
        a = first_stitch(d())[1].stitches; b = first_stitch(d(entry=None))[1].stitches
        self.assertEqual([(s.x, s.y) for s in a], [(s.x, s.y) for s in b])
        s, p, notes = first_stitch(d(entry=["x", 1])); self.assertTrue(any("ignored" in n for n in notes))
    def test_manual_objects_are_never_reversed(self):
        pts = [[0, 0], [5, 0], [10, 0]]
        des = {"name": "t", "hoop": {"w": 100, "h": 100}, "objects": [{"id": "m", "type": "manual", "color": "#000", "points": pts, "entry": [10, 0]}]}
        s, p, _ = first_stitch(des); self.assertLess(s.x, 5)
if __name__ == "__main__": unittest.main()
