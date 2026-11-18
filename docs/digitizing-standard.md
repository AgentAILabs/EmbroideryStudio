# Digitizing & quality-control standard - what is implemented

Source: the specification "AI Embroidery Studio - formal digitizing and quality-control specification" (sections 1-13).
Each requirement is mapped to the code that implements it and the test that proves it. ✅ implemented + tested · ◐ partial · ❌ not built.
All values are **starting values, not certified settings**: fabric, thread, needle, stabiliser and the machine decide the final ones,
and nothing here replaces a stitch-out on the Ricoma (section 9).

**Decision on section 13:** both modes. *Professional Auto Digitizing* = the **Auto digitize** wizard; *Expert Manual Digitizing* =
the existing editor in Pro mode (angles, density, underlay incl. zig-zag, pull comp, shortening, region order, start direction, thread order).
First category: **Maggam blouse neck**; maggam floral, saree border and logo are profiles too.

**Honesty about "AI":** the digitizer is rule-based computer vision (colour clustering in CIELAB, sub-pixel contour tracing, shape-width
rules), not a trained neural network. It is deterministic and measurable (`tools/image_bench.py`: shape match IoU 0.95 on test art) but it
does not "understand" a photo of a blouse. Flat-colour artwork in, editable objects out.

## 1. Core parameters
| Parameter | Spec | Implemented | Where |
|---|---|---|---|
| Satin density | 0.40-0.45 mm | ✅ 0.40 x thread x fabric x width factor (auto spacing), clamped 0.18-0.60 | `profiles.apply_profile` |
| Tatami density | 0.40-0.45 mm | ✅ same, per fabric / thread | `profiles` |
| Underlay | by object + fabric | ✅ ladder by width / area, shifted by fabric and category | `profiles.satin_underlay`, `fill_underlay` |
| Pull compensation | 0.1-0.3 mm | ✅ per fabric 0.15-0.40, capped at 10 % of a narrow satin | `profiles` |
| Minimum stitch | ~0.8-1.0 mm | ◐ hard floor 0.3 mm (validator), tatami row ends ≥ 0.7 mm, curve shortening never below ~0.8 mm, sub-0.35 mm corner stitches pruned. Lone 0.2-0.4 mm row turns of tatami are inherent and reported separately | `stitches`, checklist item 8 |
| Maximum stitch | 7 mm | ✅ machine profile 7 mm, auto split | `design.machine`, checklist item 9 |
| Satin width | 2-7 mm | ✅ raster digitizer: < 1 mm → running, narrow bands → column, wide → fill; checklist item 3 warns < 1 mm and > 7 mm unsplit | `raster._make_object`, `checklist` |
| Running stitch | 2-3 mm | ✅ 2.0 (maggam) / 2.5 (saree, logo) | `profiles.CATEGORIES` |

## 2. Stitch-type selection
Satin / column for narrow shapes and lettering, tatami for large areas, running for lines < 1 mm: ✅ `raster._make_object` (width by
distance transform / PCA). Zig-zag as a *decorative* stitch: ◐ a satin with open spacing (Pro mode) - no dedicated decorative zig-zag tool.

## 3. Density - fabric-aware engine
| Fabric | Density factor | Pull comp | Underlay shift |
|---|---|---|---|
| Cotton | 1.00 | 0.20 | 0 |
| Blouse (raw silk / cotton silk) | 1.00 | 0.25 | 0 |
| Silk | 1.10 (lighter) | 0.25 | -1 (minimal) |
| Georgette / chiffon | 1.12 | 0.30 | -1 |
| Velvet | 0.95 | 0.30 | +1 (support the pile) |
| Stretch / knit | 1.00 | 0.40 | +1 |
| Denim / canvas | 1.00 | 0.15 | 0 |
Automatic satin spacing ✅ (narrow opens up, wide closes up) · fewer penetrations in narrow objects ✅ · underlay instead of more top density ✅ (ladder) ·
stitch shortening on tight curves ✅ (`stitches._shorten_inner`, test: inner-edge penetrations reduced by > 30 %) · overlapping fills: ◐ the image
digitizer produces non-overlapping regions; for hand-made designs overlap is **measured** (checklist item 7) but not cut away automatically.

## 4. Underlay
| Type | Implemented | Used by the profile for |
|---|---|---|
| Centre run | ✅ | satin / column 1.5-3 mm |
| Edge run | ✅ | satin 3-4.5 mm; fills (light fabrics) |
| Zig-zag | ✅ new | satin 4.5-6 mm |
| Edge run + zig-zag (double) | ✅ new | satin ≥ 6 mm, or one step heavier on velvet / stretch |
| Tatami underlay | ✅ | fills 25-400 mm² (edge + tatami above) |

## 5. Pull compensation
Satin / column width ✅ · fill row length along the stitch direction ✅ · fabric-specific ✅ · separate horizontal / vertical (push) values ❌ (one value per object) ·
fill-outline expansion perpendicular to the rows ❌.

## 6. Stitch path
| Algorithm | Implemented |
|---|---|
| Nearest-neighbour sequencing that respects colour order, layering (overlapping objects keep order) and is accepted only if the generated file improves | ✅ `sequence.optimize_sequence` - library travel -7 % to -42 % |
| Region-ordered fills (holes / U / C shapes stitched block by block) | ✅ `stitches._region_order` - ring with a hole 93 → 20 trims; image benchmark trims 1,686 → 467 |
| Jump / trim optimisation | ✅ trims only above the trim distance, run direction chosen to carry short jumps |
| Tie-in / tie-off | ✅ 1.0 mm locks, every cut end |
| Stitch shortening | ✅ |
| Overlap removal | ◐ detection only (above) |
| Auto split | ✅ |

## 7. DST format
512-byte header, 3-byte records, 0.1 mm units, relative moves, stitch / jump / colour change / end ✅ (cross-checked with pyembroidery in CI).
Thread colours are not in DST → **separate colour sequence report** `{name}.colours.csv` ✅ in every package and placement set, plus the production sheet.

## 8. The 15 mandatory checks (export gate)
`engine/stitchcraft_engine/checklist.py`, shown in the wizard and in Quality check, `POST /api/checklist`. **Any FAIL blocks Export DST**
(server side, not just the button). All 15 are computed from the design, the generated stitches and the written-and-reopened DST:
1 image cleaned & vectorised · 2 hoop limits · 3 satin widths · 4 fill density vs fabric · 5 underlay where required · 6 pull comp ·
7 overlapping stitches · 8 short stitches · 9 long stitches split · 10 no unintended long jumps · 11 trims + colour stops ·
12 tie-in / tie-off · 13 stitch count · 14 DST header + command sequence · 15 DST reopened + simulated.

## 9. Ricoma testing
Wizard step 6 lists the procedure (tick-boxes kept in the browser) and the production sheet now has a **machine test record** table
(needle, thread, fabric, stabiliser; thread breaks, puckering, skipped stitches, registration, coverage, trims; approval signature).
Results feed back as parameter changes in Expert mode. **No file in this repository has been approved by a stitch-out yet.**

## 10. Architecture
Engine 1 (understanding): `raster.py` (+ `enhance_image`) · Engine 2 (digitizing): `profiles.py`, `stitches.py`, `design.py`, `sequence.py` ·
Engine 3 (validation): `validate.py`, `dst_verify.py`, `checklist.py`. Machine and fabric profiles are data (`profiles.FABRICS`, `design.machine`), not hard-coded in the digitizer.

## 11. Production profiles
`profiles.CATEGORIES`: blouse neck, maggam floral (satin + tatami, high detail), saree border (satin + running, lighter underlay), logo (satin + fill).

## 12. Ink/Stitch
Not adopted as the engine. It is GPL-3 and would make this codebase GPL; it runs inside Inkscape (an install on the user's machine,
which is not allowed on the office laptop); and our own engine is already validated byte-for-byte against an independent DST reader. Its
documentation was used as a reference for terminology only.
