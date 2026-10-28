# Testing and Benchmark Plan

## 1. Objectives

Testing must demonstrate correct domain behavior, safe booking writes, proper service failure handling, provenance safeguards, and equivalence between serial and process-pool candidate evaluation. Benchmarks measure observed behavior; they do not assume that multiprocessing is faster.

The plan uses pytest and pytest-django with PostgreSQL for transaction/concurrency integration tests. No tests or benchmark results are claimed by this design document.

## 2. Testing layers

### Unit tests

Test pure rules without external services:

- Facility-to-sport and resource-to-sport membership.
- `match=any` OR and `match=all` AND filter semantics.
- Weekly weekday schedule/effective-date boundaries.
- Operating hours and schedule containment for an entire one-hour slot.
- Facility/resource closure overlap with half-open intervals.
- Confirmed versus cancelled booking overlap.
- Decimal rate selection/fallback and immutable snapshot behavior.
- Participant count validation and capacity fallback.
- `Asia/Manila` conversion, whole-hour alignment, single-day restriction, and boundary/error handling.
- Stable availability reason codes and deterministic result ordering.

### Django/API integration tests

Use Django's test client or DRF API client with a test database and controlled fixtures:

- Public sports/facility/profile access and correct synthetic provenance.
- OR/ALL filter response shape and one-result-per-facility behavior.
- Public playable-time search inputs and distinction between support, schedule, and availability.
- Session authentication, CSRF behavior for unsafe requests, booking ownership, and admin permissions.
- Rate fields are ignored/rejected from user input; server-calculated snapshots are returned as decimal strings.
- Cancellation changes status and timestamp while retaining the row and snapshot; another user cannot cancel it.
- Admin schedule/closure impact preview blocks or warns as designed; rate changes do not rewrite snapshots.
- Verified coordinates are the only coordinates eligible for real map rendering.

### FastAPI/service integration tests

- Validate `POST /availability/search` schema, supported reason codes, and interval semantics.
- Reject malformed, oversized, inconsistent, or unsupported payload versions without returning available results.
- Verify Django's HTTP client sends only necessary candidate data and validates response IDs/schema.
- Simulate timeout, connection refusal, non-2xx response, malformed JSON, and incomplete response; assert a clear failure result, never availability success.
- Verify FastAPI has no booking-write path or database access requirement.

### PostgreSQL transaction and concurrency tests

These are required against PostgreSQL, not SQLite:

- Two different sports sharing one physical resource cannot receive overlapping confirmed bookings.
- Adjacent intervals are accepted under `[start,end)` semantics.
- Two concurrent requests for an initially empty overlapping slot result in at most one confirmed booking and one clear conflict.
- Concurrent cancellations/booking attempts do not violate the documented lock protocol.
- A schedule/closure change cannot silently invalidate confirmed bookings.
- If an exclusion constraint is selected, test its integrity failure mapping as well as the application lock path.
- Use separate database connections/threads or processes appropriate to Django's test runner; ensure test setup itself does not share a transaction in a way that masks locking behavior.

### Windows process-pool tests

- Exercise a top-level worker under the `spawn` start method used on Windows.
- Verify workers can import the module safely without creating recursive pools.
- Test empty, singleton, mixed, and larger candidate sets.
- Compare normalized serial and parallel result sets and ordering exactly.
- Confirm worker input/output objects are picklable and contain no ORM instances or handles.

## 3. Test matrix

| Area | Test type | Key evidence |
|---|---|---|
| Mode A OR/ALL discovery | Unit + API integration | Expected facility IDs and matching sports; facility not duplicated. |
| Mode B schedule/closures/bookings | Unit + API integration | Reason-code coverage for unsupported, unscheduled, outside hours, closed, booked, and available. |
| Booking/auth/ownership | API integration | Anonymous rejection, owner-only access, admin authorization, valid booking response. |
| Price/capacity/history | Unit + API integration | Decimal totals, fallback precedence, unchanged snapshot, count bounds, retained cancellation. |
| Concurrent booking conflicts | PostgreSQL integration | At most one overlapping confirmed booking for the resource. |
| Admin impact prevention | PostgreSQL/API integration | Affected confirmed bookings identified before schedule/closure mutation. |
| FastAPI failure boundary | Service/client integration | Timeout/error/malformed response is explicit and never “available.” |
| Process-pool equivalence | Windows process integration | Same deterministic output from serial and parallel evaluators. |
| Data provenance | Unit + API/UI checks | Synthetic flags visible; no unverified coordinates presented as real. |

## 4. Benchmark design (planned for Phase 4)

Use generated fixtures that are labeled synthetic and do not encode invented real Naval venues. Keep a fixed seed and serialize the input snapshot so serial and parallel runs evaluate exactly the same candidates.

Candidate-workload dimensions should include multiple facilities, physical resources per facility, supported sports, dates, weekly sport schedules/effective dates, closure intervals, and existing confirmed-reservation intervals. Record candidate count and each dimension. Select numeric small/medium/large sizes in the benchmark implementation plan after a smoke run; the dataset should be large enough to expose scaling but bounded for the student laptop.

For each workload:

1. Verify serial/parallel results are identical before comparing timings.
2. Warm up interpreter/import paths consistently.
3. Run multiple repetitions in a documented order; use the median elapsed wall time and report spread (e.g. minimum/maximum or interquartile range).
4. Record cold end-to-end pool time (including process startup) and, if a persistent pool is part of the actual service design, separately record warm-pool evaluation time.
5. Measure serialization/pickling and result-collection/IPC cost separately where feasible; explain what is included and avoid subtracting costs from the headline user-visible measurement.
6. Record speedup as `serial_median / parallel_median`; values below `1.0` indicate a parallel slowdown. Report raw medians and the ratio.
7. Record Python version, OS, CPU/worker count, lock revision, workload seed/size, repetitions, timing tool, and benchmark command.

Do not claim universal speedup. Windows process spawning and serialization/IPC can make small cases slower. Report negative results and choose any serial/parallel threshold only from measured evidence.

## 5. Release gate

Before a feature is considered complete, its acceptance criteria in [requirements.md](../phase-1/requirements.md) must have a test or documented manual check. Race-safety claims require PostgreSQL evidence. Benchmark claims require retained result artifacts and reproducible commands. No Phase 2 design document itself represents a passing test result.
