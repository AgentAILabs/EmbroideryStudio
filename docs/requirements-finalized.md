# StitchCraft AI - Finalized Requirements (v1, reviewed)

## A. Review of the master prompt (what I changed and why)
| # | Issue in prompt | Decision |
|---|---|---|
| 1 | Scope is a 3-5 year product (Wilcom/Hatch parity) | MVP = **"image/SVG -> editable objects -> simulate -> DST"**, nothing else. Everything else is Phase 2/3. |
| 2 | "Upload any PNG/JPG and get a professional design" | Photographic/shaded art cannot be auto-digitized well. MVP accepts **flat-colour artwork (<= 8 colours)** and says so. Poor input gets a clear warning, not a bad stitch file. |
| 3 | Beads, stones, sequins, zardosi, Maggam stone work | Out of stitch scope. Provide **"embellishment placeholder" objects** (position + marker) that export in a production sheet, not in the DST. |
| 4 | Python engine called from .NET | Run as a **separate containerised service** (FastAPI, job queue) behind the versioned JSON contract (`schema_version 1.0`, already in code). No in-process interop. |
| 5 | ASP.NET Core 10, Konva, MediatR, CQRS everywhere | Keep, but CQRS only where it pays (jobs, designs). Avoid ceremony for settings CRUD. |
| 6 | "Independent reader" for DST | Write own reader (done) **plus** cross-check with pyembroidery and Ink/Stitch output in CI. |
| 7 | Pull compensation / underlay "correct" values | These are fabric- and machine-specific. Ship **presets by fabric** (cotton, silk, georgette, velvet), editable, flagged "unverified" until stitched. |
| 8 | Missing: stabiliser/fabric profile, thread brand palettes, stitch-count/time estimate, trim rules | Added to MVP data model (FabricProfile, ThreadBrand). |
| 9 | Missing: Indian-market specifics | Added: Maggam border repeat tool (Phase 2), Telugu/Hindi/Devanagari lettering (Phase 2, needs font+satin outline research), blouse neckline/back templates, inch+mm hoops. |
| 10 | No auth model / tenancy | Email+password via ASP.NET Identity, per-user ownership; shop/team accounts Phase 2. |
| 11 | Windows desktop later | Keep web-first; design API so a Tauri/WebView2 shell can reuse it. |

## B. MVP functional requirements (release gate)
1. Upload SVG (full), PNG/JPG (flat colour, quantised), PDF (first page, vector only) with size/dimension limits.
2. Set real-world size (mm/inch) and see DPI warning. Never auto-stretch.
3. Auto-digitize: colour regions -> fills; thin strokes -> running; mid-width strokes -> satin. User can **override any object's stitch type**.
4. Object list with colour, type, order; move/scale/rotate/delete; undo/redo.
5. Properties: density, angle, stitch length, underlay on/off, pull comp, satin width.
6. Simulation driven by real stitch array (play/pause/step/speed, jumps, colour changes).
7. Hoop + machine profile (W, H, margin, max stitch). Block export on errors.
8. Export: DST, project JSON, preview PNG/SVG, production sheet (colour order, stitch count, size, estimated time).
9. Beginner mode (presets, plain-language warnings) and Professional mode (all controls).
10. Save/reopen projects; versions.

### MVP non-functional
- 100x100 mm design with <= 50k stitches digitized in < 15 s on a laptop CPU.
- No paid APIs, no GPU. Uploads validated (type sniffing, size, pixel count). Per-user file access.

## C. Embroidery quality rules the engine must enforce
- Stitch length 1.0-7.0 mm typical, hard stop at 12.1 mm (DST record). Warn < 0.3 mm.
- Satin: warn width < 1.0 mm (too narrow) and > 7 mm (loose; split recommended).
- Fill density default 0.4 mm row spacing; warn if penetrations/mm^2 exceed threshold.
- Sequence: underlay -> fill -> satin borders -> details; minimise colour changes only where layering allows.
- Trim if jump > 3 mm (configurable); anchor stitch at starts (done: stitch after every jump).
- No stitches outside source geometry beyond boundary tolerance.

## D. Phase plan
| Phase | Scope | Status |
|---|---|---|
| 3 | SVG -> run/satin/tatami -> DST, validator, round-trip, tests | **Done in /engine (26 tests passing)** |
| 4a | Raster pipeline: quantise, segment, contours, simplify, hole handling (OpenCV/NumPy) | next |
| 4b | Shapely offsets: fill pull-comp, inset underlay, satin from outline (skeleton) | next |
| 4c | Engine service (FastAPI + job queue), JSON contract tests | next |
| 2 (foundation) | Docker Compose, .NET API skeleton, Postgres schema, React shell + layout | after 4c |
| 5 | Konva editor, properties panel, simulation | |
| 6 | Export package, production sheet, project reopen | |
| 7 | Hardening, **physical stitch-out matrix**, docs | |

Note: I moved the engine ahead of the UI because quality of the stitch data is the product; a beautiful UI on bad stitches is worthless.

## E. Sprint 1 (done) / Sprint 2 (proposed)
Sprint 1: engine core, DST writer/reader, validator, SVG input, preview, CLI, tests - delivered.
Sprint 2: (1) install OpenCV/NumPy/Shapely/pyembroidery in a networked environment, add pyembroidery cross-check test; (2) raster quantise+contour pipeline with 5 test artworks; (3) satin-from-outline (skeleton/rails) for petals/letters; (4) FastAPI wrapper + JSON contract tests; (5) first physical stitch-out of flower.dst on the shop machine and record results in docs/testing/.

## F. Physical test matrix (must be run before any "production ready" claim)
Flower, 3 lettering heights (5/8/12 mm), logo, border, 4-colour design, 1.0/2.0/3.0 mm satin columns, 30x30 mm fill. Record: thread breaks, puckering, registration, trim behaviour, colour-change position, fabric, stabiliser, needle, speed.
