# Physical machine-validation evidence

One JSON file per physical test (`ev_<id>.json`), created by the Machine test dialog or imported from an exported record.

* A record is bound to the **SHA-256 of the exact DST** that was stitched. If the design (and so the DST) changes, the old record no longer applies (status STALE).
* Records are sealed with `record_sha256`; an edited record is refused.
* **This repository ships no records.** Nothing is "passed" until someone runs the design on a real machine and records the result.
* Status values: PENDING, INCOMPLETE, STALE, FAILED, PASSED_WITH_NOTES, PASSED. PASSED requires every required field, final inspection = pass and a matching checksum.

Required fields: operator, design_name, design_version, machine_model, fabric, stabiliser, needle, thread, hoop, stitch_count, speed_spm, thread_breaks, skipped_stitches, puckering (0-3), registration_mm, jump_trim_result (ok/problems), final_inspection (pass/pass_with_notes/fail). Optional: notes, photo_sha256[].
