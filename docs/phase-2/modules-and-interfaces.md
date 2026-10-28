# Modules and Interfaces

## 1. API conventions

- Browser-facing API base path: `/api/`.
- JSON request/response bodies use UTF-8. Dates use `YYYY-MM-DD`; local wall times use `HH:MM` (24-hour), interpreted in `Asia/Manila`.
- Datetimes in responses use ISO 8601 with an explicit UTC offset. Persisted Django datetimes are timezone-aware.
- All booking endpoints require Django session authentication and CSRF protection for unsafe browser requests. Public discovery/search endpoints are read-only.
- Unknown fields, malformed values, invalid filters, and permission failures must return explicit errors. Responses must not expose internal stack traces, secrets, or database credentials.
- `id` values are opaque integer identifiers for the MVP. Pagination may be added consistently if catalogs grow; response examples below show an unpaginated shape for clarity.

## 2. Django browser-facing endpoints

### `GET /api/sports/`

**Authentication:** Public.

**Query parameters:** Optional `active` (default `true` for public catalog).

**200 response:**

```json
{
  "results": [
    {
      "id": 1,
      "name": "Basketball",
      "slug": "basketball",
      "description": null
    }
  ]
}
```

Only active sports are exposed publicly. Names are catalog labels, not evidence that a specific local facility supports the sport.

### `GET /api/courts/`

**Authentication:** Public.

**Query parameters:**

| Parameter | Meaning |
|---|---|
| `sports` | Optional comma-separated sport slugs, e.g. `basketball,pickleball`. |
| `match` | `any` (default, OR) or `all` (AND). Invalid values return `400`. |

**200 response:**

```json
{
  "results": [
    {
      "id": 12,
      "name": "Facility display name",
      "barangay": null,
      "address": null,
      "facility_type": "sports_facility",
      "is_demo_data": true,
      "is_verified": false,
      "coordinates": null,
      "matching_sports": [
        {"id": 1, "name": "Basketball", "slug": "basketball"}
      ],
      "supported_sports": [
        {"id": 1, "name": "Basketball", "slug": "basketball"}
      ],
      "resources": [
        {"id": 20, "name": "Court A", "resource_type": "multipurpose"}
      ]
    }
  ],
  "match": "any"
}
```

`matching_sports` contains the selected sports supported by that facility; `supported_sports` contains its public active sports. Do not return unverified coordinates as real map points.

### `GET /api/courts/{id}/`

**Authentication:** Public.

**200 response:** One facility profile with identifiers, verified or synthetic provenance, supported sports/resources, safe public contact information where verified, and coordinates only where verified.

```json
{
  "id": 12,
  "name": "Facility display name",
  "facility_type": "sports_facility",
  "address": null,
  "barangay": null,
  "is_demo_data": true,
  "is_verified": false,
  "coordinates": null,
  "supported_sports": [
    {"id": 1, "name": "Basketball", "slug": "basketball"}
  ],
  "resources": [
    {"id": 20, "name": "Court A", "resource_type": "multipurpose", "supported_sports": ["basketball"]}
  ]
}
```

Return `404` for a missing or non-public facility.

### `GET /api/availability/search`

**Authentication:** Public.

**Query parameters:** `sport` (sport slug; required), `date` (`YYYY-MM-DD`; required), `start_time` (`HH:00`; required for a single requested slot), optional `resource_id`, and optional `facility_id`.

The initial contract searches one requested hour. Whole-hour alignment, single-day behavior, and `Asia/Manila` are validated. A later date-wide list of candidates can be added without changing the distinction between support, schedule, and availability.

**200 response:**

```json
{
  "timezone": "Asia/Manila",
  "evaluated_at": "2026-10-29T10:00:00+08:00",
  "advisory": true,
  "results": [
    {
      "facility_id": 12,
      "resource_id": 20,
      "sport": "basketball",
      "start": "2026-10-30T10:00:00+08:00",
      "end": "2026-10-30T11:00:00+08:00",
      "supported": true,
      "scheduled": true,
      "available": true,
      "reason": "available",
      "is_demo_data": true
    }
  ]
}
```

Search results are advisory, not reservations. Expected errors include `400` for invalid date/time/sport input, `404` for an unknown sport/resource, and `503` (or a consistently documented gateway error) when FastAPI is unavailable or returns invalid data. Never claim `available: true` when evaluation failed.

### `POST /api/bookings/`

**Authentication:** Required Django session; CSRF token required for browser session requests.

**Request:**

```json
{
  "resource_id": 20,
  "sport_id": 1,
  "date": "2026-10-30",
  "start_time": "10:00",
  "participant_count": 4
}
```

The caller does not submit an authoritative price. Django computes the end time, rate, and total.

**201 response:**

```json
{
  "id": 501,
  "resource_id": 20,
  "sport_id": 1,
  "start": "2026-10-30T10:00:00+08:00",
  "end": "2026-10-30T11:00:00+08:00",
  "participant_count": 4,
  "status": "CONFIRMED",
  "rate_snapshot": "150.00",
  "total_price": "150.00",
  "currency": "PHP",
  "created_at": "2026-10-29T10:00:00+08:00"
}
```

Decimal amounts are JSON strings to preserve decimal representation. Return `400` for invalid fields, `401` for unauthenticated API clients where applicable, `403` for permission failure, and `409` for a final schedule/closure/resource conflict. The exact authentication response convention follows Django session behavior.

### `GET /api/bookings/my/`

**Authentication:** Required Django session.

**200 response:**

```json
{
  "results": [
    {
      "id": 501,
      "resource_id": 20,
      "sport_id": 1,
      "start": "2026-10-30T10:00:00+08:00",
      "end": "2026-10-30T11:00:00+08:00",
      "participant_count": 4,
      "status": "CONFIRMED",
      "rate_snapshot": "150.00",
      "total_price": "150.00",
      "currency": "PHP",
      "created_at": "2026-10-29T10:00:00+08:00",
      "cancelled_at": null
    }
  ]
}
```

Return only records owned by the authenticated user. Never accept another user ID as a filter that bypasses ownership.

### `POST /api/bookings/{id}/cancel/`

**Authentication:** Required Django session; owner or authorized administrator only. CSRF token required for browser session requests.

**Request:** Empty JSON object `{}`.

**200 response:**

```json
{
  "id": 501,
  "status": "CANCELLED",
  "cancelled_at": "2026-10-29T10:30:00+08:00"
}
```

Cancel only a future `CONFIRMED` booking. Preserve its history and price snapshot. Return `404` when not found/not owned (to avoid disclosure), `409` when it is already cancelled or no longer cancellable, and `403` only where policy permits disclosing the resource's existence.

## 3. FastAPI internal service

### `POST /availability/search`

**Caller:** Django service only. Bind locally for the same-machine setup. If exposed to a LAN, require explicit network controls and service authentication configured outside source control.

**Purpose:** Evaluate a bounded candidate snapshot. It is not a public booking endpoint and has no database-write capability.

**Request schema:**

```json
{
  "schema_version": 1,
  "timezone": "Asia/Manila",
  "evaluated_at": "2026-10-29T10:00:00+08:00",
  "candidates": [
    {
      "candidate_id": "resource-20-2026-10-30T10:00",
      "facility_id": 12,
      "resource_id": 20,
      "sport_id": 1,
      "start": "2026-10-30T10:00:00+08:00",
      "end": "2026-10-30T11:00:00+08:00",
      "facility_open_intervals": [
        {"start": "2026-10-30T08:00:00+08:00", "end": "2026-10-30T18:00:00+08:00"}
      ],
      "sport_supported": true,
      "sport_schedule_intervals": [
        {"start": "2026-10-30T09:00:00+08:00", "end": "2026-10-30T12:00:00+08:00"}
      ],
      "closure_intervals": [],
      "confirmed_booking_intervals": [
        {"start": "2026-10-30T13:00:00+08:00", "end": "2026-10-30T14:00:00+08:00"}
      ]
    }
  ]
}
```

Intervals use explicit offsets and half-open semantics. The service receives only the data needed to evaluate each candidate; omit user identities, credentials, rate data, and unrelated facility fields.

**200 response:**

```json
{
  "schema_version": 1,
  "evaluated_at": "2026-10-29T10:00:00+08:00",
  "results": [
    {
      "candidate_id": "resource-20-2026-10-30T10:00",
      "supported": true,
      "within_operating_hours": true,
      "scheduled": true,
      "blocked_by_closure": false,
      "blocked_by_booking": false,
      "available": true,
      "reason": "available"
    }
  ]
}
```

Allowed reason codes include `available`, `unsupported_sport`, `outside_hours`, `unscheduled`, `closed`, and `booked`. Schema-version mismatch, invalid intervals, or oversized requests produce explicit `4xx` responses; unexpected service failures produce `5xx`. Django validates status, schema version, and candidate IDs before using results. It must not transform an HTTP failure into an available candidate.

## 4. Error response convention

Browser-facing validation errors should use a stable structured response, for example:

```json
{
  "error": {
    "code": "booking_conflict",
    "message": "The selected resource is no longer available for that time."
  }
}
```

Messages are user-safe; logs may contain correlation IDs and technical context but never passwords, secret keys, session cookies, or unnecessary personal data. Exact status/code mapping is finalized with the Phase 3 implementation.
