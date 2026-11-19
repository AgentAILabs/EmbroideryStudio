# DST regression test report

Run: `./tools/run_tests.sh` (engine 32 + studio 387, 3 skipped locally where pyembroidery is absent; CI runs them with pyembroidery).

| Suite | Purpose |
|---|---|
| `tests/test_dst_axis.py` | hand-written byte vectors, horizontal / vertical / diagonal / asymmetric shapes, centring, preview agreement, hoop |
| `tests/test_export_pipeline.py` (25) | valid fixtures (circle, complex polygon, hole geometry, multi-colour + trims, +/- quadrants, satin + run, 300 mm jump = max-movement records) release a complete report; mutations are refused: 1-bit flip, deleted/inserted record, stitch->jump, colour change removed, trim shortened, truncated file, trailing data, lying `CO` / extents header, mirrored/scaled plan, **historic X/Y table swap in writer and reader**; every bit flip in the first 60 records is caught; wiring (`api_dst`, package, placement set) refuses a corrupted writer |

Physical machine results: none. See `docs/testing/physical-machine-test-plan.md` (Phase 7).
