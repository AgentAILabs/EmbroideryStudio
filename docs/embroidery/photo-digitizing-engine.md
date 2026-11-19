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

## Thread separation (garment photos of red / gold embroidery) - `thread_separation.py`, `POST /api/garment/digitize`
For photos where the thread colours are known (default: red and gold on pink / cream silk) the generic palette digitizer produced scribbled fills, hollow gold rings and a heavy border. This workflow separates the threads first.
1. **Classify by hue** (not by distance to the fabric, which fails on shiny silk): per thread class a hue window, saturation and value floors (`threads` parameter; defaults red 348-14 deg / sat > 0.66, gold 26-62 deg / sat > 0.17). Earlier classes win overlaps; opening + speck removal per class.
2. **Rosettes**: gold-like (`rosette: true`) round blobs (area / circle through the farthest point >= 0.70, radius 2.2-9 mm, found after an opening that removes thin lines) become **radial satin columns** (two circular rails; inner radius = the real hole, or a 1.6 mm stone seat). Non-round gold goes to the vector digitizer.
3. **Border**: a long near-horizontal thread line in the lower 30 % of the picture (>= 35 % of the width) is fitted as ONE satin line (1.8 mm, centre underlay): low envelope, median outlier rejection (stems and petals touching the line), light smoothing; the band is removed from the mask so the flowers on it can become rosettes.
4. **Finish**: stray objects removed (fills < 3 mm2, runs / tack stitches shorter than 5 mm), leaf fills angled across their long axis (+68 deg) with spacing 0.46, pull compensation 0.12, no overlap growth, tatami underlay > 14 mm2, trim distance 6 mm (short hops carried, not cut).
**Measured on three pink-silk photos** (customer images, not committed): PINK2 19 rosettes + 3 border segments, 57 stray objects removed, jump records 364 -> 283 vs the previous generic result; PINK1 (pale gold) found no rosettes. **Limits:** hue windows are tuned on pink silk (other fabrics / lighting need other windows); curved necklines get no border line; petals are not individually defined (rosettes are rings); leaf midribs are not reproduced; stones / beads are not stitched; not machine-tested.

## Shape recognition and stitch-type presets (vector workflow) - `smart_design.py`
* `shapes=true` (API / import dialog / wizard / Instant smart design): each traced fill outline (and each hole) that is an **ellipse / circle** (area-moment fit: a, b, angle, centre; mean radial deviation <= 3.5 %, max <= 8 %, area within 7 %) or a **rectangle / square** (minimum-area rotated box, fill ratio >= 0.975, every point within 4 % of the box edge) is replaced by the ideal shape (circle / ellipse sampled every ~0.6 mm, rectangle = 4 corners). Others stay as traced. Recognised shapes are counted in `report.shapes` and named (Circle, Ellipse, Rectangle, Square).
* `preset=` chooses the stitch-type boundaries (stroke width = 2 x area / perimeter): `auto` thin < 1.0 mm run, up to 5.5 mm elongated column; `logo_satin` thin < 0.9, columns up to 9 mm (aspect >= 1.8); `line_art` thin < 2.0, columns up to 4 mm; `fine_detail` thin < 0.7, columns up to 4 mm (aspect >= 3); `fill_all` no runs / columns. Measured on a test plate: `auto` 4 fills + 1 column, `logo_satin` 2 fills + 3 columns, `fill_all` 5 fills.
* Defaults of the engine API are unchanged (`shapes=false`, `preset=auto`) so existing designs and tests are byte-stable. Tests: `tests/test_smart_design.py` (14).
* **Stroke satin (`logo_satin`)**: a fill whose estimated stroke width is 0.9-9 mm and that is stroke-like (largest inscribed width <= 1.4 x 9 mm, >= 1 mm) is analysed along its **medial axis**: the filled region is rasterised (0.1 mm or coarser), distance transform (3-4 chamfer), Zhang-Suen thinning, the skeleton is split into branches (a diagonal neighbour counts only when no orthogonal neighbour already reaches it, so staircase corners are not junctions), spurs shorter than the local width are dropped, each remaining branch becomes a satin column whose rails follow the local width (free tips extended by 1.05 x half-width, junction ends by 0.5 x, width x 1.04). The result is accepted only if the columns cover >= 94 % of the shape with <= 14 % spill; otherwise the shape stays a fill (on a test word the 's' falls back to a fill while t, i, c, h become satin). Limits: heavily branched or tapered shapes often fall back to fill; letter quality is not equal to a hand-digitized logo; not machine-tested.
