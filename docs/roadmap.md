# Roadmap
Done: see `docs/status.md` (audited matrix of every planned item).

## Next, in order
0. **Stitch-out of the v2 files** (`designs/peacock_arch/`, `fine_120/`) next to the v1 file; compare coverage and trims. Tune the thread presets from what you see.
1. **Physical stitch-out** of `testpack/` (procedure: `docs/testing/`). Tune fabric presets, trim jumps, pull comp from the results. Nothing below should be called production-ready before this.
2. ~~Run CI and confirm the pyembroidery cross-check~~ **done**: CI is green; the cross-check found and fixed the X/Y swap in the DST writer (see `docs/status.md`). Extend it to more designs (appliqué, columns, patterns) when convenient.
3. ~~EXP writer~~ **done** (validated against pyembroidery in CI; it caught my wrong trim opcode). PES / JEF stay out: they need vendor thread palettes (78 / 65 colours) that cannot be reproduced reliably.
4. Bezier node handles; Shapely-backed robust inset (replace the pure-Python miter inset where it refuses).
5. TrueType lettering → satin, then Telugu/Devanagari (font files + shaping rules needed).
6. Thread brand charts (licensed data), hoop split for large designs, stitch-level editing, gradient/stipple/motif fills.
7. Hosted/desktop: accounts + cloud library, then a Tauri/WebView2 shell reusing the same API.
