"""TrueType / OpenType lettering -> embroidery objects.

The text is shaped by FreeType + Raqm (HarfBuzz) when Pillow has them - required for Telugu, Devanagari, Tamil, Arabic ...
(conjuncts, vowel signs, joining) - rendered at high resolution and digitized with the same image pipeline as artwork, so letters
get the same stitch-type rules (satin columns for strokes, fill for wide parts, running stitch for hairlines).
Fonts are supplied by the user (upload) - only fonts they are licensed to embroider with. DejaVu Sans is used when none is given.
"""
import io
from pathlib import Path

from .raster import RasterUnavailable, digitize_image

FALLBACK_FONTS = [Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/TTF/DejaVuSans.ttf")]
MAX_FONT_BYTES, MAX_TEXT = 20_000_000, 120


def shaping_available() -> bool:
    try:
        from PIL import features
        return bool(features.check("raqm"))
    except Exception:  # noqa: BLE001
        return False


def _missing_glyphs(font, text):
    """Characters the font cannot draw. FreeType draws a placeholder box (.notdef, 'tofu') for them, so compare each character's
    bitmap with the font's own placeholder for a code point no font has."""
    def sig(ch):
        m = font.getmask(ch, mode="1"); return (m.size, bytes(m))
    tofu = {sig(ch) for ch in ("\U0010FFFD", "\U000E0FFF")}
    out = []
    for ch in sorted(set(text)):
        if ch.isspace() or ch in out or (0x200B <= ord(ch) <= 0x200D) or 0x0300 <= ord(ch) <= 0x036F:
            continue                                   # spaces, joiners and combining marks are drawn with their base letter
        if sig(ch) in tofu:
            out.append(ch)
    return out[:20]


def render_text(text: str, font_bytes: bytes = None, px: int = 360, language: str = None, direction: str = None, shaping: bool = True):
    """Black text on white as PNG bytes + info. px = font size in pixels."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as e:
        raise RasterUnavailable("TrueType lettering needs the optional Pillow package") from e
    if not text or not text.strip():
        raise ValueError("lettering text is empty")
    if len(text) > MAX_TEXT:
        raise ValueError(f"lettering text is limited to {MAX_TEXT} characters")
    if font_bytes is None:
        path = next((p for p in FALLBACK_FONTS if p.exists()), None)
        if path is None:
            raise ValueError("no font supplied and no fallback font installed - upload a .ttf / .otf file")
        font_bytes, font_name = path.read_bytes(), path.stem
    else:
        if len(font_bytes) > MAX_FONT_BYTES:
            raise ValueError("font file larger than 20 MB")
        font_name = "uploaded font"
    use_raqm = shaping and shaping_available()
    layout = ImageFont.Layout.RAQM if use_raqm else ImageFont.Layout.BASIC
    try:
        font = ImageFont.truetype(io.BytesIO(font_bytes), px, layout_engine=layout)
    except OSError as e:
        raise ValueError(f"not a usable TrueType / OpenType font: {e}") from e
    kw = {}
    if use_raqm:
        if language:
            kw["language"] = language
        if direction:
            kw["direction"] = direction
    missing = _missing_glyphs(font, text)
    if missing:
        raise ValueError("the font has no glyph for: " + " ".join(missing) + " - it would stitch empty boxes. Upload a font that covers "
                         "this script (e.g. Noto Sans Telugu / Noto Sans Devanagari).")
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font, **kw)
    pad = px // 6
    im = Image.new("RGB", (r - l + 2 * pad, b - t + 2 * pad), "white")
    ImageDraw.Draw(im).text((pad - l, pad - t), text, font=font, fill="black", **kw)
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue(), {"font": font_name, "shaping": "raqm (HarfBuzz)" if use_raqm else "basic (no complex-script shaping)",
                            "ink_px": [r - l, b - t], "pad_px": pad}


def lettering_objects(text: str, height_mm: float, color: str = "#000000", font_bytes: bytes = None, language: str = None,
                      direction: str = None, quality: str = "high", shaping: bool = True):
    """Returns (objects, notes, info). height_mm = height of the inked letters (tallest glyph top to lowest bottom)."""
    if not 3.0 <= float(height_mm) <= 200.0:
        raise ValueError("lettering height must be 3-200 mm")
    png, info = render_text(text, font_bytes, language=language, direction=direction, shaping=shaping)
    ink_w, ink_h = info["ink_px"]; pad = info["pad_px"]
    width_mm = float(height_mm) * (ink_w + 2 * pad) / max(ink_h, 1)          # the image includes the padding
    r = digitize_image(png, width_mm, 2, quality)
    objs = [o for o in r["objects"]]
    for i, o in enumerate(objs):
        o["color"] = color; o["id"] = f"lt{i + 1}"; o["name"] = f"Letter shape {i + 1}"
    notes = list(r["notes"])
    if float(height_mm) < 6:
        notes.append("lettering under 6 mm is hard to keep legible in satin; consider a larger size")
    info.update(report=r["report"])
    return objs, notes, info
