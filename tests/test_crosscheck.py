"""Independent cross-check of our DST writer against pyembroidery's reader (requirements A.6).
Runs only where pyembroidery is installed (CI installs it); skipped otherwise - it has NOT been run in the authoring
environment, so a failure here in CI is a real signal to investigate, either in our writer or in this test's API use."""
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "tools"))
try:
    import pyembroidery
except ImportError:           # pragma: no cover
    pyembroidery = None

from stitchcraft_engine.design import generate                      # noqa: E402
from stitchcraft_engine.dst import write_dst, read_dst              # noqa: E402


def designs():
    sq = [[0, 0], [20, 0], [20, 20], [0, 20]]
    return {
        "fill": {"name": "fill", "hoop": {"w": 100, "h": 100}, "objects": [{"id": "a", "type": "fill", "color": "#f00", "rings": [sq]}]},
        "multi": {"name": "multi", "hoop": {"w": 100, "h": 100}, "objects": [
            {"id": "a", "type": "fill", "color": "#f00", "rings": [sq]},
            {"id": "b", "type": "satin", "color": "#00f", "points": [[0, 40], [30, 45]], "params": {"width": 3}},
            {"id": "c", "type": "text", "color": "#000", "text": "OK 7", "height": 8, "x": 0, "y": 55}]},
        "far_jump": {"name": "far", "hoop": {"w": 200, "h": 200}, "objects": [
            {"id": "a", "type": "run", "color": "#f00", "points": [[0, 0], [10, 0]]},
            {"id": "b", "type": "run", "color": "#00f", "points": [[90, 90], [100, 90]]}]},
    }


@unittest.skipIf(pyembroidery is None, "pyembroidery not installed (CI installs it)")
class PyembroideryCrossCheck(unittest.TestCase):
    def read_theirs(self, data: bytes):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "x.dst"; f.write_bytes(data)
            return pyembroidery.read(str(f))

    def test_stitch_positions_and_colour_changes_match(self):
        for name, d in designs().items():
            pat, _, st = generate(d); data = write_dst(pat).data
            theirs = self.read_theirs(data); self.assertIsNotNone(theirs, name)
            ours = read_dst(data)
            our_xy = [p for (dx, dy, c), p in zip(ours.records, ours.positions) if c == "stitch"]
            their_xy = [(int(x), int(y)) for x, y, cmd in theirs.stitches if (cmd & pyembroidery.COMMAND_MASK) == pyembroidery.STITCH]
            flipped = [(x, -y) for x, y in their_xy]                                    # y axis convention may differ between libraries
            self.assertTrue(their_xy == our_xy or flipped == our_xy, f"{name}: stitch sequences differ ({len(their_xy)} vs {len(our_xy)})")
            their_cc = sum(1 for _, _, cmd in theirs.stitches if (cmd & pyembroidery.COMMAND_MASK) == pyembroidery.COLOR_CHANGE)
            self.assertEqual(their_cc, st["color_changes"], name)
            self.assertEqual(len(their_xy), st["stitches"], name)


if __name__ == "__main__":
    unittest.main()
