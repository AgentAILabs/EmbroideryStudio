"""Validated export pipeline: a file that differs from the stitch plan is never released. Mutation tests break the DST on purpose."""
import dataclasses, io, json, math, sys, unittest, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server")); sys.path.insert(0, str(ROOT / "tests"))
from stitchcraft_engine import export_pipeline as EP, dst
from stitchcraft_engine.design import generate
from stitchcraft_engine.model import Cmd, Pattern, Stitch, ThreadColor
import app as server
import sheet

T = [ThreadColor("a", "#c00000"), ThreadColor("b", "#0000c0")]
def doc(*objs, **kw): return dict({"name": "t", "hoop": {"w": 200, "h": 200, "margin": 3}, "objects": list(objs)}, **kw)
def lib(n): return json.loads((ROOT / "designs" / "library" / n / f"{n}.esproj").read_text())["doc"]
def circle(cx, cy, r, n=48): return [[cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)] for k in range(n)]
def sq(x, y, w, h): return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

FIXTURES = {
    "circle": doc({"id": "c", "type": "fill", "color": "#c00000", "rings": [circle(0, 0, 25)]}),
    "complex polygon": doc({"id": "p", "type": "fill", "color": "#c00000", "rings": [[[0, 0], [60, 5], [45, 30], [70, 55], [30, 45], [10, 70], [15, 35], [-10, 20]]]}),
    "hole geometry": doc({"id": "h", "type": "fill", "color": "#c00000", "rings": [circle(0, 0, 30), circle(0, 0, 12)]}),
    "multi colour + trims": doc({"id": "a", "type": "fill", "color": "#c00000", "rings": [sq(0, 0, 20, 20)]}, {"id": "b", "type": "fill", "color": "#0000c0", "rings": [sq(80, 60, 20, 20)]}),
    "positive and negative quadrants": doc({"id": "r", "type": "run", "color": "#000000", "points": [[-80, -70], [80, -70], [80, 70], [-80, 70], [-80, -70]]}),
    "satin + run": doc({"id": "s", "type": "satin", "color": "#0000c0", "points": [[-30, 0], [0, 10], [30, 0]], "params": {"width": 3}}, {"id": "r", "type": "run", "color": "#000000", "points": [[-30, 20], [30, 20]]}),
}


def decoded_plan(design):
    p, _, _ = generate(design); data = dst.write_dst(p).data
    return p, data


class ValidDesignsAreReleased(unittest.TestCase):
    def test_every_fixture_exports_with_a_complete_report(self):
        for name, d in FIXTURES.items():
            r = EP.export_dst(d)
            self.assertTrue(r.data and len(r.sha256) == 64, name)
            rep = r.report
            self.assertEqual([s["stage"] for s in rep["stages"]][:2], ["generate", "validate"], name)
            self.assertIn("decode-compare", [s["stage"] for s in rep["stages"]], name)
            self.assertEqual(rep["validation"]["physical_machine"][:8], "NOT DONE", name)             # never claims machine validation
            self.assertIn("software", rep["validation"]); self.assertIn("independent_reader", rep["validation"])
            self.assertEqual(rep["sha256"], r.sha256); self.assertTrue(rep["exported_utc"].endswith("+00:00")); self.assertTrue(rep["engine_version"])
    def test_counts_match_the_stitch_plan(self):
        for name, d in FIXTURES.items():
            r = EP.export_dst(d); p, _, st = generate(d)
            c = r.report["counts"]
            self.assertEqual(c["stitch"], st["stitches"], name); self.assertEqual(c["color_change"], st["color_changes"], name)
            self.assertEqual(c["end"], 1, name)
    def test_dimensions_in_the_report_match_the_design(self):
        r = EP.export_dst(FIXTURES["circle"]); self.assertAlmostEqual(r.report["size_mm"][0], 50.0, delta=1.0); self.assertAlmostEqual(r.report["size_mm"][1], 50.0, delta=1.0)
    def test_maximum_movement_records_are_respected(self):
        # a 300 mm jump = 25 records of <= 121 units; every record must stay within the DST limit and the plan must still match
        d = doc({"id": "a", "type": "run", "color": "#000", "points": [[-140, -140], [-130, -140]]}, {"id": "b", "type": "run", "color": "#000", "points": [[130, 140], [140, 140]]}, hoop={"w": 400, "h": 400, "margin": 3})
        r = EP.export_dst(d); recs, _, _ = EP.independent_decode(r.data)
        self.assertTrue(all(abs(dx) <= 121 and abs(dy) <= 121 for dx, dy, _ in recs)); self.assertGreater(sum(1 for *_, k in recs if k == "jump"), 20)
    def test_library_designs_all_pass(self):
        for n in ("kalash", "peacock_arch", "lotus_bloom", "bride_frame"):
            self.assertTrue(EP.export_dst(lib(n)).report["stages"])


class MutationTestsTheFileIsRefused(unittest.TestCase):
    """Each mutation keeps the file structurally valid (END, header) but makes it say something different from the plan."""
    def setUp(self):
        self.d = FIXTURES["multi colour + trims"]; self.p, self.data = decoded_plan(self.d); self.tj = 3
    def refuse(self, data, code=None):
        with self.assertRaises(EP.ExportError) as cm: EP.compare_with_plan(self.p, data, self.tj)
        self.assertEqual(cm.exception.stage, "decode-compare")
        if code: self.assertEqual(cm.exception.code, code, str(cm.exception))
        return cm.exception
    def test_unmodified_file_passes(self):
        self.assertEqual(EP.compare_with_plan(self.p, self.data, self.tj)["counts"]["end"], 1)
    def test_one_stitch_moved_by_one_unit(self):
        b = bytearray(self.data); b[512 + 3 * 40] ^= 0x01; self.refuse(bytes(b), "EXPORT_MISMATCH")
    def test_a_stitch_record_deleted(self):
        b = bytearray(self.data); del b[512 + 3 * 40:512 + 3 * 41]; self.refuse(bytes(b))
    def test_a_stitch_record_inserted(self):
        b = bytearray(self.data); b[512 + 3 * 40:512 + 3 * 40] = bytes([0x00, 0x00, 0x03]); self.refuse(bytes(b))
    def test_a_stitch_turned_into_a_jump(self):
        b = bytearray(self.data); b[512 + 3 * 40 + 2] |= 0x80; self.refuse(bytes(b))
    def test_colour_change_removed(self):
        b = bytearray(self.data); i = next(k for k in range(512, len(b) - 2, 3) if b[k + 2] == 0xC3); b[i + 2] = 0x83; self.refuse(bytes(b))
    def test_trim_shortened(self):
        b = bytearray(self.data); i = next(k for k in range(512, len(b) - 2, 3) if b[k + 2] == 0x83 and b[k] == 0 and b[k + 1] == 0); del b[i:i + 3]; self.refuse(bytes(b))
    def test_truncated_file(self):
        self.refuse(self.data[:-9])
    def test_extra_records_after_end(self):
        self.refuse(self.data + bytes([0x00, 0x00, 0x03]))
    def test_header_lies_about_colour_changes(self):
        b = bytearray(self.data); i = bytes(b).index(b"CO:"); b[i + 3:i + 6] = b" 9 "; self.refuse(bytes(b), "EXPORT_BAD_HEADER")
    def test_header_lies_about_extents(self):
        b = bytearray(self.data); i = bytes(b).index(b"+X:"); b[i + 3:i + 8] = b"99999"; self.refuse(bytes(b), "EXPORT_BAD_HEADER")
    def test_every_single_bit_flip_in_the_first_records_is_caught(self):
        caught = 0
        for byte in range(512, 512 + 3 * 60):
            for bit in (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
                b = bytearray(self.data); b[byte] ^= bit
                if bytes(b) == self.data: continue
                try: EP.compare_with_plan(self.p, bytes(b), self.tj)
                except EP.ExportError: caught += 1
        self.assertGreater(caught, 60 * 3 * 7)                             # essentially every flip (a few land on bits the format ignores)


class TheOriginalSwapCannotReturnUnnoticed(unittest.TestCase):
    def test_swapped_axis_tables_in_the_writer_and_reader_are_refused_at_export_time(self):
        d = FIXTURES["complex polygon"]
        old = (dst._X_BITS, dst._Y_BITS)
        try:
            dst._X_BITS, dst._Y_BITS = dst._Y_BITS, dst._X_BITS             # the historic bug: both writer and project reader agree with each other
            with self.assertRaises(EP.ExportError) as cm: EP.export_dst(d)
            self.assertEqual(cm.exception.stage, "decode-compare")
        finally:
            dst._X_BITS, dst._Y_BITS = old
        EP.export_dst(d)                                                     # restored: exports again
    def test_mirrored_and_scaled_files_are_refused(self):
        p, data = decoded_plan(FIXTURES["complex polygon"])
        mirrored = Pattern("m", [dataclasses.replace(s, x=-s.x) for s in p.stitches], T)
        with self.assertRaises(EP.ExportError): EP.compare_with_plan(mirrored, data, 3)
        scaled = Pattern("s", [dataclasses.replace(s, x=s.x * 1.1, y=s.y * 1.1) for s in p.stitches], T)
        with self.assertRaises(EP.ExportError): EP.compare_with_plan(scaled, data, 3)


class WiringRefusesBadFilesEverywhere(unittest.TestCase):
    def corrupt_writer(self, mode):
        real = dst.write_dst
        def bad(p, *a, **k):
            r = real(p, *a, **k); b = bytearray(r.data)
            if mode == "bit": b[512 + 3 * 40] ^= 0x01
            else: del b[512 + 3 * 40:512 + 3 * 41]
            return dataclasses.replace(r, data=bytes(b))
        return real, bad
    def test_api_dst_refuses_a_corrupted_writer_with_a_structured_error(self):
        for mode in ("bit", "delete"):
            real, bad = self.corrupt_writer(mode); EP.write_dst = bad
            try:
                res, err = server.api_dst(lib("kalash"))
            finally:
                EP.write_dst = real
            self.assertIsNone(res, mode); self.assertEqual(err["stage"], "decode-compare"); self.assertEqual(err["issues"][0]["severity"], "error")
            self.assertIn("refused", err["error"])
    def test_package_and_placement_set_refuse_too(self):
        real, bad = self.corrupt_writer("bit"); EP.write_dst = bad
        try:
            data, err = sheet.package(lib("kalash")); self.assertIsNone(data); self.assertEqual(err["stage"], "decode-compare")
            z, rep = sheet.placement_set(lib("kalash"), [{"id": "left"}], "left")
            self.assertIsNone(z); self.assertEqual(rep["placements"][0]["status"], "blocked")
        finally:
            EP.write_dst = real
    def test_package_carries_the_export_report_with_three_validation_sections(self):
        data, err = sheet.package(lib("kalash")); self.assertIsNone(err)
        z = zipfile.ZipFile(io.BytesIO(data)); rep = json.loads(z.read("kalash.export-report.json"))
        self.assertEqual(rep["sha256"], __import__("hashlib").sha256(z.read("kalash.dst")).hexdigest())
        self.assertEqual(set(rep["validation"]), {"software", "independent_reader", "physical_machine"}); self.assertIn("NOT DONE", rep["validation"]["physical_machine"])
    def test_validation_errors_still_block_with_issues(self):
        res, err = server.api_dst(doc({"id": "f", "type": "fill", "color": "#f00", "rings": [sq(0, 0, 300, 20)]}))
        self.assertIsNone(res); self.assertEqual(err["error"], "Export blocked"); self.assertTrue(err["issues"])
    def test_nothing_to_stitch_stays_a_value_error(self):
        with self.assertRaises(ValueError): server.api_dst({"name": "x", "hoop": {"w": 100, "h": 100}, "objects": [{"id": "e", "type": "embellishment", "kind": "bead", "color": "#fff", "size_mm": 3, "points": [[0, 0]]}]})


class IndependentReaderIsNeverFaked(unittest.TestCase):
    def test_reader_result_is_either_pass_or_explicitly_not_run(self):
        r = EP.export_dst(FIXTURES["circle"]).report["validation"]["independent_reader"]
        self.assertTrue(r.startswith("PASSED") or r.startswith("NOT RUN"))
        try:
            import pyembroidery  # noqa: F401
            self.assertTrue(r.startswith("PASSED"))
        except ImportError:
            self.assertTrue(r.startswith("NOT RUN"))

if __name__ == "__main__":
    unittest.main()
