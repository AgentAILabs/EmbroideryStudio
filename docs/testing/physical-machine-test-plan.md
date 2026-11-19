# Physical machine test plan (PENDING - to be done by a person on a real machine)

**Status: NOT STARTED. No result exists. This software cannot produce one. Do not mark any item as passed without the evidence listed here.**
Use `testpack/v2` (hash-listed in `MANIFEST.json`, `"physically_validated": false`), the checklist `docs/testing/machine-test-checklist.md` and the blank sheet `docs/testing/machine-test-report-template.md` / `testpack/v2/RESULTS.csv`.

Before you start: confirm the files are current (`python3 tools/dst_provenance.py testpack/v2` -> nothing stale). Record machine model, controller firmware, needle, thread (brand / weight), bobbin, stabiliser, fabric, hoop, speed (spm).

| # | Area | Test file(s) | What to record (evidence) | Pass criterion (set by you before stitching) |
|---|---|---|---|---|
| 1 | **Axis / orientation / dimensions** - do it first | `13_axis_orientation`, `01_flower` | photo with a ruler; measured W x H vs the design size in the report | asymmetric shape appears un-mirrored, un-rotated; size within your tolerance |
| 2 | Hoop boundary / extents | `16_hoop_boundary` | does the machine accept it; trace result | no frame-limit alarm at the declared hoop |
| 3 | Trims and jump behaviour (3 zero-move jumps; trim above 3 mm) | `12_trims_locks`, `15_jump_movement` | trims actually cut? thread tails left? count of unwanted jump threads | the machine trims as the report assumes (else adjust `trim_jumps`) |
| 4 | Lock (tie-in / tie-off) stitches | `12_trims_locks` | does the thread hold when pulled | locks hold |
| 5 | Colour changes / thread order | `07_four_colour` | sequence matches the report's thread sequence | order identical |
| 6 | Fill density / pull compensation | `09_fill_30x30`, `11_fill_patterns` | measured shape vs design (mm), gaps, puckering | gaps/puckering within tolerance |
| 7 | Satin widths and corners | `08_satin_widths` | thread breaks, loops, coverage per width | no repeated breaks at widths you intend to use |
| 8 | Small lettering | `02..04_lettering_*`, `14_running_small` | legibility at 5/8/12 mm | legible at the smallest height you will sell |
| 9 | Applique | `10_applique` | placement/tack-down/cover registration | cover hides the edge |
| 10 | Fabric presets | `17..22_fabric_*` (+ satin / net / thick if you generate them) | puckering, show-through, sinking, per fabric | per fabric decision: keep / adjust / reject the preset |
| 11 | Needle breaks, thread breaks, skipped stitches, bird nests | all | counts per file and where (stitch number from the inspector) | zero tolerated or your own limit |

Evidence required per row: file name + SHA-256 prefix (from the export report), photo, measured values, who/when, notes. A row without evidence stays "not tested".
When results exist, a person records them in the report template; only then may `docs/status.md` and the production report's physical section change - and only for the specific machine / fabric / file tested. The software will not infer compatibility for any other machine.
