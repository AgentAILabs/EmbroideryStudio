"""Machine-format registry (the architecture for future format adapters).

DST is the only format validated by the full pipeline (decode-compare + independent decoder). The other encoders are "software_verified": each is read back with the independent
pyembroidery library and every stitch position is compared (tests/test_encoders.py, CI, and at export time when the library is present). That is software evidence only - no format
has been loaded on a real machine and no vendor reference file is in the repository. A format reaches "supported" only after a vendor reference file / machine confirms it.

(Original policy text follows; the extra tier above was introduced on the project owner's decision.) Only DST is a supported machine export. A format becomes *exposed* (API, UI button, package file) only when its adapter is registered here as
"supported". That requires, per format, ALL of:
  1. a valid reference file written by real vendor software (committed under tests/fixtures/<fmt>/ with its provenance), and
  2. byte-level fixture tests (hand-written expected bytes, not derived from the writer's own tables), and
  3. an independent reader agreeing on the fixtures, and
  4. ideally a stitch-out on a machine that reads the format.
Until then the adapter may exist in the engine as "experimental" but is NOT exposed unless the operator sets ES_EXPERIMENTAL_FORMATS=1
(development only, never in a shop deployment). "planned" formats have no writer at all and raise UnsupportedFormat with the reason.
"""
import os
from dataclasses import dataclass
from typing import Callable, Dict, List


class UnsupportedFormat(ValueError):
    pass


@dataclass(frozen=True)
class FormatInfo:
    id: str
    label: str
    status: str                 # supported | experimental | planned
    ext: str
    note: str
    needs: str = ""             # what is missing before this format may be exposed


FORMATS: Dict[str, FormatInfo] = {
    "dst": FormatInfo("dst", "Tajima DST", "supported", ".dst",
                      "Validated in software (hand-written byte vectors, independent pyembroidery reader in CI, six-stage verifier). NOT yet validated on a physical machine."),
    "exp": FormatInfo("exp", "Melco EXP", "software_verified", ".exp", "Read back by pyembroidery; no machine confirmation. Trims are zero-move jumps (unverified)."),
    "jef": FormatInfo("jef", "Janome JEF", "software_verified", ".jef", "Read back by pyembroidery; colours = nearest of the 78 Janome colours. No machine confirmation."),
    "pes": FormatInfo("pes", "Brother PES", "software_verified", ".pes", "PES version 1 layout with the PEC block (no CEmbOne object blocks); colours = nearest of the 65 PEC colours. Read back by pyembroidery; no machine confirmation."),
    "xxx": FormatInfo("xxx", "Singer XXX", "software_verified", ".xxx", "Read back by pyembroidery; at most 20 colours. No machine confirmation."),
    "u01": FormatInfo("u01", "Barudan U01", "software_verified", ".u01", "Read back by pyembroidery (needle changes). No machine confirmation."),
    "sew": FormatInfo("sew", "Janome / Elna SEW", "software_verified", ".sew", "Read back by pyembroidery; colours = nearest of the SEW palette. No machine confirmation."),
    "vp3": FormatInfo("vp3", "Husqvarna Viking VP3", "planned", ".vp3", "Not implemented yet.", "an encoder + read-back verification (VP3 stores per-colour blocks and a thread chart)"),
    "hus": FormatInfo("hus", "Husqvarna HUS", "planned", ".hus", "Not implemented yet.", "an encoder + the HUS compression + read-back verification"),
}


def experimental_enabled() -> bool:
    return os.environ.get("ES_EXPERIMENTAL_FORMATS", "") == "1"


def is_exposed(fmt: str) -> bool:
    info = FORMATS.get(fmt)
    return bool(info) and (info.status in ("supported", "software_verified") or (info.status == "experimental" and experimental_enabled()))


def exposed_formats() -> List[FormatInfo]:
    return [f for f in FORMATS.values() if is_exposed(f.id)]


def get_writer(fmt: str) -> Callable:
    """Writer function (pattern, trim_jumps=...) -> bytes-like for an EXPOSED format; UnsupportedFormat otherwise."""
    info = FORMATS.get(fmt)
    if info is None:
        raise UnsupportedFormat(f"unknown format {fmt!r}")
    if not is_exposed(fmt):
        raise UnsupportedFormat(f"{info.label} export is not available. DST is the only fully validated machine format." + (f" Needs: {info.needs}." if info.needs else ""))
    if fmt == "dst":
        from .dst import write_dst
        return lambda pattern, trim_jumps=3: write_dst(pattern, trim_jumps=trim_jumps).data
    if fmt == "exp":
        from .exp import write_exp
        return write_exp
    from .encoders import WRITERS
    if fmt in WRITERS:
        return lambda pattern, trim_jumps=3: WRITERS[fmt](pattern, trim_jumps=trim_jumps)
    raise UnsupportedFormat(f"no writer for {fmt!r}")


def describe() -> dict:
    """JSON for GET /api/formats and the UI status strip."""
    return {"export": [{"id": f.id, "label": f.label, "ext": f.ext, "status": f.status, "note": f.note} for f in exposed_formats()],
            "planned": [{"id": f.id, "label": f.label, "needs": f.needs} for f in FORMATS.values() if not is_exposed(f.id)],
            "machine_validation": "not_yet_physically_validated",
            "fabric_presets": "experimental",
            "time_estimate": "estimated_not_verified",
            "validation_tiers": {"supported": "DST: full software pipeline, not machine-tested", "software_verified": "read back by an independent library, not machine-tested"},
            "import": {"supported": ["svg", "png", "jpg", "bmp"], "unsupported": ["pdf"], "pdf_message": PDF_MESSAGE}}


PDF_MESSAGE = "PDF import is not currently supported. Please export your artwork as SVG, PNG or JPG."
