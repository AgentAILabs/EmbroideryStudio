"""Physical-validation evidence workflow: statuses, checksum binding, tamper refusal, and that the repository ships no fabricated records."""
import json, os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import evidence as EV
import app as server

SHA = "a" * 64; SHA2 = "b" * 64
FULL = dict(dst_sha256=SHA, operator="op", design_name="d1", design_version="v1", machine_model="Ricoma X", fabric="cotton", stabiliser="cut-away", needle="75/11", thread="40wt poly", hoop="150 mm",
            stitch_count=12000, speed_spm=600, thread_breaks=0, skipped_stitches=0, puckering=1, registration_mm=0.4, jump_trim_result="ok", final_inspection="pass")


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); os.environ["ES_EVIDENCE_DIR"] = self.tmp.name
    def tearDown(self):
        os.environ.pop("ES_EVIDENCE_DIR", None); self.tmp.cleanup()

    def test_repo_ships_no_records(self):
        os.environ.pop("ES_EVIDENCE_DIR", None)
        self.assertEqual(list((ROOT / "evidence").glob("ev_*.json")), [], "the repository must not contain fabricated physical test records")
        self.assertEqual(EV.status_for(SHA)["status"], "PENDING")

    def test_pending_with_no_record(self):
        st = EV.status_for(SHA, "d1"); self.assertEqual(st["status"], "PENDING"); self.assertIsNone(st["record"])

    def test_incomplete_until_all_required_fields(self):
        part = dict(FULL); del part["puckering"]; del part["needle"]
        EV.create(part); st = EV.status_for(SHA)
        self.assertEqual(st["status"], "INCOMPLETE"); self.assertEqual(sorted(st["missing"]), ["needle", "puckering"])

    def test_passed_only_when_complete_and_inspection_pass(self):
        EV.create(FULL); self.assertEqual(EV.status_for(SHA)["status"], "PASSED")

    def test_pass_with_notes_and_failed(self):
        EV.create(dict(FULL, final_inspection="pass_with_notes")); self.assertEqual(EV.status_for(SHA)["status"], "PASSED_WITH_NOTES")
        EV.create(dict(FULL, final_inspection="fail"), now=4102444800); self.assertEqual(EV.status_for(SHA)["status"], "FAILED")      # the latest record decides

    def test_stale_when_checksum_changes(self):
        EV.create(FULL); st = EV.status_for(SHA2, "d1"); self.assertEqual(st["status"], "STALE"); self.assertIn("checksum differs", st["detail"])
        self.assertEqual(EV.status_for(SHA2, "other")["status"], "PENDING")

    def test_cannot_pass_without_inspection_field(self):
        d = dict(FULL); del d["final_inspection"]; EV.create(d); self.assertEqual(EV.status_for(SHA)["status"], "INCOMPLETE")

    def test_input_validation(self):
        for bad in (dict(FULL, dst_sha256="xyz"), dict(FULL, puckering=7), dict(FULL, final_inspection="great"), dict(FULL, thread_breaks=-1), dict(FULL, stitch_count=True), dict(FULL, photo_sha256=["no"]), "x"):
            with self.assertRaises(ValueError): EV.create(bad)

    def test_tamper_refused(self):
        rec = EV.create(dict(FULL, final_inspection="fail")); forged = dict(rec, final_inspection="pass")
        with self.assertRaises(ValueError): EV.import_record(forged)
        p = Path(self.tmp.name) / f"{rec['id']}.json"; j = json.loads(p.read_text()); j["final_inspection"] = "pass"; p.write_text(json.dumps(j))
        self.assertEqual(EV.status_for(SHA)["status"], "PENDING", "a hand-edited file on disk is ignored, not trusted")

    def test_export_import_round_trip(self):
        rec = EV.create(FULL)
        with tempfile.TemporaryDirectory() as d2:
            os.environ["ES_EVIDENCE_DIR"] = d2; EV.import_record(json.loads(json.dumps(rec))); self.assertEqual(EV.status_for(SHA)["status"], "PASSED")
            os.environ["ES_EVIDENCE_DIR"] = self.tmp.name

    def test_code_never_creates_results_on_its_own(self):
        EV.create({"dst_sha256": SHA}); st = EV.status_for(SHA); self.assertEqual(st["status"], "INCOMPLETE")
        self.assertNotIn("final_inspection", st["record"])

    def test_checklist(self):
        self.assertGreaterEqual(len(EV.CHECKLIST), 6)

    def test_api_functions(self):
        from http.server import HTTPServer
        import threading, urllib.request
        srv = HTTPServer(("127.0.0.1", 0), server.H) if True else None
        if srv is None: self.skipTest("no Handler class exposed")
        t = threading.Thread(target=srv.serve_forever, daemon=True); t.start(); base = f"http://127.0.0.1:{srv.server_port}"
        try:
            j = json.loads(urllib.request.urlopen(f"{base}/api/evidence?sha={SHA}").read()); self.assertEqual(j["status"], "PENDING")
            req = urllib.request.Request(f"{base}/api/evidence", data=json.dumps(FULL).encode(), method="POST"); r = json.loads(urllib.request.urlopen(req).read())
            self.assertEqual(r["status"]["status"], "PASSED")
            j = json.loads(urllib.request.urlopen(f"{base}/api/evidence?sha={SHA}").read()); self.assertEqual(j["status"], "PASSED")
            self.assertEqual(len(json.loads(urllib.request.urlopen(f"{base}/api/evidence/records").read())["records"]), 1)
            with self.assertRaises(Exception): urllib.request.urlopen(f"{base}/api/evidence?sha=zz")
        finally:
            srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main()
