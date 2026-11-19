"""Machine profiles, fabric profiles and the production report - and that none of them overclaims."""
import io, json, sys, unittest, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine")); sys.path.insert(0, str(ROOT / "server"))
from stitchcraft_engine import machines as M, profiles, report as R, export_pipeline as EP
from stitchcraft_engine.design import generate
import app as server, sheet

def lib(n): return json.loads((ROOT / "designs" / "library" / n / f"{n}.esproj").read_text())["doc"]

class MachineProfiles(unittest.TestCase):
    def test_no_profile_is_validated_and_only_dst(self):
        for p in M.catalog():
            self.assertFalse(p["validated"], p["id"]); self.assertEqual(p["format"], "dst")
        self.assertEqual({p["id"] for p in M.catalog()}, {"generic_tajima_dst", "ricoma_unvalidated", "custom"})
    def test_ricoma_preset_does_not_invent_machine_facts(self):
        r = M.resolve({"machine_profile": {"id": "ricoma_unvalidated"}}); self.assertIsNone(r["max_hoop"]); self.assertIsNone(r["needles"]); self.assertIn("NOT VALIDATED", r["validation_statement"])
    def test_user_claim_is_quoted_as_a_statement_never_as_validation(self):
        r = M.resolve({"machine_profile": {"id": "custom", "validated_by": "stitched test pack 2026-01-01"}}); self.assertFalse(r["validated"]); self.assertIn("not verified by this software", r["validation_statement"])
    def test_overrides_are_sanitised(self):
        r = M.resolve({"machine_profile": {"id": "custom", "overrides": {"max_stitch": 99, "needles": 999, "max_hoop": {"w": -1, "h": 5}, "evil": 1, "model": "x" * 500}}})
        self.assertEqual(r["max_stitch"], 12.1); self.assertIsNone(r["needles"]); self.assertIsNone(r["max_hoop"]); self.assertNotIn("evil", r); self.assertEqual(len(r["model"]), 80)
    def test_hoop_limit_blocks_export_and_unknown_hoop_only_warns(self):
        d = lib("kalash"); p, _, _ = generate(d)
        self.assertTrue(any(i["code"] == "MACHINE_HOOP_UNKNOWN" for i in M.check_design(d, p)))
        d2 = dict(d, machine_profile={"id": "custom", "overrides": {"max_hoop": {"w": 20, "h": 20}}})
        self.assertTrue(any(i["code"] == "MACHINE_HOOP" and i["severity"] == "error" for i in M.check_design(d2, p)))
        with self.assertRaises(EP.ExportError) as cm: EP.export_dst(d2)
        self.assertEqual(cm.exception.stage, "machine-profile")
        EP.export_dst(d)
    def test_needle_count_warns(self):
        d = dict(lib("kalash"), machine_profile={"id": "custom", "overrides": {"needles": 1}}); p, _, _ = generate(d)
        self.assertTrue(any(i["code"] == "MACHINE_NEEDLES" for i in M.check_design(d, p)))

class FabricProfiles(unittest.TestCase):
    def test_new_fabrics_exist_and_are_experimental_with_warnings(self):
        cat = {f["id"]: f for f in profiles.fabric_catalog()}
        for k in ("satin_fabric", "net", "thick"):
            self.assertIn(k, cat); self.assertTrue(cat[k]["experimental"]); self.assertFalse(cat[k]["validated"]); self.assertTrue(cat[k]["explanation"])
        self.assertIn("stabiliser", cat["net"]["warning"].lower())
        self.assertTrue(all(f["experimental"] and not f["validated"] for f in cat.values()))
    def test_applying_net_profile_logs_the_warning_and_ui_lists_match(self):
        d, log = profiles.apply_profile(lib("kalash"), "net", "blouse_neck", overwrite=True)
        self.assertEqual(d["fabric"], "net"); self.assertTrue(any(l.startswith("warning:") for l in log))
        js = (ROOT / "web" / "app.js").read_text()
        for k in profiles.FABRICS: self.assertIn(k, js, k)

class Report(unittest.TestCase):
    def test_report_has_all_required_fields_and_three_separate_validation_sections(self):
        r = R.build_report(lib("kalash"))
        for k in ("design", "machine_profile", "hoop_mm", "fabric", "counts", "thread_sequence", "estimated_time", "quality", "warnings", "file", "engine_version", "exported_utc", "validation", "limits"):
            self.assertIn(k, r, k)
        self.assertEqual(set(r["validation"]), {"1_software", "2_independent_reader", "3_physical_machine"})
        self.assertEqual(r["validation"]["3_physical_machine"]["result"], "NOT DONE"); self.assertIn("estimate", r["estimated_time"]["note"].lower())
        self.assertEqual(len(r["file"]["sha256"]), 64); self.assertIn("does not guarantee", r["limits"]); self.assertFalse(r["machine_profile"]["validated"])
        self.assertTrue(all(e["stitches"] > 0 for e in r["thread_sequence"]))
    def test_report_sha_matches_the_released_file(self):
        d = lib("kalash"); res = EP.export_dst(d); self.assertEqual(R.build_report(d, res)["file"]["sha256"], res.sha256)
    def test_html_is_escaped_and_states_physical_not_done(self):
        d = lib("kalash"); d["name"] = "<script>alert(1)</script>"
        h = R.render_html(R.build_report(d)); self.assertNotIn("<script>alert", h); self.assertIn("NOT DONE", h); self.assertIn("Physical machine validation", h)
    def test_refused_export_gives_no_report(self):
        d = dict(lib("kalash"), machine_profile={"id": "custom", "overrides": {"max_hoop": {"w": 5, "h": 5}}})
        res, err = server.api_report(d); self.assertIsNone(res); self.assertEqual(err["stage"], "machine-profile")
    def test_package_contains_the_production_report(self):
        data, err = sheet.package(lib("kalash")); self.assertIsNone(err); z = zipfile.ZipFile(io.BytesIO(data)); names = z.namelist()
        self.assertIn("kalash.production-report.json", names); self.assertIn("kalash.production-report.html", names)
        self.assertEqual(json.loads(z.read("kalash.production-report.json"))["file"]["sha256"], __import__("hashlib").sha256(z.read("kalash.dst")).hexdigest())
    def test_api_endpoints(self):
        self.assertIn("report", server.api_report(lib("kalash"))[0]); self.assertIn("html", server.api_report(dict(lib("kalash"), html=True))[0])
        self.assertIn("issues", server.api_machine_check(lib("kalash")))
if __name__ == "__main__": unittest.main()
