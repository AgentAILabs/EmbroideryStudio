"""Builds the physical stitch-out test pack (requirements section F).
    python3 tools/make_testpack.py [out_dir] [--hoop WxH[xMARGIN]]      default: testpack/v2/  (testpack/ itself = v1, kept untouched)
For each design: .dst (validated + round-trip read back), .esproj (open in the Studio), preview .svg,
plus RESULTS.csv and RESULTS.html (printable sheet) to record what the machine actually did.
Designs are deliberately plain so a failure points at ONE variable."""
import csv, html, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine.design import generate, run_checks          # noqa: E402
from stitchcraft_engine.dst import write_dst, read_dst              # noqa: E402
from stitchcraft_engine.preview import preview_svg                  # noqa: E402
import app as srv                                                    # noqa: E402

HOOP = {"w": 100, "h": 100, "margin": 3}
RED, BLUE, GREEN, GOLD, BLACK = "#c8102e", "#1e3a8a", "#2e9e44", "#d4af37", "#000000"


def D(name, objs, fabric="cotton"):
    return {"name": name, "hoop": dict(HOOP), "fabric": fabric, "objects": objs}


def rect(x, y, w, h): return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def text(i, s, h, y, color=BLACK):
    return {"id": i, "type": "text", "text": s, "height": h, "x": -45, "y": y, "color": color}


def designs():
    out = {}
    # 1. flower (from the engine sample SVG, imported exactly as a user would)
    svg = (ROOT / "engine" / "samples" / "flower.svg").read_text(encoding="utf-8")
    imp = srv.api_svg({"svg": svg})
    objs = imp["objects"]
    xs = [p[0] for o in objs for p in (o.get("rings", [[]])[0] if o.get("rings") else o.get("points", []))]
    ys = [p[1] for o in objs for p in (o.get("rings", [[]])[0] if o.get("rings") else o.get("points", []))]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    for o in objs:
        for k in ("rings", "points"):
            if k in o:
                o[k] = [[[p[0] - cx, p[1] - cy] for p in r] for r in o[k]] if k == "rings" else [[p[0] - cx, p[1] - cy] for p in o[k]]
    for i, o in enumerate(objs): o["id"] = f"flower{i + 1}"
    out["01_flower"] = D("01_flower", objs)
    # 2-4. lettering at 5 / 8 / 12 mm (A-Z too small to fit; use text that shows every stroke type)
    out["02_lettering_5mm"] = D("02_lettering_5mm", [text("t1", "ABC HELLO 0123", 5, -4)])
    out["03_lettering_8mm"] = D("03_lettering_8mm", [text("t1", "ABC HELLO", 8, -6)])
    out["04_lettering_12mm"] = D("04_lettering_12mm", [text("t1", "ABC 123", 12, -8)])
    # 5. logo: filled shape + outline + short text (rounded, curved)
    heart = [[0, 8], [-12, -4], [-6, -14], [0, -8], [6, -14], [12, -4]]
    out["05_logo"] = D("05_logo", [
        {"id": "l1", "type": "fill", "color": RED, "smooth": True, "rings": [heart], "params": {"angle": 30}},
        {"id": "l2", "type": "run", "color": BLACK, "smooth": True, "closed": True, "points": heart},
        text("l3", "LOVE", 9, 18, BLUE)])
    # 6. border: repeated motif row (Maggam-style repeat)
    petal = {"type": "column", "color": GOLD, "rail1": [[0, 0], [-3, 5], [0, 10]], "rail2": [[0, 0], [3, 5], [0, 10]]}
    row = [dict(petal, id=f"b{i}", rail1=[[x + i * 9, y] for x, y in petal["rail1"]], rail2=[[x + i * 9, y] for x, y in petal["rail2"]]) for i in range(9)]
    for o in row:
        for k in ("rail1", "rail2"): o[k] = [[x - 36, y - 5] for x, y in o[k]]
    out["06_border"] = D("06_border", row + [{"id": "bl", "type": "run", "color": GOLD, "points": [[-40, 8], [40, 8]]}])
    # 7. four-colour design (stack of coloured blocks: tests colour-change position + registration)
    out["07_four_colour"] = D("07_four_colour", [
        {"id": "c1", "type": "fill", "color": RED, "rings": [rect(-20, -20, 20, 20)]},
        {"id": "c2", "type": "fill", "color": BLUE, "rings": [rect(0, -20, 20, 20)]},
        {"id": "c3", "type": "fill", "color": GREEN, "rings": [rect(-20, 0, 20, 20)]},
        {"id": "c4", "type": "fill", "color": GOLD, "rings": [rect(0, 0, 20, 20)]},
        {"id": "c5", "type": "run", "color": BLACK, "closed": True, "points": rect(-20, -20, 40, 40)}])
    # 8. satin columns 1.0 / 2.0 / 3.0 mm (+ 4/6 mm to show auto-split), 40 mm long
    cols = []
    for i, w in enumerate((1.0, 2.0, 3.0, 4.0, 6.0)):
        cols.append({"id": f"s{i}", "type": "satin", "color": BLUE, "points": [[-20, -30 + i * 14], [20, -30 + i * 14]],
                     "params": {"width": w}, "name": f"satin {w} mm"})
    out["08_satin_widths"] = D("08_satin_widths", cols)
    # 9. 30x30 mm fill (single variable: density/pull comp/underlay) + border run to check registration
    out["09_fill_30x30"] = D("09_fill_30x30", [
        {"id": "f1", "type": "fill", "color": RED, "rings": [rect(-15, -15, 30, 30)]},
        {"id": "f2", "type": "run", "color": BLACK, "closed": True, "points": rect(-15, -15, 30, 30)}])
    # 10. appliqué (placement -> tack-down -> cover; tests the stop + trim workflow)
    out["10_applique"] = D("10_applique", [{"id": "a1", "type": "applique", "color": GREEN, "rings": [rect(-18, -18, 36, 36)], "params": {"width": 2.5}}])
    # 11. fill patterns side by side: same 22 mm circle as tatami / contour / cross-stitch (compare density + texture)
    import math
    def circ(cx, r=11, n=48): return [[cx + r * math.cos(k * 2 * math.pi / n), r * math.sin(k * 2 * math.pi / n)] for k in range(n)]
    out["11_fill_patterns"] = D("11_fill_patterns", [
        {"id": "p1", "type": "fill", "color": RED, "rings": [circ(-26)], "params": {"pattern": "tatami"}},
        {"id": "p2", "type": "fill", "color": BLUE, "rings": [circ(0)], "params": {"pattern": "contour"}},
        {"id": "p3", "type": "fill", "color": GREEN, "rings": [circ(26)], "params": {"pattern": "cross", "cross_size": 2.0}}])
    # 12. trims and locks: a row of 5 mm running-stitch bars (one run each, so the jump distance IS the gap) on one line, separated by jumps of 1, 2, 3.5, 6, 12 and 25 mm. Jumps up to the
    #     3 mm trim threshold carry the thread; longer ones get tie-off + trim + tie-in. A second row in another colour tests the
    #     colour-change trim. Check what the machine cuts, and whether thread ends stay locked.
    def trim_row(prefix, color, y):
        row, end = [], None
        for k, g in enumerate((None, 1, 2, 3.5, 6, 12, 25)):
            start = -42.25 if g is None else end + g
            row.append({"id": f"{prefix}{k}", "type": "run", "color": color, "points": [[start, y], [start + 5, y]], "params": {"stitch_len": 2.5},
                        "name": "first bar" if g is None else f"bar after {g} mm jump"})
            end = start + 5
        return row
    out["12_trims_locks"] = D("12_trims_locks", trim_row("r", RED, -10) + trim_row("b", BLUE, 10))
    # ---------------------------------------------------------------- v2 additions
    # 13. orientation + measuring: a 60 x 40 mm frame (non-square, so a swapped X/Y is obvious), a horizontal and a vertical ruler line with a tick
    #     every 10 mm, an arrow head on the +X end and on the +Y (up) end, and a filled square ONLY in the upper-right corner.
    #     On the machine: the 60 mm side must run left-right, the arrow must point right / up, the square must be top-right as you face the machine.
    def arrow(i, tip, d):  # small chevron at `tip`, pointing in direction d = (dx, dy) (engine y is down)
        (tx, ty), (dx, dy) = tip, d; nx, ny = -dy, dx
        return {"id": i, "type": "run", "color": BLACK, "points": [[tx - dx * 4 + nx * 2.5, ty - dy * 4 + ny * 2.5], [tx, ty], [tx - dx * 4 - nx * 2.5, ty - dy * 4 - ny * 2.5]]}
    ticks = [{"id": f"th{k}", "type": "run", "color": BLACK, "points": [[-30 + k * 10, 0], [-30 + k * 10, -2.5]]} for k in range(7)] + \
            [{"id": f"tv{k}", "type": "run", "color": BLACK, "points": [[0, 20 - k * 10], [2.5, 20 - k * 10]]} for k in range(5)]
    out["13_axis_orientation"] = D("13_axis_orientation", [
        {"id": "frame", "type": "run", "color": BLACK, "closed": True, "points": rect(-30, -20, 60, 40), "name": "60 x 40 mm frame"},
        {"id": "hline", "type": "run", "color": BLACK, "points": [[-30, 0], [30, 0]], "name": "horizontal ruler, 60 mm"},
        {"id": "vline", "type": "run", "color": BLACK, "points": [[0, 20], [0, -20]], "name": "vertical ruler, 40 mm"},
        arrow("ah", (30, 0), (1, 0)), arrow("av", (0, -20), (0, -1)),
        {"id": "marker", "type": "fill", "color": RED, "rings": [rect(18, -18, 10, 10)], "name": "marker: TOP-RIGHT only"}] + ticks)
    # 14. small running-stitch design: a 24 mm circle and a 5-point star (2.5 mm stitches, no satin / fill)
    import math as _m
    star = [[(10 if k % 2 == 0 else 4.2) * _m.cos(_m.pi * k / 5 - _m.pi / 2) + 22, (10 if k % 2 == 0 else 4.2) * _m.sin(_m.pi * k / 5 - _m.pi / 2)] for k in range(10)]
    out["14_running_small"] = D("14_running_small", [
        {"id": "c", "type": "run", "color": BLUE, "closed": True, "points": [[-18 + 12 * _m.cos(k * _m.pi / 12), 12 * _m.sin(k * _m.pi / 12)] for k in range(24)], "params": {"stitch_len": 2.5}},
        {"id": "s", "type": "run", "color": RED, "closed": True, "points": [[x - 18, y] for x, y in star], "params": {"stitch_len": 2.5}}])
    # 15. jump movement: four small crosses at the corners of an 80 x 80 mm square. The needle must cross 80 mm between them (several
    #     12.1 mm records per jump). Trim distance is set high so the thread is CARRIED (no trims): this isolates the frame movement.
    def cross(i, cx, cy):
        return [{"id": i + "a", "type": "run", "color": BLACK, "points": [[cx - 3, cy], [cx + 3, cy]]}, {"id": i + "b", "type": "run", "color": BLACK, "points": [[cx, cy - 3], [cx, cy + 3]]}]
    d15 = D("15_jump_movement", cross("p1", -40, -40) + cross("p2", 40, -40) + cross("p3", 40, 40) + cross("p4", -40, 40))
    d15["machine"] = {"trim_distance": 200, "trim_at_color_change": 0, "trim_at_end": 1}
    out["15_jump_movement"] = d15
    # 16. hoop boundary: the largest design the hoop check allows (hoop minus margin each side) with a frame and corner marks.
    #     Needs the hoop this pack was generated for: run with --hoop WxH for your real hoop.
    w, h = HOOP["w"] - 2 * HOOP["margin"], HOOP["h"] - 2 * HOOP["margin"]
    out["16_hoop_boundary"] = D("16_hoop_boundary", [{"id": "fr", "type": "run", "color": BLACK, "closed": True, "points": rect(-w / 2, -h / 2, w, h), "name": "largest allowed area"},
        {"id": "d1", "type": "run", "color": RED, "points": [[-w / 2, -h / 2], [-w / 2 + 8, -h / 2 + 8]]}, {"id": "d2", "type": "run", "color": RED, "points": [[w / 2, h / 2], [w / 2 - 8, h / 2 - 8]]}])
    # 17-22. fabric-specific: one small design per PROVISIONAL fabric preset (30 mm tatami square + 40 mm satin column + outline), parameters
    #     exactly as the editor applies that preset. Stitch each on that fabric; none of the preset values has been verified on a machine.
    from stitchcraft_engine.design import FABRICS
    PACK_FABRICS = ["cotton", "silk", "georgette", "velvet", "denim", "knit"]      # the original six; satin / net / thick are experimental and have their own pack: --extra-fabrics
    if EXTRA:
        out = {}
        PACK_FABRICS = ["satin_fabric", "net", "thick"]
    for k, (fab, vals) in enumerate((f, FABRICS[f]) for f in PACK_FABRICS):
        pr = {"spacing": vals["spacing"], "pull_comp": vals["pull_comp"]}
        out[f"{(23 if EXTRA else 17) + k}_fabric_{fab}"] = D(f"{(23 if EXTRA else 17) + k}_fabric_{fab}", [
            {"id": "f", "type": "fill", "color": RED, "rings": [rect(-15, -22, 30, 22)], "params": dict(pr)},
            {"id": "s", "type": "satin", "color": BLUE, "points": [[-20, 14], [20, 14]], "params": dict(pr, width=3)},
            {"id": "o", "type": "run", "color": BLACK, "closed": True, "points": rect(-15, -22, 30, 22)}], fabric=fab)
    return out


EXTRA = False                                   # --extra-fabrics: only the experimental satin / net / thick designs (testpack/v2_extra_fabrics)


COLS = ["design", "file", "dst_version_sha256_12", "stitch_count", "size_mm", "est_min_UNVERIFIED", "colour_changes",
        "machine_model", "fabric", "stabiliser", "thread", "needle", "hoop", "speed_spm",
        "thread_breaks", "puckering", "registration", "jump_trim_behaviour", "colour_change_position", "overall_result", "notes"]
# overall_result: leave EMPTY until stitched. Allowed once stitched: PASS / FAIL / PASS WITH NOTES. Nothing in this repository pre-fills it.


def build(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, problems = [], []
    for name, d in designs().items():
        p, notes, st = generate(d)
        rep = run_checks(d, p)
        if not rep.ok:
            problems.append((name, [i.message for i in rep.errors])); continue
        from stitchcraft_engine.design import machine
        res = write_dst(p, trim_jumps=machine(d)["trim_jumps"])
        back = read_dst(res.data)
        assert back.ends_properly and back.color_changes == st["color_changes"], name
        (out_dir / f"{name}.dst").write_bytes(res.data)
        (out_dir / f"{name}.esproj").write_text(json.dumps({"app": "EmbroideryStudio", "version": 1, "doc": d}, indent=1))
        (out_dir / f"{name}.preview.svg").write_text(preview_svg(p, HOOP["w"], HOOP["h"]))
        rows.append({"design": name, "file": f"{name}.dst", "dst_version_sha256_12": res.sha256[:12], "stitch_count": st["stitches"],
                     "size_mm": f"{st['width_mm']} x {st['height_mm']}", "est_min_UNVERIFIED": st["est_minutes"], "colour_changes": st["color_changes"],
                     "hoop": f"{d['hoop']['w']} x {d['hoop']['h']} mm", "fabric": d.get("fabric", "") if name[:2] in ("17", "18", "19", "20", "21", "22", "23", "24", "25") else "",
                     "warnings": "; ".join(sorted({i.code for i in rep.warnings} | set())), "sha256": res.sha256})
    with open(out_dir / "RESULTS.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    (out_dir / "MANIFEST.json").write_text(json.dumps({
        "pack": "EmbroideryStudio machine test pack", "hoop_mm": [HOOP["w"], HOOP["h"], HOOP["margin"]], "physically_validated": False,
        "note": "Every design below is UNSTITCHED. No result, pass or fail, exists for any file until a person records it in RESULTS.",
        "files": [{"file": r["file"], "sha256": r["sha256"], "stitches": r["stitch_count"], "size_mm": r["size_mm"]} for r in rows]}, indent=1))
    tr = "".join(f"<tr><td><b>{html.escape(r['design'])}</b><br>DST {r['dst_version_sha256_12']}<br>{r['stitch_count']} stitches · {r['size_mm']} mm<br>"
                 f"est. ~{r['est_min_UNVERIFIED']} min (not verified) · {r['colour_changes']} colour change(s)"
                 f"{'<br><i>' + html.escape(r['warnings']) + '</i>' if r['warnings'] else ''}</td>" + "<td></td>" * 8 + "</tr>" for r in rows)
    (out_dir / "RESULTS.html").write_text(f"""<!doctype html><meta charset=utf-8><title>EmbroideryStudio stitch-out results</title>
<style>body{{font:12px system-ui;margin:16px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #888;padding:6px;height:52px;vertical-align:top}}th{{background:#eee}}.box{{border:2px solid #b45309;background:#fffbeb;padding:8px;margin:8px 0}}</style>
<h2>EmbroideryStudio stitch-out results</h2>
<div class="box"><b>Status: NOT YET PHYSICALLY VALIDATED.</b> This pack has not been stitched. Fabric presets are provisional. Time estimates are not verified. Fill in this sheet at the machine; leave every box empty until you have actually stitched the design.</div>
<table style="margin-bottom:10px"><tr><th>Machine model</th><td></td><th>Hoop used</th><td></td><th>Speed (spm)</th><td></td></tr>
<tr><th>Fabric</th><td></td><th>Stabiliser</th><td></td><th>Needle</th><td></td></tr>
<tr><th>Thread (brand / weight)</th><td></td><th>Date / operator</th><td></td><th>Pack version</th><td>{html.escape(str(out_dir.name))}</td></tr></table>
<table><tr><th>Design / DST version</th><th>Thread breaks (count + where)</th><th>Fabric puckering (0-3)</th><th>Registration (outline vs fill, mm)</th><th>Jump / trim behaviour</th><th>Colour-change position</th><th>Overall: PASS / FAIL / PASS WITH NOTES</th><th>Measured size (mm) / orientation OK?</th><th>Notes / change needed</th></tr>{tr}</table>
<p>Scale 0 = none … 3 = severe. Record the fabric and stabiliser for EVERY design. After a failure change ONE setting, regenerate that design only, and stitch it again.</p>""", encoding="utf-8")
    return rows, problems


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--hoop" in sys.argv:                                   # --hoop WxH[xM] : hoop size in mm (and safe margin) the hoop-boundary test is generated for
        spec = sys.argv[sys.argv.index("--hoop") + 1]; args = [a for a in args if a != spec]
        parts = [float(v) for v in spec.lower().split("x")]
        HOOP.update(w=parts[0], h=parts[1], margin=parts[2] if len(parts) > 2 else HOOP["margin"])
    if "--extra-fabrics" in sys.argv:
        EXTRA = True
    out = Path(args[0]) if args else ROOT / "testpack" / ("v2_extra_fabrics" if EXTRA else "v2")
    rows, problems = build(out)
    for r in rows: print(f"OK  {r['design']:20} {r['stitch_count']:>6} st  {r['size_mm']:>12} mm  ~{r['est_min_UNVERIFIED']} min (unverified)  {r['warnings']}")
    for n, m in problems: print("FAIL", n, m)
    sys.exit(1 if problems else 0)
