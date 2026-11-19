# Enterprise feature roadmap

Prioritised by customer value, dependencies, complexity and quality impact. "Done" means implemented AND tested in this repository (software level). Nothing here is physically validated.

| Priority | Item | State | Notes / dependency |
|---|---|---|---|
| P0 | Physical machine validation of `testpack/v2` | **pending (user)** | `docs/testing/physical-machine-test-plan.md`; blocks every "machine-proven" claim |
| P0 | Validated DST export (decode-compare, structured refusal) | done | `export_pipeline.py` |
| P0 | Geometry validation, boundary / coverage checks, 8-category software score | done | `quality.py` |
| P0 | Production report with three separate validation sections | done | `report.py` |
| P1 | Machine profiles (generic Tajima, Ricoma unvalidated, custom) | done (profiles; none validated) | needs real machine data from the user |
| P1 | Fabric profiles incl. satin / net / thick | done (all experimental) | needs stitch-outs |
| P1 | Travel / trim analysis, entry/exit hints | done | optimiser properties tested |
| P1 | Simulation from the decoded DST, inspector, rulers, step back, object visibility | done | |
| P1 | Grouping, segmentation (region) review | done | pixel-level label painting not built |
| P1 | Logging, rate limit, upload policy, security headers, perf budgets | done (thin slice) | in-process only |
| P2 | Bezier node handles | not started | editor |
| P2 | Thread brand charts | not started | needs licensed data |
| P2 | Telugu / Hindi lettering verification | not started | needs fonts + a stitch-out |
| P2 | PES / JEF / EXP output | not started by policy | only after valid reference files and tests exist |
| P3 | Authentication, per-user ownership, RBAC | roadmap | needs the persistence decision (architecture doc, stage 2-3) |
| P3 | Database, project history, audit store | roadmap | PostgreSQL target |
| P3 | Background jobs with cancel / retry | roadmap | queue target |
| P3 | React / TypeScript UI, ASP.NET Core API | roadmap | staged migration in `docs/architecture/enterprise-architecture.md` |
| P3 | Windows desktop packaging | roadmap | |
| P3 | Cloud storage / accounts | roadmap | |
