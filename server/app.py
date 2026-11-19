"""EmbroideryStudio API + static host (stdlib only).  python3 server/app.py [port]
POST /api/generate        design JSON -> stitches, stats, issues
POST /api/export/dst      design JSON -> .dst  (blocked on validation errors)
POST /api/export/exp      EXPERIMENTAL, disabled unless ES_EXPERIMENTAL_FORMATS=1 (DST is the only supported machine format)
GET  /api/formats         supported / planned formats + validation status (drives the UI status strip)
POST /api/export/package  design JSON -> zip (dst, project, preview, sheet, manifest)
POST /api/export/sheet    design JSON -> production sheet HTML
POST /api/export/svg      design JSON -> preview SVG
POST /api/import/dst      {data(base64)} -> stitches (view only)
POST /api/import/svg      {svg, width_mm?} -> objects
POST /api/import/raster   {data(base64), width_mm, colors} -> objects
GET  /api/library         library index (designs/library/index.json)
GET  /api/library/<id>/thumb.svg | dst | esproj   only ids listed in the index
GET  /api/templates       template catalogue
POST /api/tools/column-from-outline  {ring} -> {rail1, rail2, ...} or 400 with the reason
POST /api/template        {id, params, color} -> objects
GET  /api/health"""
import base64, json, math, os, re, sys, time, hashlib
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from stitchcraft_engine.design import generate, run_checks, FABRICS, machine, empty_stats            # noqa: E402
from stitchcraft_engine.dst import write_dst, read_dst                          # noqa: E402
from stitchcraft_engine import formats                                          # noqa: E402
from stitchcraft_engine.model import Cmd                                        # noqa: E402
from stitchcraft_engine.svg_input import parse_svg, UnsupportedSvg              # noqa: E402
from stitchcraft_engine.raster import digitize_image, enhance_image, RasterUnavailable        # noqa: E402
from stitchcraft_engine.schema import validate_design                                       # noqa: E402
import openapi                                                                                # noqa: E402
import ops                                                                                  # noqa: E402
from stitchcraft_engine import machines, report as report_mod, templates, dst_analyze, dst_verify, checklist, profiles, sequence, export_pipeline, placements as placements_mod                                        # noqa: E402
from stitchcraft_engine.outline import column_from_outline                      # noqa: E402
import sheet                                                                   # noqa: E402

WEB = ROOT / "web"
LIB = ROOT / "designs" / "library"
LIB_FILES = {"thumb.svg": ("thumb.svg", "image/svg+xml"), "dst": ("dst", "application/octet-stream"), "esproj": ("esproj", "application/json")}
MAX_BODY = 25 * 1024 * 1024
LIMITER = ops.limiter_from_env()
MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json"}


def compact(pattern, ids=None):
    """Stitches as arrays for fast transfer: [x,y,cmdcode,thread,objectIndex]; cmd 0=stitch 1=jump 2=trim 3=colour 4=end.
    objectIndex points into the `ids` list (object ids in order of first appearance), -1 = none."""
    code = {Cmd.STITCH: 0, Cmd.JUMP: 1, Cmd.TRIM: 2, Cmd.COLOR_CHANGE: 3, Cmd.END: 4}
    ids = [] if ids is None else ids
    idx = {}
    out = []
    for s in pattern.stitches:
        if s.object_id is not None and s.object_id not in idx:
            idx[s.object_id] = len(ids); ids.append(s.object_id)
        out.append([round(s.x, 3), round(s.y, 3), code[s.cmd], s.thread, idx.get(s.object_id, -1)])
    return out


def issues(rep):
    return [{"code": i.code, "severity": i.severity, "message": i.message, "index": i.index} for i in rep.issues]


MAX_OBJECTS, MAX_POINTS, MAX_SVG = 3000, 400_000, 5 * 1024 * 1024


def check_design(d):
    validate_design(d)                                   # types / finite numbers / parameter ranges -> a clear 400, never a 500 from deep inside the engine
    objs = d.get("objects", [])
    if not isinstance(objs, list) or len(objs) > MAX_OBJECTS:
        raise ValueError(f"too many objects (limit {MAX_OBJECTS})")
    pts = 0
    for o in objs:
        for k in ("points", "rail1", "rail2"):
            pts += len(o.get(k, []))
        pts += sum(len(r) for r in o.get("rings", []))
    if pts > MAX_POINTS:
        raise ValueError(f"design too complex (limit {MAX_POINTS} points)")


def _only_unstitched(d):
    objs = [o for o in d.get("objects", []) if not o.get("hidden")]
    return bool(objs) and all(o.get("guide") or o.get("type") == "embellishment" for o in objs)


def library_index():
    """The library index, or an empty list when the folder is missing/corrupt (the panel then just shows 'no designs')."""
    try:
        data = json.loads((LIB / "index.json").read_text(encoding="utf-8"))
        return [e for e in data.get("designs", []) if isinstance(e, dict) and isinstance(e.get("id"), str) and re.fullmatch(r"[a-z0-9_]+", e["id"])]
    except (OSError, ValueError):
        return []


def library_file(design_id, kind):
    """(path, content_type) for a library file, only for ids listed in the index and the three known file kinds. Never builds
    a path from anything the client sent except an id that already exists in the index."""
    if kind not in LIB_FILES or design_id not in {e["id"] for e in library_index()}:
        return None
    ext, ctype = LIB_FILES[kind]
    f = LIB / design_id / f"{design_id}.{ext}"
    return (f, ctype) if f.is_file() else None


def api_generate(d):
    check_design(d)
    if _only_unstitched(d):        # e.g. only embellishment placeholders / guides: valid, just nothing to stitch
        return {"stitches": [], "threads": [], "stats": empty_stats(d), "issues": [],
                "notes": ["Nothing to stitch yet - embellishments and guides are not part of the DST."]}
    pattern, notes, st = generate(d)
    rep = run_checks(d, pattern)
    out = {"source": "plan", "notes": notes, "issues": issues(rep), "stats": st}
    if d.get("decoded"):                         # simulate the DST FILE (decoded bytes), not the engine's floating-point plan
        try:
            sim = export_pipeline.decoded_simulation(d)
            out.update(source="dst-file", sha256=sim["sha256"], stitches=sim["stitches"], objects=sim["objects"], threads=sim["threads"])
            return out
        except export_pipeline.ExportError as e:
            out["notes"] = notes + [f"Simulation shows the stitch plan, not a DST file: {e}"]
    ids = []
    out.update(stitches=compact(pattern, ids), objects=ids, threads=[t.hex for t in pattern.threads])
    return out


def api_dst(d):
    """Validated export: returns (ExportResult, None) or (None, error dict with stage + structured issues). Never returns an unverified file."""
    check_design(d)
    try:
        return export_pipeline.export_dst(d), None
    except export_pipeline.ExportError as e:
        if e.code == "EXPORT_NO_STITCHES":
            raise ValueError(str(e)) from e              # unchanged API contract: nothing to stitch is a 400, not a 422 refusal
        return None, e.to_dict()


def api_preview_svg(d):
    from stitchcraft_engine.preview import preview_svg
    pattern, _, _ = generate(d)
    h = d.get("hoop", {})
    return preview_svg(pattern, float(h.get("w", 0)), float(h.get("h", 0))).encode()


def api_view_dst(d):
    """Read an existing .dst so it can be inspected/simulated (view only)."""
    ops.check_base64_upload(d.get("data"), "DST")
    raw = base64.b64decode(d["data"])
    ops.check_dst_upload(raw)
    f = read_dst(raw)
    if len(f.records) > 2_000_000:
        raise ValueError("file too large")
    pal = ["#c8102e", "#2563eb", "#2e9e44", "#f28c28", "#6d28d9", "#14b8a6", "#000000", "#ec4899"]
    out, x, y, th = [], 0, 0, 0
    for dx, dy, cmd in f.records:
        x += dx; y += dy
        if cmd == "color_change":
            th += 1; out.append([x / 10, -y / 10, 3, th])
        elif cmd == "end":
            out.append([x / 10, -y / 10, 4, th])
        else:
            out.append([x / 10, -y / 10, 1 if cmd == "jump" else 0, th])
    return {"stitches": out, "threads": [pal[i % len(pal)] for i in range(th + 1)], "header": f.header,
            "color_changes": f.color_changes, "ends_properly": f.ends_properly}


def api_placements(d):
    """Placement set: design + [{id, width_mm?, ...}] -> zip of named DSTs. Returns (bytes, report)."""
    check_design(d["design"])
    data, rep = sheet.placement_set(d["design"], d.get("placements") or [], str(d.get("source_side", "left")), d.get("thread"))
    if data is None:
        raise ValueError(rep["error"] + ": " + "; ".join(f"{r['file']}: {r.get('reason', '')}" for r in rep["placements"])[:600])
    return data, rep


def api_lettering(d):
    """TrueType / OpenType lettering (uploaded font, complex-script shaping) -> editable embroidery objects."""
    from stitchcraft_engine.lettering import lettering_objects
    font = base64.b64decode(d["font"]) if d.get("font") else None
    color = str(d.get("color", "#000000"))
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("color must be #rrggbb")
    lang = d.get("language") or None
    if lang is not None and not re.fullmatch(r"[a-z]{2,3}", str(lang)):
        raise ValueError("language must be an ISO 639 code such as te, hi, ta, ar")
    direction = d.get("direction") or None
    if direction not in (None, "ltr", "rtl"):
        raise ValueError("direction must be ltr or rtl")
    objs, notes, info = lettering_objects(str(d.get("text", "")), float(d.get("height_mm", 15)), color, font, lang, direction,
                                          str(d.get("quality", "high")))
    return {"objects": objs, "notes": notes, "info": {k: v for k, v in info.items() if k != "report"}}


def api_to_manual(d):
    """Stitch-level editing: replace one object by its generated needle points as `manual` objects (one per stitched run)."""
    design, oid = d["design"], str(d["id"])
    check_design(design)
    src = next((o for o in design.get("objects", []) if str(o.get("id")) == oid), None)
    if src is None:
        raise ValueError(f"no object with id {oid!r}")
    if src.get("type") in ("embellishment", "manual"):
        raise ValueError("this object has no generated stitches to convert")
    # without lock stitches: the builder adds tie-in / tie-off again when the manual object is sewn (no doubled locks)
    pattern, _, _ = generate(dict(design, objects=[src], machine=dict(design.get("machine") or {}, lock_len=0)))
    runs, cur = [], []
    for s in pattern.stitches:
        if s.cmd == Cmd.STITCH:
            if not cur or (abs(s.x - cur[-1][0]) > 1e-9 or abs(s.y - cur[-1][1]) > 1e-9):
                cur.append([s.x, s.y])                                # full precision: converting changes nothing in the DST
        elif cur:
            runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    runs = [r for r in runs if len(r) >= 2]
    if not runs:
        raise ValueError("object produced no stitches")
    base = src.get("name") or oid
    out = [{"id": f"{oid}_m{k + 1}", "type": "manual", "color": src.get("color"), "name": f"{base} stitches {k + 1}" if len(runs) > 1 else f"{base} stitches",
            "points": r} for k, r in enumerate(runs)]
    return {"objects": out, "replaces": oid, "stitches": sum(len(r) for r in runs)}


def api_quality(d):
    check_design(d)
    from stitchcraft_engine import quality
    pattern, _notes, _st = generate(d)
    return quality.quality_report(d, pattern)


def api_report(d):
    check_design(d)
    try:
        r = report_mod.build_report(d)
    except export_pipeline.ExportError as e:
        if e.code == "EXPORT_NO_STITCHES":
            raise ValueError(str(e)) from e
        return None, e.to_dict()
    return ({"report": r, "html": report_mod.render_html(r)} if d.get("html") else {"report": r}), None


def api_machine_check(d):
    check_design(d)
    pattern, _n, _s = generate(d)
    return {"profile": machines.resolve(d), "issues": machines.check_design(d, pattern)}


def api_travel(d):
    check_design(d)
    from stitchcraft_engine import travel
    pattern, _notes, _st = generate(d)
    return travel.travel_report(d, pattern)


def api_checklist(d):
    check_design(d)
    return checklist.evaluate(d)


def api_autodigitize(d):
    """Professional auto-digitizing pipeline: image -> clean + vectorise -> stitch types -> fabric/category profile
    (density, underlay, pull comp, shortening) -> safe auto-fix -> sequence optimisation -> 15-item checklist."""
    imp = api_raster({k: d[k] for k in ("data", "width_mm", "colors", "quality", "enhance") if k in d})
    if not imp["objects"]:
        raise ValueError("; ".join(imp["notes"]) or "nothing to digitize")
    hoop = {"w": float(d.get("hoop_w", 100)), "h": float(d.get("hoop_h", 100)), "margin": 3}
    thread = str(d.get("thread", "40wt"))
    from stitchcraft_engine.design import THREADS
    if thread not in THREADS:
        raise ValueError(f"unknown thread preset {thread!r}")
    design = {"name": placements_mod.slug(d.get("name") or "design"), "hoop": hoop, "thread": thread, "stabiliser": d.get("stabiliser", "cut-away"),
              "source": {"type": "raster", "report": imp.get("report") or {}}, "objects": imp["objects"]}
    log = [f"digitized: {len(imp['objects'])} object(s) " + ", ".join(f"{v} {k}" for k, v in (imp.get("report") or {}).get("objects", {}).items() if v)]
    log += [f"import: {n}" for n in imp.get("notes", [])]
    # the digitizer's own parameter values are defaults, not user choices: the profile replaces them (angle is kept)
    design, l2 = profiles.apply_profile(design, str(d.get("fabric", "cotton")), str(d.get("category", "blouse_neck")), overwrite=True)
    design, l3 = placements_mod.autofix(design)
    design, l4 = sequence.optimize_sequence(design)
    return {"design": design, "log": log + l2 + l3 + l4, "import_report": imp.get("report"), "checklist": checklist.evaluate(design)}


def api_profile(d):
    """Apply a fabric / category profile and / or optimise the sewing sequence of the CURRENT design (the editor's Profile panel).
    profile=false -> sequence only; optimize=false -> profile only."""
    check_design(d["design"])
    design, log = d["design"], []
    if d.get("profile", True):
        design, log = profiles.apply_profile(design, d.get("fabric"), d.get("category"), bool(d.get("overwrite")))
    design, l2 = sequence.optimize_sequence(design) if d.get("optimize", True) else (design, [])
    return {"design": design, "log": log + l2}


def api_autofix(d):
    """Conservative auto-correction of a design. Returns {design, log}."""
    check_design(d)
    from stitchcraft_engine import placements
    fixed, log = placements.autofix(d)
    return {"design": fixed, "log": log}


def api_dst_report(d):
    """Analysis + six-stage verification of any DST (ours or a third party's): metrics and PASS/WARN/FAIL with evidence."""
    raw = base64.b64decode(d["data"])
    if len(raw) > 30_000_000:
        raise ValueError("file too large")
    try:
        f = read_dst(raw)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"not a readable DST file: {e}") from e
    if len(f.records) > 2_000_000:
        raise ValueError("file too large")
    k = {"40wt": 1.0, "60wt": 0.75, "120": 0.55}.get(str(d.get("thread", "40wt")), 1.0)
    hoop = (float(d.get("hoop_w", 200)), float(d.get("hoop_h", 300)))
    return {"analysis": dst_analyze.analyze(raw, str(d.get("name", ""))), "verify": dst_verify.verify(raw, hoop, k, int(d.get("needles", 15)), str(d.get("name", "")))}


def api_exp(d):
    """EXPERIMENTAL Melco EXP - not exposed unless ES_EXPERIMENTAL_FORMATS=1 (see engine/stitchcraft_engine/formats.py)."""
    writer = formats.get_writer("exp")              # raises UnsupportedFormat while EXP is not exposed
    check_design(d)
    pattern, notes, st = generate(d)
    rep = run_checks(d, pattern)
    if not rep.ok:
        return None, {"error": "Export blocked", "issues": issues(rep)}
    return writer(pattern, trim_jumps=machine(d)["trim_jumps"]), None


def api_svg(d):
    from stitchcraft_engine.pipeline import digitize_svg  # noqa: F401  (ensures module import works)
    txt = d["svg"]
    if not isinstance(txt, str) or len(txt) > MAX_SVG:
        raise ValueError("SVG too large (limit 5 MB)")
    if "<!ENTITY" in txt or "<!DOCTYPE" in txt.upper():
        raise ValueError("SVG with DOCTYPE/ENTITY declarations is rejected for safety; re-save it as plain SVG")
    if txt.lstrip()[:4] == "%PDF":
        raise ValueError(formats.PDF_MESSAGE)
    try:
        doc = parse_svg(txt)
    except (ET.ParseError, IndexError, ZeroDivisionError, OverflowError) as e:
        raise ValueError(f"this SVG could not be read ({type(e).__name__}); re-save it as plain SVG") from e
    objs = []
    for sh in doc.shapes:
        if sh.fill and sh.closed:
            objs.append({"id": sh.id, "type": "fill", "color": sh.fill, "rings": [[list(p) for p in r] for r in sh.rings]})
        if sh.stroke:
            for k, r in enumerate(sh.rings):
                pts = [list(p) for p in (r + [r[0]] if sh.closed else r)]
                w = sh.stroke_width_mm
                o = {"id": f"{sh.id}.s{k}", "color": sh.stroke, "points": pts}
                o.update({"type": "satin", "params": {"width": round(w, 2)}} if 1.0 <= w <= 7.0 else {"type": "run"})
                objs.append(o)
    return {"objects": objs, "width_mm": doc.width_mm, "height_mm": doc.height_mm, "notes": doc.warnings}


def _erase_pixels(raw: bytes, width_mm: float, strokes) -> bytes:
    """Pixel-level editing of the SOURCE image before digitizing: each stroke [x_mm, y_mm, r_mm] (in the imported object coordinates, origin top-left)
    is painted with the image's background colour (or made transparent), so the region simply is not detected. Nothing else is touched."""
    if not isinstance(strokes, list) or len(strokes) > 400:
        raise ValueError("erase must be a list of at most 400 [x_mm, y_mm, radius_mm] strokes")
    import io as _io
    from collections import Counter
    from PIL import Image, ImageDraw
    for st in strokes:
        if not (isinstance(st, list) and len(st) == 3 and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in st) and 0 < st[2] <= 500):
            raise ValueError("each erase stroke must be [x_mm, y_mm, radius_mm] with 0 < radius <= 500")
    if not strokes:
        return raw
    try:
        im = Image.open(_io.BytesIO(raw)); im.load()
    except OSError as e:
        raise ValueError("the image is damaged or is not a valid PNG / JPEG file") from e
    im = im.convert("RGBA")
    w, h = im.size; k = w / float(width_mm)
    px = im.load(); border = [px[x, 0] for x in range(0, w, max(1, w // 64))] + [px[x, h - 1] for x in range(0, w, max(1, w // 64))] + \
        [px[0, y] for y in range(0, h, max(1, h // 64))] + [px[w - 1, y] for y in range(0, h, max(1, h // 64))]
    bg = Counter(border).most_common(1)[0][0]
    dr = ImageDraw.Draw(im)
    for x, y, r in strokes:
        dr.ellipse([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k], fill=bg)
    out = _io.BytesIO(); im.save(out, "PNG")
    return out.getvalue()


def api_raster(d):
    ops.check_base64_upload(d.get("data"), "image")
    raw = base64.b64decode(d["data"])
    if raw[:4] == b"%PDF":
        raise ValueError(formats.PDF_MESSAGE)
    if d.get("erase"):
        raw = _erase_pixels(raw, float(d.get("width_mm", 80)), d["erase"])
    enh = None
    mode = str(d.get("enhance", "off"))
    if mode not in ("off", "auto", "always"):
        raise ValueError("enhance must be off, auto or always")
    if mode != "off":
        try:
            out, info = enhance_image(raw, 2.0, "sharpen" if mode == "always" else "auto")
        except OSError as e:
            raise ValueError("the image is damaged or is not a valid PNG / JPEG file") from e
        if len(info["steps"]) > 1:                       # only use it when it actually cleaned something
            raw, enh = out, info
        else:
            enh = dict(info, skipped="image is already sharp and high-resolution")
    try:
        r = digitize_image(raw, float(d.get("width_mm", 80)), int(d.get("colors", 6)), str(d.get("quality", "standard")))
    except OSError as e:                                  # PIL: truncated / damaged / unrecognised image data
        raise ValueError("the image is damaged or is not a valid PNG / JPEG file") from e
    return {"objects": r["objects"], "notes": r["notes"], "width_mm": r["size_mm"][0], "height_mm": r["size_mm"][1], "report": dict(r["report"], enhance=enh)}


def api_enhance(d):
    ops.check_base64_upload(d.get("data"), "image")
    raw = base64.b64decode(d["data"])
    try:
        out, info = enhance_image(raw, float(d.get("scale", 2.0)), str(d.get("mode", "auto")))
    except OSError as e:
        raise ValueError("the image is damaged or is not a valid PNG / JPEG file") from e
    return {"png": base64.b64encode(out).decode(), "info": info}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Request-Id", getattr(self, "_rid", "-"))
        for k, v in ops.SECURITY_HEADERS.items():
            self.send_header(k, v)
        self._status = code
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    timeout = 30                                         # a stalled client cannot hold a worker thread forever (socket read timeout)

    def _begin(self):
        self._rid = ops.new_request_id(); self._t0 = time.monotonic(); self._status = 0
        client = self.client_address[0] if self.client_address else "?"
        ok, retry = LIMITER.allow(client, ops.cost_of(self.path.split("?")[0]) if self.command == "POST" else 1.0)
        if not ok:
            ops.log_event("warning", "rate_limited", rid=self._rid, client=client, path=self.path.split("?")[0])
            body = json.dumps({"error": "too many requests - slow down and retry", "retry_after_s": retry, "request_id": self._rid}).encode()
            self.send_response(429); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            self.send_header("Retry-After", str(retry)); self.send_header("X-Request-Id", self._rid); self.end_headers(); self.wfile.write(body); self._status = 429
            return False
        return True

    def _end(self):
        ms = round((time.monotonic() - self._t0) * 1000)
        ops.log_event("warning" if ms > ops.SLOW_SECONDS * 1000 else "info", "slow_request" if ms > ops.SLOW_SECONDS * 1000 else "request", rid=self._rid,
                      method=self.command, path=self.path.split("?")[0], status=self._status, ms=ms, client=self.client_address[0] if self.client_address else "?")

    def do_GET(self):
        if not self._begin():
            return
        try:
            self._get()
        finally:
            self._end()

    def _get(self):
        path = self.path.split("?")[0]
        if path == "/api/font":
            from stitchcraft_engine.font import GLYPHS, GLYPH_W, GLYPH_H, GAP
            return self._send(200, {"glyphs": GLYPHS, "w": GLYPH_W, "h": GLYPH_H, "gap": GAP})
        if path == "/api/library":
            return self._send(200, {"designs": library_index()})
        m = re.fullmatch(r"/api/library/([a-z0-9_]+)/(thumb\.svg|dst|esproj)", path)
        if m:
            hit = library_file(m.group(1), m.group(2))
            if not hit:
                return self._send(404, {"error": "not found"})
            f, ctype = hit
            data = f.read_bytes()
            extra = {"Content-Disposition": f'attachment; filename="{m.group(1)}.dst"', "X-SHA256": hashlib.sha256(data).hexdigest()} if m.group(2) == "dst" else {}
            return self._send(200, data, ctype, extra)
        if path == "/api/templates":
            return self._send(200, {"templates": templates.catalog()})
        if path == "/api/openapi.json":
            return self._send(200, openapi.spec())
        if path == "/api/machines":
            return self._send(200, {"machines": machines.catalog(), "note": "No machine profile is validated. Output format: DST only."})
        if path == "/api/fabrics":
            return self._send(200, {"fabrics": profiles.fabric_catalog()})
        if path == "/api/formats":
            return self._send(200, formats.describe())
        if path == "/api/health":
            return self._send(200, {"ok": True, "fabrics": FABRICS})
        f = (WEB / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if WEB not in f.parents and f != WEB or not f.is_file():
            return self._send(404, {"error": "not found"})
        self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))

    def do_POST(self):
        if not self._begin():
            return
        try:
            self._post()
        finally:
            self._end()

    def _post(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._send(400, {"error": "bad Content-Length"})
        if n < 0 or n > MAX_BODY:
            return self._send(413, {"error": "body too large"})
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
            path = self.path.split("?")[0]
            if path == "/api/generate":
                return self._send(200, api_generate(d))
            if path == "/api/export/dst":
                res, err = api_dst(d)
                if err:
                    ops.log_event("warning", "export_dst", rid=self._rid, result="refused", stage=err.get("stage"), code=err.get("code"))
                    return self._send(422, err)
                name = sheet._safe(d.get("name"))
                ops.log_event("info", "export_dst", rid=self._rid, design_sha=hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16], dst_sha256=res.sha256, bytes=len(res.data), result="released")
                return self._send(200, res.data, "application/octet-stream",
                                  {"Content-Disposition": f'attachment; filename="{name}.dst"', "X-SHA256": res.sha256})
            if path == "/api/tools/column-from-outline":
                ring = d.get("ring")
                if not isinstance(ring, list) or len(ring) > 5000:
                    raise ValueError("ring must be a list of [x, y] points (max 5000)")
                return self._send(200, column_from_outline([(float(a), float(b)) for a, b in ring]))
            if path == "/api/template":
                return self._send(200, {"objects": templates.build(d.get("id", ""), (d.get("params") or {}), d.get("color", "#c8102e"))})
            if path == "/api/export/exp":
                data, err = api_exp(d)
                if err:
                    return self._send(422, err)
                return self._send(200, data, "application/octet-stream", {"Content-Disposition": f'attachment; filename="{sheet._safe(d.get("name"))}.exp"'})
            if path == "/api/export/package":
                check_design(d)
                data, err = sheet.package(d)
                if err:
                    return self._send(422, err)
                return self._send(200, data, "application/zip",
                                  {"Content-Disposition": f'attachment; filename="{sheet._safe(d.get("name"))}-package.zip"'})
            if path == "/api/export/sheet":
                check_design(d)
                return self._send(200, sheet.sheet_html(d).encode(), "text/html; charset=utf-8")
            if path == "/api/export/svg":
                return self._send(200, api_preview_svg(d), "image/svg+xml",
                                  {"Content-Disposition": 'attachment; filename="preview.svg"'})
            if path == "/api/import/dst":
                return self._send(200, api_view_dst(d))
            if path == "/api/import/svg":
                return self._send(200, api_svg(d))
            if path == "/api/import/raster":
                return self._send(200, api_raster(d))
            if path == "/api/lettering":
                return self._send(200, api_lettering(d))
            if path == "/api/to_manual":
                return self._send(200, api_to_manual(d))
            if path == "/api/report":
                res, err = api_report(d)
                return self._send(400 if err else 200, err or res)
            if path == "/api/machine/check":
                return self._send(200, api_machine_check(d))
            if path == "/api/travel":
                return self._send(200, api_travel(d))
            if path == "/api/quality":
                return self._send(200, api_quality(d))
            if path == "/api/checklist":
                return self._send(200, api_checklist(d))
            if path == "/api/autodigitize":
                return self._send(200, api_autodigitize(d))
            if path == "/api/profile":
                return self._send(200, api_profile(d))
            if path == "/api/autofix":
                return self._send(200, api_autofix(d))
            if path == "/api/placements":
                data, rep = api_placements(d)
                return self._send(200, data, "application/zip", {"Content-Disposition": f'attachment; filename="{rep["base"]}-placements.zip"',
                                                                  "X-Placement-Report": base64.b64encode(json.dumps([{k: r.get(k) for k in ("file", "status", "grade", "stitches", "reason")} for r in rep["placements"]]).encode()).decode()})
            if path == "/api/dst/report":
                return self._send(200, api_dst_report(d))
            if path == "/api/enhance":
                return self._send(200, api_enhance(d))
            self._send(404, {"error": "not found"})
        except json.JSONDecodeError:
            self._send(400, {"error": "request body is not valid JSON"})
        except (UnsupportedSvg, RasterUnavailable, ValueError, KeyError, TypeError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            import traceback
            ops.log_event("error", "unhandled_exception", rid=self._rid, path=self.path.split("?")[0], error_type=type(e).__name__, error=str(e)[:300], trace=traceback.format_exc()[-1500:])
            self._send(500, {"error": f"internal error ({type(e).__name__}); quote request id {self._rid} when reporting it", "request_id": self._rid})

    def log_message(self, *a):
        pass


def serve_args(argv, env):
    """(host, port). Default is localhost-only: the app has no login, so only bind wider (ES_HOST=0.0.0.0) inside a
    container that publishes the port to 127.0.0.1, or behind your own authenticated proxy."""
    host = env.get("ES_HOST", "127.0.0.1")
    port = int(argv[1]) if len(argv) > 1 else int(env.get("ES_PORT", 8765))
    if not 1 <= port <= 65535:
        raise ValueError("port must be 1-65535")
    return host, port


if __name__ == "__main__":
    host, port = serve_args(sys.argv, os.environ)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"WARNING: listening on {host}. EmbroideryStudio has no login - expose it only through an authenticated proxy or a localhost-published container port.")
    print(f"EmbroideryStudio on http://{host}:{port}")
    ThreadingHTTPServer((host, port), H).serve_forever()
