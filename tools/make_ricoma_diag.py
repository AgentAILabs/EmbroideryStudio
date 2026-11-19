#!/usr/bin/env python3
"""Ricoma display diagnostic set (testpack/ricoma_diag). Three small single-colour DSTs, 8.3-style upper-case names, increasing in features, so the first one that
fails to appear / preview on the machine isolates the cause. Nothing here has been stitched; MANIFEST.json says so."""
import hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from stitchcraft_engine import export_pipeline as EP, sections as SEC

def sq(x, y, w, h): return [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]
BOX = {"id": "box", "type": "run", "color": "#000000", "points": sq(0, 0, 30, 30)}
CROSS = {"id": "x", "type": "run", "color": "#000000", "points": [[0, 0], [30, 30]]}
FILL = {"id": "f", "type": "fill", "color": "#000000", "rings": [sq(5, 5, 20, 20)[:4]]}
CASES = [  # name, objects, machine overrides, what it isolates
    ("RD1", [BOX], {"lock_len": 0, "trim_at_end": 0, "trim_at_color_change": 0}, "plain running square, no locks, no trims: the simplest valid DST"),
    ("RD2", [BOX, CROSS], {}, "adds lock stitches, a trim and the 3-zero-jump trim emulation (our production defaults)"),
    ("RD3", [BOX, FILL], {}, "adds a tatami fill with underlay (a few hundred stitches)")]

def build(out: Path):
    out.mkdir(parents=True, exist_ok=True); man = []
    for name, objs, mach, why in CASES:
        d = {"name": name, "hoop": {"w": 100, "h": 100, "margin": 3}, "machine": mach, "objects": objs}
        ex = EP.export_dst(d); (out / f"{name}.DST").write_bytes(ex.data)
        checks = SEC.dst_checks(ex.data, d["hoop"]); bad = [c for c in checks if c["result"] == "FAILED"]
        man.append({"file": f"{name}.DST", "sha256": ex.sha256, "bytes": len(ex.data), "records": ex.record_count, "stitches": ex.report["counts"]["stitch"], "size_mm": ex.report["size_mm"], "isolates": why,
                    "software_checks": "no FAILED check" if not bad else bad, "physically_validated": False})
    (out / "MANIFEST.json").write_text(json.dumps({"pack": "ricoma_diag", "physically_validated": False, "files": man}, indent=1)); return man

if __name__ == "__main__":
    for m in build(ROOT / "testpack" / "ricoma_diag"): print(m["file"], m["bytes"], "B", m["stitches"], "stitches", m["size_mm"], m["software_checks"])
