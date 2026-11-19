# Professional digitizing platform - audit against the requirements (2026-11-19)

Legend: ✅ exists and tested · 🟡 partial · ❌ missing · 🧪 needs outside data / a machine. Nothing here is physically machine-validated.

| # | Requirement | State | Evidence / gap |
|---|---|---|---|
| 1 | Image upload: PNG, JPG/JPEG, SVG, transparent PNG | ✅ | `raster.py`, `svg_input.py`; alpha handled |
| 1 | BMP upload | ❌ | upload gate accepts PNG/JPEG only (Pillow can read BMP) |
| 1 | Background removal, colour regions, outlines, overlapping objects | 🟡 | background = dominant border colour; thick/thin split; no overlap separation of translucent layers |
| 1 | Object recognition: shapes | 🟡 | circle / ellipse / rectangle / square (`smart_design.py`); no rounded rectangle / polygon / star |
| 1 | Text detection | ❌ | no OCR; letters are traced as shapes (stroke satin handles simple strokes) |
| 1 | Photographs | ✅ | Photo Stitch engine, garment-photo isolation, thread separation |
| 2 | Stitch types: satin, tatami, running, bean/triple, zigzag, motif, cross, manual, centre-run, edge-run | ✅/🟡 | `design.py`, `stitches.py` (run styles single/bean/zigzag/motif, fills tatami/contour/cross, underlays centre/edge/zigzag). **E-stitch fill and a distinct triple-run style are missing** |
| 2 | Controls: length, density, angle, pull/push comp, underlay, split, corners, overlap, short-stitch filter, tie-in/off, start/end | ✅ | params + machine settings (`micro_clean`, locks, entry/exit points) |
| 3 | Auto stitch-type assignment per object | ✅ | thickness/aspect rules, presets, profiles |
| 4 | Editor: zoom/pan, select/move/rotate/resize, node editing + Bezier, group, layers, properties, undo/redo, copy/paste, align/distribute, rulers/grid, stitch direction + sequence views | ✅ (audit item by item before claiming) | `web/app.js` (~1.4 k lines), e2e covers most |
| 5 | Lettering: TrueType shaping, fonts, spacing, curve, rotation | ✅/🟡 | `lettering.py`, built-in stroke font, uploaded fonts; circular text / monogram to verify |
| 6 | Thread colours: palette, matching, custom palettes, replacement, consumption | ✅/🧪 | `threads.py`: import-your-own CSV/JSON palettes (stored in `palettes/`, git-ignored), CIEDE2000 matching (checked against Sharma et al. reference values), snap design to palette with codes recorded, colour replacement, consumption estimate (also in the production report). **No brand chart is bundled (licensed); Madeira / Isacord / Gunold / Brother codes exist only if you import your own charts** |
| 7 | Simulator: 2D thread-texture preview, 3D WebGL viewer, fabrics | ✅/🟡 | `preview.py`, `web` 3D viewer, photo thread-texture; fabric backgrounds partly |
| 8 | Export: DST | ✅ | validated in software (decode-compare, independent decoder, pyembroidery in CI) |
| 8 | Export: EXP, JEF, PES, XXX, U01, SEW | 🟡 **software-verified** | `encoders.py` (own code, layouts per pyembroidery readers/writers, MIT attribution in NOTICE.md); every file read back with pyembroidery and every stitch position compared (`tests/test_encoders.py`, and at export time); same gating as DST; formats dialog + `POST /api/export/<fmt>`. **Not machine-tested**; PES is the version-1 layout with the PEC block only |
| 8 | Export: VP3, HUS | ❌ | not implemented (VP3 per-colour blocks + thread chart; HUS compression) |
| 9 | Optimization advisor, apply individually/auto | 🟡 | quality report, travel report, checklist, auto-fix; no per-recommendation "apply" buttons for all items |
| 10 | Production info: stitches, colour changes, trims, size, thread use, time, complexity, hoop | ✅/🟡 | production report; complexity rating missing |
| 11 | Workspace layout, 10-step workflow | ✅/🟡 | wizard + dialogs; some steps are separate dialogs |
| 12 | AI digitizing assistant applying real edits | ❌ | not present |
| 13 | Architecture, background jobs, large uploads | 🟡 | modules are separated; server is threaded stdlib; long operations are synchronous with time budgets (no job queue) |

Hard constraints carried over: stdlib Python server + vanilla JS, no migration; Pillow / NumPy optional with a pure-Python fallback; nothing installed on the office laptop without approval; no physical validation claimed without machine evidence; no fabricated thread-chart data.
