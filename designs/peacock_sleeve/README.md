# Peacock-in-arch – sleeve-end panels (scaled pair)

> **Stitch these only after the main panel (`designs/peacock_arch`) has passed your test.** The sleeve files are generated from the same
> source; any change the panel test calls for will be regenerated here too. Not stitched on any machine yet.

| | |
|---|---|
| Size | 63.1 × 94.0 mm (2.5 × 3.7 in) – the main motif at 65 %. Change with `--scale` |
| Hoop | 100 × 130 mm or larger (the design is centred) |
| Files | `A/peacock_sleeve_A.dst` (as drawn, head to the right) and `B/peacock_sleeve_B_mirrored.dst` (true mirror image, fill direction mirrored too) |
| Stitches | ≈ 2,480 each · 3 colours (lime → red → gold) · ≈ 33–35 trims · ≈ 7.5 min |
| Left or right sleeve? | Compare the machine preview with your reference photos: pick the file whose peacock faces the same way as the sleeve you are making. Do **not** rotate one file 180° – that is not a mirror image. |

**Details left out at this size:** the 7 gold feather eyes (they fall below the 1.5 mm minimum satin width after scaling). Their red sequin positions stay on the production sheet.
The net-sleeve vine and threadwork above the arch in the reference photo are **not** included (hand/aari work on tulle needs its own design and a different stabiliser approach).

Beads / stones / pearl / sequins are not in the DST; see each `*.production-sheet.html`.

## Regenerate
```bash
python3 tools/make_peacock_panel.py designs/peacock_sleeve/A --scale 0.65 --name peacock_sleeve_A
python3 tools/make_peacock_panel.py designs/peacock_sleeve/B --scale 0.65 --name peacock_sleeve_B_mirrored --mirror
```
A test fails if the committed files drift from the source. Stitch-out procedure and fixes: see `designs/peacock_arch/README.md`.
