# Micro-detail preservation

Goal: **no detail of the source disappears silently.** Every detail ends in exactly one of four states.

| Status | Meaning |
|---|---|
| `digitized` | stitched as its own object (fill, column or run) |
| `approximate` | stitched by the closest valid method (tack dot, bean/running line, merged piece) – shape differs from the source |
| `not_stitchable` | smaller than a safe stitch (about 0.75 mm) or otherwise impossible; reported, never hidden |
| `awaiting_review` | detected in the source but matched to nothing the digitizer produced; needs a human decision |
(`omitted_by_user` is also recorded when the user chose to leave it out.)

## Two independent detectors
1. **Digitizer inventory** (`raster.py`) – every region found after palette quantisation and label cleaning gets an id, bbox (mm), area and status, and `src` links the editor object back to it (source → object traceability).
2. **Independent multi-scale scan** (`detail_scan.py`) – runs on the **original** image, not on the palette/label map the digitizer used, so a detail the digitizer lost is still found.
   * luminance and colour-distance-from-background maps, ≤ 1600 px;
   * scale space: difference of Gaussians at σ = 1, 2, 4, 8 px (feature size ≈ 2.83 σ, reported in mm);
   * a detection is a local extremum of |DoG| above `max(6, 0.25 × p99.5)`, non-maximum suppressed (1.5 σ), on the subject only (colour distance from the background ≥ 25 % of the maximum – the gap between two marks is not a detail);
   * kind = blob or line from the Hessian eigenvalue ratio (> 0.45 = blob); detections of the same place at several scales are merged (strongest wins; radius `max(0.5 mm, 0.4 × size)`);
   * each detection is matched to the inventory item whose bbox contains it (0.35 mm tolerance) and takes that item's status; otherwise `awaiting_review`.
   Faint responses (half the threshold) are counted, not listed; at most 300 detections are listed.
The scan is part of validation pass 2 (WARNING when anything is `awaiting_review`) and is shown in the fidelity dialog.

## Stitch strategies for small features (`raster.py`)
tack dot (≈ 0.9 mm), bean/triple run for thin lines, satin for 1–6 mm columns, thick/thin split for mixed strokes, residual pieces for what a fill would lose. User decisions (`tack` / `omit`) are passed back through `decisions` and recorded.

## What enhancement can and cannot do
`enhance.py` (Lanczos upscale, denoise, contrast, edge-preserving unsharp) creates a **derived, estimated** image: `provenance.estimated = true`, `recovered_detail = false`, with source/result SHA-256 and the statement *"ESTIMATED – not recovered detail"*. Real detail is measured before and after (`real_detail_px`); a test proves an enhanced image does not raise it artificially. All validation compares against the **original**, never the enhanced copy. No machine-learning model is used or installed.

## Measured evidence
`tools/detail_bench.py` (synthetic benchmark plate with ground-truth details), `tests/test_detail_scan.py` (8), `tests/test_image_fidelity.py`. The scan's independence is proven by running it on a draft-quality digitization: the digitizer then misses details and the scan reports 36 `awaiting_review`, while on the normal run it reports 0.

## Limits
Anything below the source's own resolution cannot be detected; a detail the detector sees but the stitch engine cannot sew is reported as `not_stitchable`, not drawn larger.
