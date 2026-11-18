# Bridal motif library (original designs)

Twelve motifs for blouse, saree-border and wedding work: lotus, mandala rosette, marigold, paisley pair, floral vine border,
temple border, kalash, jhumka, scroll pair, rings & heart, BRIDE frame, and the peacock-in-arch panel.

**Where they come from:** every design is drawn from scratch by `tools/make_library.py` (plus `tools/make_peacock_panel.py`) as
geometry in code, using traditional motif *types* (lotus, paisley, kalash …) that are common cultural vocabulary. No photo, catalogue
or third-party design was copied, traced or converted. You decide the licence for the repository.
If you want a design from your own artwork or from a designer who has given you the right to use it, import it
with the app's *Import art* (SVG, or flat-colour PNG/JPG) - photos of other people's finished work are not a source this project converts.

**What they are not:** these are **starting motifs**, not finished garment layouts. Beads, stones and pearls are hand work and are
not in any DST (the jhumka lists its pearl positions on the production sheet). Nothing here has been stitched on a machine yet.

| Rule every design passes | |
|---|---|
| Engine checks | no errors, no warnings, no notes (short stitches, density, hoop fit, sequence, self-crossing outlines …) |
| Colours | at most 4 thread colours (fewest colour stops) |
| Files | `<id>/<id>.dst`, `<id>/<id>.esproj` (open in the Studio), `<id>/<id>.thumb.svg`; `index.json` lists them for the Library panel |
| Reproducible | `python3 tools/make_library.py` rewrites everything; a test fails if the committed files drift from the source |

Open the **Library** panel in the app to browse thumbnails, open a design for editing, view it in 3D, or download the DST.
Before using any of them on a garment, stitch a scrap: see `docs/testing/README.md`.
