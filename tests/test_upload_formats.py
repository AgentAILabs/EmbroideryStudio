"""Image upload formats: BMP is accepted (converted to PNG, original hashed), unsupported types refused."""
import base64, hashlib, io, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
try:
    from PIL import Image, ImageDraw
    HAVE = True
except ImportError:
    HAVE = False
import app as server


def img(fmt, mode="RGB"):
    im = Image.new(mode, (200, 120), "white" if mode == "RGB" else (255, 255, 255, 0)); ImageDraw.Draw(im).rectangle([20, 20, 120, 90], fill=(200, 0, 0) if mode == "RGB" else (200, 0, 0, 255)); b = io.BytesIO(); im.save(b, fmt); return b.getvalue()
b64 = lambda raw: base64.b64encode(raw).decode()


@unittest.skipUnless(HAVE, "Pillow not installed")
class Upload(unittest.TestCase):
    def test_bmp_png_jpeg_all_import(self):
        for fmt in ("BMP", "PNG", "JPEG"):
            r = server.api_raster({"data": b64(img(fmt)), "width_mm": 50, "colors": 3}); self.assertTrue(r["objects"], fmt)
    def test_bmp_is_hashed_as_uploaded(self):
        raw = img("BMP"); r = server.api_raster({"data": b64(raw), "width_mm": 50, "colors": 3}); self.assertEqual(r["source"]["sha256"], hashlib.sha256(raw).hexdigest())
    def test_other_endpoints_accept_bmp(self):
        raw = b64(img("BMP"))
        self.assertIn("workflow", server.api_image_quality({"data": raw, "width_mm": 50}))
        self.assertTrue(server.api_image_isolate({"data": raw, "threshold": 0.6}).get("ran") in (True, False))
    def test_transparent_png_and_unsupported_types(self):
        self.assertTrue(server.api_raster({"data": b64(img("PNG", "RGBA")), "width_mm": 50, "colors": 3})["objects"])
        for bad in (b"GIF89a....", b"%PDF-1.4", b"RIFF....WEBPVP8 ", b"BM" + b"\x00" * 40):
            with self.assertRaises(ValueError): server.api_raster({"data": b64(bad), "width_mm": 50})


if __name__ == "__main__":
    unittest.main()
