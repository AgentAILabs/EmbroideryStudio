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


def peacock():
    import importlib.util
    spec = importlib.util.spec_from_file_location("peacock_mod", ROOT / "tools" / "make_peacock_panel.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m.build()


def peacock_sleeve_mirrored():
    import importlib.util
    spec = importlib.util.spec_from_file_location("peacock_mod2", ROOT / "tools" / "make_peacock_panel.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    d, _ = m.drop_unstitchable(m.transform(m.build(), 0.65, True))
    return d


def library_samples():
    import importlib.util
    spec = importlib.util.spec_from_file_location("lib_mod", ROOT / "tools" / "make_library.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    want = ("lotus_bloom", "paisley_pair", "jhumka_bell", "temple_border")           # fills, columns, satin, short runs, placeholders
    return {f"lib_{b[0]}": b[4] for b in m.build_all() if b[0] in want}


def designs():
    sq = [[0, 0], [20, 0], [20, 20], [0, 20]]
    return {
        "fill": {"name": "fill", "hoop": {"w": 100, "h": 100}, "objects": [{"id": "a", "type": "fill", "color": "#f00", "rings": [sq]}]},
        "multi": {"name": "multi", "hoop": {"w": 100, "h": 100}, "objects": [
            {"id": "a", "type": "fill", "color": "#f00", "rings": [sq]},
            {"id": "b", "type": "satin", "color": "#00f", "points": [[0, 40], [30, 45]], "params": {"width": 3}},
            {"id": "c", "type": "text", "color": "#000", "text": "OK 7", "height": 8, "x": 0, "y": 55}]},
        "colour_and_trims": {"name": "ct", "hoop": {"w": 150, "h": 150}, "objects": [          # far jumps + a colour change + end, with lock stitches (the default)
            {"id": "a", "type": "fill", "color": "#f00", "rings": [sq]},
            {"id": "b", "type": "fill", "color": "#f00", "rings": [[[50, 0], [70, 0], [70, 20], [50, 20]]]},
            {"id": "c", "type": "satin", "color": "#00f", "points": [[0, 60], [40, 70]], "params": {"width": 3}},
            {"id": "d", "type": "applique", "color": "#0a0", "rings": [[[60, 50], [90, 50], [90, 80], [60, 80]]]}]},
        "peacock_sleeve_mirrored": peacock_sleeve_mirrored(),    # scaled + mirrored production variant
        "peacock_panel": peacock(),                       # the real production design: ~70 objects, 3 colours, locks and trims
        **library_samples(),
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

    @staticmethod
    def deltas(xy):
        return [(b[0] - a[0], b[1] - a[1]) for a, b in zip(xy, xy[1:])]

    def test_stitch_positions_and_colour_changes_match(self):
        for name, d in designs().items():
            pat, _, st = generate(d); data = write_dst(pat).data
            theirs = self.read_theirs(data); self.assertIsNotNone(theirs, name)
            ours = read_dst(data)
            our_xy = [p for (dx, dy, c), p in zip(ours.records, ours.positions) if c == "stitch"]
            their_xy = [(int(x), int(y)) for x, y, cmd in theirs.stitches if (cmd & pyembroidery.COMMAND_MASK) == pyembroidery.STITCH]
            self.assertEqual(len(their_xy), len(our_xy), f"{name}: stitch count differs")
            self.assertEqual(len(their_xy), st["stitches"], name)
            od, td = self.deltas(our_xy), self.deltas(their_xy)
            flipped = [(dx, -dy) for dx, dy in td]
            if od != td and od != flipped:                    # origin-independent comparison; print enough to diagnose from CI logs
                bad = next((i for i, (u, v) in enumerate(zip(od, td)) if u != v), -1)
                self.fail(f"{name}: stitch DELTAS differ at index {bad}\n  ours  : {od[max(0, bad - 2):bad + 4]}\n  theirs: {td[max(0, bad - 2):bad + 4]}"
                          f"\n  first abs ours {our_xy[:3]} theirs {their_xy[:3]}\n  last abs ours {our_xy[-2:]} theirs {their_xy[-2:]}"
                          f"\n  their cmds around: {[(x, y, cmd) for x, y, cmd in theirs.stitches[max(0, 3):10]]}")
            their_cc = sum(1 for _, _, cmd in theirs.stitches if (cmd & pyembroidery.COMMAND_MASK) == pyembroidery.COLOR_CHANGE)
            self.assertEqual(their_cc, st["color_changes"], name)
            # informational: how pyembroidery interprets our trims (consecutive zero-move jumps); DST has no trim opcode, so this is
            # convention, not a pass/fail. Read it in the CI log when tuning "Trim jumps" for a real machine.
            their_trim = sum(1 for _, _, cmd in theirs.stitches if (cmd & pyembroidery.COMMAND_MASK) == pyembroidery.TRIM)
            their_jump = sum(1 for _, _, cmd in theirs.stitches if (cmd & pyembroidery.COMMAND_MASK) == pyembroidery.JUMP)
            print(f"[crosscheck] {name}: our trims={st['trims']} locks={st['lock_stitches']} | pyembroidery reads TRIM={their_trim} JUMP={their_jump}")
            # Observed in CI: with the default 3 trim jumps pyembroidery reads exactly one TRIM per trim we write. Pin it, so a change
            # to the trim encoding (or to how many trims we emit) is noticed. (Other jump counts are a machine convention, not asserted.)
            self.assertEqual(their_trim, st["trims"], f"{name}: pyembroidery sees {their_trim} trims, we wrote {st['trims']}")
            # informational only: where the two libraries put the origin (not asserted - DST has no absolute origin)
            print(f"[crosscheck] {name}: ok; first stitch ours={our_xy[0]} theirs={their_xy[0]}")


if __name__ == "__main__":
    unittest.main()
