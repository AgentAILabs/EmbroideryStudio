# Source image quality assessment

`POST /api/image/quality` → `source_quality.assess(data, width_mm)`. Pure measurement of the uploaded bytes; the file is never modified. Needs Pillow + NumPy (otherwise `ran: false`). Analysis uses at most 1600 px on the long side. Each metric returns `value`, `unit`, `grade` (good / fair / poor / info) and `how`. **The grades describe the source only – they say nothing about stitch-out quality.**

| Metric | Formula / rule | good | fair |
|---|---|---|---|
| `resolution_dpi` | source px ÷ design width in inches | ≥ 250 | ≥ 120 |
| `sharpness_laplacian_var` | variance of the 3×3 Laplacian of luminance | ≥ 150 | ≥ 40 |
| `sharpness_tenengrad` | mean squared Sobel gradient magnitude | ≥ 3000 | ≥ 600 |
| `blur_edge_width_px` | median width of strong edges = contrast ÷ peak gradient | ≤ 1.6 | ≤ 2.8 |
| `noise_sigma` | 1.4826 × MAD of the high-pass residual in the flattest 30 % | ≤ 2 | ≤ 5 |
| `contrast_span` | 95th − 5th percentile luminance | ≥ 120 | ≥ 60 |
| `contrast_rms` | standard deviation of luminance | ≥ 45 | ≥ 25 |
| `jpeg_blockiness` | gradient across 8-px block boundaries ÷ elsewhere (1.0 = none; JPEG only) | ≤ 1.08 | ≤ 1.25 |
| `effective_resolution` | fraction of the pixel grid with real detail: radial power spectrum, cut-off where energy falls to 20 × the noise floor (an indicator – bicubic-enlarged art reads ≈ 0.5, not exactly the true factor) | ≥ 0.55 | ≥ 0.30 |
| `smallest_feature_mm` | scale-space (DoG) smallest feature, in mm at the chosen width | ≤ 0.75 | ≤ 1.5 |
| `subject_visibility` | share of central pixels > 30 RGB units from the border colour | ≥ 0.08 | ≥ 0.02 |
| `subject_separation` | 90th-percentile RGB distance subject vs background | ≥ 90 | ≥ 45 |
| `classification` | artwork if 64 colour bins cover ≥ 80 % of pixels and smooth shading is small; photograph otherwise; a photograph with one dominant colour cluster (≥ 35 %) = garment photo | info | |

Outputs: `metrics`, `classification`, `workflow` (`vector` / `photo` / `garment_photo`), `effective_pixels_across`, `recommendations` (actionable text, e.g. "use a larger source or a smaller design width", "this looks like an enlarged or blurry image – enhancement can sharpen edges but cannot recover missing detail", "photograph: use Photo stitch"), `source_sha256`.

UI: the import dialog shows the panel and highlights the recommended workflow; section 1 of the five-section report repeats it.

Tests: `tests/test_source_quality.py` (11: sharp vs blurred, noisy, low contrast, JPEG blocking, enlarged image detected, classification, workflow, recommendations, no-Pillow fallback shape, API rejects).
