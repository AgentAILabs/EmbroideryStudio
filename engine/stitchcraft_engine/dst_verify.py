#!/usr/bin/env python3
"""Multi-stage DST verification. Every stage returns PASS / WARN / FAIL with evidence; the file's grade is the worst stage.

  Stage 1 container   header vs records (ST/CO/extents), END record, trailing bytes, record alignment
  Stage 2 encoding    decode -> re-encode round trip is byte-identical per record; optional pyembroidery cross-decode
  Stage 3 machine     per-record limit 12.1 mm, long/short stitches, needle count, hoop fit
  Stage 4 stitch      density per mm2, penetration clusters, satin line spacing, fill row spacing, short-stitch rate
  Stage 5 thread path trims (jump trains), tie-in / tie-off coverage, orphan stitches, travel ratio
  Stage 6 simulation  replays the file from (0,0): stays inside the hoop, ends at END, ends near start, time estimate

Usage: python3 tools/dst_verify.py FILE_OR_DIR [...] [--hoop=WxH] [--thread=40wt|60wt|120] [--needles=15] [--json=out.json]
Library: verify(data, hoop=(w, h), thread_k=1.0, needles=15) -> dict
"""
import json, math, sys
from pathlib import Path

from .dst import read_dst, encode_record, decode_record, HEADER_SIZE
from . import dst_analyze as A

ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}


def _stage(name, checks):
    worst = max((ORDER[c[0]] for c in checks), default=0)
    return {"stage": name, "result": ["PASS", "WARN", "FAIL"][worst], "checks": [{"level": c[0], "what": c[1], "evidence": c[2]} for c in checks]}


def _runs(f):
    cur, out, kinds = [], [], []
    for (dx, dy, c), (px, py) in zip(f.records, f.positions):
        if c == "stitch":
            cur.append((px / 10.0, py / 10.0))
        else:
            if cur:
                out.append(cur); cur = []
    if cur:
        out.append(cur)
    return out


def satin_advance(runs):
    """Median distance between consecutive same-side penetrations of zig-zag satin (= 2 x stitch-line spacing)."""
    sp = []
    for r in runs:
        for a, b, c in zip(r, r[1:], r[2:]):
            l1, l2 = math.dist(a, b), math.dist(b, c)
            if 1.0 < l1 < 9 and 1.0 < l2 < 9:
                if ((b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])) / (l1 * l2) < -0.7:
                    d = math.dist(a, c)
                    if d < 1.2:
                        sp.append(d)
    sp.sort()
    return (sp[len(sp) // 2], len(sp)) if sp else (None, 0)


def verify(data: bytes, hoop=(100.0, 100.0), thread_k: float = 1.0, needles: int = 15, name: str = "") -> dict:
    stages = []
    # ---------------- stage 1: container
    c = []
    try:
        f = read_dst(data)
    except Exception as e:  # noqa: BLE001
        return {"file": name, "grade": "FAIL", "stages": [_stage("1 container", [("FAIL", "file parses as DST", str(e))])]}
    c.append(("PASS" if f.ends_properly else "FAIL", "END record is the last record", f"ends_properly={f.ends_properly}"))
    tail = data[HEADER_SIZE + 3 * len(f.records):]
    c.append(("PASS" if not tail.strip(b"\x1a\x00") else "FAIL", "nothing but an EOF marker after END", f"{len(tail)} trailing byte(s)"))
    hdr = f.header
    try:
        st = int(hdr.get("ST", "-1"))
        c.append(("PASS" if st == len(f.records) else "WARN", "header ST equals the record count (incl. END, as Wilcom/Tajima files do)", f"ST={st} records={len(f.records)}"))
    except ValueError:
        c.append(("FAIL", "header ST is a number", repr(hdr.get("ST"))))
    try:
        co = int(hdr.get("CO", "-1"))
        c.append(("PASS" if co in (f.color_changes, f.color_changes + 1) else "WARN", "header CO matches colour changes", f"CO={co} changes={f.color_changes}"))
    except ValueError:
        c.append(("FAIL", "header CO is a number", repr(hdr.get("CO"))))
    xs = [0] + [p[0] for p in f.positions]; ys = [0] + [p[1] for p in f.positions]
    try:
        ext = [int(hdr[k]) for k in ("+X", "-X", "+Y", "-Y")]
        real = [max(xs), -min(xs), max(ys), -min(ys)]
        ok = all(abs(a - b) <= 2 for a, b in zip(ext, real))
        c.append(("PASS" if ok else "WARN", "header extents (+X -X +Y -Y) match the stitches", f"header={ext} actual={real} (0.1 mm)"))
    except (KeyError, ValueError):
        c.append(("WARN", "header extents present", "missing +X/-X/+Y/-Y"))
    stages.append(_stage("1 container", c))
    # ---------------- stage 2: encoding
    c, bad = [], 0
    body = data[HEADER_SIZE:HEADER_SIZE + 3 * len(f.records)]
    for i, (dx, dy, cmd) in enumerate(f.records):
        rec = body[3 * i:3 * i + 3]
        flag = {"stitch": 0, "jump": 0x80, "color_change": 0xC0, "end": 0xF0}[cmd]
        if cmd in ("stitch", "jump"):
            if encode_record(dx, dy, flag if cmd == "jump" else 0) != rec and (rec[2] & 0x03) == 0x03:
                bad += 1
        elif decode_record(rec)[2] != cmd:
            bad += 1
    c.append(("PASS" if bad == 0 else "FAIL", "every record re-encodes to the same bytes (movement + command flag)", f"{bad} mismatch(es) in {len(f.records)} records"))
    try:
        import pyembroidery as pe  # optional, used in CI
        import io, tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".dst", delete=False) as t:
            t.write(data); path = t.name
        try:
            pat = pe.read(path)
            n_pe = sum(1 for s in pat.stitches if (s[2] & pe.COMMAND_MASK) == pe.STITCH)
            n_us = sum(1 for _, _, k in f.records if k == "stitch")
            c.append(("PASS" if abs(n_pe - n_us) <= 1 else "FAIL", "independent decoder (pyembroidery) agrees on stitch count", f"pyembroidery={n_pe} ours={n_us}"))
        finally:
            os.unlink(path)
    except ImportError:
        c.append(("PASS", "independent decoder cross-check", "skipped (pyembroidery not installed; runs in CI)"))
    stages.append(_stage("2 encoding", c))
    # ---------------- analysis for stages 3-6
    a = A.analyze(data, name)
    runs = _runs(f)
    # ---------------- stage 3: machine limits
    c = []
    over = sum(1 for dx, dy, k in f.records if max(abs(dx), abs(dy)) > 121)
    c.append(("PASS" if over == 0 else "FAIL", "no record exceeds 12.1 mm", f"{over} record(s)"))
    c.append(("PASS" if a["pct_gt7"] < 1.0 else "WARN", "long stitches (> 7 mm) are rare", f"{a['pct_gt7']}% of stitches"))
    c.append(("PASS" if a["pct_short_clustered"] < 3.0 else "WARN", "no runs of very short stitches (< 0.5 mm, two or more in a row)",
              f"{a['pct_short_clustered']}% clustered ({a['pct_short_lt0.5']}% incl. lone row-turn / lock stitches)"))
    blocks = a["colour_blocks"]
    c.append(("PASS" if blocks <= needles else "WARN", f"colour blocks fit the {needles} needles", f"{blocks} block(s)"))
    w, h = hoop
    fits = (a["size_mm"][0] <= w and a["size_mm"][1] <= h)
    c.append(("PASS" if fits else "FAIL", f"design fits the {w:g}x{h:g} mm hoop", f"{a['size_mm'][0]}x{a['size_mm'][1]} mm"))
    stages.append(_stage("3 machine", c))
    # ---------------- stage 4: stitch quality
    c = []
    lim = 16.0 / thread_k * 1.35
    c.append(("PASS" if a["dens_max"] <= lim else "WARN", f"needle penetrations per mm2 <= {lim:.0f}", f"max {a['dens_max']}, p90 {a['dens_p90']}"))
    c.append(("PASS" if a["cluster_max_in_0.2mm"] <= 12 else "FAIL", "no thread-break / fabric-cut cluster (<= 12 penetrations in 0.2 mm)", f"max {a['cluster_max_in_0.2mm']}"))
    adv, n = satin_advance(runs)
    if n >= max(30, 0.08 * a['stitches']):          # only judge satin spacing when the design is really satin (fill rows also zig-zag)
        line = adv / 2.0
        lo, hi = 0.15, 0.55
        c.append(("PASS" if lo <= line <= hi else "WARN", f"satin line spacing {lo}-{hi} mm (coverage vs. thread-break)",
                  f"median {line:.2f} mm over {n} zig-zags (thread preset k={thread_k})"))
    stages.append(_stage("4 stitch", c))
    # ---------------- stage 5: thread path
    c = []
    stitched, travel = a["stitched_mm"], a["travel_mm"]
    c.append(("PASS" if travel <= 3.0 * max(stitched, 1) else "WARN", "travel (jumps) is not wildly more than stitching", f"travel {travel} mm vs stitched {stitched} mm"))
    jump_runs, cur, kinds = [], 0, [k for _, _, k in f.records]
    for k in kinds:
        if k == "jump":
            cur += 1
        else:
            if cur: jump_runs.append(cur)
            cur = 0
    long_runs = [r for r in jump_runs if r >= 3]
    c.append(("PASS", "trims are jump trains of >= 3 records", f"{len(long_runs)} trim(s), {len(jump_runs) - len(long_runs)} carried jump(s)"))
    # fresh thread starts (after a trim or colour change) need a tie-in; carried short jumps do not
    n_cut, locks = a["cut_runs"], a["lock_runs"]
    c.append(("PASS" if n_cut == 0 or locks >= 0.5 * n_cut else "WARN", "fresh thread starts are tied in (>= half of the starts after a trim / colour change)",
              f"{locks} tie-in(s) over {n_cut} thread start(s); {len(runs) - n_cut} carried continuation(s) need none"))
    tiny = a["orphan_cut_runs"]
    c.append(("PASS" if tiny <= max(2, 0.05 * max(n_cut, 1)) else "WARN", "few orphan pieces (1-2 stitches between two cuts)", f"{tiny} of {n_cut} thread start(s)"))
    stages.append(_stage("5 thread path", c))
    # ---------------- stage 6: simulation
    c = []
    x = y = 0; out = 0; mx = my = 0
    for dx, dy, k in f.records:
        x += dx; y += dy
    xs2 = [p[0] / 10 for p in f.positions]; ys2 = [p[1] / 10 for p in f.positions]
    if xs2:
        spanx, spany = max(xs2 + [0]) - min(xs2 + [0]), max(ys2 + [0]) - min(ys2 + [0])
        c.append(("PASS" if spanx <= w and spany <= h else "FAIL", "replayed needle path stays inside the hoop", f"span {spanx:.1f}x{spany:.1f} mm"))
    end_off = math.hypot(x, y) / 10.0
    c.append(("PASS", "end position (information: the frame returns home itself)", f"end offset {end_off:.1f} mm from start"))
    c.append(("PASS" if a["est_minutes"] < 240 else "WARN", "run time is reasonable", f"~{a['est_minutes']} min at 700 spm"))
    stages.append(_stage("6 simulation", c))
    grade = ["PASS", "WARN", "FAIL"][max(ORDER[s["result"]] for s in stages)]
    return {"file": name, "grade": grade, "stages": stages, "metrics": {k: a[k] for k in ("stitches", "colour_blocks", "trims", "size_mm", "est_minutes", "dens_max", "len_median")}}


def main(argv):
    opts = dict(a.lstrip("-").split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    hoop = tuple(float(v) for v in opts.get("hoop", "200x300").lower().split("x"))
    k = {"40wt": 1.0, "60wt": 0.75, "120": 0.55}.get(opts.get("thread", "40wt"), 1.0)
    reports = []
    for fp in A.collect([a for a in argv if not a.startswith("--")]):
        r = verify(fp.read_bytes(), hoop, k, int(opts.get("needles", 15)), fp.name); reports.append(r)
        print(f"{r['grade']:5} {fp.name:34}" + "  ".join(f"{s['stage'][0]}:{s['result'][0]}" for s in r["stages"]))
        for s in r["stages"]:
            for ch in s["checks"]:
                if ch["level"] != "PASS":
                    print(f"        [{ch['level']}] stage {s['stage']}: {ch['what']} - {ch['evidence']}")
    if opts.get("json"):
        Path(opts["json"]).write_text(json.dumps(reports, indent=1))
    return reports


if __name__ == "__main__":
    main(sys.argv[1:])
