"""Split-for-hoop and micro-stitch cleanup."""
import copy, io, json, math, sys, unittest, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import hooping, export_pipeline as EP
from stitchcraft_engine.design import generate, clean_micro_stitches, machine
from stitchcraft_engine.model import Cmd, Pattern, Stitch
import app as server

def big():
    objs = [{"id": f"r{i}", "type": "run", "color": "#000", "points": [[-150 + i * 30, -120], [-150 + i * 30, 120]]} for i in range(11)]
    objs += [{"id": "band", "type": "satin", "color": "#c00", "points": [[-160, 0], [160, 0]], "params": {"width": 3}},
             {"id": "f", "type": "fill", "color": "#00c", "rings": [[[-20, -20], [20, -20], [20, 20], [-20, 20]]]}]
    return {"name": "big", "hoop": {"w": 200, "h": 150, "margin": 8}, "objects": objs}
def total_len(objs):
    n = 0.0
    for o in objs:
        if o.get("type") in ("run", "satin"): n += sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(o["points"], o["points"][1:]))
    return n

class Split(unittest.TestCase):
    def test_design_that_fits_is_one_tile(self):
        d = big(); d["hoop"] = {"w": 600, "h": 600, "margin": 8}; r = hooping.split_for_hoop(d, 600, 600); self.assertTrue(r["fits"]); self.assertEqual(len(r["tiles"]), 1)
    def test_partition_nothing_lost_nothing_duplicated(self):
        d = big(); r = hooping.split_for_hoop(d, 200, 150, 8, marks=False); self.assertFalse(r["fits"]); self.assertGreater(len(r["tiles"]), 1)
        got = [o for t in r["tiles"] for o in t["design"]["objects"]]
        self.assertEqual(len({o["id"] for o in got}), len(got))                                  # no duplicate ids
        self.assertEqual(sum(1 for o in got if o["id"] == "f"), 1)                               # the fill is whole and in exactly one tile
        self.assertAlmostEqual(total_len(got), total_len(d["objects"]), delta=1.0)               # cutting a run keeps its length (to the 0.8 mm sliver rule)
    def test_every_tile_fits_the_hoop_and_exports(self):
        r = hooping.split_for_hoop(big(), 200, 150, 8)
        for t in r["tiles"]:
            res = EP.export_dst(t["design"]); w, h = res.report["size_mm"]; self.assertLessEqual(w, 200 - 16 + 1e-6, t["name"]); self.assertLessEqual(h, 150 - 16 + 1e-6, t["name"])
    def test_alignment_marks_are_shared_grid_points(self):
        r = hooping.split_for_hoop(big(), 200, 150, 8); marks = {}
        for t in r["tiles"]:
            ms = [o for o in t["design"]["objects"] if o["id"].startswith("mark_")]; self.assertEqual(len(ms), 8)          # 4 crosses x 2 strokes
            for o in ms:
                (x0, y0), (x1, y1) = o["points"]; marks.setdefault((round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)), set()).add(t["name"])
        self.assertTrue(any(len(v) > 1 for v in marks.values()), "neighbouring tiles must share at least one physical mark")
    def test_oversize_object_is_reported(self):
        d = big(); d["objects"].append({"id": "huge", "type": "fill", "color": "#0a0", "rings": [[[-150, -100], [150, -100], [150, 100], [-150, 100]]]})
        self.assertIn("huge", hooping.split_for_hoop(d, 200, 150)["oversize"])
    def test_limits(self):
        with self.assertRaises(ValueError): hooping.split_for_hoop(big(), 30, 30, 10)
        with self.assertRaises(ValueError): hooping.split_for_hoop({"objects": []}, 200, 150)
    def test_api_returns_a_zip_of_valid_tiles(self):
        data, rep = server.api_split(big()); z = zipfile.ZipFile(io.BytesIO(data)); names = z.namelist()
        self.assertTrue(all(t["status"] == "ok" for t in rep["tiles"])); self.assertEqual(len([n for n in names if n.endswith(".dst")]), len(rep["tiles"])); self.assertIn("SPLIT-README.txt", names)
    def test_the_blue_neckline_splits_into_valid_tiles(self):
        d = json.loads((ROOT / "designs" / "blue_set" / "blue_front_neck_full.esproj").read_text())["doc"]; d["hoop"] = {"w": 260, "h": 300, "margin": 8}
        _, rep = server.api_split(d); self.assertEqual(len(rep["tiles"]), 4); self.assertTrue(all(t["status"] == "ok" for t in rep["tiles"]))

class MicroClean(unittest.TestCase):
    def pat(self, pts):
        return Pattern("t", [Stitch(0, 0, Cmd.JUMP, 0, "a")] + [Stitch(x, y, Cmd.STITCH, 0, "a") for x, y in pts], [])
    def test_short_stitch_is_dropped_but_entry_and_tail_stay(self):
        p = self.pat([(0, 0), (2, 0), (2.1, 0), (4, 0), (6, 0)]); n = clean_micro_stitches(p, 0.4)
        self.assertEqual(n, 1); xs = [s.x for s in p.stitches if s.cmd == Cmd.STITCH]; self.assertEqual(xs, [0, 2, 4, 6])
    def test_entry_stitch_after_a_jump_is_never_removed(self):
        p = self.pat([(0, 0), (0.1, 0), (3, 0)]); clean_micro_stitches(p, 0.4); self.assertEqual(p.stitches[1].cmd, Cmd.STITCH); self.assertEqual(p.stitches[1].x, 0)
    def test_off_by_default_and_clamped(self):
        self.assertEqual(machine({})["micro_clean"], 0.0); self.assertEqual(machine({"machine": {"micro_clean": 5}})["micro_clean"], 0.8); self.assertEqual(machine({"machine": {"micro_clean": 0.05}})["micro_clean"], 0.2)
    def test_in_a_real_design_it_removes_short_stitches_and_still_exports(self):
        d = json.loads((ROOT / "designs" / "blue_set" / "blue_peacock_pair.esproj").read_text())["doc"]
        def short(dd):
            p = generate(dd)[0]; prev = None; n = 0
            for s in p.stitches:
                if s.cmd == Cmd.STITCH and prev is not None and math.hypot(s.x - prev[0], s.y - prev[1]) < 0.4: n += 1
                prev = (s.x, s.y) if s.cmd in (Cmd.STITCH, Cmd.JUMP) else None
            return n
        d0 = copy.deepcopy(d); d0.setdefault("machine", {})["micro_clean"] = 0.0
        d1 = copy.deepcopy(d); d1.setdefault("machine", {})["micro_clean"] = 0.4
        self.assertLess(short(d1), short(d0) * 0.5); EP.export_dst(d1)
if __name__ == "__main__": unittest.main()
