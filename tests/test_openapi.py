"""Contract test: the OpenAPI document and the server's routes must match, and key responses must have the documented shape."""
import json, re, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
import app as server, openapi

SRC = (ROOT / "server" / "app.py").read_text()
def code_routes():
    get = set(); post = set()
    g0, p0 = SRC.index("def _get(self)"), SRC.index("def _post(self)")
    for m in re.finditer(r'path == "(/api/[a-z0-9_/.\-]+)"', SRC[g0:p0]): get.add(m.group(1))
    for m in re.finditer(r'path == "(/api/[a-z0-9_/.\-]+)"', SRC[p0:]): post.add(m.group(1))
    return get | {"/api/library/{id}/{file}"}, post

class Contract(unittest.TestCase):
    def test_every_route_is_documented_and_every_documented_route_exists(self):
        get, post = code_routes(); doc = openapi.spec()["paths"]
        dget = {p for p, v in doc.items() if "get" in v}; dpost = {p for p, v in doc.items() if "post" in v}
        self.assertEqual(sorted(get ^ dget), [], "GET routes differ between app.py and openapi.py"); self.assertEqual(sorted(post ^ dpost), [], "POST routes differ")
    def test_document_is_valid_enough(self):
        s = openapi.spec(); self.assertEqual(s["openapi"][:1], "3"); json.dumps(s)
        for path, ops in s["paths"].items():
            for m, op in ops.items():
                self.assertIn("200", op["responses"]); self.assertTrue(op["summary"])
                if m == "post": self.assertIn("requestBody", op, path)
        for ref in re.findall(r'#/components/schemas/(\w+)', json.dumps(s)): self.assertIn(ref, s["components"]["schemas"])
    def test_generated_and_error_shapes_match_the_schema(self):
        d = json.loads((ROOT / "designs" / "library" / "kalash" / "kalash.esproj").read_text())["doc"]
        r = server.api_generate(dict(d, decoded=True)); props = openapi.SCHEMAS["Generated"]["properties"]
        for k in ("source", "stitches", "objects", "threads", "stats", "notes", "issues"): self.assertIn(k, r); self.assertIn(k, props)
        self.assertIn(r["source"], props["source"]["enum"])
        res, err = server.api_dst(dict(d, machine_profile={"id": "custom", "overrides": {"max_hoop": {"w": 5, "h": 5}}}))
        self.assertIsNone(res)
        for k in ("error", "stage", "code", "issues"): self.assertIn(k, err); self.assertIn(k, openapi.SCHEMAS["Error"]["properties"])
    def test_object_types_in_the_schema_match_the_validator(self):
        from stitchcraft_engine.schema import TYPES
        self.assertEqual(set(openapi.SCHEMAS["Object"]["properties"]["type"]["enum"]), set(TYPES))
if __name__ == "__main__": unittest.main()
