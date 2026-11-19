"""Operational hardening for the stdlib server: structured logging, rate limiting, security headers, upload policy.

Scope (honest): this protects a single-process server used by one shop or behind a trusted proxy. It is NOT authentication, per-user ownership,
a job queue or a database - those are roadmap items (docs/architecture/enterprise-architecture.md).
Environment: ES_LOG=off|info|debug (default info), ES_RATE_PER_MIN (default 600, 0 = off), ES_RATE_BURST (default 120).
"""
from __future__ import annotations
import json, os, sys, threading, time, uuid

LOG_LEVEL = os.environ.get("ES_LOG", "info").lower()
HEAVY = {"/api/export/dst", "/api/export/package", "/api/placements", "/api/autodigitize", "/api/import/raster", "/api/enhance", "/api/report", "/api/quality", "/api/profile"}
HEAVY_COST = 8
SLOW_SECONDS = 5.0
MAX_UPLOAD_B64 = 40 * 1024 * 1024
MAX_DST_BYTES = 16 * 1024 * 1024

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
}


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def log_event(level: str, event: str, **fields) -> None:
    """One JSON object per line on stderr. Never logs request bodies (they contain customer artwork)."""
    if LOG_LEVEL == "off" or (level == "debug" and LOG_LEVEL != "debug"):
        return
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "level": level, "event": event}
    rec.update(fields)
    try:
        sys.stderr.write(json.dumps(rec, default=str) + "\n")
        sys.stderr.flush()
    except Exception:  # noqa: BLE001 - logging must never break a request
        pass


class RateLimiter:
    """Token bucket per client. cost>1 for expensive endpoints. rate_per_min=0 disables."""
    def __init__(self, rate_per_min: float, burst: float, clock=time.monotonic):
        self.rate, self.burst, self.clock = rate_per_min / 60.0, float(burst), clock
        self.buckets = {}
        self.lock = threading.Lock()

    def allow(self, client: str, cost: float = 1.0):
        """-> (allowed, retry_after_seconds)"""
        if self.rate <= 0:
            return True, 0
        now = self.clock()
        with self.lock:
            tokens, last = self.buckets.get(client, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens >= cost:
                self.buckets[client] = (tokens - cost, now)
                if len(self.buckets) > 5000:                       # bound memory: drop idle clients
                    for k in [k for k, (_, t) in self.buckets.items() if now - t > 600][:2500]:
                        self.buckets.pop(k, None)
                return True, 0
            self.buckets[client] = (tokens, now)
            return False, max(1, int((cost - tokens) / self.rate) + 1)


def limiter_from_env(env=os.environ) -> RateLimiter:
    return RateLimiter(float(env.get("ES_RATE_PER_MIN", 600)), float(env.get("ES_RATE_BURST", 120)))


def cost_of(path: str) -> float:
    return HEAVY_COST if path in HEAVY else 1.0


def check_base64_upload(b64: str, what: str = "file") -> None:
    if not isinstance(b64, str):
        raise ValueError(f"{what}: data must be a base64 string")
    if len(b64) > MAX_UPLOAD_B64:
        raise ValueError(f"{what} too large (limit {MAX_UPLOAD_B64 // (1024 * 1024)} MB)")


def check_dst_upload(raw: bytes) -> None:
    if len(raw) > MAX_DST_BYTES:
        raise ValueError(f"DST file too large (limit {MAX_DST_BYTES // (1024 * 1024)} MB)")
    if len(raw) < 515:
        raise ValueError("not a DST file (shorter than the 512-byte header plus one record)")
