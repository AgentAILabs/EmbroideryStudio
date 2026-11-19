"""Image fidelity support: the source record (the original is authoritative and never modified), derived working images, and bundles.

Rules (see docs/embroidery/image-to-dst-validation.md):
  * the ORIGINAL bytes are never re-encoded, cropped, recoloured or overwritten; they are hashed on arrival and packaged byte-for-byte;
  * every derived image (enhanced analysis image, label map, vector overlay, stitch preview, difference map) is a separate artefact generated on demand;
  * a derived image is never fed back as 'the original'.
"""
from __future__ import annotations
import hashlib
import io
import json
import zipfile
from typing import Dict, Optional


def source_record(data: bytes, width_mm: Optional[float] = None) -> dict:
    """Facts about the uploaded file. Pure read: `data` is not changed."""
    fmt = "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpeg" if data[:3] == b"\xff\xd8\xff" else "unknown"
    rec = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "format": fmt, "px": None, "mode": None, "dpi_at_width": None, "preserved": True}
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        rec["px"] = [im.width, im.height]; rec["mode"] = im.mode
        if width_mm:
            rec["dpi_at_width"] = round(im.width / (width_mm / 25.4))
    except Exception:  # noqa: BLE001 - Pillow missing or file unreadable: the hash and size are still valid
        pass
    return rec


def make_bundle(original: bytes, derived: Dict[str, bytes], reports: Dict[str, object], name: str = "artwork") -> bytes:
    """ZIP with the untouched original (`original.<ext>`), a SHA-256 manifest, derived images and JSON reports."""
    rec = source_record(original)
    ext = {"png": "png", "jpeg": "jpg"}.get(rec["format"], "bin")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"original/{name}.{ext}", original)                                   # byte-for-byte
        z.writestr("SOURCE.json", json.dumps(rec, indent=1))
        for k, v in derived.items():
            z.writestr(f"derived/{k}", v)
        for k, v in reports.items():
            z.writestr(f"{k}.json", json.dumps(v, indent=1, default=str))
        z.writestr("README.txt", "original/ is the uploaded file, unmodified (SHA-256 in SOURCE.json). Everything in derived/ was generated from it and is not a replacement for it.\n")
    return buf.getvalue()


def verify_original_in_bundle(bundle: bytes, original: bytes) -> bool:
    z = zipfile.ZipFile(io.BytesIO(bundle))
    return any(n.startswith("original/") and z.read(n) == original for n in z.namelist())
