# Phase 2 Instructor/Adviser Review Checklist

## Design summary for review

- [ ] One `Facility` record can support multiple `Sport` records through normalized associations.
- [ ] A `BookableResource` is the physical conflict identity; bookings for different sports still conflict when they overlap on the same shared resource.
- [ ] Mode A facility discovery is independent of date/time and uses OR (`match=any`) by default, with optional AND (`match=all`).
- [ ] Mode B distinguishes sport support, applicable schedule, and actual playable availability after operating hours, closures, and bookings.
- [ ] Slots are fixed one-hour, whole-hour, single-day intervals in `Asia/Manila`, with half-open `[start,end)` semantics.
- [ ] PostgreSQL remains the authoritative source for booking state, transactional conflict prevention, and server-calculated Decimal pricing snapshots.
- [ ] FastAPI `POST /availability/search` evaluates only a bounded read-only candidate snapshot; it never writes bookings or prices.
- [ ] A stale or failed availability response cannot authorize booking; Django rechecks under a PostgreSQL resource-row lock before inserting.
- [ ] The database design includes resource-sport eligibility, facility operating hours, sport schedules with date bounds, closure precedence, and synthetic/verified provenance.
- [ ] A separate FastAPI/Uvicorn process on one laptop is described as local multi-service HTTP communication, not multi-machine deployment.
- [ ] Serial evaluation is the deterministic reference; Windows-safe `ProcessPoolExecutor` results must be equivalent. Benchmarks include startup/IPC costs and report slowdown honestly.
- [ ] Synthetic demo records are explicitly marked, have no fabricated real coordinates, and remain distinct from verified Naval facts.
- [ ] Project scope excludes payments, arbitrary durations, Docker, Redis, Kubernetes, and cloud services.
- [ ] Gilland owns system engineering; co-members focus on the academic manuscript.

## Technical decisions requiring adviser confirmation

- [ ] Is the resource-row `select_for_update()` protocol on every Django booking-write path an acceptable primary concurrency guard for the MVP?
- [ ] Should a PostgreSQL exclusion constraint be added as defense in depth? If so, confirm `btree_gist` availability/privileges and migration risk before implementation.
- [ ] Is the proposed schedule precedence acceptable: a resource-specific schedule overrides the FacilitySport-wide schedule for its covered weekday/effective period?
- [ ] Is the default safe policy acceptable: block a closure/schedule change that would invalidate a confirmed booking until the booking is resolved; warn for rate changes while preserving existing snapshots?
- [ ] Are the proposed API response schemas, error codes, service timeout behavior, and service-to-service protection sufficient?
- [ ] Are Decimal `numeric(10,2)` PHP rates and `PHP` currency suitable for the MVP, subject to verified facility rates?
- [ ] Are PostgreSQL integration tests for race safety and a small/medium/large benchmark sufficient for the academic evidence?
- [ ] Are the proposed Phase 2-to-8 deliverables and target windows compatible with course milestones and the November 19-20, 2026 defense?

## Readiness criteria before implementation

Phase 2 may exit when:

1. The adviser/project owner reviews the architecture, workflows, interfaces, ERD, technology/configuration policy, test/benchmark plan, and this checklist.
2. The primary conflict guard and any extension/privilege requirement are decided.
3. Schedule precedence, closure impact handling, rate-change behavior, authentication setup, and FastAPI failure mapping are understood.
4. No requirement implies invented real-world data or an unverified map pin.
5. The owner approves the Phase 3 implementation boundary and keeps the Phase 4 service work distinct.

## Academic justification

The design gives each responsibility a verifiable boundary: PostgreSQL transactions protect booking truth; FastAPI demonstrates a separate HTTP service; pure candidate evaluation supports a fair serial/parallel comparison; and provenance rules protect the credibility of local facility information. These are measurable engineering choices rather than claims of production-scale distributed deployment or guaranteed speedup.

## Review outcome

Record the review date, reviewer, approved amendments, and unresolved questions here before beginning implementation. This checklist is a template; no instructor approval is implied by its creation.
