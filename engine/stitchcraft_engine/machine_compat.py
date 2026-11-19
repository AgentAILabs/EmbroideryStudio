"""Machine-compatibility helpers for DST files: a safe header label, a safe machine file name, and a byte-level pre-flight.

What is KNOWN vs ASSUMED (nothing here has been verified on a Ricoma):
  * KNOWN (Tajima DST layout): 512-byte header of CR-separated `XX:value` fields ending with 0x1A and space padding; 3-byte records; one END record.
  * CONSERVATIVE ASSUMPTION (dealer / forum advice, not a Ricoma specification): short upper-case file names with only letters and digits, a `.DST` extension,
    the file in the USB root, FAT32 media. Ricoma's own documentation could not be read from this environment.
Every check says which of the two it is.
"""
from __future__ import annotations
import hashlib
import re
from typing import List, Optional

LABEL_LEN = 16
NAME_LEN = 8


def label_for(name) -> str:
    """Header label: ASCII letters, digits, space, '_' and '-' only, upper case, <= 16 chars. A CR, ':' or 0x1A in the label would corrupt the header's field structure, and
    non-ASCII text (e.g. Telugu / Devanagari names) cannot be written in the ASCII header at all."""
    s = re.sub(r"[^A-Za-z0-9 _-]+", "", str(name or "")).strip().upper()[:LABEL_LEN].rstrip()
    return s or "DESIGN"


def filename_for(name, taken=()) -> str:
    """Conservative machine file name: upper-case A-Z / 0-9, at most 8 characters, `.DST`. Non-ASCII names fall back to DESIGN plus a short hash so two different
    designs do not collide. `taken` = names already used (a numeric suffix is added)."""
    raw = str(name or "")
    if not raw.strip():
        return "DESIGN.DST"
    base = re.sub(r"[^A-Za-z0-9]+", "", raw).upper()
    if not base or base != re.sub(r"[^A-Za-z0-9]+", "", raw.encode("ascii", "ignore").decode()).upper():
        base = "D" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:5].upper()
    base = base[:NAME_LEN]
    out, i = base, 1
    while out + ".DST" in taken:
        suf = str(i); out = base[:NAME_LEN - len(suf)] + suf; i += 1
    return out + ".DST"


def check(name, result, detail, basis):
    return {"name": name, "result": result, "detail": detail, "basis": basis}


def preflight(data: bytes, filename: Optional[str] = None, hoop: Optional[dict] = None) -> dict:
    """Byte-level structural pre-flight of a DST. basis = 'Tajima layout' (structural fact) or 'unverified advice' (a precaution, not a Ricoma rule)."""
    from .export_pipeline import independent_decode, ExportError
    T, A = "Tajima layout", "unverified advice"
    cs: List[dict] = []
    try:
        recs, pos, hdr = independent_decode(data)
    except ExportError as e:
        return {"verdict": "FAILED", "checks": [check("readable", "FAILED", str(e), T)], "filename": filename}
    head = data[:512]
    cs.append(check("header is 512 bytes, terminated by 0x1A, padded with spaces", "PASSED" if len(data) >= 512 and b"\x1a" in head and set(head[head.index(b"\x1a") + 1:]) <= {0x20} else "FAILED", "", T))
    lines = head.split(b"\x1a")[0].split(b"\r")
    keys = [l[:3].decode("ascii", "replace") for l in lines if l]
    want = ["LA:", "ST:", "CO:", "+X:", "-X:", "+Y:", "-Y:", "AX:", "AY:", "MX:", "MY:", "PD:"]
    cs.append(check("header fields exactly LA ST CO +X -X +Y -Y AX AY MX MY PD, in order", "PASSED" if keys == want else "FAILED", f"found {keys}", T))
    label = lines[0][3:].decode("ascii", "replace") if lines else ""
    cs.append(check("label is plain ASCII (letters, digits, space, _ -)", "PASSED" if re.fullmatch(r"[A-Z0-9 _-]{0,16}", label) else "FAILED", repr(label), T))
    cs.append(check("(len - 512) is a multiple of 3", "PASSED" if (len(data) - 512) % 3 == 0 else "FAILED", f"{len(data)} bytes", T))
    kinds = [k for _, _, k in recs]
    cs.append(check("exactly one END record, last", "PASSED" if kinds.count("end") == 1 and kinds[-1] == "end" else "FAILED", "", T))
    cs.append(check("ST equals the record count", "PASSED" if str(len(recs)) == hdr.get("ST", "").strip() else "WARNING", f"header {hdr.get('ST')} vs {len(recs)} records (a reference file from Ricoma / Tajima would show whether END is counted)", T))
    cs.append(check("CO equals the number of colour-change records", "PASSED" if str(kinds.count("color_change")) == hdr.get("CO", "").strip() else "FAILED", f"header {hdr.get('CO')} vs {kinds.count('color_change')}", T))
    cs.append(check("no record moves more than 12.1 mm", "PASSED" if max([max(abs(dx), abs(dy)) for dx, dy, _ in recs] + [0]) <= 121 else "FAILED", "", T))
    xs = [p[0] for p in pos] or [0]; ys = [p[1] for p in pos] or [0]
    try:
        ok = (int(hdr["+X"]), int(hdr["-X"]), int(hdr["+Y"]), int(hdr["-Y"])) == (max(xs), -min(xs), max(ys), -min(ys))
    except (KeyError, ValueError):
        ok = False
    cs.append(check("header extents equal the decoded extents", "PASSED" if ok else "FAILED", "", T))
    if hoop and hoop.get("w") and hoop.get("h"):
        w, h = (max(xs) - min(xs)) / 10, (max(ys) - min(ys)) / 10
        cs.append(check("design fits the hoop", "PASSED" if w <= hoop["w"] and h <= hoop["h"] else "FAILED", f"{w:.1f} x {h:.1f} mm in {hoop['w']} x {hoop['h']} mm", T))
    if filename:
        stem, _, ext = filename.rpartition(".")
        cs.append(check("file name: upper-case letters / digits, at most 8, extension .DST", "PASSED" if re.fullmatch(r"[A-Z0-9]{1,8}", stem) and ext == "DST" else "WARNING", filename, A))
    cs.append(check("file must be copied to the USB root on FAT32 media", "INFO", "cannot be checked by software", A))
    bad = [c for c in cs if c["result"] == "FAILED"]; warn = [c for c in cs if c["result"] == "WARNING"]
    return {"verdict": "FAILED" if bad else "PASSED_WITH_WARNINGS" if warn else "PASSED", "checks": cs, "filename": filename,
            "note": "Structural checks only. A passing pre-flight does not prove a Ricoma accepts the file; Ricoma's own file rules could not be read here. Physical validation: PENDING."}
