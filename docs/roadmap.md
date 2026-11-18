# Roadmap
Done: see `docs/status.md` (audited matrix of every planned item).

## Next, in order
1. **Physical stitch-out** of `testpack/` (procedure: `docs/testing/`). Tune fabric presets, trim jumps, pull comp from the results. Nothing below should be called production-ready before this.
2. ~~Run CI and confirm the pyembroidery cross-check~~ **done**: CI is green; the cross-check found and fixed the X/Y swap in the DST writer (see `docs/status.md`). Extend it to more designs (appliqué, columns, patterns) when convenient.
3. PES / JEF / EXP writers, each validated against pyembroidery (and a real machine) before shipping.
4. Bezier node handles; Shapely-backed robust inset (replace the pure-Python miter inset where it refuses).
5. TrueType lettering → satin, then Telugu/Devanagari (font files + shaping rules needed).
6. Thread brand charts (licensed data), hoop split for large designs, stitch-level editing, gradient/stipple/motif fills.
7. Hosted/desktop: accounts + cloud library, then a Tauri/WebView2 shell reusing the same API.
