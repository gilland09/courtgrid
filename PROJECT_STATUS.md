# Naval Sports Court Booking and Availability Management System

## Current status

- **Phase 0 — Environment and Dependency Feasibility Audit:** Completed and approved on 2026-10-28.
- **Phase 0.5 — Environment Bootstrap:** Completed and verified on 2026-10-29.
  - Git repository initialized locally (`C:\Gilland projects\court_booking`); initial commit `674e1e224fcac64c7cc97a376e92efd68cd48cf5` created with no remote configured.
  - `.gitignore`, `requirements.in`, and hash-locked `requirements.txt` (942 lines) created and verified.
  - `.venv` (Python 3.13.9, pip 25.2) created and verified (`pip check` passed with no broken requirements).
  - Local PostgreSQL 18.6 authentication (`psql.exe`) and Python driver connectivity (`psycopg` 3.3.6) verified via read-only `SELECT version();` checks. `pgAdmin 4` is also accessible locally.
- **Phase 1 — Requirements and planning:** Completed and committed as `28a14dc23e88cd84e2d9088b8563069c1867ce61` (`Complete Phase 1 project planning, requirements, and MVP scope`).
- **Phase 2 — System framework and technical design:** Completed and committed as `099510b1babb979cdfaad43c28750498b0b43a26`.
- **Phase 3 — Core functional application:** Started. Django project/apps, PostgreSQL environment configuration, core models/admin, and initial migrations generated; database migrations have not been applied.
- **Next recommended task:** Manually enter the authorized PostgreSQL password in the ignored root `.env`, then review the Phase 3 models and generated migrations before a separately approved `migrate` operation.
- **Scope boundary preserved:** No project database objects or roles were created, no migrations were applied, and no booking views/API or FastAPI app have been implemented. The Phase 1 CSV contains only explicitly synthetic template examples.

## Phase 1 — Requirements and planning

**Status:** Completed and committed as `28a14dc23e88cd84e2d9088b8563069c1867ce61`. The 10 owner-approved MVP decisions are recorded in `docs/phase-1/requirements.md` and are the locked Phase 1 baseline.

Created:

- `docs/phase-1/problem-statement.md` — Naval-focused problem framing, support/schedule/availability distinction, shared-resource conflict risk, and data-quality guardrails.
- `docs/phase-1/objectives-and-scope.md` — General and measurable objectives, MVP in/out of scope, assumptions, and completion definition.
- `docs/phase-1/parallel-distributed-justification.md` — Stateless candidate evaluation, Django/FastAPI boundary, local versus multi-machine distinction, and honest benchmark caveats.
- `docs/phase-1/roles-and-deliverables.md` — Gilland's sole software engineering role, co-members' manuscript focus, and Phase 0-8 deliverable roadmap to the November 19-20, 2026 defense window.
- `docs/phase-1/requirements.md` — Functional/non-functional requirements, grouped acceptance criteria, ten approved decisions, and Phase 2 design questions.
- `docs/phase-1/court-data-collection-template.csv` — Survey fields plus provenance flags and two explicitly synthetic examples with no fabricated coordinates or real location claims.

The Phase 1 documents are committed. `requirements.in` and `requirements.txt` remain unchanged from Phase 0.5. Django scaffolding and generated migration files were added in Phase 3; no database, role, migration application, or booking feature has been created.

### Approved MVP decisions locked in Phase 1

1. Real facility data must be verified; synthetic demo records must be unmistakably labeled and never mapped as real.
2. A facility is normalized across sports; bookings conflict on the shared physical resource across sports.
3. Mode A uses multi-sport OR matching by default and optional ALL matching; Mode B distinguishes sport support, schedule, and actual availability.
4. Slots are fixed one-hour whole-hour intervals in `Asia/Manila`, half-open, and cannot cross midnight.
5. Server-calculated `Decimal` flat hourly slot rate uses FacilitySport with facility-default fallback and immutable booking snapshots.
6. Participant count is an integer of at least one, checked against known capacity, and does not multiply slot price.
7. Booking statuses are `CONFIRMED` and `CANCELLED`; cancellation preserves history; admin changes affecting confirmed bookings must warn/block.
8. Public browse/search is unauthenticated; booking, own-booking view, and cancellation use Django session authentication; administration is protected server-side.
9. Weekly Monday-Sunday sport schedules may have effective bounds; date/time facility closures override them.
10. Django/PostgreSQL owns booking writes; separate FastAPI HTTP service evaluates availability; serial and Windows-safe process-pool outputs are compared and benchmarked honestly. Gilland owns system engineering and co-members focus on the academic manuscript.

## Phase 2 — System framework and technical design

**Status:** Completed and committed as `099510b1babb979cdfaad43c28750498b0b43a26`. Phase 1 was committed before Phase 2 work began.

Created:

- `docs/phase-2/architecture.md` — Browser, Django/DRF, PostgreSQL, and FastAPI/Uvicorn components, communication/trust boundaries, and local versus multi-machine terminology.
- `docs/phase-2/workflows.md` — Facility discovery, playable-time search, transactionally revalidated booking, cancellation, administrative impact review, and explicit service-failure workflows.
- `docs/phase-2/modules-and-interfaces.md` — Django public/authenticated API contracts and internal FastAPI POST payload/response, validation, and error conventions.
- `docs/phase-2/database-design.md` — Logical ERD, table/field design, supporting operating-hours and resource-sport relations, constraints, and PostgreSQL resource-row locking strategy.
- `docs/phase-2/technology-stack.md` — Locked runtime/dependency versions, reproducible lock procedure, environment-based secret/configuration policy, and service/database boundaries.
- `docs/phase-2/testing-and-benchmark-plan.md` — Unit, API, PostgreSQL concurrency, Windows process-pool test matrix, and honest median/speedup/IPC benchmark methodology.
- `docs/phase-2/instructor-review-checklist.md` — Adviser review decisions, readiness criteria, and academic rationale.

Phase 1 and Phase 2 reflect the 10 approved MVP decisions. Phase 2 documentation remains committed as recorded above; the subsequent Phase 3 scaffolding and dependency update are currently unstaged. The Phase 3 migration files are generated but unapplied, and no database objects or roles were created.

### Phase 2 design decisions and open review items

- Proposed primary booking guard: lock the existing `BookableResource` row with `select_for_update()` inside a PostgreSQL transaction, then re-read schedules, closures, and overlapping confirmed bookings before insertion. All booking writers must follow the same protocol; a PostgreSQL exclusion constraint remains an optional defense-in-depth decision for review.
- Resource-specific sport schedules are designed to take precedence for their scoped resource/effective period over the FacilitySport-wide schedule. Confirm this precedence before implementing schedule evaluation.
- Proposed safe admin policy blocks schedule/closure edits that invalidate confirmed bookings until resolved; rate edits warn and never rewrite stored booking snapshots.
- FastAPI receives only bounded serializable candidate data, without user PII or booking-write capability. Search results are advisory; Django rechecks authoritatively.
- The design contains API/schema examples and a logical ERD only. None are implemented or validated against a running application.

## Phase 3 — Core functional application (Part 1: Django scaffolding and models)

**Status:** Scaffolding, environment configuration, models/admin registration, and initial `makemigrations` completed on 2026-10-29. No database migration was applied.

- Generated `backend/config/`, `backend/facilities/`, and `backend/bookings/` with Django 5.2.18.
- Added root `.env.example` with placeholder configuration and root `.env` with the same keys; `DB_PASSWORD` is blank for the owner to fill locally. `.env` is ignored by Git. The secret key in both files is an explicit placeholder, not a production secret.
- Configured `python-dotenv` to load the root `.env`, PostgreSQL connection settings from `DB_*`, `Asia/Manila`, `USE_TZ=True`, and `rest_framework`, `facilities`, and `bookings`.
- Added the Phase 2 facilities/domain models, supporting `FacilityOperatingHours` and `ResourceSport` relations, provenance/rate-fallback fields, and booking snapshots. `Facility.is_demo_data` defaults to `True`; no facility/demo records were created.
- Registered the facility, schedule, closure, resource, sport, and booking models in Django Admin.
- Added pinned `python-dotenv==1.2.4` as a direct requirement and regenerated/installed the hash-locked dependency file.
- `makemigrations` generated `backend/facilities/migrations/0001_initial.py` and `backend/bookings/migrations/0001_initial.py`. It exited successfully, but warned that PostgreSQL migration history could not be checked because the password is blank (`fe_sendauth: no password supplied`).
- `manage.py check` passed with no issues. `makemigrations --check --dry-run` reported no changes pending; it emitted the same expected connection warning. `pip check` reported no broken requirements.
- **Not run:** `manage.py migrate`; database schema/object changes; `createsuperuser`; booking views/API or business workflows; FastAPI application.
- **Manual action:** Enter the PostgreSQL password locally in `.env` without pasting it into chat. After review and approval, verify login and run the separately approved migration step.

## Phase 0.5 — Environment Bootstrap

**Last checked:** 2026-10-29
**Result:** Environment, dependency lock, PostgreSQL authentication, and Psycopg 3 driver connectivity verified.

### Git and workspace files

- Initialized Git in `C:\Gilland projects\court_booking`; no remote is configured.
- Initial commit `674e1e224fcac64c7cc97a376e92efd68cd48cf5` contains `.gitignore`, `PROJECT_STATUS.md`, `requirements.in`, and `requirements.txt`.
- `.gitignore` excludes `.venv/`, `.env` and other `.env.*` files (while allowing placeholder-only `.env.example`), Python bytecode/caches, test/type/coverage caches, build artifacts, local SQLite databases, `local_data/`, `/data/private/`, logs, common key files, and OS metadata files (`Thumbs.db`, `Desktop.ini`, `.DS_Store`). The overly broad `data/` rule was narrowed so future version-controlled sample/synthetic fixtures are not accidentally ignored.

### Virtual environment

- Created `C:\Gilland projects\court_booking\.venv` using Python 3.13.9.
- Verified `.venv\Scripts\python.exe --version`: Python 3.13.9.
- Verified `.venv\Scripts\python.exe -m pip --version`: pip 25.2.
- Activation in PowerShell uses `(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned)` for the current session only, or direct invocation via `.\.venv\Scripts\python.exe`.

### Dependency resolution, installation, and checks

- Direct dependencies pinned in `requirements.in`:
  - `Django==5.2.18`
  - `djangorestframework==3.18.3`
  - `fastapi==0.162.0`
  - `psycopg[binary]==3.3.6`
  - `pytest==9.2.0`
  - `pytest-django==4.14.0`
  - `requests==2.34.2`
  - `uvicorn[standard]==0.54.0`
  - `pip-tools==7.6.2`
- `requirements.txt` (942 lines) verified as autogenerated by `pip-compile --generate-hashes --output-file=requirements.txt --strip-extras requirements.in` on Python 3.13.
- Installed with `pip install --require-hashes -r requirements.txt`.
- Verified `.\.venv\Scripts\python.exe -m pip check`: `No broken requirements found.`
- Import and version checks for Django, DRF, FastAPI, Psycopg (`binary`), pytest, pytest-django, Requests, and Uvicorn succeeded.

Exact installed versions reported by the venv:

```text
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
asgiref==3.13.0
build==1.6.1
certifi==2026.10.23
charset-normalizer==3.5.2
click==8.5.0
colorama==0.4.6
Django==5.2.18
djangorestframework==3.18.3
fastapi==0.162.0
h11==0.16.0
httptools==0.9.0
idna==3.20
iniconfig==2.3.1
opentelemetry-api==1.45.1
packaging==26.3
pip==25.2
pip-tools==7.6.2
pluggy==1.7.0
psycopg==3.3.6
psycopg-binary==3.3.6
pydantic==2.14.1
pydantic_core==2.50.1
Pygments==2.21.0
pyproject_hooks==1.3.3
pytest==9.2.0
pytest-django==4.14.0
python-dotenv==1.2.4
PyYAML==6.0.3
requests==2.34.2
setuptools==84.2.1
sqlparse==0.6.0
starlette==1.10.0
typing_extensions==4.16.0
typing-inspection==0.4.4
tzdata==2026.6
urllib3==2.8.0
uvicorn==0.54.0
watchfiles==1.3.0
websockets==17.3
wheel==0.48.0