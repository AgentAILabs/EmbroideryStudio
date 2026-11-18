# EmbroideryStudio roadmap (vs Wilcom feature set)
Done (v0.3): see README table + smooth (Catmull-Rom) curve mode + sample project in samples/.
## Next (highest value first)
1. **Physical stitch-out** of the test matrix; tune fabric presets from results.
2. Bezier/curve nodes + convert-to-curve; Shapely offsets for robust inset (edge underlay v1 is done in pure Python) and true pull-comp.
3. Satin-from-outline (skeleton rails) so any thick shape becomes a satin column (manual two-rail Column tool is done); corner handling. (Auto-split of long satin stitches is done.)
4. More formats: PES, JEF, EXP (cross-check with pyembroidery/Ink-Stitch in CI).
5. TrueType lettering to satin + Telugu/Devanagari research; arc/envelope text.
6. Thread brand charts (Madeira, Isacord, Gunold) with licensed data; colour-sequence optimiser.
7. Stitch-type extras: contour/spiral/motif fills, programmable patterns, gradient fill, cross-stitch, stipple.
8. Blouse neckline/back templates, hoop split for large designs, auto-trim rules, stitch editing (reshape at stitch level).
9. Teams/accounts, design library, versions; Tauri desktop shell.
