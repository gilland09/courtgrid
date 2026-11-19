from datetime import date, datetime
from math import isfinite
from typing import Iterable

import requests
from django.conf import settings
from django.utils import timezone

from .models import Facility, FacilityClosure, FacilityOperatingHours, SportSchedule


class AvailabilityServiceError(RuntimeError):
    """Raised when the separate availability service cannot return a valid result."""


def _serialize_date(value):
    return value.isoformat() if value is not None else None


def _serialize_facility(facility: Facility) -> dict:
    facility_sports = list(
        facility.facility_sports.filter(
            is_active=True,
            sport__is_active=True,
        ).values_list('id', flat=True)
    )
    operating_hours = [
        {
            'day_of_week': hours.day_of_week,
            'start_time': hours.start_time.isoformat(),
            'end_time': hours.end_time.isoformat(),
            'effective_from': _serialize_date(hours.effective_from),
            'effective_until': _serialize_date(hours.effective_until),
        }
        for hours in FacilityOperatingHours.objects.filter(facility=facility)
    ]

    resources = []
    for resource in facility.resources.filter(is_active=True):
        resource_facility_sport_ids = list(
            resource.resource_sports.filter(
                facility_sport_id__in=facility_sports,
                facility_sport__is_active=True,
                facility_sport__sport__is_active=True,
            ).values_list('facility_sport_id', flat=True)
        )
        resources.append({
            'resource_id': resource.pk,
            'facility_sport_ids': resource_facility_sport_ids,
        })

    return {
        'facility_id': facility.pk,
        'resources': resources,
        'operating_hours': operating_hours,
    }


def _serialize_schedule(schedule: SportSchedule) -> dict:
    return {
        'facility_id': schedule.facility_sport.facility_id,
        'facility_sport_id': schedule.facility_sport_id,
        'sport_id': schedule.facility_sport.sport_id,
        'resource_id': schedule.resource_id,
        'day_of_week': schedule.day_of_week,
        'start_time': schedule.start_time.isoformat(),
        'end_time': schedule.end_time.isoformat(),
        'effective_from': _serialize_date(schedule.effective_from),
        'effective_until': _serialize_date(schedule.effective_until),
    }


def _serialize_closure(closure: FacilityClosure) -> dict:
    return {
        'facility_id': closure.facility_id,
        'resource_id': closure.resource_id,
        'start_datetime': closure.start_datetime.isoformat(),
        'end_datetime': closure.end_datetime.isoformat(),
        'reason': closure.reason,
    }


def _serialize_booking(booking) -> dict:
    return {
        'resource_id': booking.resource_id,
        'start_datetime': booking.start_datetime.isoformat(),
        'end_datetime': booking.end_datetime.isoformat(),
    }


def serialize_availability_request(
    target_date: date,
    facilities: Iterable[Facility],
    closures: Iterable[FacilityClosure],
    schedules: Iterable[SportSchedule],
    existing_bookings: Iterable,
) -> dict:
    """Convert Django query results into JSON-safe primitives before HTTP/process use."""
    return {
        'target_date': target_date.isoformat(),
        'evaluated_at': timezone.now().isoformat(),
        'facilities': [
            _serialize_facility(facility)
            for facility in facilities
            if facility.is_active
        ],
        'closures': [_serialize_closure(closure) for closure in closures],
        'schedules': [_serialize_schedule(schedule) for schedule in schedules],
        'existing_bookings': [
            _serialize_booking(booking)
            for booking in existing_bookings
            if booking.status == 'CONFIRMED'
        ],
    }


def fetch_parallel_availability(
    target_date: date,
    facilities: Iterable[Facility],
    closures: Iterable[FacilityClosure],
    schedules: Iterable[SportSchedule],
    existing_bookings: Iterable,
) -> dict:
    payload = serialize_availability_request(
        target_date=target_date,
        facilities=facilities,
        closures=closures,
        schedules=schedules,
        existing_bookings=existing_bookings,
    )
    base_url = getattr(settings, 'FASTAPI_URL', 'http://127.0.0.1:8001').rstrip('/')
    service_token = getattr(settings, 'COMPUTE_SERVICE_TOKEN', '')
    try:
        headers = (
            {'X-Compute-Service-Token': service_token}
            if service_token
            else {}
        )
        response = requests.post(
            f'{base_url}/availability/search',
            json=payload,
            headers=headers,
            timeout=3.0,
        )
        response.raise_for_status()
        result = response.json()
    except requests.Timeout as exc:
        raise AvailabilityServiceError(
            'Availability service request timed out.'
        ) from exc
    except requests.ConnectionError as exc:
        raise AvailabilityServiceError(
            'Availability service could not be reached.'
        ) from exc
    except requests.HTTPError as exc:
        raise AvailabilityServiceError(
            f'Availability service returned HTTP {response.status_code}.'
        ) from exc
    except ValueError as exc:
        raise AvailabilityServiceError(
            'Availability service returned invalid JSON.'
        ) from exc
    except requests.RequestException as exc:
        raise AvailabilityServiceError(
            'Availability service request failed.'
        ) from exc

    elapsed_time = result.get('parallel_elapsed_time') if isinstance(result, dict) else None
    if (
        not isinstance(result, dict)
        or not isinstance(result.get('available_slots'), list)
        or not isinstance(result.get('slots', result.get('available_slots')), list)
        or isinstance(elapsed_time, bool)
        or not isinstance(elapsed_time, (int, float))
        or not isfinite(elapsed_time)
        or elapsed_time < 0
    ):
        raise AvailabilityServiceError(
            'Availability service returned an invalid response shape.'
        )
    expected_slot_fields = {
        'facility_id',
        'resource_id',
        'sport_id',
        'start_datetime',
        'end_datetime',
    }
    for slot in result['available_slots']:
        if (
            not isinstance(slot, dict)
            or not expected_slot_fields.issubset(slot)
            or any(
                isinstance(slot[field], bool) or not isinstance(slot[field], int)
                for field in ('facility_id', 'resource_id', 'sport_id')
            )
        ):
            raise AvailabilityServiceError(
                'Availability service returned an invalid available slot.'
            )
        for field in ('start_datetime', 'end_datetime'):
            value = slot[field]
            if not isinstance(value, str):
                raise AvailabilityServiceError(
                    'Availability service returned an invalid available slot.'
                )
            try:
                parsed_datetime = datetime.fromisoformat(value)
            except ValueError as exc:
                raise AvailabilityServiceError(
                    'Availability service returned an invalid available slot datetime.'
                ) from exc
            if parsed_datetime.tzinfo is None or parsed_datetime.utcoffset() is None:
                raise AvailabilityServiceError(
                    'Availability service returned a naive available slot datetime.'
                )
    for slot in result.get('slots', result['available_slots']):
        if (
            not isinstance(slot, dict)
            or not expected_slot_fields.issubset(slot)
            or slot.get('availability', 'available')
            not in {'available', 'closed', 'booked', 'past'}
        ):
            raise AvailabilityServiceError(
                'Availability service returned an invalid schedule slot.'
            )
        for field in ('start_datetime', 'end_datetime'):
            value = slot.get(field)
            if not isinstance(value, str):
                raise AvailabilityServiceError(
                    'Availability service returned an invalid schedule slot datetime.'
                )
            try:
                parsed_datetime = datetime.fromisoformat(value)
            except ValueError as exc:
                raise AvailabilityServiceError(
                    'Availability service returned an invalid schedule slot datetime.'
                ) from exc
            if parsed_datetime.tzinfo is None or parsed_datetime.utcoffset() is None:
                raise AvailabilityServiceError(
                    'Availability service returned a naive schedule slot datetime.'
                )
    return result
