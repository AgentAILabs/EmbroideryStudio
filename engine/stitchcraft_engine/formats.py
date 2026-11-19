"""Machine-format registry (the architecture for future format adapters).

Only DST is a supported machine export. A format becomes *exposed* (API, UI button, package file) only when its adapter is registered here as
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
    "exp": FormatInfo("exp", "Melco EXP", "experimental", ".exp",
                      "Writer exists and is read back by pyembroidery in CI, but no vendor reference file or machine has confirmed it.",
                      "a valid EXP reference file from vendor software + format-specific fixtures"),
    "pes": FormatInfo("pes", "Brother PES", "planned", ".pes", "Not implemented.",
                      "valid PES reference files (several versions) + the thread palette table + fixtures; PES also embeds a colour / thread block"),
    "jef": FormatInfo("jef", "Janome JEF", "planned", ".jef", "Not implemented.",
                      "valid JEF reference files + the 78-colour JEF palette + fixtures"),
}


def experimental_enabled() -> bool:
    return os.environ.get("ES_EXPERIMENTAL_FORMATS", "") == "1"


def is_exposed(fmt: str) -> bool:
    info = FORMATS.get(fmt)
    return bool(info) and (info.status == "supported" or (info.status == "experimental" and experimental_enabled()))


def exposed_formats() -> List[FormatInfo]:
    return [f for f in FORMATS.values() if is_exposed(f.id)]


def get_writer(fmt: str) -> Callable:
    """Writer function (pattern, trim_jumps=...) -> bytes-like for an EXPOSED format; UnsupportedFormat otherwise."""
    info = FORMATS.get(fmt)
    if info is None:
        raise UnsupportedFormat(f"unknown format {fmt!r}")
    if not is_exposed(fmt):
        raise UnsupportedFormat(f"{info.label} export is not available. DST is the only supported machine format." + (f" Needs: {info.needs}." if info.needs else ""))
    if fmt == "dst":
        from .dst import write_dst
        return lambda pattern, trim_jumps=3: write_dst(pattern, trim_jumps=trim_jumps).data
    if fmt == "exp":
        from .exp import write_exp
        return write_exp
    raise UnsupportedFormat(f"no writer for {fmt!r}")


def describe() -> dict:
    """JSON for GET /api/formats and the UI status strip."""
    return {"export": [{"id": f.id, "label": f.label, "ext": f.ext, "status": f.status, "note": f.note} for f in exposed_formats()],
            "planned": [{"id": f.id, "label": f.label, "needs": f.needs} for f in FORMATS.values() if not is_exposed(f.id)],
            "machine_validation": "not_yet_physically_validated",
            "fabric_presets": "experimental",
            "time_estimate": "estimated_not_verified",
            "import": {"supported": ["svg", "png", "jpg"], "unsupported": ["pdf"], "pdf_message": PDF_MESSAGE}}


PDF_MESSAGE = "PDF import is not currently supported. Please export your artwork as SVG, PNG or JPG."
