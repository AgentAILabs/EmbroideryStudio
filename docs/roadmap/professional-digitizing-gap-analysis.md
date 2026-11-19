# Professional digitizing platform - audit against the requirements (2026-11-19)

Legend: ✅ exists and tested · 🟡 partial · ❌ missing · 🧪 needs outside data / a machine. Nothing here is physically machine-validated.

| # | Requirement | State | Evidence / gap |
|---|---|---|---|
| 1 | Image upload: PNG, JPG/JPEG, SVG, transparent PNG | ✅ | `raster.py`, `svg_input.py`; alpha handled |
| 1 | BMP upload | ✅ | converted to PNG server-side (needs Pillow); the original BMP is what is hashed / reported |
| 1 | Background removal, colour regions, outlines, overlapping objects | 🟡 | background = dominant border colour; thick/thin split; no overlap separation of translucent layers |
| 1 | Object recognition: shapes | 🟡 | circle / ellipse / rectangle / square / rounded rectangle (`smart_design.py`); **no general polygon / star recognition** |
| 1 | Text detection | ❌ | no OCR; letters are traced as shapes (stroke satin handles simple strokes) |
| 1 | Photographs | ✅ | Photo Stitch engine, garment-photo isolation, thread separation |
| 2 | Stitch types: satin, tatami, running, bean/triple, zigzag, motif, cross, manual, centre-run, edge-run | ✅/🟡 | `design.py`, `stitches.py` (run styles single/bean/zigzag/motif, fills tatami/contour/cross, underlays centre/edge/zigzag). **E-stitch fill and a distinct triple-run style are missing** |
| 2 | Controls: length, density, angle, pull/push comp, underlay, split, corners, overlap, short-stitch filter, tie-in/off, start/end | ✅ | params + machine settings (`micro_clean`, locks, entry/exit points) |
| 3 | Auto stitch-type assignment per object | ✅ | thickness/aspect rules, presets, profiles |
| 4 | Editor: zoom/pan, select/move/rotate/resize, node editing + Bezier, group, layers, properties, undo/redo, copy/paste, align/distribute, rulers/grid, stitch direction + sequence views | ✅ (audit item by item before claiming) | `web/app.js` (~1.4 k lines), e2e covers most |
| 5 | Lettering: TrueType shaping, fonts, spacing, curve, rotation | ✅/🟡 | `lettering.py`, built-in stroke font, uploaded fonts; circular text / monogram to verify |
| 6 | Thread colours: palette, matching, custom palettes, replacement, consumption | ✅/🧪 | `threads.py`: import-your-own CSV/JSON palettes (stored in `palettes/`, git-ignored), CIEDE2000 matching (checked against Sharma et al. reference values), snap design to palette with codes recorded, colour replacement, consumption estimate (also in the production report). **No brand chart is bundled (licensed); Madeira / Isacord / Gunold / Brother codes exist only if you import your own charts** |
| 7 | Simulator: 2D thread-texture preview, 3D WebGL viewer, fabrics | ✅/🟡 | WebGL 3D viewer with procedural weave; 2D stitch view paints the chosen fabric (cotton, denim, polyester, canvas, silk, velvet, knit, net, thick, ...); photo thread-texture preview. Procedural textures, not photographs of fabric; no real thread physics |
| 8 | Export: DST | ✅ | validated in software (decode-compare, independent decoder, pyembroidery in CI) |
| 8 | Export: EXP, JEF, PES, XXX, U01, SEW | 🟡 **software-verified** | `encoders.py` (own code, layouts per pyembroidery readers/writers, MIT attribution in NOTICE.md); every file read back with pyembroidery and every stitch position compared (`tests/test_encoders.py`, and at export time); same gating as DST; formats dialog + `POST /api/export/<fmt>`. **Not machine-tested**; PES is the version-1 layout with the PEC block only |
| 8 | Export: VP3, HUS | ❌ | not implemented (VP3 per-colour blocks + thread chart; HUS compression) |
| 9 | Optimization advisor, apply individually/auto | ✅ | `advisor.py`, `/api/advisor`, `/api/advisor/apply`, dialog: measured density, short / long stitches, missing underlay, tiny details, avoidable colour changes (layer-safe regrouping), trims / jumps, stitch count, pull compensation; Apply per item or all; real undoable edits |
| 10 | Production info: stitches, colour changes, trims, size, thread use, time, complexity, hoop | ✅ | production report incl. thread use and a documented complexity rating (Simple / Moderate / Complex / Very complex) |
| 11 | Workspace layout, 10-step workflow | ✅/🟡 | wizard + dialogs; some steps are separate dialogs |
| 12 | AI digitizing assistant applying real edits | ✅ rule-based | `assistant.py`, `POST /api/assistant`, dialog (More menu): borders -> satin, tatami for large areas, density up/down, fewer colour changes, small lettering, cap, left chest, reduce stitch count, fabric profiles (denim ...), scale, remove tiny details, convert (opens the image chooser). It edits real objects as one undo step, reports before/after stitches, lists what it did not understand. **No external AI / LLM** (owner decision); presets are unverified starting values |
| 13 | Architecture, background jobs, large uploads | ✅/🟡 | modules separated; `jobs.py` thread-pool job queue (autodigitize, photo, garment, raster, isolate) with status polling, cancel (result discarded) and TTL; the UI shows a working toast; uploads are size-limited with time budgets. In-memory jobs (lost on restart), no progress percentage |

Hard constraints carried over: stdlib Python server + vanilla JS, no migration; Pillow / NumPy optional with a pure-Python fallback; nothing installed on the office laptop without approval; no physical validation claimed without machine evidence; no fabricated thread-chart data.

## Still open after this round (nothing here is claimed)
VP3 and HUS export; OCR / real text recognition; general polygon / star recognition; brand thread charts (user must import their own); hand-digitized reference motif library (leaf, six-petal flower, fern) for photo conversions; any machine validation of any format or design (**NOT DONE**).
