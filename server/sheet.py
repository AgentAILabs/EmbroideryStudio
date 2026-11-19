"""Production sheet (HTML) and export package (ZIP). Single source of truth for both the UI button and the package."""
import html, io, json, re, zipfile
from datetime import datetime

from stitchcraft_engine.design import generate, run_checks, machine
from stitchcraft_engine.dst import write_dst, read_dst
from stitchcraft_engine.exp import write_exp
from stitchcraft_engine.preview import preview_svg
from stitchcraft_engine.checklist import colour_report_csv, evaluate as checklist_evaluate

E = lambda v: html.escape(str(v), quote=True)
DISCLAIMER = "NOT machine-tested. Stitch a sample on matching fabric and stabiliser before production use."


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "design")).strip("_") or "design"


def sheet_html(design: dict, pattern=None, notes=None, st=None, issues=None) -> str:
    if pattern is None:
        try:
            pattern, notes, st = generate(design)
            issues = run_checks(design, pattern).issues
        except ValueError:          # nothing stitchable (embellishments / guides only)
            from stitchcraft_engine.design import empty_stats
            pattern, notes, st, issues = None, ["Nothing to stitch - this design only has embellishment placeholders or guides."], empty_stats(design), []
    h, m = design.get("hoop", {}), machine(design)
    hoop = f'{h.get("w", 100)} × {h.get("h", 100)} mm (margin {h.get("margin", 3)} mm)'
    rows = "".join(f'<tr><td>{i + 1}</td><td><span class="sw" style="background:{E(s["hex"])}"></span> {E(s["hex"])}</td><td>{s["stitches"]}</td></tr>'
                   for i, s in enumerate(st["color_sequence"]))
    appl = [o for o in design.get("objects", []) if o.get("type") == "applique" and not o.get("hidden")]
    emb = [o for o in design.get("objects", []) if o.get("type") == "embellishment" and not o.get("hidden") and not o.get("guide")]
    emb_html = ""
    if emb:
        agg = {}
        for o in emb:
            agg.setdefault(o.get("kind", "bead"), []).append(o)
        er = "".join(f"<tr><td>{E(k)}</td><td>{sum(len(o.get('points', [])) for o in v)}</td><td>{E(', '.join(sorted({o.get('color', '') for o in v})))}</td><td>{E(', '.join(sorted({str(o.get('size_mm', '')) for o in v})))}</td></tr>"
                     for k, v in agg.items())
        pos = "".join(f"<tr><td>{E(o.get('name', o['id']))}</td><td>{E(o.get('kind', 'bead'))}</td><td>" +
                      E("; ".join(f"({p[0]:.1f}, {p[1]:.1f})" for p in o.get("points", []))) + "</td></tr>" for o in emb)
        emb_html = ("<h3>Embellishments (placed by hand - <b>not</b> in the DST)</h3><table><tr><th>Type</th><th>Count</th><th>Colour</th><th>Size mm</th></tr>" + er +
                    "</table><p class='m'>Positions in mm from the design centre (x right, y down):</p><table><tr><th>Group</th><th>Type</th><th>Positions</th></tr>" + pos + "</table>")
    msgs = [f'<li class="{"e" if i.severity == "error" else "w"}">{E(i.message)}</li>' for i in (issues or [])][:40]
    msgs += [f'<li class="w">{E(n)}</li>' for n in (notes or [])]
    svg = preview_svg(pattern, float(h.get("w", 0)), float(h.get("h", 0))) if pattern else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Production sheet - {E(design.get('name', 'design'))}</title>
<style>body{{font:14px system-ui,sans-serif;margin:24px;max-width:860px;color:#111}}table{{border-collapse:collapse;margin:6px 0}}td,th{{border:1px solid #999;padding:4px 10px;text-align:left}}
h1{{margin:0}}.m{{color:#555}}.sw{{display:inline-block;width:16px;height:16px;border:1px solid #000;vertical-align:middle}}.e{{color:#b91c1c}}.w{{color:#b45309}}
.prev{{float:right;width:380px;border:1px solid #ccc;margin:0 0 12px 16px}}.prev svg{{width:100%;height:auto;display:block}}@media print{{body{{margin:8mm}}}}</style></head><body>
<h1>{E(design.get('name', 'design'))}</h1><p class="m">EmbroideryStudio production sheet · {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
<div class="prev">{svg}</div>
<p><b>Design size:</b> {st['width_mm']} × {st['height_mm']} mm<br><b>Hoop:</b> {E(hoop)}<br>
<b>Fabric preset:</b> {E(design.get('fabric', '-'))} (unverified starting values)<br><b>Stabiliser:</b> {E(design.get('stabiliser') or 'cut-away')}<br>
<b>Stitches:</b> {st['stitches']}<br><b>Colour changes:</b> {st['color_changes']} · <b>Trims:</b> {st['trims']} · <b>Jumps:</b> {st['jumps']}<br>
<b>Estimated run time:</b> ~{st['est_minutes']} min at {st['assumed_spm']:.0f} spm (assumed)<br>
<b>Machine profile:</b> max stitch {m['max_stitch']} mm · trim above {m['trim_distance']} mm · {m['trim_jumps']} trim jumps (DST has no trim code - confirm on your machine)<br>
<b>Thread locks:</b> {('tie-in/tie-off ' + str(m['lock_len']) + ' mm, ' + str(st.get('lock_stitches', 0)) + ' lock stitches added') if m['lock_len'] else 'off'} · trim at colour change: {'yes' if m['trim_at_color_change'] else 'no'} · trim at end: {'yes' if m['trim_at_end'] else 'no'}</p>
<h3>Colour order</h3><table><tr><th>#</th><th>Thread</th><th>Stitches</th></tr>{rows}</table>
{('<p><b>Appliqué:</b> ' + str(len(appl)) + ' patch(es). At each placement → tack-down colour change, lay the fabric; trim after tack-down.</p>') if appl else ''}
{emb_html}
<h3>Checks</h3><ul>{''.join(msgs) or '<li>No problems found</li>'}</ul>
<h3>Machine test record (fill in at the machine)</h3>
<table><tr><th>Date</th><td style="width:160px"></td><th>Machine / head</th><td style="width:200px">Ricoma</td></tr>
<tr><th>Needle</th><td></td><th>Thread brand / weight</th><td>{E(design.get('thread') or '40wt')}</td></tr>
<tr><th>Fabric</th><td>{E((design.get('profile') or dict()).get('fabric') or design.get('fabric', ''))}</td><th>Stabiliser</th><td>{E(design.get('stabiliser') or 'cut-away')}</td></tr></table>
<table><tr><th>Observation</th><th>OK</th><th>Problem - where / what</th></tr>
{''.join(f'<tr><td>{x}</td><td style="width:40px"></td><td style="width:380px"></td></tr>' for x in ('Size and position match', 'Thread breaks', 'Puckering', 'Skipped stitches', 'Registration (outlines meet fills)', 'Coverage (fabric shows through)', 'Trims clean, no loose tails'))}
<tr><th>Approved for production</th><td></td><td>signature:</td></tr></table>
<div style="clear:both"></div><p class="m">{E(DISCLAIMER)}</p></body></html>"""


def applique_cut_svg(design: dict):
    """1:1 cutting template for appliqué patches: the cut line is the placement outline grown by a third of the cover-satin width, so
    the satin hides the raw edge; the placement line is drawn dashed. Includes a 50 mm scale bar to check the print scale. None when
    the design has no appliqué."""
    from stitchcraft_engine.geometry import outset_ring
    apps = [o for o in design.get("objects", []) if o.get("type") == "applique" and not o.get("hidden") and o.get("rings")]
    if not apps:
        return None
    shapes = []
    for o in apps:
        ring = [tuple(p) for p in o["rings"][0]]
        w = float((o.get("params") or {}).get("width", 2.5))
        cut = outset_ring(ring, w / 3) or ring
        shapes.append((o.get("name") or o["id"], ring, cut, w / 3))
    xs = [p[0] for _, _, c, _ in shapes for p in c]; ys = [p[1] for _, _, c, _ in shapes for p in c]
    x0, y0 = min(xs) - 10, min(ys) - 10; W, H = max(xs) - x0 + 10, max(ys) - y0 + 25
    path = lambda r: "M " + " L ".join(f"{p[0] - x0:.2f},{p[1] - y0:.2f}" for p in r) + " Z"
    body = "".join(f'<path d="{path(c)}" fill="none" stroke="#000" stroke-width="0.3"/><path d="{path(r)}" fill="none" stroke="#888" stroke-width="0.2" stroke-dasharray="1.5 1"/>'
                   f'<text x="{sum(p[0] for p in r) / len(r) - x0:.1f}" y="{sum(p[1] for p in r) / len(r) - y0:.1f}" font-size="3" text-anchor="middle">{E(n)} (+{m:.1f} mm)</text>'
                   for n, r, c, m in shapes)
    bar = f'<path d="M 10,{H - 8:.1f} h 50" stroke="#000" stroke-width="0.4"/><text x="10" y="{H - 3:.1f}" font-size="3">50 mm - print at 100 %, check this bar</text>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.1f}mm" height="{H:.1f}mm" viewBox="0 0 {W:.1f} {H:.1f}">'
            f'<title>Appliqué cutting template - {E(design.get("name", "design"))}</title>{body}{bar}</svg>')


def package(design: dict):
    """Returns (zip_bytes, None) or (None, {'error', 'issues'}). Blocked on validation errors, like the DST export."""
    pattern, notes, st = generate(design)
    rep = run_checks(design, pattern)
    if not rep.ok:
        return None, {"error": "Export blocked", "issues": [{"code": i.code, "severity": i.severity, "message": i.message} for i in rep.issues]}
    m = machine(design)
    res = write_dst(pattern, trim_jumps=m["trim_jumps"])
    back = read_dst(res.data)
    if not back.ends_properly or back.color_changes != st["color_changes"]:
        return None, {"error": "DST round-trip check failed"}
    n = _safe(design.get("name"))
    h = design.get("hoop", {})
    files = {
        f"{n}.dst": res.data,
        f"{n}.esproj": json.dumps({"app": "EmbroideryStudio", "version": 1, "doc": design}, indent=1).encode(),
        f"{n}.preview.svg": preview_svg(pattern, float(h.get("w", 0)), float(h.get("h", 0))).encode(),
        f"{n}.production-sheet.html": sheet_html(design, pattern, notes, st, rep.issues).encode(),
        f"{n}.stitchcraft.json": json.dumps(pattern.to_dict()).encode(),
        f"{n}.exp": write_exp(pattern, trim_jumps=m["trim_jumps"]),
        f"{n}.colours.csv": colour_report_csv(design, st).encode(),
    }
    cut = applique_cut_svg(design)
    if cut:
        files[f"{n}.applique-cut.svg"] = cut.encode()
    checks = "\n".join([f"{i.severity.upper()} {i.code}: {i.message}" for i in rep.issues] + [f"NOTE {x}" for x in notes]) or "No problems found"
    manifest = "\n".join([f"EmbroideryStudio export package · {datetime.now().isoformat(timespec='seconds')}",
                          f"design: {design.get('name', 'design')}", f"stitches: {st['stitches']}  colour changes: {st['color_changes']}",
                          f"trim jumps: {m['trim_jumps']}", f"DST records: {res.record_count}", f"DST sha256: {res.sha256}", "",
                          f"{n}.exp: Melco EXP of the same stitches; trims are written as {m['trim_jumps']} zero-move jumps (no agreed trim opcode in EXP). Read back by pyembroidery in CI; not machine-tested.",
                          DISCLAIMER, "", "CHECKS", checks, ""])
    files["MANIFEST.txt"] = manifest.encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue(), None


def placement_set(design: dict, spec: list, source_side: str = "left", thread=None):
    """One design -> a named DST per garment placement (left / right / neck ...), each auto-corrected and verified.
    Returns (zip_bytes, report) or (None, {'error': ...}). A placement that fails verification is left out and reported - never shipped."""
    from stitchcraft_engine import placements as P
    from stitchcraft_engine import dst_verify
    from stitchcraft_engine.design import THREADS
    if thread:
        if thread not in THREADS:
            raise ValueError(f"unknown thread preset {thread!r}")
        design = dict(design, thread=thread)
    if not design.get("objects"):
        raise ValueError("the design has no objects")
    plans = P.plan(spec, source_side)
    base = P.slug(design.get("name"))
    k = THREADS[design.get("thread") or "40wt"]["k"]
    files, rows = {}, []
    for p in plans:
        d, log = P.make_variant(design, p)
        name = d["name"]
        row = {"placement": p["id"], "label": p["label"], "file": f"{name}.dst", "mirror": p["mirror"], "rotate": p["rotate"], "log": log}
        try:
            pattern, notes, st = generate(d)
        except ValueError as e:
            row.update(status="skipped", reason=str(e)); rows.append(row); continue
        rep = run_checks(d, pattern)
        if not rep.ok:
            row.update(status="blocked", reason="; ".join(i.message for i in rep.errors)[:300]); rows.append(row); continue
        m = machine(d)
        res = write_dst(pattern, trim_jumps=m["trim_jumps"])
        h = d.get("hoop", {})
        ver = dst_verify.verify(res.data, (float(h.get("w", 100)), float(h.get("h", 100))), k, 15, f"{name}.dst")
        if ver["grade"] == "FAIL":
            row.update(status="blocked", reason="verification FAIL: " + "; ".join(c["what"] for s in ver["stages"] for c in s["checks"] if c["level"] == "FAIL")[:300])
            rows.append(row); continue
        files[f"{name}.dst"] = res.data
        files[f"{name}.esproj"] = json.dumps({"app": "EmbroideryStudio", "version": 1, "doc": d}, indent=1).encode()
        files[f"{name}.preview.svg"] = preview_svg(pattern, float(h.get("w", 0)), float(h.get("h", 0))).encode()
        files[f"{name}.production-sheet.html"] = sheet_html(d, pattern, notes, st, rep.issues).encode()
        files[f"{name}.verification.json"] = json.dumps(ver, indent=1).encode()
        files[f"{name}.colours.csv"] = colour_report_csv(d, st).encode()
        row.update(status="ok", grade=ver["grade"], stitches=st["stitches"], colours=st["color_changes"] + 1, trims=st["trims"],
                   size_mm=[st["width_mm"], st["height_mm"]], minutes=st["est_minutes"], sha256=res.sha256, notes=list(notes)[:20])
        rows.append(row)
    if not files:
        return None, {"error": "No placement passed verification", "placements": rows}
    lines = [f"EmbroideryStudio placement set - {base} - {datetime.now().isoformat(timespec='seconds')}",
             f"source artwork drawn for the {source_side} side; thread preset {design.get('thread') or '40wt'}", ""]
    for r in rows:
        if r["status"] == "ok":
            lines.append(f"{r['file']:44} {r['grade']:5} {r['stitches']:>6} st  {r['colours']} col  {r['size_mm'][0]}x{r['size_mm'][1]} mm  ~{r['minutes']} min   sha256 {r['sha256'][:12]}")
        else:
            lines.append(f"{r['file']:44} {r['status'].upper()}: {r.get('reason', '')}")
        for l in r["log"]:
            lines.append(f"      - {l}")
    lines += ["", DISCLAIMER, "'left' / 'right' follow the side the artwork was drawn for; mirrored files are true mirror images (not rotated copies)."]
    files["MANIFEST.txt"] = "\n".join(lines).encode()
    files["placement-report.json"] = json.dumps({"design": base, "source_side": source_side, "placements": rows}, indent=1).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k2, v in files.items():
            z.writestr(k2, v)
    return buf.getvalue(), {"base": base, "placements": rows}
