# Project status (audited against code + tests)
Legend: ✅ done & tested · 🟡 partial · ⬜ not started · ⏸ deferred (reason given) · 🧪 needs physical machine / external input

## A. Review decisions (requirements §A)
| # | Item | Status | Evidence / note |
|---|---|---|---|
| 1 | MVP = image/SVG → objects → simulate → DST | ✅ | editor + engine + DST |
| 2 | Raster: flat colour ≤ 8 colours, warn on poor input | 🟡→step 2 | cap was 12; low-DPI + colour warnings exist |
| 3 | Bead/stone/sequin = placeholders, on production sheet, not in DST | ⬜→step 4 | |
| 4 | Engine as separate service behind versioned JSON contract | 🟡 | HTTP service + `schema_version` contract tests; no queue (not needed at this scale); container files step 7 |
| 5 | .NET / MediatR / Konva | ⏸ | Replaced by a Python stdlib service + canvas editor: zero installs, same contract. Revisit only if a .NET shop wants it |
| 6 | Independent DST reader + pyembroidery/Ink-Stitch cross-check in CI | 🟡→step 7 | own reader ✅ (found + fixed 1 bug); cross-check is CI-only (no installs here) |
| 7 | Fabric presets, flagged unverified | ✅ | cotton/silk/georgette/velvet/denim/knit; 🧪 values unverified |
| 8 | FabricProfile, ThreadBrand, stabiliser, time estimate, trim rules | 🟡→step 2 | time ✅, trim rules ✅, fabric ✅; stabiliser field missing; brand charts ⏸ (licensed data) |
| 9 | Indian-market: Maggam repeat, blouse templates, Telugu/Hindi, inch hoops | 🟡 | repeat ✅, inch hoops ✅; templates →step 4; Telugu/Hindi ⏸ (needs font files + outline→satin research) |
| 10 | Auth / per-user ownership | ⏸ | single-user local tool; accounts belong to a hosted version |
| 11 | Windows desktop later (Tauri/WebView2) | ⏸ | API is reusable; do after stitch-out proves the engine |

## B. MVP functional (release gate)
| # | Item | Status | Note |
|---|---|---|---|
| 1 | Upload SVG / PNG / JPG / PDF first page, limits | 🟡 | SVG ✅ PNG/JPG ✅ limits ✅ safety ✅; **PDF ⏸** (rejected with message; needs a PDF vector parser) |
| 2 | Real-world size, DPI warning, never auto-stretch | ✅ | |
| 3 | Auto-digitize + per-object stitch-type override | ✅ | convert fill/satin/run/column |
| 4 | Object list, move/scale/rotate/delete, undo/redo | ✅ | |
| 5 | Properties | ✅ | |
| 6 | Simulation from real stitch array incl. jumps + colour changes | 🟡→step 2 | jumps not drawn yet |
| 7 | Hoop + machine profile, block export on errors | ✅ | |
| 8 | Export DST, project, preview PNG/SVG, production sheet | ✅ | single "package" download →step 3 |
| 9 | Beginner / Pro | ✅ | |
| 10 | Save/reopen, versions | ✅ | versions are per-browser |

## C. Quality rules
| Rule | Status |
|---|---|
| Stitch 1–7 mm typical, hard stop 12.1, warn < 0.3 | 🟡→step 2 (warn threshold was 0.2) |
| Satin width warn <1 / >7 (+ auto-split) | ✅ |
| Density warning | ✅ |
| Sequence underlay → fill → satin → details | 🟡→step 2 (underlay ✅; ordering only manual/optimiser; add overlap warning) |
| Trim if jump > 3 mm (configurable), anchor stitches | ✅ |
| No stitches outside source geometry beyond tolerance | 🟡→step 2 (tested for edge underlay only; add general test) |

## D. Phases
| Phase | Status |
|---|---|
| 3 engine | ✅ |
| 4a raster pipeline | ✅ basic (5 artwork tests →step 2) |
| 4b offsets (Shapely) | 🟡 pure-Python inset ✅, fill pull-comp ✅, satin-from-outline →step 5 |
| 4c service + contract tests | ✅ HTTP + contract; ⏸ job queue |
| 2 foundation (Docker, .NET, Postgres, React) | 🟡 Docker →step 7; rest ⏸ (decision 5) |
| 5 editor + simulation | ✅ |
| 6 export package, sheet, reopen | 🟡→step 3 |
| 7 hardening, physical matrix, docs | 🟡 test pack ✅ + procedure ✅; 🧪 stitching is yours; user guide →step 7 |

## E. Sprint 2
| Item | Status |
|---|---|
| pyembroidery cross-check | step 7 (CI only) |
| Raster 5 test artworks | step 2 |
| Satin-from-outline | step 5 |
| Service + contract tests | ✅ |
| First physical stitch-out | 🧪 |

## Roadmap items not covered by steps 2–7 (deferred, with reason)
| Item | Why deferred |
|---|---|
| PES / JEF / EXP writers | Cannot be validated without a reference reader or machine; a wrong file is worse than none. Do with pyembroidery cross-check once available |
| PDF import | needs a PDF vector parser (no installs allowed here) |
| TrueType + Telugu/Devanagari lettering | needs licensed/available font files; shaping rules for Indic scripts |
| Thread brand charts | licensed colour data; generic hex palette used |
| Bezier node handles | Catmull-Rom smooth mode covers curves; handles are a UX upgrade |
| Hoop split, stitch-level editing, gradient/stipple/motif fills | large, separate features; not needed for the MVP gate |
| Accounts, cloud library, Tauri shell | hosted/desktop product phase |
