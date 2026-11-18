# Project status (audited against code + tests)
Legend: ✅ done & tested · 🟡 partial · ⏸ deferred (reason given) · 🧪 needs a physical machine / external input · 🔬 written but only runs in CI

Verification: `./tools/run_tests.sh` (engine + studio suites; the pyembroidery cross-check and the image-import tests skip themselves where the optional libraries are missing),
plus `tools/e2e_ui.js` – 24 end-to-end browser steps (draw every tool, templates, convert, patterns, undo/redo, simulation, every export,
save/reopen, SVG + PNG import, versions) with zero page errors / HTTP 5xx.

## A. Review decisions (requirements §A)
| # | Item | Status | Evidence / note |
|---|---|---|---|
| 1 | MVP = image/SVG → objects → simulate → DST | ✅ | editor + engine + DST |
| 2 | Raster: flat colour ≤ 8 colours, warn on poor input | ✅ | cap 8, low-DPI and colour-limit warnings, 5 artwork tests incl. hole stays empty |
| 3 | Bead/stone/sequin = placeholders, on production sheet, not in DST | ✅ | DST bytes identical with/without them (test) |
| 4 | Engine as separate service behind versioned JSON contract | ✅ | HTTP service, `schema_version` contract tests; ⏸ job queue (not needed at this scale) |
| 5 | .NET / MediatR / Konva | ⏸ | replaced by Python stdlib service + canvas editor: no installs, same contract |
| 6 | Independent DST reader + pyembroidery cross-check in CI | ✅ | own reader fixed a long-jump bug; **the CI cross-check found that the writer had X and Y bit tables swapped (every DST was transposed) – fixed, pinned by hand-written byte vectors**; the cross-check runs in CI only (pyembroidery is not installed here) |
| 7 | Fabric presets, flagged unverified | ✅ / 🧪 | six presets; values unverified until stitched |
| 8 | FabricProfile, stabiliser, time estimate, trim rules | ✅ | stabiliser field → sheet; ⏸ thread brand charts (licensed data; generic hex palette) |
| 9 | Indian-market: Maggam repeat, neckline templates, inch hoops | ✅ | repeat tool, border templates, neckline guides in inches (generic proportions); ⏸ Telugu/Hindi lettering (needs font files + Indic shaping) |
| 10 | Auth / per-user ownership | ⏸ | single-user local tool; belongs to a hosted version |
| 11 | Windows desktop shell | ⏸ | API reusable; do after the stitch-out proves the engine |

## B. MVP functional (release gate)
| # | Item | Status | Note |
|---|---|---|---|
| 1 | Upload SVG / PNG / JPG / PDF first page, limits | 🟡 | SVG, PNG, JPG ✅ with limits + safety; **PDF ⏸** (rejected with a clear message; needs a PDF vector parser) |
| 2 | Real-world size, DPI warning, never auto-stretch | ✅ | |
| 3 | Auto-digitize + per-object stitch-type override | ✅ | convert fill/satin/run/column; shape → column |
| 4 | Object list, move/scale/rotate/delete, undo/redo | ✅ | |
| 5 | Properties | ✅ | |
| 6 | Simulation from real stitch array incl. jumps + colour changes | ✅ | jumps drawn dashed, toggle |
| 7 | Hoop + machine profile, block export on errors | ✅ | |
| 8 | Export DST, project, preview PNG/SVG, production sheet, package | ✅ | |
| 9 | Beginner / Pro | ✅ | |
| 10 | Save/reopen, versions | ✅ | versions are per-browser |

## C. Quality rules
| Rule | Status |
|---|---|
| Stitch 1–7 mm typical, hard stop 12.1, warn < 0.3 | ✅ |
| Satin width warn <1 / >7 (+ auto-split) | ✅ |
| Density warning | ✅ |
| Sequence underlay → fill → satin → details | ✅ underlay first; warning when an outline/lettering is stitched before a fill it overlaps |
| Trim if jump > 3 mm (configurable), anchor stitches | ✅ |
| No stitches outside source geometry beyond tolerance | ✅ general test (fill, 4 angles × pull comp), satin-from-outline, concave contour |
| Colour sequence valid, returning to an earlier colour allowed | ✅ **bug fixed this round** (red→blue→red used to block export) |

## D. Phases
| Phase | Status |
|---|---|
| 3 engine | ✅ |
| 4a raster pipeline | ✅ |
| 4b offsets / outline | ✅ pure-Python inset (edge underlay, contour), fill pull-comp, satin-from-outline; ⏸ Shapely (robust inset) |
| 4c service + contract tests | ✅ |
| 2 foundation | 🟡 Dockerfile/compose written + statically tested – **not built** (no Docker daemon here); .NET/Postgres/React ⏸ |
| 5 editor + simulation | ✅ |
| 6 export package, sheet, reopen | ✅ |
| 7 hardening, physical matrix, docs | 🟡 user guide, architecture, test pack (11 designs), procedure ✅; 🧪 **stitching the pack is the remaining gate** |

## E. Sprint 2
| Item | Status |
|---|---|
| pyembroidery cross-check | ✅ ran in CI; found + fixed the X/Y swap |
| Raster 5 test artworks | ✅ |
| Satin-from-outline | ✅ (one column per shape; refuses branches/blobs/curls) |
| Service + contract tests | ✅ |
| First physical stitch-out | 🧪 yours |

## Roadmap items deliberately not built (with reason)
| Item | Why |
|---|---|
| PES / JEF writers | thread colours are indices into vendor palettes (65 / 78 colours) I cannot reproduce; wrong colours are worse than no file. **EXP is done** (no palette; CI-validated) |
| PDF import | needs a PDF vector parser (nothing may be installed here) |
| TrueType + Telugu/Devanagari lettering | needs font files and Indic shaping rules |
| Thread brand charts | licensed colour data |
| Bezier node handles | spline "Smooth curve" covers curves; handles are a UX upgrade |
| Hoop split, stitch-level editing, gradient/stipple/motif fills | separate large features, not on the MVP gate |
| Accounts, cloud library, Tauri shell | hosted/desktop product phase |

## Library + 3D (this round)
✅ 12 original motifs (`designs/library`), each with zero warnings/notes, ≤ 4 colours, DST round trip, thumbnail; Library panel; WebGL 3D viewer verified by reading real pixels in headless Chromium (SwiftShader).
Found and fixed along the way: tatami joined row segments 0.156 mm apart under pull compensation (now pruned); dense smoothed vertices became hundreds of tiny stitches (now thinned);
self-crossing outlines passed every stitch check (now flagged); colour strings were not validated (now are); the Step button always jumped to the end and the slider re-read its own overwritten value; an invisible canvas ate editor clicks (`[hidden]`).
🧪 None of the library designs has been stitched on a machine. ⏸ Not done: importing other people's finished designs/photos (deliberately - not a source this project converts).

## Trims (previous round)
Before: no lock stitches, no trim before a colour change or the end, and a satin column after its underlay often trimmed inside itself.
Now: tie-off → trim → jump → tie-in at every thread cut, configurable (lock length, trim at colour change/end, trim jumps, trim distance, smart direction),
appliqué passes staggered, runs started at the nearer end when that avoids a trim (test pack: 138 → 112 trims, never worse on any design). Pinned by exact-sequence
tests, geometry tests (locks stay inside the stitched geometry, 0.3 mm to lock length), DST-level tests (exactly N trim jumps before colour change and end),
and a CI cross-check that reads the same files with pyembroidery (it sees exactly one TRIM per trim we write, and identical stitch sequences including the lock stitches). 🧪 **Not yet proven on a machine** - design 12 in the test pack exists for that.

## DST axis bug (found by the CI cross-check; fixed)
The first DST writer used swapped X/Y bit tables. Our own reader used the same tables, so every round-trip test passed while a standard reader
saw the design transposed (rotated 90° and mirrored). **Any `.dst` generated before this fix is wrong – delete it and regenerate** (the test pack,
`engine/samples/flower.dst` and the zips sent earlier were regenerated). Guarded by byte vectors written by hand from the layout (not derived from
the code's tables) and by `tests/test_crosscheck.py` in CI. What is still unproven: behaviour on a physical machine.

## Known limits (honest)
* Nothing has been stitched on a machine; fabric presets, trim-jump default and time estimate are unverified.
* Satin-from-outline gives one column per shape; strongly curved shapes may show slightly uneven stitch angle at tight bends (tested: S-curve, banana, L within 6° mean).
* Contour fill falls back to tatami (with a note) for shapes with holes or that it cannot inset to the centre.
* Versions and autosave live in the browser only.
