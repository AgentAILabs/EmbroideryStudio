"""Production report: everything a shop needs to judge a DST before stitching, with the three validation levels kept apart.

  1. software validation           - the file equals the stitch plan (decode-compare) and the design passed the checks
  2. independent reader validation - a second DST reader (pyembroidery) parsed the file, or an explicit "NOT RUN"
  3. physical machine validation   - ALWAYS "NOT DONE" unless a human attaches stitch-out evidence; this software cannot produce it
Estimates (time) are labelled as estimates. Nothing here promises stitch quality or zero thread breaks.
"""
from __future__ import annotations
import html
from datetime import datetime, timezone
from typing import Optional

from . import machines, profiles
from .design import generate, machine as engine_machine
from .quality import quality_report
from .travel import travel_report
from .export_pipeline import export_dst, ExportResult
from .model import Cmd

TIME_NOTE = "Estimated machine time. Not verified on any machine; real time depends on the machine's speed settings."
GUARANTEE = "This report does not predict stitch-out quality and does not guarantee the absence of thread breaks, puckering or registration errors."


def complexity(design: dict, stitches: int, colour_changes: int, trims: int) -> dict:
    """Embroidery complexity rating from five measured factors, each scored 0-4 by fixed thresholds; total 0-3 Simple, 4-7 Moderate, 8-11 Complex, 12+ Very complex.
    A guide for quoting / planning, not a machine-verified measure."""
    def band(v, edges): return sum(1 for e in edges if v > e)
    objs = design.get("objects", [])
    small = 0
    for o in objs:
        if o.get("type") == "fill" and o.get("rings"):
            r = o["rings"][0]; a = abs(sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))) / 2
            small += 1 if a < 3.0 else 0
        elif o.get("type") in ("satin", "column") and (o.get("params") or {}).get("width", 9) < 1.5: small += 1
    f = {"stitches": band(stitches, (2000, 5000, 10000, 25000)), "colour_changes": band(colour_changes, (1, 3, 6, 10)), "trims": band(trims, (5, 20, 50, 100)),
         "objects": band(len(objs), (5, 20, 60, 150)), "small_features": band(small, (0, 5, 20, 60))}
    pts = sum(f.values()); level = "Simple" if pts <= 3 else "Moderate" if pts <= 7 else "Complex" if pts <= 11 else "Very complex"
    return {"level": level, "points": pts, "max_points": 20, "factors": f, "inputs": {"stitches": stitches, "colour_changes": colour_changes, "trims": trims, "objects": len(objs), "small_features": small},
            "rule": "five factors scored 0-4 (stitches > 2k/5k/10k/25k; colour changes > 1/3/6/10; trims > 5/20/50/100; objects > 5/20/60/150; small features > 0/5/20/60); 0-3 Simple, 4-7 Moderate, 8-11 Complex, 12+ Very complex"}


def build_report(design: dict, result: Optional[ExportResult] = None) -> dict:
    """Raises export_pipeline.ExportError when no DST can be released (a report for a refused file would be misleading)."""
    res = result or export_dst(design)
    pattern, notes, st = generate(design)
    prof = machines.resolve(design)
    mach_issues = machines.check_design(design, pattern)
    q = quality_report(design, pattern, notes)
    tr = travel_report(design, pattern)
    hoop = design.get("hoop", {})
    names = {str(o.get("id")): (o.get("name") or o.get("id")) for o in design.get("objects", [])}
    seq = []
    for i, c in enumerate(st.get("color_sequence", [])):
        seq.append({"order": i + 1, "hex": c.get("hex"), "stitches": c.get("stitches")})
    by_thread = {}
    for s in pattern.stitches:
        if s.cmd == Cmd.STITCH and s.object_id:
            by_thread.setdefault(s.thread, [])
            nm = names.get(s.object_id.split(".")[0], s.object_id)
            if nm not in by_thread[s.thread]:
                by_thread[s.thread].append(nm)
    for e in seq:
        e["objects"] = by_thread.get(e["order"] - 1, [])[:12]
    fab = design.get("fabric") or (design.get("profile") or {}).get("fabric")
    fab_info = next((f for f in profiles.fabric_catalog() if f["id"] == fab), None)
    warnings = [{"source": "geometry/quality", "severity": i["severity"], "object": i.get("object"), "message": i["message"]} for i in q["issues"]]
    warnings += [{"source": "machine profile", "severity": i["severity"], "message": i["message"]} for i in mach_issues]
    warnings += [{"source": "design", "severity": "info", "message": n} for n in notes]
    if fab_info and fab_info["warning"]:
        warnings.append({"source": "fabric", "severity": "warning", "message": fab_info["warning"]})
    rep = res.report
    return {
        "report_version": "1.0",
        "design": {"name": design.get("name", "design"), "size_mm": rep["size_mm"], "objects": len(design.get("objects", []))},
        "machine_profile": {k: prof.get(k) for k in ("id", "manufacturer", "model", "format", "max_hoop", "needles", "max_stitch", "min_stitch", "trim_distance", "trim_jumps", "lock_len", "validated", "validation_statement")},
        "hoop_mm": {"w": hoop.get("w"), "h": hoop.get("h"), "margin": hoop.get("margin")},
        "fabric": {"id": fab, "experimental": True, "validated": False, "stabiliser": design.get("stabiliser"), "thread": design.get("thread") or "40wt"},
        "counts": {"stitches": rep["counts"]["stitch"], "jumps": rep["counts"]["jump"], "trims": tr["totals"]["trims"], "trim_jump_records": rep["counts"]["trim_jumps"],
                   "colour_changes": rep["counts"]["color_change"], "dst_records": rep["records"]},
        "thread_sequence": seq,
        "estimated_time": {"minutes": st.get("est_minutes"), "note": TIME_NOTE},
        "complexity": complexity(design, rep["counts"]["stitch"], rep["counts"]["color_change"], tr["totals"]["trims"]),
        "thread_use": __import__("stitchcraft_engine.threads", fromlist=["consumption"]).consumption(pattern),
        "quality": {"score": q["score"], "categories": [{"name": c["name"], "score": c["score"]} for c in q["categories"]], "disclaimer": q["disclaimer"]},
        "travel": {"verdicts": tr["verdicts"], **tr["totals"]},
        "warnings": warnings,
        "file": {"sha256": res.sha256, "bytes": rep["bytes"], "format": "dst"},
        "engine_version": rep["engine_version"], "exported_utc": rep["exported_utc"],
        "stages": rep["stages"],
        "validation": {
            "1_software": {"result": "PASSED", "what": "stitch plan -> DST -> independent decode -> compared record by record (kind, count, position, size, orientation, header)"},
            "2_independent_reader": {"result": rep["validation"]["independent_reader"], "what": "a separate DST parser (pyembroidery) read the file and its stitch count was compared"},
            "3_physical_machine": {"result": "NOT DONE", "what": rep["validation"]["physical_machine"], "how_to_change": "Stitch the test pack on your machine and record the result; this software cannot do it."},
        },
        "limits": GUARANTEE,
    }


def render_html(r: dict) -> str:
    e = lambda x: html.escape(str(x if x is not None else "-"))
    v = r["validation"]
    rows = lambda items: "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td></tr>" for a, b in items)
    c, m, d = r["counts"], r["machine_profile"], r["design"]
    seq = "".join(f"<tr><td>{s['order']}</td><td><i style='display:inline-block;width:14px;height:14px;background:{e(s['hex'])};border:1px solid #0004'></i> {e(s['hex'])}</td><td>{s['stitches']}</td><td>{e(', '.join(s['objects']))}</td></tr>" for s in r["thread_sequence"])
    warn = "".join(f"<li class='{e(w['severity'])}'>[{e(w['source'])}] {e(w['message'])}</li>" for w in r["warnings"]) or "<li>none</li>"
    qs = "".join(f"<tr><td>{e(x['name'])}</td><td>{x['score']}/100</td></tr>" for x in r["quality"]["categories"])
    box = lambda k, t: f"<div class='box {'ok' if str(v[k]['result']).startswith('PASSED') else 'no'}'><b>{t}</b><br>{e(v[k]['result'])}<br><small>{e(v[k]['what'])}</small></div>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Production report - {e(d['name'])}</title>
<style>body{{font:14px/1.4 system-ui,sans-serif;max-width:900px;margin:20px auto;padding:0 14px;color:#111}}table{{border-collapse:collapse;width:100%;margin:6px 0}}td,th{{border:1px solid #cbd5e1;padding:4px 8px;text-align:left}}
.box{{border:2px solid;border-radius:6px;padding:8px;margin:6px 0}}.ok{{border-color:#15803d}}.no{{border-color:#b45309;background:#fffbeb}}li.warning{{color:#b45309}}li.error{{color:#b91c1c}}h2{{margin-top:22px}}small{{color:#555}}</style></head><body>
<h1>Production report - {e(d['name'])}</h1><p><small>Generated {e(r['exported_utc'])} by EmbroideryStudio engine {e(r['engine_version'])}</small></p>
<h2>Validation (three separate levels)</h2>{box('1_software', '1. Software validation')}{box('2_independent_reader', '2. Independent reader validation')}{box('3_physical_machine', '3. Physical machine validation')}
<h2>Design</h2><table>{rows([('Size', f"{d['size_mm'][0]} x {d['size_mm'][1]} mm"), ('Hoop', f"{r['hoop_mm']['w']} x {r['hoop_mm']['h']} mm (margin {r['hoop_mm']['margin']})"),
 ('Fabric preset', f"{r['fabric']['id']} (experimental, not validated)"), ('Stabiliser', r['fabric']['stabiliser']), ('Thread', r['fabric']['thread']),
 ('Stitches', c['stitches']), ('Jumps', c['jumps']), ('Trims', c['trims']), ('Colour changes', c['colour_changes']), ('DST records', c['dst_records']),
 ('Estimated time', f"{r['estimated_time']['minutes']} min - {r['estimated_time']['note']}")])}</table>
<h2>Machine profile</h2><table>{rows([('Profile', f"{m['manufacturer']} {m['model']}"), ('Validated', m['validated']), ('Statement', m['validation_statement']), ('Max hoop', m['max_hoop'] or 'not set'), ('Needles', m['needles'] or 'not set'),
 ('Max / min stitch', f"{m['max_stitch']} / {m['min_stitch']} mm"), ('Trim', f"{m['trim_jumps']} zero-move jumps when a jump exceeds {m['trim_distance']} mm (unverified convention)")])}</table>
<h2>Thread sequence</h2><table><tr><th>#</th><th>Colour</th><th>Stitches</th><th>Objects</th></tr>{seq}</table>
<h2>Software quality score: {r['quality']['score']}/100</h2><table>{qs}</table><p><small>{e(r['quality']['disclaimer'])}</small></p>
<h2>Warnings</h2><ul>{warn}</ul><h2>File</h2><table>{rows([('Format', 'DST'), ('Size', f"{r['file']['bytes']} bytes"), ('SHA-256', r['file']['sha256'])])}</table>
<p><small>{e(r['limits'])}</small></p></body></html>"""
