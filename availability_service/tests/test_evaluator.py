from datetime import date, datetime

from availability_service.app.evaluator import (
    evaluate_facility_slots,
    run_parallel_evaluation,
)
from availability_service.app.main import app, search_availability
from availability_service.app.schemas import AvailabilityRequest


def build_request() -> AvailabilityRequest:
    target_date = date(2026, 11, 2)
    return AvailabilityRequest.model_validate({
        'target_date': target_date.isoformat(),
        'evaluated_at': '2026-10-29T12:00:00+08:00',
        'facilities': [{
            'facility_id': 1,
            'resources': [{
                'resource_id': 10,
                'facility_sport_ids': [100],
            }],
            'operating_hours': [{
                'day_of_week': target_date.weekday(),
                'start_time': '08:00:00',
                'end_time': '13:00:00',
            }],
        }],
        'schedules': [{
            'facility_id': 1,
            'facility_sport_id': 100,
            'sport_id': 5,
            'resource_id': None,
            'day_of_week': target_date.weekday(),
            'start_time': '09:00:00',
            'end_time': '12:00:00',
        }],
        'closures': [{
            'facility_id': 1,
            'resource_id': 10,
            'start_datetime': '2026-11-02T09:30:00+08:00',
            'end_datetime': '2026-11-02T10:00:00+08:00',
        }],
        'existing_bookings': [{
            'resource_id': 10,
            'start_datetime': '2026-11-02T10:00:00+08:00',
            'end_datetime': '2026-11-02T11:00:00+08:00',
        }],
    })


def test_parallel_evaluator_matches_serial_worker_result():
    request = build_request()
    request_data = request.model_dump(mode='json')
    expected = evaluate_facility_slots(
        request_data['facilities'][0],
        request_data['schedules'],
        request_data['closures'],
        request_data['existing_bookings'],
        request_data['target_date'],
        request_data['evaluated_at'],
    )

    parallel_slots, elapsed = run_parallel_evaluation(request)

    assert parallel_slots == expected
    assert len(parallel_slots) == 1
    assert parallel_slots[0]['sport_id'] == 5
    assert parallel_slots[0]['start_datetime'] == '2026-11-02T11:00:00+08:00'
    assert elapsed >= 0


def test_parallel_evaluator_maps_independent_facilities():
    payload = build_request().model_dump(mode='json')
    second_facility = {
        **payload['facilities'][0],
        'facility_id': 2,
        'resources': [{
            'resource_id': 20,
            'facility_sport_ids': [200],
        }],
    }
    second_schedule = {
        **payload['schedules'][0],
        'facility_id': 2,
        'facility_sport_id': 200,
        'sport_id': 6,
    }
    payload['facilities'].append(second_facility)
    payload['schedules'].append(second_schedule)
    payload['closures'] = []
    payload['existing_bookings'] = []
    request = AvailabilityRequest.model_validate(payload)

    slots, _elapsed = run_parallel_evaluation(request)

    assert {(slot['facility_id'], slot['resource_id'], slot['sport_id']) for slot in slots} == {
        (1, 10, 5),
        (2, 20, 6),
    }


def test_resource_specific_schedule_overrides_general_schedule():
    request = build_request()
    payload = request.model_dump(mode='json')
    payload['facilities'][0]['operating_hours'] = [{
        'day_of_week': 0,
        'start_time': '08:00:00',
        'end_time': '13:00:00',
    }]
    payload['closures'] = []
    payload['existing_bookings'] = []
    payload['schedules'].append({
        'facility_id': 1,
        'facility_sport_id': 100,
        'sport_id': 5,
        'resource_id': 10,
        'day_of_week': 0,
        'start_time': '11:00:00',
        'end_time': '12:00:00',
    })
    request = AvailabilityRequest.model_validate(payload)
    request_data = request.model_dump(mode='json')

    result = evaluate_facility_slots(
        request_data['facilities'][0],
        request_data['schedules'],
        request_data['closures'],
        request_data['existing_bookings'],
        request_data['target_date'],
        request_data['evaluated_at'],
    )

    assert [slot['start_datetime'] for slot in result] == [
        '2026-11-02T11:00:00+08:00',
    ]


def test_search_endpoint_returns_typed_parallel_response():
    assert any(
        route.path == '/availability/search' and 'POST' in route.methods
        for route in app.routes
    )
    response = search_availability(build_request())

    assert len(response.available_slots) == 1
    assert response.parallel_elapsed_time >= 0


def test_request_schema_rejects_naive_evaluation_datetime():
    payload = build_request().model_dump(mode='json')
    payload['evaluated_at'] = datetime(2026, 10, 29, 12).isoformat()

    try:
        AvailabilityRequest.model_validate(payload)
    except ValueError as exc:
        assert 'timezone offset' in str(exc)
    else:
        raise AssertionError('Naive evaluated_at was accepted.')
