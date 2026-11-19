"""Fuzz-found bugs: malformed designs must be refused with a clear 400, never crash (500) or hang. Seeded, so deterministic."""
import copy, json, math, random, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
import app as server
from stitchcraft_engine.schema import validate_design

BASE = json.loads((ROOT / "designs" / "library" / "kalash" / "kalash.esproj").read_text())["doc"]
def one(**ob): return {"name": "t", "hoop": {"w": 100, "h": 100}, "objects": [dict({"id": "o", "type": "fill", "color": "#c00", "rings": [[[0, 0], [10, 0], [10, 10]]]}, **ob)]}

class Schema(unittest.TestCase):
    BAD = [
        ([], "JSON object"), ({"hoop": True}, "hoop"), ({"hoop": None}, "hoop"), ({"hoop": {"w": 0, "h": 5}}, "hoop width"), ({"hoop": {"w": float("nan"), "h": 5}}, "hoop width"),
        ({"name": ["x"]}, "name"), ({"objects": {}}, "objects"), ({"objects": [1]}, "object 1"), ({"machine": {"max_stitch": [1]}}, "machine"),
        (one(rings="x"), "rings"), (one(rings=[[["a", 1]]]), "number"), (one(rings=[[[0, 0, 0]]]), "[x, y]"), (one(rings=[[[1e308, 0]]]), "number"),
        (one(type="bogus"), "unknown type"), (one(id=5), "id"), (one(params={"spacing": 0}), "spacing"), (one(params={"spacing": 1e-300}), "spacing"),
        (one(params={"stitch_len": -1}), "stitch_len"), (one(params={"width": float("inf")}), "number"), (one(params=[1]), "params"), (one(entry=[1]), "entry"),
        (one(handles=[[1, 2]]), "handle"), (one(color=["#fff"]), "color"),
    ]
    def test_bad_designs_are_refused_with_a_message(self):
        for d, frag in self.BAD:
            with self.assertRaises(ValueError, msg=str(d)[:80]) as cm: validate_design(d)
            self.assertIn(frag, str(cm.exception), str(d)[:80])
    def test_duplicate_ids_are_refused(self):
        d = one(); d["objects"].append(dict(d["objects"][0]))
        with self.assertRaises(ValueError): validate_design(d)
    def test_good_designs_and_ui_shapes_pass(self):
        validate_design(BASE); validate_design(one(params=None)); validate_design({"objects": []}); validate_design({})
        validate_design(one(rings=[])); validate_design(one(params={"spacing": 0.4, "underlay": "edge", "pattern": "contour", "auto_split": True}))
    def test_every_library_and_testpack_design_passes(self):
        for f in list((ROOT / "designs" / "library").glob("*/*.esproj")) + list((ROOT / "testpack" / "v2").glob("*.esproj")):
            validate_design(json.loads(f.read_text())["doc"])

class EmptyGeometryDoesNotCrash(unittest.TestCase):
    def test_empty_rings_fill_is_skipped_with_a_note(self):
        d = one(rings=[]); d["objects"].append({"id": "r", "type": "run", "color": "#000", "points": [[0, 0], [10, 0]]})
        r = server.api_generate(d); self.assertTrue(any("skipped" in n for n in r["notes"])); self.assertGreater(len(r["stitches"]), 2)
    def test_null_params_and_empty_column(self):
        server.api_generate(dict(one(params=None), objects=[dict(one(params=None)["objects"][0]), {"id": "c", "type": "column", "color": "#000", "rail1": [], "rail2": []},
                                                            {"id": "r", "type": "run", "color": "#000", "points": [[0, 0], [9, 0]]}]))
        server.api_autofix(one(rings=[]))

class Fuzz(unittest.TestCase):
    def test_mutated_designs_never_crash(self):
        rnd = random.Random(7); junk = [None, "x", -1, 0, 1e308, float("nan"), float("inf"), [], {}, [[]], [["a", "b"]], True, [[0, 0]], {"w": -5, "h": 1e9}]
        calls = [server.api_generate, server.api_dst, server.api_quality, server.api_travel, server.api_checklist, server.api_report, server.api_machine_check, server.api_autofix]
        crashes = []
        for i in range(40):
            d = copy.deepcopy(BASE)
            for _ in range(rnd.randint(1, 3)):
                o = rnd.choice(d["objects"]); k = rnd.choice(list(o) + ["params", "rings", "points", "entry", "group"])
                if rnd.random() < .6: o[k] = rnd.choice(junk)
                else: d[rnd.choice(["hoop", "machine", "machine_profile", "thread", "name"])] = rnd.choice(junk)
            for f in calls:
                try: f(d)
                except (ValueError, KeyError, TypeError): pass
                except Exception as e: crashes.append((f.__name__, type(e).__name__, str(e)[:60]))
        self.assertEqual(sorted(set(crashes)), [])
if __name__ == "__main__": unittest.main()


class UploadsDoNotCrash(unittest.TestCase):
    def test_malformed_svg_is_a_400_not_a_500(self):
        for t in ("<svg", "<svg xmlns='http://www.w3.org/2000/svg'><path d='M 0 0 L'/></svg>"):
            with self.assertRaises(ValueError): server.api_svg({"svg": t})
    def test_damaged_images_are_refused_cleanly(self):
        import base64
        try: import PIL  # noqa: F401
        except ImportError: self.skipTest("Pillow not installed")
        png = (ROOT / "tools" / "e2e_art.png").read_bytes()
        for blob in (png[:300], png[:80] + b"\x00" * 200 + png[280:], b"\x89PNG\r\n\x1a\n" + b"junk" * 20):
            with self.assertRaises(ValueError): server.api_raster({"data": base64.b64encode(blob).decode(), "width_mm": 60})
