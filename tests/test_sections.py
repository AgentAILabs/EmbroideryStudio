"""Five separate validation sections: independence, no combined score, DST checks from the bytes, preview == export, physical only from evidence."""
import base64, io, json, os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import sections as SEC, export_pipeline as EP, evidence as EV
import app as server

D = {"name": "sec", "hoop": {"w": 100, "h": 100, "margin": 3}, "objects": [{"id": "a", "type": "run", "color": "#ff0000", "points": [[0, 0], [30, 0], [30, 20], [0, 20]]}]}


def by(r, sid): return next(s for s in r["sections"] if s["id"] == sid)


class SectionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); os.environ["ES_EVIDENCE_DIR"] = self.tmp.name
        self.res = EP.export_dst(D)
    def tearDown(self):
        os.environ.pop("ES_EVIDENCE_DIR", None); self.tmp.cleanup()

    def test_exactly_five_sections_in_order_no_combined_score(self):
        r = SEC.build(D, self.res)
        self.assertEqual([s["id"] for s in r["sections"]], list(SEC.SECTION_IDS)); self.assertIsNone(r["combined_score"])
        txt = json.dumps(r)
        for banned in ('"overall_score"', '"total_score"', '"combined"', '"confidence"'):
            self.assertNotIn(banned, txt)
        for s in r["sections"]:
            self.assertTrue(s["question"] and s["title"]); self.assertIn("not_measured", s)

    def test_every_metric_documents_how(self):
        r = SEC.build(D, self.res)
        for s in r["sections"]:
            for m in s["metrics"]:
                self.assertTrue(m["how"], f"{s['id']}/{m['name']} has no documentation")

    def test_software_verdict_never_claims_physical(self):
        r = SEC.build(D, self.res)
        self.assertEqual(by(r, "physical")["verdict"], "PENDING"); self.assertIn("software only", by(r, "stitch_path")["verdict"])
        self.assertIn("a high software score does not prove physical stitching success", by(r, "stitch_path")["not_measured"])

    def test_dst_section_passes_on_real_export_and_checks_preview_equals_export(self):
        s = by(SEC.build(D, self.res), "independent_dst"); self.assertEqual(s["verdict"], "PASSED")
        names = {m["name"]: m for m in s["metrics"]}
        for n in ("end record", "largest record movement", "header extents vs decoded", "fits the hoop (decoded extents)", "re-import (project reader)", "preview == export"):
            self.assertEqual(names[n]["result"], "PASSED", n)

    def test_missing_end_record_detected(self):
        data = bytearray(self.res.data)
        for i in range(len(data) - 3, len(data), 3): pass
        bad = bytes(data[:-3])                                            # drop the END record
        ms = {m["name"]: m for m in SEC.dst_checks(bad, D["hoop"])}
        self.assertEqual(ms["end record"]["result"], "FAILED")

    def test_corrupted_header_extents_flagged(self):
        data = self.res.data.replace(b"+X:", b"+X:9", 1)
        ms = {m["name"]: m for m in SEC.dst_checks(data, D["hoop"])}
        self.assertNotEqual(ms["header extents vs decoded"]["result"], "PASSED")

    def test_truncated_file_fails_readable_check(self):
        ms = SEC.dst_checks(self.res.data[:100], D["hoop"]); self.assertEqual(ms[0]["result"], "FAILED")

    def test_hoop_fit_rule(self):
        self.assertTrue(SEC.hoop_fit((94, 94), {"w": 100, "h": 100, "margin": 3})["fits"])
        self.assertFalse(SEC.hoop_fit((94.5, 50), {"w": 100, "h": 100, "margin": 3})["fits"])
        self.assertFalse(SEC.hoop_fit((50, 95), {"w": 100, "h": 100, "margin": 3})["fits"])

    def test_preview_equals_export_detects_a_mutated_preview(self):
        sim = EP.decoded_simulation(D)
        sim["stitches"] = [[x + (1.0 if i == 5 else 0.0), y, c, t, o] for i, (x, y, c, t, o) in enumerate(sim["stitches"])]
        s = SEC.dst_section(D, self.res, sim); m = next(x for x in s["metrics"] if x["name"] == "preview == export")
        self.assertEqual(m["result"], "FAILED"); self.assertEqual(s["verdict"], "FAILED")

    def test_physical_follows_evidence_only(self):
        self.assertEqual(by(SEC.build(D, self.res), "physical")["verdict"], "PENDING")
        EV.create(dict(dst_sha256=self.res.sha256, design_name="sec", final_inspection="pass"))
        self.assertEqual(by(SEC.build(D, self.res), "physical")["verdict"], "INCOMPLETE")
        full = dict(dst_sha256=self.res.sha256, operator="o", design_name="sec", design_version="1", machine_model="m", fabric="f", stabiliser="s", needle="n", thread="t", hoop="h",
                    stitch_count=38, speed_spm=500, thread_breaks=0, skipped_stitches=0, puckering=0, registration_mm=0.2, jump_trim_result="ok", final_inspection="pass")
        EV.create(full, now=4102444800)
        self.assertEqual(by(SEC.build(D, self.res), "physical")["verdict"], "PASSED")
        D2 = json.loads(json.dumps(D)); D2["objects"][0]["points"][1] = [31, 0]; res2 = EP.export_dst(D2)
        self.assertEqual(by(SEC.build(D2, res2), "physical")["verdict"], "STALE")

    def test_source_section_without_image_is_not_assessed(self):
        self.assertEqual(by(SEC.build(D, self.res), "source_quality")["verdict"], "NOT ASSESSED")

    def test_source_and_preservation_sections_from_image(self):
        try:
            import numpy as np
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow/NumPy not installed")
        y, x = np.mgrid[0:200, 0:200]; a = np.full((200, 200, 3), 255.0); a[(abs(x - 100) < 60) & (abs(y - 100) < 40)] = (200, 20, 20)
        b = io.BytesIO(); Image.fromarray(a.astype(np.uint8)).save(b, "PNG")
        out = server.api_report_sections({"design": D, "image": base64.b64encode(b.getvalue()).decode(), "width_mm": 60})
        self.assertEqual(len(out["sections"]), 5); self.assertNotEqual(by(out, "source_quality")["verdict"], "NOT ASSESSED"); self.assertGreater(len(by(out, "source_quality")["metrics"]), 5)

    def test_photo_api_returns_sections_with_photo_preservation(self):
        try:
            import numpy as np
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow/NumPy not installed")
        y, x = np.mgrid[0:200, 0:200]; r = np.hypot(x - 100, y - 100) / 80; v = np.where(r < 1, 235 - 170 * np.clip(1 - r * r, 0, 1) ** .6, 235.0)
        b = io.BytesIO(); Image.fromarray(np.stack([v] * 3, -1).astype(np.uint8)).save(b, "PNG")
        out = server.api_photo_stitch({"data": base64.b64encode(b.getvalue()).decode(), "width_mm": 50})
        secs = out["sections"]; self.assertEqual([s["id"] for s in secs["sections"]], list(SEC.SECTION_IDS))
        self.assertTrue(any(m["name"].startswith("photo:") for m in by(secs, "preservation")["metrics"]))
        self.assertEqual(by(secs, "independent_dst")["verdict"], "PASSED"); self.assertEqual(by(secs, "physical")["verdict"], "PENDING")

    def test_sections_api_validation(self):
        with self.assertRaises(ValueError): server.api_report_sections({})


if __name__ == "__main__":
    unittest.main()
