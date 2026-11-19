"""Physical machine-validation evidence records.

A record is what a PERSON observed on a real machine for ONE exact DST file (identified by its SHA-256). This module never creates results: it stores
what is submitted, checks it is complete and untampered, and derives a status. The repository ships NO records.

Status for a DST (sha):
  PENDING            no record exists for this design
  STALE              records exist for this design name, but none for the current DST checksum (the design changed after the test)
  INCOMPLETE         a record for this checksum exists but a required field is missing
  FAILED             final inspection = fail
  PASSED_WITH_NOTES  every required field filled, inspection = pass_with_notes
  PASSED             every required field filled, inspection = pass, and the record's checksum equals the current DST
A record carries `record_sha256` (hash of its canonical JSON without that field); a record whose hash does not match is refused on import / ignored on load.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
INSPECTION = ("pass", "pass_with_notes", "fail")
JUMP_TRIM = ("ok", "problems")
REQUIRED_TEXT = ("operator", "design_name", "design_version", "machine_model", "fabric", "stabiliser", "needle", "thread", "hoop")
REQUIRED_NUM = ("stitch_count", "speed_spm", "thread_breaks", "skipped_stitches", "registration_mm")
REQUIRED_ENUM = {"puckering": (0, 1, 2, 3), "jump_trim_result": JUMP_TRIM, "final_inspection": INSPECTION}
OPTIONAL = ("notes", "photo_sha256", "design_id")
STATUSES = ("PENDING", "INCOMPLETE", "STALE", "FAILED", "PASSED_WITH_NOTES", "PASSED")

CHECKLIST = [
    {"id": "design", "text": "Note the design name and version; the DST checksum is recorded automatically. A changed design needs a new test."},
    {"id": "setup", "text": "Record machine model, fabric, stabiliser, needle, thread and hoop exactly as used."},
    {"id": "orientation", "text": "Confirm the stitched orientation (X right, Y down as viewed from above) matches the preview; mark a corner with the first colour."},
    {"id": "run", "text": "Stitch at a modest speed first; count thread breaks and skipped / missed stitches."},
    {"id": "trims", "text": "Check every jump and trim: no long threads left, no unwanted trims, no thread nests."},
    {"id": "pucker", "text": "Remove from the hoop and judge puckering / distortion on a 0 (none) - 3 (severe) scale."},
    {"id": "registration", "text": "Measure the worst gap or overlap between adjacent colours / outlines in mm."},
    {"id": "final", "text": "Final inspection: pass, pass with notes, or fail. Photograph the result; record the photo checksum if kept."},
]


def evidence_dir() -> Path:
    d = Path(os.environ.get("ES_EVIDENCE_DIR") or (ROOT / "evidence")); d.mkdir(parents=True, exist_ok=True); return d


def _canon(rec: dict) -> bytes:
    return json.dumps({k: v for k, v in rec.items() if k != "record_sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def seal(rec: dict) -> dict:
    rec = dict(rec); rec["record_sha256"] = hashlib.sha256(_canon(rec)).hexdigest(); return rec


def intact(rec: dict) -> bool:
    return isinstance(rec, dict) and rec.get("record_sha256") == hashlib.sha256(_canon(rec)).hexdigest()


def missing(rec: dict) -> List[str]:
    out = []
    for k in REQUIRED_TEXT:
        if not str(rec.get(k, "")).strip(): out.append(k)
    for k in REQUIRED_NUM:
        if not isinstance(rec.get(k), (int, float)) or isinstance(rec.get(k), bool): out.append(k)
    for k, vals in REQUIRED_ENUM.items():
        if rec.get(k) not in vals: out.append(k)
    return out


def clean(d: dict) -> dict:
    """Validate + normalise a SUBMITTED record (values are accepted as given; missing ones stay missing -> INCOMPLETE)."""
    if not isinstance(d, dict): raise ValueError("record must be an object")
    sha = str(d.get("dst_sha256", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha): raise ValueError("dst_sha256 must be the 64-hex SHA-256 of the exported DST")
    rec: Dict[str, object] = {"dst_sha256": sha}
    for k in REQUIRED_TEXT + ("notes", "design_id"):
        v = d.get(k)
        if v is None or v == "": continue
        if not isinstance(v, str) or len(v) > 2000: raise ValueError(f"{k} must be text up to 2000 characters")
        rec[k] = v.strip()
    for k in REQUIRED_NUM:
        v = d.get(k)
        if v is None or v == "": continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 <= v <= 1e9): raise ValueError(f"{k} must be a non-negative number")
        rec[k] = v
    for k, vals in REQUIRED_ENUM.items():
        v = d.get(k)
        if v is None or v == "": continue
        if v not in vals: raise ValueError(f"{k} must be one of {list(vals)}")
        rec[k] = v
    ph = d.get("photo_sha256") or []
    if not (isinstance(ph, list) and len(ph) <= 20 and all(isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) for h in ph)): raise ValueError("photo_sha256 must be a list of up to 20 SHA-256 hex strings")
    rec["photo_sha256"] = ph
    return rec


def record_status(rec: dict, current_sha: Optional[str]) -> str:
    if missing(rec): return "INCOMPLETE"
    if current_sha and rec.get("dst_sha256") != current_sha: return "STALE"
    ins = rec["final_inspection"]
    if ins == "fail": return "FAILED"
    if ins == "pass_with_notes": return "PASSED_WITH_NOTES"
    return "PASSED"


def create(d: dict, now: Optional[float] = None) -> dict:
    """Store a submitted record (never invents values). -> sealed record with id + created."""
    rec = clean(d); t = time.time() if now is None else now
    rec["created"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    rec["id"] = "ev_" + hashlib.sha256((rec["dst_sha256"] + rec["created"] + json.dumps(rec, sort_keys=True)).encode()).hexdigest()[:16]
    rec = seal(rec)
    (evidence_dir() / f"{rec['id']}.json").write_text(json.dumps(rec, indent=2, sort_keys=True))
    return rec


def import_record(rec: dict) -> dict:
    """Import a previously exported record unchanged; refused when its hash does not match (edited / corrupted)."""
    if not intact(rec): raise ValueError("the record was changed after it was saved (its record_sha256 does not match) - it is refused")
    if not re.fullmatch(r"ev_[0-9a-f]{16}", str(rec.get("id", ""))): raise ValueError("invalid record id")
    clean(rec)
    (evidence_dir() / f"{rec['id']}.json").write_text(json.dumps(rec, indent=2, sort_keys=True)); return rec


def load_all() -> List[dict]:
    out = []
    for p in sorted(evidence_dir().glob("ev_*.json")):
        try: r = json.loads(p.read_text())
        except (OSError, ValueError): continue
        if intact(r): out.append(r)
    out.sort(key=lambda r: r.get("created", ""))
    return out


def status_for(sha: Optional[str], design_name: Optional[str] = None) -> dict:
    """Status of the CURRENT dst checksum. Never PASSED unless a complete, intact, passing record for exactly this checksum exists."""
    recs = load_all()
    mine = [r for r in recs if sha and r["dst_sha256"] == sha]
    if mine:
        r = mine[-1]; st = record_status(r, sha)
        return {"status": st, "record": r, "missing": missing(r), "records": len(mine), "dst_sha256": sha}
    same = [r for r in recs if design_name and r.get("design_name") == design_name]
    if same:
        return {"status": "STALE", "record": None, "missing": [], "records": len(same), "dst_sha256": sha,
                "detail": "this design was tested before, but the DST has changed since (checksum differs) - the earlier result does not apply"}
    return {"status": "PENDING", "record": None, "missing": [], "records": 0, "dst_sha256": sha, "detail": "no physical machine test has been recorded for this DST"}
