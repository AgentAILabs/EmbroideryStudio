# Stitch-quality validation – the five separate sections

`POST /api/report/sections` (also embedded in `/api/photo/stitch` and `/api/image/validate`) returns **five independent sections**. There is deliberately **no combined score**: `combined_score` is always `null`. A good source says nothing about stitching, a software score says nothing about a machine, and only section 5 can speak about physical success. Every metric carries `how` (formula or rule). Code: `engine/stitchcraft_engine/sections.py`.

## 1. Source image quality
Grades from `source_quality` (see `image-quality-assessment.md`). Verdict = worst grade: GOOD / FAIR / POOR; `NOT ASSESSED` for vector input or without Pillow/NumPy. Not measured: detail that is not in the image can never be recovered.

## 2. Artwork / geometry preservation
Image-to-DST validation passes 1, 2, 3, 5, 8 (source completeness; segmentation + the independent detail scan; geometry vs the original; optimisation did not remove stitched shapes; visual comparison original vs **decoded DST**) with their thresholds (`image_validation.THRESHOLDS`: ink recall, stitched spill, boundary p95 deviation, thread coverage, colour match). For photo designs: the photo metrics below. Verdict: PASSED / WARNING / FAILED. Not measured: stitch-out quality.

### Photo similarity metrics (`photo_validation.compare`)
Both images are resampled to 4 px/mm and blurred σ = 0.7 mm.
| Metric | Definition | Threshold |
|---|---|---|
| `luminance_mae` | mean \|L_photo − L_sim\| (0–1) | informational |
| `luminance_corr` | Pearson correlation of luminance (scale-invariant: thread cannot be brighter than fabric) | ≥ 0.70 |
| `structure_ssim` | mean of block-wise (8×8) SSIM on luminance | ≥ 0.40 |
| `histogram_distance` | ½ × L1 distance of 32-bin luminance histograms after matching their 2nd–98th percentile range | ≤ 0.35 |
| `edge_corr` | correlation of gradient-magnitude maps | ≥ 0.30 |
| `colour_de` (multicolour) | mean CIE-Lab distance | ≤ 28 |
Thresholds are engineering starting points, **not** calibrated against stitched samples.

## 3. Stitch-path software validation
`quality_report` (8-category software score, labelled software-only) plus measurements on the **decoded** stitch stream:
| Metric | Rule |
|---|---|
| min / max stitch length | ≥ 0.5 mm preferred / ≤ 12.1 mm (one record) |
| stitches < 0.5 mm, > 7 mm | each ≤ 1 % of stitches |
| needle penetrations per mm² | max over 1 mm cells of the decoded positions ≤ 12 |
| jumps, trims, colour changes, longest jump | counted |
| travel verdicts | unnecessary / missing trims, thread changes (`travel_report`) |
Verdict `PASSED (software only)` / `WARNING (software only)` / `FAILED`. Not measured: *a high software score does not prove physical stitching success*; thread, fabric, stabiliser behaviour are not modelled.

## 4. Independent DST validation
Everything here is computed from the **DST bytes** with the independent decoder (`export_pipeline.independent_decode`, hand-typed layout table, own loop) or a third-party reader:
| Check | Rule |
|---|---|
| export stages | `decode-compare` (plan ↔ file, record by record: kind, count, position, size, orientation) and `independent-reader` (pyembroidery; **NOT RUN** where it is not installed – CI runs it) |
| end record | exactly one, and it is last |
| largest record movement | ≤ 12.1 mm (121 units) |
| decoded extents | bounding box of all decoded absolute positions |
| header extents vs decoded | `+X -X +Y -Y` header fields equal the decoded extents |
| fits the hoop | decoded W×H ≤ hoop − 2 × margin |
| re-import | the project reader gets the same number of stitch records |
| **preview == export** | the preview stitches reconstructed **from the exported records** equal the intended stitch sequence (same count, max deviation ≤ 0.08 mm = 0.1 mm quantisation) |
Mutation tests (`tests/test_sections.py`): dropping the END record, corrupting a header extent, truncating the file and shifting one preview stitch are each detected. Not measured: a consistent file is not proof a machine will sew it; trims are emulated as three zero-move jumps (unverified on machines).

## 5. Physical machine validation
Only from a recorded, checksum-matching evidence record (`evidence.py`, `docs/testing/physical-machine-test-plan.md`). Status: PENDING / INCOMPLETE / STALE / FAILED / PASSED_WITH_NOTES / PASSED. **No record exists in this repository; the status is PENDING.**

## Stitch-generation regression tests (`tests/test_stitch_generation.py`)
Movement (every DST record ≤ 12.1 mm, far islands), stitch lengths, thread per area follows spacing, penetration cap, satin density, underlay choice (none / centre), pull compensation (`pull_comp` widens the column by exactly that many mm), jump/trim counts, one colour change per thread change, and an image-derived design. **Defect found here:** a satin wider than twice the trim distance (about 6 mm and up) leaves the needle at the far end after the centre-walk underlay, then *trims and jumps the whole object length (about 39 mm for a 40 mm column)* before the top stitching. A fix exists (`builder.build_pattern(entry_after_underlay=True)`, machine setting **`underlay_entry`**, panel checkbox "Underlay entry (wide satin)"): the first top run starts at the end nearest the needle (longest in-object jump <= width/2 + 2.5 mm; the regression test fails without it). **It is off by default**: enabling it changes the stitch order of every underlaid object, which would change every delivered, hash-pinned DST (library, test packs, blue set), and in the 25-file test pack it reduced trims in some files but added one in `01_flower` (16 vs 15). Turn it on per design after you compare the result; nothing about its effect on a real machine is known.
