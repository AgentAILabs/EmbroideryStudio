# Current validation report

Date: 2026-11-19 · Base commit: `1ed88d7` (main) + the changes of branch `feature/validation-honesty`.
This report separates **what was actually checked** from **what is assumed**. Nothing here is a statement about physical machine behaviour.

> **Physical machine validation: NOT DONE. No design from this software has been stitched on any machine, and no machine evidence exists in this repository.**
> A DST file that exports and passes every software check is **not** evidence that a machine will stitch it correctly.

---
## 1. Automated tests passed
Command: `./tools/run_tests.sh` (run in this environment, which has **no** `pyembroidery`, so 3 independent-reader tests skip here - see §4).

| Suite | Result | Count |
|---|---|---|
| Engine tests (`engine/tests`) | OK | 32 / 32 |
| Studio tests (`tests/`) | OK, 3 skipped | 660 run, 657 executed and passed, 3 skipped (pyembroidery not installed here) - updated after the photo / source-quality / physical-validation upgrade (2026-11-19) |
| JavaScript syntax (`node --check`) | OK | `web/app.js`, `tools/e2e_ui.js` |
| Browser end-to-end (`tools/e2e_ui.js`, real Chromium, run separately - not part of `run_tests.sh`, not part of CI) | PASS | 62 / 62 steps, 0 page errors, 0 HTTP 5xx, no CSP console errors |

Notable suites relevant to output correctness: `tests/test_dst_axis.py` (18, new), `tests/test_testpack_v2.py` (10, new), `engine/tests` byte-pin tests, `tests/test_digitizing_standard.py`, `tests/test_ui_wiring.py`.

### 1b. Enterprise upgrade additions (software level only)
`tests/test_export_pipeline.py` (25, incl. mutation tests and the historic axis swap in writer + reader), `tests/test_quality.py` (20), `tests/test_travel.py` (9), `tests/test_simulation.py` (5), `tests/test_entry_exit.py` (4),
`tests/test_machines_report.py` (14), `tests/test_ops.py` (12, incl. performance budgets). Every report states `physical_machine: NOT DONE`.

## 1c. Photo digitizing / source quality / physical-validation upgrade (software level only)
New suites: `tests/test_source_quality.py` (11), `tests/test_enhance.py` (5), `tests/test_detail_scan.py` (8), `tests/test_photo_stitch.py` (19), `tests/test_motif_isolation.py` (13), `tests/test_evidence.py` (13), `tests/test_sections.py` (14), `tests/test_stitch_generation.py` (15), `tests/test_photo_testpack.py` (2), plus extended OpenAPI / UI-wiring contracts.
Representative measurements (synthetic images; reproducible with `tools/make_photo_testfiles.py` and the tests):
| Run | Result |
|---|---|
| shaded sphere, grayscale, 60-100 mm | luminance correlation 0.96, block SSIM 0.85, decode-compare PASSED, independent DST section PASSED, ~0.7 s |
| 5-colour picture | colours mapped to the generic thread palette, fabric-coloured area skipped, Lab dE 9.9, ~1.3 s |
| garment synthetic (fabric + shadow + fold + 2 embroidered motifs) | embroidery mask IoU 0.82, 1.9 % of fabric area falsely classified |
| blouse photos (third-party, not committed) | flat-lay on plum fabric isolates the embroidery well; a model photo with a busy background needs the crop region and a higher threshold - see `docs/embroidery/photo-digitizing-engine.md` |
| DST independent section on every pack file in `testpack/photo_v1` | no FAILED check |
**Not measured / not claimed:** stitch-out quality, thread breaks, puckering, registration, trim behaviour, fabric behaviour. Photo similarity thresholds are engineering starting points, not calibrated against stitched samples.
**Physical validation: NOT DONE. Evidence records in the repository: 0. Every design reports PENDING.**

## 2. Automated tests failed
**At the time of writing: none fail.**
Failures that occurred *during this round of work* and what they were (so the history is not hidden):
| Failure | Cause | Resolution |
|---|---|---|
| 1 of the new axis tests (asymmetric flower) | a bug in the **test helper** (my hand decoder dropped colour-change records from the position list, shifting positions by one) - not a product bug | helper fixed; it now keeps positions aligned |
| 3 existing tests after the format changes | tests still assumed 12 pack designs / an EXP button / locks changing the stitch count by exactly the lock count | updated to the new facts; the lock test now accounts for the one anchor stitch needed after a colour-change cut when a colour starts where the previous ended |
| docs link checker | status.md linked to this report before it existed | this file |
The pyembroidery cross-check does not run in this environment; it ran in CI (§4).

## 3. Software-level DST validation (what the software itself checks)
* **Hand-written byte vectors** (`engine/tests/test_engine.py::DstBytePinTests`): expected bytes typed from the Tajima layout, deliberately not derived from the writer's tables.
* **Hand-typed decoder in the axis suite** (`tests/test_dst_axis.py`): decodes real output without importing the project's tables. Covers horizontal (left / right), vertical (up / down), diagonals (3-4-5 and all four quadrants), >12.1 mm lines, a 40 × 25 rectangle (width ≠ height), non-square designs (100 × 30, 30 × 100, 7 × 63), centring on the bounding box, header extents, an asymmetric flower (landmarks and exact positions), preview-SVG vs DST agreement, the editor → file path, and hoop width / height not swapped.
* **Mutation check performed:** re-introducing the historic X/Y table swap (writer and reader swapped together, as before) makes **12 of the 18 new tests and 4 of the 32 engine tests fail**. The suite would have caught the original bug.
* **Round trip:** every export is read back by the project's reader (ends with END, colour changes match).
* **Six-stage verifier** (`engine/stitchcraft_engine/dst_verify.py`): container, encoding, machine limits, stitch quality, thread path, simulation. `testpack/v2`: 21 of 22 files PASS; 1 WARN (`15_jump_movement`, expected: it is a deliberate long-jump test with trims disabled).
* **15-item production checklist** gates the server-side export.
* **Provenance** (`tools/dst_provenance.py`): regenerates each committed DST from its own `.esproj` and compares bytes. Current result over `designs/`, `testpack/`, `testpack/v2/`: **78 files, 66 CURRENT, 12 not current**: 11 STALE (`testpack/` v1: 01, 03-12) and 1 NO-SOURCE (`designs/peacock_arch/v1_tested/...`, kept only so an earlier stitch-out stays traceable).

## 4. Independent DST reader validation
* **`pyembroidery`** (third-party reader) decodes our output in `tests/test_crosscheck.py` (stitch deltas, colour changes, trims, real-world EOF layout). **It does not run in this environment.**
* **Evidence that it ran:** CI run `44452434905` on `main` at `1ed88d7` (pip installs `pyembroidery`): *Ran 32 tests OK; Ran 329 tests OK*, no "skipped" line → the cross-check tests executed and passed there. The same CI run is the evidence that the X/Y fix is confirmed by an independent reader (the original swap was *found* this way).
* **After this round's changes:** CI run `44455215135` on `main` at `f166279` (pyembroidery installed): *Ran 32 tests OK; Ran 362 tests OK*, no "skipped" line - the independent-reader checks, the 18 axis tests and the 10 test-pack tests all executed and passed in CI.
* **Limits:** reader agreement shows the file is *well formed and consistently interpreted*; it does not show a machine will accept or sew it.
* **Third-party files (informational):** 20 commercial DST files supplied by the user decode with our reader into correctly oriented designs (visual check of renders), which supports the bit tables. Those files are not in the repository.

## 5. Physical embroidery machine validation
| Item | Result |
|---|---|
| Any file stitched on any machine | **none** |
| Axis / orientation on a machine | **not tested** (design `13_axis_orientation` exists for this) |
| Trim and jump behaviour | **not tested** (design `12_trims_locks`, `15_jump_movement`) |
| Fabric presets | **not tested** |
| Hoop boundary | **not tested** (`16_hoop_boundary`) |
| Thread breaks, puckering, registration | **no data** |
Status of the pack: `testpack/v2` is generated, hash-listed (`MANIFEST.json`, `"physically_validated": false`) and its result sheets are blank by design (a test checks that no result field is pre-filled). Procedure: `machine-test-checklist.md`; template: `machine-test-report-template.md`.

## 6. Unverified assumptions (each one is a hypothesis until stitched)
| Assumption | Where | Why it may be wrong |
|---|---|---|
| The machine reads our DST as Tajima DST with Y up, 0.1 mm units, origin at the design's bounding-box centre | `dst.py` | machines differ in how they place the origin (hoop centre vs first stitch) |
| A trim = **3 consecutive zero-move jumps** | `design.MACHINE_DEFAULTS.trim_jumps = 3` | DST has no trim opcode; machines differ (2-6); some trim on any jump |
| Jumps longer than **3 mm** are trimmed | `trim_distance = 3.0` | machine setting dependent |
| **1.0 mm** tie-in / tie-off locks hold | `lock_len = 1.0` (0.8 for 60 wt, 1.0 for 120/2) | derived from measuring other suppliers' files, not tested |
| Stitch-line spacing 0.40 mm (40 wt), 0.30 (60 wt), 0.22 (120/2) | `design.THREADS` | copied from measured commercial files; depends on thread, needle, fabric |
| Fabric presets: cotton 0.40 / pull 0.20, silk 0.45 / 0.30, georgette 0.45 / 0.35, velvet 0.38 / 0.40, denim 0.40 / 0.10, knit 0.42 / 0.40 (spacing mm / pull mm) | `design.FABRICS` | guesses; **experimental** |
| Profile fabrics (blouse, silk, georgette, velvet, stretch, denim, cotton: density factor, pull, underlay shift) | `profiles.FABRICS` | same |
| Stitch-time estimate = stitches / **700 spm** + **20 s** per colour change + **6 s** per trim | `design.SPM`, `COLOR_CHANGE_S`, `TRIM_S` | machine speed, acceleration, jump speed and thread-cut time all differ |
| Max stitch 7 mm, min 0.3 mm, record limit 12.1 mm | machine profile | 12.1 is the DST record limit (format fact); 7 / 0.3 are practice values |
| Hoop sizes / margins | UI presets | generic; no machine-specific frame database |
| Image-to-embroidery fidelity (IoU 0.95) | `tools/image_bench.py` | measured on synthetic flat-colour art only |
| Telugu / Hindi lettering works | `lettering.py` | never run with an Indic font |

## 7. Evidence needed to close the gaps
Return a filled machine test report for `testpack/v2` (at minimum designs 13, 12, 15, 09, 07, 16 on the real fabric). Until then every "unverified" above stays unverified and the UI keeps saying so.
