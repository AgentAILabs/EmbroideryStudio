# Stitch-quality rules (software validation)

Implemented in `engine/stitchcraft_engine/quality.py`; API `POST /api/quality`; the score is also in every export report.
**Everything here is software validation of the design and the stitch plan. It is not a prediction of stitch-out quality on any machine, fabric or thread.**

## Geometry rules (`validate_geometry`) - errors block DST export
| Code | Severity | Rule |
|---|---|---|
| GEO_NON_FINITE | error | missing / NaN / infinite coordinate |
| GEO_TOO_FEW_POINTS | error | ring < 3 points; run/satin/rail < 2 points |
| GEO_ZERO_AREA | error | ring area < 0.05 mm2 |
| GEO_ZERO_LENGTH | error | all points of a run/satin identical |
| GEO_DUPLICATE_RING | error (auto-fixable) | identical rings cancel under the even-odd rule and leave a hole |
| GEO_SELF_INTERSECT | error | ring crosses itself |
| GEO_RING_CROSS | error | hole crosses or touches the outline / another ring |
| GEO_RAIL_CROSS | error | the two rails of a satin column cross |
| GEO_HOLE_IN_HOLE | warning | ring inside a hole becomes an island |
| GEO_DISJOINT_RING | warning | ring outside the first outline stitches as a separate piece, not a hole |
| GEO_SATIN_SELF_CROSS | warning | satin centre line crosses itself |
| GEO_TINY | warning | fill < 1 mm2 |

## Runtime checks on the generated stitches (warnings)
* `Q_OUTSIDE_BOUNDARY` - sampled stitches farther outside their object than the compensation tolerance.
* `Q_COVERAGE_GAP` - raster check (cell 0.5 mm or coarser for big designs, each stitch covers its cell + 8 neighbours): >3 % of a fill interior unstitched. Patterned fills are skipped; designs over 200k stitches skip the check and say so.

## Score (0-100, unweighted mean of 8 categories; each category lists its evidence)
| Category | How it is scored |
|---|---|
| Geometry | 100 - 30/error - 8/warning - 6/boundary or coverage warning |
| Stitch length | each 1 % of stitches outside min-max length costs 10 points |
| Density | each 1 % of occupied 1 mm cells above the penetration limit costs 5 points |
| Underlay | share of large fills / wide satins that have none (advisory; depends on fabric) |
| Path optimisation | jump length vs stitched length; ratio 0.5 scores 0 |
| Jumps and trims | -10 per long jump carried without a trim, -2 per trim before a very short jump |
| Hoop fit | 0 if outside the safe area, 85 if >95 % used, else 100 |
| DST format | -50 per format error (limit, END, thread index) |

The weights are documented, simple and deliberately not tuned to flatter designs. A high score does not mean the design will stitch well; it means the software found fewer problems.

## Travel and trim analysis (`travel.py`, `POST /api/travel`, summary in every export report)
Every needle move between objects is classified: `colour change`, `trimmed` (justified), `unnecessary trim` (cut before a jump shorter than half the trim distance), `carried` (jump <= trim distance, thread attached), `missing trim` (jump > trim distance carried without a cut). Carried jumps also report the length that crosses empty fabric (no stitches within ~1 mm). The report lists colour changes against the minimum possible (distinct threads - 1; more can be unavoidable because of layering), per-object entry/exit points and the exit-to-next-entry distance. Seconds are estimates only.
The sequence optimiser (`sequence.py`) is covered by property tests: never worse than the input, nothing lost, colour-block order kept, overlapping objects keep their layering, deterministic.

## Simulation source (Phase 5)
`POST /api/generate` with `"decoded": true` writes the DST, proves it equals the plan (decode-compare) and returns the stitches **decoded from the file bytes** (0.1 mm quantised, `source: "dst-file"`). The Stitches/3D views use it by default ("From DST file" toggle); if the file cannot be produced the view falls back to the plan and says so. Controls: play/pause, step forward/back (also Left/Right arrows, Shift = 10), trim markers, jump lines, per-object visibility, click-to-inspect a stitch (index, mm position, length, object, thread), rulers, design size and counts.
Start / end hints: Set start / Set end on an object stores `entry` / `exit`; the engine sews the object in whichever of its two orientations (stitches in order, or exactly reversed) starts and ends nearest the hints - same needle points, never new ones; manual objects are never reversed. Grouping keeps the members next to each other in stitch order. The region review works on detected regions (click one to leave it out), not on individual pixels.

## DST quality options added after the senior-designer review
* **Micro-stitch cleanup** (`machine.micro_clean`, mm, default 0 = off; UI: "Clean micro-stitches below mm"): a stitch closer than this to the previous one (same thread, no jump / trim between) is merged into it. Entry stitches and locks are never removed. On the blue set: stitches under 0.5 mm fell from 4.2 % to 0.9 % (neckline) and 6.6 % to 1.1 % (bird pair). The shape moves by less than the setting. Off by default because it changes stitch data of existing designs.
* **Split for hoop** (`POST /api/split`, UI "Split for hoop", `hooping.py`): a design larger than the hoop becomes one validated DST per hooping. Long runs / satin / columns are cut at the grid lines; fills are never cut (an object too big for one hooping is reported). Grey alignment crosses sit at the tile corners in design coordinates, so neighbouring tiles share physical marks. The grid grows until every tile fits.
* **Density / risk overlay** (Stitches view, "Density / risk"): amber cells > 10 and red cells > 16 penetrations per mm2, red rings on stitches shorter than 0.4 mm.
* **Blue set presets**: mint satin 0.24 / fill 0.28 mm, copper (metallic look) 0.32-0.34 mm, petals under-lap the centre by 0.6 mm, copper rosettes are satin lobes not tiny fills, neckline band 5.6 mm with edge + zig-zag underlay.
None of these has been stitched; they are software measures, and the physical test decides the final values.
