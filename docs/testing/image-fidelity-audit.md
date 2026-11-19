# Image-to-DST fidelity audit (software level)

Scope: the raster import path (`engine/stitchcraft_engine/raster.py::digitize_image`, `server/app.py::api_raster / api_autodigitize`). Nothing here is physical-machine evidence.
Benchmark: `tools/detail_bench.py` - an 80 mm plate of 52 exact-truth small elements (4 hairlines 0.3-1.2 mm, 4 dots 0.5-2 mm, 3 tiny six-petal flowers, 4 leaves, 4 closely spaced arcs, 10 border squares, 3 text-like marks, 2 overlapping discs).
An element is FOUND when >= 50 % of its true area is covered by stitched shapes of the right colour (0.3 mm tolerance for thin elements).

## Baseline (before this work, commit 48c131b)
| Quality | Source | Found | Lost |
|---|---|---|---|
| standard | 400 px | 37 / 52 (71 %) | dots 0.5 / 0.8 / 1.2 mm, flower centres R2 + R3, all 10 border squares |
| standard | 1600 px | 37 / 52 (71 %) | same |
| high | 400 px | 48 / 52 (92 %) | dots 0.5 / 0.8 / 1.2 mm, flower centre R2 |
| high | 1600 px | 48 / 52 (92 %) | same |
A 1600 px source gives the same result as a 400 px one: the source resolution is thrown away before analysis (finding F1).

## Issue register
| ID | Sev | Finding | Root cause | Repro | Fix (phase) | Regression test | Status |
|---|---|---|---|---|---|---|---|
| F1 | High | Fine detail in a high-resolution source is lost | `QUALITY[...]["max_px"]` (260 / 420 / 700) downsamples the image before palette / contours | `detail_bench --px 1600` = `--px 400` | adaptive working resolution (P3) | `tests/test_image_fidelity.py` | **Fixed** (P3): `high` and new `maximum` analyse at up to 1,600 working px (<= 0.08 mm/px); 1600 px source now keeps its resolution |
| F2 | High | Small elements are silently dropped | `min_area` (1.2-6 mm2) discards components; only a count `dropped_specks` is reported; no list, no reason | dots, flower centres, border squares above | inventory with a status and a reason for every component; closest valid stitch (P4-P5) | same | **Fixed - verified** (P4/P5): every component is inventoried with status, reason, stitchability; below the fill threshold it gets the closest valid stitch (tack dot / running or bean line / small fill); under 0.75 mm it is `not_stitchable` with a reason and review flag. Benchmark: 37 -> 51 of 52 elements (standard), 48 -> 51 (high); the 1 remaining (0.5 mm dot) is listed, not silent |
| F3 | Med | Holes smaller than half `min_area` are filled in | hole filter in `digitize_image` | tiny hole in a shape | keep + inventory (P4) | same | **Fixed**: tiny holes filled in are counted with their area in `coverage.holes_filled` (not silent) |
| F4 | Med | 1-2 px lines and tiny regions can be erased by cleanup | `_majority` and `_remove_fringe` are not feature-size aware | thin arc plate | feature-aware cleanup (P3) | same | **Fixed - verified** (P3). Measured: 13 one-pixel lines -> 0 objects before (standard / high), 13 after. Causes: blur + threshold erased thin ink; 3x3 majority filter erased 1-px lines; fringe removal could delete a genuine thin colour. Fixes: thin pixels re-added after smoothing, majority only on noisy sources, fringe only for Lab blends |
| F5 | High | No traceability: no list of source regions, no region -> object mapping, no coverage number | nothing builds an inventory | - | inventory + coverage (P4) | same | **Fixed - verified** (P4): `inventory` (id, bbox, size, area, strategy, status, reason, stitchability, object id) + `coverage` (stitched fraction, noise specks, antialiasing fringe, holes filled); every object traces to a source region (`tests/test_image_fidelity.py::DetailInventory`) |
| F6 | High | The exported DST is never compared with the source image | no reconstruction / overlay | - | image-to-DST validation (P6) | same | **Fixed - verified** (P6): `image_validation.validate` - nine passes; the DECODED DST is rasterised (0.45 mm thread) and compared with the original ink; mutation tests (delete objects, move one object, mirror, axis-swapped DST, unaccounted ink) all FAIL the validation (`tests/test_image_validation.py`) |
| F7 | Med | Original image is not hashed or preserved by the pipeline | server is stateless; package has no source | - | source record + package (P2) | same | **Fixed - verified** (P2/P6): SHA-256 + size recorded; `/api/image/bundle` ships the untouched original byte-for-byte; byte-identity tests |
| F8 | Med | autofix / sequence optimisation can change geometry; the change is only a log line | logs are text, no measured difference | - | measured diff (P5) | same | **Fixed** (P6 pass 5): objects removed / added and the stitched-area change between import and final design are measured (limit 3 %) and shown |
| F9 | Info | Photographs become flat regions and cannot match | by nature (shading, texture) | blue blouse photos | detection + explicit limitation + review flags (P4/P6) | same | **Documented**: photographs are detected, listed as a remaining risk and processed best-effort to flat regions; no invented detail |

| F10 | Med | Antialiasing blends (e.g. pink between red and white) formed many tiny false objects once small details were no longer dropped | the fringe test compared Lab distance to a straight Lab line; resamplers blend in sRGB or linear light, so real blends were 24 dE away | standard, 1600 px source: 63 objects instead of 37 | `_is_mix` tests both blend spaces | `DetailInventory` tests | **Fixed - verified** |
| F11 | High | Digitizing a 2,400 px artwork at `maximum` took 244 s | `_nest` recomputed every ring area for every pair of rings (54 M area sums for 1,600 rings) | bird-pair artwork, maximum | areas once + numpy bounding-box candidates | `MixedShapes::test_nesting_thousands_of_rings_is_fast`, `ComplexArtworkBudget` | **Fixed - verified**: 2.8 s |
| F12 | High | A bead on the end of a line, and thin lines touching a leaf, lost part of the artwork | the component was classed as one line / fill by its average width | complex-artwork overlay: crest beads and the copper swirl line tips were red in the difference map | coverage check + residual pieces; thick / thin split | `MixedShapes` | **Fixed - verified**: ink recall 99.2 -> 99.95 %, worst colour 90.5 -> 94 % |
| F13 | Med | auto-fix removed fills under 1 mm2 (20 objects at `maximum`) although micro strategies exist | `placements.autofix` speck rule vs the 0.25 mm2 fill threshold | maximum run: pass 5 WARNING + pass 8 FAILED | the fill threshold is never below 1 mm2; smaller shapes get a micro strategy | validation passes on the demo | **Fixed - verified** |
| F14 | Low | `test_logs_never_contain_request_bodies` was racy (access line written after the response) | test | one failure in a full run | wait for the line | `tests/test_ops.py` | **Fixed** |

## Result (benchmark, 52 exact-truth elements, 1000 px source)
| Quality | Before | After |
|---|---|---|
| standard | 37 / 52 | **51 / 52** |
| high | 48 / 52 | **51 / 52** |
| maximum | (not available) | **51 / 52** |
The one element not reproduced (a 0.5 mm dot) is listed as `not_stitchable` with its reason. One-pixel lines: 0 of 13 objects before (standard, high), 13 of 13 after.
