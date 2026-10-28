# Software Requirements

## Purpose and terminology

This document defines the approved MVP requirements for the Naval Sports Court Booking and Availability Management System. “Must” denotes a required MVP behavior. Facility support, a scheduled sport time, and an unbooked playable slot are distinct concepts.

### Core domain terms

- **Facility:** A venue/location represented once in the catalog.
- **Sport:** A supported activity such as a sport selected by the user.
- **FacilitySport:** A normalized association between a facility and a sport, optionally containing sport-specific rate/schedule information.
- **BookableResource:** The physical court or space reserved by a booking. A single shared multipurpose court has one resource identity even when it supports multiple sports.
- **Playable slot:** A one-hour interval that passes all support, schedule, operating-hours, closure, and booking-conflict checks.
- **Verified record:** Information confirmed from an authorized, recorded source with verifier and date. A row is not verified merely because it has complete fields.
- **Synthetic demo record:** Fictional test/demo information clearly marked as synthetic; it is not evidence about a real Naval facility.

## Functional requirements

### FR-1 — Public facility discovery (Mode A)

- Public visitors must be able to browse facility records before choosing a date or time.
- A facility must be stored once and linked to supported sports through a normalized many-to-many association, not duplicated once per sport.
- Multi-sport filtering must default to `match=any` (OR): include a facility when it supports at least one selected sport.
- An optional `match=all` mode must include a facility only when it supports every selected sport.
- Results must clearly identify which of the selected sports each facility supports.
- Facility profile presentation must distinguish verified information from synthetic demo information. Only verified coordinates may be presented as real map locations; do not use a generic Naval-center pin.

### FR-2 — Playable-time search (Mode B)

- Search must accept the requested sport and date, and identify candidate one-hour times/resources for that request.
- The result must distinguish whether a facility/resource supports the sport, whether that sport is scheduled for the requested interval, and whether the physical resource is actually free to book.
- A candidate is playable only when the entire slot is inside applicable facility operating hours and the selected sport/resource schedule, its weekly schedule is effective on that date, no applicable closure overlaps the slot, and no conflicting `CONFIRMED` booking exists on the same physical resource.
- Weekly schedules must support Monday-Sunday recurrence and optional effective start/end dates. Evaluate schedule times in `Asia/Manila`.
- Date/time facility closures override otherwise applicable schedules. A closure may cover a full day or a defined time interval. A facility-wide closure applies to its resources.
- Cancelled bookings must not block a candidate. Adjacent half-open intervals such as 10:00-11:00 and 11:00-12:00 do not overlap.
- Do not return or display invented real-world schedules, facilities, or coordinates.

### FR-3 — Booking and cancellation

- Creating a booking, listing a user's bookings, and cancelling a booking must require an authenticated user.
- A user may view and cancel only their own bookings; authorized administrators may manage bookings through protected server-side permissions.
- A new booking must reference a `BookableResource`, requested sport, date/time interval, participant count, user, status, and immutable price snapshot.
- A booking interval must be exactly one hour, aligned to a whole hour in `Asia/Manila`, and cannot cross midnight.
- A successful new booking has status `CONFIRMED`. MVP cancellation changes a future confirmed booking to `CANCELLED`; it must preserve the record and cancellation/audit timestamps. Users may cancel their own booking; administrators may perform authorized cancellation.
- A booking cannot be cancelled by its user at or after its start time. Repeated or invalid cancellation requests must return a clear outcome without deleting history.
- Validate participant count as an integer greater than or equal to one. When the relevant capacity is known, reject counts above capacity; do not invent a capacity when it is unknown.
- Final availability must be rechecked within the booking transaction. A previously returned search result is not a reservation.

### FR-4 — Pricing and price snapshots

- Rates must be configured by `FacilitySport`, with the approved facility-level default fallback where no sport-specific rate applies.
- The hourly rate is a flat per-slot amount represented and calculated using decimal arithmetic, never binary floating point.
- The server is authoritative for price selection and calculation; do not accept a client-supplied total as authoritative.
- Each booking must store an immutable rate/price snapshot sufficient to explain the total charged for that booking later.
- Participant count does not multiply the flat one-hour slot price.
- Later rate edits must not change existing booking snapshots or historical totals.

### FR-5 — Physical-resource conflict prevention

- Conflict checks must be made against the physical `BookableResource`, not only the facility or selected sport.
- Unless separate independent physical resources are explicitly modeled, any sport booking blocks the same physical resource for overlapping intervals across all supported sports.
- Intervals use `[start, end)` semantics. Two intervals conflict exactly when they overlap; adjacent slots are permitted.
- The final booking transaction must recheck closures and active bookings and must prevent simultaneous requests from silently confirming an overlapping booking.
- The implementation must use one documented PostgreSQL concurrency guard (for example, an approved database exclusion constraint or a consistently applied resource-level locking and recheck strategy). All booking write paths must obey it.
- Return an explicit conflict outcome when a concurrent or prior booking has occupied the slot; do not report success or silently replace another booking.

### FR-6 — Administrative management and schedule conflict detection

- Protected Django Admin workflows must manage facilities, supported sports/associations, physical resources, recurring schedules/effective dates, closures, rates, and bookings.
- Server-side authorization must prevent public users from modifying administrative records.
- Before applying schedule, rate, or closure changes that affect existing `CONFIRMED` bookings, the system must identify affected bookings and warn/block according to the agreed safe policy.
- Administrative changes must not silently invalidate, delete, reprice, or conceal a confirmed booking. Existing booking price snapshots are immutable.
- Facility and resource changes must preserve identity and relationships required for historical bookings.

### FR-7 — Parallel availability evaluator

- Provide a deterministic serial reference evaluator over plain data inputs.
- Provide a parallel evaluator that uses `concurrent.futures.ProcessPoolExecutor` for independent candidate evaluations.
- Worker functions must be top-level and inputs/results picklable and safe under Windows process spawning.
- Workers must be read-only and must not receive database connections or write booking data.
- Given the same snapshot and candidate set, serial and parallel evaluation must produce equivalent candidate outcomes and deterministic output ordering.
- Benchmark small, medium, and large workloads and include relevant startup/serialization/IPC overhead in the reported user-visible comparison. Report slowdowns as well as speedups.

### FR-8 — FastAPI distributed availability service

- Run availability evaluation as a separate FastAPI/Uvicorn HTTP service with `POST /availability/search`.
- Django must communicate with the service over a configurable HTTP base URL, with local values kept in environment configuration.
- FastAPI receives candidate input or a read-only snapshot and returns candidate evaluation results; it must not independently create, confirm, cancel, or price bookings.
- Django/PostgreSQL remains the single authoritative source for booking writes, conflict resolution, and prices.
- Set bounded HTTP timeouts and handle service errors explicitly. A timeout, malformed response, or service failure must not be converted into a successful “available” result.
- A returned available candidate remains advisory; the final Django booking transaction revalidates it.
- Documentation and presentation must distinguish local two-process HTTP communication from actual multi-machine LAN/cloud deployment.

### FR-9 — Data provenance and demo data

- Real facility information must be entered only from an authorized source and reviewed/verified with source, verifier, and verification date.
- Until real information is verified, use only clearly labeled synthetic demo records, with `is_demo_data=True` and a synthetic data-source marker.
- Synthetic data must not be represented as a real Naval facility and must not include fictitious coordinates displayed as real map pins.
- Keep demo/synthetic and verified records distinguishable in fixtures, records, and user-facing presentation.

## Non-functional requirements

| ID | Requirement |
|---|---|
| **NFR-1 Data integrity** | Use normalized facility/sport/resource relationships and referential integrity. Keep the physical resource as the shared conflict identity. Preserve cancelled booking records and immutable price snapshots. |
| **NFR-2 Concurrency and race safety** | Concurrent attempts to reserve overlapping intervals on one physical resource must not both be confirmed. Enforce the selected guard in PostgreSQL/transactions and test it using concurrent requests against PostgreSQL. |
| **NFR-3 HTTP resilience** | Bound Django-to-FastAPI request timeouts; validate response shape and status; surface timeout and service errors distinctly. Never treat a missing/error response as an available slot. Booking correctness must not depend on a stale evaluator response. |
| **NFR-4 Reproducibility** | Use the reviewed `requirements.in` and fully pinned/hash-locked `requirements.txt`. Document commands, workload sizes/seeds, Python/package versions, worker count, and timing method for benchmarks. |
| **NFR-5 Security and authorization** | Keep secrets and local DB credentials outside source control (`.env` ignored; `.env.example` placeholders only). Use Django session authentication for booking operations, enforce ownership and administrator permissions server-side, validate all inputs, and calculate prices on the server. |
| **NFR-6 Time accuracy** | Use `Asia/Manila` consistently for schedules, closures, booking validation, display, and cancellation cutoff. Use whole-hour one-hour half-open intervals and reject overnight slots. Test date/time boundaries. |
| **NFR-7 Data quality** | Do not publish unverified facility names, addresses, rates, schedules, contacts, or coordinates as real. Make synthetic data unmistakable in all relevant user-facing views and documentation. |
| **NFR-8 Determinism** | Serial and parallel evaluation must use the same rules and return equivalent, consistently ordered results for the same input snapshot. |
| **NFR-9 Maintainability** | Keep the MVP at two application services and one authoritative database. Avoid Docker, Redis, Kubernetes, and unnecessary infrastructure for this project scope. |
| **NFR-10 Accessibility of failure states** | Show understandable validation, conflict, unavailable-service, and authentication outcomes without exposing secrets or internal stack traces to public users. |

## Acceptance criteria by requirement group

| Group | Acceptance criteria |
|---|---|
| **Mode A discovery** | With synthetic test fixtures, selecting two sports in `match=any` returns facilities matching either sport; `match=all` returns only facilities matching both. Each result identifies its matching sports. A facility is not duplicated because it has several sports. Unverified/blank coordinates do not create real map pins. |
| **Mode B playable-time search** | Tests independently cover unsupported sport, supported-but-unscheduled time, closed operating hours, expired/not-yet-effective schedule, full-day and partial closure, conflicting confirmed booking, cancelled booking, and a genuinely playable slot. The result distinguishes support, schedule, and availability. |
| **Booking and cancellation** | Anonymous booking/list/cancel attempts are rejected. An authenticated owner can book a valid slot and view it; cannot view/cancel another user's booking. A future confirmed booking can be cancelled and remains as a `CANCELLED` history record. Cancellation at/after start is rejected. Participant count is at least one and respects known capacity. |
| **Pricing and snapshots** | Tests prove the sport-specific rate takes precedence over facility default, decimal arithmetic is used, participant count does not multiply the rate, and changing a configured rate leaves prior booking snapshots unchanged. Client-provided price cannot override the server result. |
| **Resource conflict safety** | Two sports sharing a resource cannot reserve overlapping intervals; adjacent intervals are accepted. Concurrent attempts for the same overlap result in at most one confirmed booking and a clear conflict for the other. The test exercises PostgreSQL and the selected transaction/database guard. |
| **Administration** | Authorized staff can manage the approved records; unauthorized users cannot. A schedule, rate, or closure edit affecting confirmed bookings identifies those bookings and follows the configured warning/block policy without silently changing or deleting them. |
| **Parallel evaluator** | Serial and process-pool evaluators return equivalent outcomes and deterministic ordering for the same test snapshots, including empty and mixed candidate sets. A Windows-compatible process-spawn test passes. |
| **FastAPI HTTP service** | Django can call `POST /availability/search` with the configured URL and validate a successful response. Tests for timeout, connection failure, invalid response, and service error produce explicit failure outcomes rather than “available.” The service has no booking-write responsibility. |
| **Benchmarks** | Small, medium, and large benchmark runs can be repeated from documented commands; output includes workload and environment details and serial/parallel timings. Results are reported without claiming a universal parallel speedup. |
| **Security, time, provenance** | Secret files are ignored; `.env.example` has placeholders only; booking ownership and admin authorization are enforced server-side; tests use `Asia/Manila` boundaries; synthetic rows are visibly labeled and not mapped as verified places. |

## Summary of the 10 approved MVP decisions

| # | Decision | Requirement interpretation |
|---|---|---|
| 1 | Real versus synthetic court data | Never invent Naval facility facts. Use clearly labeled synthetic records (`is_demo_data=True`, `is_verified=false`, synthetic source marker) until verified with the collection template. Never use a generic Naval-center pin as a real facility. |
| 2 | Multi-sport and physical-resource modeling | One facility links to many sports through normalized relations. Book physical resources. Unless separate courts are modeled, any sport booking blocks that same resource across sports. |
| 3 | Two search modes | Mode A browses before date/time with `match=any` default and optional `match=all`. Mode B separately evaluates sport support, scheduling, and actual bookable availability. |
| 4 | Slot duration/timezone | Fixed one-hour whole-hour slots in `Asia/Manila`, half-open `[start,end)`, single-day only. |
| 5 | Pricing/rate basis | Server-side flat hourly slot rate using `Decimal`, per FacilitySport with facility default fallback; immutable price snapshot per booking. |
| 6 | Participant count | Integer count of at least one, validated against known capacity; does not multiply the flat slot rate. |
| 7 | Status/history/cancellation | MVP statuses `CONFIRMED` and `CANCELLED`; owner/admin may cancel a future confirmed booking; retain history. Admin schedule/rate/closure changes detect affected confirmed bookings and warn/block rather than silently invalidating them. |
| 8 | Authentication/authorization | Django session authentication. Public read/search; authentication for booking, own-booking view, and cancellation; protected server-side admin authorization, initially Django Admin. |
| 9 | Schedule recurrence/precedence | Weekly Monday-Sunday schedules per FacilitySport with optional effective bounds; date/time FacilityClosure blocks override schedule. |
| 10 | Parallel/distributed/team scope | Django/DRF/PostgreSQL owns all writes; standalone FastAPI `POST /availability/search` evaluates candidates; compare deterministic serial and Windows-safe process-pool results and benchmark honestly. Local processes do not equal multi-machine deployment. Gilland owns all system engineering; co-members focus on the paper. |

## Open design items for Phase 2

The approved policies establish the MVP behavior, but the technical design should still specify:

- The exact PostgreSQL concurrency guard (including extension/privilege requirements if an exclusion constraint is selected).
- Detailed API request/response schemas, service timeout values, and error mapping.
- User registration/bootstrap approach and administrator account setup, without committing credentials.
- Exact policy for time-limited closures, cancellation timestamps, and administrative warning versus blocking.
- Which verified information sources and approval evidence are acceptable for each real facility record.
- Benchmark dataset sizes, repetition count, timing aggregation, and target machine metadata.

Resolve these design details before implementing corresponding writes or claiming results.
