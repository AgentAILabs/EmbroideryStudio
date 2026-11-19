# Maggam blouse set (original designs, traditional style)

Built for the reference photos shared on 2026-11-19 (pink silk blouse: gold flowers with kundan stones, red fern sprays, scalloped gold neckline).
These are **original vector designs in that traditional style**, hand-digitized in `tools/make_maggam_set.py` - not traced from the photos.
Regenerate: `python3 tools/make_maggam_set.py`.

| File | Size (mm) | Stitches | Colours | Trims | Hoop needed | Note |
|---|---|---|---|---|---|---|
| `maggam_test_motif.dst` | 43 x 33 | ~1,050 | 2 | 6 | any 100 x 100 | **stitch this first** |
| `maggam_front_neck.dst` | 198 x 219 | ~14,000 | 2 | 43 | >= 240 x 260 (large / maggam frame) | symmetric U-neck |
| `maggam_back_neck.dst` | 198 x 104 | ~8,050 | 2 | 44 | >= 220 x 130 | half medallion over a scalloped border |
| `maggam_sleeve_left.dst` / `_right.dst` | 115 x 50 | ~2,370 | 2 | 12 | 130 x 180 | true mirror pair |

Thread order: 1 red, 2 gold (`*.colours.csv`). Stones (5 mm flower centres, 3 mm small flowers) are **not stitched** - positions are on each
production sheet; fix them by hand after embroidery.

Digitizing: silk profile, 120/2 fine thread for red (line spacing ~0.24 mm), gold 0.27 mm - about 25 % more open than the 0.21 mm the measured
commercial files use on every colour, because metallic / zari-look thread breaks when packed tight (open to 0.32 if it frays). Every petal and leaflet runs out on a centre-run underlay and returns on its satin
(`end_at_start`), and each fern is sewn as one continuous thread along its stem - that is why the trim counts are low.
All files: 15/15 production checks, six-stage DST verification PASS. **None of them has been stitched yet** - test motif first, on the real
fabric with the real stabiliser (cut-away), then the sleeves, then the necks.

## Quality round 2 (measured against 20 commercial DSTs of the same genre)
| Metric | Commercial median | v1 | v2 (now) |
|---|---|---|---|
| Trims per 1,000 stitches (front neck) | 4.2 | 5.5 | **3.2** |
| Travel / stitched length | 0.045 | 0.11-0.18 | 0.07-0.13 |
| Satin line spacing | 0.21 | 0.32 | 0.25-0.27 |
| Trims: test / front / back / sleeve | - | 6 / 64 / 48 / 23 | 6 / 43 / 44 / 12 |
How: motif-level sequencing (touching objects stay together, motifs ordered by nearest neighbour + 2-opt, accepted only when machine time
drops); fern pairs share one thread (second fern sewn from the base); neckline / border pieces use edge-run underlay so they chain
end-to-start; petals finish exactly on their start point; gold density 0.35 -> 0.27 mm; first leaflets close to the base.
The remaining travel gap is structural: red and gold are separate passes over alternating motifs.
