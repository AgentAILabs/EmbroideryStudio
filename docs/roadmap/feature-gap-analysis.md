# Feature gap analysis

Maintained alongside `docs/status.md`. **Rule: no control appears in the production UI until its feature works and has tests.** Planned features live here, not in the interface.
Priority: **P1** = needed to trust output or to use the product in a shop · **P2** = clearly valuable next · **P3** = later / conditional.
Complexity: **S** days · **M** 1-3 weeks · **L** 1-2 months · **XL** a quarter or more.

## Summary
| # | Feature | State today | Priority | Complexity | Blocked by |
|---|---|---|---|---|---|
| 0 | **Physical machine validation** (not a feature, the gate for everything) | not done - no stitch-out evidence exists | **P1** | S per round, needs a person at a machine | access to the machine; `testpack/v2` is ready |
| 1 | PES / JEF / EXP formats | **DST only is exposed.** EXP writer exists unexposed (experimental, off by default); PES / JEF not started | P2 | M each | reference files from vendor software, vendor palettes, fixtures |
| 2 | TrueType / OpenType lettering | **partially implemented** (see note A) | P2 | M to finish | fonts with the right licences; machine test of small lettering |
| 3 | Telugu lettering | **not verified** - shaping engine present, never run with a Telugu font | P2 | M | a licensed Telugu font; native-speaker review of the output |
| 4 | Hindi (Devanagari) lettering | **not verified** - same as Telugu | P2 | M | a licensed Devanagari font; native-speaker review |
| 5 | Bezier node editing | not implemented (polyline points + smoothing only) | P2 | L | editor model change (curve types in the JSON contract, engine flattening, undo) |
| 6 | Thread brand catalogs | not implemented (hex colours only) | P3 | M | **licensed** brand colour data (Madeira, Isacord ...) - cannot be reproduced from memory |
| 7 | User accounts | not implemented (single-user local tool, no login) | P3 | L | hosting decision, auth provider, data model |
| 8 | Cloud storage | not implemented (projects are local files; versions are per-browser) | P3 | L | accounts (7), object store, privacy / retention policy |
| 9 | Windows desktop application | not implemented | P3 | L | stable API (exists), packaging choice (Tauri / WebView2), code signing, update channel |
| 10 | PDF import | **unsupported on purpose**; UI tells the user to export SVG / PNG / JPG | P3 | L | a PDF vector parser (no dependency allowed on the shop laptop) |
| 11 | Machine / hoop database (Ricoma frames etc.) | not implemented; generic hoop presets only | P2 | S | **verified** frame dimensions from the machine / vendor documentation |

**Note A - TrueType.** The product brief lists TrueType lettering as not implemented. The repository has it since 2026-11-19: *More ▾ → TrueType lettering…* shapes text with FreeType + HarfBuzz (Pillow Raqm), renders it, and digitizes it through the image pipeline (fill / column / run by stroke width). It is tested with DejaVu Sans (Latin, Arabic joining) and refuses characters the font lacks. What is **not** done: Indic scripts with a real Telugu / Devanagari font, hand-tuned per-letter satin (Wilcom-style), small-size legibility on a machine, a font library. It is therefore listed as partial and unverified, and the dialog says so.

## Details
### 0. Physical validation (gate)
* Current evidence: software-level only (`docs/testing/current-validation-report.md`).
* Next step: stitch `testpack/v2` in the documented order (`docs/testing/machine-test-checklist.md`), return the filled `RESULTS` sheet.
* Exit criteria: orientation correct (design 13), trims behave (12), no thread breaks at 600 spm on the chosen fabric; only then can a preset for that fabric lose the "experimental" label.
* Everything below that touches stitch output (presets, trim defaults, time estimates) waits for this.

### 1. PES / JEF / EXP
* Architecture is ready: `engine/stitchcraft_engine/formats.py` registry (`supported` / `experimental` / `planned`). A format is exposed only when registered as supported.
* Per format, the minimum: a valid reference file written by vendor software, hand-written byte fixtures, an independent reader agreeing, a stitch-out.
* PES additionally embeds a thread block and needs the vendor palette; JEF needs its 78-colour palette. Do not guess either.
* EXP: writer + pyembroidery read-back in CI exist; no reference file or machine has confirmed it, so it stays unexposed.

### 2-4. Lettering (TrueType, Telugu, Hindi)
* Done: shaping (HarfBuzz), missing-glyph refusal, uploaded fonts, text on a path for the built-in font.
* To do: ship nothing without a licence check; collect 2-3 Telugu and 2-3 Devanagari fonts the user is licensed to use; run conjunct-heavy test words; visual review by a native reader; stitch at 8 / 12 / 20 mm; decide minimum legible size per script; consider converting glyph outlines to satin columns directly (cleaner than tracing a bitmap).
* Risk: stitched complex-script letters are legible only above a certain height; an unreadable name on a garment is a customer-facing failure.

### 5. Bezier node editing
* Needs a curve type in the design JSON (`schema_version` bump + migration), flattening in the engine with a tolerance setting, handle UI, hit-testing, undo / redo, SVG import mapping the original curves instead of flattening them.
* Dependency for good text-on-path of TrueType glyph outlines.

### 6. Thread catalogs
* Data licensing is the blocker, not code. Options: user imports their own catalog CSV; or a generic palette named as such. Never ship brand names with invented values.

### 7-9. Accounts, cloud, desktop
* Treat as one product decision ("hosted shop product" vs "local tool"). The engine API is already separable. Do not start before machine validation proves the output.

## Deliberately not planned
* Claiming machine compatibility from successful export alone.
* Auto-importing third-party copyrighted designs.
