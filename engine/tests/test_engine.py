import math, unittest
from stitchcraft_engine import dst
from stitchcraft_engine.builder import StitchObject, build_pattern
from stitchcraft_engine.geometry import point_in_polygon, dist, polyline_length
from stitchcraft_engine.model import Cmd, Pattern, Stitch, ThreadColor
from stitchcraft_engine.pipeline import digitize_svg
from stitchcraft_engine.stitches import running_stitch, satin_stitch, tatami_fill, edge_walk_underlay, DigitizingError
from stitchcraft_engine.svg_input import parse_svg, UnsupportedSvg
from stitchcraft_engine.validate import validate

T = [ThreadColor("A", "#ff0000"), ThreadColor("B", "#0000ff")]


class DstCodec(unittest.TestCase):
    def test_every_delta_roundtrips(self):
        for dx in range(-121, 122, 1):
            for dy in range(-121, 122, 11):
                self.assertEqual(dst.decode_record(dst.encode_record(dx, dy, 0))[:2], (dx, dy))
    def test_out_of_range_rejected(self):
        with self.assertRaises(dst.DstError):
            dst.encode_record(122, 0)
    def test_known_bytes(self):
        self.assertEqual(dst.encode_record(1, 0), bytes([0x80, 0x00, 0x03]))
        self.assertEqual(dst.encode_record(0, 1), bytes([0x01, 0x00, 0x03]))
        self.assertEqual(dst.encode_record(0, 0, dst.FLAG_END), bytes([0, 0, 0xF3]))
        self.assertEqual(dst.encode_record(0, 0, dst.FLAG_COLOR), bytes([0, 0, 0xC3]))


class Roundtrip(unittest.TestCase):
    def pattern(self):
        runs = [[(0, 0), (10, 0), (10, 10)]]
        objs = [StitchObject("a", "running", 0, runs), StitchObject("b", "running", 1, [[(20, 20), (30, 25)]])]
        return build_pattern(objs, T, "rt")
    def test_roundtrip_positions(self):
        p = self.pattern(); res = dst.write_dst(p, center=False)
        f = dst.read_dst(res.data)
        self.assertTrue(f.ends_properly)
        self.assertEqual(len(res.data), 512 + 3 * res.record_count)
        self.assertEqual(f.color_changes, 1)
        self.assertEqual(f.header["CO"], "1")
        self.assertEqual(f.header["ST"], str(res.record_count))
        # final decoded position equals last stitch within rounding (0.1 mm), Y flipped
        last = [s for s in p.stitches if s.cmd == Cmd.STITCH][-1]
        self.assertAlmostEqual(f.positions[-1][0] / 10, last.x, delta=0.06)
        self.assertAlmostEqual(f.positions[-1][1] / 10, -last.y, delta=0.06)
    def test_header_512(self):
        self.assertEqual(len(dst.write_dst(self.pattern()).data[:512]), 512)
    def test_long_jump_split_within_limit(self):
        p = Pattern("j", [Stitch(0, 0, Cmd.STITCH), Stitch(100, 0, Cmd.JUMP), Stitch(100, 0, Cmd.STITCH), Stitch(100, 0, Cmd.END)], T)
        f = dst.read_dst(dst.write_dst(p, center=False).data)
        self.assertTrue(all(abs(dx) <= 121 and abs(dy) <= 121 for dx, dy, _ in f.records))
        self.assertEqual(f.positions[-1][0], 1000)
    def test_missing_end_rejected(self):
        with self.assertRaises(dst.DstError):
            dst.write_dst(Pattern("x", [Stitch(0, 0)], T))
    def test_json_contract(self):
        p = self.pattern(); q = Pattern.from_dict(p.to_dict())
        self.assertEqual(len(q.stitches), len(p.stitches))
        with self.assertRaises(ValueError):
            Pattern.from_dict({**p.to_dict(), "schema_version": "2.0"})


class Running(unittest.TestCase):
    def test_max_length_and_vertices(self):
        pts = [(0, 0), (10, 0), (10, 7)]
        out = running_stitch(pts, 2.5)
        self.assertIn((10, 0), [(round(x, 9), round(y, 9)) for x, y in out])
        self.assertTrue(all(dist(a, b) <= 2.5 + 1e-9 for a, b in zip(out, out[1:])))
        self.assertAlmostEqual(polyline_length(out), 17)
    def test_bad_params(self):
        with self.assertRaises(DigitizingError): running_stitch([(0, 0), (1, 1)], 0)
        with self.assertRaises(DigitizingError): running_stitch([(0, 0)], 2)


class Satin(unittest.TestCase):
    def test_straight_column_within_width_and_alternating(self):
        pts = satin_stitch([(0, 0), (20, 0)], width=4, spacing=0.4)
        ys = [y for _, y in pts]
        self.assertTrue(all(abs(abs(y) - 2) < 1e-6 for y in ys))
        self.assertTrue(all(ys[i] * ys[i + 1] < 0 for i in range(len(ys) - 1)))
        self.assertAlmostEqual(pts[1][0] - pts[0][0], 0.4, places=2)
        self.assertGreaterEqual(min(p[0] for p in pts), -1e-9); self.assertLessEqual(max(p[0] for p in pts), 20 + 1e-9)
    def test_pull_comp_widens(self):
        pts = satin_stitch([(0, 0), (5, 0)], 3, 0.4, pull_comp=0.4)
        self.assertAlmostEqual(max(abs(y) for _, y in pts), 1.7)
    def test_edge_walk_inside_column(self):
        pts = edge_walk_underlay([(0, 0), (20, 0)], 4, inset=0.5)
        self.assertTrue(all(abs(y) <= 1.5 + 1e-6 for _, y in pts))


class Tatami(unittest.TestCase):
    SQ = [(0, 0), (10, 0), (10, 10), (0, 10)]
    def test_square_all_points_in_bounds(self):
        for ang in (0, 45, 90, 30):
            runs = tatami_fill([self.SQ], ang)
            pts = [p for r in runs for p in r]
            self.assertTrue(all(-1e-6 <= x <= 10 + 1e-6 and -1e-6 <= y <= 10 + 1e-6 for x, y in pts), ang)
    def test_row_spacing_and_density(self):
        runs = tatami_fill([self.SQ], 0, spacing=0.5)
        ys = sorted({round(y, 6) for r in runs for _, y in r})
        self.assertEqual(len(ys), 20)
        self.assertAlmostEqual(ys[1] - ys[0], 0.5)
    def test_max_stitch_length_in_rows(self):
        runs = tatami_fill([self.SQ], 0, spacing=0.4, stitch_len=3.5)
        for r in runs:
            self.assertTrue(all(dist(a, b) <= 3.5 + 1.0 for a, b in zip(r, r[1:])))
    def test_hole_is_respected(self):
        outer = [(0, 0), (20, 0), (20, 20), (0, 20)]
        hole = [(7, 7), (13, 7), (13, 13), (7, 13)]
        runs = tatami_fill([outer, hole], 0)
        pts = [p for r in runs for p in r]
        inside_hole = [p for p in pts if 7.05 < p[0] < 12.95 and 7.05 < p[1] < 12.95]
        self.assertEqual(inside_hole, [])
        # stitches must not cross the hole either
        for r in runs:
            for a, b in zip(r, r[1:]):
                m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                self.assertFalse(7.05 < m[0] < 12.95 and 7.05 < m[1] < 12.95)
    def test_concave_shape_uses_jumps_not_outside_stitches(self):
        u = [(0, 0), (10, 0), (10, 10), (7, 10), (7, 3), (3, 3), (3, 10), (0, 10)]
        runs = tatami_fill([u], 0)
        self.assertGreater(len(runs), 1)
        for r in runs:
            for a, b in zip(r, r[1:]):
                self.assertTrue(point_in_polygon(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), [u]) or dist(a, b) < 1.0)


class Validation(unittest.TestCase):
    def test_hoop_overflow(self):
        p = build_pattern([StitchObject("a", "running", 0, [[(0, 0), (120, 0)]])], T)
        r = validate(p, 100, 100)
        self.assertIn("HOOP", [i.code for i in r.errors])
    def test_long_stitch_flagged(self):
        p = Pattern("x", [Stitch(0, 0), Stitch(13, 0), Stitch(13, 0, Cmd.END)], T)
        self.assertIn("STITCH_TOO_LONG_DST", [i.code for i in validate(p).errors])
    def test_missing_end(self):
        self.assertIn("NO_END", [i.code for i in validate(Pattern("x", [Stitch(0, 0)], T)).errors])
    def test_density_warning(self):
        runs = [[(0.5, 0.5)] * 1 + [(0.5 + 0.01 * (k % 3), 0.5) for k in range(40)]]
        p = build_pattern([StitchObject("a", "running", 0, runs)], T)
        self.assertIn("DENSITY", [i.code for i in validate(p).warnings])


class Svg(unittest.TestCase):
    def test_scale_and_shapes(self):
        d = parse_svg('<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm" viewBox="0 0 100 100"><rect x="0" y="0" width="100" height="100" fill="#f00"/></svg>')
        self.assertAlmostEqual(d.shapes[0].rings[0][2][0], 50)
    def test_arc_rejected(self):
        with self.assertRaises(UnsupportedSvg):
            parse_svg('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 A5 5 0 0 1 10 0"/></svg>')
    def test_transform_warns(self):
        d = parse_svg('<svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5" transform="rotate(5)"/></svg>')
        self.assertTrue(d.warnings)
    def test_end_to_end_sample(self):
        with open("samples/flower.svg", encoding="utf-8") as fh:
            d = parse_svg(fh.read())
        p, _ = digitize_svg(d)
        self.assertTrue(validate(p, 100, 100).ok)
        f = dst.read_dst(dst.write_dst(p).data)
        self.assertTrue(f.ends_properly)
        self.assertEqual(int(f.header["CO"]), f.color_changes)
        self.assertEqual(sum(1 for _, _, c in f.records if c == "color_change"), p.counts()["color_change"])


if __name__ == "__main__":
    unittest.main()


class LongJumpDecodeTest(unittest.TestCase):
    def test_long_jump_with_x81_bit_decodes_as_jump(self):
        from stitchcraft_engine.dst import encode_record, decode_record, FLAG_JUMP
        for dx, dy in [(89, 0), (121, -121), (-100, 81), (81, 81)]:
            self.assertEqual(decode_record(encode_record(dx, dy, FLAG_JUMP)), (dx, dy, "jump"))
            self.assertEqual(decode_record(encode_record(dx, dy, 0))[2], "stitch")
