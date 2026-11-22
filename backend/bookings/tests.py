from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from decimal import Decimal
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from facilities.models import (
    BookableResource,
    FacilityClosure,
    Facility,
    FacilityOperatingHours,
    FacilitySport,
    ResourceSport,
    Sport,
    SportSchedule,
)

from .models import Booking


class BookingAPITests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='booker',
            password='test-password',
        )
        self.other_user = user_model.objects.create_user(
            username='other-booker',
            password='test-password',
        )
        self.facility = Facility.objects.create(
            name='Synthetic Test Facility',
            capacity=20,
            default_hourly_rate='300.00',
            wallet_account_name='Test Venue Merchant',
            gcash_number='09171234567',
            maya_number='09181234567',
        )
        self.sport = Sport.objects.create(name='Basketball', slug='basketball')
        self.facility_sport = FacilitySport.objects.create(
            facility=self.facility,
            sport=self.sport,
            hourly_rate='250.00',
        )
        self.resource = BookableResource.objects.create(
            facility=self.facility,
            name='Shared Court',
            capacity=10,
        )
        ResourceSport.objects.create(
            resource=self.resource,
            facility_sport=self.facility_sport,
        )
        self.start_datetime = timezone.make_aware(
            datetime.combine(timezone.localdate() + timedelta(days=1), time(hour=10))
        )
        FacilityOperatingHours.objects.create(
            facility=self.facility,
            day_of_week=self.start_datetime.weekday(),
            start_time=time(0),
            end_time=time(23, 59),
        )
        self.sport_schedule = SportSchedule.objects.create(
            facility_sport=self.facility_sport,
            day_of_week=self.start_datetime.weekday(),
            start_time=time(0),
            end_time=time(23, 59),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def booking_payload(self, **overrides):
        payload = {
            'resource_id': self.resource.pk,
            'sport_id': self.sport.pk,
            'start_datetime': self.start_datetime.isoformat(),
            'end_datetime': (self.start_datetime + timedelta(hours=1)).isoformat(),
            'participant_count': 4,
        }
        payload.update(overrides)
        return payload

    def create_booking(self, client=None, **overrides):
        return (client or self.client).post(
            '/api/bookings/',
            self.booking_payload(**overrides),
            format='json',
        )

    def test_valid_booking_is_created_with_server_calculated_price(self):
        response = self.create_booking(
            total_price='0.00',
            rate_snapshot='0.00',
            participant_names='Alex, Sam',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['user'], self.user.pk)
        self.assertEqual(response.data['status'], Booking.Status.CONFIRMED)
        self.assertEqual(response.data['facility_name'], self.facility.name)
        self.assertEqual(response.data['resource_name'], self.resource.name)
        self.assertEqual(response.data['sport_name'], self.sport.name)
        self.assertEqual(response.data['rate_snapshot'], '250.00')
        self.assertEqual(response.data['total_price'], '250.00')
        self.assertEqual(response.data['platform_fee_rate'], '0.0500')
        self.assertEqual(response.data['platform_fee_amount'], '12.50')
        self.assertEqual(response.data['owner_payout_amount'], '237.50')
        self.assertEqual(response.data['payment_method'], 'gcash')
        self.assertEqual(response.data['payment_status'], 'pending')
        self.assertRegex(response.data['payment_reference'], r'^CG-\d{8}-[A-F0-9]{6}$')
        self.assertEqual(response.data['merchant_account_name'], 'Test Venue Merchant')
        self.assertEqual(response.data['merchant_gcash_number'], '09171234567')
        self.assertEqual(response.data['merchant_maya_number'], '09181234567')
        self.assertEqual(response.data['merchant_qr_url'], '')
        self.assertEqual(response.data['participant_names'], 'Alex, Sam')
        self.assertEqual(Booking.objects.get().participant_names, 'Alex, Sam')
        self.assertEqual(Booking.objects.count(), 1)

    def test_batch_booking_creates_multiple_slots_atomically_with_total(self):
        second_start = self.start_datetime + timedelta(hours=1)
        response = self.client.post(
            '/api/bookings/',
            {
                'sport_id': self.sport.pk,
                'participant_count': 3,
                'participant_names': 'Alex, Sam, Jo',
                'contact_email': 'booker@example.com',
                'contact_phone': '+639171234567',
                'slots': [
                    {
                        'resource_id': self.resource.pk,
                        'start_datetime': self.start_datetime.isoformat(),
                        'end_datetime': (self.start_datetime + timedelta(hours=1)).isoformat(),
                    },
                    {
                        'resource_id': self.resource.pk,
                        'start_datetime': second_start.isoformat(),
                        'end_datetime': (second_start + timedelta(hours=1)).isoformat(),
                    },
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data['results']), 2)
        self.assertEqual(response.data['total_price'], '500.00')
        self.assertEqual(Booking.objects.count(), 2)
        self.assertEqual(
            set(Booking.objects.values_list('contact_email', flat=True)),
            {'booker@example.com'},
        )
        self.assertEqual(
            set(Booking.objects.values_list('contact_phone', flat=True)),
            {'+639171234567'},
        )
        self.assertEqual(
            set(Booking.objects.values_list('platform_fee_amount', flat=True)),
            {Decimal('12.50')},
        )

    def test_cash_payment_is_pending_and_payment_method_is_returned(self):
        response = self.create_booking(payment_method='cash')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['payment_method'], 'cash')
        self.assertEqual(response.data['payment_status'], 'pending')
        self.assertEqual(response.data['platform_fee_amount'], '12.50')
        self.assertEqual(response.data['owner_payout_amount'], '237.50')

    def test_unconfigured_payment_methods_are_rejected(self):
        self.facility.gcash_number = ''
        self.facility.maya_number = ''
        self.facility.save(update_fields=('gcash_number', 'maya_number'))

        response = self.create_booking(payment_method='gcash')

        self.assertEqual(response.status_code, 400)
        self.assertIn('payment_method', response.data)
        self.assertEqual(Booking.objects.count(), 0)

    def test_card_booking_requires_owner_card_configuration(self):
        response = self.create_booking(payment_method='card')
        self.assertEqual(response.status_code, 400)

        self.facility.accepts_card = True
        self.facility.save(update_fields=('accepts_card',))
        response = self.create_booking(payment_method='card')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['payment_method'], 'card')
        self.assertEqual(response.data['payment_status'], 'pending')

    def test_batch_booking_records_selected_payment_method(self):
        response = self.client.post(
            '/api/bookings/',
            {
                'sport_id': self.sport.pk,
                'participant_count': 2,
                'contact_email': 'booker@example.com',
                'contact_phone': '+639171234567',
                'payment_method': 'maya',
                'slots': [{
                    'resource_id': self.resource.pk,
                    'start_datetime': self.start_datetime.isoformat(),
                    'end_datetime': (self.start_datetime + timedelta(hours=1)).isoformat(),
                }],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201, response.data)
        booking = response.data['results'][0]
        self.assertEqual(booking['payment_method'], 'maya')
        self.assertEqual(booking['payment_status'], 'pending')
        self.assertEqual(booking['payment_reference'], Booking.objects.get().payment_reference)

    def test_batch_booking_rolls_back_earlier_slots_when_a_later_slot_conflicts(self):
        second_start = self.start_datetime + timedelta(hours=1)
        existing = Booking.objects.create(
            user=self.user,
            resource=self.resource,
            sport=self.sport,
            start_datetime=second_start,
            end_datetime=second_start + timedelta(hours=1),
            participant_count=2,
            rate_snapshot='250.00',
            total_price='250.00',
        )
        response = self.client.post(
            '/api/bookings/',
            {
                'sport_id': self.sport.pk,
                'participant_count': 2,
                'contact_email': 'booker@example.com',
                'contact_phone': '+639171234567',
                'slots': [
                    {
                        'resource_id': self.resource.pk,
                        'start_datetime': self.start_datetime.isoformat(),
                        'end_datetime': (self.start_datetime + timedelta(hours=1)).isoformat(),
                    },
                    {
                        'resource_id': self.resource.pk,
                        'start_datetime': second_start.isoformat(),
                        'end_datetime': (second_start + timedelta(hours=1)).isoformat(),
                    },
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(list(Booking.objects.values_list('pk', flat=True)), [existing.pk])

    def test_batch_booking_requires_valid_contact_details(self):
        response = self.client.post(
            '/api/bookings/',
            {
                'sport_id': self.sport.pk,
                'participant_count': 2,
                'contact_email': 'not-an-email',
                'contact_phone': '123',
                'slots': [{
                    'resource_id': self.resource.pk,
                    'start_datetime': self.start_datetime.isoformat(),
                    'end_datetime': (self.start_datetime + timedelta(hours=1)).isoformat(),
                }],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Booking.objects.count(), 0)

    def test_facility_default_rate_is_used_when_sport_rate_is_unset(self):
        self.facility_sport.hourly_rate = None
        self.facility_sport.save(update_fields=('hourly_rate',))

        response = self.create_booking(total_price='0.00')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['rate_snapshot'], '300.00')
        self.assertEqual(response.data['total_price'], '300.00')

    def test_resource_specific_rate_overrides_sport_rate(self):
        self.resource.hourly_rate = Decimal('125.00')
        self.resource.save(update_fields=('hourly_rate',))

        response = self.create_booking(total_price='0.00')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['rate_snapshot'], '125.00')
        self.assertEqual(response.data['total_price'], '125.00')

    def test_overlapping_confirmed_booking_returns_http_409_across_sports(self):
        response = self.create_booking()
        self.assertEqual(response.status_code, 201)

        pickleball = Sport.objects.create(name='Pickleball', slug='pickleball')
        pickleball_offering = FacilitySport.objects.create(
            facility=self.facility,
            sport=pickleball,
            hourly_rate='150.00',
        )
        ResourceSport.objects.create(
            resource=self.resource,
            facility_sport=pickleball_offering,
        )
        SportSchedule.objects.create(
            facility_sport=pickleball_offering,
            day_of_week=self.start_datetime.weekday(),
            start_time=time(0),
            end_time=time(23, 59),
        )

        conflict = self.create_booking(sport_id=pickleball.pk)

        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CONFIRMED).count(), 1)

    def test_adjacent_one_hour_slots_do_not_conflict(self):
        first = self.create_booking()
        self.assertEqual(first.status_code, 201)

        adjacent_start = self.start_datetime + timedelta(hours=1)
        adjacent = self.create_booking(
            start_datetime=adjacent_start.isoformat(),
            end_datetime=(adjacent_start + timedelta(hours=1)).isoformat(),
        )

        self.assertEqual(adjacent.status_code, 201)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CONFIRMED).count(), 2)

    def test_invalid_slot_duration_is_rejected(self):
        response = self.create_booking(
            end_datetime=(self.start_datetime + timedelta(hours=2)).isoformat(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Booking.objects.count(), 0)

    def test_booking_start_must_align_to_a_local_whole_hour(self):
        unaligned_start = self.start_datetime.replace(minute=30)
        response = self.create_booking(
            start_datetime=unaligned_start.isoformat(),
            end_datetime=(unaligned_start + timedelta(hours=1)).isoformat(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Booking.objects.count(), 0)

    def test_booking_start_must_be_in_the_future(self):
        past_start = (
            timezone.localtime()
            .replace(minute=0, second=0, microsecond=0)
            - timedelta(hours=2)
        )
        response = self.create_booking(
            start_datetime=past_start.isoformat(),
            end_datetime=(past_start + timedelta(hours=1)).isoformat(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Booking.objects.count(), 0)

    def test_booking_cannot_cross_local_midnight(self):
        next_day = timezone.localdate() + timedelta(days=1)
        midnight = timezone.make_aware(datetime.combine(next_day, time.min))
        overnight_start = midnight - timedelta(hours=1)
        response = self.create_booking(
            start_datetime=overnight_start.isoformat(),
            end_datetime=midnight.isoformat(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Booking.objects.count(), 0)

    def test_booking_outside_resource_specific_sport_schedule_is_rejected(self):
        SportSchedule.objects.create(
            facility_sport=self.facility_sport,
            resource=self.resource,
            day_of_week=self.start_datetime.weekday(),
            start_time=time(11),
            end_time=time(12),
        )

        response = self.create_booking()

        self.assertEqual(response.status_code, 400)
        self.assertIn('outside the sport schedule', str(response.data))
        self.assertEqual(Booking.objects.count(), 0)

    def test_booking_respects_schedule_effective_date_bounds(self):
        self.sport_schedule.effective_from = self.start_datetime.date() + timedelta(days=1)
        self.sport_schedule.save(update_fields=('effective_from',))

        response = self.create_booking()

        self.assertEqual(response.status_code, 400)
        self.assertIn('outside the sport schedule', str(response.data))
        self.assertEqual(Booking.objects.count(), 0)

    def test_booking_overlapping_resource_closure_is_rejected(self):
        FacilityClosure.objects.create(
            facility=self.facility,
            resource=self.resource,
            start_datetime=self.start_datetime + timedelta(minutes=30),
            end_datetime=self.start_datetime + timedelta(hours=1),
            reason='Scheduled maintenance',
        )

        response = self.create_booking()

        self.assertEqual(response.status_code, 400)
        self.assertIn('closure', str(response.data))
        self.assertEqual(Booking.objects.count(), 0)

    def test_mid_hour_closure_blocks_overlapping_hour_and_frees_the_next_hour(self):
        closure_start = timezone.make_aware(
            datetime.combine(self.start_datetime.date(), time(13, 36))
        )
        closure_end = timezone.make_aware(
            datetime.combine(self.start_datetime.date(), time(17, 35))
        )
        FacilityClosure.objects.create(
            facility=self.facility,
            start_datetime=closure_start,
            end_datetime=closure_end,
            reason='Mid-hour maintenance',
        )
        blocked_start = timezone.make_aware(
            datetime.combine(self.start_datetime.date(), time(17))
        )
        blocked_response = self.create_booking(
            start_datetime=blocked_start.isoformat(),
            end_datetime=(blocked_start + timedelta(hours=1)).isoformat(),
        )
        free_start = timezone.make_aware(
            datetime.combine(self.start_datetime.date(), time(18))
        )
        free_response = self.create_booking(
            start_datetime=free_start.isoformat(),
            end_datetime=(free_start + timedelta(hours=1)).isoformat(),
        )

        self.assertEqual(blocked_response.status_code, 400)
        self.assertIn('closure', str(blocked_response.data).lower())
        self.assertEqual(free_response.status_code, 201)

    def test_resource_must_be_configured_for_requested_sport(self):
        other_sport = Sport.objects.create(name='Volleyball', slug='volleyball')
        FacilitySport.objects.create(
            facility=self.facility,
            sport=other_sport,
            hourly_rate='200.00',
        )

        response = self.create_booking(sport_id=other_sport.pk)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Booking.objects.count(), 0)

    def test_user_can_cancel_own_booking_but_not_another_users(self):
        response = self.create_booking()
        booking_id = response.data['id']

        self.assertEqual(response.status_code, 201)
        cancel_response = self.client.post(
            f'/api/bookings/{booking_id}/cancel/',
            {},
            format='json',
        )
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.data['status'], Booking.Status.CANCELLED)
        self.assertIsNotNone(cancel_response.data['cancelled_at'])

        another_booking = Booking.objects.create(
            user=self.other_user,
            resource=self.resource,
            sport=self.sport,
            start_datetime=self.start_datetime + timedelta(hours=1),
            end_datetime=self.start_datetime + timedelta(hours=2),
            participant_count=2,
            rate_snapshot='250.00',
            total_price='250.00',
        )
        forbidden_response = self.client.post(
            f'/api/bookings/{another_booking.pk}/cancel/',
            {},
            format='json',
        )
        self.assertEqual(forbidden_response.status_code, 404)
        another_booking.refresh_from_db()
        self.assertEqual(another_booking.status, Booking.Status.CONFIRMED)

    def test_booking_list_only_returns_authenticated_users_bookings(self):
        own_booking = Booking.objects.create(
            user=self.user,
            resource=self.resource,
            sport=self.sport,
            start_datetime=self.start_datetime,
            end_datetime=self.start_datetime + timedelta(hours=1),
            participant_count=2,
            rate_snapshot='250.00',
            total_price='250.00',
        )
        Booking.objects.create(
            user=self.other_user,
            resource=self.resource,
            sport=self.sport,
            start_datetime=self.start_datetime + timedelta(hours=1),
            end_datetime=self.start_datetime + timedelta(hours=2),
            participant_count=2,
            rate_snapshot='250.00',
            total_price='250.00',
        )

        response = self.client.get('/api/bookings/my/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data], [own_booking.pk])

    def test_booking_endpoints_require_authentication(self):
        client = APIClient()

        create_response = client.post(
            '/api/bookings/',
            self.booking_payload(),
            format='json',
        )
        list_response = client.get('/api/bookings/my/')

        self.assertIn(create_response.status_code, (401, 403))
        self.assertIn(list_response.status_code, (401, 403))

    def test_concurrent_requests_for_same_slot_create_only_one_booking(self):
        barrier = Barrier(2)
        payload = self.booking_payload()

        def submit_booking():
            connections.close_all()
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                client = APIClient()
                client.force_authenticate(user=user)
                barrier.wait(timeout=10)
                response = client.post('/api/bookings/', payload, format='json')
                return response.status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: submit_booking(), range(2)))

        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CONFIRMED).count(), 1)
