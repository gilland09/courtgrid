import importlib
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase, override_settings
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
