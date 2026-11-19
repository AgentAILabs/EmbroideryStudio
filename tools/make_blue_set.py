"""Blue maggam blouse set (v2) - ORIGINAL designs in the style of the reference photos (royal-blue silk, mint-green and copper thread):
six-petal daisies with copper centres, floral vine sprays with leaves / buds / copper sprigs, a pair of facing birds with paisley tails,
a mint satin neckline band edged with copper bead dots. Hand-digitized as vector objects, NOT traced from the photos (the photos carry a
designer's watermark; their artwork is not copied).

    python3 tools/make_blue_set.py [out_dir]            default: designs/blue_set/

One DST per element (each with .esproj, preview, production sheet, reports):
  blue_daisy_large, blue_daisy_small, blue_copper_sprig, blue_floral_vine_spray, blue_peacock_single (left + right mirror pair),
  blue_peacock_pair, blue_neck_border_band, blue_front_neck_full (U neckline + vines + bird pair; needs a large frame)
Thread colours: mint #3fd6b4, copper #b85a2b (metallic look: copper kept 0.27 mm open). Fabric preset 'silk' (experimental, unverified).
Units mm, y down, origin = design centre. Nothing here has been stitched on a machine."""
import json, math, sys, zipfile, io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server")); sys.path.insert(0, str(ROOT / "tools"))
from stitchcraft_engine import profiles, sequence, placements, checklist   # noqa: E402
import sheet                                                                 # noqa: E402
from make_maggam_set import petal_rails, leaf_rails                          # noqa: E402

MINT, COPPER = "#3fd6b4", "#b85a2b"
COPPER_SPACING = 0.27
FABRIC, CATEGORY, THREAD = "silk", "blouse_neck", "120"


def R(v): return round(v, 3)


class B:
    """Collects objects; a transform stack (translate / rotate / mirror / scale) lets one motif be placed many times."""
    def __init__(self):
        self.o, self.n, self.T = [], 0, [lambda p: p]

    def id(self, p):
        self.n += 1; return f"{p}{self.n}"

    def tf(self, p):
        for f in reversed(self.T):
            p = f(p)
        return (R(p[0]), R(p[1]))

    def at(self, dx=0.0, dy=0.0, rot=0.0, mirror=False, scale=1.0):
        a = math.radians(rot); c, s = math.cos(a), math.sin(a)

        def f(p):
            x, y = p[0] * scale * (-1 if mirror else 1), p[1] * scale
            return (x * c - y * s + dx, x * s + y * c + dy)
        b = self

        class Ctx:
            def __enter__(self_): b.T.append(f)
            def __exit__(self_, *a): b.T.pop()
        return Ctx()

    def pts(self, v): return [list(self.tf(p)) for p in v]


def col(b, name, color, r1, r2, **params):
    params.setdefault("spacing", COPPER_SPACING if color == COPPER else 0.30)
    b.o.append({"id": b.id("c"), "type": "column", "color": color, "name": name, "rail1": b.pts(r1), "rail2": b.pts(r2), "params": params})


def run(b, name, color, pts, **params):
    b.o.append({"id": b.id("r"), "type": "run", "color": color, "name": name, "points": b.pts(pts), "params": params})


def fill(b, name, color, ring, **params):
    params.setdefault("spacing", COPPER_SPACING if color == COPPER else 0.30)
    b.o.append({"id": b.id("f"), "type": "fill", "color": color, "name": name, "rings": [b.pts(ring)], "params": params})


def ellipse(cx, cy, rx, ry, rot=0.0, n=24):
    c, s = math.cos(rot), math.sin(rot)
    return [(cx + rx * math.cos(2 * math.pi * k / n) * c - ry * math.sin(2 * math.pi * k / n) * s,
             cy + rx * math.cos(2 * math.pi * k / n) * s + ry * math.sin(2 * math.pi * k / n) * c) for k in range(n)]


def ribbon(cl, wfun, n=None):
    """Rails of a column of varying width around the centre line `cl` (points); wfun(t) = full width at t in 0..1."""
    a, c = [], []
    for i, p in enumerate(cl):
        q0, q1 = cl[max(i - 1, 0)], cl[min(i + 1, len(cl) - 1)]
        tx, ty = q1[0] - q0[0], q1[1] - q0[1]; l = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / l, tx / l; h = wfun(i / (len(cl) - 1)) / 2
        a.append((p[0] + nx * h, p[1] + ny * h)); c.append((p[0] - nx * h, p[1] - ny * h))
    return a, c


def bez(p0, p1, p2, p3, n=12):
    out = []
    for k in range(n + 1):
        t = k / n; u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0], u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


# ---------------------------------------------------------------- motifs (local coordinates)
def unit(a): return math.cos(a), math.sin(a)


def daisy(b, cx, cy, R0=9.0, petals=7, rot=0.0, name="Daisy"):
    """Long tapered mint petals (7) around a copper centre with a copper ring on the larger flowers. Every petal runs out on a centre-run underlay and its satin comes back."""
    rin = max(1.8, R0 * 0.26)
    for k in range(petals):
        ang = rot + 2 * math.pi * k / petals
        w = min(R0 * 0.40, 2 * math.pi * (rin + R0 * 0.4) / petals * 0.92)
        a, c = petal_rails(cx, cy, ang, rin + 0.1, R0, w, n=8, tip=0.30)
        col(b, f"{name} petal", MINT, a, c, underlay="center", end_at_start=True)
    fill(b, f"{name} centre", COPPER, ellipse(cx, cy, rin, rin, n=20), underlay="none")
    if R0 >= 8:
        run(b, f"{name} centre ring", COPPER, ellipse(cx, cy, rin + 1.1, rin + 1.1, n=24) + [ellipse(cx, cy, rin + 1.1, rin + 1.1, n=24)[0]], stitch_len=1.8)


def curved_leaf(b, x0, y0, ang, L, W, bend=0.25, color=MINT, name="Leaf"):
    """Comma-shaped leaf: a bent centre line, widest in the first third, both ends meeting in a point."""
    ux, uy = unit(ang); nx, ny = -uy, ux
    cl = bez((x0, y0), (x0 + ux * L * 0.35 + nx * bend * L * 0.55, y0 + uy * L * 0.35 + ny * bend * L * 0.55),
             (x0 + ux * L * 0.75 + nx * bend * L * 0.45, y0 + uy * L * 0.75 + ny * bend * L * 0.45), (x0 + ux * L + nx * bend * L * 0.2, y0 + uy * L + ny * bend * L * 0.2), 10)
    a, c = ribbon(cl, lambda t: W * math.sin(math.pi * min(1.0, t ** 0.8)) ** 0.9)
    a[0] = c[0] = cl[0]; a[-1] = c[-1] = cl[-1]
    col(b, name, color, a, c, underlay="center", end_at_start=True)


def leaf(b, x0, y0, ang, L, W, color=MINT, name="Leaf"):
    a, c = leaf_rails(x0, y0, ang, L, W)
    col(b, name, color, a, c, underlay="center", end_at_start=True)


def sprig(b, x0, y0, ang, L=14.0, pairs=4, name="Copper fern"):
    """Copper fern: stem + pairs of narrow leaflets + tip. Leaflets get shorter towards the tip."""
    ux, uy = unit(ang)
    run(b, f"{name} stem", COPPER, [(x0 + ux * L * t, y0 + uy * L * t) for t in (0, 0.25, 0.5, 0.75, 1.0)], stitch_len=2.0)
    for i in range(pairs):
        t = 0.22 + 0.62 * i / max(1, pairs - 1); px, py = x0 + ux * L * t, y0 + uy * L * t
        ll = L * (0.38 - 0.06 * i)
        for side in (-1, 1):
            leaf(b, px, py, ang + side * math.radians(52), ll, max(1.5, ll * 0.30), COPPER, f"{name} leaflet")
    leaf(b, x0 + ux * L * 0.9, y0 + uy * L * 0.9, ang, L * 0.26, 1.6, COPPER, f"{name} tip")


def bud(b, x0, y0, ang, L=8.0, name="Copper bud"):
    ux, uy = unit(ang)
    run(b, f"{name} stem", COPPER, [(x0, y0), (x0 + ux * L * 0.5, y0 + uy * L * 0.5)], stitch_len=1.8)
    fill(b, name, COPPER, ellipse(x0 + ux * L * 0.78, y0 + uy * L * 0.78, 1.7, L * 0.34, ang + math.pi / 2, 14), underlay="none")


def rosette(b, cx, cy, R0=3.6, name="Copper rosette"):
    """Tiny copper five-lobed flower (five small filled lobes round a centre)."""
    for k in range(5):
        a = 2 * math.pi * k / 5 + 0.3
        fill(b, f"{name} lobe", COPPER, ellipse(cx + math.cos(a) * R0 * 0.62, cy + math.sin(a) * R0 * 0.62, R0 * 0.42, R0 * 0.42, n=12), underlay="none")


def path_len(path): return sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(path, path[1:]))


def path_at(path, s):
    """(point, tangent angle) at arclength s along the polyline."""
    acc = 0.0
    for p, q in zip(path, path[1:]):
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        if acc + d >= s and d > 0:
            t = (s - acc) / d
            return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t), math.atan2(q[1] - p[1], q[0] - p[0])
        acc += d
    p, q = path[-2], path[-1]
    return q, math.atan2(q[1] - p[1], q[0] - p[0])


def garland(b, path, step=32.0, first_side=1, name="Garland"):
    """Continuous floral vine along `path`: wavy mint stem, big daisies alternating sides, curved leaves, copper buds / ferns / rosettes, small mint flowers."""
    total = path_len(path)
    stem = []
    n = int(total / 2.0)
    for k in range(n + 1):
        (px, py), th = path_at(path, min(total, k * total / n)); nx, ny = -math.sin(th), math.cos(th)
        w = 3.2 * math.sin(2 * math.pi * (k * total / n) / 70.0)
        stem.append((px + nx * w, py + ny * w))
    a, c = ribbon(stem, lambda t: 1.6)
    col(b, f"{name} stem", MINT, a, c, underlay="none")
    k, s = 0, step * 0.5
    while s < total - step * 0.35:
        side = first_side * (1 if k % 2 == 0 else -1)
        (px, py), th = path_at(path, s); nx, ny = -math.sin(th), math.cos(th); ux, uy = math.cos(th), math.sin(th)
        R0 = 11.0 if k % 2 == 0 else 9.5
        daisy(b, px + nx * side * (R0 + 2.0), py + ny * side * (R0 + 2.0), R0, rot=0.4 * k, name=f"{name} daisy")
        (qx, qy), _ = path_at(path, min(total, s + step * 0.30))
        curved_leaf(b, qx, qy, th - side * math.radians(50), 15.0, 5.6, bend=0.3 * side, name=f"{name} leaf")
        (rx, ry), _ = path_at(path, min(total, s + step * 0.42))
        sprig(b, rx - nx * side * 2, ry - ny * side * 2, th - side * math.radians(38), 15.0, 4, f"{name} fern")
        bud(b, rx + nx * side * 2, ry + ny * side * 2, th + side * math.radians(42), 8.5, f"{name} bud")
        (tx, ty), _ = path_at(path, min(total, s + step * 0.60))
        daisy(b, tx - nx * side * 13.0, ty - ny * side * 13.0, 3.8, petals=5, rot=0.2 * k, name=f"{name} small flower")
        rosette(b, tx + nx * side * 12.0, ty + ny * side * 12.0, 3.6, f"{name} rosette")
        (vx, vy), _ = path_at(path, min(total, s + step * 0.78))
        curved_leaf(b, vx, vy, th + side * math.radians(55), 11.0, 4.2, bend=-0.3 * side, name=f"{name} small leaf")
        k += 1; s += step


def bird(b, facing=1, name="Bird"):
    """A duck-like bird with a large paisley tail, layered wing, S-neck and a crested head, facing right (+1) or left (-1). ~66 x 66 mm."""
    with b.at(mirror=(facing < 0)):
        base = bez((-31, 14), (-12, 25), (12, 23), (33, 4))
        a, c = ribbon(base, lambda t: 1.0 + 5.4 * math.sin(math.pi * t) ** 0.8)
        col(b, f"{name} swirl", MINT, a, c, underlay="center")
        run(b, f"{name} swirl line 1", COPPER, bez((-29, 18), (-12, 29), (12, 27), (32, 9)), stitch_len=2.2)
        run(b, f"{name} swirl line 2", COPPER, bez((-27, 21), (-12, 33), (12, 31), (31, 12)), stitch_len=2.2)
        tail = bez((-8, 2), (-35, 6), (-38, -21), (-17, -31)) + bez((-17, -31), (-6, -35), (1, -22), (-11, -17))[1:]
        a, c = ribbon(tail, lambda t: 1.5 + 5.0 * math.sin(math.pi * min(1.0, t * 1.05)) ** 0.7 * (1 - 0.3 * t))
        col(b, f"{name} tail", MINT, a, c, underlay="center")
        run(b, f"{name} tail inner line", COPPER, tail[3:-5], stitch_len=2.2)
        fill(b, f"{name} tail drop", COPPER, ellipse(-18, -19, 2.1, 4.4, 0.55, 16), underlay="none")
        fill(b, f"{name} body", MINT, ellipse(2, 4, 14.5, 8.8, -0.10, 30), underlay="tatami")
        for i, dy in enumerate((0, 3.6, 7.2)):                                                     # layered wing feathers
            run(b, f"{name} wing {i + 1}", COPPER, bez((-9 + i, 1 + dy), (-4, -3 + dy), (4, -3 + dy), (10 - i, 1 + dy), 8), stitch_len=2.0)
        neck = bez((11, 0), (19, -4), (15, -13), (18, -21))
        a, c = ribbon(neck, lambda t: 6.0 - 2.6 * t)
        col(b, f"{name} neck", MINT, a, c, underlay="center")
        fill(b, f"{name} head", MINT, ellipse(18.5, -24, 4.6, 4.0, 0, 20), underlay="none")
        fill(b, f"{name} beak", COPPER, [(22.5, -25.2), (28.8, -22.0), (22.8, -21.6)], underlay="none")
        fill(b, f"{name} eye", COPPER, ellipse(19.8, -24.6, 0.9, 0.9, n=10), underlay="none")
        for tip in ((13.0, -36.0), (18.5, -37.5), (24.0, -35.0)):                                  # crest plumes with bead tips
            run(b, f"{name} crest", COPPER, [(18.5 + (tip[0] - 18.5) * 0.3, -27.4), tip], stitch_len=1.6)
            fill(b, f"{name} crest bead", COPPER, ellipse(tip[0], tip[1], 1.0, 1.0, n=10), underlay="none")
        sprig(b, -33, -2, math.radians(205), 14.0, 3, f"{name} tail sprig")


def band_points(path, step):
    out, acc = [path[0]], 0.0
    for p, q in zip(path, path[1:]):
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        while acc + d >= step:
            t = (step - acc) / d; p = (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t); out.append(p); d = math.hypot(q[0] - p[0], q[1] - p[1]); acc = 0.0
        acc += d
    return out


def offset(path, dist):
    out = []
    for i, p in enumerate(path):
        q0, q1 = path[max(i - 1, 0)], path[min(i + 1, len(path) - 1)]
        tx, ty = q1[0] - q0[0], q1[1] - q0[1]; l = math.hypot(tx, ty) or 1.0
        out.append((p[0] - ty / l * dist, p[1] + tx / l * dist))
    return out


def bead_row(b, path, dist, step=2.4, shift=0.0, name="Bead"):
    dots = band_points(offset(path, dist), step)
    for i, p in enumerate(dots):
        q0, q1 = dots[max(i - 1, 0)], dots[min(i + 1, len(dots) - 1)]
        tx, ty = q1[0] - q0[0], q1[1] - q0[1]; l = math.hypot(tx, ty) or 1.0; tx, ty = tx / l, ty / l; nx, ny = -ty, tx
        a = [(p[0] - tx * 0.7 + nx * 0.9, p[1] - ty * 0.7 + ny * 0.9), (p[0] + tx * 0.7 + nx * 0.9, p[1] + ty * 0.7 + ny * 0.9)]
        c = [(p[0] - tx * 0.7 - nx * 0.9, p[1] - ty * 0.7 - ny * 0.9), (p[0] + tx * 0.7 - nx * 0.9, p[1] + ty * 0.7 - ny * 0.9)]
        col(b, f"{name} dot", COPPER, a, c, underlay="none")


def neck_band(b, path, name="Neck band"):
    """6 mm mint satin band; copper line inside; outside: copper line, two staggered rows of copper bead dots, copper line."""
    b.o.append({"id": b.id("s"), "type": "satin", "color": MINT, "name": f"{name} mint satin", "points": b.pts(path), "params": {"width": 6.0, "spacing": 0.30}})
    run(b, f"{name} inner line", COPPER, offset(path, -4.2), stitch_len=2.2)
    run(b, f"{name} outer line 1", COPPER, offset(path, 4.2), stitch_len=2.2)
    bead_row(b, path, 6.4, name=f"{name} bead row 1")
    bead_row(b, path, 8.9, name=f"{name} bead row 2")
    run(b, f"{name} outer line 2", COPPER, offset(path, 11.1), stitch_len=2.2)


def u_path(half_w=80.0, side=175.0, step=2.0):
    left = [(-half_w, -side + k * step) for k in range(int(side / step))]
    arc = [(half_w * math.cos(math.pi - math.pi * k / 48), half_w * math.sin(math.pi - math.pi * k / 48)) for k in range(49)]
    right = [(half_w, (k + 1) * -step) for k in range(int(side / step))]
    return left + arc + right


def ordered(b):
    """All mint first (it lies under / beside the copper), then copper: one colour change. Creation order is kept inside each colour."""
    return sorted(b.o, key=lambda o: 0 if o["color"] == MINT else 1)


# ---------------------------------------------------------------- designs
def D(name, b, w, h):
    return {"name": name, "hoop": {"w": w, "h": h, "margin": 8}, "objects": ordered(b)}


def daisy_large():
    b = B(); daisy(b, 0, 0, 11.0, name="Large daisy"); return D("blue_daisy_large", b, 100, 100)


def daisy_small():
    b = B(); daisy(b, 0, 0, 5.2, petals=6, name="Small daisy"); return D("blue_daisy_small", b, 100, 100)


def copper_sprig():
    b = B(); sprig(b, 0, 18, math.radians(-90), 34.0, 5); return D("blue_copper_sprig", b, 100, 100)


def vine():
    b = B(); garland(b, [(0.0, -62.0 + k * 2.0) for k in range(63)], step=34.0); return D("blue_floral_vine_spray", b, 150, 190)


def daisy_scatter():
    b = B()
    for i, (x, y, r) in enumerate(((-60, -45, 7.5), (0, -45, 7.5), (60, -45, 7.5), (-30, 0, 7.5), (30, 0, 7.5), (-60, 45, 7.5), (0, 45, 7.5), (60, 45, 7.5))):
        daisy(b, x, y, r, rot=0.35 * i, name=f"Scatter daisy {i + 1}")
    return D("blue_daisy_scatter_set", b, 200, 160)


def bird_single():
    b = B(); bird(b, 1); return D("blue_peacock_single", b, 120, 120)


def bird_pair_into(b):
    with b.at(-38, 0): bird(b, 1, "Left bird")
    with b.at(38, 0): bird(b, -1, "Right bird")
    daisy(b, 0, -4, 8.5, name="Centre daisy")
    daisy(b, -13, -19, 3.6, petals=5, name="Centre small flower L"); daisy(b, 13, -19, 3.6, petals=5, name="Centre small flower R")
    sprig(b, -3, 24, math.radians(-118), 16.0, 4, "Base fern L"); sprig(b, 3, 24, math.radians(-62), 16.0, 4, "Base fern R")
    rosette(b, 0, 12, 3.4, "Centre rosette")


def bird_pair():
    b = B(); bird_pair_into(b); return D("blue_peacock_pair", b, 200, 130)


def neck_border():
    b = B(); neck_band(b, [(-80 + k * 2.0, 0.0) for k in range(81)]); return D("blue_neck_border_band", b, 220, 80)


def front_neck():
    b = B()
    path = u_path()
    neck_band(b, path)
    outer = offset(path, 34.0)
    left_len = 175.0 + math.pi * 80.0 * 0.58                                  # down the side and round ~58 % of the curve, then the birds take over
    left = []
    acc = 0.0
    for p, q in zip(outer, outer[1:]):
        left.append(p); acc += math.hypot(q[0] - p[0], q[1] - p[1])
        if acc > left_len: break
    garland(b, left, step=34.0, name="Left garland")
    with b.at(mirror=True): garland(b, left, step=34.0, name="Right garland")
    with b.at(0, 160): bird_pair_into(b)
    for i, (x, y, r) in enumerate(((-150, -60, 7.5), (150, -60, 7.5), (-152, 50, 7.5), (152, 50, 7.5), (-120, 190, 7.5), (120, 190, 7.5), (-60, 232, 7.5), (60, 232, 7.5), (0, 248, 7.5))):
        daisy(b, x, y, r, rot=0.3 * i, name=f"Body daisy {i + 1}")
    return D("blue_front_neck_full", b, 360, 480)


# ---------------------------------------------------------------- pipeline
def finish(d):
    d = dict(d, thread=THREAD, stabiliser="cut-away")
    d, log = profiles.apply_profile(d, FABRIC, CATEGORY)
    d, l2 = placements.autofix(d)
    d, l3 = sequence.optimize_sequence(d)
    return d, log + l2 + l3


def write(d, out: Path, log):
    out.mkdir(parents=True, exist_ok=True)
    cl = checklist.evaluate(d)
    data, err = sheet.package(d)
    if err:
        raise SystemExit(f"{d['name']}: {err}")
    z = zipfile.ZipFile(io.BytesIO(data))
    for n in z.namelist():
        (out / n).write_bytes(z.read(n))
    (out / f"{d['name']}.checklist.json").write_text(json.dumps({"log": log, **cl}, indent=1))
    st = cl["stats"]
    print(f"{d['name']:26} {st['stitches']:6} st  {st['color_changes'] + 1} col  {st['trims']:3} trims  {st['width_mm']} x {st['height_mm']} mm  ~{st['est_minutes']} min  "
          f"checklist {cl['passed']}/15 {'EXPORT OK' if cl['export_allowed'] else 'BLOCKED'}  " + ", ".join(f"#{i['n']} {i['level']}" for i in cl["items"] if i["level"] not in ("PASS", "N/A")))
    return cl


def cli(argv):
    out = Path(argv[0]) if argv else ROOT / "designs" / "blue_set"
    ok = True
    for make in (daisy_large, daisy_small, daisy_scatter, copper_sprig, vine, bird_pair, neck_border, front_neck):
        d, log = finish(make())
        ok &= bool(write(d, out, log)["export_allowed"])
    d, log = finish(bird_single())
    z, rep = sheet.placement_set(d, [{"id": "left"}, {"id": "right"}], "left")
    zf = zipfile.ZipFile(io.BytesIO(z))
    for n in zf.namelist():
        if n != "MANIFEST.txt":
            (out / n).write_bytes(zf.read(n))
    for r in rep["placements"]:
        print(f"{r['file'][:-4]:26} {r.get('stitches', 0):6} st  {r['status']} {r.get('grade', '')}  (mirror pair)")
        ok &= r["status"] == "ok"
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
