# EmbroideryStudio

A web-based embroidery digitizing studio in the spirit of Wilcom EmbroideryStudio / Hatch.
Built on the StitchCraft engine from your zip (pure Python, 26 original tests kept), now with an editor UI.
**Zero third-party runtime dependencies** (Pillow + NumPy only for optional image import).

## Docs
[User guide](docs/user-guide.md) · [Architecture](docs/architecture.md) · [Status audit](docs/status.md) · [Roadmap](docs/roadmap.md) · [Stitch-out test](docs/testing/README.md)

## Run
    python3 server/app.py 8765        # then open http://127.0.0.1:8765
    python3 -m unittest discover -s tests && python3 -m unittest discover -s engine/tests

## Features (working today)
| Area | What you get |
|---|---|
| Manual digitizing | Fill (tatami), Satin column, **two-rail Column** (petals, leaves, tapers), Running stitch, Rectangle, Ellipse, Lettering, Appliqué tools; vertex editing, move, nudge, snap-to-grid |
| Auto digitizing | SVG import (fills → tatami, strokes → satin/run); flat-colour PNG/JPG import (quantise → trace → fills) |
| Lettering | Built-in single-line satin font (A–Z, 0–9, `- . !`), height / spacing / stroke width |
| Appliqué | Placement line → tack-down → satin cover, with fabric-placement stop note |
| Stitch properties | Direction, density, stitch length, underlay (tatami / **edge-walk inset** / both), **pull compensation** (fill + satin), satin width |
| Fabric presets | cotton, silk, georgette, velvet, denim, knit (flagged unverified until stitch-tested) |
| Object tools | Order list (stitch sequence), hide, duplicate, flip, rotate 90°, scale %, **repeat/array** (borders, Maggam-style rows), add border |
| Simulation | Play/pause/step/scrub/speed driven by the real stitch array, needle marker, colour changes |
| Hoops | 100×100, 130×180, 4×4 in, 5×7 in, 200×300, 240×150, custom; safe-margin guide |
| Checks | Hoop fit, long/short/duplicate stitches, density, DST limits; export is **blocked on errors** |
| Output | **Tajima DST** (round-trip verified on every export), project `.esproj`, **production sheet** (colour order, stitch count, size, est. time, preview) |
| Sizing & transforms | Set exact width/height in mm (proportional or free), free rotation, flip, 90° rotate, scale %, convert stitch type (fill ↔ satin ↔ run), optimise colour order |
| Fill patterns | Tatami (rows), **contour** (concentric rings, falls back to tatami for holes/complex shapes) and **cross-stitch** grid |
| Satin-from-outline | Convert an elongated shape (petal, leaf, curved stroke, L) into a two-rail column; refuses blobs/branches/curls with the reason |
| Embellishments & guides | Bead / stone / sequin placeholders (not stitched, listed on the production sheet), non-stitched guide objects, neckline guides in inches, petal/scallop/zigzag/dot border templates |
| Export package | One zip: DST + project + preview + production sheet + manifest (sha256, trim jumps, checks) |
| Satin splitting | Stitches longer than the machine max stitch are split with staggered points (satin, column, lettering), so wide columns up to and beyond the 12.1 mm DST limit stay valid; toggle per object |
| Machine profile | Max stitch, trim distance, trim-jump count (DST has no trim code, so confirm on your machine) |
| Safety | SVG DOCTYPE/entity rejected, PNG/JPEG type sniffing, size/pixel/complexity limits, low-DPI warning, PDF rejected with a clear message |
| Exports | DST, project, preview **SVG + PNG**, production sheet, saved **versions** (browser) |
| Workflow | Undo/redo, autosave, Beginner / Pro modes, keyboard shortcuts (V F S R T A, Ctrl+Z/Y/S/D, arrows, P, 0) |

## Not done yet (honest; full table in `docs/status.md`)
- **Never stitched on a machine** – run the test pack first (`docs/testing/`). Fabric presets, trim-jump default and time estimate are unverified.
- DST export only (PES/JEF/EXP need a reference to validate against); PDF import not supported (export as SVG).
- No Bezier node handles, TrueType / Telugu / Hindi lettering, thread brand charts, accounts/cloud, desktop shell.
- Dockerfile/compose are written and statically tested but **not built** (no Docker daemon was available); the pyembroidery cross-check runs in CI only.

## Stitch-out test pack
`python3 tools/make_testpack.py` writes 11 ready-to-stitch designs (flower, lettering 5/8/12 mm, logo, border, 4-colour, satin widths, 30x30 fill, appliqué, fill patterns) to `testpack/` with a printable results sheet. Procedure: `docs/testing/README.md`.

## Tests
Run everything with `./tools/run_tests.sh` (engine suite + studio suite: engine features, HTTP round trips, geometry quality, safety limits, performance, docs/front-end guards). CI runs exactly that script on every push. `tools/e2e_ui.js` drives the whole UI in a browser (needs Playwright; run it before releases).
