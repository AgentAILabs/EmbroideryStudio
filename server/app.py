"""EmbroideryStudio API + static host (stdlib only).  python3 server/app.py [port]
POST /api/generate        design JSON -> stitches, stats, issues
POST /api/export/dst      design JSON -> .dst  (blocked on validation errors)
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
import base64, json, os, re, sys, hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from stitchcraft_engine.design import generate, run_checks, FABRICS, machine, empty_stats            # noqa: E402
from stitchcraft_engine.dst import write_dst, read_dst                          # noqa: E402
from stitchcraft_engine.model import Cmd                                        # noqa: E402
from stitchcraft_engine.svg_input import parse_svg, UnsupportedSvg              # noqa: E402
from stitchcraft_engine.raster import digitize_raster, RasterUnavailable        # noqa: E402
from stitchcraft_engine import templates                                        # noqa: E402
from stitchcraft_engine.outline import column_from_outline                      # noqa: E402
import sheet                                                                   # noqa: E402

WEB = ROOT / "web"
LIB = ROOT / "designs" / "library"
LIB_FILES = {"thumb.svg": ("thumb.svg", "image/svg+xml"), "dst": ("dst", "application/octet-stream"), "esproj": ("esproj", "application/json")}
MAX_BODY = 25 * 1024 * 1024
MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json"}


def compact(pattern):
    """Stitches as parallel arrays for fast transfer: [x,y,cmdcode,thread]; cmd 0=stitch 1=jump 2=trim 3=colour 4=end."""
    code = {Cmd.STITCH: 0, Cmd.JUMP: 1, Cmd.TRIM: 2, Cmd.COLOR_CHANGE: 3, Cmd.END: 4}
    return [[round(s.x, 3), round(s.y, 3), code[s.cmd], s.thread] for s in pattern.stitches]


def issues(rep):
    return [{"code": i.code, "severity": i.severity, "message": i.message, "index": i.index} for i in rep.issues]


MAX_OBJECTS, MAX_POINTS, MAX_SVG = 3000, 400_000, 5 * 1024 * 1024


def check_design(d):
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
    return {"stitches": compact(pattern), "threads": [t.hex for t in pattern.threads], "stats": st,
            "notes": notes, "issues": issues(rep)}


def api_dst(d):
    check_design(d)
    pattern, notes, st = generate(d)
    rep = run_checks(d, pattern)
    if not rep.ok:
        return None, {"error": "Export blocked", "issues": issues(rep)}
    res = write_dst(pattern, trim_jumps=machine(d)["trim_jumps"])
    back = read_dst(res.data)
    if not back.ends_properly or back.color_changes != int(back.header["CO"]):
        return None, {"error": "DST round-trip check failed"}
    return res, None


def api_preview_svg(d):
    from stitchcraft_engine.preview import preview_svg
    pattern, _, _ = generate(d)
    h = d.get("hoop", {})
    return preview_svg(pattern, float(h.get("w", 0)), float(h.get("h", 0))).encode()


def api_view_dst(d):
    """Read an existing .dst so it can be inspected/simulated (view only)."""
    f = read_dst(base64.b64decode(d["data"]))
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


def api_svg(d):
    from stitchcraft_engine.pipeline import digitize_svg  # noqa: F401  (ensures module import works)
    txt = d["svg"]
    if not isinstance(txt, str) or len(txt) > MAX_SVG:
        raise ValueError("SVG too large (limit 5 MB)")
    if "<!ENTITY" in txt or "<!DOCTYPE" in txt.upper():
        raise ValueError("SVG with DOCTYPE/ENTITY declarations is rejected for safety; re-save it as plain SVG")
    if txt.lstrip()[:4] == "%PDF":
        raise ValueError("PDF import is not supported yet; export the artwork as SVG")
    doc = parse_svg(txt)
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


def api_raster(d):
    raw = base64.b64decode(d["data"])
    if raw[:4] == b"%PDF":
        raise ValueError("PDF import is not supported yet; export the artwork as SVG or PNG")
    objs, notes, size = digitize_raster(raw, float(d.get("width_mm", 80)), int(d.get("colors", 6)))
    return {"objects": objs, "notes": notes, "width_mm": size[0], "height_mm": size[1]}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
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
        if path == "/api/health":
            return self._send(200, {"ok": True, "fabrics": FABRICS})
        f = (WEB / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if WEB not in f.parents and f != WEB or not f.is_file():
            return self._send(404, {"error": "not found"})
        self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._send(413, {"error": "body too large"})
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
            path = self.path.split("?")[0]
            if path == "/api/generate":
                return self._send(200, api_generate(d))
            if path == "/api/export/dst":
                res, err = api_dst(d)
                if err:
                    return self._send(422, err)
                name = sheet._safe(d.get("name"))
                return self._send(200, res.data, "application/octet-stream",
                                  {"Content-Disposition": f'attachment; filename="{name}.dst"', "X-SHA256": res.sha256})
            if path == "/api/tools/column-from-outline":
                ring = d.get("ring")
                if not isinstance(ring, list) or len(ring) > 5000:
                    raise ValueError("ring must be a list of [x, y] points (max 5000)")
                return self._send(200, column_from_outline([(float(a), float(b)) for a, b in ring]))
            if path == "/api/template":
                return self._send(200, {"objects": templates.build(d.get("id", ""), d.get("params") or {}, d.get("color", "#c8102e"))})
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
            self._send(404, {"error": "not found"})
        except (UnsupportedSvg, RasterUnavailable, ValueError, KeyError, TypeError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"internal error: {type(e).__name__}"})

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
