# Photo digitizing engine

StitchCraft has **two independent image workflows**. They share the validated DST export, nothing else.

| Workflow | Input | Method | Module / API |
|---|---|---|---|
| **Vector artwork** | logos, line art, flat-colour drawings | palette → regions → fill / column / run objects | `raster.py`, `POST /api/import/raster`, `/api/autodigitize` |
| **Photo Stitch** | photographs, shaded art | tonal flow-field hatching (below) | `photo.py`, `POST /api/photo/stitch` |
| **Garment photo** (pre-step) | photo of a finished garment | isolate the embroidery, then feed vector or photo | `motif_isolation.py`, `POST /api/image/isolate` |

The workflow is recommended automatically from the source-quality check (`workflow`: `vector` / `photo` / `garment_photo`); the user can always choose another one (import dialog buttons).

## Why a separate engine
The vector pipeline reduces an image to ≤ 8 flat colours. For a photograph that removes every shade, so the result is a poster. Thread cannot print continuous tone either, but embroiderers represent tone with **stitch density, stitch direction and thread colour**. The photo engine does exactly that.

## What thread can and cannot do (stated in the UI)
* Tone = line spacing (dark 0.34 mm … light 1.15 mm, white = bare fabric). Lines stay visible.
* At most 12 colours; fabric shows through; no continuous tone; resolution about 0.3–1 mm.
* A software similarity score is not a stitch-out result (see `docs/testing/stitch-quality-validation.md`).

## Algorithm (`photo.photo_stitch`)
1. **Tonal mapping** – luminance → 2nd/98th percentile stretch → partial histogram equalisation (`equalize`, default 0.6) → gamma → darkness *D* ∈ [0,1]. **Controlled dithering**: an ordered Bayer 4×4 threshold (`dither`, default 0.5) is added to *D* before it is quantised to `levels` tones, which breaks up banding deterministically. White (D below the first level) produces no stitches.
2. **Variable stitch direction** – two-scale structure tensor of the luminance: a fine scale (~1.2 mm) follows edges, a coarse scale (~5 mm) follows shading isophotes. Stitches run **along** the orientation; in flat areas the user angle is used (`direction: "flow" | "fixed"`).
3. **Density control / shading** – evenly spaced streamlines (Jobard–Lefer) with local spacing `s = s_dark · (s_light/s_dark)^(1−D)` (0.34–1.15 mm, scaled by `density`). The darkest tone gets a **cross-hatch** pass. Stitches are resampled to equal arc length (`stitch_mm`, default 2.5 mm).
4. **Colour transitions** – multicolour mode: Lab k-means (`colors` ≤ 12) → each cluster is mapped to the nearest **generic** thread colour of a built-in 18-colour list (not a brand chart; a custom `thread_palette` can be given). Cluster boundaries are **feathered**: inside a band, spacing is doubled so neighbouring colours interleave. Areas whose colour equals the fabric colour are not stitched.
5. **Safety** – minimum stitch 0.9 mm, maximum 7 mm by construction (sub-minimum chords are dropped); a total stitch budget (`max_stitches`, default 180 000) coarsens the spacing automatically and reports it; time budget 120 s.
6. **Output** – ordinary `manual` objects (every point a penetration), chained nearest-end to keep jumps/trims low; the generator, locks, sequencing and `export_pipeline.export_dst` (decode-compare, independent decoder) are reused. `machine.micro_clean = 0.4` is set for photo designs.

## Thread-texture simulation
`photo_validation.render_preview` draws each stitch of the **decoded DST** (not the generator's floats) as a 0.38 mm thread line whose brightness depends on its direction against a fixed light (anisotropic sheen) over the fabric colour. The UI shows it beside the unchanged original.

## Validation (software, simulated)
`photo_validation.compare` compares that simulated thread image with the photo (both blurred 0.7 mm): luminance MAE / correlation, block SSIM, histogram distance, edge correlation, and (multicolour) Lab ΔE. **It measures similarity of a simulation, not stitch-out quality.** Metrics, formulas and thresholds: `docs/testing/stitch-quality-validation.md`.

## Parameters
`width_mm, mode (grayscale|multicolour), colors (2–12), levels (2–8), density (0.4–2.5), angle, direction, dither (0–1), gamma, cross_hatch, equalize (0–1), thread_palette (≤ 24 #rrggbb), fabric (#rrggbb), thread, stitch_mm, max_stitches`. Invalid values are refused (HTTP 400), a flat/blank image is refused ("nothing to stitch").

## Garment-photo motif isolation (`motif_isolation.py`)
Heuristic and semi-automatic; it never claims certainty.
* **Fabric colour** = dominant colour cluster (coarse Lab bins) of the picture.
* **Embroidery probability** = `clip(0.65·colour + 0.45·detail + 0.10·coherence·detail)` where *colour* = Lab chroma distance from the fabric, *detail* = fine high-pass luminance energy relative to the fabric weave, *coherence* = structure-tensor coherence (thread sheen).
* **Shadows** (same chroma, darker than the smoothed fabric illumination, no fine texture) and **folds** (same chroma, no texture, strong low-frequency gradient) are multiplied by 0.15 and counted in the report.
* Mask = probability ≥ threshold (default 0.65, the UI shows coverage at 0.4…0.8 because the result can change sharply with it); specks removed; nearby parts grouped into **motifs** that the user can untick; an optional **crop region** handles busy backgrounds.
* Output: an overlay (non-embroidery dimmed), the motif list (bbox, area, confidence) and a **derived** cropped motif image (everything outside the mask filled with the estimated fabric colour). The original is never modified.
* **Known limits** (returned with every result): tone-on-tone thread, deep shadows over bright thread, printed or strongly textured fabric, and a close-up with no dominant fabric colour. Measured locally on synthetic garments (IoU 0.82, 1.9 % false-positive area) and on real blouse photos: a flat-lay on plum fabric isolates well; a model photo with a busy background needs the crop region and a higher threshold. Always inspect the overlay.

## Tests
`tests/test_photo_stitch.py` (tone→density, white = bare fabric, contour following, safety limits, determinism, budget, palette, DST round trip, preview-from-decoded-DST, mirrored-preview mutation), `tests/test_motif_isolation.py`, `tests/test_source_quality.py`.
