# Technical audit report

Audit date: 2026-11-19 · baseline commit: `f166279`+`9a94b02` (main). Method: read the code, **reproduce each defect with a script**, record the outcome, then fix and re-verify.
Statuses are updated as phases land; a row is only "Verified" when its regression test exists and passes.

## Baseline (before this upgrade)
| Check | Result |
|---|---|
| Engine tests | 32 / 32 pass |
| Studio tests | 362 run, 359 pass, 3 skipped (pyembroidery not installed in this environment; CI runs them) |
| Browser end-to-end (`tools/e2e_ui.js`) | 46 / 46 |
| DST provenance (`designs/`, `testpack/`, `testpack/v2/`) | 78 files: 66 CURRENT, 11 STALE (test pack v1), 1 NO-SOURCE (kept for traceability) |
| CI (main, pyembroidery installed) | green; 362 + 32 tests, none skipped |
| Performance | 300 separate fills (78,628 stitches): generate 0.4 s, DST write 0.28 s |
| Physical machine validation | **none** |

## Issue register
Severity: Critical / High / Medium / Low / Info.

| ID | Sev | Finding | Root cause | Component | Reproduction (actual output) | Fix | Regression test | Status |
|---|---|---|---|---|---|---|---|---|
| I-01 | High | Unexpected server errors are silent | `H.do_POST` catches `Exception`, returns `{"error":"internal error: <Type>"}`; `log_message` is a no-op; nothing is logged | `server/app.py` | monkeypatch `generate` to raise: HTTP 500, body `internal error: RuntimeError`, **0 bytes** on stderr and logging | structured logging + request id returned to the client | `tests/test_enterprise.py` (planned, Phase 7) | Open |
| I-02 | High | A corrupted DST is accepted as a valid export | `api_dst` re-reads the file but only checks END + colour-change count; positions / stitch & jump counts / dimensions are never compared with the generated sequence | `server/app.py::api_dst`, `sheet.package` | writer patched to flip 1 bit of one stitch record → export **accepted**; writer patched to delete one stitch record → export **accepted** | validated-export pipeline (decode-compare) | `tests/test_export_pipeline.py` (25 tests: 1-bit flip, delete/insert record, jump/colour/trim mutations, truncation, trailing data, lying header, historic X/Y swap in writer+reader) | **Fixed - verified** (Phase 2) |
| I-03 | Med | No machine profile | hoop presets only; "Ricoma" appears as text in wizard steps; machine limits not modelled | engine + UI | n/a (absence) | `machines.py` | planned Phase 6 | Open |
| I-04 | Med | No quality score | checklist is a pass / warn / fail list | `checklist.py` | n/a | `quality.py` 8-category score | planned Phase 3 | Open |
| I-05 | Med | Invalid fill geometry is silently stitched or gives an unhelpful error | only fill self-crossing is checked | `design.generate` | hole **outside** outline → 562 stitches, no error, no note; hole **crossing** the outline → 583 stitches, no error; duplicate outer ring / zero-area ring → generic "no stitches generated" | `validate_geometry` | planned Phase 3 | **Fixed - verified** (Phase 3, `tests/test_quality.py`) |
| I-06 | Med | No coverage-gap check, no runtime boundary check | validators look at stitch lengths and density only | `validate.py` | fill with `spacing: 4.0` (large gaps) → **no warning**, 89 stitches | `quality.py` coverage + boundary | planned Phase 3 | **Fixed - verified** (Phase 3, `tests/test_quality.py`) |
| I-07 | Med | Simulation lacks inspection and is not the file | no step back, trim marker, per-object visibility, stitch inspector; plays engine floats, not the quantised DST | `web/app.js`, `/api/generate` | UI inspection: only play / step / reset / slider / speed / jump toggle | simulation from the **re-decoded DST** + controls | planned Phase 5 | Open |
| I-08 | Med | Production report incomplete | HTML sheet lacks jump / trim split, engine version, timestamp, machine, separate validation sections | `server/sheet.py` | n/a | `report.py` | planned Phase 6 | Open |
| I-09 | Med | Segmentation cannot be reviewed before digitizing | raster import goes straight to objects | `raster.py`, wizard | n/a | segmentation review step | planned Phase 5 | Open |
| I-10 | Low | No group / ungroup, entry-exit hints, rulers | not built | `web/app.js` | n/a | Phase 5 | | Open |
| I-11 | Low | Fabric profiles missing: satin, net, thick | not built | `profiles.py` | n/a | add (experimental) | Phase 6 | Open |
| I-12 | Low | No rate limiting | not built | `server/app.py` | 400 rapid requests → 400 accepted in 0.3 s | token bucket | `tests/test_enterprise.py` | Open |
| I-13 | Info | 11 stale v1 test-pack DSTs | engine changed after they were written | `testpack/` | `tools/dst_provenance.py` | superseded README + v2 pack | `tests/test_testpack_v2.py` | **Verified** (handled earlier) |
| I-14 | Info | Performance baseline | - | engine | 300 fills / 78k stitches: 0.4 s + 0.28 s | perf budget tests at larger sizes | Phase 7 | Open |

## Prompt's 25 "hidden issue" areas - where each stands
| # | Area | Status / evidence |
|---|---|---|
| 1 | X/Y transposition | Fixed (`1980975`); `tests/test_dst_axis.py` - re-introducing the swap fails 12 of its 18 tests |
| 2 | +/- movement encoding | byte-pin vectors (`engine/tests`), axis suite |
| 3 | Scaling / units | 0.1 mm units; rectangle / non-square dimension tests |
| 4 | Centring, hoop positioning | centring + hoop tests. **Note:** the design is centred on its **bounding box**, not on a hoop centre; where the machine puts DST (0,0) is machine-dependent → physical test 13 |
| 5 | Trims | implemented (3 zero-move jumps) - **unverified on a machine**; Phase 4 added the travel/trim report (`travel.py`) for a trim justification report |
| 6 | Long jumps / travel | `sequence.py`; Phase 4 travel report |
| 7 | Density | `validate.py` DENSITY, checklist; Phase 3 score |
| 8 | Short / long stitches | validators; clustered-short metric in `dst_analyze` |
| 9 | Satin width | checklist item 3, engine split of wide columns |
| 10 | Fill gaps / overlaps / angles | overlaps: cut-hidden-layers; **gaps: I-06 open** |
| 11 | Underlay | profiles + ladder |
| 12 | Pull comp | pull / push / H-V comp |
| 13 | Needle penetrations near boundaries | **I-06 open** (runtime boundary check) |
| 14 | Unnecessary overlap | cut hidden layers, checklist 7 |
| 15 | Sequencing | `sequence.py` |
| 16 | Colour change errors | `validate.py` COLOR_SEQ / DOUBLE_COLOR |
| 17 | Paths crossing empty regions | Phase 4 |
| 18 | Invalid geometry | **I-05 open** |
| 19 | Missing small details | raster pipeline drops specks (reported in notes) - Phase 5 review step lets the user restore them |
| 20 | DST headers / END / records | `dst_verify` stage 1-2, hand-written vectors |
| 21 | Preview ≠ DST | axis suite agrees geometry; **I-07 open** (simulation still plays float data) |
| 22 | Large designs / machine limits | hoop check, 12.1 mm record split; machine-limit profile **I-03 open** |
| 23 | Memory / performance | **I-14** baseline only |
| 24 | Background jobs failing silently | no background jobs exist (all synchronous); the silent-failure risk is **I-01** |
| 25 | Invalid-but-successful exports | I-02 fixed in Phase 2 (decode-compare pipeline) |
