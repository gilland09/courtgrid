# CourtGrid — Distributed Real-Time Court Booking & Venue Management System

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Django 5.1](https://img.shields.io/badge/Django-5.1-092E20?style=flat&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-Cache-DC382D?style=flat&logo=redis&logoColor=white)](https://redis.io/)
[![Build & Test Status](https://img.shields.io/badge/Tests-182%20Passed-brightgreen?style=flat)](https://github.com/gilland09/courtgrid)
[![Deployment](https://img.shields.io/badge/Railway-Live%20Production-0B0D0E?style=flat&logo=railway&logoColor=white)](https://web-production-82eee727.up.railway.app)

CourtGrid is a distributed, high-concurrency sports court booking and venue management platform engineered specifically for venue partners and players in Naval, Biliran, Philippines. Built with a two-node hybrid architecture (Django 5.1 Web Portal + FastAPI Compute Node), CourtGrid handles multi-venue scheduling, real-time availability sync, automated payment reconciliation, and automated Brevo email notifications with zero double-booking under high concurrent load.

---

## 🚀 Live Production & Infrastructure Summary

* **Live Public Web Portal (Node 1):** [https://web-production-82eee727.up.railway.app](https://web-production-82eee727.up.railway.app)
* **Architecture Model:** Two-Node Distributed System (Ingress Django Node + Private FastAPI Compute Engine + Shared PostgreSQL + Shared Redis).
* **Automated Test Coverage:** **182 Passed Tests** (159 Django Core, 12 FastAPI Compute, 11 JS Unit Tests).
* **Parallel Availability Benchmark:** $2.86\times$ execution speedup across 60-day matrix evaluations.
* **Seeded Pilot Venues (Naval, Biliran):** *Tonio's Dink District*, *BiPSU Sports Complex*, *Naval Municipal Gym*, *Caneja Turf*, and *Santissimo Rosario*.

---

## 🏗️ System Architecture & Node Topology

CourtGrid decouples user management, transaction processing, and UI rendering from CPU-intensive, 60-day multi-slot matrix availability calculations.

```
                  ┌─────────────────────────────────────────┐
                  │          Browser Ingress / Web          │
                  └────────────────────┬────────────────────┘
                                       │ HTTPS (Port 443)
                                       ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  NODE 1: Django 5.1 Web Application Node (Public HTTPS Ingress)     │
    │  - Gunicorn Web Server (3 Synchronous Workers)                       │
    │  - Role-Based Portals: Player, Venue Owner, System Administrator    │
    │  - Booking Creation, Payment Processing & Financial Settlement      │
    │  - Transactional Emails via Brevo HTTPS API                         │
    │  - Private Receipt Media Engine (PRIVATE_RECEIPT_ROOT Storage)       │
    └──────────────┬───────────────────┬───────────────────┬──────────────┘
                   │                   │                   │
  Internal Private │                   │ ORM Query         │ Cache Sync /
  HTTP Token Auth  │                   │ Engine            │ Invalidation
                   ▼                   ▼                   ▼
    ┌─────────────────────────┐ ┌───────────────┐ ┌──────────────────────┐
    │ NODE 2: FastAPI Compute │ │ PostgreSQL 16 │ │ Redis Cache Node     │
    │ (Private Network Only)  │ │ Persistent DB │ │ In-Memory State &    │
    │ - ProcessPoolExecutor   │ │ Multi-Table   │ │ Regional Key Caching │
    │   (4 Worker Processes)  │ │ ACID Storage  │ │                      │
    │ - 60-Day Availability   │ └───────────────┘ └──────────────────────┘
    │   Matrix Computation    │
    └─────────────────────────┘
```

### Key Architectural Safeguards
1. **Node 1 — Django 5.1 Web Server:** Serves as the primary public entry point. Handles session-based auth, GCash/Maya payment receipt uploads, 5% owner commission calculations (95% net retained earnings), and user interactions.
2. **Node 2 — Standalone FastAPI Compute Engine:** Isolated from public HTTP traffic on Railway's internal network. Protected via `COMPUTE_SERVICE_TOKEN` authorization headers. Offloads multi-court 60-day availability matrix grid generation to a 4-worker `ProcessPoolExecutor`.
3. **Database & Cache:** Shared PostgreSQL storage enforced with transaction atomic blocks (`select_for_update()`) to prevent race conditions during checkout. Shared Redis node handles zero-delay cache invalidation via `transaction.on_commit()`.
4. **Lightweight Polling Engine:** Frontend synchronization uses 3–4 second `live_version` HTTP 200 polling (`live_sync.js`) to update dashboards dynamically without the overhead of persistent WebSockets.

---

## 📂 Repository Structure

```text
courtgrid/
├── .env.example              # Template environment variables (safe placeholders only)
├── .gitignore                # Excludes secrets, receipt uploads, local DBs, and virtual envs
├── Procfile                  # Railway production startup command (Gunicorn 3 workers)
├── railway.json              # Railway deployment specifications
├── requirements.txt          # Hash-locked Python dependencies
├── manage.py                 # Django management CLI
├── README.md                 # System documentation & setup guide
│
├── backend/                  # Django 5.1 Core Web Node Application
│   ├── court_booking/        # Root project configuration, WSGI/ASGI, storage handlers
│   ├── facilities/           # Venue, court, rate rule, and QR asset models & views
│   ├── bookings/             # Booking engine, batch operations, live sync, Brevo email services
│   ├── templates/            # Responsive HTML5/Bootstrap5 templates (Player, Owner, Admin)
│   └── static/               # Client-side JavaScript (live_sync.js, booking_actions.js, toasts.js)
│
├── compute/                  # FastAPI Compute Node (Node 2)
│   ├── main.py               # FastAPI entry point & HTTP token verification
│   └── availability.py       # Multi-process 60-day matrix engine (ProcessPoolExecutor)
│
└── tests/                    # Automated Test Suites
    ├── test_django/          # 159 Core Django models, views, booking concurrency & security tests
    ├── test_compute/         # 12 FastAPI compute worker & token authentication tests
    └── test_js/              # 11 Client-side polling & UI unit checks (node --check)
```

---

## 🛠️ Local Environment Setup

### 1. Prerequisites
* **Python:** 3.12 or higher
* **Node.js:** 18+ (for running JS syntax unit tests)
* **PostgreSQL & Redis:** Installed locally OR accessible via Docker/Cloud.

### 2. Clone & Environment Configuration
```powershell
git clone https://github.com/gilland09/courtgrid.git
cd courtgrid

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # On Windows PowerShell
# source .venv/bin/activate  # On Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env` in the root directory:
```powershell
Copy-Item .env.example .env
```
Ensure your `.env` contains appropriate local values (e.g., local PostgreSQL credentials, secret keys, and dummy tokens). **Never commit real `.env` secret values to Git.**

### 4. Database Setup & Migrations
```powershell
python manage.py migrate
python manage.py seed_naval_venues  # Populates the 5 Naval pilot venue partners
```

### 5. Running the Application Locally

**Start Node 1 (Django Web Server):**
```powershell
python manage.py runserver 8000
```

**Start Node 2 (FastAPI Availability Compute Engine):**
```powershell
uvicorn compute.main:app --host 127.0.0.1 --port 8001 --reload
```

Access the application at `http://localhost:8000`.

---

## 🧪 Automated Test Suite (182 Passed Tests)

The repository includes a comprehensive 3-tier automated test suite covering web logic, API security, parallel compute logic, and client-side modules.

To execute all tests locally, run:

```powershell
# Tier 1: Django Core, Concurrency, and Security Tests (159 Tests)
python manage.py test tests.test_django --verbosity=2

# Tier 2: FastAPI Compute Node Tests (12 Tests)
pytest tests/test_compute/ -v

# Tier 3: JavaScript Client-side Unit Tests (11 Checks)
node --check backend/static/js/live_sync.js
node --check backend/static/js/booking_actions.js
node --check backend/static/js/toasts.js
```

---

## 📊 Parallel Compute Benchmark Execution

CourtGrid includes a benchmark script to measure execution speedups achieved by offloading 60-day availability calculations from Django to FastAPI's 4-worker `ProcessPoolExecutor`.

To run the 60-day availability benchmark:
```powershell
python manage.py run_availability_benchmark --days 60 --runs 10
```

* **Sequential Execution Mean:** $\approx 412 \text{ ms}$
* **Parallel Compute Node Mean:** $\approx 144 \text{ ms}$
* **Achieved Speedup:** $\mathbf{2.86\times}$

---

## 🔒 Security & Data Privacy Engineering

1. **Private Proof-of-Payment Receipt Isolation (`PRIVATE_RECEIPT_ROOT`):**
   User-uploaded payment receipt images are stored completely outside the public `static/` or `media/` directories. Receipts are routed through Django's custom `PrivateFileSystemStorage` engine and served strictly to authorized venue owners and admins via authenticated, tokenized HTTP streams.
2. **Stateless Inter-Service Authentication:**
   Requests between Django and FastAPI require an internal `X-Compute-Token` header matching `COMPUTE_SERVICE_TOKEN`. External HTTP attempts directly against Node 2 endpoints are rejected with HTTP `401 Unauthorized`.
3. **Environment Secret Protection:**
   Production secrets (`DATABASE_URL`, `REDIS_URL`, `BREVO_API_KEY`, `DJANGO_SECRET_KEY`) are managed entirely through Railway's encrypted environment dashboard. Source control contains zero hardcoded API keys or private database URLs.

---

## 🚢 Deployment Architecture (Railway)

CourtGrid is configured for instant single-repo deployment on Railway:

* **Node 1 Entrypoint (`Procfile`):**
  ```text
  web: gunicorn backend.court_booking.wsgi:application --bind 0.0.0.0:$PORT --workers 3
  ```
* **Persistent Volumes:** A persistent Railway volume is mounted to Node 1 at `/app/private_receipts` to preserve sensitive uploaded customer payment receipts across container redeployments.

---

## 📝 License & Project Information

Developed as an academic capstone software engineering project for sports venue management and booking coordination in Biliran, Philippines.

* **Lead Developer:** Gilland Sabile
* **Repository:** [github.com/gilland09/courtgrid](https://github.com/gilland09/courtgrid)
* **Production Deployment:** [web-production-82eee727.up.railway.app](https://web-production-82eee727.up.railway.app)