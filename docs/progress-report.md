2## Technical Progress Report

## Project Status Overview

- **Backend, API, distributed integration, automated testing, and CourtGrid-branded frontend UI:** 100% code-complete.
- **Automated tests:** 38 passing in the recorded validation run: 33 Django tests and 5 FastAPI evaluator tests.

## Distributed Architecture

- **Node 1 — Django and PostgreSQL (port 8000):** Provides unified authentication, authoritative application and booking state, and transactional booking creation with resource-row concurrency locking.
- **Node 2 — FastAPI (port 8001):** Receives availability requests as JSON over HTTP REST and performs stateless, CPU-bound parallel candidate evaluation using `ProcessPoolExecutor`. It does not access PostgreSQL or modify booking state.
- The services communicate over HTTP as separate processes. The recorded benchmark uses a local, single-workstation setup; it does not demonstrate deployment across separate physical machines.

## Parallel Performance

The recorded 10-iteration benchmark compared serial Django availability evaluation with the parallel FastAPI HTTP path:

- **Serial median:** 1.548 s
- **Parallel HTTP median:** 0.542 s
- **Measured speedup:** 2.86×
- **Correctness check:** Serial and parallel slot sets were identical.

The parallel measurement includes request serialization and HTTP transport, as well as process-pool evaluation. Results are specific to the tested synthetic workload and environment.

## Test Coverage

The recorded automated run passed **38 tests**:

- **33 Django tests:** Validate discovery OR-matching, booking and overlapping-booking rules, concurrency behavior, availability routing, HTTP payload handling, and timeout fallback behavior.
- **5 FastAPI tests:** Validate evaluator behavior, process-pool execution, scheduling, endpoint responses, and Pydantic schemas.

## Next Steps

- **Remaining task:** Rehearse the presentation for the November 19–20 defense.
