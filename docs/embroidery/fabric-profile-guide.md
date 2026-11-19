# Fabric profile guide

**Every fabric profile is EXPERIMENTAL.** The values are starting points (derived from measuring commercial files and from general digitizing practice).
No profile has been stitched out on a machine by this project, and none is "validated". They are never universal settings: fabric, thread, needle, stabiliser and machine decide the real result. Always stitch a sample on your own fabric and stabiliser.

| Profile | Density factor | Pull comp (mm) | Underlay shift | What to expect / warning |
|---|---|---|---|---|
| Cotton | 1.00 | 0.20 | 0 | Stable woven base case |
| Blouse fabric | 1.00 | 0.25 | 0 | Raw silk / cotton-silk |
| Silk | 1.10 | 0.25 | lighter | Fine, slippery; firm stabiliser |
| Georgette / chiffon | 1.12 | 0.30 | lighter | Sheer, shifting; stabiliser needed |
| Velvet | 0.95 | 0.30 | heavier | Pile crushes; heavier underlay |
| Stretch / knit | 1.00 | 0.40 | heavier | Push compensation 0.2 mm |
| Denim / canvas | 1.00 | 0.15 | 0 | Firm, thick |
| **Satin (slippery weave)** | 1.10 | 0.25 | lighter | Shows needle holes, puckers easily; test first |
| **Net / tulle** | 1.15 | 0.30 | lighter | Open mesh: dense fills cut or sink into it. Needs water-soluble or tear-away backing; prefer satin and open fills |
| **Thick / heavy fabric** | 0.95 | 0.15 | heavier | Needs more underlay and a suitable needle; check hooping |

"Underlay shift" moves the automatic underlay one step lighter / heavier (see `profiles.py`). Selecting a profile in the editor shows its explanation and warning; applying one logs the warning (`warning: ...`). `GET /api/fabrics` returns the catalogue with `experimental: true, validated: false` for every entry.

The physical test pack (`testpack/v2`) still covers the original six presets. Satin, net and thick have no test files yet: build them with `tools/make_testpack.py` when you want to test those materials, and record the result in your own report before trusting a preset.

# Machine profiles
`GET /api/machines` lists: Generic Tajima-compatible DST, Ricoma (unvalidated, user-editable) and Custom. Hoop size and needle count are blank until you enter your machine's values; a blank value is reported as "not checked", never assumed. Export is blocked only by a limit you entered (for example a design larger than your maximum hoop). Every profile reports `validated: false`; a note you type in `validated_by` is quoted as your statement, not as verification.
