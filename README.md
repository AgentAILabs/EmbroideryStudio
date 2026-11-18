# EmbroideryStudio

A web-based embroidery digitizing studio in the spirit of Wilcom EmbroideryStudio / Hatch.
Built on the StitchCraft engine from your zip (pure Python, 26 original tests kept), now with an editor UI.
**Zero third-party runtime dependencies** (Pillow + NumPy only for optional image import).

## Run
    python3 server/app.py 8765        # then open http://127.0.0.1:8765
    python3 -m unittest discover -s tests && python3 -m unittest discover -s engine/tests

## Features (working today)
| Area | What you get |
|---|---|
| Manual digitizing | Fill (tatami), Satin column, Running stitch, Rectangle, Ellipse, Lettering, Appliqué tools; vertex editing, move, nudge, snap-to-grid |
| Auto digitizing | SVG import (fills → tatami, strokes → satin/run); flat-colour PNG/JPG import (quantise → trace → fills) |
| Lettering | Built-in single-line satin font (A–Z, 0–9, `- . !`), height / spacing / stroke width |
| Appliqué | Placement line → tack-down → satin cover, with fabric-placement stop note |
| Stitch properties | Direction, density, stitch length, underlay, **pull compensation** (fill + satin), satin width |
| Fabric presets | cotton, silk, georgette, velvet, denim, knit (flagged unverified until stitch-tested) |
| Object tools | Order list (stitch sequence), hide, duplicate, flip, rotate 90°, scale %, **repeat/array** (borders, Maggam-style rows), add border |
| Simulation | Play/pause/step/scrub/speed driven by the real stitch array, needle marker, colour changes |
| Hoops | 100×100, 130×180, 4×4 in, 5×7 in, 200×300, 240×150, custom; safe-margin guide |
| Checks | Hoop fit, long/short/duplicate stitches, density, DST limits; export is **blocked on errors** |
| Output | **Tajima DST** (round-trip verified on every export), project `.esproj`, **production sheet** (colour order, stitch count, size, est. time, preview) |
| Workflow | Undo/redo, autosave, Beginner / Pro modes, keyboard shortcuts (V F S R T A, Ctrl+Z/Y/S/D, arrows, P, 0) |

## Not done yet (honest)
- Not machine-tested: stitch `samples` on a test fabric before production (matrix in `docs/requirements-finalized.md` §F).
- Lettering is a simple stroke font, no TrueType fonts, no Telugu/Hindi yet.
- Only DST export (PES/JEF/EXP planned; pyembroidery cross-check needs network).
- No auto edge-inset underlay / skeleton satin-from-outline (needs Shapely); no node curves (polylines only).
- No accounts / cloud; projects are local files + browser autosave.
See `docs/roadmap.md`.
