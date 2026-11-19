#!/usr/bin/env python3
"""DST provenance check: is this .dst exactly what the CURRENT engine writes for its own project file?

A .dst next to a .esproj is regenerated in memory and compared byte for byte.
  CURRENT  identical to what the current engine writes
  STALE    differs: it was written by an older engine (e.g. before the DST X/Y axis fix, or before later stitch changes).
           Do NOT stitch it as if it were current - regenerate it (see docs/testing/regeneration-procedure.md)
  NO-SOURCE a .dst with no .esproj beside it: origin cannot be verified (treated as unverified, never as current)
Exit code 1 when anything is STALE or has no source, so CI / a script can refuse to ship it.
Usage: python3 tools/dst_provenance.py [DIR ...] [--json out.json] [--allow-stale DIR]"""
import hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from stitchcraft_engine.design import generate, machine  # noqa: E402
from stitchcraft_engine.dst import write_dst              # noqa: E402


def check(dst: Path) -> dict:
    esp = dst.with_suffix(".esproj")
    data = dst.read_bytes()
    row = {"file": str(dst.relative_to(ROOT)), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    if not esp.exists():
        row["status"] = "NO-SOURCE"; return row
    try:
        d = json.loads(esp.read_text())["doc"]
        pattern, _, _ = generate(d)
        new = write_dst(pattern, trim_jumps=machine(d)["trim_jumps"]).data
    except Exception as e:  # noqa: BLE001
        row["status"] = "ERROR"; row["error"] = str(e)[:120]; return row
    row["status"] = "CURRENT" if new == data else "STALE"
    row["current_sha256"] = hashlib.sha256(new).hexdigest()
    return row


def scan(dirs):
    out = []
    for d in dirs:
        for f in sorted(Path(d).rglob("*.dst")):
            out.append(check(f))
    return out


def main(argv):
    dirs = [a for a in argv if not a.startswith("--") and not a.startswith("{")] or ["designs", "testpack"]
    skip = []
    if "--allow-stale" in argv:
        i = argv.index("--allow-stale"); skip = [argv[i + 1]]; dirs = [d for d in dirs if d != argv[i + 1]]
    rows = scan([ROOT / d for d in dirs])
    for r in rows:
        print(f"{r['status']:9} {r['file']}")
    bad = [r for r in rows if r["status"] != "CURRENT"]
    print(f"\n{len(rows)} file(s): {len(rows) - len(bad)} CURRENT, {len(bad)} not current")
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps(rows, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
