# Enterprise architecture

## 1. Current architecture (what exists and is tested)
```
Browser (vanilla JS, canvas + WebGL)  --JSON-->  server/app.py (Python stdlib ThreadingHTTPServer)
                                                   |-- ops.py: request id, JSON logs, rate limit, security headers, upload policy
                                                   '-- engine/stitchcraft_engine (pure Python, stdlib; Pillow/numpy only for raster import)
                                                         design.py -> builder.py -> dst.py
                                                         export_pipeline.py (generate -> validate -> write -> independent decode -> compare -> report)
                                                         quality.py, travel.py, machines.py, profiles.py, report.py, sequence.py, checklist.py
```
* **Contract:** `design JSON` in, `stitch plan` (`CONTRACT_VERSION 1.0`, mm, Y down) out; the DST layer converts to 0.1 mm units, Y up.
* **Release gate:** no DST leaves the server unless `export_pipeline.export_dst` proved that decoding the file reproduces the stitch plan (see `docs/dst/dst-validation-rules.md`).
* **Validation levels** are never merged: software / independent reader / physical (always "NOT DONE" without human evidence).
* **Operations (thin slice):** `X-Request-Id` on every response, one JSON log line per request (bodies are never logged), unhandled exceptions logged with a traceback and returned as a request id, token-bucket rate limit per client (429 + Retry-After), CSP / nosniff / frame-deny headers, 25 MB body cap, base64 and DST upload caps, 30 s socket timeout, slow-request warnings (> 5 s), audit line per export (design hash, DST SHA-256, result).
* **Tests:** engine 32 + studio 451 (`./tools/run_tests.sh`), 53 browser steps (`tools/e2e_ui.js`), CI with `pyembroidery` as independent reader.

### Known limits of the current slice
No authentication, no per-user ownership, no database, no job queue / cancellation, no horizontal scaling (one process, in-memory rate limiter). A request is not CPU-preemptible: complexity caps (3,000 objects, 400,000 points) and the performance budget tests are the protection. Bind to localhost or sit behind an authenticated proxy (the server warns when bound wider).

## 2. Target architecture (roadmap - NOT started)
| Layer | Target | Why |
|---|---|---|
| UI | React + TypeScript + Tailwind | component model, typed contract with the API |
| API | ASP.NET Core 10, OpenAPI contract, auth (OIDC), RBAC | accounts, audit, enterprise SSO |
| Persistence | PostgreSQL + EF Core (projects, versions, exports, audit log); object storage for artwork | multi-user ownership, history |
| Jobs | background queue (e.g. Hangfire/Rabbit) with cancel / retry / progress | long digitizing and large exports |
| Engine | keep the Python engine behind a versioned JSON contract (CLI/HTTP) first; port hot paths only when measured | the engine is the tested asset; rewriting it risks the DST correctness proven so far |
| Observability | OpenTelemetry traces + the existing JSON log schema | |

### Staged migration (each stage ships and is tested before the next)
1. **Freeze the contract - DONE:** `GET /api/openapi.json` (`server/openapi.py`); `tests/test_openapi.py` fails if a route and the document drift apart or key response shapes change.
2. **API host:** ASP.NET Core in front, calling the Python engine as a service; auth + rate limit move here. Python server keeps running unchanged behind it.
3. **Persistence:** projects/versions/exports in PostgreSQL; the `.esproj` file stays an import/export format.
4. **UI:** React/TS rebuilt screen by screen against the same API (the vanilla-JS UI keeps working until parity is proven by the e2e suite).
5. **Jobs:** move auto-digitize / package / placement sets to the queue with cancel + retry.
Risks: contract drift (mitigated by stage 1), re-implementing DST correctness (avoided: the engine is not rewritten), dual-run complexity (each stage is behind a flag).

## 3. Decisions recorded
Hardening the current stack was chosen over a rewrite (office-laptop rule: nothing installed; 400+ passing tests and CI as the safety net). Shapely / OpenCV / pyembroidery are optional accelerators or independent checkers only.
