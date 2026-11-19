"""Validated DST export pipeline.

A DST is released only after it has been written, re-read and compared with the stitch plan it was written from:

  1 generate stitches            (design.generate)
  2 validate design + geometry   (run_checks, validate_geometry when available)
  3 production checklist gate    (checklist.evaluate: any FAIL blocks)
  4 write DST
  5 re-read the bytes            (project reader)
  6 decode-compare               every record vs the stitch plan: kind, count, absolute position (0.1 mm), dimensions, orientation
  7 independent reader           pyembroidery stitch count when that library is importable (always in CI), else reported as "not run"
  8 report                       checksum, counts, what was and was not verified

Any failure raises ExportError with a stage and structured issues. A file that fails is never returned.
This is SOFTWARE validation: it proves the file says what the stitch plan says. It does not prove a machine will stitch it well.
"""
import hashlib, math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import __version__, CONTRACT_VERSION
from .design import generate, machine, run_checks
from .dst import write_dst, MAX_DELTA, UNITS_PER_MM
from .model import Cmd, Pattern

# Hand-typed Tajima layout, deliberately NOT imported from dst.py: if dst.py's writer and reader ever share a wrong table again (the original
# X/Y swap), a compare built on them would still pass. (byte, bit mask) -> (axis, signed weight)
_LAYOUT = {
    (0, 0x01): ("x", 1), (0, 0x02): ("x", -1), (0, 0x04): ("x", 9), (0, 0x08): ("x", -9),
    (0, 0x80): ("y", 1), (0, 0x40): ("y", -1), (0, 0x20): ("y", 9), (0, 0x10): ("y", -9),
    (1, 0x01): ("x", 3), (1, 0x02): ("x", -3), (1, 0x04): ("x", 27), (1, 0x08): ("x", -27),
    (1, 0x80): ("y", 3), (1, 0x40): ("y", -3), (1, 0x20): ("y", 27), (1, 0x10): ("y", -27),
    (2, 0x04): ("x", 81), (2, 0x08): ("x", -81), (2, 0x20): ("y", 81), (2, 0x10): ("y", -81),
}
HEADER_SIZE = 512


def independent_decode(data: bytes):
    """-> (records [(dx, dy, kind)], absolute positions [(x, y)] in 0.1 mm after each record, header dict). Own layout table, own loop."""
    if len(data) < HEADER_SIZE + 3:
        raise ExportError("the file is shorter than a DST header", "decode-compare", "EXPORT_TRUNCATED")
    hdr = {}
    for line in data[:HEADER_SIZE].split(b"\x1a")[0].split(b"\r"):
        if b":" in line:
            k, v = line.decode("ascii", "replace").split(":", 1); hdr[k.strip()] = v.strip()
    body = data[HEADER_SIZE:]
    recs, pos, x, y = [], [], 0, 0
    for i in range(0, len(body) - 2, 3):
        rec = body[i:i + 3]; dx = dy = 0
        for (bi, mask), (axis, w) in _LAYOUT.items():
            if rec[bi] & mask:
                if axis == "x": dx += w
                else: dy += w
        flag = rec[2] & 0xC0
        if not (dx or dy) and rec[2] & 0xF3 == 0xF3:
            kind = "end"
        elif not (dx or dy) and flag == 0xC0:
            kind = "color_change"
        elif flag == 0x80:
            kind = "jump"
        else:
            kind = "stitch"
        x += dx; y += dy
        recs.append((dx, dy, kind)); pos.append((x, y))
        if kind == "end":
            break
    return recs, pos, hdr


TOLERANCE_UNITS = 0.6          # decoded absolute position vs the plan, in 0.1 mm units (quantisation is exact, this only absorbs float rounding)


class ExportError(ValueError):
    """Export refused. `stage` says where; `issues` are structured (code / severity / message) for the UI."""
    def __init__(self, message: str, stage: str, code: str = "EXPORT_REFUSED", issues: Optional[List[dict]] = None):
        super().__init__(message)
        self.stage, self.code = stage, code
        self.issues = issues or [{"code": code, "severity": "error", "message": message}]

    def to_dict(self) -> dict:
        return {"error": str(self), "stage": self.stage, "code": self.code, "issues": self.issues}


@dataclass
class ExportResult:
    data: bytes
    sha256: str
    record_count: int
    report: dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def compare_with_plan(pattern: Pattern, data: bytes, trim_jumps: int, want_sim: bool = False) -> dict:
    """Decode `data` and walk the stitch plan against it. Returns a result dict; raises ExportError on the first mismatch.
    Written independently of dst.write_dst's loop: it recomputes the centring offset and the expected absolute position itself."""
    recs, pos, hdr = independent_decode(data)
    bb = pattern.bbox()
    if bb is None:
        raise ExportError("the stitch plan has no stitches", "decode-compare", "EXPORT_EMPTY")
    ox, oy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
    i = 0
    counts = {"stitch": 0, "jump": 0, "color_change": 0, "trim_jumps": 0, "end": 0}
    pts = []
    sim = []          # (x_mm, y_mm, Stitch) with the position DECODED FROM THE FILE, mapped back to design coordinates

    def fail(msg, code="EXPORT_MISMATCH"):
        raise ExportError(f"The generated file does not match the stitch plan: {msg}. The export was refused.", "decode-compare", code)

    def need(n):
        if i + n > len(recs):
            fail(f"the file ends early (record {i} of {len(recs)})", "EXPORT_TRUNCATED")

    for k, s in enumerate(pattern.stitches):
        if s.cmd == Cmd.COLOR_CHANGE:
            need(1)
            if recs[i][2] != "color_change":
                fail(f"record {i} should be a colour change but is a {recs[i][2]}")
            counts["color_change"] += 1; i += 1
            if want_sim: sim.append((None, None, s))
        elif s.cmd == Cmd.TRIM:
            need(trim_jumps)
            for j in range(trim_jumps):
                dx, dy, c = recs[i + j]
                if c != "jump" or dx or dy:
                    fail(f"record {i + j} should be a zero-move jump (trim) but is a {c} of ({dx},{dy})")
            counts["trim_jumps"] += trim_jumps; i += trim_jumps
            if want_sim: sim.append((None, None, s))
        elif s.cmd == Cmd.END:
            need(1)
            if recs[i][2] != "end":
                fail(f"record {i} should be END but is a {recs[i][2]}", "EXPORT_BAD_END")
            counts["end"] += 1; i += 1
            if want_sim: sim.append((None, None, s))
        else:
            want_kind = "jump" if s.cmd == Cmd.JUMP else "stitch"
            px, py = (pos[i - 1] if i else (0, 0))
            tx, ty = (s.x - ox) * UNITS_PER_MM, -(s.y - oy) * UNITS_PER_MM        # engine y is DOWN, file y is UP
            n = max(1, math.ceil(max(abs(round(tx) - px), abs(round(ty) - py)) / MAX_DELTA - 1e-9))
            need(n)
            for j in range(n):
                if recs[i + j][2] != want_kind:
                    fail(f"record {i + j} should be a {want_kind} but is a {recs[i + j][2]}")
                if abs(recs[i + j][0]) > MAX_DELTA or abs(recs[i + j][1]) > MAX_DELTA:
                    fail(f"record {i + j} moves more than the DST limit of {MAX_DELTA} units", "EXPORT_MOVE_LIMIT")
            gx, gy = pos[i + n - 1]
            if abs(gx - tx) > TOLERANCE_UNITS or abs(gy - ty) > TOLERANCE_UNITS:
                fail(f"stitch {k} should end at ({tx / 10:.2f}, {ty / 10:.2f}) mm but the file puts it at ({gx / 10:.2f}, {gy / 10:.2f}) mm (record {i + n - 1})")
            counts[want_kind] += 1; i += n
            pts.append((gx, gy))
            if want_sim: sim.append((gx / UNITS_PER_MM + ox, -gy / UNITS_PER_MM + oy, s))
    if i != len(recs):
        fail(f"the file has {len(recs) - i} extra record(s) after END", "EXPORT_EXTRA_RECORDS")
    consumed = HEADER_SIZE + 3 * len(recs)
    if data[consumed:] not in (b"", b"\x1a"):                       # real files may end with one stray 0x1A byte; anything else is unexplained data
        fail(f"the file has {len(data) - consumed} unexplained byte(s) after END", "EXPORT_EXTRA_RECORDS")
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = (max(xs) - min(xs)) / 10.0, (max(ys) - min(ys)) / 10.0
    pw, ph = bb[2] - bb[0], bb[3] - bb[1]
    if abs(w - pw) > 0.11 or abs(h - ph) > 0.11:
        fail(f"file size {w:.1f} x {h:.1f} mm differs from the plan {pw:.1f} x {ph:.1f} mm (axes swapped or scaled?)", "EXPORT_DIMENSIONS")
    # header metadata must describe the file (CO = colour changes, ST = records incl. END, extents = decoded extents)
    try:
        co, st_hdr = int(hdr.get("CO", "-1")), int(hdr.get("ST", "-1"))
        ext = [int(hdr[k]) for k in ("+X", "-X", "+Y", "-Y")]
    except (ValueError, KeyError):
        fail("the DST header is missing or unreadable (CO / ST / extents)", "EXPORT_BAD_HEADER")
    if co != counts["color_change"]:
        fail(f"header says {co} colour change(s) but the file has {counts['color_change']}", "EXPORT_BAD_HEADER")
    if st_hdr != len(recs):
        fail(f"header says {st_hdr} records but the file has {len(recs)}", "EXPORT_BAD_HEADER")
    want = [max([0] + xs), -min([0] + xs), max([0] + ys), -min([0] + ys)]
    if any(abs(a - b) > 1 for a, b in zip(ext, want)):
        fail(f"header extents {ext} do not match the decoded extents {want}", "EXPORT_BAD_HEADER")
    out = {"counts": counts, "size_mm": [round(w, 2), round(h, 2)], "records": len(recs), "colour_changes_in_header": co}
    if want_sim:
        out["sim"] = sim
    return out


def independent_reader(data: bytes, expected_stitches: int) -> dict:
    """Third-party reader (pyembroidery) - only if importable. Never fakes a pass."""
    try:
        import pyembroidery as pe, tempfile, os
    except ImportError:
        return {"ran": False, "result": "not run in this process (pyembroidery not installed); CI runs it"}
    with tempfile.NamedTemporaryFile(suffix=".dst", delete=False) as t:
        t.write(data); path = t.name
    try:
        pat = pe.read(path)
        if pat is None:
            return {"ran": True, "result": "FAIL", "detail": "pyembroidery could not read the file"}
        n = sum(1 for x, y, c in pat.stitches if (c & pe.COMMAND_MASK) == pe.STITCH)
        ok = n == expected_stitches
        return {"ran": True, "result": "PASS" if ok else "FAIL", "stitches_read": n, "stitches_expected": expected_stitches}
    finally:
        os.unlink(path)


def export_dst(design: dict, *, use_checklist: bool = True) -> ExportResult:
    """Run the full workflow and return validated bytes, or raise ExportError."""
    stages: List[dict] = []
    try:
        pattern, notes, st = generate(design)
    except ValueError as e:
        raise ExportError(str(e), "generate", "EXPORT_NO_STITCHES") from e
    stages.append({"stage": "generate", "result": "PASS", "stitches": st["stitches"]})
    rep = run_checks(design, pattern)
    if not rep.ok:
        issues = [{"code": i.code, "severity": i.severity, "message": i.message} for i in rep.issues]
        raise ExportError("Export blocked", "validate", "EXPORT_BLOCKED", issues)
    stages.append({"stage": "validate", "result": "PASS", "warnings": len(rep.issues)})
    try:                                               # geometry rules arrive in a later phase; use them as soon as they exist
        from .quality import validate_geometry
        geo = validate_geometry(design)
        errs = [g for g in geo if g["severity"] == "error"]
        if errs:
            raise ExportError("Export blocked", "geometry", "EXPORT_BLOCKED", errs)
        stages.append({"stage": "geometry", "result": "PASS", "warnings": len(geo)})
    except ImportError:
        pass
    if use_checklist:
        from .checklist import evaluate
        cl = evaluate(design)
        fails = [{"code": f"CHECK{i['n']}", "severity": "error", "message": f"{i['title']}: {i['evidence']}"} for i in cl["items"] if i["level"] == "FAIL"]
        if fails:
            raise ExportError("Export blocked by the production checklist", "checklist", "EXPORT_BLOCKED", fails)
        stages.append({"stage": "checklist", "result": "PASS", "passed": f"{cl['passed']}/{cl['total']}"})
    from .machines import check_design as machine_check
    mi = machine_check(design, pattern)
    merrs = [i for i in mi if i["severity"] == "error"]
    if merrs:
        raise ExportError("Export blocked by the machine profile", "machine-profile", "EXPORT_BLOCKED", merrs)
    stages.append({"stage": "machine-profile", "result": "PASS", "warnings": len(mi)})
    m = machine(design)
    res = write_dst(pattern, trim_jumps=m["trim_jumps"])
    stages.append({"stage": "write", "result": "PASS", "records": res.record_count})
    cmp = compare_with_plan(pattern, res.data, m["trim_jumps"])
    stages.append({"stage": "decode-compare", "result": "PASS", **cmp["counts"], "size_mm": cmp["size_mm"]})
    ind = independent_reader(res.data, cmp["counts"]["stitch"])
    if ind["result"] == "FAIL":
        raise ExportError(f"The independent reader disagrees with the file ({ind.get('detail') or ind}). The export was refused.", "independent-reader", "EXPORT_READER_MISMATCH")
    stages.append({"stage": "independent-reader", "result": ind["result"] if ind["ran"] else "NOT RUN", "detail": ind.get("result")})
    from .quality import quality_report
    q = quality_report(design, pattern)
    from .travel import travel_report
    tr = travel_report(design, pattern)
    report = {
        "engine_version": __version__, "contract_version": CONTRACT_VERSION, "format": "dst",
        "exported_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sha256": res.sha256, "bytes": len(res.data), "records": res.record_count, "stages": stages,
        "counts": cmp["counts"], "size_mm": cmp["size_mm"],
        "quality": {"score": q["score"], "categories": {c["id"]: c["score"] for c in q["categories"]}, "warnings": len(q["issues"]), "disclaimer": q["disclaimer"]},
        "travel": {"verdicts": tr["verdicts"], **tr["totals"]},
        "validation": {
            "software": "PASSED: plan -> file -> decode -> compare (kind, count, position, size, orientation)",
            "independent_reader": ("PASSED (pyembroidery)" if ind["ran"] and ind["result"] == "PASS" else "NOT RUN in this process"),
            "physical_machine": "NOT DONE - no stitch-out evidence exists for this file",
        },
    }
    return ExportResult(res.data, res.sha256, res.record_count, report, list(res.warnings))


def decoded_simulation(design: dict) -> dict:
    """Stitches for the simulator taken from the DST bytes themselves (quantised to 0.1 mm), proven equal to the plan by compare_with_plan.
    Raises ExportError if the file cannot be produced (the caller falls back to the plan and says so)."""
    pattern, notes, st = generate(design)
    m = machine(design)
    res = write_dst(pattern, trim_jumps=m["trim_jumps"])
    cmp = compare_with_plan(pattern, res.data, m["trim_jumps"], want_sim=True)
    code = {Cmd.STITCH: 0, Cmd.JUMP: 1, Cmd.TRIM: 2, Cmd.COLOR_CHANGE: 3, Cmd.END: 4}
    ids, idx, out, last = [], {}, [], (0.0, 0.0)
    for x, y, s in cmp["sim"]:
        if x is None:
            x, y = last
        else:
            last = (x, y)
        if s.object_id is not None and s.object_id not in idx:
            idx[s.object_id] = len(ids); ids.append(s.object_id)
        out.append([round(x, 3), round(y, 3), code[s.cmd], s.thread, idx.get(s.object_id, -1)])
    return {"stitches": out, "objects": ids, "threads": [t.hex for t in pattern.threads], "stats": st, "notes": notes,
            "sha256": res.sha256, "pattern": pattern}


def export_format(design: dict, fmt: str) -> ExportResult:
    """Export in any exposed machine format. DST runs the full pipeline. Every other format first passes the SAME gating as DST (generate, validate, geometry, checklist,
    machine profile, decode-compare of the DST), then the pattern is encoded and - when pyembroidery is installed - READ BACK and compared stitch by stitch; a mismatch refuses
    the export. The report says plainly which validation ran and that no machine validation exists."""
    from . import formats, encoders
    if fmt == "dst":
        return export_dst(design)
    info = formats.FORMATS.get(fmt)
    if info is None or not formats.is_exposed(fmt):
        raise ExportError(f"{fmt!r} export is not available" + (f" ({info.note})" if info else ""), "format", "EXPORT_FORMAT_UNAVAILABLE")
    gate = export_dst(design)                                                   # same refusals as a DST export
    pattern, notes, st = generate(design); m = machine(design)
    try:
        data = formats.get_writer(fmt)(pattern, trim_jumps=m["trim_jumps"])
    except (ValueError, encoders.EncodeError) as e:
        raise ExportError(f"{info.label}: {e}", "encode", "EXPORT_ENCODE_FAILED") from e
    data = bytes(data)
    ver = encoders.verify_with_pyembroidery(data, fmt, pattern) if fmt != "exp" else {"ran": False, "result": "EXP is verified by tests/test_crosscheck.py"}
    if ver.get("result") == "FAIL":
        raise ExportError(f"The independent reader disagrees with the {info.label} file ({ver}). The export was refused.", "independent-reader", "EXPORT_READER_MISMATCH")
    import hashlib
    sha = hashlib.sha256(data).hexdigest()
    report = {"format": fmt, "label": info.label, "bytes": len(data), "sha256": sha, "dst_gate_sha256": gate.sha256, "counts": gate.report["counts"], "size_mm": gate.report["size_mm"],
              "validation": {"software": "PASSED: the DST gating pipeline for this design", "independent_reader": ver, "physical_machine": "NOT DONE - no stitch-out on any machine",
                             "tier": info.status}, "note": info.note}
    return ExportResult(data, sha, gate.record_count, report, list(gate.warnings))
