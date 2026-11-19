"""Background jobs for the expensive operations (image conversion, photo stitching, garment digitizing): the HTTP request returns at once with a job id, the work runs on a small
thread pool, the client polls /api/job/status. stdlib only (concurrent.futures). In-memory with a TTL: jobs are not persisted across a server restart.
A job that is cancelled keeps running to its end (threads cannot be killed) but its result is discarded."""
from __future__ import annotations
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Optional

MAX_WORKERS = 2
MAX_JOBS = 60
TTL_S = 900


class JobError(ValueError):
    pass


class Jobs:
    def __init__(self, kinds: Dict[str, Callable], workers: int = MAX_WORKERS, clock=time.time):
        self.kinds = kinds; self.pool = ThreadPoolExecutor(max_workers=workers); self.jobs: Dict[str, dict] = {}; self.lock = threading.Lock(); self.clock = clock

    def _gc(self):
        now = self.clock()
        for k in [k for k, j in self.jobs.items() if j["status"] in ("done", "failed", "cancelled") and now - j["finished"] > TTL_S]: del self.jobs[k]

    def start(self, kind: str, payload: dict) -> str:
        if kind not in self.kinds: raise JobError(f"unknown job kind {kind!r}; use one of {sorted(self.kinds)}")
        if not isinstance(payload, dict): raise JobError("payload must be an object")
        with self.lock:
            self._gc()
            if sum(1 for j in self.jobs.values() if j["status"] in ("queued", "running")) >= MAX_JOBS: raise JobError("too many jobs are queued; wait for some to finish")
            jid = uuid.uuid4().hex[:16]; self.jobs[jid] = {"id": jid, "kind": kind, "status": "queued", "created": self.clock(), "started": None, "finished": None, "result": None, "error": None}
        self.pool.submit(self._run, jid, kind, payload); return jid

    def _run(self, jid: str, kind: str, payload: dict):
        j = self.jobs[jid]
        if j["status"] == "cancelled": return
        j["status"] = "running"; j["started"] = self.clock()
        try:
            res = self.kinds[kind](payload)
            if j["status"] != "cancelled": j["result"] = res; j["status"] = "done"
        except ValueError as e:
            j["error"] = str(e); j["status"] = "failed"
        except Exception as e:                                                       # never leak internals; the log has the type
            j["error"] = f"internal error ({type(e).__name__})"; j["status"] = "failed"
        j["finished"] = self.clock()

    def status(self, jid: str) -> dict:
        j = self.jobs.get(jid)
        if j is None: raise JobError("unknown or expired job")
        now = self.clock(); out = {k: j[k] for k in ("id", "kind", "status", "error")}
        out["elapsed_s"] = round((j["finished"] or now) - (j["started"] or j["created"]), 1)
        if j["status"] == "done": out["result"] = j["result"]
        return out

    def cancel(self, jid: str) -> bool:
        j = self.jobs.get(jid)
        if j is None: raise JobError("unknown or expired job")
        if j["status"] in ("queued", "running"): j["status"] = "cancelled"; j["finished"] = self.clock(); return True
        return False
