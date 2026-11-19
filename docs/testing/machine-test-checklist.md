# Physical machine test checklist

> **Status: not yet physically validated.** Nothing on this page has been done. A file that exports without errors is **not** evidence that a machine will stitch it
> correctly. Only the completed report (below), signed by the person who stood at the machine, counts.

Use the files in `testpack/v2/` (verify first: `python3 tools/dst_provenance.py testpack/v2` must say every file is CURRENT).
Record everything on `testpack/v2/RESULTS.html` or the template `machine-test-report-template.md`. Leave a field empty if you did not observe it.

## 0. Before you start
- [ ] Hoop size known; hoop-boundary design regenerated for **your** hoop: `python3 tools/make_testpack.py testpack/v2 --hoop WxH[xMARGIN]`
- [ ] Same fabric, stabiliser, needle, thread and (low) speed for the whole run; written on the sheet
- [ ] File hashes noted (`MANIFEST.json`) so the result belongs to a specific file version

## 1. Order of stitching (each step is one file; stop and fix before moving on)
| # | File | Pass means (you decide, record what you saw) |
|---|---|---|
| 1 | `13_axis_orientation` | 60 mm side runs left-right, 40 mm up-down; arrows point right and up; filled square top-right facing the machine; ruler ticks 10 mm apart (measure with a ruler: record the real mm) |
| 2 | `14_running_small` | circle and star closed, even stitch length, no thread breaks |
| 3 | `15_jump_movement` | four crosses at the corners of an ~80 mm square, correct corners, no hoop strike, no drift (cross shapes undistorted) |
| 4 | `12_trims_locks` | thread cut / not cut as listed in `README.md` (1 and 2 mm carried; 3.5, 6, 12, 25 mm cut); ends locked |
| 5 | `08_satin_widths` | each width covers; the 6 mm column is split; no breaks in 1 mm |
| 6 | `09_fill_30x30` | even coverage, outline within ~0.5 mm of the fill edge, puckering noted |
| 7 | `07_four_colour` | colour changes where expected; fills register |
| 8 | `16_hoop_boundary` | **trace the outline on the machine first** - the needle must stay inside the hoop; then stitch |
| 9 | `17`-`22` fabric_* | one per fabric you actually use, **on that fabric**; presets are provisional - note every change you had to make |
| 10 | the rest (`01`-`06`, `10`, `11`) | as needed |

## 2. For every file record
Machine model · fabric · stabiliser · thread · needle · hoop · DST file version (sha256 first 12) · stitch count (from the machine) · thread breaks (number + where) ·
fabric puckering (0-3) · registration (mm) · jump / trim behaviour · overall result (PASS / FAIL / PASS WITH NOTES) · what you changed before re-stitching.

## 3. After the run
- [ ] Failures: change **one** setting in the Studio, regenerate that design only, stitch it again, record both results
- [ ] Only a **PASS** result for a given fabric allows removing the "provisional" label of that fabric preset, and only for that fabric / thread / needle / stabiliser combination
- [ ] Send the filled sheet back; presets, trim defaults and time estimates are updated from evidence only
