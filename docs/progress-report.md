## Technical Progress Report

## Project Status Overview

- **Phase 3 / batch review:** Owners can review a checkout's private receipt, confirm or reject its pending slots together, and cancel its active slots together. Customers receive one confirmation, rejection, or owner/admin cancellation email after commit.
- **Backend and owner portal:** Phase 2A payment-first support is implemented. Multiple courts, venue photos, and amenities remain available.
- **Latest automated validation (2026-11-22):** 153 Django tests, 12 FastAPI evaluator tests, and 9 JavaScript helper tests passed.

## Payment-first API

- Owners manage active payment methods in the owner dashboard. Discovery and facility API responses expose active methods; unconfigured venues show a warning.
- `POST /api/bookings/` accepts multipart form data. Supply `booking_type`, `payment_method_used` (the active method ID), `payment_receipt`, `policy_accepted=true`, and the existing booking details. Batch requests provide `slots` as a JSON-encoded array, with `sport_id`, `participant_count`, `contact_email`, and `contact_phone`. A batch can include up to 20 slots at one venue. Players may use one court; organizers also supply `organization_name`, `event_name`, and `expected_participants`.
- `POST /api/availability/range` accepts JSON containing `start_date`, `end_date`, `court_ids`, `booking_type`, and optionally `sport`, or both `start_time` and `end_time`. The inclusive range is limited to 14 days and the existing availability date limits apply. The response provides `available_slots`, `skipped_slots`, and the evaluation `modes`.
- `PRIVATE_RECEIPT_ROOT` defaults to `MEDIA_ROOT/private_receipts`, allowing receipts to persist when the media directory is on a persistent volume. Django blocks that directory (including resolved aliases) from its public media route; receipts are served only through the authorized booking endpoint. Any external proxy or file server serving media must independently deny access to this directory. Confirm the production media volume is mounted before deployment.
- If an earlier deployment stored receipts under the former `backend/private_receipts` default, preserve their relative paths when moving those files into the new private root after the guarded media route is deployed. An explicit `PRIVATE_RECEIPT_ROOT` can instead keep the previous location.
- New reservations hold slots in `PENDING_VERIFICATION` until payment is marked received. Existing confirmed bookings retain their previous status and financial treatment.
- New checkouts share a batch identifier while retaining individual reservation references. Review and cancellation apply to the relevant slots in the same customer and venue batch; older bookings without an identifier remain independent. Cancellation is rejected for the whole active batch if any active slot has started. Customer cancellation follows the same batch rule.
- Owner and admin booking actions support JSON and standard form redirects; the dashboards refresh their grouped table and financial summary without a page reload. Mixed-status batches remain visible with their individual audit records.
- Availability is rebuilt from current booking rows for both Django and the FastAPI request; there is no availability-result cache to invalidate.

## Booking notifications

- Set `BREVO_API_KEY`, `BREVO_SENDER_EMAIL` (a verified Brevo sender), and optionally `BREVO_SENDER_NAME` to use Brevo's transactional HTTPS API. Otherwise, set `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` for Django SMTP. Debug mode defaults to the console even with a host configured; explicitly set `EMAIL_BACKEND` to use SMTP locally. Console output is not delivered to customers.
- Notifications target the registered email, falling back to the booking contact email. Delivery runs after the transaction commits; errors do not reverse the review and are shown to the owner. This is not a durable queue and failed notifications require manual follow-up.

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

The latest automated run passed **174 tests**:

- **153 Django tests:** Validate batch checkout and actions, payment-first bookings, receipt review and notifications, payment methods, slot holds, discovery, concurrency, availability, owner management, court-specific rates, photos, amenities, and tenant isolation.
- **12 FastAPI tests:** Validate evaluator behavior, process-pool execution, scheduling, endpoint responses, and Pydantic schemas.
- **9 JavaScript helper tests:** Validate existing slot/date/payment behavior and court-specific rate calculation.
- `manage.py check`, `makemigrations --check --dry-run`, production WhiteNoise `collectstatic`, Node syntax checks, and `git diff --check` passed. Photo validation also passed with the image library unavailable.

The earlier Phase 5 report remains a historical record of its 38-test validation run.

## Next Steps

- Verify the production media volume and its access controls before deploying the customer checkout.
