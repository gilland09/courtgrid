# Objectives and Scope

## General objective

Design and build a safe, data-quality-conscious sports facility discovery and court-booking MVP for Naval, Biliran, using Django and PostgreSQL as the authoritative booking system and a separate FastAPI service to evaluate availability candidates over HTTP.

## Specific objectives

1. Represent each facility once, associate it with multiple sports through a normalized relation, and record its physical bookable resources without duplicating a facility for each sport.
2. Provide facility discovery before date/time selection, supporting `match=any` (OR) multi-sport filtering by default and optional `match=all`, with the selected supported sports shown for each result.
3. Provide playable-time search by sport, date, and time that distinguishes facility/resource sport support, the selected sport's schedule, and actual slot availability after hours, closures, and bookings are considered.
4. Offer fixed one-hour slots aligned to whole hours in `Asia/Manila`, using half-open time intervals and disallowing overnight bookings.
5. Create and cancel authenticated bookings with server-side validation, a `CONFIRMED`/`CANCELLED` history, participant-count/capacity validation where capacity is known, and transaction-time conflict checking in PostgreSQL.
6. Prevent overlapping confirmed reservations on the same physical resource across all sports and preserve cancellation history rather than deleting cancelled bookings.
7. Calculate a server-authoritative flat hourly slot rate using `Decimal`, store an immutable price/rate snapshot on each booking, and ensure participant count does not multiply the slot rate.
8. Implement a deterministic serial candidate evaluator and a `ProcessPoolExecutor` evaluator using plain picklable inputs and top-level worker functions; verify that both produce equivalent results.
9. Communicate with the standalone FastAPI availability service using an HTTP contract and report service failures/timeouts explicitly rather than treating an error as successful availability.
10. Produce reproducible small, medium, and large benchmark runs that report workload size, serial/parallel results, elapsed time, and environment details without promising a speedup.
11. Keep verified facility data and synthetic demonstration data clearly separated; avoid representing synthetic addresses, prices, schedules, or map coordinates as real.
12. Provide protected Django Admin management and prevent administrative schedule, rate, or closure edits from silently invalidating existing confirmed bookings.

## In-scope MVP

- Public facility list/map presentation and facility profiles, with maps using only verified coordinates and required map attribution.
- Sport catalog and normalized multi-sport facility/resource associations.
- Mode A discovery with OR-by-default and optional AND matching, indicating which selected sports each facility supports.
- Mode B search over fixed one-hour candidate slots, checking facility hours, the selected sport/resource's recurring weekly schedule, effective date bounds, date/time closures, and conflicting confirmed bookings.
- Session-authenticated booking creation, a user's own booking list, and cancellation of that user's future confirmed booking; protected administrator access.
- Facility, resource, sport, schedule, closure, rate, and booking management in Django Admin, including warnings or blocking when an administrative change affects confirmed bookings.
- Decimal-based server-side pricing, facility default fallback, per-FacilitySport rate configuration, and immutable booking price snapshots.
- Resource-level conflict protection across sports, rechecked in the final Django/PostgreSQL booking transaction.
- FastAPI `POST /availability/search` as a separate read-only candidate-evaluation service. Django and PostgreSQL remain authoritative for bookings and price.
- Serial/parallel equivalence tests and reproducible benchmark scripts for representative workload sizes.
- Clearly labeled synthetic demo data only when verified Naval facility data is unavailable.
- Setup, data provenance, API boundary, test, and benchmark documentation.

## Out of scope for the MVP

- Online payment gateways, payment processing, refunds, or external financial transactions.
- Arbitrary minute-by-minute durations, partial-hour starts, and overnight bookings crossing midnight.
- Claiming unverified facilities, addresses, contact details, rates, schedules, or coordinates as real.
- Generic or fabricated map pins, including a pin at the center of Naval presented as a verified facility.
- Docker, Redis, Kubernetes, cloud infrastructure, or additional services beyond Django/PostgreSQL and FastAPI/Uvicorn.
- A claim of multi-machine or cloud deployment based only on two local processes.
- FastAPI independently creating, confirming, cancelling, or pricing bookings, or maintaining a competing booking database.
- Advanced account federation, external identity providers, complex role hierarchies, or payment-linked account workflows.
- Guaranteeing that process-pool execution is faster for every workload.
- Facility data collection without an authorized source and clear provenance.

## Data assumptions and constraints

- One `Facility` can be linked to many `Sport` records through a normalized association (`FacilitySport`); resources can have their own sport eligibility relation where needed.
- A `BookableResource` represents the physical space that is actually reserved. Unless separate independent courts are explicitly recorded, all sports on that resource share one conflict calendar.
- Weekly schedules apply to the relevant facility/sport or resource/sport association and may have effective date bounds. Date/time `FacilityClosure` records override the otherwise applicable schedule.
- Hourly price is a flat per-slot amount, stored as a decimal value. Booking history retains the price snapshot even after a rate is edited.
- `member_count`/`participant_count` is an integer of at least one, checked against known capacity; it does not multiply the hourly slot rate.
- The project uses the `Asia/Manila` application timezone and single-day slot intervals.

## Definition of MVP completion

The MVP is ready for its academic demonstration when an operator can manage the approved catalog and schedules; a visitor can discover facilities and correctly filter supported sports; an authenticated user can find and book a playable slot; overlapping attempts on one physical resource are rejected safely; price snapshots and cancellation history are retained; FastAPI failures are explicit; and serial/parallel outputs are equivalent in tests with benchmark results reported honestly.
