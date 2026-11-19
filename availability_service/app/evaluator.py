from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, time, timedelta
from functools import partial
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

APPLICATION_TIMEZONE = ZoneInfo('Asia/Manila')


def _is_effective_on(item: dict[str, Any], target_date: date) -> bool:
    effective_from = item.get('effective_from')
    effective_until = item.get('effective_until')
    return (
        (effective_from is None or date.fromisoformat(effective_from) <= target_date)
        and (effective_until is None or date.fromisoformat(effective_until) >= target_date)
    )


def evaluate_facility_slots(
    facility_data: dict[str, Any],
    schedules: list[dict[str, Any]],
    closures: list[dict[str, Any]],
    bookings: list[dict[str, Any]],
    target_date: str,
    evaluated_at: str,
    include_unavailable: bool = False,
) -> list[dict[str, Any]]:
    """Evaluate one facility using only picklable JSON-compatible values."""
    search_date = date.fromisoformat(target_date)
    current_time = datetime.fromisoformat(evaluated_at).astimezone(APPLICATION_TIMEZONE)
    facility_id = facility_data['facility_id']
    available_slots = []

    for resource in facility_data['resources']:
        resource_id = resource['resource_id']
        for facility_sport_id in resource['facility_sport_ids']:
            applicable_schedules = [
                schedule
                for schedule in schedules
                if schedule['facility_id'] == facility_id
                and schedule['facility_sport_id'] == facility_sport_id
                and schedule['day_of_week'] == search_date.weekday()
                and _is_effective_on(schedule, search_date)
            ]
            resource_schedules = [
                schedule
                for schedule in applicable_schedules
                if schedule['resource_id'] == resource_id
            ]
            if resource_schedules:
                applicable_schedules = resource_schedules
            else:
                applicable_schedules = [
                    schedule
                    for schedule in applicable_schedules
                    if schedule['resource_id'] is None
                ]

            operating_hours = [
                hours
                for hours in facility_data['operating_hours']
                if hours['day_of_week'] == search_date.weekday()
                and _is_effective_on(hours, search_date)
            ]
            for hour in range(24):
                start = datetime.combine(
                    search_date,
                    time(hour=hour),
                    tzinfo=APPLICATION_TIMEZONE,
                )
                end = start + timedelta(hours=1)
                if end.date() != start.date():
                    continue
                if not any(
                    time.fromisoformat(hours['start_time']) <= start.time().replace(tzinfo=None)
                    and time.fromisoformat(hours['end_time']) >= end.time().replace(tzinfo=None)
                    for hours in operating_hours
                ):
                    continue
                if not any(
                    time.fromisoformat(schedule['start_time']) <= start.time().replace(tzinfo=None)
                    and time.fromisoformat(schedule['end_time']) >= end.time().replace(tzinfo=None)
                    for schedule in applicable_schedules
                ):
                    continue

                overlapping_closure = any(
                    closure['facility_id'] == facility_id
                    and closure['resource_id'] in (None, resource_id)
                    and datetime.fromisoformat(closure['start_datetime']) < end
                    and datetime.fromisoformat(closure['end_datetime']) > start
                    for closure in closures
                )
                overlapping_booking = any(
                    booking['resource_id'] == resource_id
                    and datetime.fromisoformat(booking['start_datetime']) < end
                    and datetime.fromisoformat(booking['end_datetime']) > start
                    for booking in bookings
                )
                if start <= current_time:
                    availability = 'past'
                    reason = ''
                elif overlapping_closure:
                    availability = 'closed'
                    reason = next(
                        (
                            closure.get('reason', '')
                            for closure in closures
                            if closure['facility_id'] == facility_id
                            and closure['resource_id'] in (None, resource_id)
                            and datetime.fromisoformat(closure['start_datetime']) < end
                            and datetime.fromisoformat(closure['end_datetime']) > start
                        ),
                        '',
                    )
                elif overlapping_booking:
                    availability = 'booked'
                    reason = ''
                else:
                    availability = 'available'
                    reason = ''
                if availability != 'available' and not include_unavailable:
                    continue

                slot = {
                    'facility_id': facility_id,
                    'resource_id': resource_id,
                    'sport_id': next(
                        schedule['sport_id']
                        for schedule in applicable_schedules
                    ),
                    'start_datetime': start.isoformat(),
                    'end_datetime': end.isoformat(),
                }
                if include_unavailable:
                    slot['availability'] = availability
                    slot['reason'] = reason
                available_slots.append(slot)

    return available_slots


def run_parallel_evaluation_with_schedule(
    payload,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    request_data = payload.model_dump(mode='json')
    facilities = request_data['facilities']
    started_at = perf_counter()
    if not facilities:
        return [], [], perf_counter() - started_at

    worker_count = min(len(facilities), 4)
    worker = partial(
        evaluate_facility_slots,
        schedules=request_data['schedules'],
        closures=request_data['closures'],
        bookings=request_data['existing_bookings'],
        target_date=request_data['target_date'],
        evaluated_at=request_data['evaluated_at'],
        include_unavailable=True,
    )
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        facility_results = executor.map(worker, facilities)
        schedule_slots = [
            slot
            for facility_slots in facility_results
            for slot in facility_slots
        ]
    available_slots = [
        {key: value for key, value in slot.items() if key not in {'availability', 'reason'}}
        for slot in schedule_slots
        if slot['availability'] == 'available'
    ]
    return available_slots, schedule_slots, perf_counter() - started_at


def run_parallel_evaluation(payload) -> tuple[list[dict[str, Any]], float]:
    available_slots, _schedule_slots, elapsed = run_parallel_evaluation_with_schedule(payload)
    return available_slots, elapsed
