import json
from datetime import datetime, time, timedelta
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Booking

from .availability_client import (
    AvailabilityServiceError,
    fetch_parallel_availability,
    serialize_availability_request,
)
from .models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilityOperatingHours,
    FacilitySport,
    ResourceSport,
    Sport,
    SportSchedule,
)


@override_settings(COMPUTE_SERVICE_TOKEN='test-compute-token')
class AvailabilityHTTPClientTests(TestCase):
    def setUp(self):
        self.facility = Facility.objects.create(
            name='Synthetic HTTP Client Facility',
            default_hourly_rate='200.00',
        )
        self.sport = Sport.objects.create(name='Basketball', slug='basketball')
        self.facility_sport = FacilitySport.objects.create(
            facility=self.facility,
            sport=self.sport,
            hourly_rate='175.00',
        )
        self.resource = BookableResource.objects.create(
            facility=self.facility,
            name='Client Test Court',
        )
        ResourceSport.objects.create(
            resource=self.resource,
            facility_sport=self.facility_sport,
        )
        self.target_date = timezone.localdate() + timedelta(days=1)
        FacilityOperatingHours.objects.create(
            facility=self.facility,
            day_of_week=self.target_date.weekday(),
            start_time=time(8),
            end_time=time(17),
        )
        self.schedule = SportSchedule.objects.create(
            facility_sport=self.facility_sport,
            day_of_week=self.target_date.weekday(),
            start_time=time(9),
            end_time=time(12),
        )
        self.closure = FacilityClosure.objects.create(
            facility=self.facility,
            resource=self.resource,
            start_datetime=timezone.make_aware(
                datetime.combine(self.target_date, time(10))
            ),
            end_datetime=timezone.make_aware(
                datetime.combine(self.target_date, time(11))
            ),
            reason='Synthetic maintenance window',
        )
        self.user = get_user_model().objects.create_user(username='client-test')
        self.confirmed_booking = Booking.objects.create(
            user=self.user,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.make_aware(
                datetime.combine(self.target_date, time(11))
            ),
            end_datetime=timezone.make_aware(
                datetime.combine(self.target_date, time(12))
            ),
            participant_count=2,
            rate_snapshot='175.00',
            total_price='175.00',
        )
        self.cancelled_booking = Booking.objects.create(
            user=self.user,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.make_aware(
                datetime.combine(self.target_date, time(12))
            ),
            end_datetime=timezone.make_aware(
                datetime.combine(self.target_date, time(13))
            ),
            participant_count=2,
            status=Booking.Status.CANCELLED,
            rate_snapshot='175.00',
            total_price='175.00',
        )

    def test_request_serialization_contains_only_json_primitives(self):
        payload = serialize_availability_request(
            self.target_date,
            [self.facility],
            [self.closure],
            [self.schedule],
            [self.confirmed_booking, self.cancelled_booking],
        )

        self.assertEqual(payload['facilities'][0]['resources'][0]['resource_id'], self.resource.pk)
        self.assertEqual(payload['facilities'][0]['resources'][0]['facility_sport_ids'], [self.facility_sport.pk])
        self.assertEqual(len(payload['existing_bookings']), 1)
        self.assertEqual(payload['existing_bookings'][0]['resource_id'], self.resource.pk)
        json.dumps(payload)

    @patch('facilities.availability_client.requests.post')
    def test_client_posts_serialized_payload_and_returns_service_response(self, post):
        post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'available_slots': [],
                'parallel_elapsed_time': 0.02,
            }),
        )

        result = fetch_parallel_availability(
            self.target_date,
            [self.facility],
            [self.closure],
            [self.schedule],
            [self.confirmed_booking],
        )

        self.assertEqual(result['parallel_elapsed_time'], 0.02)
        args, kwargs = post.call_args
        self.assertEqual(args[0], 'http://127.0.0.1:8001/availability/search')
        self.assertEqual(kwargs['json']['target_date'], self.target_date.isoformat())
        self.assertEqual(
            kwargs['headers']['X-Compute-Service-Token'],
            'test-compute-token',
        )
        self.assertEqual(kwargs['timeout'], 3.0)

    @patch(
        'facilities.availability_client.requests.post',
        side_effect=requests.ConnectionError('offline'),
    )
    def test_client_raises_explicit_error_when_service_is_offline(self, post):
        with self.assertRaisesMessage(
            AvailabilityServiceError,
            'Availability service could not be reached.',
        ):
            fetch_parallel_availability(
                self.target_date,
                [self.facility],
                [self.closure],
                [self.schedule],
                [self.confirmed_booking],
            )
        post.assert_called_once()

    @patch('facilities.availability_client.requests.post')
    def test_client_rejects_malformed_service_response(self, post):
        post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'available_slots': [{
                    'facility_id': self.facility.pk,
                    'resource_id': self.resource.pk,
                    'sport_id': self.sport.pk,
                    'start_datetime': '2026-10-30T10:00:00',
                    'end_datetime': '2026-10-30T11:00:00+08:00',
                }],
                'parallel_elapsed_time': 0.02,
            }),
        )

        with self.assertRaisesMessage(
            AvailabilityServiceError,
            'Availability service returned a naive available slot datetime.',
        ):
            fetch_parallel_availability(
                self.target_date,
                [self.facility],
                [self.closure],
                [self.schedule],
                [self.confirmed_booking],
            )
