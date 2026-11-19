"""Guards against 'implemented but not wired to the UI' and against UI / engine default drift."""
import json, re, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
from stitchcraft_engine.design import DEFAULTS, MACHINE_DEFAULTS

JS = (ROOT / "web" / "app.js").read_text()
HTML = (ROOT / "web" / "index.html").read_text()
SERVER = (ROOT / "server" / "app.py").read_text()

# endpoints that are deliberately not called by the editor (internal / infrastructure)
NOT_UI = {"/api/health": "container health check", "/api/export/exp": "EXPERIMENTAL, deliberately not exposed (DST is the only supported format)", "/api/profile/": "", "/api/openapi.json": "API contract for integrators, not used by the UI"}
# engine parameters deliberately without an editor field (always derived / not user-tunable)
NO_FIELD = {("satin", "width"), ("fill", "stitch_len_underlay")}


class EndpointWiring(unittest.TestCase):
    def test_every_endpoint_is_used_by_the_ui(self):
        eps = set(re.findall(r'"(/api/[a-z_/.]+)"', SERVER)) | set(re.findall(r'path == "(/api/[a-z_/.]+)"', SERVER))
        eps = {e for e in eps if not e.endswith("/") and e not in NOT_UI}
        unused = sorted(e for e in eps if e not in JS)
        self.assertEqual(unused, [], "implemented in the server but never called by web/app.js: " + ", ".join(unused))

    def test_every_header_button_has_a_handler(self):
        ids = re.findall(r'<button id="(b[A-Z][A-Za-z]*)"', HTML)
        missing = [i for i in ids if f'$("#{i}")' not in JS]
        self.assertEqual(missing, [], "buttons without a click handler: " + ", ".join(missing))


class ParameterWiring(unittest.TestCase):
    def fields(self):
        return set(re.findall(r'field\("[^"]*", "([a-z_]+)"', JS)) | set(re.findall(r'data-k="([a-z_]+)"', JS))
    def test_every_engine_object_parameter_is_editable(self):
        f = self.fields(); lacking = []
        for t, params in DEFAULTS.items():
            for k in params:
                if k not in f and (t, k) not in NO_FIELD:
                    lacking.append(f"{t}.{k}")
        # parameters set through dedicated controls instead of a generic field
        lacking = [x for x in lacking if x not in ("text.width",)]
        self.assertEqual(lacking, [], "engine parameters the editor cannot set: " + ", ".join(lacking))
    def test_machine_parameters_have_panel_controls(self):
        ids = {"max_stitch": "mMax", "min_stitch": "mMin", "trim_distance": "mTrim", "trim_jumps": "mJ", "lock_len": "mLock",
               "trim_at_color_change": "mTC", "trim_at_end": "mTE", "smart_direction": "mSD", "micro_clean": "mClean", "underlay_entry": "mUE"}
        self.assertEqual(sorted(ids), sorted(MACHINE_DEFAULTS))
        for k, i in ids.items():
            self.assertIn(f'id="{i}"', JS, f"machine.{k}")
    def test_design_level_settings_are_in_the_panel(self):
        for what in ('id="thr"', 'id="pfFab"', 'id="pfCat"', 'id="fab"', 'id="stab"', 'id="hoopSel"'):
            self.assertIn(what, JS)


class DefaultsDoNotDrift(unittest.TestCase):
    def test_ui_numeric_and_choice_defaults_equal_the_engine(self):
        m = re.search(r'const DEF = (\{.*?\});\n', JS, re.S).group(1)
        j = re.sub(r'([{,])([a-zA-Z_]+):', r'\1"\2":', m); j = re.sub(r'(?<![\d"])\.(\d)', r'0.\1', j)
        ui = json.loads(j); drift = []
        for t, eng in DEFAULTS.items():
            for k, v in eng.items():
                if v is None:
                    continue
                if k in ui.get(t, {}) and ui[t][k] != v:
                    drift.append(f"{t}.{k}: engine {v!r} vs UI {ui[t][k]!r}")
        self.assertEqual(drift, [], "UI shows a different default than the engine uses: " + "; ".join(drift))

if __name__ == "__main__":
    unittest.main()
