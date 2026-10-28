# Technology Stack

## Locked runtime and direct dependencies

The following are the Phase 0.5 reviewed and installed versions recorded in `requirements.in` and the hash-locked `requirements.txt`. Recheck package support and regenerate the lock through the reviewed process when intentionally upgrading.

| Technology | Locked version | Purpose |
|---|---:|---|
| CPython | 3.13.9 | Runtime in the project-local `.venv`. |
| Django | 5.2.18 | LTS web framework, ORM, sessions, admin, and transaction boundary. |
| Django REST Framework | 3.18.3 | Browser-facing REST API. |
| FastAPI | 0.162.0 | Separate read-only availability HTTP service. |
| Psycopg | 3.3.6 | PostgreSQL driver; `psycopg[binary]` installs the Windows binary implementation. |
| Uvicorn | 0.54.0 | ASGI server for the FastAPI process. |
| pytest | 9.2.0 | Test runner. |
| pytest-django | 4.14.0 | Django integration fixtures/settings support for pytest. |
| Requests | 2.34.2 | Django-to-FastAPI synchronous HTTP client for the MVP. |
| pip-tools | 7.6.2 | Reproducibly resolves direct pins and generates the hash lock. |
| PostgreSQL Server | 18.6 | Authoritative persistent database; installed locally and connectivity was verified in Phase 0.5. |
| Browser stack | Bootstrap, HTML/CSS/JavaScript, Leaflet | User interface and verified-coordinate map rendering; front-end asset versions are selected during implementation and must be documented. |

FastAPI's transitive runtime includes Starlette and Pydantic; `uvicorn[standard]` supplies its server extras. Full transitive versions/hashes live in `requirements.txt`, not this summary.

## Dependency-lock policy

- Treat `requirements.in` as reviewed, pinned direct requirements.
- Generate the complete transitive pin/hash file with the pinned pip-tools version and the approved Python/platform.
- Install using hash enforcement: `.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt`.
- Verify with `.\.venv\Scripts\python.exe -m pip check` and import/version checks.
- Upgrade intentionally: review official compatibility information, update direct pins, compile, inspect changes, install in the venv, and run tests.
- Do not hand-edit generated pins in `requirements.txt`; do not install unrecorded application dependencies.

## Configuration and secrets

Application settings should read environment variables through Python's `os.environ`/`os.getenv`; this is the dependency-free source of truth. Example configuration names include:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_HOST`, `DATABASE_PORT`
- `AVAILABILITY_SERVICE_URL`
- Optional service-to-service authentication secret if the FastAPI endpoint is reachable beyond loopback.

Keep actual local values in an ignored `.env` file or set them in the process environment. Commit only `.env.example` with unmistakable placeholder values. Never commit database credentials, secret keys, tokens, or real user data. Do not print secrets in logs or diagnostics.

If local `.env` auto-loading is selected, add and directly pin a deliberate loader dependency such as `django-environ` or `python-dotenv` in a separately reviewed dependency update; do not rely on an incidental transitive dependency for runtime configuration. Alternatively, set environment variables in the launching PowerShell process. `.env.example` is a template, not an automatically loaded configuration.

Local run commands, service URLs, and secret-management instructions belong in the README during the application scaffold phase. Development `DEBUG` and allowed hosts must be explicitly configured and must not be copied as production guidance.

## Service and database configuration

- Django uses the supported `django.db.backends.postgresql` backend and Psycopg 3.
- FastAPI's URL is configurable by environment; loopback is preferred for the same-machine MVP.
- FastAPI receives only serialized candidate data and is not configured with database credentials.
- A LAN test requires deliberate listen-address/firewall/service-auth decisions and must not expose secrets or an unauthenticated evaluator indiscriminately.
- Database credentials are only for Django's authoritative service. Admin tooling such as pgAdmin is optional and is not a deployed system dependency.

## Security and lifecycle notes

Use Django session authentication and CSRF protection for browser booking writes; enforce ownership and administrative permissions server-side. Calculate rates on the server using `Decimal`. Keep the `.venv` local and ignored. No Docker, Redis, Kubernetes, cloud provider, or payment-gateway dependency is part of the approved MVP.
