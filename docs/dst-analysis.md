# DST analysis: what 20 commercial files taught us

Input: two supplier packs (D821 - 12 files, D9857 - 8 files; blouse / sleeve / neckline embroidery, up to 505 x 405 mm, 262,039 stitches in total).
Method: `tools/dst_analyze.py` reads every byte (our own reader, no third-party code), `tools/dst_verify.py` runs a six-stage check.
The files are third-party commercial designs: they were **measured, not copied** - nothing from them is in the repo, only the numbers below.

## What the real files do (medians over all 20 files)

| Property | Measured | Ours before | Ours now |
|---|---|---|---|
| Satin line spacing (advance per stitch) | **0.21 mm** (same-side penetrations 0.42 mm) | 0.40 mm (40 wt thread) | 0.40 default; **0.22 mm with the 120/2 preset** |
| Median stitch length / p95 | 2.49 / 5.06 mm | 3.05 / 4.04 mm | unchanged |
| Stitches shorter than 0.5 mm | 0.56 % (0.04 % clustered) | up to **28.7 %** (scroll_pair) | 3.5 % mean, 0.65 % clustered (rest = lone row turns and locks) |
| Stitches longer than 7 mm | 0.0 % | 0.0 % | 0.0 % |
| Tie-in (when present) | 4 x 1.0 mm back-and-forth; tie-off 2 x 0.5 mm | 0.6 mm | **1.0 mm** |
| Trim | train of 8-13 short jump records (2 mm chunks), then `S(0,0)` | 3 zero-move jumps + travel | unchanged (machine-tested path; see trim test pack) |
| Header `ST` | count of **all** records incl. END | same | same |
| File end | END record then a lone `0x1A` byte | END only | writer unchanged, **reader now accepts it** |
| Underlay | centre run only, ~3 mm stitches; none on narrow satin (< 2 mm) | centre run, but **0.5 mm stitches** in columns | ~2.5 mm stitches |
| Density | p90 4 penetrations/mm2, peak 26 | peak 13 | peak 13 (40 wt), 17 (120/2) |
| Design style | almost all satin, motifs repeated and trimmed between | - | - |

## Defects this found in our engine (all fixed, all covered by tests)

1. **Our reader rejected 19 of the 20 real files** (it demanded a multiple of 3 bytes; real files end with a `0x1A` EOF byte). Now tolerant: accepts the EOF marker / zero padding, still rejects garbage after END and files cut off before END.
2. **Column underlay had a needle penetration every 0.5 mm** (the column's sampling step leaked into the underlay). About 5x too many penetrations on every column, outline->satin and image-import column: scroll_pair went 2,114 -> 1,508 stitches, short stitches 28.7 % -> 1.3 %. Underlay paths are now simplified (0.1 mm tolerance) before stitching.
3. **Tatami rows ended in 0.3-0.5 mm stubs** (the stagger phase). End stitch is now at least 0.7 mm; round-shape rings thinned at 0.6 mm instead of 0.3 mm.
4. **Satin tips tapering to a point produced sub-0.3 mm stitches**; they are dropped.
5. **Lock stitches were 0.6 mm**; production files use 1.0 mm. Default is now 1.0 (the UI field and validation range are unchanged, 0.4-1.5).
6. **No way to match fine thread.** A satin at 0.4 mm line spacing under-covers 120/2 blouse thread (0.2 mm diameter) - fabric shows through. New **thread weight** setting (40 wt / 60 wt / 120/2) scales line spacing for every stitched object that does not set its own, and the density check scales with it.
7. **Docker image had no `designs/` folder** (the library panel would have been empty). Fixed.

Evidence: `docs/dst-compare.png` (same 22 x 22 mm window of a commercial sample, our v1, v2 and v2 with the fine-thread preset).

## Verification stages (`tools/dst_verify.py`, UI: Quality check, API: `POST /api/dst/report`)

1. **container** header vs records (ST / CO / extents), END record, trailing bytes
2. **encoding** every record re-encodes to the same bytes; pyembroidery cross-decode when installed (always in CI)
3. **machine** 12.1 mm record limit, long / clustered-short stitches, needles, hoop fit
4. **stitch** penetrations per mm2, thread-break clusters, satin line spacing
5. **thread path** trims, tie-in / tie-off coverage, orphan runs, travel vs stitched length
6. **simulation** replayed path inside the hoop, run time estimate

All 12 library designs and both peacock versions pass with no FAIL. The 20 commercial files are also run through it as a sanity check of the checker itself: it flags real differences (e.g. D821 has no lock stitches, relying on the machine) and fails only the files that really exceed a 300 x 330 mm hoop.

## What this does not prove

* Nothing here has been stitched. Numbers describe files, not sewing quality; thread, needle, fabric and stabiliser decide the rest.
* 0.21 mm is what these two suppliers ship for fine thread on light fabric. It is a sensible starting point for 120/2, **not** a universal rule - test on your fabric.
* We did not copy anyone's digitizing: no geometry, no ordering, no design content from the samples is used.
* The v1 peacock (hash `368c90c4...`) is kept untouched in `designs/peacock_arch/v1_tested/` so the first machine test stays traceable. v2 and `fine_120/` are new files that have **not** been stitched.
