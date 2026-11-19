"""Five separate validation sections. There is deliberately NO combined score: each section answers one question, with its own metrics and its own verdict.

  1 source_quality           Is the SOURCE good enough? (resolution, sharpness, noise, contrast, ... of the uploaded image)
  2 preservation             Did the digitized artwork / photo stitch keep the source's shapes, colours and details? (geometry vs the ORIGINAL)
  3 stitch_path              Is the stitch path sensible for a machine? (stitch lengths, density, jumps, trims, travel) - SOFTWARE rules only
  4 independent_dst          Is the exported FILE internally consistent? (re-decoded from its own bytes: end record, record limits, extents vs hoop, header, preview == export)
  5 physical                 Was it stitched on a real machine, and what happened? (only from a recorded, checksum-matching evidence record)

Section 4 reads the DST bytes with the independent decoder; it never trusts the generator's own numbers. Section 5 can only be PASSED by a human-submitted record.
Every metric carries `how` (formula / rule) - documented in docs/testing/stitch-quality-validation.md.
"""
from __future__ import annotations
import math
from typing import Dict, List, Optional

SECTION_IDS = ("source_quality", "preservation", "stitch_path", "independent_dst", "physical")
TITLES = {"source_quality": "1. Source image quality", "preservation": "2. Artwork / geometry preservation", "stitch_path": "3. Stitch-path software validation",
          "independent_dst": "4. Independent DST validation", "physical": "5. Physical machine validation"}
QUESTIONS = {"source_quality": "Is the uploaded image good enough to digitize?", "preservation": "Did the digitizing keep the source's shapes, colours and details?",
             "stitch_path": "Does the stitch path obey machine-friendly rules? (software rules, not a machine test)", "independent_dst": "Is the exported DST file consistent when read back from its own bytes?",
             "physical": "Has this exact DST been stitched on a real machine, and what was observed?"}
NOT_MEASURED = {"source_quality": ["detail that is not in the image can never be recovered or invented by enhancement"],
                "preservation": ["similarity to the picture is not stitch-out quality"],
                "stitch_path": ["a high software score does not prove physical stitching success", "thread behaviour, fabric and stabiliser are not modelled"],
                "independent_dst": ["a consistent file is not proof that a machine will sew it", "trims are emulated as zero-move jumps (unverified on machines)"],
                "physical": []}


def metric(name, value, unit="", rule="", result=None, how=""):
    return {"name": name, "value": value, "unit": unit, "rule": rule, "result": result, "how": how}


def _sec(sid, verdict, metrics, extra=None):
    s = {"id": sid, "title": TITLES[sid], "question": QUESTIONS[sid], "verdict": verdict, "metrics": metrics, "not_measured": NOT_MEASURED[sid]}
    if extra: s.update(extra)
    return s


# ---------------------------------------------------------------- 1
def source_section(q: Optional[dict]) -> dict:
    if not q or not q.get("ran"):
        return _sec("source_quality", "NOT ASSESSED", [], {"reason": (q or {}).get("reason", "no raster source (vector input) or the optional imaging packages are missing")})
    ms = [metric(k, v.get("value"), v.get("unit", ""), "", v.get("grade"), v.get("how", "")) for k, v in q["metrics"].items()]
    grades = [m["result"] for m in ms if m["result"] in ("good", "fair", "poor")]
    verdict = "POOR" if "poor" in grades else "FAIR" if "fair" in grades else "GOOD"
    return _sec("source_quality", verdict, ms, {"classification": q.get("classification"), "suggested_route": q.get("workflow"), "recommendations": q.get("recommendations", [])})


# ---------------------------------------------------------------- 2
PRESERVATION_PASSES = (1, 2, 3, 5, 8)


def preservation_section(validation: Optional[dict] = None, photo: Optional[dict] = None) -> dict:
    ms: List[dict] = []; results: List[str] = []; extra: Dict[str, object] = {}
    if validation and validation.get("ran"):
        for p in validation["passes"]:
            if p["pass"] in PRESERVATION_PASSES:
                ms.append(metric(p["name"], p["detail"], "", "", p["result"], f"image-to-DST validation pass {p['pass']}")); results.append(p["result"])
        scan = (validation["passes"][1].get("metrics") or {}).get("detail_scan") if len(validation["passes"]) > 1 else None
        if scan and scan.get("ran"):
            extra["detail_scan_counts"] = scan.get("counts")
    if photo:
        for k in ("luminance_corr", "structure_ssim", "histogram_distance", "edge_corr", "luminance_mae") + (("colour_de",) if photo.get("mode") == "multicolour" else ()):
            ms.append(metric("photo: " + k, photo.get(k), "", f"threshold {photo['thresholds'].get(k)}" if k in photo.get("thresholds", {}) else "", ("PASSED" if photo["checks"].get(k) else "WARNING") if k in photo.get("checks", {}) else None,
                             "simulated thread image (drawn from the DST) vs the photograph, blurred 0.7 mm"))
        results.append(photo["verdict"])
    if not ms:
        return _sec("preservation", "NOT ASSESSED", [], {"reason": "no original image comparison was run for this design"})
    verdict = "FAILED" if "FAILED" in results else "WARNING" if ("WARNING" in results or "WARNING" in [m["result"] for m in ms]) else "PASSED"
    return _sec("preservation", verdict, ms, extra)


# ---------------------------------------------------------------- 3
def stitch_path_section(design: dict, res, sim_stitches=None, threads_hex=None) -> dict:
    from .design import generate
    from .quality import quality_report
    from .travel import travel_report
    pattern, notes, st = generate(design)
    q = quality_report(design, pattern, notes); tr = travel_report(design, pattern)
    ms = [metric("software quality score", q["score"], "/100", "", None, "8-category weighted score of geometry, density, stitch length, travel, trims... (software rules only; see quality_report)")]
    for c in q["categories"]:
        ms.append(metric("quality: " + c["name"], c["score"], "/100", "", None, "category score"))
    if sim_stitches is not None:
        from .photo_validation import stitch_metrics
        sm = stitch_metrics(sim_stitches, threads_hex or [])
        ms += [metric("min stitch length", sm["min_stitch_mm"], "mm", ">= 0.5 mm preferred", None if sm["min_stitch_mm"] is None else ("PASSED" if sm["min_stitch_mm"] >= 0.5 else "WARNING"), "shortest distance between consecutive stitch records"),
               metric("max stitch length", sm["max_stitch_mm"], "mm", "<= 12.1 mm (one record)", None if sm["max_stitch_mm"] is None else ("PASSED" if sm["max_stitch_mm"] <= 12.1 else "FAILED"), "longest distance between consecutive stitch records"),
               metric("stitches under 0.5 mm", sm["share_under_0_5mm"], "share", "<= 1 %", "PASSED" if sm["share_under_0_5mm"] <= 0.01 else "WARNING", "count / stitches"),
               metric("stitches over 7 mm", sm["share_over_7mm"], "share", "<= 1 %", "PASSED" if sm["share_over_7mm"] <= 0.01 else "WARNING", "count / stitches"),
               metric("needle penetrations per mm2", sm["max_penetrations_per_mm2"], "1/mm2", "<= 12", "PASSED" if sm["max_penetrations_per_mm2"] <= 12 else "WARNING", "max over 1 mm x 1 mm cells of the decoded stitch positions"),
               metric("jumps", sm["jumps"], "", "", None, "jump records"), metric("trims", sm["trims"], "", "", None, "trim events"), metric("colour changes", sm["colour_changes"], "", "", None, "colour-change records"),
               metric("longest jump", sm["longest_jump_mm"], "mm", "", None, "largest single jump")]
    ms.append(metric("travel verdicts", tr["verdicts"], "", "", None, "travel_report: unnecessary / missing trims, thread changes"))
    results = [m["result"] for m in ms if m["result"]]
    verdict = "FAILED" if "FAILED" in results else "WARNING" if "WARNING" in results else "PASSED"
    return _sec("stitch_path", verdict + " (software only)" if verdict != "PASSED" else "PASSED (software only)", ms)


# ---------------------------------------------------------------- 4
def hoop_fit(extents_mm, hoop: dict) -> dict:
    w, h = extents_mm; m = float(hoop.get("margin", 3) or 0)
    uw, uh = float(hoop["w"]) - 2 * m, float(hoop["h"]) - 2 * m
    return {"width_mm": round(w, 2), "height_mm": round(h, 2), "usable_w_mm": round(uw, 2), "usable_h_mm": round(uh, 2), "fits": w <= uw + 1e-6 and h <= uh + 1e-6}


def dst_checks(data: bytes, hoop: Optional[dict] = None) -> List[dict]:
    """Checks that use ONLY the DST bytes (independent decoder)."""
    from .export_pipeline import independent_decode, ExportError
    out: List[dict] = []
    try:
        recs, pos, hdr = independent_decode(data)
    except ExportError as e:
        return [metric("DST readable", str(e), "", "", "FAILED", "independent decoder")]
    kinds = [k for _, _, k in recs]
    out.append(metric("end record", f"{kinds.count('end')} end record(s), last record is {kinds[-1] if kinds else 'none'}", "", "exactly one, last", "PASSED" if kinds.count("end") == 1 and kinds[-1] == "end" else "FAILED", "record flag byte 0xF3 with zero move"))
    mx = max([max(abs(dx), abs(dy)) for dx, dy, _ in recs] + [0])
    out.append(metric("largest record movement", round(mx / 10, 1), "mm", "<= 12.1 mm", "PASSED" if mx <= 121 else "FAILED", "max(|dx|, |dy|) of any record, 0.1 mm units"))
    xs = [p[0] for p in pos] or [0]; ys = [p[1] for p in pos] or [0]
    ext = ((max(xs) - min(xs)) / 10.0, (max(ys) - min(ys)) / 10.0)
    out.append(metric("decoded extents", f"{ext[0]:.1f} x {ext[1]:.1f} mm", "", "", None, "bounding box of every decoded absolute position"))
    try:
        hx = {k: int(hdr[k]) for k in ("+X", "-X", "+Y", "-Y")}
        ok = hx["+X"] == max(xs) - 0 and hx["-X"] == -min(xs) and hx["+Y"] == max(ys) and hx["-Y"] == -min(ys)
        # DST headers store extents relative to the start (0,0): +X = max x, -X = -(min x)
        out.append(metric("header extents vs decoded", f"header +X{hx['+X']} -X{hx['-X']} +Y{hx['+Y']} -Y{hx['-Y']}; decoded +X{max(xs)} -X{-min(xs)} +Y{max(ys)} -Y{-min(ys)}", "0.1 mm", "equal", "PASSED" if ok else "WARNING", "header fields +X -X +Y -Y compared with the decoded positions"))
    except (KeyError, ValueError):
        out.append(metric("header extents vs decoded", "header fields missing", "", "equal", "WARNING", "header fields +X -X +Y -Y"))
    if hoop and hoop.get("w") and hoop.get("h"):
        f = hoop_fit(ext, hoop)
        out.append(metric("fits the hoop (decoded extents)", f"{f['width_mm']} x {f['height_mm']} mm in {f['usable_w_mm']} x {f['usable_h_mm']} mm usable", "", "extents <= hoop - 2 x margin", "PASSED" if f["fits"] else "FAILED", "decoded bounding box vs hoop size minus margin on each side"))
    stitches = sum(1 for k in kinds if k == "stitch")
    out.append(metric("stitch records", stitches, "", "", None, "records classified as stitch by the independent decoder"))
    return out


def dst_section(design: dict, res, sim: Optional[dict] = None) -> dict:
    from .design import generate
    ms: List[dict] = []
    stages = (res.report or {}).get("stages", [])
    for s in stages:
        if s["stage"] in ("decode-compare", "independent-reader"):
            r = s["result"]; ms.append(metric("stage: " + s["stage"], s.get("detail") or r, "", "", "PASSED" if r == "PASS" else "NOT RUN" if r == "NOT RUN" else "FAILED", "export pipeline stage (record-by-record comparison of the plan with the file / third-party reader)"))
    ms += dst_checks(res.data, design.get("hoop"))
    try:
        from .dst import read_dst
        back = read_dst(res.data); n_back = sum(1 for r in back.records if r[2] == "stitch")
        ms.append(metric("re-import (project reader)", f"{n_back} stitches", "", "equals decoded stitch records", "PASSED" if n_back == next((m["value"] for m in ms if m["name"] == "stitch records"), -1) else "FAILED", "read_dst on the exported bytes"))
    except Exception as e:                       # the reader failing is itself a finding
        ms.append(metric("re-import (project reader)", f"{type(e).__name__}: {e}", "", "", "FAILED", "read_dst on the exported bytes"))
    if sim is not None:
        pattern = sim.get("pattern")
        if pattern is None:
            pattern, _, _ = generate(design)
        from .model import Cmd
        plan = [(s.x, s.y) for s in pattern.stitches if s.cmd == Cmd.STITCH]
        prev = [(x, y) for x, y, c, _t, _o in sim["stitches"] if c == 0]
        same_n = len(plan) == len(prev)
        dev = max((math.hypot(a[0] - b[0], a[1] - b[1]) for a, b in zip(plan, prev)), default=0.0) if same_n else None
        ok = same_n and dev is not None and dev <= 0.08
        ms.append(metric("preview == export", f"{len(prev)} preview stitches vs {len(plan)} planned; max deviation {dev if dev is None else round(dev, 3)} mm", "", "same count, deviation <= 0.08 mm (0.1 mm quantisation)", "PASSED" if ok else "FAILED",
                         "preview stitches reconstructed from the exported DST records vs the intended stitch sequence"))
    results = [m["result"] for m in ms if m["result"]]
    verdict = "FAILED" if "FAILED" in results else "PASSED" if results else "NOT ASSESSED"
    return _sec("independent_dst", verdict, ms, {"dst_sha256": res.sha256, "pyembroidery": next((m["value"] for m in ms if m["name"] == "stage: independent-reader"), "NOT RUN")})


# ---------------------------------------------------------------- 5
def physical_section(sha: Optional[str], design_name: Optional[str] = None) -> dict:
    from . import evidence
    st = evidence.status_for(sha, design_name); rec = st.get("record")
    ms = [metric("status", st["status"], "", "PASSED needs a complete record, inspection = pass and a matching DST checksum", None, "evidence.status_for(sha256)")]
    if rec:
        for k in ("machine_model", "fabric", "stabiliser", "needle", "thread", "hoop", "speed_spm", "thread_breaks", "skipped_stitches", "puckering", "registration_mm", "jump_trim_result", "final_inspection"):
            ms.append(metric(k, rec.get(k), "", "", None, "recorded by the operator"))
    return _sec("physical", st["status"], ms, {"missing": st.get("missing", []), "detail": st.get("detail"), "record_id": rec.get("id") if rec else None, "dst_sha256": sha})


# ---------------------------------------------------------------- all
def build(design: dict, res, *, source_quality: Optional[dict] = None, validation: Optional[dict] = None, photo: Optional[dict] = None, sim: Optional[dict] = None) -> dict:
    sim = sim
    if sim is None:
        from .export_pipeline import decoded_simulation, ExportError
        try: sim = decoded_simulation(design)
        except ExportError: sim = None
    sp = stitch_path_section(design, res, sim["stitches"] if sim else None, sim["threads"] if sim else None)
    secs = [source_section(source_quality), preservation_section(validation, photo), sp, dst_section(design, res, sim), physical_section(res.sha256, design.get("name"))]
    return {"sections": secs, "combined_score": None,
            "note": "The five sections are never combined: a good source says nothing about stitching, a software score says nothing about a machine, and only section 5 can speak about physical success."}
