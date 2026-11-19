import asyncio
from datetime import date, datetime, timedelta
import json

from fastapi import HTTPException
from availability_service.app.evaluator import (
    evaluate_facility_slots,
    run_parallel_evaluation,
)
from availability_service.app.main import (
    app,
    authorize_compute_node,
    search_availability,
)
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


def _post_asgi(payload, token):
    body = json.dumps(payload).encode('utf-8')
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.3'},
        'http_version': '1.1',
        'method': 'POST',
        'scheme': 'http',
        'path': '/availability/search',
        'raw_path': b'/availability/search',
        'query_string': b'',
        'root_path': '',
        'headers': [
            (b'content-type', b'application/json'),
            (b'content-length', str(len(body)).encode('ascii')),
            (b'x-compute-service-token', token.encode('ascii')),
        ],
        'client': ('127.0.0.1', 12345),
        'server': ('127.0.0.1', 8001),
    }
    request_sent = False
    response_messages = []

    async def receive():
        nonlocal request_sent
        if request_sent:
            return {'type': 'http.disconnect'}
        request_sent = True
        return {'type': 'http.request', 'body': body, 'more_body': False}

    async def send(message):
        response_messages.append(message)

    asyncio.run(app(scope, receive, send))
    status_code = next(
        message['status']
        for message in response_messages
        if message['type'] == 'http.response.start'
    )
    response_body = b''.join(
        message.get('body', b'')
        for message in response_messages
        if message['type'] == 'http.response.body'
    )
    return status_code, response_body


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


def test_mid_hour_closure_marks_overlapping_hour_closed_and_next_hour_available():
    request_data = build_request().model_dump(mode='json')
    request_data['facilities'][0]['operating_hours'] = [{
        'day_of_week': 0,
        'start_time': '13:00:00',
        'end_time': '19:00:00',
    }]
    request_data['schedules'][0]['start_time'] = '13:00:00'
    request_data['schedules'][0]['end_time'] = '19:00:00'
    request_data['closures'] = [{
        'facility_id': 1,
        'resource_id': 10,
        'start_datetime': '2026-11-02T13:36:00+08:00',
        'end_datetime': '2026-11-02T17:35:00+08:00',
        'reason': 'Mid-hour maintenance',
    }]
    request_data['existing_bookings'] = []
    request = AvailabilityRequest.model_validate(request_data).model_dump(mode='json')

    slots = evaluate_facility_slots(
        request['facilities'][0],
        request['schedules'],
        request['closures'],
        request['existing_bookings'],
        request['target_date'],
        request['evaluated_at'],
        include_unavailable=True,
    )

    assert [slot['availability'] for slot in slots] == [
        'closed', 'closed', 'closed', 'closed', 'closed', 'available',
    ]
    assert slots[4]['reason'] == 'Mid-hour maintenance'


def test_parallel_evaluator_includes_past_slots_as_unavailable():
    request_data = build_request().model_dump(mode='json')
    request_data['evaluated_at'] = '2026-11-02T09:15:00+08:00'
    request = AvailabilityRequest.model_validate(request_data).model_dump(mode='json')
    slots = evaluate_facility_slots(
        request['facilities'][0],
        request['schedules'],
        request['closures'],
        request['existing_bookings'],
        request['target_date'],
        request['evaluated_at'],
        include_unavailable=True,
    )

    assert [slot['availability'] for slot in slots] == ['past', 'booked', 'available']


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


def test_request_schema_rejects_target_date_more_than_31_days_away():
    payload = build_request().model_dump(mode='json')
    payload['target_date'] = (
        date.fromisoformat(payload['target_date']) + timedelta(days=32)
    ).isoformat()

    try:
        AvailabilityRequest.model_validate(payload)
    except ValueError as exc:
        assert 'within 31 days' in str(exc)
    else:
        raise AssertionError('An out-of-bounds target date was accepted.')


def test_request_schema_rejects_more_than_50_courts():
    payload = build_request().model_dump(mode='json')
    payload['facilities'][0]['resources'] = [
        {'resource_id': court_id, 'facility_sport_ids': [100]}
        for court_id in range(1, 52)
    ]

    try:
        AvailabilityRequest.model_validate(payload)
    except ValueError as exc:
        assert 'at most 50' in str(exc)
    else:
        raise AssertionError('A request with more than 50 courts was accepted.')


def test_compute_endpoint_authentication_fails_closed(monkeypatch):
    monkeypatch.setenv('COMPUTE_SERVICE_TOKEN', 'shared-test-token')
    try:
        authorize_compute_node('incorrect-token')
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError('An incorrect compute token was accepted.')

    assert authorize_compute_node('shared-test-token') is None

    monkeypatch.delenv('COMPUTE_SERVICE_TOKEN')
    try:
        authorize_compute_node('shared-test-token')
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError('The compute endpoint accepted a missing server token.')


def test_compute_http_endpoint_rejects_bad_credentials_and_oversized_schedules(
    monkeypatch,
):
    monkeypatch.setenv('COMPUTE_SERVICE_TOKEN', 'shared-test-token')
    request_data = build_request().model_dump(mode='json')

    unauthorized_status, _body = _post_asgi(request_data, 'wrong-token')
    assert unauthorized_status == 401

    request_data['target_date'] = (
        date.fromisoformat(request_data['target_date']) + timedelta(days=32)
    ).isoformat()
    date_status, date_body = _post_asgi(request_data, 'shared-test-token')
    assert date_status == 422
    assert b'within 31 days' in date_body

    request_data = build_request().model_dump(mode='json')
    request_data['facilities'][0]['resources'] = [
        {'resource_id': court_id, 'facility_sport_ids': [100]}
        for court_id in range(1, 52)
    ]
    invalid_status, body = _post_asgi(request_data, 'shared-test-token')

    assert invalid_status == 422
    assert b'at most 50' in body


def test_compute_http_endpoint_rejects_payloads_over_five_megabytes(monkeypatch):
    monkeypatch.setenv('COMPUTE_SERVICE_TOKEN', 'shared-test-token')
    body = b' ' * (5 * 1024 * 1024 + 1)
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.3'},
        'http_version': '1.1',
        'method': 'POST',
        'scheme': 'http',
        'path': '/availability/search',
        'raw_path': b'/availability/search',
        'query_string': b'',
        'root_path': '',
        'headers': [
            (b'content-type', b'application/json'),
            (b'content-length', str(len(body)).encode('ascii')),
            (b'x-compute-service-token', b'shared-test-token'),
        ],
        'client': ('127.0.0.1', 12345),
        'server': ('127.0.0.1', 8001),
    }
    response_messages = []

    async def receive():
        raise AssertionError('Oversized Content-Length should be rejected before reading.')

    async def send(message):
        response_messages.append(message)

    asyncio.run(app(scope, receive, send))

    response_start = next(
        message
        for message in response_messages
        if message['type'] == 'http.response.start'
    )
    assert response_start['status'] == 413
