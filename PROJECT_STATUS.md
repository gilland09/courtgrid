# Naval Sports Court Booking and Availability Management System

## Current status

- **Phase 0 — Environment and Dependency Feasibility Audit:** Completed and approved on 2026-10-28.
- **Phase 0.5 — Environment Bootstrap:** Completed and verified on 2026-10-29.
  - Git repository initialized locally (`C:\Gilland projects\court_booking`); initial commit `674e1e224fcac64c7cc97a376e92efd68cd48cf5` created with no remote configured.
  - `.gitignore`, `requirements.in`, and hash-locked `requirements.txt` (942 lines) created and verified.
  - `.venv` (Python 3.13.9, pip 25.2) created and verified (`pip check` passed with no broken requirements).
  - Local PostgreSQL 18.6 authentication (`psql.exe`) and Python driver connectivity (`psycopg` 3.3.6) verified via read-only `SELECT version();` checks. `pgAdmin 4` is also accessible locally.
- **Phase 1 — Requirements and planning:** Six requested documents created on 2026-10-29; pending owner review and commit.
- **Next recommended task:** Review and commit the Phase 1 documentation, then proceed to **Phase 2 — System framework and technical design** in `docs/phase-2/`.
- **Scope boundary preserved:** No project database, project role, Django/FastAPI application code, migration, or application demo/seed record has been created yet. The Phase 1 CSV contains only explicitly synthetic template examples.

## Phase 1 — Requirements and planning

**Status:** Documentation prepared; owner review gate pending. The 10 approved MVP decisions are recorded in `docs/phase-1/requirements.md` and are treated as the locked Phase 1 baseline.

Created:

- `docs/phase-1/problem-statement.md` — Naval-focused problem framing, support/schedule/availability distinction, shared-resource conflict risk, and data-quality guardrails.
- `docs/phase-1/objectives-and-scope.md` — General and measurable objectives, MVP in/out of scope, assumptions, and completion definition.
- `docs/phase-1/parallel-distributed-justification.md` — Stateless candidate evaluation, Django/FastAPI boundary, local versus multi-machine distinction, and honest benchmark caveats.
- `docs/phase-1/roles-and-deliverables.md` — Gilland's sole software engineering role, co-members' manuscript focus, and Phase 0-8 deliverable roadmap to the November 19-20, 2026 defense window.
- `docs/phase-1/requirements.md` — Functional/non-functional requirements, grouped acceptance criteria, ten approved decisions, and Phase 2 design questions.
- `docs/phase-1/court-data-collection-template.csv` — Survey fields plus provenance flags and two explicitly synthetic examples with no fabricated coordinates or real location claims.

No Phase 1 file has been staged or committed. `requirements.in` and `requirements.txt` were left unchanged. No Django/FastAPI application, database, role, migration, or booking feature was created.

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