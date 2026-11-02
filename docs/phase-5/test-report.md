# Phase 5 Test Report

## Scope and evidence

This report summarizes the existing automated test suites for the Naval Sports
Court Booking and Availability Management System. The recorded validation run
completed **33 Django tests** and **5 FastAPI evaluator tests** successfully.
These tests use synthetic records; they do not establish that real Naval
facility information has been collected or verified.

The Django tests cover the browser-facing API, booking rules, serial and
parallel availability routing, the HTTP client, and service-failure handling.
The FastAPI tests cover Pydantic validation and pure evaluator behavior,
including execution through a process pool.

## Django functional and integration tests — 33 tests

### Mode A — Facility discovery

The discovery tests verify:

- The public sports list excludes inactive sports.
- Facility browsing defaults to multi-sport OR matching, while `match=all`
  requires every requested active sport.
- Facility profiles include supported and matching sports and active resources.
- Invalid match modes return a client error.
- Inactive facilities are not publicly retrievable.
- Coordinates are only exposed for verified, non-demo facilities.

### Mode B — Booking and availability

The booking and availability tests verify:

- Authenticated booking creation stores a server-calculated price, supports the
  facility default rate when no sport-specific rate is configured, and ignores
  client-supplied prices.
- A booking must start in the future, align to a whole hour, last exactly one
  hour, and remain within a local calendar day.
- Resource/sport eligibility is checked; schedule windows and effective dates
  are enforced; bookings overlapping a facility/resource closure are rejected.
- A confirmed booking or closure removes its affected slot from serial
  availability results, and unscheduled slots are excluded.
- The availability search validates dates and sport filters and returns the
  expected facility, resource, sport, and local-time slot identifiers.

**Capacity coverage note:** Booking validation checks the resource capacity,
falling back to facility capacity when the resource capacity is unknown.
Capacity values are present in booking test fixtures, but the current 33-test
suite does **not** contain a dedicated test proving that an over-capacity
participant count is rejected. Add such a focused test in a later testing
pass; capacity behavior should not be described as independently test-verified
until then.

### Transactional conflict prevention and concurrency

Tests verify that overlapping confirmed intervals on one physical resource are
rejected with HTTP 409, including when the existing booking is for a different
sport on that shared resource. Adjacent half-open one-hour intervals are
allowed. A concurrent duplicate-request test submits two requests for the same
resource and slot and verifies that exactly one booking is created while the
other request conflicts.

The implementation path under test uses PostgreSQL `transaction.atomic()` and
`select_for_update()` on the resource row before rechecking confirmed-booking
overlaps. This test demonstrates the guarded concurrent request behavior in the
configured database test environment; it is not a proof against writers that
bypass the application transaction protocol.

### Authentication, ownership, and error handling

The tests also verify authentication requirements, user-scoped booking lists,
and that a user cannot cancel another user's booking. The Django availability
integration tests verify:

- Explicit `mode=serial` returns the serial evaluator's result.
- `mode=parallel` posts JSON-compatible date-scoped data to the FastAPI client
  and returns the mocked service result with the same slot shape as serial.
- A `requests.Timeout` triggers a warning and a successful, explicitly marked
  serial fallback.
- Invalid mode values are rejected.

Separate Django HTTP-client tests verify JSON serialization, request URL and
timeouts, and explicit errors for an offline service or malformed response.

## FastAPI distributed evaluator tests — 5 tests

The five tests verify:

1. A timezone-naive evaluation timestamp is rejected by the Pydantic request
   schema.
2. The pure facility evaluator excludes closed and booked slots and returns
   the expected available slot.
3. Independent facility payloads can be mapped through
   `ProcessPoolExecutor`; results retain their facility/resource/sport identity.
4. A resource-specific schedule takes precedence over the general
   facility/sport schedule.
5. The FastAPI route is registered and returns typed available-slot and elapsed
   time fields.

The Pydantic models reject unknown fields and require timezone offsets on the
evaluation timestamp and interval boundaries. Django-side tests separately
confirm that the serialized request contains JSON-compatible primitive
values. No ORM model, open database connection, or socket is passed to the
worker processes.

## Test evidence and limitations

- Recorded automated run: **33 Django tests passed; 5 FastAPI tests passed**.
- The test sets exercise unit, API, database integration, HTTP-client, and
  process-pool behavior; the benchmark run separately verifies exact
  serial/parallel slot-set equality.
- The distributed HTTP success case is tested with a mocked Django HTTP
  client. Live service-to-service HTTP behavior was exercised by the benchmark,
  rather than by a Django test running both servers.
- The over-capacity rejection case remains a specific test-coverage gap, as
  noted above.
