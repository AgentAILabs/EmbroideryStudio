# Wilcom "Instant Smart Design" - what is public, and how our pipeline maps to it

**Scope and honesty.** Wilcom EmbroideryStudio is closed-source commercial software. Its source code and algorithm internals are **not published**, so none of it was read or reproduced here. This analysis uses only Wilcom's public help pages (listed at the end). Where the documentation is silent (stitch-type rules, thresholds, speed internals) this file says so and does not guess.

## What Wilcom documents
* **One click, defaults.** "Instant Smart Design" converts the selected bitmap or vector artwork in one step: it decides which colours become **fills**, which become **outlines** and which are **omitted**, and picks stitch types with **default settings**. If the image has not been prepared it processes it automatically (Graphics menu; also on the Auto-digitize toolbar).
* **Preparation (optional, before the click).** *Prepare Bitmap Colors* reduces the number of colours and removes image noise; a **colour matching method** decides whether artwork colours are added to the palette or matched to existing threads; *Crop Bitmap* and *Adjust Bitmap* (lightness / contrast) are other prep tools. Wilcom advises reducing colours to the minimum before digitizing.
* **More control: Smart Design.** The fuller "Smart Design" recognises shapes in the artwork and lets the user **preset suitable stitch types** for conversion.
* **Object model.** Auto-digitized results are **branched** objects; to apply satin-type stitches (Satin, Raised Satin, Zigzag, Blanket) the object must be unbranched first.
* **Related tools.** *Auto Trace to Vectors* (outlines and filled shapes), *Turning Satin / Tatami Fill (with holes) / Centreline Run / Outline Run* from the same menu, *Photo Flash* and **Color PhotoStitch** for photographs.
* **Limits stated by Wilcom.** Results depend heavily on resolution, colour depth and quality of the source; clean bitmaps with minor pixellation convert best.
* **Not documented.** Which stitch type is chosen for which shape, the thresholds, the vectorisation algorithm, and anything about runtime. "In seconds" is the vendor's wording for clean images; no method is published.

## How StitchCraft maps to it (measured / verified in this repo)
| Wilcom step (documented) | StitchCraft | Where |
|---|---|---|
| Prepare Bitmap Colors: reduce colours, remove noise | palette by median cut + perceptual merge of near-identical colours, label cleaning, speck removal | `raster.py` |
| Decide fill / outline / omit per colour | background colour omitted; each region becomes a fill, satin column or run by thickness (thick/thin split), tiny details tack dots or flagged | `raster.py` inventory |
| Default stitch types and settings | fabric + category profiles (density, underlay, pull compensation, shortening) | `profiles.py`, `api_autodigitize` |
| Auto Trace to Vectors | sub-pixel contour tracing, holes kept | `raster.py` |
| Color PhotoStitch / Photo Flash | tonal flow-field **Photo Stitch** engine | `photo.py` |
| Crop / Adjust Bitmap | crop region (garment photos), enhancement with provenance | `motif_isolation.py`, `enhance.py` |
| Instant Smart Design (one click) | **new: "Instant smart design..." (More menu)**: file -> source-quality check -> routed (artwork -> auto-digitize, photo -> Photo Stitch, garment photo -> garment dialog) -> opened in the editor with a summary | `web/app.js instantSmart`, `/api/image/quality`, `/api/autodigitize` |

## Gaps that remain (not hidden)
* **Shape recognition** (circles, rectangles, text recognised as primitives) is not implemented; everything is traced.
* **Thread-chart colour matching** (matching artwork colours to a brand chart) is not implemented; no licensed chart data. Colours are the artwork's own.
* **Speed.** Wilcom is native code; StitchCraft is pure Python. Measured here: artwork conversions take seconds, and complex photographs of embroidery take roughly 5-20 s. No claim of parity.
* **Quality on the customer's pink-silk photos** is limited (see the digitizing reviews); Wilcom's own docs also warn that photographs and low-quality sources need manual work.
* No Wilcom file format (EMB) is read or written, and no Wilcom code or data was used.

## Sources (public Wilcom documentation)
* Auto-digitize 'instant embroidery': https://docs.wilcom.com/embroiderystudio/27/en/OnlineHelp/Automatic/automatic/automatic-9.htm
* Auto-digitize entire designs: https://docs.wilcom.com/embroiderystudio/27/en/OnlineHelp/Automatic/automatic/automatic-10.htm
* Smart Design: https://docs.wilcom.com/embroiderystudio/e4/en/MainHelp/Summary/summary_-_create/Smart_Design.htm
* Prepare bitmaps for auto-digitizing: https://docs.wilcom.com/embroiderystudio/27/en/OnlineHelp/Automatic/automatic/automatic-4.htm
* Auto-digitizing - a Smart Design approach: https://wilcom.com/resources/blog/auto-digitizing-a-smart-design-approach
* Understanding auto-digitizing: https://help.wilcom.com/portal/en/kb/articles/autodigitizing-concept
