#!/usr/bin/env python3
"""Deep structural analysis of DST files (pure stdlib + our own reader).

Usage:  python3 tools/dst_analyze.py FILE_OR_DIR [...] [--json out.json] [--csv out.csv]

Per file it reports what a digitizer / machine operator cares about:
  * format: header counts vs real counts, end record, extents
  * commands: stitches, jumps, colour changes, trims (runs of >= 2 jumps), longest jump
  * stitch length distribution (mm): mean/median/p95/max, % < 0.5 mm, % > 7 mm, % > 12.1 mm (DST split limit)
  * lock/tie stitches at the start/end of every stitch run
  * density: needle penetrations per mm2 over covered 1 mm cells (p50/p90/max) and estimated fill row spacing
  * thread path: stitched mm vs travel mm, estimated run time at 700 spm incl. trims/colour changes
  * penetration clusters: >N penetrations within 0.2 mm (thread-break / fabric-cut risk)
Everything is derived from the bytes of the file, so the same function scores our own output and third-party samples.
"""
import json, math, sys
from pathlib import Path

from .dst import read_dst


def _pct(v, p):
    if not v:
        return 0.0
    v = sorted(v); k = (len(v) - 1) * p / 100.0; lo = int(math.floor(k)); hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def analyze(data: bytes, name: str = "") -> dict:
    f = read_dst(data)
    hdr = f.header
    # --- walk records -> events
    pts, kinds = [(0.0, 0.0)], []          # positions in mm after each record
    x = y = 0
    stitches, jumps, ccs = 0, 0, 0
    runs = []                              # list of lists of (x_mm, y_mm) for consecutive stitch records
    cur, jump_runs, jr = [], [], 0
    blocks, blk = [], {"stitches": 0, "start": 0}
    for (dx, dy, cmd), (px, py) in zip(f.records, f.positions):
        X, Y = px / 10.0, py / 10.0
        if cmd == "stitch":
            if jr:
                jump_runs.append(jr); jr = 0
            if not cur:
                cur = [(pts[-1][0], pts[-1][1])] if False else []
            cur.append((X, Y)); stitches += 1; blk["stitches"] += 1
        else:
            if cur:
                runs.append(cur); cur = []
            if cmd == "jump":
                jumps += 1; jr += 1
            elif cmd == "color_change":
                ccs += 1
                if jr:
                    jump_runs.append(jr); jr = 0
                blocks.append(blk); blk = {"stitches": 0}
        pts.append((X, Y)); kinds.append(cmd)
    if cur:
        runs.append(cur)
    if jr:
        jump_runs.append(jr)
    blocks.append(blk)
    trims = sum(1 for j in jump_runs if j >= 2)   # a run of >=2 zero-length-ish jumps is how DST encodes a trim
    # --- stitch lengths (between consecutive stitch records inside a run)
    lens, angs = [], []
    for r in runs:
        for a, b in zip(r, r[1:]):
            d = math.dist(a, b)
            lens.append(d)
            angs.append(math.atan2(b[1] - a[1], b[0] - a[0]))
    short = sum(1 for l in lens if l < 0.5)
    # "clustered" short stitches: two or more in a row. A lone short stitch is a tatami row turn (= row spacing) or a lock - normal.
    short_cluster = sum(1 for l1, l2 in zip(lens, lens[1:]) if l1 < 0.5 and l2 < 0.5); long7 = sum(1 for l in lens if l > 7.0); over = sum(1 for l in lens if l > 12.1)
    # --- lock stitches: run begins/ends with >=2 tiny (<=1 mm) stitches
    locks = 0
    for r in runs:
        if len(r) >= 4:
            for seg in (r[:3], r[-3:]):
                if all(math.dist(a, b) <= 1.0 for a, b in zip(seg, seg[1:])):
                    locks += 1
    # --- travel: jumps lengths
    jl, px_, py_ = [], 0.0, 0.0
    last = (0.0, 0.0)
    for k, (p, c) in enumerate(zip(pts[1:], kinds)):
        if c == "jump":
            jl.append(math.dist(last, p))
        last = p
    # --- density on a 1 mm grid
    cells = {}
    for r in runs:
        for (X, Y) in r:
            cells[(int(X // 1), int(Y // 1))] = cells.get((int(X // 1), int(Y // 1)), 0) + 1
    dens = list(cells.values())
    # --- fill row spacing: for long, parallel-ish stitch pairs i,i+2 distance perpendicular to stitch
    spac = []
    for r in runs:
        for i in range(len(r) - 3):
            a, b, c, d = r[i], r[i + 1], r[i + 2], r[i + 3]
            l1 = math.dist(a, b); l2 = math.dist(c, d)
            if l1 > 2.0 and l2 > 2.0:
                a1 = math.atan2(b[1] - a[1], b[0] - a[0]); a2 = math.atan2(d[1] - c[1], d[0] - c[0])
                dd = abs((a1 - a2 + math.pi) % (2 * math.pi) - math.pi)
                if dd < 0.12:                                   # parallel (same direction): rows i and i+2
                    nx, ny = -math.sin(a1), math.cos(a1)
                    s = abs((c[0] - a[0]) * nx + (c[1] - a[1]) * ny)
                    if 0.05 < s < 2.0:
                        spac.append(s)
    # --- penetration clusters (hash grid 0.2 mm)
    g = {}
    for r in runs:
        for (X, Y) in r:
            k = (int(X // 0.2), int(Y // 0.2)); g[k] = g.get(k, 0) + 1
    cluster = max(g.values()) if g else 0
    n_cluster = sum(1 for v in g.values() if v >= 6)
    # --- thread path & time
    stitched_mm = sum(lens)
    travel_mm = sum(jl)
    minutes = stitches / 700.0 + (trims * 6 + ccs * 25 + jumps * 0.1) / 60.0
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    hist_edges = [0.5, 1, 2, 3, 4, 5, 6, 7, 9, 12.1]
    hist = {}
    for e0, e1 in zip([0] + hist_edges, hist_edges + [1e9]):
        hist[f"{e0:g}-{e1:g}" if e1 < 1e8 else f">{e0:g}"] = sum(1 for l in lens if e0 <= l < e1)
    n = max(1, len(lens))
    return {
        "file": name, "bytes": len(data), "records": len(f.records), "ends_properly": f.ends_properly,
        "hdr_ST": hdr.get("ST"), "hdr_CO": hdr.get("CO"), "label": hdr.get("LA", ""),
        "stitches": stitches, "jumps": jumps, "colour_changes": ccs, "trims": trims, "colour_blocks": len(blocks),
        "size_mm": [round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1)],
        "len_mean": round(sum(lens) / n, 2), "len_median": round(_pct(lens, 50), 2), "len_p95": round(_pct(lens, 95), 2), "len_max": round(max(lens or [0]), 2),
        "pct_short_lt0.5": round(100 * short / n, 2), "pct_short_clustered": round(100 * short_cluster / n, 2), "pct_gt7": round(100 * long7 / n, 2), "n_gt12.1": over,
        "hist": hist, "lock_runs": locks, "runs": len(runs),
        "dens_p50": round(_pct(dens, 50), 1), "dens_p90": round(_pct(dens, 90), 1), "dens_max": max(dens or [0]),
        "row_spacing_median": round(_pct(spac, 50), 2) if spac else None, "row_spacing_n": len(spac),
        "max_jump_mm": round(max(jl or [0]), 1), "mean_jump_mm": round(sum(jl) / max(1, len(jl)), 1),
        "stitched_mm": round(stitched_mm), "travel_mm": round(travel_mm), "cluster_max_in_0.2mm": cluster, "cluster_cells_ge6": n_cluster,
        "est_minutes": round(minutes, 1), "stitches_per_cm2": round(stitches / max(0.01, (max(xs) - min(xs)) * (max(ys) - min(ys)) / 100.0), 1),
    }


def collect(paths):
    out = []
    for p in paths:
        p = Path(p)
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        for f in files:
            if f.suffix.lower() == ".dst" and f.is_file():
                out.append(f)
    return out


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    opts = {a.split("=")[0]: (a.split("=", 1)[1] if "=" in a else "") for a in argv if a.startswith("--")}
    rows = []
    for f in collect(args):
        try:
            rows.append(analyze(f.read_bytes(), f.name))
        except Exception as e:  # noqa: BLE001
            rows.append({"file": f.name, "error": str(e)})
    cols = ["file", "stitches", "colour_blocks", "trims", "size_mm", "len_median", "len_p95", "pct_short_lt0.5", "pct_gt7", "n_gt12.1", "row_spacing_median",
            "dens_p90", "dens_max", "cluster_max_in_0.2mm", "lock_runs", "runs", "max_jump_mm", "est_minutes"]
    print("  ".join(f"{c[:12]:>12}" if c != "file" else f"{c:28}" for c in cols))
    for r in rows:
        if "error" in r:
            print(r["file"], "ERROR", r["error"]); continue
        print("  ".join((f"{str(r[c])[:12]:>12}" if c != "file" else f"{r[c][:28]:28}") for c in cols))
    if "--json" in opts and opts["--json"]:
        Path(opts["--json"]).write_text(json.dumps(rows, indent=1))
    return rows


if __name__ == "__main__":
    main(sys.argv[1:])
