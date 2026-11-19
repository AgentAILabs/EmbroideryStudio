# testpack/v2 - machine test pack (UNSTITCHED)

**Status: not physically validated.** No file here has been stitched; no result exists for any of them. The sheets are blank on purpose.

| File | What it isolates |
|---|---|
| 01-12 | as in v1 (flower, lettering 5/8/12 mm, logo, border, four colours, satin widths, 30 x 30 fill, appliqué, fill patterns, **trims + locks**) |
| **13_axis_orientation** | 60 x 40 mm frame (non-square), horizontal + vertical rulers with 10 mm ticks, arrows on +X and +Y ends, filled square **only top-right**. Stitch it first: confirms the file's X/Y direction on the real machine and gives a measured scale check |
| 14_running_small | small circle + star in 2.5 mm running stitch |
| 15_jump_movement | four crosses at the corners of an 80 x 80 mm square, thread **carried** (no trims): isolates frame movement over long jumps |
| 16_hoop_boundary | the largest area the hoop check allows (94 x 94 for a 100 x 100 hoop, 3 mm margin). **Generate for your real hoop:** `python3 tools/make_testpack.py testpack/v2 --hoop 200x300x5` |
| 17-22 fabric_* | cotton, silk, georgette, velvet, denim, knit: 30 mm tatami + 40 mm satin + outline with that preset's spacing / pull comp - **provisional presets, unverified** |

`MANIFEST.json` lists every file's SHA-256. `RESULTS.html` / `RESULTS.csv` are the record sheets (machine model, fabric, stabiliser, thread, needle, hoop,
DST version, stitch count, thread breaks, puckering, registration, jump / trim behaviour, overall result). Estimated times are **not verified**.
