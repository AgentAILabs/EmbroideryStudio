# Physical stitch-out test (required before any "production ready" claim)

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
| 11 | fill patterns | Same circle as tatami / contour / cross-stitch: density, texture, thread breaks on short stitches |

## Procedure
1. Same fabric + stabiliser + needle + thread + speed for the whole run (record them on `RESULTS.html`).
2. Start at a **conservative speed** (e.g. 600 spm). Stitch each `.dst` once; note thread breaks, puckering, registration, trim behaviour (see below), colour-change position.
3. If something fails, change **one** setting in the Studio (pull comp, spacing, underlay, max stitch, trim jumps), regenerate that design only, and re-stitch.
4. Copy the working values back: fabric presets in `engine/stitchcraft_engine/design.py` (`FABRICS`) and `web/app.js` — they are **unverified guesses until this passes**.

## Trim behaviour — check this first
DST has no trim opcode. Trims are emulated as N consecutive zero-move jumps (Design → Machine → **Trim jumps**, default 3).
Some machines need 2–5 jumps (or a trim code in the machine's own settings). If threads are not cut after a jump, raise it; if the machine stalls or cuts mid-design, lower it.

## Pass criteria (suggested)
No thread breaks at 600 spm · no visible puckering after removing stabiliser as intended · outline within 0.5 mm of fill edge · lettering legible at 5 mm (or note the real minimum) · trims cut cleanly · colour changes land at the expected place.
