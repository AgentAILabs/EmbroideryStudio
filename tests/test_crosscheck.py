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


@unittest.skipIf(pyembroidery is None, "pyembroidery not installed (CI installs it)")
class PyembroideryExpCrossCheck(unittest.TestCase):
    """Our EXP writer read back by pyembroidery. A mismatch is a bug in exp.py (or in this test's reading of the library) - the
    message prints enough to tell which."""
    def test_exp_stitches_colour_changes_and_trims_match(self):
        from stitchcraft_engine.exp import write_exp
        for name, d in designs().items():
            pat, _, st = generate(d); data = write_exp(pat)
            with tempfile.TemporaryDirectory() as t:
                f = Path(t) / "x.exp"; f.write_bytes(data); theirs = pyembroidery.read(str(f))
            self.assertIsNotNone(theirs, name)
            C = pyembroidery.COMMAND_MASK
            from collections import Counter
            names = {getattr(pyembroidery, n): n for n in ("STITCH", "JUMP", "TRIM", "COLOR_CHANGE", "STOP", "END", "NEEDLE_SET") if hasattr(pyembroidery, n)}
            tc = Counter(names.get(cmd & C, hex(cmd & C)) for _, _, cmd in theirs.stitches)
            first = next((i for i, (_, _, cmd) in enumerate(theirs.stitches) if (cmd & C) not in (pyembroidery.STITCH,)), None)
            print(f"[crosscheck-exp] {name}: wrote {len(data)} bytes; ours stitches={st['stitches']} jumps={st['jumps']} trims={st['trims']} colour={st['color_changes']} | theirs {dict(tc)}")
            seq_theirs = [(i, names.get(cmd & C, hex(cmd & C)), int(x), int(y)) for i, (x, y, cmd) in enumerate(theirs.stitches) if (cmd & C) != pyembroidery.STITCH]
            from stitchcraft_engine.exp import read_exp
            seq_ours = [(i, k, dx, dy) for i, (k, dx, dy) in enumerate(read_exp(data)) if k != "stitch"]
            print(f"[crosscheck-exp]   NON-STITCH ours  (record#, kind, dx, dy): {seq_ours[:8]}")
            print(f"[crosscheck-exp]   NON-STITCH theirs(cmd#, kind, x, y)    : {seq_theirs[:8]}")
            if first is not None:
                print(f"[crosscheck-exp]   theirs around first non-stitch: {[(int(x), int(y), names.get(cmd & C, hex(cmd & C))) for x, y, cmd in theirs.stitches[max(0, first - 2):first + 4]]}")
                print(f"[crosscheck-exp]   our bytes at the start: {data[:12].hex(' ')}")
            their_xy = [(int(x), int(y)) for x, y, cmd in theirs.stitches if (cmd & C) == pyembroidery.STITCH]
            self.assertEqual(len(their_xy), st["stitches"], f"{name}: stitch count {len(their_xy)} vs {st['stitches']}")
            ours = [(s.x, s.y) for s in pat.stitches if s.cmd.value == "stitch"]
            bb = pat.bbox(); ox, oy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            our_xy = [(round((x - ox) * 10), round(-(y - oy) * 10)) for x, y in ours]          # centred, 0.1 mm, y up (as written)
            td = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(their_xy, their_xy[1:])]
            od = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(our_xy, our_xy[1:])]
            flipped = [(dx, -dy) for dx, dy in td]
            if td != od and flipped != od:
                bad = next((i for i, (u, v) in enumerate(zip(od, td)) if u != v), -1)
                self.fail(f"{name}: EXP stitch deltas differ at {bad}\n  ours  : {od[max(0, bad - 2):bad + 4]}\n  theirs: {td[max(0, bad - 2):bad + 4]}"
                          f"\n  first abs ours {our_xy[:3]} theirs {their_xy[:3]}")
            cc = sum(1 for _, _, cmd in theirs.stitches if (cmd & C) == pyembroidery.COLOR_CHANGE)
            tr = sum(1 for _, _, cmd in theirs.stitches if (cmd & C) == pyembroidery.TRIM)
            print(f"[crosscheck-exp] {name}: stitches ok; colour changes ours={st['color_changes']} theirs={cc}; trims ours={st['trims']} theirs={tr}; y {'flipped' if td != od else 'same'}")
            self.assertEqual(cc, st["color_changes"], name)
            self.assertEqual(tr, st["trims"], name)


if __name__ == "__main__":
    unittest.main()
