# Project status (audited against code + tests)
Legend: ✅ done & tested · 🟡 partial · ⏸ deferred (reason given) · 🧪 needs a physical machine / external input · 🔬 written but only runs in CI

Verification: `./tools/run_tests.sh` (engine + studio suites; the pyembroidery cross-check and the image-import tests skip themselves where the optional libraries are missing),
plus `tools/e2e_ui.js` – 24 end-to-end browser steps (draw every tool, templates, convert, patterns, undo/redo, simulation, every export,
save/reopen, SVG + PNG import, versions) with zero page errors / HTTP 5xx.

## A. Review decisions (requirements §A)
| # | Item | Status | Evidence / note |
|---|---|---|---|
| 1 | MVP = image/SVG → objects → simulate → DST | ✅ | editor + engine + DST |
| 2 | Raster: flat colour ≤ 8 colours, warn on poor input | ✅ | quality pipeline (draft/standard/high), import dialog + report, objective benchmark `tools/image_bench.py`: mean IoU 0.949 vs 0.682 legacy, trims -89%, warnings 44 → 4 |
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


## DST quality round (analysis of 20 commercial files)
| Item | State | Evidence |
|---|---|---|
| Real-world DST reading (EOF 0x1A) | ✅ | `tests/test_dst_quality.py` TolerantReaderTests; 20/20 files read |
| Column underlay 0.5 mm stitches | ✅ fixed | scroll_pair 2,114 → 1,508 stitches, short stitches 28.7 % → 1.3 % |
| Tatami end stubs, satin-tip micro stitches | ✅ fixed | stub test, taper test |
| Lock stitch 1.0 mm default | ✅ | matches production files; clamps unchanged |
| Thread weight presets 40 wt / 60 wt / 120/2 | ✅ | spacing 0.40 / 0.30 / 0.22 mm measured on generated output |
| Six-stage verifier + API + UI Quality check | ✅ | tests + e2e; all library designs without FAIL |
| Header overflow (Export DST clipped) | ✅ fixed | e2e checks visibility at 1500 and 1100 px |
| v1 peacock kept byte-identical | ✅ | `designs/peacock_arch/v1_tested`, hash pinned in tests |
| Stitch-out of v2 / fine_120 | ⏳ not done | needs the machine |

## Placement sets (left / right / neck)
| Item | State | Evidence |
|---|---|---|
| Generic transform: scale, true mirror (fill angles mirrored), rotate | ✅ | `tests/test_placements.py` TransformTests |
| Named set per placement, size per file, zip + manifest + per-file verification | ✅ | PackageTests, e2e step |
| Auto-correction with log (fit, centre, specks, hairlines, duplicates, density relief) | ✅ | AutofixTests |
| Failing placement is reported, never shipped | ✅ | PackageTests |
| Which sleeve gets which file | user decision | documented; confirm on the garment |

## Digitizing standard (spec sections 1-13) - see `docs/digitizing-standard.md`
| Item | State | Evidence |
|---|---|---|
| Fabric + category profiles (density, underlay ladder, pull comp, run length) | ✅ | `tests/test_digitizing_standard.py` ProfileTests |
| Zig-zag and edge+zig-zag underlay | ✅ | UnderlayTests |
| Stitch shortening on curves | ✅ | ShorteningTests |
| Region-ordered fills | ✅ default on | RegionFillTests; ring 93 → 20 trims; bench trims -72 %; all delivered DSTs byte-identical |
| Dependency-aware sequence optimisation | ✅ | SequenceTests |
| 15-item checklist + server-side export gate | ✅ | ChecklistTests, e2e |
| Auto digitize wizard (6 steps) | ✅ | e2e step |
| Colour sequence CSV, machine test record | ✅ | ChecklistTests, sheet |
| Push compensation (fills + columns), overlap cutting with under-lap, zig-zag style | ✅ | `tests/test_overlap_push.py`; lotus -38 % stitches with cutting |
| Stitch-out approval | ⏳ | needs the machine |

## Code review 2026-11-19 + partial items
| Item | State | Evidence |
|---|---|---|
| 9 review findings (full-length stitch with end_at_start + edge underlay, motif containment / layering, cubic 2-opt, closed satin ring opened by auto-fix, density relief overriding user values, end_at_start exits, cut-outs ignoring compensation, fern pairs, mirrored fill angles) | ✅ fixed | `tests/test_review_fixes.py` |
| Sequencer determinism (work budget, not wall-clock) | ✅ | same DST on any machine |
| Bean / triple running stitch | ✅ | BeanStitch tests |
| Satin corner handling | ✅ | SatinCorners tests (folded stitches 73 → 0) |
| Appliqué cutting template | ✅ | AppliqueCutTemplate test |
| Still not built | ❌ | Bezier handles; PES/JEF (needs vendor thread palettes); machine hoop database (needs verified Ricoma frame data) |

## New features (2026-11-19)
| Feature | State | Evidence |
|---|---|---|
| Motif run: wave, zigzag, scallop, diamond, leaf | ✅ | MotifRunTests, e2e |
| Text on a path (built-in font follows a run / satin line; mirroring keeps it readable) | ✅ | TextOnPathTests, e2e |
| Stitch-level editing: convert to manual stitches | ✅ lossless | 72 / 72 library objects byte-identical after conversion; moving one point changes exactly one stitch |
| TrueType / OpenType lettering, HarfBuzz shaping via Pillow Raqm | ✅ | Arabic joins (2 shapes vs 5 unshaped); missing glyphs refused. **Telugu / Devanagari need a font upload and were not verified with a real Telugu font (none installed here)** |

## UI wiring audit (2026-11-19)
Method: every server endpoint vs. what `web/app.js` calls; every engine parameter vs. an editor field; UI vs. engine defaults; then 56 property
values driven through the real UI (fill + satin) and the 7 other object types, watching page errors, HTTP errors and invalid output.
| Gap found | Fix |
|---|---|
| `/api/profile` (fabric / category profile + sequence optimiser) had **no UI** - only the wizard could use it | Design panel: Category, Profile fabric, *Apply profile*, *Apply & overwrite*, *Optimise sequence* (undoable) |
| `/api/enhance` had no standalone UI | More ▾ → *Enhance image 2×…* downloads the upscaled PNG |
| No editor field for `end_at_start`, `corner_angle`, appliqué `cover_color` | Pro-mode fields added (corner angle appears when corner splitting is on) |
| Machine `smart_direction` and `min_stitch` had no control | Machine panel checkbox + number |
| **Bug:** fields that add other fields (stitch *Style* → motif options, *Split sharp corners* → corner angle, fill *Pattern*) did not appear until the object was reselected | Panel rebuilds on those changes |
| Guard | `tests/test_ui_wiring.py` fails if an endpoint / engine parameter / machine setting ships without UI, or UI and engine defaults drift (it fails on the pre-fix UI) |
Result of the exploratory run: 0 invalid outputs, 0 page errors across all object types; the only HTTP 400 was the Quality check correctly refusing a design with nothing to stitch.
