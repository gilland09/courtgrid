import importlib
import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.db import connection, transaction
from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from facilities.availability import active_resource_offerings, evaluate_serial_slots
from facilities.availability_client import serialize_availability_request
from facilities.models import (
    BookableResource, Facility, FacilityOperatingHours, FacilityPaymentMethod,
    FacilitySport, ResourceSport, Sport, SportSchedule,
)
from facilities.test_management_portals import _png_image, assert_rendered_scripts_parse

from .models import Booking, UserProfile


class PrivateMediaTests(SimpleTestCase):
    def test_registration_inline_scripts_parse(self):
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        assert_rendered_scripts_parse(self, response.content.decode())

    def test_media_route_blocks_private_receipts_even_in_public_media_root(self):
        with TemporaryDirectory() as media_directory:
            root = Path(media_directory)
            private_root = root / 'private_receipts'
            private_root.mkdir()
            (private_root / 'receipt.pdf').write_bytes(b'%PDF-1.4 example')
            (root / 'public.txt').write_text('public', encoding='utf-8')
            with override_settings(MEDIA_ROOT=root, PRIVATE_RECEIPT_ROOT=private_root):
                visitor = Client()
                for debug in (True, False):
                    with override_settings(DEBUG=debug, SECURE_SSL_REDIRECT=False):
                        self.assertEqual(visitor.get('/media/private_receipts/receipt.pdf').status_code, 404)
                        public_response = visitor.get('/media/public.txt')
                        self.assertEqual(public_response.status_code, 200)
                        self.assertEqual(b''.join(public_response.streaming_content), b'public')
                        public_response.close()


class EmailCommitTests(TransactionTestCase):
    @override_settings(BREVO_API_KEY='test-key')
    def test_delivery_timeout_does_not_roll_back_confirmation(self):
        users = get_user_model()
        customer = users.objects.create_user(username='email-customer', email='player@example.com')
        owner = users.objects.create_user(username='email-owner')
        UserProfile.objects.create(user=owner, role=UserProfile.Role.COURT_OWNER)
        facility = Facility.objects.create(name='Venue', owner=owner)
        resource = BookableResource.objects.create(facility=facility, name='Court')
        sport = Sport.objects.create(name='Basketball', slug='basketball')
        start = timezone.now() + timedelta(days=1)
        booking = Booking.objects.create(
            user=customer, resource=resource, sport=sport, start_datetime=start,
            end_datetime=start + timedelta(hours=1), participant_count=1,
            status=Booking.Status.PENDING_VERIFICATION, rate_snapshot='200.00',
        )
        self.client.force_login(owner)
        with patch('bookings.email_service.request.urlopen', side_effect=TimeoutError('timeout')):
            with self.assertLogs('bookings.email_service', level='ERROR'):
                response = self.client.post(reverse('owner_confirm_payment', args=[booking.pk]), follow=True)
        booking.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertContains(response, 'Email delivery failed. Please contact the customer directly.')


class PaymentFirstTests(TestCase):
    def setUp(self):
        private_dir = TemporaryDirectory()
        self.addCleanup(private_dir.cleanup)
        override = override_settings(PRIVATE_RECEIPT_ROOT=private_dir.name)
        override.enable()
        self.addCleanup(override.disable)
        users = get_user_model()
        self.user = users.objects.create_user(username='player')
        self.other = users.objects.create_user(username='other')
        self.owner = users.objects.create_user(username='owner')
        self.other_owner = users.objects.create_user(username='other-owner')
        self.admin = users.objects.create_superuser(username='admin', password='password')
        UserProfile.objects.create(user=self.owner, role=UserProfile.Role.COURT_OWNER)
        self.facility = Facility.objects.create(
            name='Venue', owner=self.owner, is_verified=True,
            verification_status=Facility.VerificationStatus.VERIFIED,
        )
        self.method = FacilityPaymentMethod.objects.create(
            facility=self.facility, label='GCash', account_name='Owner',
            account_number='1234567',
        )
        self.sport = Sport.objects.create(name='Basketball', slug='basketball')
        offering = FacilitySport.objects.create(
            facility=self.facility, sport=self.sport, hourly_rate='200.00',
        )
        self.courts = [
            BookableResource.objects.create(facility=self.facility, name=f'Court {index}')
            for index in (1, 2)
        ]
        for court in self.courts:
            ResourceSport.objects.create(resource=court, facility_sport=offering)
        self.start = timezone.make_aware(datetime.combine(
            timezone.localdate() + timedelta(days=1), time(10),
        ))
        FacilityOperatingHours.objects.create(
            facility=self.facility, day_of_week=self.start.weekday(),
            start_time=time(8), end_time=time(15),
        )
        SportSchedule.objects.create(
            facility_sport=offering, day_of_week=self.start.weekday(),
            start_time=time(8), end_time=time(15),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def payload(self, **overrides):
        payload = {
            'booking_type': 'player',
            'payment_method_used': str(self.method.pk),
            'policy_accepted': 'true',
            'payment_receipt': SimpleUploadedFile('receipt.pdf', b'%PDF-1.4 example'),
            'resource_id': str(self.courts[0].pk),
            'sport_id': str(self.sport.pk),
            'participant_count': '2',
            'start_datetime': self.start.isoformat(),
            'end_datetime': (self.start + timedelta(hours=1)).isoformat(),
        }
        payload.update(overrides)
        return payload

    def submit(self, **overrides):
        return self.client.post('/api/bookings/', self.payload(**overrides), format='multipart')

    def test_receipt_policy_and_method_are_mandatory(self):
        cases = (
            {'payment_receipt': None},
            {'payment_receipt': SimpleUploadedFile('fake.png', b'not png')},
            {'payment_receipt': SimpleUploadedFile('fake.pdf', b'not pdf')},
            {'payment_receipt': SimpleUploadedFile('huge.pdf', b'%PDF-' + b'x' * (5 * 1024 * 1024))},
            {'policy_accepted': 'false'},
            {'payment_method_used': '999999'},
        )
        for override in cases:
            with self.subTest(override=list(override)):
                data = self.payload(**override)
                if data['payment_receipt'] is None:
                    del data['payment_receipt']
                response = self.client.post('/api/bookings/', data, format='multipart')
                self.assertEqual(response.status_code, 400, response.data)
                self.assertFalse(Booking.objects.exists())
        self.method.is_active = False
        self.method.save(update_fields=('is_active',))
        self.assertEqual(self.submit().status_code, 400)
        self.assertFalse(Booking.objects.exists())
        data = self.payload()
        del data['policy_accepted']
        self.assertEqual(self.client.post('/api/bookings/', data, format='multipart').status_code, 400)
        self.assertFalse(Booking.objects.exists())

    def test_valid_signatures_hold_slots_and_snapshot_method(self):
        for index, (name, body) in enumerate((
            ('proof.jpg', b'\xff\xd8\xffabc'),
            ('proof.png', b'\x89PNG\r\n\x1a\nabc'),
            ('proof.pdf', b'%PDF-1.4 abc'),
        )):
            start = self.start + timedelta(hours=index)
            response = self.submit(
                start_datetime=start.isoformat(),
                end_datetime=(start + timedelta(hours=1)).isoformat(),
                payment_receipt=SimpleUploadedFile(name, body),
            )
            self.assertEqual(response.status_code, 201, response.data)
            booking = Booking.objects.get(pk=response.data['id'])
            self.assertEqual(booking.status, Booking.Status.PENDING_VERIFICATION)
            self.assertEqual(booking.payment_method_label, 'GCash')
            self.assertEqual(booking.payment_account_number, '1234567')
            self.assertTrue(booking.policy_accepted)
            self.assertIsNotNone(booking.payment_receipt_uploaded_at)
            self.assertEqual(booking.payment_receipt.read(), body)
            booking.payment_receipt.close()
        conflict = self.submit()
        self.assertEqual(conflict.status_code, 409)

    def test_player_and_organizer_rules_and_atomic_conflict(self):
        slots = [{
            'resource_id': court.pk,
            'start_datetime': self.start.isoformat(),
            'end_datetime': (self.start + timedelta(hours=1)).isoformat(),
        } for court in self.courts]
        batch = {
            'slots': json.dumps(slots), 'contact_email': 'player@example.com',
            'contact_phone': '+639171234567',
        }
        player = self.submit(**batch)
        self.assertEqual(player.status_code, 400)
        missing = self.submit(booking_type='organizer', **batch)
        self.assertEqual(missing.status_code, 400)
        organizer = {
            'booking_type': 'organizer', 'organization_name': 'Club',
            'event_name': 'Games', 'expected_participants': '8',
        }
        self.assertEqual(self.submit(**organizer, **batch).status_code, 201)
        self.assertEqual(Booking.objects.count(), 2)
        self.assertTrue(all(b.status == Booking.Status.PENDING_VERIFICATION for b in Booking.objects.all()))
        listed = self.client.get(reverse('my-booking-list')).data
        self.assertEqual(len(listed), 2)
        for booking in listed:
            self.assertEqual(booking['booking_type'], 'organizer')
            self.assertEqual(booking['organization_name'], 'Club')
            self.assertEqual(booking['event_name'], 'Games')
            self.assertEqual(booking['status'], Booking.Status.PENDING_VERIFICATION)
            self.assertEqual(
                booking['payment_receipt_url'],
                reverse('booking-receipt', kwargs={'booking_id': booking['id']}),
            )
        conflict = self.submit(**organizer, **batch)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(Booking.objects.count(), 2)

    def test_exact_five_megabyte_receipt_is_accepted(self):
        body = b'%PDF-' + b'x' * (5 * 1024 * 1024 - 5)
        response = self.submit(payment_receipt=SimpleUploadedFile('receipt.pdf', body))
        self.assertEqual(response.status_code, 201, response.data)

    def test_stale_checkout_total_does_not_create_bookings_or_save_receipt(self):
        response = self.submit(expected_total='199.00')
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Booking.objects.exists())
        self.assertFalse(list(Path(settings.PRIVATE_RECEIPT_ROOT).rglob('*')))

    def test_customer_pages_render_phase_two_controls_and_inline_scripts(self):
        self.facility.name = "Tonio's Dink District"
        self.facility.save(update_fields=('name',))
        self.client.force_login(self.user)
        home = self.client.get(reverse('home'))
        self.assertContains(home, 'How are you booking today?')
        self.assertContains(home, 'Players can only book 1 court per reservation.')
        self.assertContains(home, 'Clubs and organizers can book multiple courts at once.')
        assert_rendered_scripts_parse(self, home.content.decode())
        for mode in ('player', 'organizer'):
            detail = self.client.get(
                reverse('facility-detail-page', kwargs={'pk': self.facility.pk}),
                {'mode': mode},
            )
            for content in (
                'Tonio&#x27;s Dink District', 'organization-name', 'event-name',
                'expected-participants', 'range-start', 'range-end', 'range-courts',
                "Choose How You'll Pay", 'GCash', 'payment-receipt',
                'policy-accepted', 'id="confirm-booking"', 'disabled',
            ):
                self.assertContains(detail, content)
            html = detail.content.decode()
            self.assertLess(html.index('id="booking-modal"'), html.index('js/availability.js'))
            assert_rendered_scripts_parse(self, html)
        for user, route in (
            (self.user, 'my_bookings'),
            (self.owner, 'owner_dashboard'),
            (self.admin, 'admin_dashboard'),
        ):
            self.client.force_login(user)
            page = self.client.get(reverse(route))
            self.assertEqual(page.status_code, 200)
            assert_rendered_scripts_parse(self, page.content.decode())

    def test_receipt_permissions_and_no_public_media_url(self):
        response = self.submit()
        booking = Booking.objects.get(pk=response.data['id'])
        url = reverse('booking-receipt', kwargs={'booking_id': booking.pk})
        for user in (self.user, self.owner, self.admin):
            self.client.force_login(user)
            result = self.client.get(url)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result['Content-Type'], 'application/pdf')
            self.assertEqual(result['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(b''.join(result.streaming_content), b'%PDF-1.4 example')
        for user in (self.other, self.other_owner):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get('/media/' + booking.payment_receipt.name).status_code, 404)
        booking.payment_receipt = None
        booking.save(update_fields=('payment_receipt',))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_holds_are_in_serial_and_compute_payload_and_excluded_from_totals(self):
        self.submit()
        booking = Booking.objects.get()
        slots = evaluate_serial_slots(active_resource_offerings(facility_id=self.facility.pk), self.start.date())
        held = next(slot for slot in slots if slot['resource_id'] == self.courts[0].pk and slot['start_datetime'] == self.start)
        self.assertEqual(held['availability'], 'booked')
        payload = serialize_availability_request(self.start.date(), [], [], [], [booking])
        self.assertEqual(payload['existing_bookings'][0]['resource_id'], self.courts[0].pk)
        self.client.force_login(self.owner)
        dashboard = self.client.get(reverse('owner_dashboard'))
        self.assertEqual(dashboard.context['financial_totals']['gross'], 0)
        self.client.force_login(self.admin)
        dashboard = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(dashboard.context['financial_totals']['gross'], 0)
        self.client.force_login(self.owner)
        self.client.post(reverse('owner_dashboard'), {'action': 'verify_payment', 'booking_id': booking.pk})
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PAID)
        dashboard = self.client.get(reverse('owner_dashboard'))
        self.assertEqual(dashboard.context['financial_totals']['gross'], 200)
        self.assertEqual(dashboard.context['financial_totals']['owner_payout'], 190)
        self.assertEqual(dashboard.context['financial_totals']['platform_fee'], 10)

    @override_settings(BREVO_API_KEY='', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_owner_confirms_organizer_and_sends_post_commit_email(self):
        self.user.email = 'registered@example.com'
        self.user.save(update_fields=('email',))
        self.facility.name = "Tonio's Dink District"
        self.facility.address = 'Naval'
        self.facility.save(update_fields=('name', 'address'))
        response = self.submit(
            booking_type='organizer', organization_name='Club & Co',
            event_name='Games', expected_participants='8', contact_email='other@example.com',
        )
        booking = Booking.objects.get(pk=response.data['id'])
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(reverse('owner_confirm_payment', args=[booking.pk]))
            self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(callbacks), 1)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertEqual(booking.payment_verified_by, self.owner)
        self.assertEqual(mail.outbox[0].to, ['registered@example.com'])
        for expected in (booking.payment_reference, "Tonio's Dink District", 'Court 1',
                         '10:00 AM', 'Club & Co', 'Games', '8', '₱200.00'):
            self.assertIn(expected, mail.outbox[0].body)
        self.assertIn('Club &amp; Co', mail.outbox[0].alternatives[0].content)
        dashboard = self.client.get(reverse('owner_dashboard'))
        self.assertEqual(dashboard.context['financial_totals']['gross'], 200)
        self.assertEqual(dashboard.context['financial_totals']['owner_payout'], 190)
        self.assertEqual(dashboard.context['financial_totals']['platform_fee'], 10)

    @override_settings(BREVO_API_KEY='', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_rejection_releases_hold_and_notifies_customer(self):
        self.user.email = 'player@example.com'
        self.user.save(update_fields=('email',))
        response = self.submit()
        booking = Booking.objects.get(pk=response.data['id'])
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('owner_reject_receipt', args=[booking.pk]),
                                        {'rejection_reason': '  Unreadable receipt  '})
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual(booking.cancellation_reason, 'Unreadable receipt')
        self.assertIn('Unreadable receipt', mail.outbox[0].body)
        self.assertIn('released', mail.outbox[0].body)
        slots = evaluate_serial_slots(active_resource_offerings(facility_id=self.facility.pk), self.start.date())
        slot = next(item for item in slots if item['resource_id'] == self.courts[0].pk and item['start_datetime'] == self.start)
        self.assertEqual(slot['availability'], 'available')
        dashboard = self.client.get(reverse('owner_dashboard'))
        self.assertEqual(dashboard.context['financial_totals']['gross'], 0)

        def fake_compute(target_date, facilities, closures, schedules, existing_bookings):
            self.assertFalse(existing_bookings)
            serial = evaluate_serial_slots(active_resource_offerings(facility_id=self.facility.pk), target_date)
            values = [{**item, 'start_datetime': item['start_datetime'].isoformat(),
                       'end_datetime': item['end_datetime'].isoformat()} for item in serial]
            return {'slots': values, 'available_slots': [s for s in values if s['availability'] == 'available'],
                    'parallel_elapsed_time': 0}

        with patch('facilities.views.fetch_parallel_availability', side_effect=fake_compute):
            result = self.client.get('/api/availability/search', {
                'mode': 'parallel', 'facility': self.facility.pk,
                'sport': self.sport.pk, 'date': self.start.date().isoformat(),
            })
        self.assertEqual(result.status_code, 200)
        self.assertTrue(any(item['resource_id'] == self.courts[0].pk
                            and item['start_datetime'] == self.start
                            and item['availability'] == 'available' for item in result.data['slots']))

    def test_review_authorization_method_and_reason_validation(self):
        booking = Booking.objects.get(pk=self.submit().data['id'])
        confirm = reverse('owner_confirm_payment', args=[booking.pk])
        reject = reverse('owner_reject_receipt', args=[booking.pk])
        for user in (self.other, self.other_owner):
            self.client.force_login(user)
            self.assertEqual(self.client.post(confirm).status_code, 404)
            self.assertEqual(self.client.post(reject, {'rejection_reason': 'No'}).status_code, 404)
        staff = get_user_model().objects.create_user(username='other-staff', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(reverse('admin_dashboard'), {
            'action': 'verify_payment', 'booking_id': booking.pk,
        }).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(confirm).status_code, 405)
        self.assertEqual(self.client.get(reject).status_code, 405)
        self.client.post(reject, {'rejection_reason': '   '})
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.PENDING_VERIFICATION)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(confirm).status_code, 403)
        self.assertEqual(csrf.post(reject, {'rejection_reason': 'No'}).status_code, 403)

    @override_settings(BREVO_API_KEY='', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_shared_checkout_is_confirmed_together_with_one_email(self):
        self.user.email = 'player@example.com'
        self.user.save(update_fields=('email',))
        batch = [{
            'resource_id': court.pk, 'start_datetime': self.start.isoformat(),
            'end_datetime': (self.start + timedelta(hours=1)).isoformat(),
        } for court in self.courts]
        response = self.submit(
            booking_type='organizer', organization_name='Club', event_name='Games',
            expected_participants='8', slots=json.dumps(batch),
            contact_email='player@example.com', contact_phone='+639171234567',
        )
        self.assertEqual(response.status_code, 201)
        first, second = list(Booking.objects.order_by('pk'))
        self.assertEqual(first.payment_receipt.name, second.payment_receipt.name)
        self.assertTrue(first.checkout_batch_id)
        self.assertEqual(first.checkout_batch_id, second.checkout_batch_id)
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('owner_confirm_payment', args=[first.pk]))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, Booking.Status.CONFIRMED)
        self.assertEqual(second.status, Booking.Status.CONFIRMED)
        self.client.post(reverse('owner_reject_receipt', args=[first.pk]), {'rejection_reason': 'No'})
        first.refresh_from_db()
        self.assertEqual(first.status, Booking.Status.CONFIRMED)
        second.refresh_from_db()
        self.assertEqual(second.status, Booking.Status.CONFIRMED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(first.payment_reference, mail.outbox[0].body)
        self.assertIn(second.payment_reference, mail.outbox[0].body)
        self.assertIn('₱400.00', mail.outbox[0].body)

    def create_three_slot_checkout(self):
        slots = [{
            'resource_id': self.courts[0].pk,
            'start_datetime': (self.start + timedelta(hours=index)).isoformat(),
            'end_datetime': (self.start + timedelta(hours=index + 1)).isoformat(),
        } for index in range(3)]
        response = self.submit(
            slots=json.dumps(slots), contact_email='player@example.com',
            contact_phone='+639171234567',
        )
        self.assertEqual(response.status_code, 201, response.data)
        ids = [item['id'] for item in response.data['results']]
        return list(Booking.objects.filter(pk__in=ids).order_by('pk'))

    @override_settings(BREVO_API_KEY='', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_three_slot_ajax_confirmation_groups_email_and_financials(self):
        self.start = self.start.replace(hour=18)
        FacilityOperatingHours.objects.filter(facility=self.facility).update(end_time=time(22))
        SportSchedule.objects.filter(facility_sport__facility=self.facility).update(end_time=time(22))
        bookings = self.create_three_slot_checkout()
        self.assertEqual(len({booking.checkout_batch_id for booking in bookings}), 1)
        self.assertTrue(bookings[0].checkout_batch_id)
        self.assertEqual(len({booking.payment_reference for booking in bookings}), 3)
        self.client.force_login(self.owner)
        dashboard = self.client.get(reverse('owner_dashboard'))
        self.assertEqual(len(dashboard.context['booking_batches']), 1)
        self.assertContains(dashboard, '3 slots')
        self.assertContains(dashboard, '6:00 PM')
        self.assertContains(dashboard, '9:00 PM')
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                reverse('owner_confirm_payment', args=[bookings[-1].pk]),
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CONFIRMED, payment_status='paid').count(), 3)
        self.assertEqual(response.json()['batch']['total'], '600.00')
        self.assertEqual(Decimal(response.json()['kpis']['gross']), Decimal('600.00'))
        self.assertEqual(Decimal(response.json()['kpis']['platform_fee']), Decimal('30.00'))
        self.assertEqual(Decimal(response.json()['kpis']['owner_payout']), Decimal('570.00'))
        self.assertEqual(response.json()['pending_count'], 0)
        self.assertEqual(len(mail.outbox), 1)
        for expected in ('6:00 PM', '9:00 PM', '₱600.00', bookings[0].checkout_batch_id,
                         *(booking.payment_reference for booking in bookings)):
            self.assertIn(expected, mail.outbox[0].body)
        self.assertNotIn('Each reservation reference is confirmed separately.', mail.outbox[0].body)

    @override_settings(BREVO_API_KEY='', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_ajax_rejection_releases_entire_checkout(self):
        bookings = self.create_three_slot_checkout()
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                reverse('owner_reject_receipt', args=[bookings[1].pk]),
                {'rejection_reason': 'Unreadable'}, HTTP_ACCEPT='application/json',
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CANCELLED, cancellation_reason='Unreadable').count(), 3)
        self.assertEqual(response.json()['kpis']['gross'], '0')
        slots = evaluate_serial_slots(active_resource_offerings(facility_id=self.facility.pk), self.start.date())
        released = [slot for slot in slots if slot['resource_id'] == self.courts[0].pk
                    and self.start <= slot['start_datetime'] < self.start + timedelta(hours=3)]
        self.assertEqual(len(released), 3)
        self.assertTrue(all(slot['availability'] == 'available' for slot in released))
        active = Booking.objects.filter(status__in=(Booking.Status.CONFIRMED, Booking.Status.PENDING_VERIFICATION))
        payload = serialize_availability_request(self.start.date(), [], [], [], active)
        self.assertEqual(payload['existing_bookings'], [])

    @override_settings(BREVO_API_KEY='', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_regular_rejection_releases_entire_checkout(self):
        bookings = self.create_three_slot_checkout()
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('owner_reject_receipt', args=[bookings[0].pk]),
                                        {'rejection_reason': 'Not legible'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CANCELLED).count(), 3)
        self.assertEqual(len(mail.outbox), 1)

    def test_confirmation_rolls_back_all_slots_if_one_save_fails(self):
        bookings = self.create_three_slot_checkout()
        self.client.force_login(self.owner)
        save = Booking.save

        def fail_second(instance, *args, **kwargs):
            if instance.pk == bookings[1].pk:
                raise RuntimeError('simulated write failure')
            return save(instance, *args, **kwargs)

        with patch.object(Booking, 'save', autospec=True, side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'simulated write failure'):
                self.client.post(reverse('owner_confirm_payment', args=[bookings[0].pk]))
        self.assertEqual(Booking.objects.filter(status=Booking.Status.PENDING_VERIFICATION).count(), 3)

    def test_batch_cancellation_owner_and_admin_regular_and_ajax(self):
        for actor, endpoint, ajax in (
            (self.owner, 'owner_cancel_booking', False),
            (self.owner, 'owner_cancel_booking', True),
            (self.admin, 'admin_cancel_booking', False),
            (self.admin, 'admin_cancel_booking', True),
        ):
            with self.subTest(endpoint=endpoint, ajax=ajax):
                bookings = self.create_three_slot_checkout()
                self.client.force_login(actor)
                response = self.client.post(
                    reverse(endpoint, args=[bookings[1].pk]),
                    {'cancellation_reason': 'Closed'},
                    **({'HTTP_ACCEPT': 'application/json'} if ajax else {}),
                )
                self.assertEqual(response.status_code, 200 if ajax else 302)
                self.assertEqual(Booking.objects.filter(pk__in=[b.pk for b in bookings], status='CANCELLED').count(), 3)
                if ajax:
                    self.assertTrue(response.json()['success'])
                    self.assertEqual(len(response.json()['batch']['booking_ids']), 3)
                self.client.force_authenticate(self.user)

    @override_settings(BREVO_API_KEY='', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_owner_cancellation_sends_one_batch_email(self):
        bookings = self.create_three_slot_checkout()
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(reverse('owner_cancel_booking', args=[bookings[0].pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('₱600.00', mail.outbox[0].body)
        for booking in bookings:
            self.assertIn(booking.payment_reference, mail.outbox[0].body)

    def test_legacy_and_cross_customer_batches_stay_isolated(self):
        common = dict(resource=self.courts[0], sport=self.sport, start_datetime=self.start,
                      end_datetime=self.start + timedelta(hours=1), participant_count=1,
                      status=Booking.Status.PENDING_VERIFICATION, rate_snapshot='200.00')
        legacy = Booking.objects.create(user=self.user, **common)
        other_legacy = Booking.objects.create(user=self.user, **common)
        first = Booking.objects.create(user=self.user, checkout_batch_id='CGB-test', **common)
        second = Booking.objects.create(user=self.other, checkout_batch_id='CGB-test', **common)
        self.client.force_login(self.owner)
        self.client.post(reverse('owner_confirm_payment', args=[legacy.pk]))
        self.client.post(reverse('owner_confirm_payment', args=[first.pk]))
        for item, expected in ((legacy, Booking.Status.CONFIRMED), (other_legacy, Booking.Status.PENDING_VERIFICATION),
                               (first, Booking.Status.CONFIRMED), (second, Booking.Status.PENDING_VERIFICATION)):
            item.refresh_from_db()
            self.assertEqual(item.status, expected)

    def test_started_batch_cancellation_is_all_or_nothing(self):
        bookings = self.create_three_slot_checkout()
        Booking.objects.filter(pk=bookings[0].pk).update(
            start_datetime=timezone.now() - timedelta(hours=2),
            end_datetime=timezone.now() - timedelta(hours=1),
        )
        self.client.force_login(self.owner)
        response = self.client.post(reverse('owner_cancel_booking', args=[bookings[1].pk]),
                                    HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.PENDING_VERIFICATION).count(), 3)

    def test_customer_cancels_all_active_slots_in_checkout(self):
        bookings = self.create_three_slot_checkout()
        response = self.client.post(reverse('booking-cancel', args=[bookings[1].pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], bookings[1].pk)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CANCELLED, cancellation_reason='Cancelled by customer').count(), 3)

    def test_mixed_batch_only_reviews_pending_slots(self):
        bookings = self.create_three_slot_checkout()
        Booking.objects.filter(pk=bookings[0].pk).update(status=Booking.Status.CANCELLED)
        self.client.force_login(self.owner)
        page = self.client.get(reverse('owner_dashboard'))
        self.assertContains(page, 'Mixed booking statuses')
        response = self.client.post(
            reverse('owner_confirm_payment', args=[bookings[1].pk]),
            HTTP_ACCEPT='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['batch']['status'], 'MIXED')
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CONFIRMED).count(), 2)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CANCELLED).count(), 1)

    def test_ajax_mutations_reject_other_tenants_and_non_post(self):
        booking = self.create_three_slot_checkout()[0]
        endpoints = ('owner_confirm_payment', 'owner_reject_receipt', 'owner_cancel_booking')
        self.client.force_login(self.other_owner)
        for endpoint in endpoints:
            url = reverse(endpoint, args=[booking.pk])
            response = self.client.post(url, {'rejection_reason': 'No'}, HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code, 404)
            self.assertFalse(response.json()['success'])
            self.assertEqual(self.client.get(url, HTTP_ACCEPT='application/json').status_code, 405)
        url = reverse('admin_cancel_booking', args=[booking.pk])
        self.assertEqual(self.client.post(url, HTTP_ACCEPT='application/json').status_code, 403)
        self.assertEqual(self.client.get(url, HTTP_ACCEPT='application/json').status_code, 405)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.PENDING_VERIFICATION).count(), 3)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        self.assertEqual(csrf.post(reverse('owner_cancel_booking', args=[booking.pk])).status_code, 403)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(url).status_code, 403)

    def test_flash_message_is_rendered_once_in_toast_stack(self):
        booking = self.create_three_slot_checkout()[0]
        self.client.force_login(self.owner)
        self.client.post(reverse('owner_reject_receipt', args=[booking.pk]), {'rejection_reason': ''})
        page = self.client.get(reverse('owner_dashboard'))
        self.assertContains(page, 'id="cg-toast-stack"', count=1)
        self.assertContains(page, 'Provide a rejection reason of at most 180 characters.', count=1)

    @override_settings(BREVO_API_KEY='test-key', BREVO_SENDER_EMAIL='sender@example.com',
                       BREVO_SENDER_NAME='CourtGrid')
    def test_brevo_payload_is_sent_over_https(self):
        self.user.email = 'player@example.com'
        self.user.save(update_fields=('email',))
        booking = Booking.objects.get(pk=self.submit().data['id'])
        self.client.force_login(self.owner)
        with patch('bookings.email_service.request.urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.status = 201
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(reverse('owner_confirm_payment', args=[booking.pk]))
        req = urlopen.call_args.args[0]
        payload = json.loads(req.data)
        self.assertEqual(req.full_url, 'https://api.brevo.com/v3/smtp/email')
        self.assertEqual(req.get_header('Api-key'), 'test-key')
        self.assertEqual(urlopen.call_args.kwargs['timeout'], 10)
        self.assertEqual(payload['sender'], {'email': 'sender@example.com', 'name': 'CourtGrid'})
        self.assertEqual(payload['to'], [{'email': 'player@example.com'}])
        for field in ('subject', 'htmlContent', 'textContent'):
            self.assertIn(booking.payment_reference, payload[field])
        self.assertIn('name="viewport"', payload['htmlContent'])

    @override_settings(BREVO_API_KEY='test-key')
    def test_brevo_http_failure_is_reported_without_reversing_confirmation(self):
        self.user.email = 'player@example.com'
        self.user.save(update_fields=('email',))
        booking = Booking.objects.get(pk=self.submit().data['id'])
        self.client.force_login(self.owner)
        failure = HTTPError('https://api.brevo.com/v3/smtp/email', 500, 'error', {}, None)
        with patch('bookings.email_service.request.urlopen', side_effect=failure):
            with self.assertLogs('bookings.email_service', level='ERROR'):
                with self.captureOnCommitCallbacks(execute=True):
                    self.client.post(reverse('owner_confirm_payment', args=[booking.pk]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PAID)

    def test_rollback_does_not_send_confirmation(self):
        booking = Booking.objects.get(pk=self.submit().data['id'])
        self.client.force_login(self.owner)
        with patch('bookings.views.send_booking_confirmed_email') as send:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                with transaction.atomic():
                    self.client.post(reverse('owner_confirm_payment', args=[booking.pk]))
                    transaction.set_rollback(True)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.PENDING_VERIFICATION)
        self.assertEqual(len(callbacks), 0)
        send.assert_not_called()

    @override_settings(BREVO_API_KEY='')
    def test_missing_email_is_logged_and_reported(self):
        from .email_service import send_booking_confirmed_email

        booking = Booking.objects.get(pk=self.submit().data['id'])
        with self.assertLogs('bookings.email_service', level='WARNING'):
            result = send_booking_confirmed_email(booking)
        self.assertFalse(result['sent'])
        self.assertIn('No customer email', result['reason'])

    @override_settings(BREVO_API_KEY='', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_booking_contact_email_is_used_when_registered_email_is_blank(self):
        from .email_service import send_booking_confirmed_email

        self.user.email = '   '
        self.user.save(update_fields=('email',))
        booking = Booking.objects.get(pk=self.submit(contact_email='contact@example.com').data['id'])
        self.assertTrue(send_booking_confirmed_email(booking)['sent'])
        self.assertEqual(mail.outbox[0].to, ['contact@example.com'])

    def test_review_ui_displays_pending_receipt_and_safe_modals(self):
        self.facility.name = "Tonio's Dink District"
        self.facility.save(update_fields=('name',))
        response = self.submit(booking_type='organizer', organization_name='Club',
                               event_name='Games', expected_participants='8')
        booking = Booking.objects.get(pk=response.data['id'])
        self.client.force_login(self.owner)
        page = self.client.get(reverse('owner_dashboard'))
        for value in ('Tonio&#x27;s Dink District', 'Pending Verification', 'Club',
                      'Games', 'View Receipt', 'Confirm Payment', 'Reject Receipt',
                      'data-receipt-modal', 'data-reject-modal'):
            self.assertContains(page, value)
        assert_rendered_scripts_parse(self, page.content.decode())
        receipt = self.client.get(reverse('booking-receipt', args=[booking.pk]))
        self.assertEqual(receipt['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(b''.join(receipt.streaming_content), b'%PDF-1.4 example')
        self.client.force_login(self.admin)
        page = self.client.get(reverse('admin_dashboard'))
        self.assertContains(page, 'Awaiting Owner Verification')
        self.assertContains(page, 'View Receipt')
        self.assertNotContains(page, '>Cancelled</span>')
        assert_rendered_scripts_parse(self, page.content.decode())

    def test_range_search_reports_held_slots_and_rejects_long_ranges(self):
        self.submit()

        def fake_compute(target_date, facilities, closures, schedules, existing_bookings):
            self.assertTrue(existing_bookings)
            slots = evaluate_serial_slots(active_resource_offerings(facility_id=self.facility.pk), target_date)
            serialized = [{**slot, 'start_datetime': slot['start_datetime'].isoformat(),
                           'end_datetime': slot['end_datetime'].isoformat()} for slot in slots]
            return {'slots': serialized, 'available_slots': [
                slot for slot in serialized if slot['availability'] == 'available'
            ], 'parallel_elapsed_time': 0}

        data = {
            'start_date': self.start.date().isoformat(),
            'end_date': self.start.date().isoformat(),
            'court_ids': [self.courts[0].pk], 'booking_type': 'player',
            'sport': self.sport.slug, 'start_time': '09:00', 'end_time': '11:00',
        }
        with patch('facilities.views.fetch_parallel_availability', side_effect=fake_compute):
            response = self.client.post('/api/availability/range', data, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data['available_slots']), 1)
        self.assertEqual(len(response.data['skipped_slots']), 1)
        self.assertEqual(response.data['skipped_slots'][0]['availability'], 'booked')
        data['end_date'] = (self.start.date() + timedelta(days=14)).isoformat()
        self.assertEqual(self.client.post('/api/availability/range', data, format='json').status_code, 400)

    def test_owner_payment_method_crud_and_tenant_isolation(self):
        url = reverse('owner-manage-payment-methods', kwargs={'facility_id': self.facility.pk})
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(url, {'action': 'toggle', 'method_id': self.method.pk}).status_code, 403)
        self.assertEqual(csrf_client.get(url).status_code, 405)
        self.client.force_login(self.other_owner)
        self.assertEqual(self.client.post(url, {'action': 'delete', 'method_id': self.method.pk}).status_code, 404)
        self.client.force_login(self.owner)
        response = self.client.post(url, {
            'action': 'add', 'label': 'Bank', 'account_name': 'Owner',
            'account_number': '12345', 'display_order': '1',
        }, format='multipart')
        self.assertEqual(response.status_code, 302)
        method = FacilityPaymentMethod.objects.get(label='Bank')
        self.client.post(url, {
            'action': 'save', 'method_id': method.pk,
            f'payment-{method.pk}-label': 'Metrobank',
            f'payment-{method.pk}-account_name': 'Owner',
            f'payment-{method.pk}-account_number': '12345',
            f'payment-{method.pk}-display_order': '2',
        }, format='multipart')
        method.refresh_from_db()
        self.assertEqual(method.label, 'Metrobank')
        self.client.post(url, {'action': 'toggle', 'method_id': method.pk})
        method.refresh_from_db()
        self.assertFalse(method.is_active)
        self.client.post(url, {'action': 'delete', 'method_id': method.pk})
        self.assertFalse(FacilityPaymentMethod.objects.filter(pk=method.pk).exists())

    def test_owner_qr_validation_and_active_discovery_methods(self):
        url = reverse('owner-manage-payment-methods', kwargs={'facility_id': self.facility.pk})
        self.client.force_login(self.owner)
        data = {
            'action': 'add', 'label': 'Bank', 'account_name': 'Owner',
            'account_number': '12345', 'display_order': '1',
            'qr_image': SimpleUploadedFile('fake.png', b'not png'),
        }
        self.client.post(url, data, format='multipart')
        self.assertFalse(FacilityPaymentMethod.objects.filter(label='Bank').exists())
        with TemporaryDirectory() as media_dir, override_settings(MEDIA_ROOT=media_dir):
            data['qr_image'] = SimpleUploadedFile('qr.png', _png_image())
            self.client.post(url, data, format='multipart')
            method = FacilityPaymentMethod.objects.get(label='Bank')
            self.assertTrue(method.qr_image.name.startswith('payment_qrs/'))
            response = self.client.get(f'/api/facilities/{self.facility.pk}/')
            self.assertEqual(len(response.data['payment_methods']), 2)
            method.is_active = False
            method.save(update_fields=('is_active',))
            response = self.client.get(f'/api/facilities/{self.facility.pk}/')
            self.assertEqual([item['label'] for item in response.data['payment_methods']], ['GCash'])

    def test_legacy_payment_migration_is_idempotent(self):
        self.facility.gcash_number = '09171234567'
        self.facility.payment_qr_image = 'owner_qrs/merchant.png'
        self.facility.save(update_fields=('gcash_number', 'payment_qr_image'))
        self.method.delete()
        migration = importlib.import_module('facilities.migrations.0010_migrate_payment_methods')
        with connection.schema_editor() as editor:
            migration.migrate_payment_methods(apps, editor)
            migration.migrate_payment_methods(apps, editor)
        methods = self.facility.payment_methods.filter(label='GCash')
        self.assertEqual(methods.count(), 1)
        self.assertEqual(methods.get().qr_image.name, 'owner_qrs/merchant.png')
