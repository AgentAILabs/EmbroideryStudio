# Image-to-DST fidelity and validation

Everything below is **software measurement**. Physical machine validation is **PENDING**: no design from this project has been stitched, so no stitch-out quality is claimed.

## Principles
* The uploaded image is the reference and is **never modified**: it is hashed on arrival (SHA-256) and shipped byte-for-byte in the bundle; every other image (overlay, difference map) is derived and separate.
* **Nothing is silently dropped.** Every component of the artwork gets an inventory record (id, position, size, area, strategy, status, reason, stitchability, linked object). Items too small to stitch safely are listed as `not_stitchable` with the reason and require review.
* **No invented detail.** No AI enhancement, no redrawing. Photographs are detected and reduced to flat colour regions at best effort; they are reported as a limitation.

## Pipeline (`raster.py`)
1. **Working resolution**: `high` and `maximum` analyse at up to 1,600 px (<= 0.08 mm/px); `standard` 420 px and `draft` 260 px are faster/coarser. The 1,600 px budget protects time and memory.
2. **Thin ink is preserved**: pixels that vanish under a 3x3 opening are put back after smoothing; the 3x3 majority filter runs only on noisy sources; fringe removal only deletes colours that are Lab blends of two other colours (sRGB or linear-light blend).
3. **Inventory + strategy** per component:
   | Feature | Strategy | Status |
   |---|---|---|
   | >= fill threshold (>= 1 mm2 and the quality's minimum) | tatami fill / satin column / running line by width and aspect | digitized |
   | narrow elongated mark | running line (bean stitch below 0.35 mm wide) | micro_representation |
   | small blob up to 2.2 mm across | **tack dot**: six-point asterisk, every stitch >= 0.86 mm | micro_representation |
   | smaller than 0.75 mm across | none - listed with reason and the closest alternative | not_stitchable (review) |
   | < 0.3 mm or < 0.15 mm2 | counted as noise (count + area in `coverage`) | - |
   | antialiasing sliver in a blend colour | counted as fringe (count + area) | - |
4. **Mixed shapes**: a line that does not cover its whole shape (bead on a line end, two lines meeting at a tip) gets extra pieces for the uncovered residual; a fill that joins broad areas with thin lines is split by morphological opening into regions + lines.
5. Optional `machine.micro_clean` merges stitches shorter than 0.4 mm after generation.

## The nine validation passes (`image_validation.py`, `POST /api/image/validate`)
| # | Pass | What it checks | Fails when |
|---|---|---|---|
| 1 | Source completeness | original hashed; analysed whole; aspect kept | aspect changed |
| 2 | Segmentation completeness | ink area = stitched + not stitchable + noise + fringe | > 1 % of the ink is unexplained |
| 3 | Geometry | vector objects vs original ink: recall, boundary distance (95 % within 0.5 mm) | recall < 97 % or boundary > 0.5 mm |
| 4 | Stitch generation | quality score, 15-item checklist, issues | blocking issue |
| 5 | Optimisation | objects removed / added, stitched-area change | warning if any removed or > 3 % |
| 6 | DST export + re-import | decode-compare, independent reader | export refused |
| 7 | Coordinates / movement | orientation test (identity vs mirrors), size, movement limits | best match is not identity |
| 8 | Visual comparison | decoded-DST thread raster vs original ink | recall < 97 %, spill > 4 %, boundary > 0.75 mm, thread coverage < 85 %, a colour < 93 % |
| 9 | Final production | aggregate + remaining risks | any mandatory failure |
Metric definitions: `ink_recall` = share of the original's ink under thread of the right colour (0.25 mm tolerance); `stitched_spill` = share of stitched area farther than 0.5 mm from any ink (a thread is 0.45 mm wide and pull compensation adds ~0.2 mm); `boundary_p95_mm` = distance within which 95 % of the outline pixels have a counterpart; `thread_coverage` = share of stitched shapes that thread lines actually cover; `colour_match_min` = worst per-colour recall.
The design may be scaled / centred by auto-fix; the image-to-design frame is recovered from objects that kept their id and verified by its residual.
Mutation tests (`tests/test_image_validation.py`): deleting objects, moving one object, mirroring, an axis-swapped DST and unaccounted ink all make the validation fail.

## Evidence: complex artwork end to end (`designs/image_fidelity_demo/`)
A 2,400 x 1,002 px flat-colour artwork (the blue-set bird pair, 179.4 mm wide) went through upload -> inventory -> digitize (profile, auto-fix, sequence) -> DST -> re-import -> decoded-DST overlay.
`high`: 10.5 s, 5,840 stitches, 101 inventoried regions (79 digitized, 20 micro, 2 not stitchable), recall 99.95 %, spill 1.9 %, software validation PASSED WITH WARNINGS (the 2 listed details; the independent reader was not available in that run), physical PENDING.
Files: `source_artwork.png` (original), `overlay.png`, `difference.png`, `bird_pair-image-to-dst.zip` (original byte-identical, inventory, reports, DST, project).

## Known limits
Photographs cannot be matched stitch-for-stitch; upscaling cannot create detail missing from the source; very small details (< 0.75 mm) cannot be stitched safely; a high software score does not predict stitch-out quality.
