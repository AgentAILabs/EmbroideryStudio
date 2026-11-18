# EmbroideryStudio user guide

## Run it
```bash
python3 server/app.py          # http://127.0.0.1:8765  (python3 server/app.py 9000 for another port)
```
Only Python 3 and a browser are needed. Pillow + NumPy are used only for PNG/JPG import. The app has **no login**: it listens on
localhost only. Set `ES_HOST=0.0.0.0` only inside a container whose port is published to 127.0.0.1 (see `Dockerfile`).

## A first design in 5 minutes
1. **Hoop** – Design panel → pick a hoop (100×100, 130×180, 4×4 in, 5×7 in …). The solid blue box is the hoop, the dashed box is the safe margin.
2. **Draw** – pick a tool on the left. *Fill*: click the corners, double-click or Enter to finish (or click the first point). *Satin*: click along the centre line. *Column*: draw edge 1, double-click, then edge 2. *Text*: click where it starts, then type in Properties.
3. **Colour** – click a swatch (or Custom) in Properties.
4. **Look at the stitches** – toggle **Stitches** at the top, press ▶ (or **P**) to watch the machine path. Grey dashed lines are jumps (toggle *Jumps*).
5. **Checks** (right panel) – fix red ✖ errors; they block export. Yellow ⚠ are advice.
6. **Export** – *Export DST* (one file), or *Export package* (zip: DST + project + preview + production sheet + manifest).

## Tools
| Tool (key) | What it makes |
|---|---|
| Select (V) | pick, drag to move, drag white handles to edit points, arrows nudge 0.5 mm (Shift 5 mm) |
| Fill (F) / Rect / Ellipse | filled area. Pattern: **tatami** (rows), **contour** (concentric), **cross** (cross-stitch) |
| Satin (S) | satin column of constant width along a line |
| Column (C) | two-rail satin: stitches run edge to edge – petals, leaves, tapers |
| Run (R) | running stitch / outline |
| Text (T) | single-line satin lettering, A–Z 0–9 `- . !`, minimum practical height ≈ 5 mm |
| Appliqué (A) | placement line → tack-down → satin cover; machine stops at the placement→tack-down colour change |
| Bead (E) | bead / stone / sequin **placeholders**: never stitched, listed with positions on the production sheet |

## Object operations (Properties panel)
Name · colour · size in mm (width/height, proportional or free) · rotate by any angle · flip · scale % · duplicate · **repeat** (border/row with an offset) · **Convert to** (fill ↔ satin ↔ run ↔ column) · **column (auto rails)** turns an elongated shape (petal, leaf, curved stroke) into a column – shapes that are blobs, branch, or curl too much are refused with the reason · *Smooth curve* (spline through your points) · *Guide only* (shown dashed, never stitched).
Order in the Objects list **is** the stitch order. Underlay is stitched before the object's top stitching. *Optimise colours* groups objects by thread colour (it warns: layering may change; Undo restores).

## Stitch settings (Pro mode; Beginner hides them)
| Setting | Meaning |
|---|---|
| Direction | tatami row angle |
| Row spacing | distance between rows/rings (0.4 mm is a normal density; smaller = denser) |
| Stitch length | tatami/contour stitch length (1–7 mm typical) |
| Underlay | tatami / edge walk / both / none for fills; auto / centre / edge / none for satin |
| Pull comp | extra length (fill) or width (satin) to offset fabric pull-in – **fabric dependent, test it** |
| Auto-split long stitches | satin stitches longer than the machine max stitch are split with staggered points |

Fabric presets (cotton, silk, georgette, velvet, denim, knit) set starting pull comp/spacing. **They are unverified guesses** until you stitch a test.
Stabiliser (cut-away / tear-away / wash-away / none) is recorded on the production sheet.

## Machine profile and trims (Design panel)
| Setting | Meaning |
|---|---|
| Max stitch | used by the checks and by auto-split of long satin stitches |
| Trim above (mm) | a jump longer than this is trimmed; shorter jumps carry the thread (no cut) |
| Trim jumps | DST has **no trim command**, so a trim is written as N zero-move jumps (default 3). Machines differ - confirm on yours |
| Lock stitch (mm) | tie-in / tie-off stitch length (default 0.6 mm; **0 = no locks**) |
| Trim at colour change / at end | tie off and trim before every colour change / before the end (default on) |

**Sequence the engine writes** at every thread cut (far jump, colour change, end):
`… last stitches → tie-off (back-forth-back along the last stitch) → TRIM → [COLOR CHANGE] → JUMP → first stitch → tie-in (forward-back) → …`
Locks stay inside the geometry just stitched, are never shorter than 0.3 mm, and are skipped (no error) where the adjacent segment is too short to lock reliably.
A jump at or under the trim distance is *carried*: no trim and no locks.

The engine also **starts a run at its nearer end** when that turns a trim into a carried jump (e.g. a satin column after its centre-walk underlay): same needle points, fewer cuts.
Appliqué passes (placement, tack-down, cover) are started a third of the way round the outline from each other so their locks do not stack into one over-dense spot.
The production sheet lists the lock length, how many lock stitches were added, and the trim policy.

## Importing artwork
* **SVG**: fills → fills, strokes → satin (1–7 mm) or running. Unsupported path commands (arcs, S/T) and transforms are rejected/flagged instead of silently distorted. Files with DOCTYPE/entity declarations are rejected.
* **PNG/JPG** (flat colour, ≤ 8 colours): quantised, traced, each colour becomes a fill. You set the real width in mm; low resolution is warned. Photos and gradients digitize badly.
* **PDF**: not supported yet – export as SVG.
* **View DST**: opens an existing `.dst` read-only for inspection and simulation.

## Library and the 3D view
**Library** (top bar) opens a gallery of 12 original bridal motifs - lotus, mandala, marigold, paisley, vine and temple borders, kalash, jhumka, scrolls, rings & heart, BRIDE frame, peacock arch.
Each card shows a thumbnail, size, stitches, colours and estimated time. *Open* loads it into the editor (so you can resize, recolour, change the machine profile), *3D* opens it and shows the 3D view, *DST* downloads the file directly. Search and category chips filter the list.
The designs are drawn from scratch for this project (see `designs/library/README.md`); they are starting motifs, not finished garment layouts, and are not yet stitch-tested.

**3D** (next to Design / Stitches) shows the real stitches as thread: lit, with a sheen along the thread direction, on a woven fabric plane, with later stitches sitting above earlier ones so layering reads correctly.
Drag to orbit, right-drag or Shift-drag to pan, wheel to zoom, double-click to reset. The simulation slider, Step, Play and Reset work in 3D too, so you can watch the design build up; *Fabric* changes the fabric colour (it does not affect the stitches).
3D needs WebGL (every current browser; a locked-down remote desktop may not offer it - the Stitches view always works). It is a visual aid: relief height and thread thickness are illustrative, not a prediction of how thread will behave on your fabric.

## Templates
Borders (stitched): petal, scallop, zigzag satin, dot row – length/size configurable.
Neckline guides (not stitched): round, boat, V, square, back-U, sized in **inches**. These are generic proportions to draw against, not tailoring standards.

## Checks glossary
| Message | Meaning / fix |
|---|---|
| Design does not fit hoop | smaller design or bigger hoop (error: blocks export) |
| Stitch too long (> 12.1 mm) | DST record limit (error). Shorten stitch length / enable auto-split |
| Stitch long (> max stitch) | may snag thread |
| Very short stitch (< 0.3 mm) | increase spacing, simplify tiny shapes (fills now drop sub-minimum rows themselves) |
| Outline crosses itself | the fill/appliqué outline has a bow-tie: redraw it as a simple shape |
| Colour replaced by black | a colour must be `#rgb` or `#rrggbb` |
| Needle penetrations too dense | raise row spacing / lower density |
| Stitched before the fill it overlaps | move the outline/lettering after the fill |
| Satin too narrow (< 1 mm) / loose (> 7 mm) | use running stitch / enable auto-split or use a fill |

## Files
`.esproj` = project (JSON). Autosave lives in the browser; *Save version…* keeps named snapshots in the browser (not in the file) – use Save to keep a file.
Keyboard: V F S C R T A E tools · Ctrl+Z / Ctrl+Y undo/redo · Ctrl+S save · Ctrl+D duplicate · Delete · Esc · Enter · P play · 0 fit · wheel zoom · Space+drag or right-drag pan.

## Before production
Nothing from this app has been stitched on a machine by its authors. Run the **stitch-out test pack** (`testpack/`, procedure in `docs/testing/`) on your fabric and machine first.
