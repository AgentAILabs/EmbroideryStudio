# Machine test report  *(template - copy one per stitch-out session; every field below is to be filled by the person at the machine)*

> This template is intentionally empty. No test result exists in this repository until a person fills in a report. Do not pre-fill, estimate or copy results.

| Field | Value |
|---|---|
| Report date | |
| Operator | |
| Machine model (and head / software version) | |
| Hoop (type and size, mm) | |
| Fabric (fibre, weight, weave / knit) | |
| Stabiliser (type, weight, layers) | |
| Thread (brand, type, weight) | |
| Needle (type, size) | |
| Machine speed (spm) | |
| Pack version | `testpack/v2` (MANIFEST.json sha256 of the manifest: ) |

## Per design
| Design file | DST version (sha256, first 12) | Stitch count shown by the machine | Thread breaks (number, where) | Puckering (0 none - 3 severe) | Registration (outline vs fill, mm) | Jump / trim behaviour | Colour-change position | Measured size mm / orientation correct? | Overall result (PASS / FAIL / PASS WITH NOTES) | Changes made before re-stitching |
|---|---|---|---|---|---|---|---|---|---|---|
| 13_axis_orientation | | | | | | | | | | |
| 14_running_small | | | | | | | | | | |
| 15_jump_movement | | | | | | | | | | |
| 12_trims_locks | | | | | | | | | | |
| 08_satin_widths | | | | | | | | | | |
| 09_fill_30x30 | | | | | | | | | | |
| 07_four_colour | | | | | | | | | | |
| 16_hoop_boundary | | | | | | | | | | |
| 17_fabric_… (one per fabric used) | | | | | | | | | | |

## Observations that change the software
| Question | Answer |
|---|---|
| Did the thread get cut where the file requested a trim? Number of trim jump records that worked (2 / 3 / 4 / 5 / 6) | |
| Tie-in / tie-off held? Lock length that worked (mm) | |
| Was the time estimate within ±20 %? Actual run time vs the estimate | |
| Which provisional fabric values did you have to change, and to what? | |
| Any file that cannot be loaded by the machine (message shown)? | |

Overall conclusion (free text, signed): ______________________________
