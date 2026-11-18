"""DST quality: tolerant reader (real-world files), thread presets, underlay/tatami clean-up, multi-stage verifier."""
import json, math, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
for sub in ("engine", "server", "tools"):
    sys.path.insert(0, str(ROOT / sub))
from stitchcraft_engine.design import generate, run_checks, THREADS, machine
from stitchcraft_engine.dst import write_dst, read_dst, DstError, HEADER_SIZE
from stitchcraft_engine.model import Cmd
from stitchcraft_engine.stitches import tatami_fill, underlay_path
from stitchcraft_engine import dst_analyze as A, dst_verify as V
import app as server

SQ = [[0, 0], [30, 0], [30, 20], [0, 20]]
def doc(*objs, **kw): return dict({"name": "t", "hoop": {"w": 100, "h": 100, "margin": 3}, "objects": list(objs)}, **kw)
def column(oid="c", w=2.5, n=12):
    r1 = [[i * 3.0, 0] for i in range(n)]; r2 = [[i * 3.0, w] for i in range(n)]
    return {"id": oid, "type": "column", "color": "#c00", "rail1": r1, "rail2": r2, "params": {"underlay": "center"}}


class TolerantReaderTests(unittest.TestCase):
    """Wilcom/Pulse/Tajima files end with END (00 00 F3) followed by a lone 0x1A; our strict reader used to reject 19 of 20 such files."""
    def base(self):
        return write_dst(generate(doc({"id": "f", "type": "fill", "color": "#f00", "rings": [SQ]}))[0]).data
    def test_trailing_eof_marker_is_accepted(self):
        d = self.base(); a = read_dst(d); b = read_dst(d + b"\x1a")
        self.assertTrue(b.ends_properly); self.assertEqual(a.records, b.records)
    def test_trailing_zero_padding_is_accepted(self):
        self.assertTrue(read_dst(self.base() + b"\x1a\x00\x00").ends_properly)
    def test_garbage_after_end_is_rejected(self):
        with self.assertRaises(DstError): read_dst(self.base() + b"\x1a\x01\x02\x03\x04")
    def test_truncated_file_is_still_rejected(self):
        d = self.base()
        with self.assertRaises(DstError): read_dst(d[:-4])                      # cut off before the END record
    def test_hand_made_file_in_real_world_layout(self):
        hdr = b"LA:T".ljust(20, b" ") + b"\r"
        hdr = (b"LA:T               \rST:      3\rCO:  1\r+X:    1\r-X:    0\r+Y:    0\r-Y:    0\rAX:+    0\rAY:+    0\rMX:+    0\rMY:+    0\rPD:******\r\x1a").ljust(HEADER_SIZE, b" ")
        body = bytes([0x01, 0x00, 0x03]) + bytes([0x00, 0x00, 0xF3]) + b"\x1a"   # one +0.1 mm stitch, END, EOF marker
        f = read_dst(hdr + body); self.assertEqual(f.positions[0], (1, 0)); self.assertTrue(f.ends_properly)


class ThreadPresetTests(unittest.TestCase):
    def satin_pitch(self, thread):
        d = doc(column(), thread=thread) if thread else doc(column())
        p, _, st = generate(d); run = [(s.x, s.y) for s in p.stitches if s.cmd == Cmd.STITCH]
        pitch, n = V.satin_advance([run]); return pitch / 2, st
    def test_finer_thread_means_closer_lines(self):
        base, _ = self.satin_pitch(None); t60, _ = self.satin_pitch("60wt"); t120, _ = self.satin_pitch("120")
        self.assertAlmostEqual(base, 0.4, delta=0.06); self.assertLess(t60, base); self.assertLess(t120, t60)
        self.assertAlmostEqual(t120, 0.22, delta=0.05)                         # production files measured 0.21 mm
    def test_explicit_object_spacing_wins(self):
        c = column(); c["params"]["spacing"] = 0.5
        p, _, _ = generate(doc(c, thread="120")); run = [(s.x, s.y) for s in p.stitches if s.cmd == Cmd.STITCH]
        self.assertAlmostEqual(V.satin_advance([run])[0] / 2, 0.5, delta=0.07)
    def test_unknown_thread_rejected_and_reported_in_stats(self):
        with self.assertRaises(ValueError): generate(doc(column(), thread="nope"))
        self.assertEqual(generate(doc(column(), thread="60wt"))[2]["thread"], "60wt")
        self.assertEqual(generate(doc(column()))[2]["thread"], "40wt")
    def test_fine_thread_lock_is_one_mm_and_checks_stay_clean(self):
        d = doc(column(), thread="120")
        p, _, _ = generate(d); self.assertTrue(run_checks(d, p).ok); self.assertEqual([i for i in run_checks(d, p).issues if i.severity == "warning"], [])
    def test_all_presets_documented(self):
        for k, v in THREADS.items(): self.assertTrue(v["label"]); self.assertGreater(v["k"], 0)


class StitchCleanUpTests(unittest.TestCase):
    def test_column_underlay_is_not_one_stitch_per_half_mm(self):
        p, _, _ = generate(doc(column(w=2.5, n=12)))
        under = []; seq = [s for s in p.stitches]
        # underlay runs first: its stitches are the ones before the first zig-zag reversal; check typical lengths overall
        L = [math.dist((a.x, a.y), (b.x, b.y)) for a, b in zip(seq, seq[1:]) if a.cmd == Cmd.STITCH and b.cmd == Cmd.STITCH]
        self.assertLess(sum(1 for l in L if l < 0.5) / len(L), 0.06)
    def test_underlay_path_keeps_shape_within_tolerance(self):
        arc = [(10 * math.cos(t / 40.0), 10 * math.sin(t / 40.0)) for t in range(0, 63 * 4, 2)]       # ~0.5 mm vertex spacing
        out = underlay_path(arc, 0.1); self.assertLess(len(out), len(arc) / 2)
        for q in out: self.assertAlmostEqual(math.hypot(*q), 10.0, delta=0.11)
    def test_tatami_rows_have_no_tiny_end_stubs(self):
        runs = tatami_fill([[(0, 0), (23.3, 0), (23.3, 9.7), (0, 9.7)]], 0, 0.4, 3.5)
        stubs = 0
        for r in runs:
            for a, b in zip(r, r[1:]):
                if abs(a[1] - b[1]) < 1e-6 and math.dist(a, b) < 0.69: stubs += 1
        self.assertEqual(stubs, 0)
    def test_satin_tapering_to_a_point_has_no_micro_stitches(self):
        c = {"id": "t", "type": "column", "color": "#c00", "params": {"underlay": "none"},
             "rail1": [[0, 0], [10, 2], [20, 0]], "rail2": [[0, 0], [10, -2], [20, 0]]}
        p, _, _ = generate(doc(c)); S = [s for s in p.stitches if s.cmd == Cmd.STITCH]
        self.assertEqual([1 for a, b in zip(S, S[1:]) if math.dist((a.x, a.y), (b.x, b.y)) < 0.3], [])


class AnalyzerAndVerifierTests(unittest.TestCase):
    def lib(self, name):
        return (ROOT / "designs" / "library" / name / f"{name}.dst").read_bytes()
    def test_analyzer_basic_metrics(self):
        a = A.analyze(self.lib("bride_frame"), "bride_frame")
        self.assertGreater(a["stitches"], 1000); self.assertEqual(a["colour_blocks"], 4); self.assertGreater(a["trims"], 5)
        self.assertLess(a["len_max"], 12.2); self.assertLess(a["pct_short_clustered"], 3.0)
    def test_every_library_design_passes_all_six_stages_without_failure(self):
        idx = json.loads((ROOT / "designs" / "library" / "index.json").read_text())
        items = idx["designs"] if isinstance(idx, dict) else idx
        self.assertGreaterEqual(len(items), 12)
        for it in items:
            name = it["id"]; r = V.verify(self.lib(name), hoop=(200, 300), name=name)
            self.assertEqual([s["stage"] for s in r["stages"]], ["1 container", "2 encoding", "3 machine", "4 stitch", "5 thread path", "6 simulation"])
            self.assertNotEqual(r["grade"], "FAIL", (name, [(s["stage"], c) for s in r["stages"] for c in s["checks"] if c["level"] == "FAIL"]))
    def test_verifier_catches_a_corrupt_header_and_an_oversize_design(self):
        d = bytearray(self.lib("kalash")); i = d.index(b"ST:"); d[i + 3:i + 9] = b"   999"
        r = V.verify(bytes(d), (200, 300)); self.assertEqual(r["stages"][0]["result"], "WARN")
        r = V.verify(self.lib("kalash"), hoop=(20, 20)); self.assertEqual(r["grade"], "FAIL")
        self.assertTrue(any(c["level"] == "FAIL" and "hoop" in c["what"] for s in r["stages"] for c in s["checks"]))
    def test_verifier_rejects_a_truncated_file(self):
        r = V.verify(self.lib("kalash")[:-4], (200, 300)); self.assertEqual(r["grade"], "FAIL")
    def test_v1_peacock_archive_passes_verifier(self):
        v1 = (ROOT / "designs" / "peacock_arch" / "v1_tested" / "peacock_arch_panel_v1.dst").read_bytes()
        self.assertNotEqual(V.verify(v1, (200, 300))["grade"], "FAIL")
    def test_api_analyze_and_verify(self):
        import base64
        data = base64.b64encode(self.lib("kalash")).decode()
        r = server.api_dst_report({"data": data, "hoop_w": 200, "hoop_h": 300, "thread": "40wt"})
        self.assertEqual(r["verify"]["grade"], "PASS"); self.assertGreater(r["analysis"]["stitches"], 1000)
        with self.assertRaises(ValueError): server.api_dst_report({"data": base64.b64encode(b"nope").decode()})


if __name__ == "__main__":
    unittest.main()
