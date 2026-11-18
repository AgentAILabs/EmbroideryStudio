# Architecture

```
 browser (web/app.js, canvas)  ──JSON over HTTP──>  server/app.py (stdlib)  ──calls──>  engine/stitchcraft_engine (pure Python)
        edits the design document                    validation, limits, zip/sheet          design -> stitches -> validate -> DST
```
**The engine is the single source of truth for stitches.** The browser only edits the design document and draws what the engine returns
(plus object outlines in the Design view). Zero third-party runtime dependencies (Pillow/NumPy optional for image import).

## Design document (the contract the UI edits)
```json
{ "name": "...", "hoop": {"w": 100, "h": 100, "margin": 3}, "fabric": "cotton", "stabiliser": "cut-away",
  "machine": {"max_stitch": 7, "min_stitch": 0.3, "trim_distance": 3, "trim_jumps": 3},
  "objects": [ { "id": "o1", "type": "fill", "color": "#c8102e", "...": "..." } ] }
```
Millimetres, y down, origin at the hoop centre. Common object fields: `id, type, name, color, hidden, guide, smooth`.

| type | geometry | params |
|---|---|---|
| fill | `rings` (even-odd, holes allowed) | angle, spacing, stitch_len, underlay (none/tatami/edge/edge+tatami), pull_comp, pattern (tatami/contour/cross), cross_size |
| satin | `points` centre line | width, spacing, underlay, pull_comp, auto_split |
| column | `rail1`, `rail2` | spacing, underlay, pull_comp, auto_split |
| run | `points`, `closed` | stitch_len |
| text | `text, height, x, y` | spacing, width, underlay, pull_comp, auto_split |
| applique | `rings` | width, spacing, stitch_len, cover_color |
| embellishment | `points`, `kind` (bead/stone/sequin), `size_mm` | – (never stitched) |

`guide: true` or `hidden: true` objects are not stitched. Stitch order = object order.

## Engine modules (`engine/stitchcraft_engine`)
`preview.py` preview + compact thumbnails · `design.py` design → stitches (+ stats, order notes, machine profile) · `stitches.py` generators (running, satin, tatami, contour, cross, split) ·
`geometry.py` (inset, smooth) · `outline.py` satin-from-outline · `templates.py` · `raster.py` · `svg_input.py` · `font.py` ·
`builder.py` objects → stitch commands (jumps, trims, colour changes) · `validate.py` quality rules · `dst.py` Tajima DST writer + independent reader · `exp.py` Melco EXP writer · `preview.py`.

Data flow: `generate(design)` → `Pattern` (stitch list, versioned JSON contract `schema_version 1.0`) → `run_checks` → `write_dst` → read back and compared (round-trip) before any file is offered.

## Web (`web/`)
`app.js` editor (canvas) · `viewer3d.js` zero-dependency WebGL thread viewer (loaded before `app.js`): each stitch is a ribbon with cylinder shading and a Kajiya-Kay sheen, later stitches higher; orbit/pan/zoom; progress follows the simulation slider.
The Library panel is a modal fed by `/api/library`. Front-end mistakes the Python tests cannot see are pinned by static tests (`FrontEndRegressionGuards`) and two browser scripts: `tools/e2e_ui.js` and `tools/e2e_library_3d.js` (reads real WebGL pixels).

## Library (`designs/library/`)
`tools/make_library.py` draws every design from code and refuses to write one that has any engine warning or note, more than 4 colours, or fails the DST round trip.
Engine behaviours added while drawing it: fill rows shorter than the minimum stitch are skipped and sub-0.3 mm stitches pruned; dense smoothed vertices are thinned in running stitches; self-crossing fill/appliqué outlines are flagged; colours are validated.

## Server (`server/`)
`app.py` HTTP + static files, limits (25 MB body, 3000 objects, 400k points, 5 MB SVG, PNG/JPEG sniffing, DOCTYPE rejected) · `sheet.py` production sheet + export package.

| Endpoint | Purpose |
|---|---|
| POST /api/generate | design → stitches, stats, issues, notes |
| POST /api/export/dst · /exp · /package · /sheet · /svg | exports (blocked on validation errors) |
| POST /api/import/svg · /raster · /dst | imports |
| POST /api/tools/column-from-outline | shape → two rails, or 400 with the reason |
| GET /api/templates · POST /api/template | template catalogue / instantiate |
| GET /api/library · GET /api/library/<id>/thumb.svg · /dst · /esproj | motif library (only ids listed in `designs/library/index.json`) |
| GET /api/font · /api/health | glyphs / liveness |

Errors are JSON 4xx with `{"error": ...}`; unexpected failures are 500 with no internals.

## Key decisions
* Python stdlib service + canvas editor instead of .NET/React: no installs, same versioned contract; revisit if a .NET deployment is required.
* Validation blocks export on errors; every DST is read back and checked.
* Anything unproven on a machine is labelled so (fabric presets, trim jumps, estimated time).
* Refuse rather than guess (satin-from-outline, SVG features, bad images).

## Tests
`python3 -m unittest discover -s engine/tests` and `-s tests` (engine behaviour, HTTP round trips, geometry quality, safety, performance, static front-end guard, test-pack validity).
`tests/test_crosscheck.py` compares our DST with pyembroidery's reader and runs only where it is installed (CI).
