"""Builds the physical stitch-out test pack (requirements section F).
    python3 tools/make_testpack.py [out_dir]       default: testpack/
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
    return out


COLS = ["design", "file", "stitches", "size_mm", "est_min", "colour_changes", "thread_breaks", "puckering", "registration",
        "trim_behaviour", "colour_change_position", "fabric", "stabiliser", "needle", "speed_spm", "pass_fail", "notes"]


def build(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, problems = [], []
    for name, d in designs().items():
        p, notes, st = generate(d)
        rep = run_checks(d, p)
        if not rep.ok:
            problems.append((name, [i.message for i in rep.errors])); continue
        res = write_dst(p, trim_jumps=3)
        back = read_dst(res.data)
        assert back.ends_properly and back.color_changes == st["color_changes"], name
        (out_dir / f"{name}.dst").write_bytes(res.data)
        (out_dir / f"{name}.esproj").write_text(json.dumps({"app": "EmbroideryStudio", "version": 1, "doc": d}, indent=1))
        (out_dir / f"{name}.preview.svg").write_text(preview_svg(p, HOOP["w"], HOOP["h"]))
        rows.append({"design": name, "file": f"{name}.dst", "stitches": st["stitches"], "size_mm": f"{st['width_mm']} x {st['height_mm']}",
                     "est_min": st["est_minutes"], "colour_changes": st["color_changes"],
                     "warnings": "; ".join(sorted({i.code for i in rep.warnings} | set()))})
    with open(out_dir / "RESULTS.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    tr = "".join(f"<tr><td><b>{html.escape(r['design'])}</b><br>{r['stitches']} st · {r['size_mm']} mm<br>~{r['est_min']} min · {r['colour_changes']} col.chg"
                 f"{'<br><i>' + html.escape(r['warnings']) + '</i>' if r['warnings'] else ''}</td>" + "<td></td>" * 9 + "</tr>" for r in rows)
    (out_dir / "RESULTS.html").write_text(f"""<!doctype html><meta charset=utf-8><title>EmbroideryStudio stitch-out results</title>
<style>body{{font:12px system-ui;margin:16px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #888;padding:6px;height:46px;vertical-align:top}}th{{background:#eee}}</style>
<h2>EmbroideryStudio stitch-out results</h2><p>Machine: ________ Fabric: ________ Stabiliser: ________ Needle: ________ Speed: ________ spm Thread: ________ Date: ________</p>
<table><tr><th>Design</th><th>Thread breaks</th><th>Puckering</th><th>Registration</th><th>Trim behaviour</th><th>Colour-change position</th><th>Density OK?</th><th>Pass / Fail</th><th>Fix needed</th><th>Notes</th></tr>{tr}</table>
<p>Scale: 0 = none … 3 = severe. Record the fabric/stabiliser for EVERY design; re-run failures after changing ONE setting.</p>""", encoding="utf-8")
    return rows, problems


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "testpack"
    rows, problems = build(out)
    for r in rows: print(f"OK  {r['design']:20} {r['stitches']:>6} st  {r['size_mm']:>12} mm  ~{r['est_min']} min  {r['warnings']}")
    for n, m in problems: print("FAIL", n, m)
    sys.exit(1 if problems else 0)
