# DST validation rules

Every DST released by the studio (`/api/dst`, export package, placement sets) goes through `engine/stitchcraft_engine/export_pipeline.py::export_dst`.
A file that fails any stage is **never returned**; the caller gets a structured error `{error, stage, code, issues[]}` (HTTP 400).

## Stages
| # | Stage | What is checked | Refusal codes |
|---|---|---|---|
| 1 | generate | design -> stitch plan; nothing to stitch is a plain validation error | `EXPORT_NO_STITCHES` |
| 2 | validate | geometry/parameter checks, 15-item production checklist (FAIL blocks) | checklist/validation codes |
| 3 | write | `dst.write_dst` | - |
| 4 | decode-compare | file re-read by a **separate, hand-typed decoder** (own bit table, not shared with the writer) and walked against the plan | see below |
| 5 | independent-reader | `pyembroidery` when importable (CI always); otherwise reported `NOT RUN` | `EXPORT_READER_MISMATCH` |
| 6 | report | counts, size, SHA-256, engine version, UTC time, three validation sections | - |

## Decode-compare rules
* Each plan stitch/jump becomes the exact number of records (max movement 121 units = 12.1 mm per record) and lands within 0.6 unit (0.06 mm) of the quantised target; engine Y is down, file Y is up (`EXPORT_MISMATCH`, `EXPORT_MOVE_LIMIT`).
* Colour changes and trims (N zero-move jumps) appear exactly where the plan has them.
* The file ends with a single END record; only one stray `0x1A` byte may follow (`EXPORT_BAD_END`, `EXPORT_EXTRA_RECORDS`, `EXPORT_TRUNCATED`).
* Decoded width/height equal the plan's within 0.11 mm - catches swapped or scaled axes (`EXPORT_DIMENSIONS`).
* Header `CO`, `ST` and `+X/-X/+Y/-Y` match the decoded content (`EXPORT_BAD_HEADER`).

## What this is not
All of the above is **software validation**. It proves the file says what the stitch plan says. It does not prove the machine stitches it well; the report always states `physical_machine: NOT DONE` until stitch-out evidence exists.
