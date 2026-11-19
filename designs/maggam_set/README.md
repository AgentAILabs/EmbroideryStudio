# Maggam blouse set (original designs, traditional style)

Built for the reference photos shared on 2026-11-19 (pink silk blouse: gold flowers with kundan stones, red fern sprays, scalloped gold neckline).
These are **original vector designs in that traditional style**, hand-digitized in `tools/make_maggam_set.py` - not traced from the photos.
Regenerate: `python3 tools/make_maggam_set.py`.

| File | Size (mm) | Stitches | Colours | Trims | Hoop needed | Note |
|---|---|---|---|---|---|---|
| `maggam_test_motif.dst` | 43 x 33 | ~920 | 2 | 6 | any 100 x 100 | **stitch this first** |
| `maggam_front_neck.dst` | 198 x 219 | ~11,950 | 2 | 64 | >= 240 x 260 (large / maggam frame) | symmetric U-neck |
| `maggam_back_neck.dst` | 198 x 104 | ~7,050 | 2 | 48 | >= 220 x 130 | half medallion over a scalloped border |
| `maggam_sleeve_left.dst` / `_right.dst` | 115 x 50 | ~2,100 | 2 | - | 130 x 180 | true mirror pair |

Thread order: 1 red, 2 gold (`*.colours.csv`). Stones (5 mm flower centres, 3 mm small flowers) are **not stitched** - positions are on each
production sheet; fix them by hand after embroidery.

Digitizing: silk profile, 120/2 fine thread for red (line spacing ~0.24 mm), gold kept open at 0.35 mm (metallic / zari-look thread breaks
when packed tight - open further to 0.40 if it frays). Every petal and leaflet runs out on a centre-run underlay and returns on its satin
(`end_at_start`), and each fern is sewn as one continuous thread along its stem - that is why the trim counts are low.
All files: 15/15 production checks, six-stage DST verification PASS. **None of them has been stitched yet** - test motif first, on the real
fabric with the real stabiliser (cut-away), then the sleeves, then the necks.
