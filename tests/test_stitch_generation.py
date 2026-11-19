"""Stitch-generation regression tests: movement, stitch length, density, penetration cap, underlay choice, pull compensation, jump / trim counts, wide-satin transit."""
import math, sys, unittest, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine.design import generate
from stitchcraft_engine.model import Cmd
from stitchcraft_engine import export_pipeline as EP

H = {"name": "t", "hoop": {"w": 220, "h": 160, "margin": 3}}
def sq(x, y, w, h): return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
def fill(i, r, **p): return {"id": i, "type": "fill", "color": "#c00000", "rings": [r], "params": p}
def satin(i, pts, w, **p): return {"id": i, "type": "satin", "color": "#c00000", "points": pts, "params": dict(width=w, **p)}
def run(i, pts, col="#c00000"): return {"id": i, "type": "run", "color": col, "points": pts}
def doc(*o, **kw): return dict(H, objects=list(o), **kw)
def doc_ue(*o): return dict(H, objects=list(o), machine={"underlay_entry": 1})

def analyse(d):
    p, notes, st = generate(d); prev = None; lens = []; cells = collections.Counter(); jumps = trims = 0; jl = 0.0; jprev = None
    for s in p.stitches:
        if s.cmd == Cmd.STITCH:
            cells[(int(s.x // 1), int(s.y // 1))] += 1
            if prev is not None: lens.append(math.hypot(s.x - prev[0], s.y - prev[1]))
            prev = (s.x, s.y); jprev = prev
        elif s.cmd == Cmd.JUMP:
            jumps += 1
            if jprev is not None: jl = max(jl, math.hypot(s.x - jprev[0], s.y - jprev[1]))
            prev = None; jprev = (s.x, s.y)
        elif s.cmd in (Cmd.TRIM, Cmd.COLOR_CHANGE): trims += s.cmd == Cmd.TRIM; prev = None
    return {"p": p, "lens": sorted(lens), "pen": max(cells.values()), "jumps": jumps, "trims": trims, "longest_jump": jl, "stitches": len(lens) + 1}


class Movement(unittest.TestCase):
    def test_every_dst_record_within_12_1mm_even_for_far_islands(self):
        res = EP.export_dst(doc(fill("a", sq(0, 0, 30, 20)), fill("b", sq(150, 0, 30, 20))))
        recs, pos, hdr = EP.independent_decode(res.data)
        self.assertLessEqual(max(max(abs(dx), abs(dy)) for dx, dy, k in recs), 121)

    def test_no_stitch_longer_than_machine_limit_in_any_object_type(self):
        for o in (fill("f", sq(0, 0, 40, 30)), satin("s", [[0, 0], [40, 0]], 6), satin("w", [[0, 0], [40, 0]], 12), run("r", [[0, 0], [100, 0]])):
            a = analyse(doc(o)); self.assertLessEqual(a["lens"][-1], 12.1, o["id"])

    def test_wide_satin_does_not_travel_its_own_length_between_underlay_and_top(self):
        # regression: a 9-12 mm satin left the needle at the far end after the centre-walk underlay, then trimmed and jumped ~39 mm back to start the top stitching
        # (opt-in machine setting underlay_entry: enabling it by default would change every delivered, hash-pinned DST)
        for w in (3, 6, 9, 12):
            a = analyse(doc_ue(satin("s", [[0, 0], [40, 0]], w)))
            self.assertLessEqual(a["longest_jump"], w / 2 + 2.5, f"width {w}: jump {a['longest_jump']:.1f}")
        self.assertGreater(analyse(doc(satin("s", [[0, 0], [40, 0]], 9)))["longest_jump"], 30, "the default is unchanged so delivered files stay byte-identical")

    def test_underlaid_fill_does_not_jump_across_itself(self):
        a = analyse(doc_ue(fill("f", sq(0, 0, 40, 30)))); self.assertLess(a["longest_jump"], 35)


class StitchLength(unittest.TestCase):
    def test_stitch_lengths_in_range_for_default_objects(self):
        for o in (fill("f", sq(0, 0, 40, 30)), satin("s", [[0, 0], [40, 0]], 4), run("r", [[0, 0], [100, 0]])):
            a = analyse(doc(o)); L = a["lens"]
            self.assertGreaterEqual(L[len(L) // 100], 0.3, o["id"])                       # 1st percentile: no flood of micro stitches
            self.assertLessEqual(L[-1], 7.0, o["id"])

    def test_short_stitch_share_small(self):
        a = analyse(doc(fill("f", sq(0, 0, 40, 30)))); L = a["lens"]; self.assertLess(sum(1 for x in L if x < 0.3) / len(L), 0.01)


class Density(unittest.TestCase):
    def test_row_spacing_controls_thread_per_area(self):
        def thread_per_mm2(sp):
            a = analyse(doc(fill("f", sq(0, 0, 40, 30), spacing=sp, underlay="none"))); return sum(a["lens"]) / (40 * 30)
        t4, t2 = thread_per_mm2(0.4), thread_per_mm2(0.2)
        self.assertAlmostEqual(t4, 1 / 0.4, delta=0.9); self.assertGreater(t2 / t4, 1.6)         # halving the spacing nearly doubles the thread

    def test_penetration_cap_on_defaults_and_on_dense_fill(self):
        self.assertLessEqual(analyse(doc(fill("f", sq(0, 0, 40, 30))))["pen"], 12)
        self.assertLessEqual(analyse(doc(fill("f", sq(0, 0, 40, 30), spacing=0.15)))["pen"], 14)

    def test_satin_density_follows_spacing(self):
        n = lambda sp: analyse(doc(satin("s", [[0, 0], [40, 0]], 4, spacing=sp, underlay="none")))["stitches"]
        self.assertGreater(n(0.3) / n(0.6), 1.7)


class Underlay(unittest.TestCase):
    def test_underlay_choice(self):
        narrow = generate(doc(satin("s", [[0, 0], [40, 0]], 1.5)))[0]; wide = generate(doc(satin("s", [[0, 0], [40, 0]], 4)))[0]
        self.assertLess(len(narrow.stitches), len(wide.stitches) / 1.5 * 1.5 + 400)
        a_none = analyse(doc(fill("f", sq(0, 0, 40, 30), underlay="none")))["stitches"]; a_u = analyse(doc(fill("f", sq(0, 0, 40, 30))))["stitches"]
        self.assertGreater(a_u, a_none)                                                       # underlay adds stitches; "none" removes them
        s_none = analyse(doc(satin("s", [[0, 0], [40, 0]], 4, underlay="none")))["stitches"]; s_c = analyse(doc(satin("s", [[0, 0], [40, 0]], 4, underlay="center")))["stitches"]
        self.assertGreater(s_c, s_none)


class PullCompensation(unittest.TestCase):
    def test_pull_comp_widens_the_satin(self):
        def ext(pc):
            ys = [s.y for s in generate(doc(satin("s", [[0, 0], [40, 0]], 4, pull_comp=pc, underlay="none")))[0].stitches if s.cmd == Cmd.STITCH]; return max(ys) - min(ys)
        self.assertAlmostEqual(ext(0.5) - ext(0.0), 0.5, delta=0.05)                          # pull_comp widens the column by exactly that many mm in total


class JumpsAndTrims(unittest.TestCase):
    def test_short_hop_has_no_trim_and_long_hop_has_one(self):
        near = analyse(doc(run("a", [[0, 0], [20, 0]]), run("b", [[21, 0], [40, 0]])))
        far = analyse(doc(run("a", [[0, 0], [20, 0]]), run("b", [[90, 0], [110, 0]])))
        self.assertEqual(near["trims"], 1)                                                    # only the final trim
        self.assertGreater(far["trims"], near["trims"])

    def test_same_colour_objects_in_one_thread_no_colour_change(self):
        p, _, st = generate(doc(run("a", [[0, 0], [20, 0]]), run("b", [[0, 10], [20, 10]])))
        self.assertEqual(sum(1 for s in p.stitches if s.cmd == Cmd.COLOR_CHANGE), 0)

    def test_two_threads_one_colour_change(self):
        p, _, st = generate(doc(run("a", [[0, 0], [20, 0]]), run("b", [[0, 10], [20, 10]], "#0000ff")))
        self.assertEqual(sum(1 for s in p.stitches if s.cmd == Cmd.COLOR_CHANGE), 1)


class ImageDerived(unittest.TestCase):
    def test_image_derived_design_exports_with_safe_metrics(self):
        try:
            import numpy as np
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow/NumPy not installed")
        from stitchcraft_engine import raster, photo_validation as PV
        data = (ROOT / "tools" / "e2e_art.png").read_bytes()
        res = raster.digitize_image(data, 60, 5)
        d = dict(H, objects=res["objects"]); exp = EP.export_dst(d); sim = EP.decoded_simulation(d); m = PV.stitch_metrics(sim["stitches"], sim["threads"])
        self.assertLessEqual(m["max_stitch_mm"], 12.1); self.assertLessEqual(m["share_over_7mm"], 0.02); self.assertLessEqual(m["max_penetrations_per_mm2"], 16)
        self.assertLessEqual(m["share_under_0_5mm"], 0.08)


if __name__ == "__main__":
    unittest.main()
