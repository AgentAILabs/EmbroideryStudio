"""Machine-format encoders (JEF, XXX, U01, SEW, PES): independent read-back with pyembroidery + structural byte checks. SOFTWARE VALIDATION ONLY."""
import os, struct, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import encoders as E, export_pipeline as EP
from stitchcraft_engine.design import generate
from stitchcraft_engine.model import Cmd
try:
    import pyembroidery as pe
    HAVE_PE = True
except ImportError:
    HAVE_PE = False

FORMATS = ("jef", "xxx", "u01", "sew", "pes")
LIMIT = {"jef": 127, "xxx": 123, "u01": 127, "sew": 127, "pes": 2047}

def design(extra=None, far=False):
    objs = [{"id": "a", "type": "fill", "color": "#cc142d", "rings": [[[0, 0], [40, 0], [40, 30], [0, 30]]]},
            {"id": "b", "type": "run", "color": "#1f4fb4", "points": [[60, 0], [120, 40], [130, 0]]},
            {"id": "c", "type": "satin", "color": "#e8b040", "points": [[0, 60], [80, 60]], "params": {"width": 4}}]
    if far: objs.append({"id": "d", "type": "run", "color": "#cc142d", "points": [[0, 100], [10, 100]]})
    return {"name": "enc", "hoop": {"w": 200, "h": 200, "margin": 3}, "objects": objs + (extra or [])}

def pattern(**kw):
    return generate(design(**kw))[0]

def expected(p, fmt):
    ops, _, _ = E._ops(p, LIMIT[fmt]); x = y = 0; out = []
    for k, dx, dy, th in ops:
        x += dx; y += dy
        if k == "s": out.append((x, y))
    return out

def read(data, fmt):
    with tempfile.NamedTemporaryFile(suffix="." + fmt, delete=False) as t: t.write(data); path = t.name
    try: return pe.read(path)
    finally: os.unlink(path)


@unittest.skipUnless(HAVE_PE, "pyembroidery not installed (CI runs this)")
class ReadBack(unittest.TestCase):
    def test_every_stitch_position_round_trips(self):
        for far in (False, True):
            p = pattern(far=far)
            for fmt in FORMATS:
                data = E.WRITERS[fmt](p); pat = read(data, fmt); self.assertIsNotNone(pat, fmt)
                got = [(round(x), round(-y)) for x, y, c in pat.stitches if (c & pe.COMMAND_MASK) == pe.STITCH]
                want = expected(p, fmt)
                if fmt == "sew" and len(got) == len(want) + 1: got = got[:-1]
                self.assertEqual(got, want, f"{fmt} far={far}")

    def test_colour_changes_and_thread_count(self):
        p = pattern()
        for fmt in ("jef", "xxx", "sew", "pes"):
            pat = read(E.WRITERS[fmt](p), fmt)
            self.assertEqual(sum(1 for x, y, c in pat.stitches if (c & pe.COMMAND_MASK) == pe.COLOR_CHANGE), 2, fmt)
            self.assertEqual(len(pat.threadlist), 3, fmt)

    def test_u01_needle_changes(self):
        pat = read(E.write_u01(pattern()), "u01")
        self.assertEqual(sum(1 for x, y, c in pat.stitches if (c & pe.COMMAND_MASK) == pe.NEEDLE_SET), 2)

    def test_long_jumps_are_split_to_the_format_limit(self):
        for fmt in FORMATS:
            ops, _, _ = E._ops(pattern(far=True), LIMIT[fmt]); self.assertLessEqual(max(max(abs(dx), abs(dy)) for k, dx, dy, t in ops), LIMIT[fmt])

    def test_agrees_with_pyembroidery_own_writer(self):
        """Same pattern written by pyembroidery's writer and by ours must read back to the same stitch positions."""
        p = pattern(); pp = pe.EmbPattern()
        ops, _, _ = E._ops(p, 127); x = y = 0; th = [pe.EmbThread(), pe.EmbThread(), pe.EmbThread()]
        for t, h in zip(th, [s.hex for s in p.threads]): t.color = int(h[1:], 16)
        for t in th: pp.add_thread(t)
        for k, dx, dy, tt in ops:
            x += dx; y += dy
            if k == "s": pp.add_stitch_absolute(pe.STITCH, x, -y)
            elif k == "j": pp.add_stitch_absolute(pe.JUMP, x, -y)
            elif k == "c": pp.add_stitch_absolute(pe.COLOR_CHANGE, x, -y)
        pp.end()
        for fmt in ("jef", "xxx"):
            with tempfile.NamedTemporaryFile(suffix="." + fmt, delete=False) as t: path = t.name
            try:
                pe.write(pp, path); theirs = pe.read(path)
            finally: os.unlink(path)
            ours = read(E.WRITERS[fmt](p), fmt)
            a = [(round(x), round(y)) for x, y, c in theirs.stitches if (c & pe.COMMAND_MASK) == pe.STITCH]; b = [(round(x), round(y)) for x, y, c in ours.stitches if (c & pe.COMMAND_MASK) == pe.STITCH]
            self.assertEqual(a, b, fmt)

    def test_export_pipeline_runs_the_readback_and_reports_it(self):
        for fmt in FORMATS:
            r = EP.export_format(design(), fmt); v = r.report["validation"]
            self.assertEqual(v["independent_reader"]["result"], "PASS", fmt); self.assertIn("NOT DONE", v["physical_machine"]); self.assertEqual(v["tier"], "software_verified")

    def test_a_corrupted_file_fails_verification(self):
        p = pattern(); data = bytearray(E.write_jef(p)); data[-30] ^= 0x7F
        self.assertEqual(E.verify_with_pyembroidery(bytes(data), "jef", p)["result"], "FAIL")


class Structure(unittest.TestCase):
    def test_signatures_and_trailers(self):
        p = pattern()
        jef = E.write_jef(p); self.assertTrue(jef.endswith(b"\x80\x10")); self.assertEqual(struct.unpack("<ii", jef[:8]), (0x74 + 3 * 8, 0x14)); self.assertEqual(struct.unpack("<i", jef[24:28])[0], 3)
        xxx = E.write_xxx(p); self.assertEqual(len(xxx[:0x100]), 0x100); self.assertIn(b"\x7f\x7f\x02\x14", xxx); self.assertEqual(struct.unpack("<H", xxx[0x27:0x29])[0], 3)
        u01 = E.write_u01(p); self.assertTrue(u01[:0x80] == b"0" * 0x80); self.assertTrue(u01.endswith(b"\xf8\x00\x00")); self.assertEqual((len(u01) - 0x100) % 3, 0)
        sew = E.write_sew(p); self.assertEqual(struct.unpack("<H", sew[:2])[0], 3); self.assertEqual(sew[-4:], b"\x80\x10\x00\x00"); self.assertGreater(len(sew), 0x1D78)
        pes = E.write_pes(p); self.assertTrue(pes.startswith(b"#PES0001")); pec_off = struct.unpack("<I", pes[8:12])[0]; self.assertEqual(pec_off, 0x16); self.assertEqual(pes[0x16:0x19], b"LA:")
        self.assertIn(b"\x31\xff\xf0", pes); self.assertIn(b"\xfe\xb0", pes)

    def test_deterministic(self):
        p = pattern()
        for fmt in FORMATS: self.assertEqual(E.WRITERS[fmt](p), E.WRITERS[fmt](pattern()), fmt)

    def test_palette_matching_picks_the_obvious_colour_and_avoids_repeats(self):
        self.assertEqual(E.nearest_index(E.FP.JEF, "#ff0000"), 10)            # "Red"
        self.assertEqual(E.nearest_index(E.FP.PEC, "#ed171f"), 5)             # "Red"
        self.assertNotEqual(E.nearest_index(E.FP.JEF, "#ff0000", (10,)), 10)

    def test_limits_and_empty_input(self):
        many = design([{"id": f"x{i}", "type": "run", "color": "#%02x%02x%02x" % (i * 11 % 256, i * 29 % 256, i * 53 % 256), "points": [[i * 3, 0], [i * 3 + 2, 5]]} for i in range(25)])
        with self.assertRaises(E.EncodeError): E.write_xxx(generate(many)[0])                          # XXX holds at most 20 colours
        from stitchcraft_engine.model import Pattern
        for fmt in FORMATS:
            with self.assertRaises(E.EncodeError): E.WRITERS[fmt](Pattern())

    def test_unavailable_formats_are_refused(self):
        with self.assertRaises(EP.ExportError): EP.export_format(design(), "vp3")
        with self.assertRaises(EP.ExportError): EP.export_format(design(), "nope")

    def test_same_gating_as_dst(self):
        big = {"name": "b", "hoop": {"w": 50, "h": 50, "margin": 3}, "objects": [{"id": "a", "type": "fill", "color": "#f00", "rings": [[[0, 0], [300, 0], [300, 10], [0, 10]]]}]}
        with self.assertRaises(EP.ExportError): EP.export_format(big, "jef")


if __name__ == "__main__":
    unittest.main()
