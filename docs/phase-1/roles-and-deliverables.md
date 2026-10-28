# Roles and Phase Deliverables

## Academic team responsibilities

This is an academic group capstone/course project. **Gilland is the sole system developer and architect** and is responsible for software engineering, system architecture, database design, Django and FastAPI implementation, parallel/distributed service work, tests, and benchmarks.

The other group members are assigned to the accompanying academic manuscript/paper documentation. This plan does not assign them software-development, database, testing, or implementation roles. Manuscript work should accurately describe the implemented and measured system; it must not claim uncompleted features or benchmarks as results.

## Phase map

The following is a proposed deliverables map from Phase 0 through Phase 8. Dates after completed phases are planning targets only and must be reconciled with course instructions. The stated defense window is November 19-20, 2026.

| Phase | Target / status | Concrete software and documentation deliverables |
|---|---|---|
| **0 — Environment and dependency feasibility audit** | Completed 2026-10-28 | Read-only audit of workspace, Python/Node/Git, PostgreSQL and pgAdmin discovery, package compatibility, architecture, slot policy, risks, and sample-data policy. Recorded in `PROJECT_STATUS.md`. |
| **0.5 — Environment bootstrap** | Completed 2026-10-29 | Project-local Python 3.13 `.venv`; reviewed `requirements.in`; hash-pinned `requirements.txt`; `.gitignore`; local Git repository; package/import and `pip check` validation; read-only PostgreSQL 18.6/Psycopg connectivity. Initial commit: `674e1e224fcac64c7cc97a376e92efd68cd48cf5`. |
| **1 — Requirements and planning** | Documentation prepared 2026-10-29; owner review gate pending | Problem statement; objectives and scope; parallel/distributed justification; roles and deliverables; functional/non-functional requirements with acceptance criteria; court data collection template; approved MVP policy summary. Files are in `docs/phase-1/`. |
| **2 — System framework and technical design** | Proposed target: 2026-10-30 to 2026-11-01 | Architecture/context and component diagrams; service/API contract; data model and relationship diagram; booking transaction and conflict-prevention design; schedule/closure precedence; security, data-provenance, and test/benchmark plans. Resolve the specific concurrency guard and any PostgreSQL extension/privilege requirement before booking implementation. |
| **3 — Service skeletons and configuration** | Proposed target: 2026-11-02 to 2026-11-04 | Minimal Django project and separate FastAPI/Uvicorn application skeletons; environment-based configuration; placeholder-only `.env.example`; health/readiness endpoints and documented local run commands. No booking features are implied by skeleton completion. |
| **4 — Data model and administration** | Proposed target: 2026-11-05 to 2026-11-07 | Approved Django models and migrations for facilities, sports, facility/sport links, resources, schedules, closures, rates, and bookings; protected Django Admin; a clearly separated synthetic-only fixture if needed. Database objects/migrations are created only after the design and authorized local database access are ready. |
| **5 — Discovery and transactional booking MVP** | Proposed target: 2026-11-08 to 2026-11-11 | Public facility discovery with OR/ALL filtering; playable-time rules; session authentication; booking creation and cancellation; server-side Decimal pricing snapshot; participant/capacity validation; resource-level transaction recheck and conflict responses; admin warnings/blocking for affected confirmed bookings. |
| **6 — Availability service and parallel evaluation** | Proposed target: 2026-11-12 to 2026-11-14 | FastAPI `POST /availability/search`; Django HTTP client configuration and explicit timeout/error behavior; deterministic serial reference evaluator; Windows-safe `ProcessPoolExecutor` evaluator; serial/parallel equivalence tests. |
| **7 — Integration, testing, and benchmarks** | Proposed target: 2026-11-15 to 2026-11-17 | Integration and failure-path tests; PostgreSQL conflict/race tests; synthetic demo-data provenance checks; repeatable small/medium/large serial/parallel benchmarks; measured results and technical documentation. Fix release-blocking issues and report limitations accurately. |
| **8 — Final review and defense preparation** | Proposed target: 2026-11-18 to 2026-11-20; defense 2026-11-19 to 2026-11-20 | Clean-install/run-through from the lock; final smoke and regression tests; confirm synthetic labels and no unverified map pins; finalize README and setup/API/benchmark notes; prepare a short demo and technical explanation for the defense; report any unfinished scope honestly. |

## Planning risks and checkpoints

- These target windows are a compressed working plan, not confirmed academic deadlines other than the supplied November 19-20 defense window. Adjust if course milestones differ.
- Phase 1 and Phase 2 are review gates: data model, resource conflict policy, schedule precedence, and concurrency design should be settled before migrations and booking writes.
- Keep the demo dataset synthetic and unmistakably labeled until each real record is independently verified.
- Benchmark outcomes must be based on recorded runs; no speedup is guaranteed.
- Maintain a working end-to-end slice early enough to leave time for integration, documentation, and defense rehearsal.
- Keep manuscript claims synchronized with implemented functionality and actual measurements. Gilland owns system deliverables; the other group members own their assigned paper documentation.
