"""DST axis regression suite.

History: the first DST writer had the X and Y bit tables swapped, so every file was transposed. Round-trip tests could not see it
(our reader used the same tables). These tests therefore decode files with a HAND-TYPED decoder defined in this file - bit layout
copied from the published Tajima layout, not imported from dst.py - and compare real geometry, not just self-consistency.

Conventions under test
  engine / editor / preview : millimetres, X right, Y DOWN, origin anywhere
  DST file                  : 0.1 mm units, X right, Y UP, origin = centre of the design's bounding box
So: moving RIGHT on screen = +X record, moving DOWN on screen = -Y record, UP = +Y.

What these tests cannot prove: that a physical machine moves the way the file says. Only a stitch-out can (docs/testing/).
"""
import json, math, re, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
for sub in ("engine", "server"):
    sys.path.insert(0, str(ROOT / sub))
from stitchcraft_engine.model import Cmd, Pattern, Stitch, ThreadColor
from stitchcraft_engine.dst import write_dst, HEADER_SIZE
from stitchcraft_engine.preview import preview_svg
from stitchcraft_engine.design import generate, run_checks
from stitchcraft_engine.validate import validate
import app as server

T = [ThreadColor("t", "#000000")]

# ---- hand-typed Tajima layout: (byte index, bit mask) -> (axis, signed weight). Written out literally on purpose.
LAYOUT = {
    (0, 0x01): ("x", +1), (0, 0x02): ("x", -1), (0, 0x04): ("x", +9), (0, 0x08): ("x", -9),
    (0, 0x80): ("y", +1), (0, 0x40): ("y", -1), (0, 0x20): ("y", +9), (0, 0x10): ("y", -9),
    (1, 0x01): ("x", +3), (1, 0x02): ("x", -3), (1, 0x04): ("x", +27), (1, 0x08): ("x", -27),
    (1, 0x80): ("y", +3), (1, 0x40): ("y", -3), (1, 0x20): ("y", +27), (1, 0x10): ("y", -27),
    (2, 0x04): ("x", +81), (2, 0x08): ("x", -81), (2, 0x20): ("y", +81), (2, 0x10): ("y", -81),
}


def hand_decode(data: bytes):
    """Absolute positions in mm (X right, Y UP) after each stitch/jump record, plus the header dict."""
    hdr = {}
    for line in data[:HEADER_SIZE].split(b"\x1a")[0].split(b"\r"):
        if b":" in line:
            k, v = line.decode("ascii").split(":", 1); hdr[k.strip()] = v.strip()
    body = data[HEADER_SIZE:]
    x = y = 0; pts = []; kinds = []
    for i in range(0, len(body) - 2, 3):
        rec = body[i:i + 3]; dx = dy = 0
        for (bi, mask), (axis, w) in LAYOUT.items():
            if rec[bi] & mask:
                if axis == "x": dx += w
                else: dy += w
        if rec[2] == 0xF3 and not (dx or dy):
            kinds.append("end"); pts.append((x / 10.0, y / 10.0)); break
        if rec[2] == 0xC3 and not (dx or dy):
            kinds.append("colour"); pts.append((x / 10.0, y / 10.0)); continue      # keep pts and kinds aligned (needle does not move)
        x += dx; y += dy
        kinds.append("jump" if rec[2] & 0x80 else "stitch"); pts.append((x / 10.0, y / 10.0))
    return pts, kinds, hdr


def pat(points, jump_first=True):
    """Pattern of straight stitches through engine points (mm, Y down)."""
    s = [Stitch(points[0][0], points[0][1], Cmd.JUMP), Stitch(points[0][0], points[0][1])]
    s += [Stitch(x, y) for x, y in points[1:]]
    s.append(Stitch(points[-1][0], points[-1][1], Cmd.END))
    return Pattern("axis", s, T)


def stitch_points(data):
    pts, kinds, _ = hand_decode(data)
    return [p for p, k in zip(pts, kinds) if k == "stitch"]


def extent(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(xs) - min(xs), max(ys) - min(ys)


class LineDirections(unittest.TestCase):
    def test_horizontal_line_moves_only_x(self):
        for pts, sign in (([(0, 0), (20, 0)], +1), ([(20, 0), (0, 0)], -1)):          # right, then left
            p = stitch_points(write_dst(pat(pts)).data)
            self.assertAlmostEqual(extent(p)[0], 20.0, delta=0.05); self.assertAlmostEqual(extent(p)[1], 0.0, delta=0.05)
            self.assertEqual(math.copysign(1, p[-1][0] - p[0][0]), sign)
    def test_vertical_line_moves_only_y(self):
        p = stitch_points(write_dst(pat([(0, 0), (0, 15)])).data)                      # 15 mm DOWN on screen
        self.assertAlmostEqual(extent(p)[0], 0.0, delta=0.05); self.assertAlmostEqual(extent(p)[1], 15.0, delta=0.05)
        self.assertLess(p[-1][1] - p[0][1], 0, "down on screen must be -Y in the file (Y up)")
        p = stitch_points(write_dst(pat([(0, 15), (0, 0)])).data)                      # 15 mm UP on screen
        self.assertGreater(p[-1][1] - p[0][1], 0, "up on screen must be +Y in the file")
    def test_diagonal_3_4_5(self):
        p = stitch_points(write_dst(pat([(0, 0), (30, 40)])).data)                     # right 30, down 40
        dx, dy = p[-1][0] - p[0][0], p[-1][1] - p[0][1]
        self.assertAlmostEqual(dx, 30.0, delta=0.1); self.assertAlmostEqual(dy, -40.0, delta=0.1)
        self.assertAlmostEqual(math.hypot(dx, dy), 50.0, delta=0.1)
    def test_all_four_diagonals_land_in_the_right_quadrant(self):
        for (ex, ey), (sx, sy) in {(10, 10): (1, -1), (-10, 10): (-1, -1), (10, -10): (1, 1), (-10, -10): (-1, 1)}.items():
            p = stitch_points(write_dst(pat([(0, 0), (ex, ey)])).data)
            self.assertEqual((math.copysign(1, p[-1][0] - p[0][0]), math.copysign(1, p[-1][1] - p[0][1])), (sx, sy), (ex, ey))
    def test_long_lines_over_12_mm_keep_their_direction(self):
        p = stitch_points(write_dst(pat([(0, 0), (-60, 35)])).data)                    # split into several records
        self.assertAlmostEqual(p[-1][0] - p[0][0], -60.0, delta=0.1); self.assertAlmostEqual(p[-1][1] - p[0][1], -35.0, delta=0.1)


class ShapesAndDimensions(unittest.TestCase):
    def test_rectangle_40_by_25_is_wider_than_tall_in_the_file(self):
        rect = [(0, 0), (40, 0), (40, 25), (0, 25), (0, 0)]
        data = write_dst(pat(rect)).data; p = stitch_points(data); w, h = extent(p)
        self.assertAlmostEqual(w, 40.0, delta=0.1); self.assertAlmostEqual(h, 25.0, delta=0.1)
        _, _, hdr = hand_decode(data)
        self.assertAlmostEqual((int(hdr["+X"]) + int(hdr["-X"])) / 10, 40.0, delta=0.1)       # header X extent is the WIDTH
        self.assertAlmostEqual((int(hdr["+Y"]) + int(hdr["-Y"])) / 10, 25.0, delta=0.1)
    def test_non_square_designs_both_orientations(self):
        for w, h in ((100, 30), (30, 100), (7, 63)):
            p = stitch_points(write_dst(pat([(0, 0), (w, 0), (w, h), (0, h), (0, 0)])).data)
            self.assertAlmostEqual(extent(p)[0], w, delta=0.1, msg=f"{w}x{h}"); self.assertAlmostEqual(extent(p)[1], h, delta=0.1, msg=f"{w}x{h}")
    def test_design_is_centred_on_its_bounding_box(self):
        p = stitch_points(write_dst(pat([(50, 80), (90, 80), (90, 105), (50, 105), (50, 80)])).data)
        xs, ys = [q[0] for q in p], [q[1] for q in p]
        self.assertAlmostEqual((max(xs) + min(xs)) / 2, 0.0, delta=0.1); self.assertAlmostEqual((max(ys) + min(ys)) / 2, 0.0, delta=0.1)
    def test_header_extents_match_the_decoded_stitches(self):
        data = write_dst(pat([(0, 0), (30, -10), (-5, 22)])).data; p = hand_decode(data)[0]; hdr = hand_decode(data)[2]
        self.assertEqual(int(hdr["+X"]), round(max(q[0] for q in p) * 10)); self.assertEqual(int(hdr["-X"]), round(-min(q[0] for q in p) * 10))
        self.assertEqual(int(hdr["+Y"]), round(max(q[1] for q in p) * 10)); self.assertEqual(int(hdr["-Y"]), round(-min(q[1] for q in p) * 10))

    # an asymmetric flower: a big petal to the upper right, a stem to the lower left, a leaf to the lower right
    FLOWER = {"name": "flower", "hoop": {"w": 100, "h": 100, "margin": 3}, "objects": [
        {"id": "petal", "type": "fill", "color": "#c00000", "rings": [[[5, -30], [30, -30], [30, -8], [5, -8]]], "params": {"underlay": "none"}},
        {"id": "stem", "type": "run", "color": "#006000", "points": [[0, 0], [-12, 25], [-20, 40]]},
        {"id": "leaf", "type": "fill", "color": "#008000", "rings": [[[8, 20], [28, 20], [28, 30], [8, 30]]], "params": {"underlay": "none"}}]}
    def test_asymmetric_flower_is_not_mirrored_or_transposed(self):
        pattern, _, _ = generate(self.FLOWER); data = write_dst(pattern).data
        bb = pattern.bbox(); cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        file_pts = [(round(x, 1), round(y, 1)) for x, y in stitch_points(data)]
        want = [(round(s.x - cx, 1), round(-(s.y - cy), 1)) for s in pattern.stitches if s.cmd == Cmd.STITCH]
        close = lambda a, b: abs(a[0] - b[0]) < 0.11 and abs(a[1] - b[1]) < 0.11
        self.assertEqual(len(file_pts), len(want))
        self.assertTrue(all(close(a, b) for a, b in zip(file_pts, want)))
        # landmark checks written by hand, independent of the conversion formula above
        petal = [q for q in file_pts if q[0] > -1 and q[1] > 5]              # upper right in the file: +X, +Y
        stem_end = min(file_pts, key=lambda q: q[0] + q[1])                    # lower left: -X, -Y
        leaf = [q for q in file_pts if q[1] < stem_end[1] + 15 and q[0] > 0]  # lower right
        self.assertTrue(petal and leaf)
        self.assertLess(stem_end[0], 0); self.assertLess(stem_end[1], 0)
        self.assertGreater(max(q[1] for q in petal), max(q[1] for q in leaf), "petal (top of the design) must be higher in the file than the leaf")
        wd, ht = extent(file_pts)
        self.assertAlmostEqual(wd, bb[2] - bb[0], delta=0.2); self.assertAlmostEqual(ht, bb[3] - bb[1], delta=0.2)


class PreviewAndEditorAgreeWithTheFile(unittest.TestCase):
    def test_preview_svg_and_dst_describe_the_same_geometry(self):
        pattern, _, _ = generate(ShapesAndDimensions.FLOWER); svg = preview_svg(pattern)
        lines = re.findall(r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)" stroke="#(?!999)', svg)
        self.assertTrue(lines)
        sx = [float(v) for l in lines for v in (l[0], l[2])]; sy = [float(v) for l in lines for v in (l[1], l[3])]
        pts = stitch_points(write_dst(pattern).data)
        fx = [p[0] for p in pts]; fy = [p[1] for p in pts]
        self.assertAlmostEqual(max(sx) - min(sx), max(fx) - min(fx), delta=0.2); self.assertAlmostEqual(max(sy) - min(sy), max(fy) - min(fy), delta=0.2)
        # same horizontal order; vertical order inverted (SVG Y down, file Y up)
        self.assertAlmostEqual((sx[0] - min(sx)) - (fx[0] - min(fx)), 0.0, delta=0.2)
        self.assertAlmostEqual((sy[0] - min(sy)) + (fy[0] - max(fy)), 0.0, delta=0.2)
    def test_editor_coordinates_reach_the_file_the_right_way_round(self):
        """Server path: an object at the right / top of the editor canvas must be at +X / +Y in the DST."""
        d = {"name": "t", "hoop": {"w": 200, "h": 200, "margin": 3}, "objects": [
            {"id": "a", "type": "run", "color": "#000", "points": [[60, 0], [70, 0]]},          # right
            {"id": "b", "type": "run", "color": "#000", "points": [[-60, 0], [-70, 0]]},        # left
            {"id": "c", "type": "run", "color": "#000", "points": [[0, -60], [0, -70]]},        # top (editor Y down => negative = up)
            {"id": "e", "type": "run", "color": "#000", "points": [[0, 60], [0, 70]]}]}         # bottom
        res, err = server.api_dst(d); self.assertIsNone(err)
        p = stitch_points(res.data)
        self.assertGreater(max(q[0] for q in p), 50); self.assertLess(min(q[0] for q in p), -50)
        self.assertGreater(max(q[1] for q in p), 50, "object above the centre in the editor must have +Y in the file")
        self.assertLess(min(q[1] for q in p), -50)
    def test_editor_right_object_is_at_plus_x(self):
        d = {"name": "t", "hoop": {"w": 200, "h": 200, "margin": 3}, "objects": [
            {"id": "a", "type": "run", "color": "#000", "points": [[50, -50], [80, -50]]},
            {"id": "b", "type": "run", "color": "#000", "points": [[-80, 50], [-50, 50]]}]}
        p = stitch_points(server.api_dst(d)[0].data)
        top_right = max(p, key=lambda q: q[0] + q[1]); bottom_left = min(p, key=lambda q: q[0] + q[1])
        self.assertTrue(top_right[0] > 0 and top_right[1] > 0); self.assertTrue(bottom_left[0] < 0 and bottom_left[1] < 0)


class HoopChecksUseWidthAndHeightTheRightWayRound(unittest.TestCase):
    def check(self, w, h, hoop_w, hoop_h, margin=3.0):
        p = pat([(0, 0), (w, 0), (w, h), (0, h), (0, 0)])
        return [i.code for i in validate(p, hoop_w, hoop_h, margin).issues if i.code == "HOOP"]
    def test_wide_design_fits_a_wide_hoop_not_a_tall_one(self):
        self.assertEqual(self.check(90, 30, 100, 40), [])                  # 90 x 30 in 100 x 40 (margin 3): fits
        self.assertEqual(self.check(90, 30, 40, 100), ["HOOP"])            # the same design in a hoop turned 90 degrees: does not
    def test_tall_design_fits_a_tall_hoop_not_a_wide_one(self):
        self.assertEqual(self.check(30, 90, 40, 100), [])
        self.assertEqual(self.check(30, 90, 100, 40), ["HOOP"])
    def test_margin_is_applied_on_both_sides(self):
        self.assertEqual(self.check(94, 20, 100, 100, 3), [])
        self.assertEqual(self.check(94.5, 20, 100, 100, 3), ["HOOP"])
    def test_a_design_is_never_larger_in_the_file_than_in_the_check(self):
        for w, h in ((94, 20), (20, 94)):
            data = write_dst(pat([(0, 0), (w, 0), (w, h), (0, h), (0, 0)])).data
            fw, fh = extent(stitch_points(data)); self.assertAlmostEqual(fw, w, delta=0.1); self.assertAlmostEqual(fh, h, delta=0.1)


class SoftwareReaderAgreesWithTheHandDecoder(unittest.TestCase):
    def test_every_library_and_pack_file_decodes_identically(self):
        """The project's reader (dst.py) and the hand decoder above must give the same positions for real, committed files."""
        from stitchcraft_engine.dst import read_dst
        files = sorted((ROOT / "designs").rglob("*.dst"))[:12]
        self.assertTrue(files)
        for f in files:
            data = f.read_bytes(); mine = read_dst(data)
            pts, kinds, _ = hand_decode(data)
            ours = [(px / 10.0, py / 10.0) for (dx, dy, c), (px, py) in zip(mine.records, mine.positions)]
            self.assertEqual(len(pts), len(ours), f.name)
            self.assertTrue(all(abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9 for a, b in zip(pts, ours)), f.name)
            self.assertEqual(kinds.count("stitch"), sum(1 for _, _, c in mine.records if c == "stitch"), f.name)


if __name__ == "__main__":
    unittest.main()
