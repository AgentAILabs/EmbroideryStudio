# Regenerating DST files (after the X/Y axis fix, or any engine change)

**Why:** DST files written before commit `1980975` have X and Y swapped (transposed). Files written by older engine versions also differ from what the
current engine writes. Never stitch a DST just because it exists; check where it came from.

## 1. Find out what is stale
```bash
python3 tools/dst_provenance.py designs testpack testpack/v2        # CURRENT / STALE / NO-SOURCE per file, exit code 1 if any is not current
```
* **CURRENT**: byte-identical to what the current engine writes from its own `.esproj`.
* **STALE**: differs - written by an older engine. Regenerate.
* **NO-SOURCE**: a `.dst` with no `.esproj` beside it (e.g. `designs/peacock_arch/v1_tested/…`, kept only so an earlier stitch-out stays traceable). Treat as unverified.
* **Any `.dst` from outside this repository, or from before 2026-11-18 14:00 UTC (the axis fix), must be regenerated from its project file**, not edited.

## 2. Regenerate
| What | Command |
|---|---|
| Test pack (new version, v1 untouched) | `python3 tools/make_testpack.py testpack/v2 [--hoop WxH[xMARGIN]]` |
| Library | `python3 tools/make_library.py` |
| Peacock panel / sleeves | `python3 tools/make_peacock_panel.py` (see `designs/peacock_*/README.md`) |
| Maggam set | `python3 tools/make_maggam_set.py` |
| Any design in the editor | open the `.esproj` → Export DST |

## 3. Verify
```bash
python3 tools/dst_provenance.py testpack/v2                 # must print only CURRENT
python3 -m unittest tests.test_dst_axis tests.test_testpack_v2
python3 tools/dst_verify.py testpack/v2 --hoop=100x100      # six-stage software verification
```
CI additionally decodes every written file with the independent `pyembroidery` reader (`tests/test_crosscheck.py`).

## 4. Keep results attached to the file version
Record the SHA-256 (first 12 characters) of each file you stitched. A result for an older hash is **not** a result for the regenerated file.
