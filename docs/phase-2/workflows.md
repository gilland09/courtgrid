# Operational Workflows

## 1. Mode A — Facility Discovery

1. A visitor opens the facility list before selecting a date or time.
2. The browser requests `GET /api/sports/` to obtain active sports, then requests `GET /api/courts/` with an optional comma-separated `sports` filter and `match` mode.
3. If `match` is omitted, Django treats it as `any`: include a facility supporting at least one requested sport. If `match=all`, include only facilities supporting every requested sport.
4. Django queries PostgreSQL for active facilities and their normalized `FacilitySport`/resource-sport relationships. It returns each facility once and identifies the selected sports that it supports.
5. The browser renders the result list/profile and clearly labels synthetic records. It maps only verified coordinates, with map attribution; missing/unverified coordinates have no real-location pin.

An empty sport filter means unfiltered discovery. Invalid sport identifiers or `match` values produce a client error rather than silently changing the requested filter.

## 2. Mode B — Playable-Time Search

1. The browser submits the selected sport, local date, and requested whole-hour time (and optionally a resource/facility filter) to Django's `GET /api/availability/search`.
2. Django validates the request against `Asia/Manila`, verifies that the sport is active, and queries the relevant facilities, physical resources, operating hours, effective sport schedules, closures, and confirmed booking intervals from PostgreSQL.
3. Django creates a bounded, serializable candidate snapshot and calls FastAPI `POST /availability/search` over the configured HTTP base URL. A local deterministic evaluator may be used if the HTTP service is intentionally disabled for a test or benchmark; production-path configuration must not silently fall back after an HTTP failure.
4. FastAPI evaluates each candidate without database access or writes. It reports separately whether support, schedule, hours, closure, or booking state makes the candidate unavailable.
5. Django validates the service response and returns an advisory result with `evaluated_at` and an explicit indication that booking is subject to final confirmation.
6. A timeout, connection failure, invalid response, or service error is surfaced as a service failure. Django does not return a success-shaped response that claims a candidate is available when it could not be evaluated.

The search response does not reserve a slot. Another user may book it before a visitor submits a booking.

## 3. Booking Creation

1. An authenticated user submits a resource, sport, local date/start time, participant count, and any allowed booking input. Client-supplied rate or total is ignored/rejected; the server calculates price.
2. Django validates ownership-independent input rules: active resource and sport, resource's sport eligibility, integer participant count at least one, capacity if known, exactly one whole-hour interval, `Asia/Manila` interpretation, and no midnight crossing.
3. Django opens `transaction.atomic()` and locks the `BookableResource` row using `select_for_update()`. If multiple resources must be locked in a single operation, acquire locks in ascending primary-key order to reduce deadlocks.
4. After the lock is acquired, Django re-reads relevant current state in the transaction:
   - Facility/resource operating hours contain the entire slot.
   - The selected sport is supported on the resource and an effective weekly schedule covers the slot.
   - The schedule is within its effective date bounds.
   - No facility-wide or resource-specific closure overlaps the slot.
   - No `CONFIRMED` booking on the physical resource overlaps the half-open interval `[start, end)`. The overlap predicate is `existing.start < requested.end AND existing.end > requested.start`.
5. If any final check fails, Django returns a clear validation or `409 Conflict` response and creates no booking.
6. If all checks pass, Django selects the sport-specific rate or approved facility default, calculates the flat hourly price with `Decimal`, and stores the rate and total snapshot in the new `CONFIRMED` booking.
7. Django commits and returns the booking representation. If a transaction/database error occurs, no success is reported.

All booking creation paths, including any administrator-created booking workflow, must take the same resource-row lock and recheck before insert. The lock protects the empty-slot case because the resource row exists even when no booking row yet exists. Direct ORM writes that bypass this protocol are prohibited. The database guard is a correctness mechanism; the advisory search is not.

## 4. Cancellation

1. An authenticated user requests cancellation for a booking ID. Django loads the booking subject to ownership filtering; an administrator may use a protected admin action.
2. In a transaction, lock the resource row first and then the booking row (the same resource-first ordering used by booking creation), confirm the status is `CONFIRMED`, and verify that the request is before the start time in `Asia/Manila`.
3. Change status to `CANCELLED`, set the cancellation/update timestamp, and retain the record and immutable price snapshot.
4. A cancelled booking no longer blocks availability. At/after the start, or when the booking is already cancelled, return a clear outcome without deleting or rewriting history.

## 5. Administrator Schedule/Closure Change

1. An authorized administrator proposes a schedule edit, effective-date change, or facility/resource closure.
2. Django validates the proposed record and determines the affected facility, resource, sport, date range, and time intervals.
3. In a transaction, lock affected resources in ascending ID order and query future `CONFIRMED` bookings whose intervals would no longer satisfy the proposed operating hours, sport schedule, or closure state.
4. Display affected booking identifiers/times and an explicit impact warning before saving. Default policy: block a schedule/closure change that would invalidate confirmed bookings until the administrator resolves or cancels them through the audited cancellation workflow. Do not silently cancel or delete bookings.
5. For a rate change, list affected upcoming confirmed bookings and warn the administrator. Existing rate/price snapshots remain unchanged. The new rate applies only to subsequently created bookings.
6. Apply the edit only after the impact policy is satisfied; record the administrator and timestamps.

The exact UI for impact preview and any explicit override is a Phase 3/4 implementation detail, but a silent invalidation path is not permitted.

## 6. Service failure handling

- Django uses bounded connect/read timeouts for FastAPI calls.
- Expected timeout, connection, non-success status, and schema-validation errors are mapped to documented service errors and logged without credentials or personal booking data.
- FastAPI errors cannot authorize or deny a booking by themselves: final booking creation still follows the PostgreSQL transaction workflow.
- Do not retry non-idempotent booking creation blindly. If idempotency is later required, design it explicitly before implementation.
