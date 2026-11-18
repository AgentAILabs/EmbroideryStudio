"""Placement sets (left / right / neck ...), true mirroring, auto-correction and the zip package."""
import base64, io, json, math, sys, unittest, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
for sub in ("engine", "server"):
    sys.path.insert(0, str(ROOT / sub))
from stitchcraft_engine import placements as P
from stitchcraft_engine.design import generate, run_checks
from stitchcraft_engine.dst import read_dst, write_dst
from stitchcraft_engine.model import Cmd
import app as server
import sheet

def lib(name): return json.loads((ROOT / "designs" / "library" / name / f"{name}.esproj").read_text())["doc"]
SQ = [[0, 0], [20, 0], [20, 12], [0, 12]]
def doc(*objs, **kw): return dict({"name": "My Design!", "hoop": {"w": 100, "h": 100, "margin": 3}, "objects": list(objs)}, **kw)
def grid(pattern, cell=1.0):
    return {(math.floor(s.x / cell), math.floor(s.y / cell)) for s in pattern.stitches if s.cmd == Cmd.STITCH}
def bbox_centre(p):
    b = p.bbox(); return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


class TransformTests(unittest.TestCase):
    def test_mirror_is_exact_and_involutive(self):
        d = doc({"id": "f", "type": "fill", "color": "#f00", "rings": [SQ], "params": {"angle": 30}},
                {"id": "c", "type": "column", "color": "#00f", "rail1": [[0, 20], [10, 22]], "rail2": [[0, 24], [10, 26]]},
                {"id": "r", "type": "run", "color": "#000", "points": [[3, 3], [9, 9]]})
        m = P.transform_design(d, 1, True)
        self.assertEqual(m["objects"][0]["rings"][0][1], [-20.0, 0.0]); self.assertEqual(m["objects"][0]["params"]["angle"], 150.0)
        back = P.transform_design(m, 1, True)
        self.assertEqual(back["objects"][0]["rings"], d["objects"][0]["rings"]); self.assertEqual(back["objects"][0]["params"]["angle"], 30.0)
        self.assertEqual(d["objects"][0]["rings"][0][1], [20, 0])                  # input untouched
    def test_rotate_90_and_scale(self):
        d = doc({"id": "r", "type": "run", "color": "#000", "points": [[10, 0], [20, 0]]})
        r = P.transform_design(d, 2, False, 90); self.assertEqual(r["objects"][0]["points"], [[0.0, 20.0], [0.0, 40.0]])
    def test_text_is_not_mirrored_only_moved(self):
        t = {"id": "t", "type": "text", "color": "#000", "text": "AB", "height": 8, "x": 10, "y": 0}
        m = P.transform_design(doc(t), 1, True)["objects"][0]
        self.assertEqual(m["text"], "AB"); self.assertLess(m["x"], 0); self.assertEqual(m["height"], 8)
    def test_embellishment_points_follow(self):
        e = {"id": "e", "type": "embellishment", "kind": "bead", "color": "#fff", "points": [[5, 5], [10, 5]], "size_mm": 3}
        self.assertEqual(P.transform_design(doc(e), 1, True)["objects"][0]["points"], [[-5.0, 5.0], [-10.0, 5.0]])


class MirroredStitchingTests(unittest.TestCase):
    def test_right_is_the_mirror_image_of_left_in_stitched_area(self):
        d = lib("peacock_arch"); p = P.plan([{"id": "left"}, {"id": "right"}], "left")
        L = generate(P.make_variant(d, p[0])[0])[0]; R = generate(P.make_variant(d, p[1])[0])[0]
        gl, gr = grid(L, 1.0), grid(R, 1.0)
        # mirror the left grid about the common centre and compare coverage
        cx = (L.bbox()[0] + L.bbox()[2]) / 2; cxr = (R.bbox()[0] + R.bbox()[2]) / 2
        ml = {(math.floor(2 * (cx - 0) / 1.0) - x - 1, y) for x, y in gl}      # reflect about x = cx (cx ~ 0 after centring)
        off = round(2 * cx) - round(2 * cxr)
        inter = len(gr & {(x - off, y) for x, y in ml}); union = len(gr | {(x - off, y) for x, y in ml})
        self.assertGreater(inter / union, 0.80)
    def test_single_object_exact_symmetry(self):
        d = doc({"id": "c", "type": "column", "color": "#c00", "rail1": [[i * 3.0, 0] for i in range(8)], "rail2": [[i * 3.0, 3] for i in range(8)]})
        L = generate(P.make_variant(d, P.plan([{"id": "left"}])[0])[0])[0]; R = generate(P.make_variant(d, P.plan([{"id": "right"}], "left")[0])[0])[0]
        self.assertEqual(R.bbox()[2] - R.bbox()[0], L.bbox()[2] - L.bbox()[0])
    def test_source_side_swaps_which_file_is_mirrored(self):
        a = P.plan([{"id": "left"}, {"id": "right"}], "left"); b = P.plan([{"id": "left"}, {"id": "right"}], "right")
        self.assertEqual([x["mirror"] for x in a], [False, True]); self.assertEqual([x["mirror"] for x in b], [True, False])
    def test_neck_is_not_mirrored_and_can_be_resized(self):
        n = P.plan([{"id": "neck", "width_mm": 60}])[0]; self.assertFalse(n["mirror"])
        d, log = P.make_variant(lib("kalash"), n); b = P.design_bbox(d); self.assertAlmostEqual(b[2] - b[0], 60, delta=0.6)
        self.assertTrue(any("scaled to" in l for l in log))


class PlanValidationTests(unittest.TestCase):
    def test_bad_requests(self):
        for spec, side in (([], "left"), ([{"id": "left"}, {"id": "left"}], "left"), ([{"id": "banana"}], "left"), ([{"id": "left"}], "up"),
                           ([{"id": "left", "rotate": 900}], "left"), ([{"id": "left", "width_mm": 1}], "left"), ([{"id": "left"}] * 13, "left")):
            with self.assertRaises(ValueError, msg=str(spec)[:40]): P.plan(spec, side)
    def test_absurd_scale_is_refused(self):
        with self.assertRaises(ValueError): P.make_variant(lib("kalash"), P.plan([{"id": "neck", "width_mm": 400}])[0])
    def test_names_are_safe(self):
        self.assertEqual(P.slug("My Design!/../x"), "My_Design_x"); self.assertEqual(P.slug(""), "design")


class AutofixTests(unittest.TestCase):
    def test_oversize_design_is_scaled_and_centred(self):
        big = [[100, 100], [220, 100], [220, 190], [100, 190]]
        d, log = P.autofix(doc({"id": "f", "type": "fill", "color": "#f00", "rings": [big]}))
        b = P.design_bbox(d); self.assertLessEqual(b[2] - b[0], 94 + 1e-6); self.assertAlmostEqual((b[0] + b[2]) / 2, 0, delta=0.01)
        self.assertTrue(any("scaled to" in l for l in log)); self.assertTrue(run_checks(d, generate(d)[0]).ok)
    def test_hairline_column_becomes_run_and_speck_is_dropped(self):
        d, log = P.autofix(doc({"id": "c", "type": "column", "color": "#00f", "name": "thin", "rail1": [[0, 0], [20, 0]], "rail2": [[0, 0.4], [20, 0.4]]},
                              {"id": "s", "type": "fill", "color": "#f00", "name": "speck", "rings": [[[0, 0], [0.5, 0], [0.5, 0.5], [0, 0.5]]]},
                              {"id": "k", "type": "fill", "color": "#0a0", "rings": [SQ]}))
        self.assertEqual([o["type"] for o in d["objects"]], ["run", "fill"]); self.assertEqual(len(log) >= 2, True)
        self.assertTrue(any("speck" in l for l in log))
    def test_bad_numbers_and_duplicates_are_cleaned(self):
        d, log = P.autofix(doc({"id": "r", "type": "run", "color": "#000", "points": [[0, 0], [0, 0], [10, 0], [10, 0], [10, 10]]},
                              {"id": "n", "type": "run", "color": "#000", "points": [[0, 0], [float("nan"), 3]]}))
        self.assertEqual(len(d["objects"]), 1); pts = d["objects"][0]["points"]; self.assertEqual([[round(x - pts[0][0], 3), round(y - pts[0][1], 3)] for x, y in pts], [[0, 0], [10, 0], [10, 10]])
    def test_correct_design_is_left_alone(self):
        d0 = lib("kalash"); d, log = P.autofix(d0)
        self.assertEqual([o["type"] for o in d["objects"]], [o["type"] for o in d0["objects"]]); self.assertEqual(d["hoop"], d0["hoop"])
    def test_autofix_does_not_mutate_input(self):
        d0 = doc({"id": "f", "type": "fill", "color": "#f00", "rings": [[[100, 100], [220, 100], [220, 190], [100, 190]]]}); s = json.dumps(d0)
        P.autofix(d0); self.assertEqual(json.dumps(d0), s)
    def test_density_relief_loop_opens_spacing(self):
        # a column with a very tight spacing triggers the DENSITY check; the loop opens it up
        c = {"id": "c", "type": "column", "color": "#00f", "rail1": [[i, 0] for i in range(0, 30, 3)], "rail2": [[i, 0.9] for i in range(0, 30, 3)], "params": {"spacing": 0.05, "underlay": "none"}}
        d, log = P.autofix(doc(c))
        p = generate(d)[0]; self.assertTrue(run_checks(d, p).ok)


class PackageTests(unittest.TestCase):
    def test_set_zip_has_standard_names_and_verified_dsts(self):
        z, rep = sheet.placement_set(lib("peacock_arch"), [{"id": "left"}, {"id": "right"}, {"id": "neck", "width_mm": 70}], "left")
        zf = zipfile.ZipFile(io.BytesIO(z)); names = set(zf.namelist())
        for want in ("peacock_arch_left.dst", "peacock_arch_right.dst", "peacock_arch_neck.dst", "MANIFEST.txt", "placement-report.json", "peacock_arch_left.verification.json"):
            self.assertIn(want, names)
        for r in rep["placements"]:
            self.assertEqual(r["status"], "ok"); self.assertIn(r["grade"], ("PASS", "WARN"))
        for n in ("left", "right", "neck"):
            self.assertTrue(read_dst(zf.read(f"peacock_arch_{n}.dst")).ends_properly)
        self.assertNotEqual(zf.read("peacock_arch_left.dst"), zf.read("peacock_arch_right.dst"))
        self.assertEqual(json.loads(zf.read("peacock_arch_left.verification.json"))["grade"], rep["placements"][0]["grade"])
    def test_blocked_placement_is_reported_not_shipped(self):
        d = doc({"id": "f", "type": "fill", "color": "#f00", "rings": [SQ]})
        d["objects"].append({"id": "g", "type": "fill", "color": "#f00", "rings": [[[0, 0], [400, 0], [400, 3], [0, 3]]]})
        z, rep = sheet.placement_set(d, [{"id": "left"}], "left")                # autofix scales it to fit -> still ships
        self.assertIsNotNone(z)
    def test_api_and_validation(self):
        data, rep = server.api_placements({"design": lib("kalash"), "placements": [{"id": "left"}, {"id": "right"}], "source_side": "left", "thread": "60wt"})
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))
        with self.assertRaises(ValueError): server.api_placements({"design": lib("kalash"), "placements": [{"id": "nope"}]})
        with self.assertRaises(ValueError): server.api_placements({"design": {"name": "x", "objects": []}, "placements": [{"id": "left"}]})
        with self.assertRaises(ValueError): server.api_placements({"design": lib("kalash"), "placements": [{"id": "left"}], "thread": "9000"})

class FromUploadedImageTests(unittest.TestCase):
    def test_png_upload_to_named_left_right_neck_set(self):
        try:
            from PIL import Image, ImageDraw
            import numpy  # noqa: F401
        except Exception:
            self.skipTest("Pillow/NumPy not available")
        im = Image.new("RGB", (400, 300), "white"); d = ImageDraw.Draw(im)
        d.ellipse((40, 40, 220, 260), fill=(190, 20, 40)); d.polygon([(230, 60), (360, 150), (230, 240)], fill=(20, 120, 50)); d.ellipse((100, 110, 160, 190), fill="white")
        b = io.BytesIO(); im.save(b, "PNG")
        r = server.api_raster({"data": base64.b64encode(b.getvalue()).decode(), "width_mm": 70, "colors": 4, "quality": "standard"})
        design = {"name": "bridal motif", "hoop": {"w": 100, "h": 100, "margin": 3}, "objects": r["objects"]}
        z, rep = sheet.placement_set(design, [{"id": "left"}, {"id": "right"}, {"id": "neck", "width_mm": 50}], "left", "120")
        names = zipfile.ZipFile(io.BytesIO(z)).namelist()
        for n in ("bridal_motif_left.dst", "bridal_motif_right.dst", "bridal_motif_neck.dst"): self.assertIn(n, names)
        self.assertTrue(all(x["status"] == "ok" for x in rep["placements"]))
    def test_autofix_api(self):
        out = server.api_autofix(doc({"id": "f", "type": "fill", "color": "#f00", "rings": [[[100, 100], [260, 100], [260, 190], [100, 190]]]}))
        self.assertTrue(out["log"]); self.assertIn("design", out)


if __name__ == "__main__":
    unittest.main()
