# EmbroideryStudio vs Wilcom EmbroideryStudio - core functionality, honest state

Wilcom column = general product knowledge of the Wilcom EmbroideryStudio e-series (not freshly verified against current vendor documentation - re-check before quoting externally).
EmbroideryStudio column = what exists in this repository **today**, with the test or file that proves it. ✅ done and tested · ◐ partly · ❌ not built.
Nothing here is machine-proven except what `docs/status.md` says was stitched. Wilcom is a mature commercial product with decades of stitch-engine tuning; this is a young open codebase and the table says where it falls short.

## Core digitizing and stitch engine
| Capability | Wilcom | EmbroideryStudio | Evidence / gap |
|---|---|---|---|
| Tatami fill, angle, density, pull comp, underlay | many fill types, per-object | ◐ tatami (region-ordered, cut hidden layers, min row length) + contour + cross; angle / spacing / pull / push / expansion / H-V comp; underlay tatami, edge, edge+tatami | `stitches.py`; no stitch-effect library (gradient, stipple, carving, motif fills) |
| Satin (centre-line + two-rail column), underlay, auto-split of long stitches | yes, corner handling, auto-spacing | ✅ satin + two-rail column; underlay centre / edge / zig-zag / edge+zig-zag; auto spacing by width; curve shortening; split of long stitches; **sharp corners split into overlapping pieces** (`corner_pieces`: 73 → 0 folded stitches in the test) | no automatic corner/join handling, no variable-width satin tool |
| Running stitch, outline | yes, many run types (bean, motif run) | ◐ single and **bean (triple) run**, closed run | no motif run |
| Appliqué | automatic placement/tack/cover | ✅ placement → tack → satin cover, staggered starts, **1:1 cutting template** (patch = outline + 1/3 cover width, 50 mm scale bar) in every package | `sheet.applique_cut_svg` |
| Lettering | many fonts, TrueType, on-path, auto-size | ◐ one built-in satin font, A-Z 0-9 | no TrueType, no Indic/Arabic shaping, no text on path |
| Thread-weight / density presets | per fabric and thread | ✅ 40 wt / 60 wt / 120/2 spacing presets, fabric presets | `design.THREADS`; values derived from measuring 20 commercial files, not stitch-tested |
| Auto trims, tie-in/tie-off, colour-change handling | yes | ✅ lock stitches (1.0 mm), trim trains, trim at colour change/end, smart start direction | trim test pack exists; **machine results pending** |
| Pull-compensation / push-pull per object | yes | ✅ pull and push (direction-relative), horizontal / vertical, fill-outline expansion, fabric-specific | `tests/test_overlap_push.py` |
| Stitch editing (move individual needle points) | yes | ❌ | roadmap |
| Node (Bezier) editing | yes | ◐ polyline points + smoothing | no Bezier handles |

## Artwork, digitizing aids
| Capability | Wilcom | EmbroideryStudio | Evidence / gap |
|---|---|---|---|
| Vector import | many | ◐ SVG | `svg_input.py` (unsupported SVG features are reported); no AI/EPS/PDF/CDR |
| Raster auto-digitize | AutoDigitize / Magic Wand | ◐ flat-colour PNG/JPG → palette → per-shape fill / column / run, quality presets, report | benchmark: mean IoU 0.95 on test art; photos are flagged, not digitized |
| Image enhance before tracing | image clean-up tools | ✅ 2× upscale + sharpen for blurry / small images | `raster.enhance_image`, measured gain |
| Hoop / frame management, safe area | machine-specific hoops | ◐ hoop presets + custom, safe margin | no machine-specific hoop database |
| Design library | large | ◐ 12 original bridal motifs with thumbnails + 3D view | no catalogue of third-party designs (deliberately - licensing) |

## Production output (the focus of this round)
| Capability | Wilcom | EmbroideryStudio | Evidence / gap |
|---|---|---|---|
| **Same design for left / right / neck as separate named files** | mirror/duplicate + manual export per placement | ✅ **Placement set**: left, right (true mirror), neck, back neck, front, back, sleeves, centre; optional size per file; standard file names; one zip | `placements.py`, `/api/placements`, UI dialog, `tests/test_placements.py` |
| Auto-correction before export | design checker + manual fixes | ✅ conservative auto-fix: fit/scale to hoop, centre, drop specks, hairline column → run, duplicate points, density relief loop, every change logged | `placements.autofix`, tests |
| DST export | yes | ✅ validated by independent decoder (pyembroidery) in CI | `tests/test_crosscheck.py` |
| Other formats (PES, JEF, EXP, ...) | many | ◐ DST, EXP | PES/JEF need vendor palettes; not built |
| Reading third-party DST | yes | ✅ tolerant reader (real-world EOF byte), simulator view, full six-stage report | `dst_verify.py`; checked on 20 commercial files |
| Pre-flight verification | design checker | ✅ six stages: container, encoding, machine limits, stitch quality, thread path, simulation | UI Quality check, `/api/dst/report`, CLI |
| Production sheet / worksheet | yes | ✅ HTML sheet: colour order, stitches, time, embellishments, checks | `sheet.py` |
| Stitch simulation | realistic + 3D | ✅ stitch player + WebGL 3D thread view | `viewer3d.js` |
| Machine connectivity / networking | yes | ❌ | out of scope for a web app |
| Colour charts (Madeira, Isacord ...) | licensed charts | ❌ hex colours only | licensing |

## Platform
| Capability | Wilcom | EmbroideryStudio | Note |
|---|---|---|---|
| Runs on | Windows desktop | browser, any OS; stdlib Python server, Docker | no install on the client |
| Accounts, cloud sync, permissions | yes (separate products) | ❌ | roadmap |
| Beginner / pro modes | steep learning curve | ✅ Beginner / Pro | |
| Price | commercial licence | open code | |

## Where Wilcom is clearly ahead (do not claim parity)
Stitch-effect libraries and 30+ years of tuned auto-digitizing; lettering fonts and TrueType; machine-specific profiles and formats; node/stitch-level editing; certified colour charts; networking. The goal of this project is a **correct, verifiable DST pipeline for repeated placements (sleeve pairs, neck panels) with a simple web UI**, not feature parity.
