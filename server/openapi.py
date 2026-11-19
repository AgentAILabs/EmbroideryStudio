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
    ("post", "/api/export/exp"): ("Melco EXP export (software-verified: encoded here and read back with an independent library; never machine-tested; same gating as DST)", DESIGN_BODY, {"description": "exp bytes"}, ["400", "422"]),
    ("post", "/api/export/jef"): ("Janome JEF export (software-verified: encoded here and read back with an independent library; never machine-tested; same gating as DST)", DESIGN_BODY, {"description": "jef bytes"}, ["400", "422"]),
    ("post", "/api/export/pes"): ("Brother PES export (software-verified: encoded here and read back with an independent library; never machine-tested; same gating as DST)", DESIGN_BODY, {"description": "pes bytes"}, ["400", "422"]),
    ("post", "/api/export/xxx"): ("Singer XXX export (software-verified: encoded here and read back with an independent library; never machine-tested; same gating as DST)", DESIGN_BODY, {"description": "xxx bytes"}, ["400", "422"]),
    ("post", "/api/export/u01"): ("Barudan U01 export (software-verified: encoded here and read back with an independent library; never machine-tested; same gating as DST)", DESIGN_BODY, {"description": "u01 bytes"}, ["400", "422"]),
    ("post", "/api/export/sew"): ("Janome SEW export (software-verified: encoded here and read back with an independent library; never machine-tested; same gating as DST)", DESIGN_BODY, {"description": "sew bytes"}, ["400", "422"]),
    ("post", "/api/export/vp3"): ("Husqvarna VP3 (planned: returns 422) export (software-verified: encoded here and read back with an independent library; never machine-tested; same gating as DST)", DESIGN_BODY, {"description": "vp3 bytes"}, ["400", "422"]),
    ("post", "/api/export/hus"): ("Husqvarna HUS (planned: returns 422) export (software-verified: encoded here and read back with an independent library; never machine-tested; same gating as DST)", DESIGN_BODY, {"description": "hus bytes"}, ["400", "422"]),
    ("post", "/api/report"): ("Production report (three validation sections); html=true adds an HTML rendering", DESIGN_BODY, JSON200("report"), ["400"]),
    ("post", "/api/split"): ("Split an oversize design into hoopings with alignment marks (zip of DSTs)", DESIGN_BODY, {"description": "zip; header X-Split-Report"}, ["400"]),
    ("post", "/api/photo/stitch"): ("Photo Stitch Engine: tonal flow-field hatching -> validated DST, thread-texture preview from the decoded DST, photo validation (software only)", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("design, report, preview_png, validation, stitch_metrics, dst"), ["400"]),
    ("post", "/api/report/sections"): ("Five separate validation sections (source quality, preservation, stitch path, independent DST, physical) - never combined into one score", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("sections"), ["400"]),
    ("post", "/api/garment/digitize"): ("Garment photo -> thread-separated design (red/gold by hue, radial-satin rosettes, smooth border line, strays removed, angled leaf fills) -> validated DST; heuristic, software validation only", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("design, separation, dst, preflight, sections"), ["400"]),
    ("post", "/api/export/preflight"): ("Byte-level DST pre-flight (header layout, counts, extents, END record, file-name precautions) and a machine-safe file name; structural only, not a Ricoma acceptance test", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("verdict, checks, suggested_filename"), ["400", "422"]),
    ("get", "/api/presets"): ("Stitch-type presets (where the run / column / fill boundaries are); pass preset= and shapes= to the import / auto-digitize routes", None, JSON200("presets"), []),
    ("get", "/api/threads/palettes"): ("Thread palettes: the generic built-in one and the user's imported brand palettes", None, JSON200("palettes"), []),
    ("get", "/api/threads/palette"): ("One palette with its colours (?id=)", None, JSON200("colours"), ["400"]),
    ("post", "/api/threads/import"): ("Import a thread palette from CSV / JSON text (code, name, hex or r,g,b); stored in the palettes/ folder, never committed", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("palette, count, rejected"), ["400"]),
    ("post", "/api/threads/delete"): ("Delete an imported palette", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("deleted"), ["400"]),
    ("post", "/api/threads/match"): ("Nearest palette thread (CIEDE2000) for every colour of a design, with alternatives and a quality label", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("rows"), ["400"]),
    ("post", "/api/threads/apply"): ("Snap every design colour to its nearest palette thread; returns the recoloured design and the code map", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("design, map"), ["400"]),
    ("post", "/api/threads/replace"): ("Replace one colour by another in all objects", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("design, replaced"), ["400"]),
    ("post", "/api/threads/consumption"): ("Estimated top / bobbin thread use per colour (estimate, not measured)", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("rows"), ["400"]),
    ("post", "/api/assistant"): ("Digitizing assistant: applies a natural-language request (make borders satin, tatami for large areas, denser, fewer colour changes, cap / left-chest / denim, scale ...) to the design's real objects; rule-based, no external AI", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("design, applied, not_understood, before, after"), ["400"]),
    ("get", "/api/evidence"): ("Physical machine-validation status for a DST checksum (?sha=&name=): PENDING / INCOMPLETE / STALE / FAILED / PASSED_WITH_NOTES / PASSED", None, JSON200("status, record, missing"), ["400"]),
    ("get", "/api/evidence/checklist"): ("Physical test checklist, required fields and status values", None, JSON200("checklist, required, statuses"), []),
    ("get", "/api/evidence/records"): ("All stored (intact) evidence records", None, JSON200("records"), []),
    ("post", "/api/evidence"): ("Store a physical test record submitted by a person (never invents results; bound to the DST SHA-256)", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("record, status"), ["400"]),
    ("post", "/api/evidence/import"): ("Import an exported evidence record; refused when its record_sha256 does not match", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("record, status"), ["400"]),
    ("post", "/api/image/isolate"): ("Garment-photo motif isolation: probable embroidery vs fabric / folds / shadows / background, motif list, overlay, optional derived motif crop (heuristic - inspect the overlay)", {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}, JSON200("motifs, overlay_png, motif_png"), ["400"]),
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
