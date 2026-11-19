"""Travel/trim analysis + optimiser properties."""
import copy, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import travel as T, sequence, export_pipeline as EP
from stitchcraft_engine.design import generate
from stitchcraft_engine.model import Cmd, Pattern, Stitch, ThreadColor

def lib(n): return json.loads((ROOT / "designs" / "library" / n / f"{n}.esproj").read_text())["doc"]
def pat(*items):
    return Pattern("t", [Stitch(x, y, c, 0, o) for x, y, c, o in items], [ThreadColor("a", "#000")])
D = {"hoop": {"w": 200, "h": 200}, "objects": []}            # default machine: trim_distance 3 mm
S, J, TR, CC = Cmd.STITCH, Cmd.JUMP, Cmd.TRIM, Cmd.COLOR_CHANGE

class Classification(unittest.TestCase):
    def verdicts(self, *items): return [m["verdict"] for m in T.travel_report(D, pat(*items))["moves"]]
    def test_long_trimmed_jump_is_justified(self):
        self.assertEqual(self.verdicts((0, 0, S, "a"), (1, 0, S, "a"), (1, 0, TR, "a"), (30, 0, J, "b"), (30, 0, S, "b")), ["trimmed"])
    def test_trim_before_a_tiny_jump_is_unnecessary(self):
        self.assertEqual(self.verdicts((0, 0, S, "a"), (0, 0, TR, "a"), (0.5, 0, J, "b"), (0.5, 0, S, "b")), ["unnecessary trim"])
    def test_long_jump_without_trim_is_missing_a_trim(self):
        self.assertEqual(self.verdicts((0, 0, S, "a"), (30, 0, J, "b"), (30, 0, S, "b")), ["missing trim"])
    def test_short_carried_jump(self):
        self.assertEqual(self.verdicts((0, 0, S, "a"), (2, 0, J, "b"), (2, 0, S, "b")), ["carried"])
    def test_colour_change_and_empty_fabric_measure(self):
        r = T.travel_report(D, pat((0, 0, S, "a"), (0, 0, CC, "b"), (5, 0, J, "b"), (5, 0, S, "b")))
        self.assertEqual([m["verdict"] for m in r["moves"]], ["colour change"]); self.assertEqual(r["totals"]["colour_changes"], 1)
        r = T.travel_report(dict(D, machine={"trim_distance": 10}), pat((0, 0, S, "a"), (8, 0, J, "b"), (8, 0, S, "b")))
        self.assertEqual(r["moves"][0]["verdict"], "carried"); self.assertGreater(r["moves"][0]["over_empty_mm"], 3.0)

class RealDesigns(unittest.TestCase):
    def test_library_designs_have_no_missing_trims_and_consistent_counts(self):
        for n in ("kalash", "mandala_rosette", "peacock_arch", "bride_frame"):
            d = lib(n); p, _, st = generate(d); r = T.travel_report(d, p)
            self.assertEqual(r["verdicts"].get("missing trim", 0), 0, n); self.assertEqual(r["totals"]["trims"], st["trims"], n)
            self.assertGreaterEqual(r["totals"]["colour_changes"], r["totals"]["minimum_colour_changes"], n)
            self.assertTrue(all(o["entry"] and o["exit"] for o in r["objects"]), n)
    def test_export_report_summarises_travel(self):
        self.assertIn("jump_mm", EP.export_dst(lib("kalash")).report["travel"])

class OptimiserProperties(unittest.TestCase):
    def test_never_worse_never_changes_colour_order_or_overlap_order(self):
        for n in ("mandala_rosette", "marigold_flower", "temple_border", "floral_vine_border", "peacock_arch"):
            d = lib(n); new, _ = sequence.optimize_sequence(copy.deepcopy(d))
            self.assertLessEqual(sequence.machine_seconds(sequence.travel_metrics(new)), sequence.machine_seconds(sequence.travel_metrics(d)) + 1e-6, n)
            self.assertEqual(sorted(o["id"] for o in new["objects"]), sorted(o["id"] for o in d["objects"]), n)                 # nothing lost or added
            cols = lambda dd: [o.get("color") for o in dd["objects"] if o.get("type") != "embellishment"]
            self.assertEqual(sorted(cols(new)), sorted(cols(d)), n)
            self.assertEqual([c for i, c in enumerate(cols(new)) if i == 0 or c != cols(new)[i - 1]], [c for i, c in enumerate(cols(d)) if i == 0 or c != cols(d)[i - 1]], n)   # colour blocks keep their order
            pos = {o["id"]: i for i, o in enumerate(new["objects"])}
            def box(o):
                pts = [p for r in o.get("rings", []) for p in r] + [p for k in ("points", "rail1", "rail2") for p in o.get(k, [])]
                return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)) if pts else None
            objs = d["objects"]
            for i, a in enumerate(objs):
                for b in objs[i + 1:]:
                    ba, bb = box(a), box(b)
                    if ba and bb and sequence._overlap(ba, bb):
                        self.assertLess(pos[a["id"]], pos[b["id"]], f"{n}: {a['id']}/{b['id']} layering changed")
    def test_deterministic(self):
        d = lib("mandala_rosette")
        self.assertEqual(json.dumps(sequence.optimize_sequence(copy.deepcopy(d))[0], sort_keys=True), json.dumps(sequence.optimize_sequence(copy.deepcopy(d))[0], sort_keys=True))

if __name__ == "__main__": unittest.main()
