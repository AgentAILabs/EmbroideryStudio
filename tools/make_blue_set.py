"""Blue maggam blouse set - ORIGINAL designs in the style of the reference photos (royal-blue silk, mint-green and copper thread):
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
def daisy(b, cx, cy, R0=9.0, petals=6, rot=0.0, name="Daisy"):
    """Six wide mint satin petals around a copper centre; every petal runs out on a centre-run underlay and its satin comes back."""
    rin = 2.4
    for k in range(petals):
        ang = rot + 2 * math.pi * k / petals
        w = min(R0 * 0.52, 2 * math.pi * (rin + R0) / 2 / petals * 0.95)
        a, c = petal_rails(cx, cy, ang, rin + 0.1, R0, w, n=7, tip=0.55)
        col(b, f"{name} petal", MINT, a, c, underlay="center", end_at_start=True)
    fill(b, f"{name} centre", COPPER, ellipse(cx, cy, max(1.5, R0 * 0.27), max(1.5, R0 * 0.27), n=20), underlay="none")


def leaf(b, x0, y0, ang, L, W, color=MINT, name="Leaf"):
    a, c = leaf_rails(x0, y0, ang, L, W)
    col(b, name, color, a, c, underlay="center", end_at_start=True)


def sprig(b, x0, y0, ang, L=14.0, pairs=3, name="Copper sprig"):
    """Copper fern-like sprig: stem + pairs of narrow leaflets + tip."""
    ux, uy = math.cos(ang), math.sin(ang)
    run(b, f"{name} stem", COPPER, [(x0 + ux * L * t, y0 + uy * L * t) for t in (0, 0.25, 0.5, 0.75, 1.0)], stitch_len=2.0)
    for i in range(pairs):
        t = 0.3 + 0.5 * i / max(1, pairs - 1); px, py = x0 + ux * L * t, y0 + uy * L * t
        for side in (-1, 1):
            leaf(b, px, py, ang + side * math.radians(50), L * 0.34, max(1.6, L * 0.11), COPPER, f"{name} leaflet")
    leaf(b, x0 + ux * L * 0.9, y0 + uy * L * 0.9, ang, L * 0.3, 1.8, COPPER, f"{name} tip")


def bud(b, x0, y0, ang, L=6.0, name="Copper bud"):
    ux, uy = math.cos(ang), math.sin(ang)
    run(b, f"{name} stem", COPPER, [(x0, y0), (x0 + ux * L * 0.5, y0 + uy * L * 0.5)], stitch_len=1.8)
    fill(b, name, COPPER, ellipse(x0 + ux * L * 0.78, y0 + uy * L * 0.78, 1.5, L * 0.32, ang + math.pi / 2, 14), underlay="none")


def vine_spray(b, L=110.0, flip=False):
    """Vertical floral vine: wavy mint stem, daisies alternating left / right, mint leaves, copper buds and sprigs."""
    s = -1 if flip else 1
    stem = [(s * 5.0 * math.sin(2 * math.pi * 1.25 * t), -L / 2 + L * t) for t in [k / 24 for k in range(25)]]
    a, c = ribbon(stem, lambda t: 1.5)
    col(b, "Vine stem", MINT, a, c, underlay="none")

    def pos(t):
        i = min(len(stem) - 1, int(t * (len(stem) - 1))); return stem[i]
    for k, (t, R0) in enumerate(((0.10, 7.5), (0.34, 8.5), (0.58, 7.8), (0.82, 8.5))):
        px, py = pos(t); side = -1 if k % 2 == 0 else 1
        daisy(b, px + side * 9.0, py, R0, rot=0.3 * k, name=f"Vine daisy {k + 1}")
    for k, t in enumerate((0.05, 0.22, 0.46, 0.70, 0.93)):
        px, py = pos(t); side = 1 if k % 2 == 0 else -1
        leaf(b, px, py, math.radians(-90 + side * 55), 11.0, 4.2, MINT, f"Vine leaf {k + 1}")
    for k, t in enumerate((0.16, 0.40, 0.64, 0.88)):
        px, py = pos(t); side = 1 if k % 2 == 0 else -1
        sprig(b, px + side * 2, py, math.radians(-90 + side * 38), 13.0, 3, f"Vine sprig {k + 1}")
        bud(b, px - side * 3, py + 3, math.radians(-90 - side * 30), 6.0, f"Vine bud {k + 1}")


def bird(b, facing=1, name="Bird"):
    """A bird with a curled paisley tail, facing right (+1) or left (-1). ~48 x 46 mm."""
    with b.at(mirror=(facing < 0)):
        # swirl base under the bird (mint) with a copper outline line
        cl = bez((-24, 10), (-10, 18), (10, 17), (26, 4))
        a, c = ribbon(cl, lambda t: 1.0 + 4.2 * math.sin(math.pi * t) ** 0.8)
        col(b, f"{name} swirl", MINT, a, c, underlay="center")
        run(b, f"{name} swirl line", COPPER, [(x, y + 5.6) for x, y in bez((-22, 12), (-8, 20), (10, 19), (25, 7))], stitch_len=2.2)
        # tail: big paisley curl up and back
        tail = bez((-5, 3), (-24, 4), (-26, -16), (-12, -22)) + bez((-12, -22), (-5, -25), (-2, -17), (-9, -14))[1:]
        a, c = ribbon(tail, lambda t: 1.2 + 5.5 * math.sin(math.pi * min(1.0, t * 1.05)) ** 0.7 * (1 - 0.35 * t))
        col(b, f"{name} tail", MINT, a, c, underlay="center")
        fill(b, f"{name} tail eye", COPPER, ellipse(-15, -13, 1.9, 3.4, 0.5, 16), underlay="none")
        # body, neck, head
        fill(b, f"{name} body", MINT, ellipse(2, 3, 11.5, 6.8, -0.12, 28), underlay="tatami")
        neck = bez((7, 0), (12, -4), (11, -10), (12, -16))
        a, c = ribbon(neck, lambda t: 5.2 - 2.2 * t)
        col(b, f"{name} neck", MINT, a, c, underlay="center")
        fill(b, f"{name} head", MINT, ellipse(12.5, -18.5, 3.4, 3.1, 0, 18), underlay="none")
        fill(b, f"{name} beak", COPPER, [(15.4, -19.6), (20.0, -17.0), (15.6, -16.6)], underlay="none")
        for dx, dy in ((10.5, -27), (13.0, -28.5), (15.5, -26.5)):                    # crest
            run(b, f"{name} crest", COPPER, [(12.5 + (dx - 12.5) * 0.35, -21.4), (dx, dy)], stitch_len=1.6)
        # wing lines
        run(b, f"{name} wing 1", COPPER, bez((-6, 1), (-2, -3), (4, -3), (9, 1), 8), stitch_len=2.0)
        run(b, f"{name} wing 2", COPPER, bez((-5, 5), (-1, 1), (4, 1), (8, 5), 8), stitch_len=2.0)


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


def neck_band(b, path, name="Neck band"):
    """Mint satin band with a row of copper bead dots on its outer side and thin copper lines either side."""
    b.o.append({"id": b.id("s"), "type": "satin", "color": MINT, "name": f"{name} mint satin", "points": b.pts(path), "params": {"width": 3.2, "spacing": 0.30}})
    run(b, f"{name} inner line", COPPER, offset(path, -2.6), stitch_len=2.2)
    run(b, f"{name} outer line", COPPER, offset(path, 2.6), stitch_len=2.2)
    dots = band_points(offset(path, 4.6), 2.8)
    for i, p in enumerate(dots):
        q0, q1 = dots[max(i - 1, 0)], dots[min(i + 1, len(dots) - 1)]
        tx, ty = q1[0] - q0[0], q1[1] - q0[1]; l = math.hypot(tx, ty) or 1.0; tx, ty = tx / l, ty / l; nx, ny = -ty, tx
        a = [(p[0] - tx * 0.8 + nx * 0.8, p[1] - ty * 0.8 + ny * 0.8), (p[0] + tx * 0.8 + nx * 0.8, p[1] + ty * 0.8 + ny * 0.8)]
        c = [(p[0] - tx * 0.8 - nx * 0.8, p[1] - ty * 0.8 - ny * 0.8), (p[0] + tx * 0.8 - nx * 0.8, p[1] + ty * 0.8 - ny * 0.8)]
        col(b, f"{name} bead dot", COPPER, a, c, underlay="none")


def u_path(half_w=65.0, side=70.0, step=2.0):
    left = [(-half_w, -side + k * step) for k in range(int(side / step))]
    arc = [(half_w * math.cos(math.pi - math.pi * k / 40), half_w * math.sin(math.pi - math.pi * k / 40)) for k in range(41)]
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
    b = B(); daisy(b, 0, 0, 5.2, name="Small daisy"); return D("blue_daisy_small", b, 100, 100)


def copper_sprig():
    b = B(); sprig(b, 0, 14, math.radians(-90), 28.0, 4); return D("blue_copper_sprig", b, 100, 100)


def vine():
    b = B(); vine_spray(b, 110.0); return D("blue_floral_vine_spray", b, 130, 160)


def bird_single():
    b = B(); bird(b, 1); return D("blue_peacock_single", b, 100, 100)


def bird_pair():
    b = B()
    with b.at(-25, 0): bird(b, 1, "Left bird")
    with b.at(25, 0): bird(b, -1, "Right bird")
    daisy(b, 0, -3, 7.5, name="Centre daisy")
    sprig(b, -6, 24, math.radians(-110), 12.0, 3, "Base sprig L"); sprig(b, 6, 24, math.radians(-70), 12.0, 3, "Base sprig R")
    return D("blue_peacock_pair", b, 130, 100)


def neck_border():
    b = B(); neck_band(b, [(-70 + k * 2.0, 0.0) for k in range(71)]); return D("blue_neck_border_band", b, 200, 60)


def front_neck():
    b = B()
    neck_band(b, u_path())
    with b.at(-97, -10): vine_spray(b, 100.0)
    with b.at(97, -10): vine_spray(b, 100.0, flip=True)
    for sgn in (-1, 1):
        with b.at(sgn * 80, 66, rot=sgn * -62): vine_spray(b, 58.0, flip=(sgn > 0))
    with b.at(0, 122):
        with b.at(-25, 0): bird(b, 1, "Left bird")
        with b.at(25, 0): bird(b, -1, "Right bird")
        daisy(b, 0, -3, 7.5, name="Centre daisy")
    for x, y, r in ((-122, 40, 4.8), (122, 40, 4.8), (-70, 150, 5.2), (70, 150, 5.2), (-112, 100, 4.8), (112, 100, 4.8)):
        daisy(b, x, y, r, name="Scatter daisy")
    return D("blue_front_neck_full", b, 300, 300)


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
    for make in (daisy_large, daisy_small, copper_sprig, vine, bird_pair, neck_border, front_neck):
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
