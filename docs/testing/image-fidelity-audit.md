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
| F2 | High | Small elements are silently dropped | `min_area` (1.2-6 mm2) discards components; only a count `dropped_specks` is reported; no list, no reason | dots, flower centres, border squares above | inventory with a status and a reason for every component; closest valid stitch (P4-P5) | same | Open |
| F3 | Med | Holes smaller than half `min_area` are filled in | hole filter in `digitize_image` | tiny hole in a shape | keep + inventory (P4) | same | Open |
| F4 | Med | 1-2 px lines and tiny regions can be erased by cleanup | `_majority` and `_remove_fringe` are not feature-size aware | thin arc plate | feature-aware cleanup (P3) | same | **Fixed - verified** (P3). Measured: 13 one-pixel lines -> 0 objects before (standard / high), 13 after. Causes: blur + threshold erased thin ink; 3x3 majority filter erased 1-px lines; fringe removal could delete a genuine thin colour. Fixes: thin pixels re-added after smoothing, majority only on noisy sources, fringe only for Lab blends |
| F5 | High | No traceability: no list of source regions, no region -> object mapping, no coverage number | nothing builds an inventory | - | inventory + coverage (P4) | same | Open |
| F6 | High | The exported DST is never compared with the source image | no reconstruction / overlay | - | image-to-DST validation (P6) | same | Open |
| F7 | Med | Original image is not hashed or preserved by the pipeline | server is stateless; package has no source | - | source record + package (P2) | same | Open |
| F8 | Med | autofix / sequence optimisation can change geometry; the change is only a log line | logs are text, no measured difference | - | measured diff (P5) | same | Open |
| F9 | Info | Photographs become flat regions and cannot match | by nature (shading, texture) | blue blouse photos | detection + explicit limitation + review flags (P4/P6) | same | Open |
