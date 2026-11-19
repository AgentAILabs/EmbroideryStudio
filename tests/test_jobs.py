"""Background job pool: lifecycle, errors, cancel, TTL, limits, and the HTTP endpoints."""
import json, sys, threading, time, unittest, urllib.request, urllib.error
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
import jobs as J
import app as server


def wait(j, jid, until=("done", "failed", "cancelled"), t=5.0):
    end = time.time() + t
    while time.time() < end:
        st = j.status(jid)
        if st["status"] in until: return st
        time.sleep(0.01)
    raise AssertionError("job did not finish")


class Lifecycle(unittest.TestCase):
    def test_done_with_result(self):
        j = J.Jobs({"echo": lambda p: {"got": p["x"] * 2}}); jid = j.start("echo", {"x": 21}); st = wait(j, jid)
        self.assertEqual(st["status"], "done"); self.assertEqual(st["result"], {"got": 42}); self.assertIn("elapsed_s", st)

    def test_value_error_is_reported_internal_errors_are_not_leaked(self):
        def boom(p):
            if p.get("v"): raise ValueError("bad input")
            raise RuntimeError("secret internal detail /etc/passwd")
        j = J.Jobs({"x": boom}); a = wait(j, j.start("x", {"v": 1})); b = wait(j, j.start("x", {}))
        self.assertEqual((a["status"], a["error"]), ("failed", "bad input")); self.assertEqual(b["status"], "failed"); self.assertNotIn("secret", b["error"]); self.assertIn("RuntimeError", b["error"])

    def test_unknown_kind_and_job(self):
        j = J.Jobs({"x": lambda p: 1})
        with self.assertRaises(J.JobError): j.start("nope", {})
        with self.assertRaises(J.JobError): j.start("x", "not a dict")
        with self.assertRaises(J.JobError): j.status("missing")
        with self.assertRaises(J.JobError): j.cancel("missing")

    def test_cancel_discards_the_result(self):
        gate = threading.Event(); j = J.Jobs({"slow": lambda p: (gate.wait(3), "late")[1]}); jid = j.start("slow", {}); wait(j, jid, ("running",))
        self.assertTrue(j.cancel(jid)); gate.set(); time.sleep(0.2); st = j.status(jid); self.assertEqual(st["status"], "cancelled"); self.assertNotIn("result", st)
        done = wait(j, j.start("slow", {}))["id"]; self.assertFalse(j.cancel(done))                                        # a finished job cannot be cancelled

    def test_runs_in_parallel_up_to_the_pool_size_and_queues_the_rest(self):
        gate = threading.Event(); j = J.Jobs({"s": lambda p: gate.wait(3)}, workers=2); ids = [j.start("s", {}) for _ in range(3)]; time.sleep(0.15)
        self.assertEqual(sorted(j.status(i)["status"] for i in ids), ["queued", "running", "running"]); gate.set(); [wait(j, i) for i in ids]

    def test_ttl_cleanup(self):
        now = [1000.0]; j = J.Jobs({"x": lambda p: 1}, clock=lambda: now[0]); jid = wait(j, j.start("x", {}))["id"]; now[0] += J.TTL_S + 5; j.start("x", {})
        with self.assertRaises(J.JobError): j.status(jid)

    def test_queue_limit(self):
        gate = threading.Event(); j = J.Jobs({"s": lambda p: gate.wait(3)}, workers=1)
        try:
            for _ in range(J.MAX_JOBS): j.start("s", {})
            with self.assertRaises(J.JobError): j.start("s", {})
        finally: gate.set()


class Http(unittest.TestCase):
    def test_endpoints_run_a_real_conversion_and_poll(self):
        import base64, io
        try:
            from PIL import Image, ImageDraw
        except ImportError: self.skipTest("Pillow not installed")
        im = Image.new("RGB", (200, 120), "white"); ImageDraw.Draw(im).rectangle([20, 20, 120, 90], fill=(200, 0, 0)); b = io.BytesIO(); im.save(b, "PNG")
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); threading.Thread(target=srv.serve_forever, daemon=True).start(); base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            post = lambda u, d: json.loads(urllib.request.urlopen(urllib.request.Request(base + u, data=json.dumps(d).encode(), method="POST")).read())
            jid = post("/api/job/start", {"kind": "raster", "payload": {"data": base64.b64encode(b.getvalue()).decode(), "width_mm": 50, "colors": 3}})["id"]
            for _ in range(200):
                st = json.loads(urllib.request.urlopen(f"{base}/api/job/status?id={jid}").read())
                if st["status"] in ("done", "failed"): break
                time.sleep(0.05)
            self.assertEqual(st["status"], "done"); self.assertTrue(st["result"]["objects"])
            with self.assertRaises(urllib.error.HTTPError) as cm: urllib.request.urlopen(urllib.request.Request(base + "/api/job/start", data=json.dumps({"kind": "rm -rf"}).encode(), method="POST"))
            self.assertEqual(cm.exception.code, 400)
            with self.assertRaises(urllib.error.HTTPError) as cm: urllib.request.urlopen(f"{base}/api/job/status?id=nope")
            self.assertEqual(cm.exception.code, 404)
            bad = post("/api/job/start", {"kind": "raster", "payload": {"data": "AAAA"}})["id"]
            for _ in range(100):
                st = json.loads(urllib.request.urlopen(f"{base}/api/job/status?id={bad}").read())
                if st["status"] != "queued" and st["status"] != "running": break
                time.sleep(0.05)
            self.assertEqual(st["status"], "failed")
        finally: srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main()
