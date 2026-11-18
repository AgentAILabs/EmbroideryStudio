# Physical stitch-out test
> **Use only test-pack files generated after the DST axis fix** (see `docs/status.md`). Earlier `.dst` files and zips have X/Y swapped - discard them.
 (required before any "production ready" claim)

Generate (or use the committed `testpack/`): `python3 tools/make_testpack.py`

| # | File | What it isolates |
|---|---|---|
| 01 | flower | End-to-end real artwork: fills, satin, colour changes, trims |
| 02–04 | lettering 5 / 8 / 12 mm | Smallest legible lettering, satin stroke ≥ 1.0 mm, corner behaviour |
| 05 | logo | Curved fill + outline + small text, registration of outline to fill |
| 06 | border | Repeated columns + jumps/trims between motifs |
| 07 | four colour | Colour-change position and fill-to-fill registration |
| 08 | satin widths 1/2/3/4/6 mm | Narrow-satin breaks, pull compensation, **auto-split** on 6 mm |
| 09 | 30×30 mm fill | Density, underlay, pull comp, puckering |
| 10 | appliqué | Placement → tack-down → cover; stop and trim workflow |
| 12 | trims + locks | Bars separated by 1, 2, 3.5, 6, 12, 25 mm jumps (trim threshold is 3 mm), then a colour change and the same again: what gets cut, whether ends stay locked, colour-change trim |
| 11 | fill patterns | Same circle as tatami / contour / cross-stitch: density, texture, thread breaks on short stitches |

## Procedure
1. Same fabric + stabiliser + needle + thread + speed for the whole run (record them on `RESULTS.html`).
2. Start at a **conservative speed** (e.g. 600 spm). Stitch each `.dst` once; note thread breaks, puckering, registration, trim behaviour (see below), colour-change position.
3. If something fails, change **one** setting in the Studio (pull comp, spacing, underlay, max stitch, trim jumps), regenerate that design only, and re-stitch.
4. Copy the working values back: fabric presets in `engine/stitchcraft_engine/design.py` (`FABRICS`) and `web/app.js` — they are **unverified guesses until this passes**.

## Trim behaviour — check this first (design 12)
DST has no trim opcode. Trims are written as N consecutive zero-move jumps (Design → Machine → **Trim jumps**, default 3). Around every cut the engine writes a **tie-off, the trim, a jump, then a tie-in** (Lock stitch 0.6 mm by default).
Stitch `12_trims_locks` first and look for:
1. **Cut or not**: jumps of 1, 2 mm must *not* be cut (carried thread); 3.5, 6, 12, 25 mm must be cut. If nothing is cut at all, raise *Trim jumps* (2–5) or check your machine's trim setting; if it cuts every jump, lower it or raise *Trim above*.
2. **Locks**: pull gently on each cut thread end - the tie-in and tie-off must hold. If the thread slips, increase *Lock stitch* (0.8–1.0 mm); if you see tiny bumps or needle breaks at starts, reduce it.
3. **Colour change**: the thread must be cut before the colour change; if the machine also trims itself, untick *Trim at colour change*.
4. **End**: tail cut and locked.
Record what worked (Trim jumps, Lock stitch mm, Trim above) - those three numbers are the machine profile for this machine.

## Pass criteria (suggested)
No thread breaks at 600 spm · no visible puckering after removing stabiliser as intended · outline within 0.5 mm of fill edge · lettering legible at 5 mm (or note the real minimum) · trims cut cleanly · colour changes land at the expected place.


## Ricoma approval procedure (any new design)
1. Load the DST; check the size on the machine screen equals the production sheet. 2. Trace the outline: it must clear the hoop.
3. Needle, thread, stabiliser as on the sheet. 4. Stitch on the real garment fabric. 5. Watch for thread breaks, puckering, skipped stitches,
registration (outlines on fills), coverage. 6. Write findings in the sheet's *Machine test record*. 7. Change density / underlay / pull comp
in Expert mode, re-run Quality check. 8. Stitch again. 9. Approve for production only after a clean sample.
