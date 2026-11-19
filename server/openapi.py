"""OpenAPI 3.0 description of the HTTP API (stage 1 of the migration plan: freeze the contract before anything is rebuilt).
The contract test (tests/test_openapi.py) fails when a route exists in app.py but not here, or the reverse."""
from __future__ import annotations

VERSION = "1.0.0"
ERR = {"description": "Refused / invalid", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
DESIGN_BODY = {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Design"}}}}
JSON200 = lambda desc, ref=None: {"description": desc, "content": {"application/json": {"schema": ({"$ref": ref} if ref else {"type": "object"})}}}

# (method, path) -> (summary, request body or None, success response, extra statuses)
ROUTES = {
    ("get", "/api/health"): ("Liveness", None, JSON200("ok"), []),
    ("get", "/api/font"): ("Built-in stroke font", None, JSON200("glyphs"), []),
    ("get", "/api/library"): ("Design library index", None, JSON200("designs"), []),
    ("get", "/api/library/{id}/{file}"): ("Library design file (thumb.svg | dst | esproj)", None, {"description": "file"}, ["404"]),
    ("get", "/api/templates"): ("Template catalogue", None, JSON200("templates"), []),
    ("get", "/api/machines"): ("Machine profile presets (none validated)", None, JSON200("machines"), []),
    ("get", "/api/fabrics"): ("Fabric profiles (all experimental)", None, JSON200("fabrics"), []),
    ("get", "/api/formats"): ("Output formats (DST only)", None, JSON200("formats"), []),
    ("get", "/api/openapi.json"): ("This document", None, JSON200("OpenAPI"), []),
    ("post", "/api/generate"): ("Design -> stitches (plan, or decoded DST file with decoded=true)", DESIGN_BODY, JSON200("stitches, objects, threads, stats, notes, issues, source", "#/components/schemas/Generated"), ["400"]),
    ("post", "/api/export/dst"): ("Validated DST export (refused unless decode-compare passes)", DESIGN_BODY, {"description": "DST bytes; headers X-SHA256, X-Request-Id"}, ["400", "422"]),
    ("post", "/api/export/package"): ("ZIP: DST, reports, preview, production sheet", DESIGN_BODY, {"description": "zip"}, ["400", "422"]),
    ("post", "/api/export/sheet"): ("Production sheet HTML", DESIGN_BODY, {"description": "html"}, ["400"]),
    ("post", "/api/export/svg"): ("Preview SVG", DESIGN_BODY, {"description": "svg"}, ["400"]),
    ("post", "/api/export/exp"): ("EXP (experimental, disabled unless enabled by the operator)", DESIGN_BODY, {"description": "exp bytes"}, ["400", "422"]),
    ("post", "/api/report"): ("Production report (three validation sections); html=true adds an HTML rendering", DESIGN_BODY, JSON200("report"), ["400"]),
    ("post", "/api/split"): ("Split an oversize design into hoopings with alignment marks (zip of DSTs)", DESIGN_BODY, {"description": "zip; header X-Split-Report"}, ["400"]),
    ("post", "/api/image/quality"): ("Source image quality assessment (resolution, sharpness, blur, noise, contrast, JPEG blocking, effective resolution, small-feature visibility, subject visibility) + recommendations", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("metrics, classification, workflow, recommendations"), ["400"]),
    ("post", "/api/image/validate"): ("Nine-pass image-to-DST validation (software only; physical = PENDING)", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("passes, remaining_risks, derived_images"), ["400"]),
    ("post", "/api/image/bundle"): ("ZIP: untouched original, inventory, overlay/difference images, validation report, DST, project", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, {"description": "zip"}, ["400", "422"]),
    ("post", "/api/quality"): ("8-category software quality score", DESIGN_BODY, JSON200("score, categories, issues"), ["400"]),
    ("post", "/api/travel"): ("Travel and trim analysis", DESIGN_BODY, JSON200("moves, verdicts, totals"), ["400"]),
    ("post", "/api/checklist"): ("15-item production checklist", DESIGN_BODY, JSON200("items"), ["400"]),
    ("post", "/api/machine/check"): ("Design vs the selected machine profile", DESIGN_BODY, JSON200("profile, issues"), ["400"]),
    ("post", "/api/autofix"): ("Safe automatic corrections", DESIGN_BODY, JSON200("design, log"), ["400"]),
    ("post", "/api/profile"): ("Apply fabric / category profile and / or optimise the sequence", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("design, log"), ["400"]),
    ("post", "/api/autodigitize"): ("Image -> checked, optimised design", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("design, log, checklist"), ["400"]),
    ("post", "/api/placements"): ("Left / right / neck placement set (zip)", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, {"description": "zip"}, ["400"]),
    ("post", "/api/import/dst"): ("Read a DST for viewing", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("stitches"), ["400"]),
    ("post", "/api/import/svg"): ("SVG -> objects", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("objects"), ["400"]),
    ("post", "/api/import/raster"): ("PNG/JPEG -> regions (optional erase strokes in source pixels)", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("objects, report"), ["400"]),
    ("post", "/api/enhance"): ("Upscale / sharpen an image", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("png, info"), ["400"]),
    ("post", "/api/dst/report"): ("Analyse an existing DST", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("report"), ["400"]),
    ("post", "/api/lettering"): ("TrueType lettering -> objects", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("objects"), ["400"]),
    ("post", "/api/template"): ("Build a template", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("objects"), ["400"]),
    ("post", "/api/to_manual"): ("Convert an object to editable manual stitches", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("objects"), ["400"]),
    ("post", "/api/tools/column-from-outline"): ("Satin column from an outline", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("rails"), ["400"]),
}
SCHEMAS = {
    "Error": {"type": "object", "required": ["error"], "properties": {"error": {"type": "string"}, "request_id": {"type": "string"}, "stage": {"type": "string"}, "code": {"type": "string"},
              "issues": {"type": "array", "items": {"type": "object", "properties": {"code": {"type": "string"}, "severity": {"type": "string", "enum": ["error", "warning", "info"]}, "message": {"type": "string"}}}}}},
    "Design": {"type": "object", "properties": {"name": {"type": "string", "maxLength": 200}, "hoop": {"type": "object", "properties": {"w": {"type": "number"}, "h": {"type": "number"}, "margin": {"type": "number"}}},
               "thread": {"type": "string"}, "fabric": {"type": "string"}, "stabiliser": {"type": "string"}, "machine": {"type": "object"}, "machine_profile": {"type": "object"},
               "decoded": {"type": "boolean", "description": "generate only: return stitches decoded from the DST file"},
               "objects": {"type": "array", "maxItems": 3000, "items": {"$ref": "#/components/schemas/Object"}}}},
    "Object": {"type": "object", "required": ["id", "type"], "properties": {"id": {"type": "string"}, "type": {"type": "string", "enum": ["fill", "satin", "column", "run", "text", "manual", "applique", "embellishment"]},
               "color": {"type": "string"}, "params": {"type": "object"}, "rings": {"type": "array"}, "points": {"type": "array"}, "rail1": {"type": "array"}, "rail2": {"type": "array"},
               "handles": {"type": "array", "description": "Bezier node handles [inX,inY,outX,outY] per vertex, absolute"}, "entry": {"type": "array"}, "exit": {"type": "array"}, "group": {"type": "string"}}},
    "Generated": {"type": "object", "properties": {"source": {"type": "string", "enum": ["plan", "dst-file"]}, "stitches": {"type": "array", "description": "[x_mm, y_mm, cmd(0 stitch,1 jump,2 trim,3 colour,4 end), thread, objectIndex]"},
                  "objects": {"type": "array", "items": {"type": "string"}}, "threads": {"type": "array", "items": {"type": "string"}}, "stats": {"type": "object"}, "notes": {"type": "array"}, "issues": {"type": "array"}}},
}


def spec() -> dict:
    paths = {}
    for (method, path), (summary, body, ok, extra) in ROUTES.items():
        op = {"summary": summary, "responses": {"200": ok, "429": {"description": "Rate limited; Retry-After header"}, "500": {"description": "Unexpected error; the body carries request_id"}}}
        for code in extra:
            op["responses"][code] = ERR if code != "404" else {"description": "not found"}
        if body:
            op["requestBody"] = body
        paths.setdefault(path, {})[method] = op
    return {"openapi": "3.0.3", "info": {"title": "EmbroideryStudio API", "version": VERSION,
            "description": "Design JSON in, validated DST out. All validation is software validation; no machine compatibility is claimed."},
            "paths": paths, "components": {"schemas": SCHEMAS}}
