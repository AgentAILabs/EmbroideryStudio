import argparse, json, sys, pathlib
from .dst import write_dst, read_dst
from .pipeline import digitize_svg, Settings
from .preview import preview_svg
from .svg_input import parse_svg
from .validate import validate


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="stitchcraft_engine", description="SVG -> validated Tajima DST")
    ap.add_argument("svg"); ap.add_argument("out_dir")
    ap.add_argument("--hoop", default="100x100", help="hoop WxH in mm")
    ap.add_argument("--margin", type=float, default=3.0)
    a = ap.parse_args(argv)
    hw, hh = (float(v) for v in a.hoop.lower().split("x"))
    out = pathlib.Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    name = pathlib.Path(a.svg).stem
    doc = parse_svg(open(a.svg, encoding="utf-8").read())
    pattern, notes = digitize_svg(doc, Settings(), name)
    rep = validate(pattern, hw, hh, a.margin)
    for n in notes: print("NOTE   ", n)
    for i in rep.issues: print(f"{i.severity.upper():7}{i.code}: {i.message}" + (f" (record {i.index})" if i.index >= 0 else ""))
    if not rep.ok:
        print("Export blocked: fix errors above."); return 2
    res = write_dst(pattern)
    back = read_dst(res.data)
    assert back.ends_properly and back.color_changes == int(back.header["CO"]), "round-trip validation failed"
    (out / f"{name}.dst").write_bytes(res.data)
    (out / f"{name}.stitchcraft.json").write_text(json.dumps(pattern.to_dict()))
    (out / f"{name}.preview.svg").write_text(preview_svg(pattern, hw, hh))
    print(f"OK {name}.dst  records={res.record_count} counts={pattern.counts()} sha256={res.sha256[:16]}…")
    print("NOT machine-validated: stitch this on a test fabric before production use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
