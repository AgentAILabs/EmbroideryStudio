"""Features new in this round: motif runs, text on a path, manual (stitch-level) editing, TrueType / OpenType lettering."""
import base64, json, math, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine.design import generate, run_checks
from stitchcraft_engine.dst import write_dst
from stitchcraft_engine.model import Cmd
from stitchcraft_engine.stitches import motif_run, MOTIFS, warp_to_path, exact_stitches, DigitizingError
from stitchcraft_engine import placements as P
import app as server

def doc(*objs): return {"name": "t", "hoop": {"w": 160, "h": 160, "margin": 3}, "objects": list(objs)}
def lib(n): return json.loads((ROOT / "designs" / "library" / n / f"{n}.esproj").read_text())["doc"]
def stitched(p): return [(s.x, s.y) for s in p.stitches if s.cmd == Cmd.STITCH]


class MotifRunTests(unittest.TestCase):
    def test_every_motif_repeats_and_stays_in_band(self):
        for kind in MOTIFS:
            pts = motif_run([(0, 0), (60, 0)], kind, 6.0, 2.0)
            self.assertTrue(all(abs(y) <= 2.0 + 1e-6 for _, y in pts), kind)
            self.assertAlmostEqual(min(x for x, _ in pts), 0, delta=0.01); self.assertAlmostEqual(max(x for x, _ in pts), 60, delta=0.01)
            if kind != "scallop":
                self.assertGreater(sum(1 for _, y in pts if y < -1.5), 5, kind)
    def test_follows_a_bent_path(self):
        pts = motif_run([(0, 0), (30, 0), (30, 30)], "wave", 5, 1.5)
        self.assertTrue(any(x > 28 and y > 20 for x, y in pts))
    def test_object_and_validation(self):
        d = doc({"id": "m", "type": "run", "color": "#c00", "points": [[0, 0], [60, 0]], "params": {"style": "motif", "motif": "leaf", "motif_size": 6, "motif_amp": 2}})
        p = generate(d)[0]; self.assertTrue(run_checks(d, p).ok)
        with self.assertRaises(DigitizingError): motif_run([(0, 0), (10, 0)], "star")
        with self.assertRaises(DigitizingError): motif_run([(0, 0), (10, 0)], "wave", 0.1)


class TextOnPathTests(unittest.TestCase):
    ARC = [[60 * math.cos(math.pi + t / 20 * math.pi), 60 * math.sin(math.pi + t / 20 * math.pi) + 40] for t in range(21)]
    def test_letters_sit_on_the_arc(self):
        d = doc({"id": "t", "type": "text", "color": "#c80", "text": "SRI LAKSHMI", "height": 8, "path": self.ARC})
        p = generate(d)[0]; self.assertTrue(run_checks(d, p).ok)
        r = [math.hypot(x, y - 40) for x, y in stitched(p)]
        self.assertTrue(all(56 <= v <= 70.5 for v in r))                          # between the arc (60) and arc + letter height (+ satin)
    def test_straight_path_equals_plain_layout_shape(self):
        strokes = [[(0, 0), (0, 10)], [(5, 10), (10, 0)]]
        w = warp_to_path(strokes, [(0, 10), (100, 10)], 10, "start")
        self.assertEqual([[tuple(round(c, 6) for c in q) for q in st] for st in w], [[(0, 0), (0, 10)], [(5, 10), (10, 0)]])
    def test_mirror_and_centre_move_the_path(self):
        o = {"id": "t", "type": "text", "color": "#c80", "text": "AB", "height": 8, "path": [[10, 0], [50, 0]]}
        m = P.transform_design(doc(o), 1, True)["objects"][0]
        self.assertEqual(m["path"], [[-50.0, 0.0], [-10.0, 0.0]])               # mirrored AND walked left-to-right: still readable
        c = P.centre_design(doc(dict(o)))["objects"][0]; self.assertAlmostEqual((c["path"][0][0] + c["path"][-1][0]) / 2, 0, delta=1)


class ManualStitchTests(unittest.TestCase):
    def test_points_are_sewn_exactly(self):
        pts = [[0, 0], [0.4, 3], [0.8, 0], [1.2, 3], [30, 3]]
        out = exact_stitches(pts, 7.0)
        self.assertEqual(out[:4], [tuple(p) for p in pts[:4]]); self.assertTrue(all(math.dist(a, b) <= 7.0 + 1e-9 for a, b in zip(out, out[1:])))
    def test_conversion_is_lossless_for_whole_library_designs(self):
        for n in ("kalash", "peacock_arch"):
            d = lib(n)
            for o in d["objects"]:
                if o["type"] == "embellishment":
                    continue
                r = server.api_to_manual({"design": d, "id": o["id"]})
                self.assertEqual(write_dst(generate(dict(d, objects=[o]))[0]).data, write_dst(generate(dict(d, objects=r["objects"]))[0]).data, (n, o["id"]))
    def test_moving_one_point_changes_only_that_stitch(self):
        d = lib("kalash"); o = next(x for x in d["objects"] if x["type"] == "column")
        m = server.api_to_manual({"design": d, "id": o["id"]})["objects"]
        a = stitched(generate(dict(d, objects=m))[0])
        m[0]["points"][10] = [m[0]["points"][10][0] + 0.5, m[0]["points"][10][1]]
        b = stitched(generate(dict(d, objects=m))[0])
        self.assertEqual(len(a), len(b)); self.assertEqual(sum(1 for x, y in zip(a, b) if math.dist(x, y) > 1e-6), 1)
    def test_bad_requests(self):
        with self.assertRaises(ValueError): server.api_to_manual({"design": lib("kalash"), "id": "nope"})
        emb = next(o["id"] for o in lib("kalash")["objects"] if o["type"] == "embellishment") if any(o["type"] == "embellishment" for o in lib("kalash")["objects"]) else None
        if emb:
            with self.assertRaises(ValueError): server.api_to_manual({"design": lib("kalash"), "id": emb})


class TrueTypeLetteringTests(unittest.TestCase):
    def setUp(self):
        try:
            from PIL import features
            import numpy  # noqa: F401
        except Exception:
            self.skipTest("Pillow / NumPy not available")
        from stitchcraft_engine import lettering
        if not any(p.exists() for p in lettering.FALLBACK_FONTS):
            self.skipTest("no fallback font installed")
        self.L = lettering
    def test_latin_lettering_has_the_requested_height_and_validates(self):
        r = server.api_lettering({"text": "Lakshmi", "height_mm": 12, "color": "#c8102e"})
        d = doc(*r["objects"]); p, _, st = generate(d)
        self.assertAlmostEqual(st["height_mm"], 12, delta=1.0); self.assertTrue(run_checks(d, p).ok)
        self.assertTrue(all(o["color"] == "#c8102e" for o in r["objects"]))
    def test_complex_script_shaping_joins_letters(self):
        if not self.L.shaping_available():
            self.skipTest("Pillow built without Raqm")
        joined, _, i1 = self.L.lettering_objects("مرحبا", 15)
        isolated, _, i2 = self.L.lettering_objects("مرحبا", 15, shaping=False)
        self.assertIn("raqm", i1["shaping"]); self.assertLess(len(joined), len(isolated))
    def test_missing_glyphs_are_refused_not_stitched_as_boxes(self):
        font = next(p for p in self.L.FALLBACK_FONTS if p.exists()).read_bytes()
        with self.assertRaises(ValueError) as e:
            server.api_lettering({"text": "AB తె", "height_mm": 12, "font": base64.b64encode(font).decode()})
        self.assertIn("త", str(e.exception)); self.assertIn("Noto Sans Telugu", str(e.exception))
        r = server.api_lettering({"text": "AB", "height_mm": 12, "font": base64.b64encode(font).decode()})   # covered text from an uploaded font works
        self.assertTrue(r["objects"])
    def test_validation(self):
        for bad in ({"text": "", "height_mm": 10}, {"text": "x" * 200, "height_mm": 10}, {"text": "A", "height_mm": 1}, {"text": "A", "color": "red"},
                    {"text": "A", "language": "telugu!"}, {"text": "A", "direction": "up"}, {"text": "A", "font": base64.b64encode(b"not a font").decode()}):
            with self.assertRaises(ValueError, msg=str(bad)[:40]): server.api_lettering(dict({"height_mm": 10}, **bad))

if __name__ == "__main__":
    unittest.main()
