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
| Satin density | 0.40-0.45 mm | ✅ 40 wt on cotton: 0.40-0.45 (auto spacing opens narrow columns to 0.45); thread and fabric factors scale the range, clamped 0.18-0.60 | `profiles.apply_profile` |
| Tatami density | 0.40-0.45 mm | ✅ same, per fabric / thread | `profiles` |
| Underlay | by object + fabric | ✅ ladder by width / area, shifted by fabric and category | `profiles.satin_underlay`, `fill_underlay` |
| Pull compensation | 0.1-0.3 mm | ✅ per fabric 0.15-0.40, capped at 10 % of a narrow satin | `profiles` |
| Minimum stitch | ~0.8-1.0 mm | ✅ profiles drop tatami rows < 0.8 mm (`min_row`), row ends ≥ 0.7 mm, curve shortening never below ~0.8 mm, underlay paths simplified, corner stitches < 0.35 mm pruned, validator floor 0.3 mm. Remaining sub-0.8 mm stitches are tatami row turns (one row spacing / sin of the edge angle) - inherent to every tatami fill, Wilcom's included | `stitches`, `profiles`, checklist item 8 |
| Maximum stitch | 7 mm | ✅ machine profile 7 mm, auto split | `design.machine`, checklist item 9 |
| Satin width | 2-7 mm | ✅ raster digitizer: < 1 mm → running, narrow bands → column, wide → fill; checklist item 3 warns < 1 mm and > 7 mm unsplit | `raster._make_object`, `checklist` |
| Running stitch | 2-3 mm | ✅ 2.0 (maggam) / 2.5 (saree, logo) | `profiles.CATEGORIES` |

## 2. Stitch-type selection
Satin / column for narrow shapes and lettering, tatami for large areas, running for lines < 1 mm: ✅ `raster._make_object` (width by
distance transform / PCA). Zig-zag as a *decorative* stitch: ✅ satin / column *Style: zigzag* (open ≥ 1.2 mm spacing, no underlay, no shortening).

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
stitch shortening on tight curves ✅ (`stitches._shorten_inner`, test: inner-edge penetrations reduced by > 30 %) · overlapping fills: ✅ **cut hidden
layers** - a fill does not sew what later fills / columns / satins / appliqués cover, keeping a 0.6 mm under-lap (underlay 1.0 mm) so no gap opens
(`stitches.tatami_fill(exclude=...)`, on in every profile, per-object switch in Pro mode). Lotus library design: 6,179 → 3,819 stitches, stacked-fill area 23 % → 9 %.

## 4. Underlay
| Type | Implemented | Used by the profile for |
|---|---|---|
| Centre run | ✅ | satin / column 1.5-3 mm |
| Edge run | ✅ | satin 3-4.5 mm; fills (light fabrics) |
| Zig-zag | ✅ new | satin 4.5-6 mm |
| Edge run + zig-zag (double) | ✅ new | satin ≥ 6 mm, or one step heavier on velvet / stretch |
| Tatami underlay | ✅ | fills 25-400 mm² (edge + tatami above) |

## 5. Pull compensation
| Requirement | Implemented |
|---|---|
| Horizontal compensation | ✅ `comp_x`: mm added to the object width, independent of stitch direction (fills, columns) |
| Vertical compensation | ✅ `comp_y`: mm added to the height |
| Satin-column compensation | ✅ `pull_comp` widens the column; `push_comp` shortens its ends |
| Fill-object expansion | ✅ `expand_mm`: outline offset outwards, holes shrink by the same amount; sharp shapes fall back safely (`geometry.outset_ring`) |
| Fabric-specific | ✅ pull 0.14-0.40 mm by fabric (narrow satins capped at 10 % of width), push 0.2 mm on stretch |
Direction-relative pull / push and absolute horizontal / vertical compensation are separate parameters and combine.

## 6. Stitch path
| Algorithm | Implemented |
|---|---|
| Nearest-neighbour sequencing that respects colour order, layering (overlapping objects keep order) and is accepted only if the generated file improves | ✅ `sequence.optimize_sequence` - library travel -7 % to -42 % |
| Region-ordered fills (holes / U / C shapes stitched block by block) | ✅ `stitches._region_order` - ring with a hole 93 → 20 trims; image benchmark trims 1,686 → 467 |
| Jump / trim optimisation | ✅ trims only above the trim distance, run direction chosen to carry short jumps |
| Tie-in / tie-off | ✅ 1.0 mm locks, every cut end |
| Stitch shortening | ✅ |
| Overlap removal | ✅ cut hidden layers with under-lap (above) |
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


## Audit against the specification - 2026-11-19 (measured, not estimated)
168 auto-digitized designs = 4 categories x 7 fabrics x 6 test images (40 wt thread, 80 mm wide, 130 x 180 mm hoop):
| Check | Result |
|---|---|
| Export allowed | 168 / 168, no FAIL |
| 15-item checklist | 15 / 15 on every design, no WARN |
| Longest stitch | 6.2 mm (spec max 7) |
| Satin / tatami spacing, cotton 40 wt | 0.40-0.45 / 0.40 mm (spec 0.40-0.45) |
| Pull compensation | 0.14-0.40 mm by fabric (spec 0.1-0.3, stretch higher on purpose) |
| Running stitch | 2.0 (maggam) / 2.5 mm (saree, logo) (spec 2-3) |
| Stitches < 0.8 mm that are not tatami row turns | median 2.8 %, max 9.1 % |
Fixed by this audit: the auto-digitizer's own default parameters were blocking the fabric profile (pull comp was 0.2 for every fabric,
running stitch 2.0 for every category); light fabrics could drop satin underlay to none on 2-3 mm columns; wide-column auto spacing went
below the spec range (0.36 mm); edge underlay followed dense outline points (0.68 mm stitches); the checklist judged underlay without the
category. Regression guard: `tests/test_digitizing_standard.py` SpecComplianceAuditTests. All delivered DSTs are unchanged.
