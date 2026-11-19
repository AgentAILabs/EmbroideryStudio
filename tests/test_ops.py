"""Operational hardening: request ids, logged 500s, rate limiting, security headers, upload policy, performance budgets."""
import contextlib, io, json, math, sys, threading, time, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
import app as server, ops

class Limiter(unittest.TestCase):
    def test_bucket_allows_burst_then_blocks_then_refills(self):
        t = [0.0]; rl = ops.RateLimiter(60, 5, clock=lambda: t[0])
        self.assertTrue(all(rl.allow("a")[0] for _ in range(5)))
        ok, retry = rl.allow("a"); self.assertFalse(ok); self.assertGreaterEqual(retry, 1)
        self.assertTrue(rl.allow("b")[0])                                   # other clients are independent
        t[0] += 2.0; self.assertTrue(rl.allow("a")[0])                      # 60/min = 1 token per second
    def test_heavy_endpoints_cost_more_and_zero_disables(self):
        self.assertGreater(ops.cost_of("/api/export/dst"), ops.cost_of("/api/generate"))
        rl = ops.RateLimiter(0, 1); self.assertTrue(all(rl.allow("x")[0] for _ in range(100)))

class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._lvl = ops.LOG_LEVEL; ops.LOG_LEVEL = "info"
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); ops.LOG_LEVEL = cls._lvl
    def call(self, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST" if data is not None else "GET")
        try:
            r = urllib.request.urlopen(req, timeout=30); return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e: return e.code, e.headers, e.read()
    def test_security_headers_and_request_id_on_every_response(self):
        for path in ("/", "/api/machines"):
            c, h, _ = self.call(path); self.assertEqual(c, 200)
            self.assertEqual(h["X-Content-Type-Options"], "nosniff"); self.assertEqual(h["X-Frame-Options"], "DENY"); self.assertIn("default-src 'self'", h["Content-Security-Policy"]); self.assertTrue(h["X-Request-Id"])
    def test_invalid_json_is_400_not_500(self):
        c, _, b = self.call("/api/generate", raw=b"{not json"); self.assertEqual(c, 400); self.assertIn("JSON", json.loads(b)["error"])
    def test_unexpected_exception_is_logged_with_request_id_and_returned_to_the_caller(self):
        real = server.api_generate
        def boom(d): raise RuntimeError("synthetic failure")
        server.api_generate = boom; err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err): c, h, b = self.call("/api/generate", {"objects": []})
        finally: server.api_generate = real
        self.assertEqual(c, 500); j = json.loads(b); rid = h["X-Request-Id"]; self.assertEqual(j["request_id"], rid); self.assertIn(rid, j["error"])
        lines = [json.loads(l) for l in err.getvalue().splitlines() if l.startswith("{")]
        rec = [l for l in lines if l["event"] == "unhandled_exception"]; self.assertTrue(rec); self.assertEqual(rec[0]["rid"], rid); self.assertEqual(rec[0]["error_type"], "RuntimeError"); self.assertIn("synthetic failure", rec[0]["error"])
    def test_logs_never_contain_request_bodies(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.call("/api/generate", {"name": "SECRET-CUSTOMER-NAME", "hoop": {"w": 100, "h": 100}, "objects": []})
            for _ in range(100):                                   # the access line is written after the response is sent: wait for it (was a race)
                if '"event": "request"' in err.getvalue(): break
                time.sleep(0.02)
        self.assertNotIn("SECRET-CUSTOMER-NAME", err.getvalue()); self.assertIn('"event": "request"', err.getvalue())
    def test_rate_limit_returns_429_with_retry_after(self):
        real = server.LIMITER; server.LIMITER = ops.RateLimiter(60, 2)
        try:
            codes = [self.call("/api/machines")[0] for _ in range(4)]
            c, h, b = self.call("/api/machines")
        finally: server.LIMITER = real
        self.assertEqual(codes[:2], [200, 200]); self.assertIn(429, codes); self.assertEqual(c, 429); self.assertTrue(h["Retry-After"]); self.assertIn("request_id", json.loads(b))
    def test_export_is_audit_logged_without_the_design(self):
        d = {"name": "AUDITNAME", "hoop": {"w": 100, "h": 100}, "objects": [{"id": "r", "type": "run", "color": "#000", "points": [[0, 0], [20, 0]]}]}
        err = io.StringIO()
        with contextlib.redirect_stderr(err): c, _, _ = self.call("/api/export/dst", d)
        self.assertEqual(c, 200); rec = [json.loads(l) for l in err.getvalue().splitlines() if '"export_dst"' in l][0]
        self.assertEqual(rec["result"], "released"); self.assertEqual(len(rec["dst_sha256"]), 64); self.assertNotIn("AUDITNAME", err.getvalue())
    def test_upload_policy(self):
        with self.assertRaises(ValueError): ops.check_base64_upload("x" * (ops.MAX_UPLOAD_B64 + 1))
        with self.assertRaises(ValueError): ops.check_dst_upload(b"short")
        c, _, b = self.call("/api/import/dst", {"data": "AAAA"}); self.assertEqual(c, 400)
        c, _, b = self.call("/api/import/raster", {"data": 123}); self.assertEqual(c, 400)

class PerformanceBudgets(unittest.TestCase):
    """Generous wall-clock budgets (CI machines are slower than a laptop): they catch accidental O(n^2) regressions, not tuning."""
    def test_3000_objects_generate_and_export(self):
        objs = [{"id": f"r{i}", "type": "run", "color": ["#c00", "#00c", "#0a0"][i % 3], "points": [[(i % 60) * 3.0 - 90, (i // 60) * 3.0 - 75], [(i % 60) * 3.0 - 88, (i // 60) * 3.0 - 75], [(i % 60) * 3.0 - 88, (i // 60) * 3.0 - 73]]} for i in range(3000)]
        d = {"name": "big", "hoop": {"w": 400, "h": 400, "margin": 3}, "objects": objs}
        t = time.time(); server.check_design(d); r = server.api_generate(d); self.assertGreater(len(r["stitches"]), 10000); self.assertLess(time.time() - t, 30)
        t = time.time(); res, err = server.api_dst(d); self.assertIsNone(err); self.assertLess(time.time() - t, 90)
    def test_dense_rings_do_not_blow_up(self):
        """Regression: ring_self_intersections was O(n^2) - 100 rings x 4000 points took minutes. Now grid-accelerated."""
        objs = [{"id": f"f{i}", "type": "fill", "color": "#c00", "rings": [[[(i % 5) * 40 - 80 + 10 * math.cos(2 * math.pi * k / 4000), (i // 5) * 40 - 80 + 10 * math.sin(2 * math.pi * k / 4000)] for k in range(4000)]]} for i in range(10)]
        d = {"name": "dense", "hoop": {"w": 300, "h": 300, "margin": 3}, "objects": objs}
        t = time.time(); res, err = server.api_dst(d); self.assertIsNone(err, err); self.assertLess(time.time() - t, 60)
        t = time.time(); server.api_quality(d); self.assertLess(time.time() - t, 60)
    def test_self_intersection_grid_matches_brute_force(self):
        import random
        from stitchcraft_engine.geometry import ring_self_intersections as rsi
        def brute(ring):
            P = [tuple(p) for p in ring]; n = len(P); f = 0
            o = lambda a, b, c: (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            for i in range(n):
                for j in range(i + 2, n):
                    if i == 0 and j == n - 1: continue
                    a, b, c, d = P[i], P[(i + 1) % n], P[j], P[(j + 1) % n]
                    if o(c, d, a) * o(c, d, b) < -1e-12 and o(a, b, c) * o(a, b, d) < -1e-12: f += 1
            return f
        random.seed(5)
        for t in range(40):
            n = random.choice([70, 90, 130]); ring = [(random.uniform(0, 50), random.uniform(0, 50)) for _ in range(n)]
            self.assertEqual(rsi(ring, 10 ** 6), brute(ring))
if __name__ == "__main__": unittest.main()
