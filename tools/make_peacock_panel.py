"""Peacock-in-arch panel (hand-digitized, simplified interpretation of a Maggam/Aari blouse motif).
    python3 tools/make_peacock_panel.py [out_dir]       default: designs/peacock_arch/
Single source of truth for the design: edit here, regenerate. Output: .dst, .esproj (open in the Studio), preview .svg,
production sheet, package zip. Beads / stones / pearls are NOT stitched: they are placeholders on the production sheet.
Units mm, y down, origin = panel centre. Size ~100 x 140 mm (fits a 130 x 180 mm / 5 x 7 in hoop)."""
import json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine.design import generate, run_checks           # noqa: E402
import app as srv                                                      # noqa: E402
import sheet                                                           # noqa: E402

GOLD, RED, LIME = "#d4af37", "#c8102e", "#6fbf3b"
HOOP = {"w": 130, "h": 180, "margin": 6}
_n = [0]


def oid(prefix):
    _n[0] += 1
    return f"{prefix}{_n[0]}"


def mirror(pts):
    return [[-x, y] for x, y in pts]


def arch_left():
    """Left half of an ogee/pointed arch from base to apex."""
    return [[-46, 58], [-46.5, 36], [-46, 12], [-43.5, -8], [-38, -27], [-29, -43], [-17, -56], [-7, -64], [0, -69]]


def full_arch(pts_left):
    return pts_left + mirror(pts_left[:-1])[::-1]


def inset(pts, k_x=0.84, k_y=0.9, base=58):
    return [[x * k_x, base + (y - base) * k_y] for x, y in pts]


def ellipse(cx, cy, rx, ry, rot=0.0, n=28):
    c, s = math.cos(rot), math.sin(rot)
    out = []
    for k in range(n):
        t = 2 * math.pi * k / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append([round(cx + x * c - y * s, 3), round(cy + x * s + y * c, 3)])
    return out


def leaf(cx, cy, length, width, angle_deg, color, name, bulge=0.5):
    """Pointed leaf as a two-rail column (tips shared): rails bulge to `width`."""
    a = math.radians(angle_deg)
    ux, uy, nx, ny = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
    r1, r2 = [], []
    for k in range(9):
        t = k / 8
        w = width / 2 * math.sin(math.pi * t) ** 0.8
        x, y = cx + ux * length * (t - 0.5), cy + uy * length * (t - 0.5)
        r1.append([round(x + nx * w, 3), round(y + ny * w, 3)]); r2.append([round(x - nx * w, 3), round(y - ny * w, 3)])
    r1[0] = r2[0] = [round(cx - ux * length / 2, 3), round(cy - uy * length / 2, 3)]
    r1[-1] = r2[-1] = [round(cx + ux * length / 2, 3), round(cy + uy * length / 2, 3)]
    return {"id": oid("leaf"), "type": "column", "color": color, "name": name, "rail1": r1, "rail2": r2, "params": {"underlay": "none"}}


def tube(center, w0, w1, color, name):
    """Tapered two-rail column along a centre line (neck)."""
    r1, r2 = [], []
    for i, (x, y) in enumerate(center):
        a = center[max(i - 1, 0)]; b = center[min(i + 1, len(center) - 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]; l = math.hypot(tx, ty) or 1
        nx, ny = -ty / l, tx / l
        w = (w0 + (w1 - w0) * i / (len(center) - 1)) / 2
        r1.append([round(x + nx * w, 3), round(y + ny * w, 3)]); r2.append([round(x - nx * w, 3), round(y - ny * w, 3)])
    return {"id": oid("tube"), "type": "column", "color": color, "name": name, "rail1": r1, "rail2": r2, "smooth": True, "params": {"underlay": "center"}}


def transform(d, scale=1.0, flip=False):
    """Scale all geometry about the origin and/or mirror it left-right (a true mirrored copy for the other sleeve).
    Stitch parameters (satin widths, spacing) and bead/stone sizes stay physical - only positions are scaled."""
    import copy
    d = copy.deepcopy(d)
    f = lambda p: [round((-p[0] if flip else p[0]) * scale, 3), round(p[1] * scale, 3)]
    for o in d["objects"]:
        if flip and o["type"] == "fill":                       # a mirrored fill must run in the mirrored direction (80 deg -> 100 deg)
            o["params"] = dict(o.get("params", {}), angle=(180.0 - float(o.get("params", {}).get("angle", 45.0))) % 180.0)
        if "rings" in o:
            o["rings"] = [[f(p) for p in r] for r in o["rings"]]
        for k in ("points", "rail1", "rail2"):
            if k in o:
                o[k] = [f(p) for p in o[k]]
    return d


MIN_COLUMN_MM = 1.5      # a satin column narrower than this on average is not reliably stitchable


def drop_unstitchable(d, min_column_mm=MIN_COLUMN_MM):
    """Remove details that a scale-down pushed below the minimum stitchable size. Returns (design, [names dropped])."""
    dropped, keep = [], []
    for o in d["objects"]:
        if o["type"] == "column":
            n = max(1, len(o["rail1"]) - 2)
            w = sum(math.dist(a, b) for a, b in zip(o["rail1"][1:-1], o["rail2"][1:-1])) / n
            if w < min_column_mm:
                dropped.append(o["name"]); continue
        keep.append(o)
    return dict(d, objects=keep), dropped


def build():
    _n[0] = 0
    O = []
    A = lambda o: O.append(o)
    arch = full_arch(arch_left())
    # ------------------------------------------------------------------ 1. RED + LIME fills first (lower layers), gold last
    # peacock body (lime) with a red wing; tail = a fan of 7 feather leaves (alternating red / lime) radiating from the body's rear
    BODY = (6, 41)
    A({"id": oid("body"), "type": "fill", "color": LIME, "name": "Peacock body", "rings": [ellipse(BODY[0], BODY[1], 15.5, 10, math.radians(-10))], "params": {"angle": 80, "pull_comp": 0.3}})
    A({"id": oid("head"), "type": "fill", "color": RED, "name": "Head", "rings": [ellipse(27.5, -8, 3.7, 3.4)], "params": {"underlay": "none", "pull_comp": 0.2}})
    A(leaf(BODY[0] + 1, BODY[1] + 1, 17, 8, -14, RED, "Wing"))
    FAN_O = (-6, 43)
    fan = [(188, 29), (205, 31), (222, 32), (239, 33), (256, 33), (273, 32), (290, 29)]            # (angle deg, length mm): y-down, 270 = straight up
    for i, (ang, ln) in enumerate(fan):
        r = math.radians(ang)
        A(leaf(FAN_O[0] + math.cos(r) * ln / 2, FAN_O[1] + math.sin(r) * ln / 2, ln, 7.4, ang, RED if i % 2 == 0 else LIME, f"Tail feather {i + 1}"))
    # red flower above the apex (5 petals)
    for k in range(5):
        a = -90 + 72 * k
        A(leaf(0 + 4.2 * math.cos(math.radians(a)), -77 + 4.2 * math.sin(math.radians(a)), 8.5, 4.4, a, RED, f"Flower petal {k + 1}"))
    # ------------------------------------------------------------------ 2. GOLD: leaf, fronds, outlines, borders
    half = [[-0.5, -51], [-7.4, -41], [-8.2, -33], [-5, -25], [-0.5, -19.5]]               # one half of the leaf; the 1 mm centre gap is the vein
    for nm, pts in (("Centre leaf left half", half), ("Centre leaf right half", mirror(half))):
        A({"id": oid("centreleaf"), "type": "fill", "color": GOLD, "name": nm, "smooth": True, "rings": [pts], "params": {"angle": 90, "pull_comp": 0.2}})
    for side, sx in (("L", -1), ("R", 1)):                                    # curved fronds either side of the leaf
        for j, (x, y, ang) in enumerate([(13, -45, -62), (16.5, -37, -38), (18, -28, -14), (17, -19, 12)]):
            A(leaf(sx * x, y, 10.5, 4.0, (180 - ang) if sx < 0 else ang, GOLD, f"Frond {side}{j + 1}"))
    A({"id": oid("arch_outer"), "type": "satin", "color": GOLD, "name": "Outer arch", "points": arch, "smooth": True, "params": {"width": 2.4, "underlay": "center", "pull_comp": 0.25}})
    A({"id": oid("arch_inner"), "type": "run", "color": GOLD, "name": "Inner arch line", "points": inset(arch), "smooth": True, "params": {"stitch_len": 2.2}})
    # neck, crest, beak, body/wing outline (gold)
    A(tube([[16, 36], [24, 28], [28, 18], [27, 6], [27.5, -4]], 7.2, 3.4, GOLD, "Peacock neck"))
    A(leaf(33.4, -8.3, 7.4, 3.4, -9, GOLD, "Beak"))
    for k, (ex, ey) in enumerate([(25.2, -14.4), (27.8, -15.8), (30.2, -14.2)]):                           # crest
        A({"id": oid("crest"), "type": "run", "color": GOLD, "name": f"Crest {k + 1}", "points": [[27.5, -11], [ex, ey - 2.6]], "params": {"stitch_len": 1.6}})
    A({"id": oid("bodyline"), "type": "run", "color": GOLD, "name": "Body outline", "closed": True, "smooth": True, "points": ellipse(BODY[0], BODY[1], 16.1, 10.6, math.radians(-10), 16), "params": {"stitch_len": 2.0}})
    for i, (ang, ln) in enumerate(fan):                                                                    # feather eyes: tiny satin leaves (a 4 mm fill is too small for tatami)
        r = math.radians(ang)
        A(leaf(FAN_O[0] + math.cos(r) * ln * 0.72, FAN_O[1] + math.sin(r) * ln * 0.72, 5.0, 2.6, ang, GOLD, f"Feather eye {i + 1}"))
    # base band: scalloped satin
    pts = []
    for i in range(9):
        x0 = -40 + i * 10
        pts += [[x0, 54], [x0 + 5, 57.6]]
    pts.append([40, 54])
    A({"id": oid("base"), "type": "satin", "color": GOLD, "name": "Scalloped base", "points": pts, "smooth": True, "params": {"width": 1.8, "underlay": "none"}})
    # ------------------------------------------------------------------ 3. embellishment placeholders (NOT stitched)
    inner = inset(arch)
    beads = [p for i, p in enumerate(inner) if i % 2 == 0]
    A({"id": oid("emb"), "type": "embellishment", "kind": "bead", "color": GOLD, "size_mm": 2.5, "name": "Gold beads on inner arch", "points": [[round(x, 2), round(y, 2)] for x, y in beads]})
    A({"id": oid("emb"), "type": "embellishment", "kind": "stone", "color": "#ffffff", "size_mm": 3.0, "name": "Stones: flower centre + leaf tip", "points": [[0, -77], [0, -53]]})
    A({"id": oid("emb"), "type": "embellishment", "kind": "bead", "color": "#ffffff", "size_mm": 2.0, "name": "Pearl: peacock eye", "points": [[28.6, -8.6]]})
    A({"id": oid("emb"), "type": "embellishment", "kind": "sequin", "color": RED, "size_mm": 2.5, "name": "Red sequins on tail eyes",
       "points": [[round(FAN_O[0] + math.cos(math.radians(a)) * ln * 0.72, 2), round(FAN_O[1] + math.sin(math.radians(a)) * ln * 0.72, 2)] for a, ln in fan]})
    # Stitch order: group by thread colour (fewest colour stops), and inside a colour fills first, then columns/satin, then lines,
    # so outlines always land on top of the fills they overlap. Embellishment placeholders are never stitched.
    colour_rank = {LIME: 0, RED: 1, GOLD: 2}
    type_rank = {"fill": 0, "column": 1, "satin": 2, "text": 3, "run": 4}
    stitched = [o for o in O if o["type"] != "embellishment"]
    placeholders = [o for o in O if o["type"] == "embellishment"]
    stitched.sort(key=lambda o: (colour_rank[o["color"]], type_rank[o["type"]]))      # sort is stable: build order kept otherwise
    return {"name": "peacock_arch_panel", "hoop": dict(HOOP), "fabric": "silk", "stabiliser": "cut-away", "objects": stitched + placeholders}


def cli(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Peacock-in-arch panel -> DST + project + sheet + package files")
    ap.add_argument("out_dir", nargs="?", default=str(ROOT / "designs" / "peacock_arch"))
    ap.add_argument("--scale", type=float, default=1.0, help="geometry scale (sleeve panel ~0.65)")
    ap.add_argument("--mirror", action="store_true", help="mirror left-right (the other sleeve)")
    ap.add_argument("--name", default="peacock_arch_panel")
    a = ap.parse_args(argv)
    if not 0.3 <= a.scale <= 1.5:
        ap.error("--scale must be between 0.3 and 1.5")
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    d = transform(build(), a.scale, a.mirror); d["name"] = a.name
    d, dropped = drop_unstitchable(d)
    if dropped:
        print(f"OMITTED (below {MIN_COLUMN_MM} mm after scaling): {', '.join(dropped)}")
    p, notes, st = generate(d); rep = run_checks(d, p)
    for i in rep.issues: print(i.severity.upper(), i.code, i.message)
    for n in notes: print("NOTE", n)
    print(f"{a.name}: stitches={st['stitches']} colours={st['color_changes'] + 1} trims={st['trims']} size={st['width_mm']}x{st['height_mm']} mm est={st['est_minutes']} min")
    if not rep.ok:
        return 2
    data, err = sheet.package(d)
    if err:
        print(err); return 2
    import zipfile, io
    z = zipfile.ZipFile(io.BytesIO(data))
    for n in z.namelist():
        (out / n).write_bytes(z.read(n))
    print("wrote", sorted(z.namelist()))
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
