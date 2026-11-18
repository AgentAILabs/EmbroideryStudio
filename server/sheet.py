"""Production sheet (HTML) and export package (ZIP). Single source of truth for both the UI button and the package."""
import html, io, json, re, zipfile
from datetime import datetime

from stitchcraft_engine.design import generate, run_checks, machine
from stitchcraft_engine.dst import write_dst, read_dst
from stitchcraft_engine.exp import write_exp
from stitchcraft_engine.preview import preview_svg

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
<div style="clear:both"></div><p class="m">{E(DISCLAIMER)}</p></body></html>"""


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
    }
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
