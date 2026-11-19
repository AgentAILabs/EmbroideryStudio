"""Maggam blouse set - original designs in the traditional style of the reference photos (gold satin flowers with kundan-stone
centres, red fern sprays, scalloped gold neckline). Hand-digitized as vector objects, NOT traced from the photos.

    python3 tools/make_maggam_set.py [out_dir]          default: designs/maggam_set/

Files (each with .esproj, preview, production sheet, colour CSV, verification report):
  maggam_test_motif.dst        ~55 x 45 mm   - STITCH THIS FIRST (fits any 100 x 100 hoop)
  maggam_front_neck.dst        ~210 x 235 mm - needs a large frame (>= 240 x 260 mm)
  maggam_back_neck.dst         ~200 x 110 mm - half medallion above a scalloped border
  maggam_sleeve_left/right.dst ~115 x 50 mm  - spray, true mirror pair
Stones / kundan are NOT stitched: they are placeholders listed with positions on the production sheet (fixed by hand afterwards).
Starting values for silk + fine thread; gold (metallic / zari-look) objects are kept more open (0.35 mm) than red. Test first.
Units mm, y down, origin = design centre."""
import copy, json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine.design import generate, run_checks                 # noqa: E402
from stitchcraft_engine import profiles, sequence, placements, checklist  # noqa: E402
import sheet                                                                 # noqa: E402

GOLD, RED = "#c9a227", "#d0102c"
GOLD_SPACING = 0.35          # metallic-look gold: more open than the red, fewer thread breaks
FABRIC, CATEGORY, THREAD = "silk", "blouse_neck", "120"


class B:
    """Small builder: collects objects, unique ids, stone positions."""
    def __init__(self):
        self.o, self.n, self.stones, self.small_stones = [], 0, [], []

    def id(self, p):
        self.n += 1; return f"{p}{self.n}"

    def add(self, ob):
        self.o.append(ob); return ob


def R(v): return round(v, 3)


def col(b, name, color, r1, r2, **params):
    return b.add({"id": b.id("c"), "type": "column", "color": color, "name": name, "rail1": [[R(x), R(y)] for x, y in r1],
                  "rail2": [[R(x), R(y)] for x, y in r2], "params": params})


def run(b, name, color, pts, **params):
    return b.add({"id": b.id("r"), "type": "run", "color": color, "name": name, "points": [[R(x), R(y)] for x, y in pts], "params": params})


# ---------------------------------------------------------------- motifs
def petal_rails(cx, cy, ang, r0, r1, w, n=7, tip=0.45):
    """Radial petal: from r0 to r1 along angle `ang`, half-width swelling to w/2, blunt (rounded-looking) at both ends."""
    ux, uy, nx, ny = math.cos(ang), math.sin(ang), -math.sin(ang), math.cos(ang)
    a, c = [], []
    for k in range(n):
        t = k / (n - 1); r = r0 + (r1 - r0) * t
        h = w / 2 * (tip + (1 - tip) * math.sin(math.pi * t))
        x, y = cx + ux * r, cy + uy * r
        a.append((x + nx * h, y + ny * h)); c.append((x - nx * h, y - ny * h))
    return a, c


def gold_flower(b, cx, cy, R0=9.0, petals=12, name="Gold flower"):
    """Chrysanthemum-style gold flower: radial satin petals around a satin ring; stone in the centre."""
    rin = 3.9
    for k in range(petals):
        ang = 2 * math.pi * k / petals + 0.13
        w = min(3.2, 2 * math.pi * (rin + R0) / 2 / petals * 0.92)
        a, c = petal_rails(cx, cy, ang, rin + 0.2, R0, w)
        col(b, f"{name} petal", GOLD, a, c, spacing=GOLD_SPACING, underlay="center", end_at_start=True)      # out along the centre run, satin back to the ring
    ring_o = [(cx + rin * math.cos(t / 24 * 2 * math.pi), cy + rin * math.sin(t / 24 * 2 * math.pi)) for t in range(25)]
    ring_i = [(cx + 2.5 * math.cos(t / 24 * 2 * math.pi), cy + 2.5 * math.sin(t / 24 * 2 * math.pi)) for t in range(25)]
    col(b, f"{name} ring", GOLD, ring_o, ring_i, spacing=GOLD_SPACING, underlay="none")
    b.stones.append([R(cx), R(cy)])


def small_flower(b, cx, cy, R0=4.6, petals=6, name="Small gold flower", rot=0.0):
    for k in range(petals):
        ang = 2 * math.pi * k / petals + rot
        a, c = petal_rails(cx, cy, ang, 1.7, R0, 2.3, n=5, tip=0.5)
        col(b, f"{name} petal", GOLD, a, c, spacing=GOLD_SPACING, underlay="center", end_at_start=True)      # centre run out, satin back: ends at the centre
    b.small_stones.append([R(cx), R(cy)])


def leaf_rails(x0, y0, ang, L, W, n=9):
    """Pointed leaf from its base along `ang`: both ends meet in a point."""
    ux, uy, nx, ny = math.cos(ang), math.sin(ang), -math.sin(ang), math.cos(ang)
    a, c = [], []
    for k in range(n):
        t = k / (n - 1); h = W / 2 * math.sin(math.pi * t) ** 0.75
        x, y = x0 + ux * L * t, y0 + uy * L * t
        a.append((x + nx * h, y + ny * h)); c.append((x - nx * h, y - ny * h))
    a[0] = c[0] = (x0, y0); a[-1] = c[-1] = (x0 + ux * L, y0 + uy * L)
    return a, c


def fern(b, x0, y0, ang, L=16.0, name="Red fern", pairs=3, curve=0.0):
    """Red fern sprig: a short stem (running stitch) with pairs of pointed satin leaflets and a tip leaflet."""
    pts = []
    for k in range(9):
        t = k / 8; a = ang + curve * (t - 0.5)
        pts.append((x0 + math.cos(ang) * L * t + math.cos(a + math.pi / 2) * curve * 2 * t * t,
                    y0 + math.sin(ang) * L * t + math.sin(a + math.pi / 2) * curve * 2 * t * t))
    # One continuous thread: start at the stem top, tip leaflet (out on its underlay, satin back), then stem segment down to the
    # next pair, both leaflets (each returns to the stem), ... and the last stem segment ends at the base. No jump inside a fern.
    tx, ty = pts[6]
    a, c = leaf_rails(tx, ty, ang, L * 0.36, max(2.2, L * 0.13))
    col(b, f"{name} tip", RED, a, c, underlay="center", end_at_start=True)
    cur = 6
    for i in reversed(range(pairs)):
        t = 0.28 + 0.22 * i
        k = min(len(pts) - 1, int(round(t * 8)))
        run(b, f"{name} stem", RED, pts[k:cur + 1][::-1], stitch_len=2.0)
        cur = k
        px, py = pts[k]
        ll = L * (0.42 - 0.07 * i); ww = max(2.0, ll * 0.36)
        for side in (-1, 1):
            a, c = leaf_rails(px, py, ang + side * math.radians(52), ll, ww)
            col(b, f"{name} leaflet", RED, a, c, underlay="center", end_at_start=True)
    run(b, f"{name} stem", RED, pts[:cur + 1][::-1], stitch_len=2.0)


def scallop_band(b, path, width=2.2, period=13.0, amp=2.6, inward=+1, name="Gold scalloped line"):
    """Gold satin band following `path` with scallops (arcs between cusps) bulging to the `inward` side."""
    dense = resample(path, 0.5)
    s = [0.0]
    for p, q in zip(dense, dense[1:]):
        s.append(s[-1] + math.dist(p, q))
    a, c = [], []
    for i, p in enumerate(dense):
        q0, q1 = dense[max(i - 1, 0)], dense[min(i + 1, len(dense) - 1)]
        tx, ty = q1[0] - q0[0], q1[1] - q0[1]; l = math.hypot(tx, ty) or 1
        nx, ny = -ty / l * inward, tx / l * inward
        off = amp * math.sin(math.pi * ((s[i] % period) / period))
        cx, cy = p[0] + nx * off, p[1] + ny * off
        a.append((cx + nx * width / 2, cy + ny * width / 2)); c.append((cx - nx * width / 2, cy - ny * width / 2))
    # split into pieces of ~45 mm so no column is absurdly long (cleaner sequencing, smaller trims on a break)
    step = max(2, int(45 / 0.5))
    for k in range(0, len(a) - 1, step):
        col(b, name, GOLD, a[k:k + step + 1], c[k:k + step + 1], spacing=GOLD_SPACING, underlay="center", shorten=True)


def resample(path, step):
    out = [tuple(path[0])]
    for p, q in zip(path, path[1:]):
        d = math.dist(p, q); n = max(1, int(d / step))
        for k in range(1, n + 1):
            out.append((p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n))
    return out


def along(path, s_target):
    """Point and unit normal (pointing to the left of travel) at arc length s on a polyline."""
    acc = 0.0
    for p, q in zip(path, path[1:]):
        d = math.dist(p, q)
        if acc + d >= s_target and d > 0:
            t = (s_target - acc) / d; tx, ty = (q[0] - p[0]) / d, (q[1] - p[1]) / d
            return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t), (-ty, tx)
        acc += d
    p, q = path[-2], path[-1]; d = math.dist(p, q); return q, (-(q[1] - p[1]) / d, (q[0] - p[0]) / d)


def plength(path): return sum(math.dist(p, q) for p, q in zip(path, path[1:]))


def stones(b, name="Kundan stones (flower centres)", small="Small stones"):
    if b.stones:
        b.add({"id": b.id("emb"), "type": "embellishment", "kind": "stone", "color": "#f5f5f5", "size_mm": 5.0, "name": name, "points": b.stones})
    if b.small_stones:
        b.add({"id": b.id("emb"), "type": "embellishment", "kind": "stone", "color": "#f5f5f5", "size_mm": 3.0, "name": small, "points": b.small_stones})


def ordered(b):
    """Red first (leaves lie under / beside the gold), then gold; placeholders last."""
    key = {RED: 0, GOLD: 1}
    return sorted(b.o, key=lambda o: (2 if o["type"] == "embellishment" else key.get(o.get("color"), 1)))


# ---------------------------------------------------------------- designs
def test_motif():
    b = B()
    fern(b, -6, 2, math.radians(200), 15, "Fern left")
    fern(b, 6, 2, math.radians(-20), 15, "Fern right")
    fern(b, 0, -6, math.radians(-90), 13, "Fern top", pairs=2)
    gold_flower(b, 0, 4, 9.0, name="Test flower")
    small_flower(b, -17, -9); small_flower(b, 17, -9)
    stones(b)
    return {"name": "maggam_test_motif", "hoop": {"w": 100, "h": 100, "margin": 5}, "objects": ordered(b)}


def neck_path(half_w=62.0, top=-120.0, r=62.0):
    """U-shaped front neckline: straight sides from the shoulders, round bottom (y down)."""
    left = [(-half_w, top + k * (abs(top) / 12)) for k in range(13)]                     # down to y=0
    arc = [(-r * math.cos(math.pi * k / 36), r * math.sin(math.pi * k / 36)) for k in range(1, 36)]
    right = [(half_w, -k * (abs(top) / 12)) for k in range(13)]
    return left + arc + right


def mirror_objects(objs, b, suffix=" (R)"):
    """True left-right mirror copies (x -> -x; fill angles mirrored), with new ids - for symmetric necklines."""
    out = []
    for o in copy.deepcopy(objs):
        o["id"] = b.id("m"); o["name"] = (o.get("name") or "") + suffix
        for k in ("points", "rail1", "rail2"):
            if k in o:
                o[k] = [[R(-x), R(y)] for x, y in o[k]]
        if "rings" in o:
            o["rings"] = [[[R(-x), R(y)] for x, y in r] for r in o["rings"]]
        out.append(o)
    return out


def front_neck():
    b = B()
    path = neck_path()
    L = plength(path)
    half = L / 2
    period = half / round(half / 15.0)                     # whole scallops per half: the two sides meet symmetrically at the centre
    scallop_band(b, path, inward=-1, period=period, amp=3.2, width=2.2, name="Neckline (gold scallops)")
    # motifs on the LEFT half only (shoulder -> centre), then an exact mirror for the right half, plus one centre flower
    left = B(); left.n = 1000
    k, s = 0, 9.0
    while s < half - 9:
        (px, py), (nx, ny) = along(path, s)
        out = (nx, ny)                                     # left of travel = away from the neck opening
        ang = math.atan2(out[1], out[0])
        if k % 2 == 0:
            gold_flower(left, px + out[0] * 13, py + out[1] * 13, 8.5, name=f"Neck flower {k // 2 + 1}")
            small_flower(left, px + out[0] * 33, py + out[1] * 33, 4.2, name=f"Outer small flower {k // 2 + 1}", rot=0.3)
        else:
            bx, by = px + out[0] * 7, py + out[1] * 7
            fern(left, bx, by, ang - 0.45, 17, f"Neck fern {k}a")
            fern(left, bx, by, ang + 0.45, 17, f"Neck fern {k}b")
        k += 1; s += 15.5
    (px, py), (nx, ny) = along(path, half)
    gold_flower(b, px + nx * 13, py + ny * 13, 9.5, petals=14, name="Centre flower")
    small_flower(b, px + nx * 33, py + ny * 33, 4.6, name="Centre small flower")
    b.o += left.o + mirror_objects(left.o, b)
    b.stones += left.stones + [[-x, y] for x, y in left.stones]
    b.small_stones += left.small_stones + [[-x, y] for x, y in left.small_stones]
    stones(b)
    return {"name": "maggam_front_neck", "hoop": {"w": 300, "h": 360, "margin": 10}, "objects": ordered(b)}


def back_neck():
    b = B()
    base = [(-92 + k * 4, 0.0) for k in range(47)]
    scallop_band(b, base, inward=+1, name="Border line (gold scallops)", period=14.0)
    gold_flower(b, 0, -40, 12.0, petals=14, name="Centre flower")
    for i, deg in enumerate((198, 234, 270, 306, 342)):
        a = math.radians(deg)
        if deg == 270:
            continue
        gold_flower(b, 64 * math.cos(a), -6 + 64 * math.sin(a) * 0.95, 10.0, name=f"Arc flower {i + 1}")
    for i, deg in enumerate(range(195, 346, 30)):
        a = math.radians(deg); small_flower(b, 40 * math.cos(a), -40 + 26 * math.sin(a) + 18, 4.6, name=f"Inner small flower {i + 1}")
    for deg in range(186, 356, 17):
        a = math.radians(deg); x0, y0 = 82 * math.cos(a), -6 + 82 * math.sin(a) * 0.95
        if y0 > -8:
            continue
        fern(b, x0, y0, a, 15, f"Rim fern {deg}")
    for x in range(-80, 81, 32):
        fern(b, x - 7, -5, math.radians(-115), 13, f"Base fern {x}a", pairs=2)
        fern(b, x + 7, -5, math.radians(-65), 13, f"Base fern {x}b", pairs=2)
        small_flower(b, x + 16, -9, 4.2, name=f"Base small flower {x}")
    for deg in (225, 255, 285, 315):
        a = math.radians(deg); fern(b, -0 + 22 * math.cos(a), -40 + 22 * math.sin(a), a, 12, f"Centre fern {deg}", pairs=2)
    stones(b)
    return {"name": "maggam_back_neck", "hoop": {"w": 300, "h": 200, "margin": 10}, "objects": ordered(b)}


def sleeve_spray():
    b = B()
    stem = [(-52 + 104 * t, 12 - 24 * t + 14 * math.sin(math.pi * t)) for t in [k / 20 for k in range(21)]]
    sa, sc = [], []
    for i, p in enumerate(stem):
        q0, q1 = stem[max(i - 1, 0)], stem[min(i + 1, len(stem) - 1)]
        tx, ty = q1[0] - q0[0], q1[1] - q0[1]; l = math.hypot(tx, ty); nx, ny = -ty / l, tx / l
        sa.append((p[0] + nx * 0.8, p[1] + ny * 0.8)); sc.append((p[0] - nx * 0.8, p[1] - ny * 0.8))
    col(b, "Gold stem", GOLD, sa, sc, spacing=GOLD_SPACING, underlay="none", shorten=True)
    for t, rr in ((0.2, 6.5), (0.5, 7.5), (0.8, 6.5)):
        (px, py), _ = along(stem, plength(stem) * t)
        gold_flower(b, px, py - 1, rr, petals=10, name=f"Spray flower {t}")
    for t, deg in ((0.08, -150), (0.33, -115), (0.36, -70), (0.62, -110), (0.66, -60), (0.92, -40)):
        (px, py), _ = along(stem, plength(stem) * t)
        fern(b, px, py - 2, math.radians(deg), 15, f"Spray fern {t}")
    small_flower(b, -46, -10, 3.8); small_flower(b, 30, -26, 3.8)
    stones(b)
    return {"name": "maggam_sleeve", "hoop": {"w": 130, "h": 180, "margin": 5}, "objects": ordered(b)}


# ---------------------------------------------------------------- pipeline: profile -> auto-fix -> sequence -> checks
def finish(d):
    d = dict(d, thread=THREAD, stabiliser="cut-away")
    d, log = profiles.apply_profile(d, FABRIC, CATEGORY)            # object-specific values (gold spacing, underlay=none) are kept
    d, l2 = placements.autofix(d)
    d, l3 = sequence.optimize_sequence(d)
    return d, log + l2 + l3


def write(d, out: Path, log):
    out.mkdir(parents=True, exist_ok=True)
    cl = checklist.evaluate(d)
    data, err = sheet.package(d)
    if err:
        raise SystemExit(f"{d['name']}: {err}")
    import zipfile, io
    z = zipfile.ZipFile(io.BytesIO(data))
    for n in z.namelist():
        (out / n).write_bytes(z.read(n))
    (out / f"{d['name']}.checklist.json").write_text(json.dumps({"log": log, **cl}, indent=1))
    st = cl["stats"]
    print(f"{d['name']:24} {st['stitches']:6} st  {st['color_changes'] + 1} col  {st['trims']:3} trims  {st['width_mm']} x {st['height_mm']} mm  ~{st['est_minutes']} min  "
          f"checklist {cl['passed']}/15 {'EXPORT OK' if cl['export_allowed'] else 'BLOCKED'}  " + ", ".join(f"#{i['n']} {i['level']}" for i in cl["items"] if i["level"] not in ("PASS", "N/A")))
    return cl


def cli(argv):
    out = Path(argv[0]) if argv else ROOT / "designs" / "maggam_set"
    results = {}
    for make in (test_motif, front_neck, back_neck):
        d, log = finish(make())
        results[d["name"]] = write(d, out, log)
    d, log = finish(sleeve_spray())
    z, rep = sheet.placement_set(d, [{"id": "left"}, {"id": "right"}], "left")
    import zipfile, io
    zf = zipfile.ZipFile(io.BytesIO(z))
    for n in zf.namelist():
        if n not in ("MANIFEST.txt",):
            (out / n).write_bytes(zf.read(n))
    for r in rep["placements"]:
        print(f"{r['file'][:-4]:24} {r.get('stitches', 0):6} st  {r['status']} {r.get('grade', '')}  (true mirror pair)")
    return 0 if all(c["export_allowed"] for c in results.values()) and all(r["status"] == "ok" for r in rep["placements"]) else 2


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
