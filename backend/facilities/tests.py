from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from bookings.models import Booking

from .availability import active_resource_offerings, evaluate_serial_slots
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
from .serializers import FacilitySportSerializer


class FacilityDetailPageTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sport = Sport.objects.create(name='Basketball', slug='basketball')
        cls.facility = Facility.objects.create(
            name='Naval Test Court',
            barangay='Poblacion',
            capacity=30,
        )
        FacilitySport.objects.create(
            facility=cls.facility,
            sport=cls.sport,
        )
        FacilityOperatingHours.objects.create(
            facility=cls.facility,
            day_of_week=0,
            start_time=time(8),
            end_time=time(17),
        )

    def test_facility_detail_page_renders_search_form_and_supported_sport(self):
        response = self.client.get(
            reverse('facility-detail-page', kwargs={'pk': self.facility.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'facility_detail.html')
        self.assertContains(response, self.facility.name)
        self.assertContains(response, self.facility.barangay)
        self.assertContains(response, '8:00 AM')
        self.assertContains(response, '5:00 PM')
        self.assertContains(response, 'id="availability-date"')
        self.assertContains(response, 'id="availability-sport"')
        self.assertContains(response, 'id="quick-date-pills"')
        self.assertContains(response, 'id="availability-results"')
        self.assertContains(response, 'name="contact_email"')
        self.assertContains(response, 'name="contact_phone"')
        self.assertContains(response, 'id="player-names-grid"')
        self.assertContains(response, 'id="facility-resources-data"')
        self.assertContains(response, 'id="merchant-qr-lightbox"')
        self.assertContains(response, 'Click to View HD QR')
        self.assertEqual(response.context['available_payment_methods'], ['cash'])
        self.assertContains(response, 'data-payment-methods="cash"')
        self.assertContains(response, 'Basketball')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'js/availability.js')

    def test_facility_detail_exposes_only_configured_payment_methods(self):
        self.facility.gcash_number = '09171234567'
        self.facility.accepts_card = True
        self.facility.save(update_fields=('gcash_number', 'accepts_card'))

        response = self.client.get(
            reverse('facility-detail-page', kwargs={'pk': self.facility.pk}),
        )

        self.assertEqual(
            response.context['available_payment_methods'],
            ['gcash', 'card', 'cash'],
        )
        self.assertContains(response, 'data-payment-methods="gcash,card,cash"')

    def test_inactive_facility_detail_page_returns_not_found(self):
        self.facility.is_active = False
        self.facility.save(update_fields=('is_active',))

        response = self.client.get(
            reverse('facility-detail-page', kwargs={'pk': self.facility.pk}),
        )

        self.assertEqual(response.status_code, 404)


class FacilityDiscoveryAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.basketball = Sport.objects.create(
            name='Basketball',
            slug='basketball',
        )
        cls.pickleball = Sport.objects.create(
            name='Pickleball',
            slug='pickleball',
        )
        cls.inactive_sport = Sport.objects.create(
            name='Inactive Sport',
            slug='inactive-sport',
            is_active=False,
        )
        cls.shared_facility = Facility.objects.create(
            name='Shared Sports Facility',
            is_demo_data=True,
            latitude='11.000000',
            longitude='124.000000',
        )
        cls.basketball_facility = Facility.objects.create(
            name='Basketball Facility',
        )
        cls.inactive_facility = Facility.objects.create(
            name='Inactive Facility',
            is_active=False,
        )

        FacilitySport.objects.create(
            facility=cls.shared_facility,
            sport=cls.basketball,
            hourly_rate='250.00',
        )
        FacilitySport.objects.create(
            facility=cls.shared_facility,
            sport=cls.pickleball,
            hourly_rate='150.00',
        )
        FacilitySport.objects.create(
            facility=cls.shared_facility,
            sport=cls.inactive_sport,
        )
        FacilitySport.objects.create(
            facility=cls.basketball_facility,
            sport=cls.basketball,
        )
        FacilitySport.objects.create(
            facility=cls.inactive_facility,
            sport=cls.basketball,
        )

        cls.active_resource = BookableResource.objects.create(
            facility=cls.shared_facility,
            name='Multipurpose Court',
            resource_type='multipurpose',
        )
        BookableResource.objects.create(
            facility=cls.shared_facility,
            name='Inactive Court',
            is_active=False,
        )

    def test_sports_endpoint_returns_only_active_sports(self):
        response = self.client.get('/api/sports/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [sport['slug'] for sport in response.data['results']],
            ['basketball', 'pickleball'],
        )

    def test_facilities_default_to_or_matching_and_include_nested_data(self):
        response = self.client.get(
            '/api/facilities/',
            {'sports': 'basketball,pickleball'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['match'], 'any')
        facilities = response.data['results']
        self.assertEqual(
            {facility['name'] for facility in facilities},
            {'Shared Sports Facility', 'Basketball Facility'},
        )
        shared = next(
            facility for facility in facilities
            if facility['name'] == 'Shared Sports Facility'
        )
        self.assertEqual(
            [sport['slug'] for sport in shared['supported_sports']],
            ['basketball', 'pickleball'],
        )
        self.assertEqual(
            [sport['slug'] for sport in shared['matching_sports']],
            ['basketball', 'pickleball'],
        )
        self.assertEqual(
            shared['resources'],
            [{
                'id': self.active_resource.id,
                'name': 'Multipurpose Court',
                'resource_type': 'multipurpose',
            }],
        )
        self.assertIsNone(shared['latitude'])
        self.assertIsNone(shared['longitude'])

    def test_all_matching_requires_each_requested_active_sport(self):
        response = self.client.get(
            '/api/courts/',
            {'sports': 'basketball,pickleball', 'match': 'all'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['match'], 'all')
        self.assertEqual(
            [facility['name'] for facility in response.data['results']],
            ['Shared Sports Facility'],
        )

    def test_invalid_match_mode_returns_bad_request(self):
        response = self.client.get(
            '/api/facilities/',
            {'sports': 'basketball', 'match': 'sometimes'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('match', response.data)

    def test_facility_detail_excludes_inactive_facilities(self):
        response = self.client.get(
            f'/api/facilities/{self.inactive_facility.id}/',
        )

        self.assertEqual(response.status_code, 404)

    def test_verified_real_facility_coordinates_are_serialized(self):
        facility = Facility.objects.create(
            name='Verified Facility',
            is_demo_data=False,
            is_verified=True,
            latitude='11.000000',
            longitude='124.000000',
        )
        response = self.client.get(f'/api/facilities/{facility.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['latitude'], Decimal('11.000000'))
        self.assertEqual(response.data['longitude'], Decimal('124.000000'))

    def test_facility_sport_serializer_includes_sport_and_hourly_rate(self):
        facility_sport = FacilitySport.objects.get(
            facility=self.shared_facility,
            sport=self.basketball,
        )

        serialized = FacilitySportSerializer(facility_sport).data

        self.assertEqual(serialized['sport']['slug'], 'basketball')
        self.assertEqual(serialized['hourly_rate'], '250.00')


class SerialAvailabilityAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sport = Sport.objects.create(name='Basketball', slug='basketball')
        cls.facility = Facility.objects.create(
            name='Synthetic Availability Facility',
            default_hourly_rate='200.00',
        )
        cls.facility_sport = FacilitySport.objects.create(
            facility=cls.facility,
            sport=cls.sport,
            hourly_rate='175.00',
        )
        cls.resource = BookableResource.objects.create(
            facility=cls.facility,
            name='Test Court',
        )
        ResourceSport.objects.create(
            resource=cls.resource,
            facility_sport=cls.facility_sport,
        )
        cls.search_date = timezone.localdate() + timedelta(days=1)
        FacilityOperatingHours.objects.create(
            facility=cls.facility,
            day_of_week=cls.search_date.weekday(),
            start_time=time(8),
            end_time=time(17),
        )
        SportSchedule.objects.create(
            facility_sport=cls.facility_sport,
            day_of_week=cls.search_date.weekday(),
            start_time=time(9),
            end_time=time(12),
        )
        local_midnight = timezone.make_aware(
            datetime.combine(cls.search_date, time.min)
        )
        cls.booked_start = local_midnight + timedelta(hours=9)
        cls.closure_start = local_midnight + timedelta(hours=10, minutes=30)
        cls.user = get_user_model().objects.create_user(username='availability-test')
        Booking.objects.create(
            user=cls.user,
            resource=cls.resource,
            sport=cls.sport,
            start_datetime=cls.booked_start,
            end_datetime=cls.booked_start + timedelta(hours=1),
            participant_count=2,
            status=Booking.Status.CONFIRMED,
            rate_snapshot='175.00',
            total_price='175.00',
        )
        FacilityClosure.objects.create(
            facility=cls.facility,
            resource=cls.resource,
            start_datetime=cls.closure_start,
            end_datetime=cls.closure_start + timedelta(minutes=30),
            reason='Temporary resource maintenance',
        )

    def test_search_excludes_booked_closed_and_unscheduled_slots(self):
        response = self.client.get(
            '/api/availability/search',
            {
                'date': self.search_date.isoformat(),
                'sport': self.sport.slug,
                'facility': self.facility.pk,
                'mode': 'serial',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['timezone'], 'Asia/Manila')
        slots = response.data['results']
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0]['facility_id'], self.facility.pk)
        self.assertEqual(slots[0]['resource_id'], self.resource.pk)
        self.assertEqual(slots[0]['sport_id'], self.sport.pk)
        self.assertEqual(
            slots[0]['start_datetime'],
            timezone.make_aware(
                datetime.combine(self.search_date, time(11))
            ),
        )
        self.assertEqual(
            slots[0]['end_datetime'],
            timezone.make_aware(
                datetime.combine(self.search_date, time(12))
            ),
        )

    def test_schedule_grid_includes_booked_closed_and_available_slots(self):
        response = self.client.get(
            '/api/availability/search',
            {
                'date': self.search_date.isoformat(),
                'sport': self.sport.slug,
                'facility': self.facility.pk,
                'mode': 'serial',
            },
        )

        self.assertEqual(response.status_code, 200)
        grid = response.data['slots']
        self.assertEqual(
            [slot['availability'] for slot in grid],
            ['booked', 'closed', 'available'],
        )
        self.assertEqual(grid[1]['reason'], 'Temporary resource maintenance')

    def test_serial_schedule_marks_current_day_slots_as_passed(self):
        today = timezone.localdate()
        FacilityOperatingHours.objects.create(
            facility=self.facility,
            day_of_week=today.weekday(),
            start_time=time(9),
            end_time=time(12),
        )
        SportSchedule.objects.create(
            facility_sport=self.facility_sport,
            day_of_week=today.weekday(),
            start_time=time(9),
            end_time=time(12),
        )
        evaluated_at = timezone.make_aware(datetime.combine(today, time(10, 30)))
        slots = evaluate_serial_slots(
            active_resource_offerings(
                facility_id=self.facility.pk,
                sport=self.sport,
            ),
            today,
            evaluated_at=evaluated_at,
        )

        self.assertTrue(slots)
        self.assertEqual(slots[0]['availability'], 'past')
        self.assertEqual(
            [slot['availability'] for slot in slots],
            ['past', 'past', 'available'],
        )

    def test_explicit_serial_mode_returns_expected_available_slot(self):
        response = self.client.get(
            '/api/availability/search',
            {
                'date': self.search_date.isoformat(),
                'sport': self.sport.slug,
                'facility': self.facility.pk,
                'mode': 'serial',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['mode'], 'serial')
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(
            response.data['results'][0]['start_datetime'],
            timezone.make_aware(
                datetime.combine(self.search_date, time(11))
            ),
        )

    @patch('facilities.availability_client.requests.post')
    def test_availability_mode_defaults_to_parallel(self, post):
        post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'available_slots': [],
                'parallel_elapsed_time': 0.01,
            }),
        )

        response = self.client.get(
            '/api/availability/search',
            {
                'date': self.search_date.isoformat(),
                'sport': self.sport.slug,
                'facility': self.facility.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['mode'], 'parallel')
        self.assertFalse(response.data['fallback'])
        post.assert_called_once()

    @patch('facilities.availability_client.requests.post')
    def test_parallel_mode_uses_fastapi_response(self, post):
        serial_response = self.client.get(
            '/api/availability/search',
            {
                'date': self.search_date.isoformat(),
                'sport': self.sport.slug,
                'facility': self.facility.pk,
                'mode': 'serial',
            },
        )
        self.assertEqual(serial_response.status_code, 200)
        serial_slots = serial_response.data['results']
        post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'available_slots': [{
                    'facility_id': self.facility.pk,
                    'resource_id': self.resource.pk,
                    'sport_id': self.sport.pk,
                    'start_datetime': serial_slots[0]['start_datetime'].isoformat(),
                    'end_datetime': serial_slots[0]['end_datetime'].isoformat(),
                }],
                'parallel_elapsed_time': 0.125,
            }),
        )

        response = self.client.get(
            '/api/availability/search',
            {
                'date': self.search_date.isoformat(),
                'sport': self.sport.slug,
                'facility': self.facility.pk,
                'mode': 'parallel',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['mode'], 'parallel')
        self.assertFalse(response.data['fallback'])
        self.assertEqual(response.data['parallel_elapsed_time'], 0.125)
        self.assertEqual(response.data['results'], serial_slots)
        post.assert_called_once()
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['target_date'], self.search_date.isoformat())
        self.assertEqual(payload['facilities'][0]['facility_id'], self.facility.pk)
        self.assertEqual(payload['existing_bookings'][0]['resource_id'], self.resource.pk)

    @patch(
        'facilities.availability_client.requests.post',
        side_effect=requests.Timeout('simulated timeout'),
    )
    def test_parallel_mode_falls_back_to_serial_on_timeout(self, post):
        response = self.client.get(
            '/api/availability/search',
            {
                'date': self.search_date.isoformat(),
                'sport': self.sport.slug,
                'facility': self.facility.pk,
                'mode': 'parallel',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['mode'], 'serial')
        self.assertEqual(response.data['requested_mode'], 'parallel')
        self.assertTrue(response.data['fallback'])
        self.assertEqual(len(response.data['results']), 1)
        post.assert_called_once()

    def test_search_rejects_invalid_date_and_unknown_sport(self):
        invalid_date = self.client.get(
            '/api/availability/search',
            {'date': 'not-a-date'},
        )
        invalid_mode = self.client.get(
            '/api/availability/search',
            {
                'date': self.search_date.isoformat(),
                'mode': 'automatic',
            },
        )
        unknown_sport = self.client.get(
            '/api/availability/search',
            {'date': self.search_date.isoformat(), 'sport': 'not-a-sport'},
        )

        self.assertEqual(invalid_date.status_code, 400)
        self.assertEqual(invalid_mode.status_code, 400)
        self.assertEqual(unknown_sport.status_code, 400)
