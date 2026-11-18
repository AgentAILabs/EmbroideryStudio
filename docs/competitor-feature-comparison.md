# Competitor feature comparison (from general product knowledge - NOT freshly verified)
Tags: MVP / P2 = Phase 2 / P3 = Phase 3. Re-verify against current vendor docs before publishing externally.
Wilcom = EmbroideryStudio, Hatch = Hatch Embroidery, I/S = Ink/Stitch (Inkscape extension, open source).

| Feature | Wilcom | Hatch | I/S | StitchCraft tag | Implemented today |
|---|---|---|---|---|---|
| Design workspace | Full, customisable | Simplified | Inside Inkscape | MVP | No (UI not started) |
| Artwork import | Raster+vector | Raster+vector | SVG | MVP (SVG, flat PNG/JPG) | SVG only (engine) |
| Vector editing | Node editing | Node editing | Inkscape | P2 | No |
| Auto digitizing | Yes (paid module) | Yes (AutoDigitize) | Limited (trace/fill) | MVP (rule-based), P3 (smart) | SVG rules only |
| Manual digitizing | Strong | Good | Via paths | P2 | No |
| Running stitch | Yes | Yes | Yes | MVP | Yes |
| Satin | Yes (auto corner/split) | Yes | Yes | MVP | Yes (basic; no corner handling) |
| Tatami/fill | Many patterns | Many | Auto-fill | MVP | Yes (scanline, staggered) |
| Underlay | Many types | Many | Several | MVP (centre/edge/fill) | Yes (basic) |
| Density | Per object | Per object | Per object | MVP | Param only |
| Stitch direction | Yes | Yes | Yes | MVP | Fill angle only |
| Pull compensation | Yes | Yes | Yes | MVP | Satin only |
| Thread colour mgmt | Brand charts | Brand charts | Inkscape colours | MVP basic, P2 brands | Hex only |
| Lettering | Extensive fonts | Extensive | Yes | P2 (MVP: basic) | No |
| Appliqué | Yes | Yes | Yes | P2 | No |
| Transformations | Yes | Yes | Inkscape | MVP | No |
| Stitch simulation | Yes | Yes | Yes | MVP | Preview SVG only |
| Machine config | Many machines | Many | Basic | MVP (Tajima DST) | Validator params |
| Hoop management | Yes | Yes | No | MVP | Bounds check only |
| Formats | Many | Many | Many | MVP DST, P2 PES/JEF/EXP | DST |
| Production info | Yes | Yes | Basic | MVP basic | Counts only |
| Design library | Yes | Yes | No | P2 | No |
| Export / print | Yes | Yes | Limited | MVP | DST+JSON+SVG |
| Beginner UX | Steep | Friendlier | Steep | MVP differentiator | Not started |
