# Thread palettes

Palettes imported through *Thread libraries* are stored here as one JSON file each (`<id>.json`). They are **yours**: the repository contains no brand charts (Madeira, Isacord, Gunold, Brother ...)
because that data is licensed; import your own CSV / JSON exports. `palettes/*.json` is git-ignored so licensed charts are never committed by accident.

CSV columns (header row, any order): `code`, `name`, and either `hex` (`#rrggbb`) or `r`,`g`,`b`. JSON: `[{"code": "1005", "name": "Black", "hex": "#000000"}, ...]`.
