# Problem Statement

## Project context

This project concerns discovery and booking of sports facilities in Naval, Biliran. A person looking for a place to play needs to find facilities, learn which sports each physical court supports, determine when a selected sport is scheduled, and establish whether a requested time can actually be booked.

The project is intended to address a common information-management problem: facility details, supported sports, weekly schedules, temporary closures, rates, and booking records may be maintained in different places or updated manually. When information is fragmented or communicated informally, users may have difficulty comparing facilities and confirming a playable time. Manual calendar or message-based booking workflows can also make it harder for staff to see conflicting reservations promptly.

These are the problem framing and risks this project will investigate, not claims that a particular Naval facility currently has these practices. No facility survey, booking log, schedule, rate, address, or location has been verified for this project at this stage. Local conditions must be established through authorized data collection and must not be presented as fact before verification.

## The distinction between support, schedule, and availability

Three different questions must not be conflated:

1. **Sport support:** Does the facility or physical resource support the selected sport at all?
2. **Sport schedule:** Is that sport scheduled on the requested date and time under the recurring weekly schedule and its effective-date bounds?
3. **Playable availability:** Is the requested one-hour slot within operating hours, scheduled for the selected sport, not blocked by a date/time closure, and free of a conflicting confirmed booking on the same physical resource?

A facility supporting basketball and volleyball does not mean both sports are scheduled at every hour, and a sport being scheduled does not mean its court is unbooked. The search interface and service responses should make these distinctions visible.

## Shared physical resource and double-booking risk

A multipurpose court can support several sports while remaining one physical bookable resource. A basketball reservation and a volleyball reservation that overlap on that shared court are mutually exclusive even though they are different sports. Treating bookings as sport-specific calendars alone could therefore allow two reservations to occupy the same space at the same time.

The system will model facilities, sports, their normalized associations, and physical bookable resources separately. Final booking validation will use the physical resource and a PostgreSQL transaction as the conflict authority. Availability calculations are advisory until Django rechecks the requested interval during the booking transaction.

## Proposed response

The MVP will provide:

- Facility discovery before date/time selection, including multi-sport filters with `match=any` (OR) by default and optional `match=all`.
- Playable-time search that distinguishes support, sport scheduling, and final candidate availability.
- Fixed, whole-hour one-hour slots in `Asia/Manila`, represented as half-open intervals `[start, end)`.
- Django and PostgreSQL as the authoritative owner of booking writes, rates, and conflict prevention.
- A separate FastAPI HTTP availability evaluator, with deterministic serial and process-pool evaluation paths.
- Protected administrative workflows for managing facilities, resources, sports, schedules, closures, rates, and bookings.

## Data-quality guardrail

The application must never invent or imply verified Naval facility names, addresses, barangays, coordinates, contact details, prices, opening hours, or schedules. Until authorized information is collected and checked, demonstrations must use clearly labeled synthetic records, such as `is_demo_data=True`, with a visible synthetic-data label. Synthetic records must be kept distinct from verified records and must not generate map pins that look like surveyed locations.

Use [court-data-collection-template.csv](court-data-collection-template.csv) to collect candidate information. A record is not verified merely because it has been entered in the template. Verification requires a credible source, an authorized verifier, and a date; coordinate provenance must be recorded independently. Blank or unverified coordinates must not be displayed as real map locations.

## Intended academic outcome

The project will demonstrate a small, testable booking application with normalized multi-sport/resource data, transactional booking safeguards, an HTTP boundary between Django and FastAPI, and honest comparison of serial and process-pool performance. Running two services as separate local processes demonstrates local service separation and inter-process HTTP communication. It does not by itself establish cloud hosting or deployment across multiple physical machines.
