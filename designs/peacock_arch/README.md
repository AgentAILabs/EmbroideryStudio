# Peacock-in-arch panel – stitch-out guide

**What this is:** a hand-digitized, *simplified interpretation* of the peacock-in-arch motif from the reference blouse photos
(front / back panel; the sleeve-end panel is the same motif at a smaller size). It is **not** a copy, and it has **never been stitched** –
you are the first test. Treat the first run as a proof, not production.

| | |
|---|---|
| Size | 95.7 × 144.0 mm (3.8 × 5.7 in) |
| Hoop | at least **130 × 180 mm (5 × 7 in)**; design is centred on the DST origin |
| Stitches | ≈ 4,230 · 3 colours (2 colour changes) · 44 trims · ≈ 11 min at 700 spm (assumed) |
| Colour order | 1 lime green (body, tail feathers) → 2 red (head, wing, feathers, flower) → 3 gold (arch, leaf, fronds, neck, beak, outlines) |
| Fabric / stabiliser | planned for silk-type blouse fabric with **cut-away** stabiliser – these are *unverified* starting values |
| Not stitched (hand work) | gold beads on the inner arch, stones (flower centre, leaf tip), pearl (eye), red sequins (tail eyes) – positions are on `*.production-sheet.html` |

## Before this design: stitch `12_trims_locks` from the test pack
It tells you how your Ricoma treats the trim jumps. Findings → Design panel → Machine (Trim jumps, Lock stitch mm). Regenerate this panel after changing them.

## Test run (do these in order)
1. **Scrap first**: same fabric + stabiliser as the blouse, hooped drum-tight. Never the real garment first.
2. Typical starting points (use whatever you normally run on silk blouse fabric - these are generic, not verified for this design): sharp needle 75/11 (65/9 for fine silk), 40 wt polyester/rayon top thread, 60 wt bobbin. Start slow, **500–600 spm**.
3. Load `peacock_arch_panel.dst`. Check the machine's design preview shows an arch with a peacock, **upright and not mirrored** (flower above the arch apex).
4. Stitch. Watch for: thread breaks at the small gold leaf tips (satin ≈ 2 mm), puckering around the lime body fill, gaps between the red/lime fills and the gold outlines (registration), trims cutting cleanly, colour stops where the sheet says.
5. Record results on a copy of `testpack/RESULTS.html` (fabric, stabiliser, needle, speed, thread breaks, puckering, registration).

## If something is off
| Symptom | Change (Studio → open `.esproj`) |
|---|---|
| Fills pull in / outline gaps | raise *Pull comp* on the fills (0.3 → 0.5), or the fabric preset |
| Puckering | cut-away stabiliser, add a second layer, reduce density (*Row spacing* 0.45 → 0.5) |
| Thread breaks in satin leaves | raise *Row spacing* (0.4 → 0.45); slow the machine |
| Threads not cut / cut too often | *Trim jumps* 2–5, *Trim above* (mm) |
| Loose thread ends | *Lock stitch* 0.8–1.0 mm |

Please send back what you see (photos of the front and back of the scrap, plus the numbers above) and I will tune the design and defaults.

## Regenerate
`python3 tools/make_peacock_panel.py` rewrites everything in this folder from the single source file. A test fails if the committed files drift from the source.
