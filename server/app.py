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
import base64
import urllib.parse, io, json, math, os, re, sys, time, hashlib
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
from stitchcraft_engine import fidelity, machines, report as report_mod, templates, dst_analyze, dst_verify, checklist, profiles, sequence, export_pipeline, placements as placements_mod                                        # noqa: E402
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


def api_split(d):
    """Design larger than the hoop -> one validated DST per hooping + alignment marks (zip). The hoop comes from the design's own hoop setting."""
    from stitchcraft_engine import hooping
    import io, zipfile
    check_design(d)
    h = d.get("hoop") or {}
    plan = hooping.split_for_hoop(d, float(h.get("w", 100)), float(h.get("h", 100)), max(6.0, float(h.get("margin", 3))), bool(d.get("marks", True)))
    buf = io.BytesIO(); rows = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for t in plan["tiles"]:
            try:
                res = export_pipeline.export_dst(t["design"])
            except export_pipeline.ExportError as e:
                rows.append({"name": t["name"], "status": "blocked", "reason": f"{e.stage}: {e}"[:300]}); continue
            n = sheet._safe(t["name"])
            z.writestr(f"{n}.dst", res.data); z.writestr(f"{n}.export-report.json", json.dumps(res.report, indent=1))
            z.writestr(f"{n}.esproj", json.dumps({"app": "EmbroideryStudio", "version": 1, "doc": t["design"]}, indent=1))
            rows.append({"name": t["name"], "status": "ok", "objects": t["objects"], "stitches": res.report["counts"]["stitch"], "col": t["col"], "row": t["row"], "size_mm": res.report["size_mm"]})
        z.writestr("SPLIT-README.txt", "Split for hooping. Hoop each tile so that its alignment crosses sit on the crosses already stitched by the neighbouring tile (use a light, removable thread; the marks are real stitches). "
                   "Order: row by row, left to right. Objects are never cut; objects larger than one tile are listed in the report. Not verified on any machine.\n")
        z.writestr("split-report.json", json.dumps({"grid": {k: v for k, v in plan["grid"].items()}, "tiles": rows, "oversize_objects": plan["oversize"]}, indent=1))
    return buf.getvalue(), {"tiles": rows, "oversize": plan["oversize"], "grid": {"cols": plan["grid"]["cols"], "rows": plan["grid"]["rows"]}}


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
    out, _full, _orig = _autodigitize_core(d)
    return out


def _autodigitize_core(d):
    imp, full, original = _raster_full({k: d[k] for k in ("data", "width_mm", "colors", "quality", "enhance", "erase", "decisions", "preset", "shapes") if k in d})
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
    return ({"design": design, "log": log + l2 + l3 + l4, "import_report": imp.get("report"), "source": imp.get("source"), "inventory": imp.get("inventory", []),
             "checklist": checklist.evaluate(design)}, full, original)


def _sections(design, original=None, width_mm=80.0, validation=None, photo=None, res=None):
    """The five separate validation sections (never combined) for a design; `original` (image bytes) enables section 1."""
    from stitchcraft_engine import sections as SEC, source_quality
    try:
        res = res or export_pipeline.export_dst(design)
    except export_pipeline.ExportError as e:
        return {"error": str(e), "export_error": e.to_dict()}
    q = source_quality.assess(original, width_mm) if original else None
    return SEC.build(design, res, source_quality=q, validation=validation, photo=photo)


def api_report_sections(d):
    design = d.get("design")
    if not isinstance(design, dict):
        raise ValueError("design is required")
    check_design(design)
    original = None
    if d.get("image"):
        ops.check_base64_upload(d["image"], "image"); original = base64.b64decode(d["image"])
    return _sections(design, original, float(d.get("width_mm", 80)), d.get("validation") if isinstance(d.get("validation"), dict) else None)


def _threads_param(v):
    from stitchcraft_engine import thread_separation as TS
    if v is None:
        return None
    if not (isinstance(v, list) and 1 <= len(v) <= 4):
        raise ValueError("threads must be a list of 1-4 thread classes")
    out = []
    for t in v:
        if not isinstance(t, dict) or not re.fullmatch(r"[a-z0-9_]{1,16}", str(t.get("id", ""))) or not re.fullmatch(r"#[0-9a-fA-F]{6}", str(t.get("hex", ""))):
            raise ValueError("each thread needs an id (a-z0-9_) and a #rrggbb hex")
        h = t.get("hue")
        if not (isinstance(h, list) and len(h) == 2 and all(isinstance(x, (int, float)) and 0 <= x <= 360 for x in h)):
            raise ValueError("hue must be [from, to] degrees 0-360")
        sm, vm, mp = t.get("sat_min", 0.3), t.get("val_min", 0.35), t.get("min_px", 120)
        if not (isinstance(sm, (int, float)) and 0 <= sm <= 1 and isinstance(vm, (int, float)) and 0 <= vm <= 1 and isinstance(mp, int) and 10 <= mp <= 5000):
            raise ValueError("sat_min / val_min must be 0-1 and min_px 10-5000")
        out.append({"id": t["id"], "hex": t["hex"].lower(), "hue": [float(h[0]), float(h[1])], "sat_min": float(sm), "val_min": float(vm), "min_px": mp, "rosette": bool(t.get("rosette"))})
    return out


def api_garment_digitize(d):
    """Garment photo -> thread-separated design (red / gold by hue, radial-satin rosettes, one smooth border line, strays removed, leaf angles) -> validated DST.
    Heuristic; software validation only; physical validation PENDING."""
    from stitchcraft_engine import thread_separation as TS, motif_isolation as MI, photo_validation as PV
    ops.check_base64_upload(d.get("data"), "image")
    raw = base64.b64decode(d["data"])
    if not (raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff"):
        raise ValueError("unsupported image type: only PNG and JPEG are accepted")
    width = float(d.get("width_mm", 130))
    raw = MI.crop_region(raw, d.get("region"))
    try:
        plan = TS.prepare(raw, width, _threads_param(d.get("threads")), border=bool(d.get("border", True)))
    except OSError as e:
        raise ValueError("the image is damaged or is not a valid PNG / JPEG file") from e
    hoop = {"w": float(d.get("hoop_w") or 180), "h": float(d.get("hoop_h") or 220), "margin": 3}
    out = api_autodigitize({"data": base64.b64encode(plan["layer_png"]).decode(), "width_mm": width, "colors": max(2, len(plan["threads"]) + 1), "quality": "high",
                            "hoop_w": hoop["w"], "hoop_h": hoop["h"], "name": d.get("name") or "garment", "fabric": d.get("fabric", "silk"), "category": d.get("category", "blouse_neck")})
    design = TS.finish(out["design"], plan); design["hoop"] = hoop; design["name"] = placements_mod.slug(d.get("name") or "garment")
    check_design(design)
    try:
        exp = export_pipeline.export_dst(design); sim = export_pipeline.decoded_simulation(design)
    except export_pipeline.ExportError as e:
        return {"error": str(e), "export_error": e.to_dict(), "design": design}
    w_mm = plan["size_px"][0] * plan["scale"]; h_mm = plan["size_px"][1] * plan["scale"]; ox = design["source"]["thread_separation"]
    from stitchcraft_engine import machine_compat
    return {"design": design, "separation": ox, "dst": {"sha256": exp.sha256, "bytes": len(exp.data), "records": exp.record_count, "counts": exp.report["counts"], "filename": machine_compat.filename_for(design["name"])},
            "preflight": machine_compat.preflight(exp.data, machine_compat.filename_for(design["name"]), hoop), "sections": _sections(design, raw, width, None, None, exp),
            "honesty": ["Heuristic colour-by-hue separation tuned on pink silk; check the result against the photo.", "Stones / beads are not stitched.", "Physical machine validation is PENDING."]}


def api_threads_import(d):
    from stitchcraft_engine import threads
    name = str(d.get("name") or "").strip()
    if not name or len(name) > 60:
        raise ValueError("palette name is required (up to 60 characters)")
    text = d.get("text")
    if not isinstance(text, str):
        raise ValueError("text (the CSV or JSON content) is required")
    cols, rej = threads.parse_palette(text, str(d.get("format", "auto")))
    rec = threads.save_palette(name, str(d.get("brand") or ""), cols)
    return {"palette": {k: rec[k] for k in ("id", "name", "brand", "source")}, "count": len(cols), "rejected": rej}


def api_threads_apply(d, snap=True):
    from stitchcraft_engine import threads
    design = d.get("design")
    if not isinstance(design, dict):
        raise ValueError("design is required")
    check_design(design)
    pal = threads.get_palette(str(d.get("palette") or ""))
    if not snap:
        return threads.match_design(design, pal)
    out, info = threads.apply_palette(design, pal)
    check_design(out)
    return {"design": out, **info}


def api_threads_replace(d):
    from stitchcraft_engine import threads
    design = d.get("design")
    if not isinstance(design, dict):
        raise ValueError("design is required")
    check_design(design)
    out, n = threads.replace_colour(design, str(d.get("from") or ""), str(d.get("to") or ""))
    return {"design": out, "replaced": n}


def api_threads_consumption(d):
    from stitchcraft_engine import threads
    design = d.get("design") if isinstance(d.get("design"), dict) else d
    check_design(design)
    pattern, notes, st = generate(design)
    return threads.consumption(pattern)


def api_assistant(d):
    """Digitizing assistant: applies a natural-language request to the design's real objects (rule-based interpreter, no external service)."""
    from stitchcraft_engine import assistant
    design = d.get("design")
    if not isinstance(design, dict):
        raise ValueError("design is required")
    check_design(design)
    out = assistant.run(design, d.get("text"))
    check_design(out["design"])
    return out


def api_photo_stitch(d):
    """Photo Stitch Engine: image -> tonal flow-field hatching design -> validated DST -> thread-texture preview from the DECODED DST -> photo validation.
    Software validation only; physical machine validation is separate and PENDING."""
    from stitchcraft_engine import photo, photo_validation as PV
    ops.check_base64_upload(d.get("data"), "image")
    raw = base64.b64decode(d["data"])
    if not (raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff"):
        raise ValueError("unsupported image type: only PNG and JPEG are accepted")
    keys = ("mode", "colors", "levels", "density", "angle", "direction", "dither", "gamma", "cross_hatch", "equalize", "fabric", "thread", "stitch_mm")
    kw = {k: d[k] for k in keys if k in d}
    if "thread_palette" in d:
        tp = d["thread_palette"]
        if not isinstance(tp, list) or len(tp) > 24 or not all(isinstance(h, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", h) for h in tp):
            raise ValueError("thread_palette must be a list of up to 24 #rrggbb colours")
        kw["thread_palette"] = tp
    try:
        res = photo.photo_stitch(raw, float(d.get("width_mm", 100)), **kw)
    except OSError as e:
        raise ValueError("the image is damaged or is not a valid PNG / JPEG file") from e
    w, h = res["size_mm"]
    hoop = {"w": float(d.get("hoop_w") or max(100, math.ceil(w + 20))), "h": float(d.get("hoop_h") or max(100, math.ceil(h + 20))), "margin": 3}
    design = {"name": placements_mod.slug(d.get("name") or "photo"), "hoop": hoop, "thread": str(d.get("thread_weight", "40wt")), "stabiliser": d.get("stabiliser", "cut-away"),
              "fabric": d.get("fabric_preset", "cotton"), "machine": {"micro_clean": 0.4}, "source": {"type": "photo", "report": res["report"]}, "objects": res["objects"]}
    check_design(design)
    try:
        exp = export_pipeline.export_dst(design)
        sim = export_pipeline.decoded_simulation(design)
    except export_pipeline.ExportError as e:
        return {"error": str(e), "export_error": e.to_dict(), "design": design, "report": res["report"]}
    segs = PV.segments_from_sim(sim["stitches"], sim["threads"])
    prev = PV.render_preview(segs, w, h, str(d.get("fabric", "#ffffff")))
    buf = io.BytesIO(); prev.save(buf, "PNG")
    val = PV.compare(raw, prev, w, res["report"]["mode"], str(d.get("fabric", "#ffffff")))
    secs = _sections(design, raw, float(d.get("width_mm", 100)), None, val, exp)
    return {"design": design, "report": res["report"], "preview_png": base64.b64encode(buf.getvalue()).decode(), "validation": val, "sections": secs, "stitch_metrics": PV.stitch_metrics(sim["stitches"], sim["threads"]),
            "dst": {"sha256": exp.sha256, "bytes": len(exp.data), "records": exp.record_count, "export_report": exp.report},
            "source": fidelity.source_record(raw, float(d.get("width_mm", 100))),
            "honesty": ["Thread cannot show continuous tone: tone is line spacing / thread colour; lines are visible.", "The validation compares a simulated thread image with the photo; it is not stitch-out quality.", "Physical machine validation is PENDING."]}


def api_image_isolate(d):
    """Garment-photo motif isolation (read-only on the upload): motif list + overlay; with `extract: true` also the derived cropped motif image
    (non-motif pixels filled with the estimated fabric colour) ready for the vector or photo workflow."""
    from stitchcraft_engine import motif_isolation as MI
    ops.check_base64_upload(d.get("data"), "image")
    raw = base64.b64decode(d["data"])
    if not (raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff"):
        raise ValueError("unsupported image type: only PNG and JPEG are accepted")
    th = float(d.get("threshold", 0.65)); region = d.get("region"); sel = d.get("select")
    if sel is not None and not (isinstance(sel, list) and len(sel) <= 40 and all(isinstance(x, str) and re.fullmatch(r"m\d{1,2}", x) for x in sel)):
        raise ValueError("select must be a list of motif ids such as m1")
    try:
        res = MI.isolate(raw, th, region=region)
        if not res.get("ran"):
            return res
        out = dict(res, source_sha256=hashlib.sha256(raw).hexdigest(), overlay_png=base64.b64encode(MI.overlay(raw, th, sel, region=region)).decode())
        if d.get("extract"):
            png, info = MI.extract(raw, th, sel, region=region)
            out["motif_png"] = base64.b64encode(png).decode(); out["motif"] = dict(info, sha256=hashlib.sha256(png).hexdigest())
        return out
    except OSError as e:
        raise ValueError("the image is damaged or is not a valid PNG / JPEG file") from e


def api_image_quality(d):
    """Source-image quality assessment (read-only): resolution, sharpness, blur, noise, contrast, JPEG blocking, effective resolution, small-feature visibility,
    subject visibility, classification and actionable recommendations. The upload is never modified."""
    from stitchcraft_engine import source_quality
    ops.check_base64_upload(d.get("data"), "image")
    raw = base64.b64decode(d["data"])
    if not (raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:3] == b"\xff\xd8\xff"):
        raise ValueError("unsupported image type: only PNG and JPEG are accepted")
    w = float(d.get("width_mm", 80))
    if not 0 < w <= 1000:
        raise ValueError("width_mm must be between 0 and 1000")
    try:
        return dict(source_quality.assess(raw, w), source_sha256=hashlib.sha256(raw).hexdigest())
    except OSError as e:
        raise ValueError("the image is damaged or is not a valid PNG / JPEG file") from e


def api_image_validate(d):
    """Nine-pass image-to-DST validation (software). Runs the auto-digitize pipeline (or uses the supplied `design` from the editor) and compares the DECODED DST
    with the original upload. Derived images (overlay, difference map) are returned base64; the original is never modified."""
    from stitchcraft_engine import image_validation
    out, full, original = _autodigitize_core(d)
    design = d.get("design") if isinstance(d.get("design"), dict) else out["design"]
    check_design(design)
    rep = image_validation.validate(original, float(d.get("width_mm", 80)), full, design)
    if not d.get("images"):
        rep.pop("derived_images", None)
    secs = _sections(design, original, float(d.get("width_mm", 80)), rep) if d.get("sections", True) else None
    return dict(rep, sections=secs, design_name=design.get("name"), inventory=out["inventory"], import_report=out["import_report"], width_mm=float(d.get("width_mm", 80)), height_mm=full["size_mm"][1])


def api_image_bundle(d):
    """ZIP: the untouched original + SOURCE.json + overlay / difference images + inventory + validation report + DST + project + production report."""
    from stitchcraft_engine import image_validation
    out, full, original = _autodigitize_core(d)
    design = out["design"]
    check_design(design)
    try:
        res = export_pipeline.export_dst(design)
    except export_pipeline.ExportError as e:
        return None, e.to_dict()
    rep = image_validation.validate(original, float(d.get("width_mm", 80)), full, design, res)
    derived = {k: base64.b64decode(v) for k, v in rep.pop("derived_images", {}).items()}
    n = sheet._safe(design.get("name"))
    derived[f"../{n}.dst"] = res.data
    derived[f"../{n}.esproj"] = json.dumps({"app": "EmbroideryStudio", "version": 1, "doc": design}, indent=1).encode()
    prod = report_mod.build_report(design, res)
    zdata = fidelity.make_bundle(original, {k: v for k, v in derived.items() if not k.startswith("../")},
                                 {"inventory": out["inventory"], "image-validation": rep, "import-report": out["import_report"], "production-report": prod, "log": out["log"]}, n)
    import zipfile, io
    zin = zipfile.ZipFile(io.BytesIO(zdata)); buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zo:
        for item in zin.namelist():
            zo.writestr(item, zin.read(item))
        zo.writestr(f"{n}.dst", res.data)
        zo.writestr(f"{n}.esproj", derived[f"../{n}.esproj"])
        zo.writestr(f"{n}.production-report.html", report_mod.render_html(prod))
    return buf.getvalue(), {"software_validation": rep.get("software_validation"), "dst_sha256": res.sha256, "passes": [(p["pass"], p["result"]) for p in rep.get("passes", [])]}


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
    """Melco EXP (software-verified tier; see engine/stitchcraft_engine/formats.py)."""
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
    return _raster_full(d)[0]


def _raster_full(d):
    """-> (JSON-safe API dict, the full digitize_image result incl. the internal label map). Only server code uses the second value."""
    ops.check_base64_upload(d.get("data"), "image")
    raw = base64.b64decode(d["data"])
    if raw[:4] == b"%PDF":
        raise ValueError(formats.PDF_MESSAGE)
    original = raw                                            # the uploaded bytes are authoritative: hashed and reported, never replaced
    if d.get("erase"):
        raw = _erase_pixels(raw, float(d.get("width_mm", 80)), d["erase"])
    enh = None
    mode = str(d.get("enhance", "off"))
    if mode not in ("off", "auto", "always"):
        raise ValueError("enhance must be off, auto or always")
    if mode != "off":
        try:
            from stitchcraft_engine import enhance as enhance_mod
            out, info = enhance_mod.enhance(raw, 2.0, "sharpen" if mode == "always" else "auto")
        except OSError as e:
            raise ValueError("the image is damaged or is not a valid PNG / JPEG file") from e
        if len(info["steps"]) > 1:                       # only use it when it actually cleaned something
            raw, enh = out, info
        else:
            enh = dict(info, skipped="image is already sharp and high-resolution")
    try:
        dec = d.get("decisions") or {}
        if not isinstance(dec, dict) or len(dec) > 2000 or any(v not in ("tack", "omit") for v in dec.values()):
            raise ValueError("decisions must be {inventory id: \"tack\" | \"omit\"}")
        from stitchcraft_engine.smart_design import PRESETS
        preset = str(d.get("preset", "auto"))
        if preset not in PRESETS:
            raise ValueError(f"preset must be one of {sorted(PRESETS)}")
        r = digitize_image(raw, float(d.get("width_mm", 80)), int(d.get("colors", 6)), str(d.get("quality", "standard")), dec, preset, bool(d.get("shapes", False)))
    except OSError as e:                                  # PIL: truncated / damaged / unrecognised image data
        raise ValueError("the image is damaged or is not a valid PNG / JPEG file") from e
    return ({"objects": r["objects"], "notes": r["notes"], "width_mm": r["size_mm"][0], "height_mm": r["size_mm"][1], "report": dict(r["report"], enhance=enh),
             "source": fidelity.source_record(original, float(d.get("width_mm", 80))), "inventory": r.get("inventory", [])}, r, original)


def api_presets(d=None):
    from stitchcraft_engine.smart_design import PRESETS
    return {"presets": [dict(id=k, **v) for k, v in PRESETS.items()], "note": "Presets choose where the run / column / fill boundaries are; density, underlay and pull compensation come from the fabric profile."}


def api_enhance(d):
    ops.check_base64_upload(d.get("data"), "image")
    raw = base64.b64decode(d["data"])
    try:
        from stitchcraft_engine import enhance as enhance_mod
        out, info = enhance_mod.enhance(raw, float(d.get("scale", 2.0)), str(d.get("mode", "auto")), bool(d.get("denoise")), bool(d.get("contrast")))
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

    def _export_format(self, fmt, d):
        check_design(d)
        try:
            res = export_pipeline.export_format(d, fmt)
        except export_pipeline.ExportError as e:
            ops.log_event("warning", "export_format", rid=self._rid, format=fmt, result="refused", stage=e.stage, code=e.code)
            return self._send(422, e.to_dict())
        from stitchcraft_engine import machine_compat
        fn = machine_compat.filename_for(d.get("name")).rsplit(".", 1)[0] + "." + fmt.upper()
        ops.log_event("info", "export_format", rid=self._rid, format=fmt, bytes=len(res.data), sha256=res.sha256, result="released")
        return self._send(200, res.data, "application/octet-stream", {"Content-Disposition": f'attachment; filename="{fn}"', "X-SHA256": res.sha256, "X-Format-Tier": res.report["validation"]["tier"]})

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
        if path == "/api/evidence/checklist":
            from stitchcraft_engine import evidence
            return self._send(200, {"checklist": evidence.CHECKLIST, "required": list(evidence.REQUIRED_TEXT + evidence.REQUIRED_NUM + tuple(evidence.REQUIRED_ENUM)), "statuses": list(evidence.STATUSES)})
        if path == "/api/evidence/records":
            from stitchcraft_engine import evidence
            return self._send(200, {"records": evidence.load_all()})
        if path == "/api/evidence":
            from stitchcraft_engine import evidence
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            sha = (q.get("sha") or [""])[0].lower(); name = (q.get("name") or [""])[0]
            if sha and not re.fullmatch(r"[0-9a-f]{64}", sha):
                return self._send(400, {"error": "sha must be a 64-hex SHA-256"})
            return self._send(200, evidence.status_for(sha or None, name or None))
        if path == "/api/threads/palettes":
            from stitchcraft_engine import threads
            return self._send(200, {"palettes": threads.list_palettes()})
        if path == "/api/threads/palette":
            from stitchcraft_engine import threads
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            try:
                return self._send(200, threads.get_palette((q.get("id") or [""])[0]))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
        if path == "/api/presets":
            return self._send(200, api_presets())
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
                from stitchcraft_engine import machine_compat
                return self._send(200, res.data, "application/octet-stream",
                                  {"Content-Disposition": f'attachment; filename="{name}.dst"', "X-SHA256": res.sha256, "X-Machine-Filename": machine_compat.filename_for(d.get("name"))})
            if path == "/api/tools/column-from-outline":
                ring = d.get("ring")
                if not isinstance(ring, list) or len(ring) > 5000:
                    raise ValueError("ring must be a list of [x, y] points (max 5000)")
                return self._send(200, column_from_outline([(float(a), float(b)) for a, b in ring]))
            if path == "/api/template":
                return self._send(200, {"objects": templates.build(d.get("id", ""), (d.get("params") or {}), d.get("color", "#c8102e"))})
            if path == "/api/export/exp":
                return self._export_format("exp", d)
            if path == "/api/export/jef":
                return self._export_format("jef", d)
            if path == "/api/export/pes":
                return self._export_format("pes", d)
            if path == "/api/export/xxx":
                return self._export_format("xxx", d)
            if path == "/api/export/u01":
                return self._export_format("u01", d)
            if path == "/api/export/sew":
                return self._export_format("sew", d)
            if path == "/api/export/vp3":
                return self._export_format("vp3", d)
            if path == "/api/export/hus":
                return self._export_format("hus", d)
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
            if path == "/api/photo/stitch":
                return self._send(200, api_photo_stitch(d))
            if path == "/api/assistant":
                return self._send(200, api_assistant(d))
            if path == "/api/threads/import":
                return self._send(200, api_threads_import(d))
            if path == "/api/threads/delete":
                from stitchcraft_engine import threads
                return self._send(200, {"deleted": threads.delete_palette(str(d.get("id") or ""))})
            if path == "/api/threads/match":
                return self._send(200, api_threads_apply(d, snap=False))
            if path == "/api/threads/apply":
                return self._send(200, api_threads_apply(d))
            if path == "/api/threads/replace":
                return self._send(200, api_threads_replace(d))
            if path == "/api/threads/consumption":
                return self._send(200, api_threads_consumption(d))
            if path == "/api/garment/digitize":
                return self._send(200, api_garment_digitize(d))
            if path == "/api/export/preflight":
                from stitchcraft_engine import machine_compat
                design = d.get("design") if isinstance(d.get("design"), dict) else d
                check_design(design)
                try:
                    res = export_pipeline.export_dst(design)
                except export_pipeline.ExportError as e:
                    return self._send(422, e.to_dict())
                fn = machine_compat.filename_for(design.get("name"))
                return self._send(200, dict(machine_compat.preflight(res.data, fn, design.get("hoop")), dst_sha256=res.sha256, suggested_filename=fn))
            if path == "/api/report/sections":
                return self._send(200, api_report_sections(d))
            if path == "/api/evidence":
                from stitchcraft_engine import evidence
                rec = evidence.create(d); return self._send(200, {"record": rec, "status": evidence.status_for(rec["dst_sha256"], rec.get("design_name"))})
            if path == "/api/evidence/import":
                from stitchcraft_engine import evidence
                rec = evidence.import_record(d); return self._send(200, {"record": rec, "status": evidence.status_for(rec["dst_sha256"], rec.get("design_name"))})
            if path == "/api/image/isolate":
                return self._send(200, api_image_isolate(d))
            if path == "/api/image/quality":
                return self._send(200, api_image_quality(d))
            if path == "/api/image/validate":
                return self._send(200, api_image_validate(d))
            if path == "/api/image/bundle":
                data, info = api_image_bundle(d)
                if data is None:
                    return self._send(422, info)
                return self._send(200, data, "application/zip", {"Content-Disposition": 'attachment; filename="image-to-dst-bundle.zip"', "X-Bundle-Summary": base64.b64encode(json.dumps(info).encode()).decode()})
            if path == "/api/split":
                data, rep = api_split(d)
                return self._send(200, data, "application/zip", {"Content-Disposition": f'attachment; filename="{sheet._safe(d.get("name"))}-split.zip"',
                                                                  "X-Split-Report": base64.b64encode(json.dumps(rep).encode()).decode()})
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
