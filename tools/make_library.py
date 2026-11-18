"""Original bridal motif library: every design is drawn here from scratch (traditional motifs - lotus, paisley, mandala,
marigold, kalash, jhumka, temple border ... - as our own geometry), so the library carries no one else's artwork.
    python3 tools/make_library.py [out_dir]            default: designs/library/
Per design: <id>.dst, <id>.esproj (open in the Studio), <id>.thumb.svg; plus index.json for the Library panel.
Every design must pass the engine checks with no warnings and no notes, use <= 4 thread colours, and be deterministic.
Beads / pearls are placeholders on the production sheet, never in the DST. NOT stitched on a machine yet."""
import json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server")); sys.path.insert(0, str(ROOT / "tools"))
from stitchcraft_engine.design import generate, run_checks                    # noqa: E402
from stitchcraft_engine.dst import write_dst, read_dst                         # noqa: E402
from stitchcraft_engine.preview import thumbnail_svg                           # noqa: E402
import make_peacock_panel as mp                                                # noqa: E402
from make_peacock_panel import leaf, ellipse, tube, mirror                     # noqa: E402

GOLD, RED, MAROON, PINK, GREEN, LIME = "#d4af37", "#c8102e", "#7a0c2e", "#e85d9a", "#2e9e44", "#6fbf3b"
ORANGE, YELLOW, IVORY = "#f28c28", "#ffc72c", "#f5f0e1"
TYPE_RANK = {"fill": 0, "column": 1, "satin": 2, "text": 3, "run": 4}


def reset():
    mp._n[0] = 0
    return []


def polar(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def petals(O, cx, cy, r_in, length, width, n, color, name, start=-90.0, span=360.0):
    """n leaf petals radiating from (cx, cy): the petal's base is r_in from the centre."""
    for i in range(n):
        a = start + (span * i / n if span >= 360 else (span * i / max(1, n - 1) - span / 2))
        px, py = polar(cx, cy, r_in + length / 2, a)
        O.append(leaf(px, py, length, width, a, color, f"{name} {i + 1}"))


WIDE_PETAL_MM = 9.0      # a satin column wider than this on average is loose; stitch the shape as a fill instead


def leaf_shape(cx, cy, length, width, angle_deg, color, name):
    """A leaf/petal: a satin column when slim, a tatami fill (rows along the petal) when wide."""
    col = leaf(cx, cy, length, width, angle_deg, color, name)
    avg = sum(math.dist(a, b) for a, b in zip(col["rail1"][1:-1], col["rail2"][1:-1])) / max(1, len(col["rail1"]) - 2)
    if avg <= WIDE_PETAL_MM * 0.8:
        return col
    ring = col["rail1"] + col["rail2"][::-1][1:-1]
    return {"id": mp.oid("fill"), "type": "fill", "color": color, "name": name, "smooth": True, "rings": [ring],
            "params": {"angle": float(angle_deg) % 180, "pull_comp": 0.25}}


def fan(O, ox, oy, angles, length, width, color, name, spread=0.0):
    """Petals/leaves fanning out from (ox, oy). `spread` staggers the start points sideways (mm per petal): many tips on one
    point pile up needle penetrations (a lotus with 16 petals from one point measured 38 per mm^2)."""
    for i, a in enumerate(angles):
        px, py = polar(ox + (i - (len(angles) - 1) / 2) * spread, oy, length / 2, a)
        O.append(leaf_shape(px, py, length, width, a, color, f"{name} {i + 1}"))


def flower(O, cx, cy, r, color, name, n=5):
    for k in range(n):
        a = -90 + 360 / n * k
        px, py = polar(cx, cy, r * 0.55, a)
        O.append(leaf(px, py, r * 2.0, r * 1.05, a, color, f"{name} petal {k + 1}"))


def fill(O, pts, color, name, smooth=True, angle=None, pull=0.25, under=None):
    p = {"pull_comp": pull}
    if angle is not None: p["angle"] = angle
    if under is not None: p["underlay"] = under
    O.append({"id": mp.oid("fill"), "type": "fill", "color": color, "name": name, "smooth": smooth, "rings": [[[round(x, 3), round(y, 3)] for x, y in pts]], "params": p})


def satin(O, pts, color, name, width=1.8, smooth=True, underlay="auto"):
    O.append({"id": mp.oid("satin"), "type": "satin", "color": color, "name": name, "smooth": smooth, "points": [[round(x, 3), round(y, 3)] for x, y in pts], "params": {"width": width, "underlay": underlay}})


def line(O, pts, color, name, closed=False, smooth=True, stitch=2.2):
    O.append({"id": mp.oid("run"), "type": "run", "color": color, "name": name, "smooth": smooth, "closed": closed, "points": [[round(x, 3), round(y, 3)] for x, y in pts], "params": {"stitch_len": stitch}})


def finish(name, O, colour_order, hoop_pad=16):
    """Group by colour (fewest colour stops), fills -> columns -> satin -> text -> lines inside a colour; set the hoop."""
    rank = {c: i for i, c in enumerate(colour_order)}
    stitched = [o for o in O if o["type"] != "embellishment"]
    emb = [o for o in O if o["type"] == "embellishment"]
    stitched.sort(key=lambda o: (rank[o["color"]], TYPE_RANK[o["type"]]))
    d = {"name": name, "hoop": {"w": 100, "h": 100, "margin": 5}, "fabric": "silk", "stabiliser": "cut-away", "objects": stitched + emb}
    st = generate(d)[2]
    d["hoop"]["w"] = max(100, int(math.ceil((st["width_mm"] + hoop_pad) / 10.0) * 10))
    d["hoop"]["h"] = max(100, int(math.ceil((st["height_mm"] + hoop_pad) / 10.0) * 10))
    return d


# ====================================================================================================== designs
def lotus():
    O = reset()
    base = (0, 26)
    fan(O, *base, [-90 + k for k in (-66, -44, -22, 0, 22, 44, 66)], 40, 13, PINK, "Back petal", spread=2.8)
    fan(O, *base, [-90 + k for k in (-55, -33, -11, 11, 33, 55)], 32, 11.5, RED, "Middle petal", spread=2.8)
    fan(O, *base, [-90 - 24, -90, -90 + 24], 22, 9.5, GOLD, "Front petal", spread=3.4)
    fan(O, *base, [-14, 194], 36, 12.5, GREEN, "Lotus leaf")
    satin(O, [[-34, 33], [-17, 36], [0, 34], [17, 36], [34, 33]], GOLD, "Water line", 1.6)
    return finish("lotus_bloom", O, [GREEN, PINK, RED, GOLD])


def mandala():
    O = reset()
    petals(O, 0, 0, 22, 15, 7.5, 16, RED, "Outer petal")
    petals(O, 0, 0, 12, 12, 6.2, 16, GOLD, "Mid petal", start=-90 + 11.25)
    petals(O, 0, 0, 4, 9, 5.6, 8, MAROON, "Inner petal", start=-90 + 22.5)
    O.append({"id": mp.oid("fill"), "type": "fill", "color": GOLD, "name": "Centre", "rings": [ellipse(0, 0, 4.2, 4.2, 0, 24)], "params": {"underlay": "none", "pull_comp": 0.2}})
    line(O, ellipse(0, 0, 41.5, 41.5, 0, 48), GOLD, "Outer ring", closed=True, stitch=2.4)
    return finish("mandala_rosette", O, [MAROON, RED, GOLD])


def marigold():
    O = reset()
    petals(O, 0, 0, 16, 13.5, 7.4, 18, ORANGE, "Outer petal")
    petals(O, 0, 0, 8, 12, 7.0, 14, YELLOW, "Mid petal", start=-90 + 12.8)
    petals(O, 0, 0, 2.5, 9, 6.0, 9, ORANGE, "Inner petal", start=-90 + 20)
    O.append({"id": mp.oid("fill"), "type": "fill", "color": GREEN, "name": "Centre", "rings": [ellipse(0, 0, 3.6, 3.6, 0, 20)], "params": {"underlay": "none", "pull_comp": 0.2}})
    return finish("marigold_flower", O, [ORANGE, YELLOW, GREEN])


def paisley_shape(w0=30.0, s_end=1.0, radius=34.0, sweep_deg=105.0, power=0.75):
    """A paisley as a tapered tube along a curved centre line: round bulb at the start, curling tail tapering to a point.
    Centre line = an arc that starts at the bulb centre (0, 10) heading up and curls to the left."""
    cx, cy = radius, 10.0                                     # arc centre; the arc starts at (0, 10) and sweeps up and over
    def C(s):
        a = math.pi - math.radians(sweep_deg) * s
        return cx + radius * math.cos(a), cy - radius * math.sin(a)
    n = 40
    left, right = [], []
    for i in range(n + 1):
        s = s_end * i / n
        x, y = C(s)
        x2, y2 = C(min(1.0, s + 1e-3)); x1, y1 = C(max(0.0, s - 1e-3))
        tx, ty = x2 - x1, y2 - y1; l = math.hypot(tx, ty) or 1
        nx, ny = -ty / l, tx / l
        w = w0 * max(0.0, 1 - s) ** power / 2
        w = max(w, 0.9) if i < n else 0.9                      # blunt tip: a needle-sharp tip makes the satin outline cross itself
        left.append((x + nx * w, y + ny * w)); right.append((x - nx * w, y - ny * w))
    # round bulb cap: half circle behind the start, from the right rail round to the left rail
    x0, y0 = C(0.0); x1, y1 = C(1e-3)
    ang = math.atan2(y1 - y0, x1 - x0)
    r0 = w0 / 2
    cap = [(x0 + r0 * math.cos(ang + math.pi / 2 + math.pi * k / 14), y0 + r0 * math.sin(ang + math.pi / 2 + math.pi * k / 14)) for k in range(1, 14)]
    ring = left + right[::-1] + cap[::-1]                      # the outline arrives on the right rail, so the cap runs right -> back -> left
    return [[round(x, 3), round(y, 3)] for x, y in ring]


def paisley_pair():
    O = reset()
    for sx, tag in ((-1, "Left"), (1, "Right")):
        place = lambda pts, dx=0.0: [[sx * (x + dx), y] for x, y in pts]
        body = paisley_shape(w0=26.0, radius=30.0, sweep_deg=72.0)
        fill(O, place(body, -36), RED, f"{tag} paisley body", angle=70 if sx > 0 else 110)
        O[-1]["params"]["spacing"] = 0.5
        inner = paisley_shape(w0=12.0, s_end=0.55, radius=30.0, sweep_deg=72.0)
        fill(O, place(inner, -36), GOLD, f"{tag} inner paisley", angle=20 if sx > 0 else 160)
        O[-1]["params"]["spacing"] = 0.5
        satin(O, place(body + [body[0]], -36), GOLD, f"{tag} outline", 1.8)
        O.append(leaf(sx * -36, 10, 5.6, 4.6, 90, MAROON, f"{tag} eye"))                  # a column (not a fill): stitched last, on top of the gold
    return finish("paisley_pair", O, [RED, GOLD, MAROON])


def vine_border():
    O = reset()
    L = 110
    xs = [-L / 2 + i * 2.0 for i in range(int(L / 2) + 1)]
    vine = [[x, 4.2 * math.sin(2 * math.pi * x / 36.0)] for x in xs]
    satin(O, vine, GOLD, "Vine", 1.6)
    for i in range(1, 12):
        x = -L / 2 + i * 9.2
        y = 4.2 * math.sin(2 * math.pi * x / 36.0)
        dy = 4.2 * 2 * math.pi / 36.0 * math.cos(2 * math.pi * x / 36.0)
        ang = math.degrees(math.atan2(dy, 1.0))
        up = 1 if i % 2 else -1
        a = ang - up * 55
        px, py = polar(x, y, 5.8, a)
        O.append(leaf(px, py, 11.5, 5.2, a, GREEN, f"Leaf {i}"))
    for k, x in enumerate((-36, 0, 36)):
        flower(O, x + 9, -7.3 if False else 4.2 * math.sin(2 * math.pi * (x + 9) / 36.0) - 11.5, 4.2, RED, f"Flower {k + 1}")
    return finish("floral_vine_border", O, [GREEN, RED, GOLD])


def temple_border():
    O = reset()
    n, w, h = 11, 10.0, 9.5
    x0 = -n * w / 2
    for i in range(n):
        bx = x0 + i * w
        tri = [[bx + 0.6, 0], [bx + w - 0.6, 0], [bx + w / 2 + 0.9, -h], [bx + w / 2 - 0.9, -h]]     # flat top: a sharp apex leaves one tiny last row
        fill(O, tri, RED if i % 2 == 0 else MAROON, f"Triangle {i + 1}", smooth=False)
        O.append(leaf(bx + w / 2, -4.6, 5.6, 2.8, 90, GOLD, f"Gold tip {i + 1}"))
    satin(O, [[x0, 2.4], [-x0, 2.4]], GOLD, "Base band", 2.4, smooth=False)
    pts = []
    for i in range(n):
        bx = x0 + i * w
        pts += [[bx, 7.0], [bx + w / 2, 10.2]]
    pts.append([-x0, 7.0])
    satin(O, pts, GOLD, "Scalloped hem", 1.6)
    return finish("temple_border", O, [MAROON, RED, GOLD])


def kalash():
    O = reset()
    body = [[-14, 30], [-18, 12], [-16, -2], [-9, -10], [-7, -14], [7, -14], [9, -10], [16, -2], [18, 12], [14, 30]]
    fill(O, body, RED, "Pot", angle=80)
    for k, y in enumerate((2, 20)):
        w = 17.2 - abs(y - 12) * 0.1
        satin(O, [[-w, y], [0, y + 1.6], [w, y]], GOLD, f"Band {k + 1}", 1.7)
    O.append(leaf(0, 11, 13, 7.5, 90, GOLD, "Pot lotus"))
    satin(O, [[-15, 31.6], [15, 31.6]], GOLD, "Base", 2.0, smooth=False)
    satin(O, [[-8, -14.5], [8, -14.5]], GOLD, "Rim", 2.0, smooth=False)
    for i, a in enumerate([-90 - 56, -90 - 28, -90, -90 + 28, -90 + 56]):                 # starts spread along the rim: five tips on one point = dense, needle-breaking spot
        ox = (i - 2) * 3.0
        px, py = polar(ox, -14, 13.5, a)
        O.append(leaf_shape(px, py, 27, 9.5, a, GREEN, f"Mango leaf {i + 1}"))
    O.append({"id": mp.oid("fill"), "type": "fill", "color": GOLD, "name": "Coconut", "rings": [ellipse(0, -34, 7.6, 8.8, 0, 26)], "params": {"pull_comp": 0.25}})
    return finish("kalash", O, [GREEN, RED, GOLD])


def jhumka():
    O = reset()
    fill(O, [[-15, 0], [-13, -9], [-6, -14], [0, -15], [6, -14], [13, -9], [15, 0]], GOLD, "Dome", angle=90)
    bell = [[-15, 1], [-19, 12], [-22, 24], [22, 24], [19, 12], [15, 1]]
    fill(O, bell, RED, "Bell", smooth=False, angle=75)
    satin(O, [[-22, 25.5], [22, 25.5]], GOLD, "Hem", 2.0, smooth=False)
    O.append({"id": mp.oid("fill"), "type": "fill", "color": GOLD, "name": "Stone", "rings": [ellipse(0, -5.5, 4.6, 4.6, 0, 22)], "params": {"underlay": "none", "pull_comp": 0.2}})
    for k in range(5):
        a = -90 + 72 * k
        px, py = polar(0, -22, 5.6, a)
        O.append(leaf(px, py, 9, 4.6, a, GOLD, f"Stud petal {k + 1}"))
    drops = []
    for i, x in enumerate([-18, -13.5, -9, -4.5, 0, 4.5, 9, 13.5, 18]):
        y = 30 + (4 if i % 2 else 0)
        O.append(leaf(x, y + 5, 8.5, 3.9, 90, GOLD, f"Drop {i + 1}"))
        drops.append([x, y + 10.6])
    O.append({"id": mp.oid("emb"), "type": "embellishment", "kind": "bead", "color": "#ffffff", "size_mm": 2.5, "name": "Pearls at the drops", "points": drops})
    return finish("jhumka_bell", O, [RED, GOLD])


def scroll_pair():
    O = reset()
    for sx, tag in ((-1, "Left"), (1, "Right")):
        cx = sx * 24
        pts = []
        for i in range(61):
            t = i / 60
            a = -90 + sx * 360 * 2.1 * t
            r = 21 * (1 - t) ** 0.85 + 2.6
            x, y = polar(0, 0, r, a)
            pts.append([x * sx * -1 * -1 + cx, y])
        O.append(tube(pts[::2], 3.6, 1.7, GOLD, f"{tag} scroll"))
        for k in range(5):
            i = 8 + k * 9
            x, y = pts[i]
            ox, oy = polar(cx, 0, 1, math.degrees(math.atan2(y, x - cx)))
            O.append(leaf(x + (x - cx) * 0.16 * 0 + (ox - cx) * 6, y + (oy - 0) * 6, 9, 4.2, math.degrees(math.atan2(y, x - cx)), GREEN, f"{tag} leaf {k + 1}"))
    return finish("scroll_pair", O, [GREEN, GOLD])


def rings_heart():
    O = reset()
    r, off = 14.0, 9.0
    ix, iy = 0.0, math.sqrt(r * r - off * off)
    def arc(cx, cy, skip_deg, skip_around, n=60):
        pts = []
        for i in range(n + 1):
            a = i * 360 / n
            d = (a - skip_around + 180) % 360 - 180
            if abs(d) > skip_deg:
                pts.append(polar(cx, cy, r, a))
            elif pts:
                yield pts; pts = []
        if pts: yield pts
    # ring A (left): gap near the bottom intersection; ring B (right): gap near the top intersection -> interlocked look
    angA = math.degrees(math.atan2(iy, ix - (-off)))
    angB = math.degrees(math.atan2(-iy, ix - off))
    for k, seg in enumerate(arc(-off, 0, 11, angA)):
        if len(seg) > 2: satin(O, seg, GOLD, f"Ring A arc {k + 1}", 2.2)
    for k, seg in enumerate(arc(off, 0, 11, angB)):
        if len(seg) > 2: satin(O, seg, GOLD, f"Ring B arc {k + 1}", 2.2)
    heart = [[0, -20], [-5, -27], [-12, -28], [-16, -22], [-13, -14], [0, -4], [13, -14], [16, -22], [12, -28], [5, -27]]
    fill(O, [[x * 0.8, y * 0.8 - 15] for x, y in heart], RED, "Heart", angle=60)
    line(O, [[x * 0.8, y * 0.8 - 15] for x, y in heart], GOLD, "Heart outline", closed=True, stitch=2.0)
    return finish("rings_and_heart", O, [RED, GOLD])


def bride_frame():
    O = reset()
    O.append({"id": mp.oid("text"), "type": "text", "color": MAROON, "name": "BRIDE", "text": "BRIDE", "height": 12, "x": -29.5, "y": -6, "params": {"width": 1.9}})
    satin(O, ellipse(0, 0, 47, 20, 0, 40), GOLD, "Frame", 2.2)
    line(O, ellipse(0, 0, 42.5, 16.2, 0, 40), GOLD, "Inner frame", closed=True, stitch=2.2)
    for sx in (-1, 1):
        fan(O, sx * 47, 0, [(-30 if sx > 0 else 210), (30 if sx > 0 else 150)], 14, 5.6, GREEN, "Leaf") if False else None
        for k, a in enumerate((-35, 35)):
            aa = a if sx > 0 else 180 - a
            px, py = polar(sx * 47, 0, 7, aa)
            O.append(leaf(px, py, 14, 5.6, aa, GREEN, f"Corner leaf {sx}{k}"))
        flower(O, sx * 47 + sx * 2, 0, 3.4, RED, "Corner flower")
    return finish("bride_frame", O, [GREEN, RED, MAROON, GOLD])


def peacock():
    d = mp.build(); d["name"] = "peacock_arch"
    return d


DESIGNS = [
    ("lotus_bloom", "Lotus bloom", "Floral", "Layered lotus with leaves and a water line.", lotus),
    ("mandala_rosette", "Mandala rosette", "Floral", "Three rings of petals and a centre stone, circled by a running outline.", mandala),
    ("marigold_flower", "Marigold flower", "Floral", "Ruffled three-layer marigold - garland and haldi favourite.", marigold),
    ("paisley_pair", "Paisley pair", "Paisley", "Two mirrored mango/paisley motifs with small flowers.", paisley_pair),
    ("floral_vine_border", "Floral vine border", "Borders", "Flowing vine with alternating leaves and red flowers, 110 mm long.", vine_border),
    ("temple_border", "Temple border", "Borders", "Kanchi-style triangle border with gold tips and scalloped hem, 110 mm long.", temple_border),
    ("kalash", "Kalash", "Auspicious", "Pot with mango leaves and coconut.", kalash),
    ("jhumka_bell", "Jhumka bell", "Jewellery", "Bridal earring motif: stud, dome, bell and drops (pearl positions listed for hand work).", jhumka),
    ("scroll_pair", "Scroll pair", "Vines", "Mirrored spiral scrolls with leaves (mehndi-style).", scroll_pair),
    ("rings_and_heart", "Rings & heart", "Wedding", "Interlocked wedding rings under a heart.", rings_heart),
    ("bride_frame", "BRIDE frame", "Wedding", "Oval gold frame with lettering and corner leaves + flowers.", bride_frame),
    ("peacock_arch", "Peacock arch panel", "Peacock", "The hand-digitized peacock-in-arch blouse panel (same as designs/peacock_arch).", peacock),
]


def build_all():
    out = []
    for id_, name, cat, desc, fn in DESIGNS:
        out.append((id_, name, cat, desc, fn()))
    return out


def main(argv):
    out = Path(argv[0]) if argv else ROOT / "designs" / "library"
    out.mkdir(parents=True, exist_ok=True)
    index, bad = [], 0
    for id_, name, cat, desc, d in build_all():
        d["name"] = id_
        p, notes, st = generate(d); rep = run_checks(d, p)
        colours = st["color_changes"] + 1
        problems = [f"{i.severity} {i.code}: {i.message}" for i in rep.issues] + [f"note: {n}" for n in notes]
        if not rep.ok or problems or colours > 4:
            bad += 1
            print(f"  !! {id_:20} colours={colours}", *problems[:4], sep="\n      ")
        else:
            print(f"  ok {id_:20} {st['stitches']:>5} st  {colours} col  {st['trims']:>3} trims  {st['width_mm']}x{st['height_mm']} mm")
        if not rep.ok:
            continue
        res = write_dst(p, trim_jumps=3)
        back = read_dst(res.data)
        assert back.ends_properly and back.color_changes == st["color_changes"], id_
        sub = out / id_; sub.mkdir(exist_ok=True)
        (sub / f"{id_}.dst").write_bytes(res.data)
        (sub / f"{id_}.esproj").write_text(json.dumps({"app": "EmbroideryStudio", "version": 1, "doc": d}, indent=1), encoding="utf-8")
        (sub / f"{id_}.thumb.svg").write_text(thumbnail_svg(p, 240), encoding="utf-8")
        index.append({"id": id_, "name": name, "category": cat, "description": desc, "width_mm": st["width_mm"], "height_mm": st["height_mm"],
                      "stitches": st["stitches"], "colours": colours, "trims": st["trims"], "est_minutes": st["est_minutes"],
                      "threads": [t["hex"] for t in st["threads"]], "embellishments": st.get("embellishments", {}),
                      "sha256": res.sha256})
    (out / "index.json").write_text(json.dumps({"version": 1, "designs": index}, indent=1), encoding="utf-8")
    print(f"{len(index)} designs written to {out}" + (f"  ({bad} with problems)" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
