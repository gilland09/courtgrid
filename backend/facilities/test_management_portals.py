import base64
from datetime import time, timedelta
from decimal import Decimal
import importlib
from pathlib import Path
import re
import shutil
import struct
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import zlib

from django.apps import apps
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.test import SimpleTestCase, TestCase

from bookings.models import Booking, UserProfile

from .models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilityPhoto,
    FacilitySport,
    ResourceSport,
    Sport,
)
from .portal_forms import FacilityPhotoForm


def assert_rendered_scripts_parse(test_case, rendered_html):
    node = shutil.which('node')
    if node is None:
        test_case.skipTest('Node is required to validate rendered JavaScript syntax.')
    script_tags = re.findall(
        r'<script([^>]*)>(.*?)</script>',
        rendered_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    scripts = []
    for attributes, content in script_tags:
        if re.search(r'\bsrc\s*=', attributes, flags=re.IGNORECASE):
            continue
        script_type = re.search(
            r'\btype\s*=\s*["\']([^"\']+)["\']',
            attributes,
            flags=re.IGNORECASE,
        )
        if script_type and script_type.group(1).lower() not in {
            'text/javascript',
            'application/javascript',
            'module',
        }:
            continue
        scripts.append(content)
    test_case.assertTrue(scripts)
    with TemporaryDirectory() as directory:
        for index, script in enumerate(scripts):
            script_path = Path(directory) / f'inline-{index}.js'
            script_path.write_text(script, encoding='utf-8')
            result = subprocess.run(
                [node, '--check', str(script_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            test_case.assertEqual(
                result.returncode,
                0,
                msg=f'Inline script {index} failed syntax validation:\n{result.stderr}',
            )


def _png_image():
    def chunk(name, data):
        body = name + data
        return (
            struct.pack('>I', len(data))
            + body
            + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)
        )

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00\x00'))
        + chunk(b'IEND', b'')
    )


def _oversized_png():
    image = _png_image()
    text = b'Comment\0' + b'x' * (5 * 1024 * 1024)
    body = b'tEXt' + text
    chunk = (
        struct.pack('>I', len(text))
        + body
        + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)
    )
    return image[:33] + chunk + image[33:]


class FacilityPhotoValidationTests(SimpleTestCase):
    def photo_form(self, name, content):
        uploaded = SimpleUploadedFile(
            name,
            content,
            content_type='image/jpeg',
        )
        return FacilityPhotoForm(
            data={'category': FacilityPhoto.Category.COURT},
            files={'image': uploaded},
        )

    def test_allowed_formats_are_accepted_and_files_rewound(self):
        jpeg = base64.b64decode(
            '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL'
            'DBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/'
            'wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAAB//EABQQAQAAAAAA'
            'AAAAAAAAAAAAAAD/2gAIAQEAAD8Af3//2Q=='
        )
        webp = base64.b64decode(
            'UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAUAmJaQAA3AA/vz0AAA='
        )
        for name, content in (
            ('court.PNG', _png_image()),
            ('court.jpg', jpeg),
            ('court.jpeg', jpeg),
            ('court.webp', webp),
        ):
            with self.subTest(name=name):
                form = self.photo_form(name, content)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data['image'].read(), content)

    def test_spoofed_mismatched_and_truncated_files_are_rejected(self):
        for name, content in (
            ('court.jpg', b'not an image'),
            ('court.jpeg', b'\xff\xd8\xff'),
            ('court.png', b'\x89PNG\r\n\x1a\n'),
            ('court.webp', b'RIFF\x00\x00\x00\x00WEBP'),
            ('court.jpg', _png_image()),
            ('court.txt', _png_image()),
            ('court.exe', _png_image()),
        ):
            with self.subTest(name=name):
                form = self.photo_form(name, content)
                self.assertFalse(form.is_valid())
                self.assertIn('image', form.errors)

    def test_file_size_limit_is_inclusive(self):
        image = _png_image()
        limit = 5 * 1024 * 1024
        body = b'tEXt' + b'x' * (limit - len(image) - 12)
        chunk = (
            struct.pack('>I', len(body) - 4)
            + body
            + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)
        )
        exactly_limit = image[:33] + chunk + image[33:]
        self.assertEqual(len(exactly_limit), limit)
        form = self.photo_form('court.png', exactly_limit)
        self.assertTrue(form.is_valid(), form.errors)

        form = self.photo_form('court.png', _oversized_png())
        self.assertFalse(form.is_valid())
        self.assertIn('5 MB or smaller', str(form.errors['image']))


class InAppManagementPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(username='portal-owner')
        UserProfile.objects.create(
            user=cls.owner,
            role=UserProfile.Role.COURT_OWNER,
        )
        cls.other_owner = user_model.objects.create_user(username='other-portal-owner')
        UserProfile.objects.create(
            user=cls.other_owner,
            role=UserProfile.Role.COURT_OWNER,
        )
        cls.admin = user_model.objects.create_user(
            username='portal-admin',
            is_staff=True,
        )
        cls.customer = user_model.objects.create_user(username='portal-customer')
        cls.sport = Sport.objects.create(name='Pickleball', slug='portal-pickleball')
        cls.facility = Facility.objects.create(
            name='Owner Test Venue',
            owner=cls.owner,
            capacity=20,
            is_verified=False,
        )
        cls.other_facility = Facility.objects.create(
            name='Other Owner Venue',
            owner=cls.other_owner,
        )
        cls.other_facility_sport = FacilitySport.objects.create(
            facility=cls.other_facility,
            sport=cls.sport,
            hourly_rate='300.00',
        )
        cls.other_resource = BookableResource.objects.create(
            facility=cls.other_facility,
            name='Other Court',
            capacity=12,
        )
        cls.facility_sport = FacilitySport.objects.create(
            facility=cls.facility,
            sport=cls.sport,
            hourly_rate='200.00',
        )
        cls.resource = BookableResource.objects.create(
            facility=cls.facility,
            name='Court 1',
            capacity=20,
        )

    def test_court_owner_can_edit_facility_and_hourly_rate_in_app(self):
        self.client.force_login(self.owner)

        facility_response = self.client.post(
            reverse('owner_dashboard'),
            {
                'action': 'save_facility',
                'facility_id': self.facility.pk,
                'name': 'Updated Owner Venue',
                'barangay': 'Atipolo',
                'address': 'Atipolo, Naval, Biliran',
                'latitude': '11.554500',
                'longitude': '124.402500',
                'capacity': '24',
                'is_active': 'on',
            },
        )
        rate_response = self.client.post(
            reverse('owner_dashboard'),
            {
                'action': 'save_rate',
                'facility_sport_id': self.facility_sport.pk,
                'hourly_rate': '275.00',
                'is_active': 'on',
            },
        )

        self.assertRedirects(facility_response, reverse('owner_dashboard'))
        self.assertRedirects(rate_response, reverse('owner_dashboard'))
        self.facility.refresh_from_db()
        self.facility_sport.refresh_from_db()
        self.assertEqual(self.facility.name, 'Updated Owner Venue')
        self.assertEqual(self.facility.owner, self.owner)
        self.assertEqual(self.facility_sport.hourly_rate, Decimal('275.00'))

        resource_response = self.client.post(
            reverse('owner_dashboard'),
            {
                'action': 'save_resource',
                'facility_id': self.facility.pk,
                'name': 'Court 2',
                'capacity': '16',
                'is_active': 'on',
            },
        )
        hours_response = self.client.post(
            reverse('owner_dashboard'),
            {
                'action': 'save_hours',
                'facility_id': self.facility.pk,
                'day_of_week': '2',
                'start_time': '09:00',
                'end_time': '19:00',
            },
        )
        self.assertRedirects(resource_response, reverse('owner_dashboard'))
        self.assertRedirects(hours_response, reverse('owner_dashboard'))
        self.assertTrue(
            BookableResource.objects.filter(
                facility=self.facility,
                name='Court 2',
                capacity=16,
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            self.facility.operating_hours.filter(
                day_of_week=2,
                start_time='09:00',
                end_time='19:00',
            ).exists()
        )

    def test_owner_can_update_only_their_payout_destination_settings(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('owner_dashboard'),
            {
                'action': 'save_payout_wallet',
                'facility_id': self.facility.pk,
                'wallet_account_name': 'Owner Demo Account',
                'gcash_number': '0917-000-0001',
                'maya_number': '0918-000-0001',
                'accepts_card': 'on',
                'payout_qr_label': 'Demo QR label',
            },
        )

        self.assertRedirects(response, reverse('owner_dashboard'))
        self.facility.refresh_from_db()
        self.assertEqual(self.facility.wallet_account_name, 'Owner Demo Account')
        self.assertEqual(self.facility.gcash_number, '0917-000-0001')
        self.assertEqual(self.facility.maya_number, '0918-000-0001')
        self.assertTrue(self.facility.accepts_card)
        self.assertEqual(self.facility.payout_qr_label, 'Demo QR label')

    def test_owner_onboarding_requires_dpa_consent_and_creates_pending_venue(self):
        basketball = Sport.objects.create(name='Basketball', slug='basketball')
        self.client.force_login(self.owner)
        onboarding_data = {
            'action': 'onboard_facility',
            'name': 'New Naval Venue',
            'barangay': 'Poblacion',
            'address': '123 Main Road, Naval, Biliran',
            'latitude': '11.560100',
            'longitude': '124.394900',
            'sports': [basketball.pk],
            'court_count': '2',
            'basketball_rate': '350.00',
            'business_trade_name': 'New Naval Sports',
            'business_permit_no': 'BRGY-2026-001',
            'business_contact_number': '+639171234567',
            'dpa_consent_accepted': 'on',
        }

        response = self.client.post(reverse('owner_dashboard'), onboarding_data)

        self.assertRedirects(response, reverse('owner_dashboard'))
        facility = Facility.objects.get(name='New Naval Venue')
        self.assertEqual(facility.owner, self.owner)
        self.assertFalse(facility.is_verified)
        self.assertEqual(
            facility.verification_status,
            Facility.VerificationStatus.PENDING,
        )
        self.assertTrue(facility.dpa_consent_accepted)
        self.assertIsNotNone(facility.dpa_consent_accepted_at)
        self.assertEqual(facility.latitude, Decimal('11.560100'))
        self.assertEqual(facility.longitude, Decimal('124.394900'))
        self.assertEqual(facility.resources.count(), 2)
        facility_sport = facility.facility_sports.get(sport=basketball)
        self.assertEqual(facility_sport.hourly_rate, Decimal('350.00'))
        self.assertEqual(facility.operating_hours.count(), 7)
        self.assertEqual(
            set(facility.operating_hours.values_list('start_time', 'end_time')),
            {(time(8), time(21))},
        )
        self.assertEqual(facility_sport.schedules.count(), 7)
        self.assertEqual(
            set(facility_sport.schedules.values_list('start_time', 'end_time')),
            {(time(8), time(21))},
        )
        self.assertEqual(ResourceSport.objects.filter(
            resource__facility=facility,
            facility_sport=facility_sport,
        ).count(), 2)
        owner_page = self.client.get(reverse('owner_dashboard'))
        self.assertContains(owner_page, 'Pending Platform Verification')
        self.assertEqual(
            self.client.get(f'/facilities/{facility.pk}/').status_code,
            404,
        )

        self.client.force_login(self.admin)
        facility.is_verified = True
        facility.is_active = False
        facility.save(update_fields=('is_verified', 'is_active'))
        admin_page = self.client.get(reverse('admin_dashboard'))
        self.assertContains(admin_page, 'Pending Venue Verification Queue')
        self.assertContains(admin_page, 'BRGY-2026-001')
        self.assertContains(
            self.client.get(reverse('management_facilities')),
            'New Naval Venue',
        )
        approval = self.client.post(
            reverse('admin_dashboard'),
            {'action': 'approve_facility', 'facility_id': facility.pk},
        )
        self.assertRedirects(approval, reverse('admin_dashboard'))
        facility.refresh_from_db()
        self.assertTrue(facility.is_verified)
        self.assertTrue(facility.is_active)
        self.assertEqual(
            facility.verification_status,
            Facility.VerificationStatus.VERIFIED,
        )
        self.assertEqual(facility.verified_by, self.admin.username)
        home_page = self.client.get(reverse('home'))
        public_payload = self.client.get('/api/facilities/')
        public_facilities = public_payload.json()['results']
        public_venue = next(
            item for item in public_facilities if item['id'] == facility.pk
        )
        self.assertEqual(home_page.status_code, 200)
        self.assertIsInstance(public_venue['latitude'], float)
        self.assertIsInstance(public_venue['longitude'], float)
        self.assertAlmostEqual(public_venue['latitude'], 11.5601)
        self.assertAlmostEqual(public_venue['longitude'], 124.3949)
        filtered_payload = self.client.get(
            '/api/facilities/',
            {'sports': 'basketball'},
        ).json()['results']
        self.assertIn(facility.pk, [item['id'] for item in filtered_payload])

        available_slots = self.client.get(
            '/api/availability/search',
            {
                'date': (timezone.localdate() + timedelta(days=1)).isoformat(),
                'sport': 'basketball',
                'facility': facility.pk,
                'mode': 'serial',
            },
        )
        self.assertEqual(available_slots.status_code, 200)
        self.assertEqual(len(available_slots.data['results']), 26)

        rejected_facility = Facility.objects.create(
            name='Rejected Naval Venue',
            owner=self.owner,
            business_permit_no='BRGY-2026-REJECT',
            dpa_consent_accepted=True,
            dpa_consent_accepted_at=timezone.now(),
        )
        rejection = self.client.post(
            reverse('management_facilities'),
            {
                'action': 'reject_facility',
                'facility_id': rejected_facility.pk,
            },
        )
        self.assertRedirects(rejection, reverse('management_facilities'))
        rejected_facility.refresh_from_db()
        self.assertEqual(
            rejected_facility.verification_status,
            Facility.VerificationStatus.REJECTED,
        )
        self.assertFalse(rejected_facility.is_verified)

    def test_owner_onboarding_rejects_submission_without_dpa_consent(self):
        basketball = Sport.objects.create(name='Basketball', slug='basketball')
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('owner_dashboard'),
            {
                'action': 'onboard_facility',
                'name': 'No Consent Venue',
                'barangay': 'Poblacion',
                'address': 'Naval, Biliran',
                'latitude': '11.560100',
                'longitude': '124.394900',
                'sports': [basketball.pk],
                'court_count': '1',
                'basketball_rate': '250.00',
                'business_trade_name': 'No Consent Trade',
                'business_permit_no': 'PERMIT-002',
                'business_contact_number': '09171234567',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Facility.objects.filter(name='No Consent Venue').exists())

    def test_owner_cannot_update_another_owners_payout_destination(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('owner_dashboard'),
            {
                'action': 'save_payout_wallet',
                'facility_id': self.other_facility.pk,
                'wallet_account_name': 'Unauthorized Account',
                'gcash_number': '0917-000-0002',
                'maya_number': '0918-000-0002',
                'payout_qr_label': 'Unauthorized QR',
            },
        )

        self.assertEqual(response.status_code, 404)
        self.other_facility.refresh_from_db()
        self.assertEqual(self.other_facility.wallet_account_name, '')
        self.assertEqual(self.other_facility.gcash_number, '')
        self.assertEqual(self.other_facility.maya_number, '')

    def test_owner_can_upload_a_provider_issued_merchant_qr_image(self):
        image_bytes = _png_image()
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.client.force_login(self.owner)
                response = self.client.post(
                    reverse('owner_dashboard'),
                    {
                        'action': 'save_payout_wallet',
                        'facility_id': self.facility.pk,
                        'wallet_account_name': 'Verified Merchant Account',
                        'gcash_number': '09171234567',
                        'maya_number': '',
                        'payout_qr_label': 'GCash Merchant QR',
                        'payment_qr_image': SimpleUploadedFile(
                            'merchant-qr.png',
                            image_bytes,
                            content_type='image/png',
                        ),
                    },
                )
                self.assertRedirects(response, reverse('owner_dashboard'))
                self.facility.refresh_from_db()
                self.assertTrue(self.facility.payment_qr_image.name.startswith('owner_qrs/'))
                self.assertTrue(self.facility.payment_qr_image.storage.exists(
                    self.facility.payment_qr_image.name
                ))

    def test_owner_closure_cancels_conflicting_booking_with_reason(self):
        start = timezone.localtime(timezone.now() + timedelta(days=3)).replace(
            hour=13,
            minute=36,
            second=0,
            microsecond=0,
        )
        end = start.replace(hour=17, minute=35)
        booking_start = start.replace(hour=17, minute=0)
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=booking_start,
            end_datetime=booking_start + timedelta(hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
            payment_status=Booking.PaymentStatus.PAID,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('owner_dashboard'),
            {
                'action': 'create_closure',
                'facility': self.facility.pk,
                'resource': self.resource.pk,
                'start_datetime': start.strftime('%Y-%m-%dT%H:%M'),
                'end_datetime': end.strftime('%Y-%m-%dT%H:%M'),
                'reason': 'Mid-hour repair',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('owner_dashboard'))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual(booking.cancellation_reason, 'Cancelled due to court closure')
        dashboard_response = self.client.get(reverse('owner_dashboard'))
        self.assertContains(dashboard_response, '1 conflicting reservation(s) were cancelled')

    def test_overlapping_closures_are_rejected(self):
        start = timezone.localtime(timezone.now() + timedelta(days=5)).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        existing = FacilityClosure.objects.create(
            facility=self.facility,
            resource=self.resource,
            start_datetime=start,
            end_datetime=start + timedelta(hours=2),
            reason='Existing work',
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('management_closures'),
            {
                'action': 'create_closure',
                'facility': self.facility.pk,
                'resource': self.resource.pk,
                'start_datetime': (start + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
                'end_datetime': (start + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M'),
                'reason': 'Duplicate work',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('management_closures'))
        self.assertEqual(FacilityClosure.objects.count(), 1)
        self.assertTrue(FacilityClosure.objects.filter(pk=existing.pk).exists())
        closure_page = self.client.get(reverse('management_closures'))
        self.assertContains(closure_page, 'overlaps an existing closure')

    def test_owner_can_verify_external_payment_after_receiving_it(self):
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=8),
            end_datetime=timezone.now() + timedelta(days=8, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('owner_dashboard'),
            {'action': 'verify_payment', 'booking_id': booking.pk},
        )

        self.assertRedirects(response, reverse('owner_dashboard'))
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertEqual(booking.payment_verified_by, self.owner)
        self.assertIsNotNone(booking.payment_verified_at)

    def test_owner_cannot_verify_payment_for_another_owners_booking(self):
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.other_resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=9),
            end_datetime=timezone.now() + timedelta(days=9, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('300.00'),
            total_price=Decimal('300.00'),
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('owner_dashboard'),
            {'action': 'verify_payment', 'booking_id': booking.pk},
        )

        self.assertEqual(response.status_code, 404)
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PENDING)

    def test_owner_can_cancel_pending_booking_and_release_slot(self):
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=9),
            end_datetime=timezone.now() + timedelta(days=9, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('owner_cancel_booking', kwargs={'booking_id': booking.pk}),
            {'cancellation_reason': '  Player requested an alternate time.  '},
        )

        self.assertRedirects(response, reverse('owner_dashboard'))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual(
            booking.cancellation_reason,
            'Player requested an alternate time.',
        )
        self.assertIsNotNone(booking.cancelled_at)
        from .availability import has_confirmed_booking
        self.assertFalse(has_confirmed_booking(
            self.resource,
            booking.start_datetime,
            booking.end_datetime,
        ))

    def test_owner_can_cancel_paid_booking_without_erasing_payment_audit(self):
        verified_at = timezone.now()
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=10),
            end_datetime=timezone.now() + timedelta(days=10, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
            payment_status=Booking.PaymentStatus.PAID,
            payment_verified_at=verified_at,
            payment_verified_by=self.owner,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('owner_cancel_booking', kwargs={'booking_id': booking.pk}),
            {'cancellation_reason': 'Facility maintenance'},
        )

        self.assertRedirects(response, reverse('owner_dashboard'))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertEqual(booking.payment_verified_by, self.owner)
        self.assertEqual(booking.payment_verified_at, verified_at)
        self.assertEqual(
            booking.cancellation_reason,
            'Cancelled by venue owner after payment was received: Facility maintenance',
        )
        dashboard = self.client.get(reverse('owner_dashboard'))
        self.assertContains(dashboard, booking.payment_reference)
        self.assertContains(dashboard, 'Cancelled · excluded from totals')
        self.assertEqual(
            dashboard.context['financial_totals']['owner_payout'],
            Decimal('0.00'),
        )

    def test_paid_booking_cancel_button_shows_refund_warning(self):
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=11),
            end_datetime=timezone.now() + timedelta(days=11, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
            payment_status=Booking.PaymentStatus.PAID,
            payment_verified_at=timezone.now(),
            payment_verified_by=self.owner,
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse('owner_dashboard'))

        self.assertContains(response, 'Cancel Booking')
        self.assertContains(
            response,
            reverse('owner_cancel_booking', kwargs={'booking_id': booking.pk}),
        )
        self.assertContains(response, 'Payment was already recorded.')

    def test_other_owner_and_player_cannot_cancel_booking(self):
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=12),
            end_datetime=timezone.now() + timedelta(days=12, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
        )
        url = reverse('owner_cancel_booking', kwargs={'booking_id': booking.pk})

        for user in (self.other_owner, self.customer):
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.post(url, {
                    'cancellation_reason': 'Unauthorized cancellation',
                })
                self.assertEqual(response.status_code, 404)
                booking.refresh_from_db()
                self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_cancelling_already_cancelled_booking_is_safe(self):
        cancelled_at = timezone.now()
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=13),
            end_datetime=timezone.now() + timedelta(days=13, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
            status=Booking.Status.CANCELLED,
            cancelled_at=cancelled_at,
            cancellation_reason='Existing cancellation reason',
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('owner_cancel_booking', kwargs={'booking_id': booking.pk}),
            {'cancellation_reason': 'Replacement reason'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This reservation is already cancelled.')
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual(booking.cancelled_at, cancelled_at)
        self.assertEqual(
            booking.cancellation_reason,
            'Existing cancellation reason',
        )

    def test_admin_can_cancel_pending_and_paid_bookings_globally(self):
        pending_booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=14),
            end_datetime=timezone.now() + timedelta(days=14, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
        )
        verified_at = timezone.now()
        paid_booking = Booking.objects.create(
            user=self.customer,
            resource=self.other_resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=15),
            end_datetime=timezone.now() + timedelta(days=15, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('300.00'),
            total_price=Decimal('300.00'),
            payment_status=Booking.PaymentStatus.PAID,
            payment_verified_at=verified_at,
            payment_verified_by=self.owner,
        )
        self.client.force_login(self.admin)

        pending_response = self.client.post(
            reverse(
                'admin_cancel_booking',
                kwargs={'booking_id': pending_booking.pk},
            ),
            {'cancellation_reason': '  Schedule conflict  '},
        )
        paid_response = self.client.post(
            reverse(
                'admin_cancel_booking',
                kwargs={'booking_id': paid_booking.pk},
            ),
            {'cancellation_reason': 'Venue unavailable'},
        )

        self.assertRedirects(pending_response, reverse('admin_dashboard'))
        self.assertRedirects(paid_response, reverse('admin_dashboard'))
        pending_booking.refresh_from_db()
        paid_booking.refresh_from_db()
        self.assertEqual(pending_booking.status, Booking.Status.CANCELLED)
        self.assertEqual(
            pending_booking.cancellation_reason,
            'Schedule conflict',
        )
        self.assertEqual(paid_booking.status, Booking.Status.CANCELLED)
        self.assertEqual(
            paid_booking.cancellation_reason,
            'Cancelled by platform administrator after payment was received: '
            'Venue unavailable',
        )
        self.assertEqual(
            paid_booking.payment_status,
            Booking.PaymentStatus.PAID,
        )
        self.assertEqual(paid_booking.payment_verified_at, verified_at)
        self.assertEqual(paid_booking.payment_verified_by, self.owner)

        from .availability import has_confirmed_booking

        self.assertFalse(has_confirmed_booking(
            self.resource,
            pending_booking.start_datetime,
            pending_booking.end_datetime,
        ))
        self.assertFalse(has_confirmed_booking(
            self.other_resource,
            paid_booking.start_datetime,
            paid_booking.end_datetime,
        ))
        dashboard = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(
            dashboard.context['financial_totals']['gross'],
            Decimal('0.00'),
        )
        self.assertEqual(
            dashboard.context['financial_totals']['platform_fee'],
            Decimal('0.00'),
        )
        self.assertEqual(
            dashboard.context['financial_totals']['owner_payout'],
            Decimal('0.00'),
        )
        self.assertEqual(
            list(dashboard.context['owner_commission_ledger']),
            [],
        )

    def test_admin_cancelling_already_cancelled_booking_is_safe(self):
        cancelled_at = timezone.now()
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=16),
            end_datetime=timezone.now() + timedelta(days=16, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
            status=Booking.Status.CANCELLED,
            cancelled_at=cancelled_at,
            cancellation_reason='Cancelled earlier',
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse(
                'admin_cancel_booking',
                kwargs={'booking_id': booking.pk},
            ),
            {'cancellation_reason': 'Overwrite attempt'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This reservation is already cancelled.')
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual(booking.cancelled_at, cancelled_at)
        self.assertEqual(booking.cancellation_reason, 'Cancelled earlier')

    def test_admin_can_delete_single_log_without_touching_business_records(self):
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=17),
            end_datetime=timezone.now() + timedelta(days=17, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
        )
        content_type = ContentType.objects.get_for_model(Booking)
        first_log = LogEntry.objects.create(
            user=self.admin,
            content_type=content_type,
            object_id=str(booking.pk),
            object_repr=str(booking),
            action_flag=CHANGE,
            change_message='First test log',
        )
        retained_log = LogEntry.objects.create(
            user=self.admin,
            content_type=content_type,
            object_id=str(booking.pk),
            object_repr=str(booking),
            action_flag=CHANGE,
            change_message='Second test log',
        )
        user_count = get_user_model().objects.count()
        facility_count = Facility.objects.count()
        booking_count = Booking.objects.count()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('admin_delete_log', kwargs={'log_id': first_log.pk}),
        )

        self.assertRedirects(response, reverse('admin_dashboard'))
        self.assertFalse(LogEntry.objects.filter(pk=first_log.pk).exists())
        self.assertTrue(LogEntry.objects.filter(pk=retained_log.pk).exists())
        self.assertEqual(get_user_model().objects.count(), user_count)
        self.assertEqual(Facility.objects.count(), facility_count)
        self.assertEqual(Booking.objects.count(), booking_count)

    def test_admin_can_delete_all_logs_and_repeat_when_empty(self):
        content_type = ContentType.objects.get_for_model(Facility)
        LogEntry.objects.create(
            user=self.admin,
            content_type=content_type,
            object_id=str(self.facility.pk),
            object_repr=str(self.facility),
            action_flag=CHANGE,
            change_message='Facility log',
        )
        LogEntry.objects.create(
            user=self.admin,
            content_type=content_type,
            object_id=str(self.other_facility.pk),
            object_repr=str(self.other_facility),
            action_flag=CHANGE,
            change_message='Other facility log',
        )
        user_count = get_user_model().objects.count()
        facility_count = Facility.objects.count()
        booking_count = Booking.objects.count()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('admin_delete_all_logs'),
            follow=True,
        )
        empty_response = self.client.post(
            reverse('admin_delete_all_logs'),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2 log entries permanently deleted.')
        self.assertEqual(empty_response.status_code, 200)
        self.assertContains(empty_response, 'There are no log entries to delete.')
        self.assertFalse(LogEntry.objects.exists())
        self.assertEqual(get_user_model().objects.count(), user_count)
        self.assertEqual(Facility.objects.count(), facility_count)
        self.assertEqual(Booking.objects.count(), booking_count)

    def test_non_admins_cannot_use_admin_booking_or_log_endpoints(self):
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=18),
            end_datetime=timezone.now() + timedelta(days=18, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
        )
        log_entry = LogEntry.objects.create(
            user=self.admin,
            content_type=ContentType.objects.get_for_model(Booking),
            object_id=str(booking.pk),
            object_repr=str(booking),
            action_flag=CHANGE,
            change_message='Protected log',
        )
        urls = (
            (
                reverse(
                    'admin_cancel_booking',
                    kwargs={'booking_id': booking.pk},
                ),
                {},
            ),
            (
                reverse(
                    'admin_delete_log',
                    kwargs={'log_id': log_entry.pk},
                ),
                {},
            ),
            (reverse('admin_delete_all_logs'), {}),
        )

        for user in (self.owner, self.customer):
            self.client.force_login(user)
            for url, payload in urls:
                with self.subTest(user=user, url=url):
                    response = self.client.post(url, payload)
                    self.assertEqual(response.status_code, 403)

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertTrue(LogEntry.objects.filter(pk=log_entry.pk).exists())

    def test_admin_destructive_endpoints_reject_get_requests(self):
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=19),
            end_datetime=timezone.now() + timedelta(days=19, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
        )
        log_entry = LogEntry.objects.create(
            user=self.admin,
            content_type=ContentType.objects.get_for_model(Booking),
            object_id=str(booking.pk),
            object_repr=str(booking),
            action_flag=CHANGE,
            change_message='Method safety log',
        )
        self.client.force_login(self.admin)

        urls = (
            reverse(
                'admin_cancel_booking',
                kwargs={'booking_id': booking.pk},
            ),
            reverse('admin_delete_log', kwargs={'log_id': log_entry.pk}),
            reverse('admin_delete_all_logs'),
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertTrue(LogEntry.objects.filter(pk=log_entry.pk).exists())

    def test_admin_dashboard_renders_booking_and_log_management_controls(self):
        self.facility.name = "Tonio's Dink District"
        self.facility.save(update_fields=('name',))
        pending_booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=20),
            end_datetime=timezone.now() + timedelta(days=20, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
        )
        paid_booking = Booking.objects.create(
            user=self.customer,
            resource=self.other_resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=21),
            end_datetime=timezone.now() + timedelta(days=21, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('300.00'),
            total_price=Decimal('300.00'),
            payment_status=Booking.PaymentStatus.PAID,
            payment_verified_at=timezone.now(),
            payment_verified_by=self.admin,
        )
        log_entry = LogEntry.objects.create(
            user=self.admin,
            content_type=ContentType.objects.get_for_model(Facility),
            object_id=str(self.facility.pk),
            object_repr=str(self.facility),
            action_flag=CHANGE,
            change_message='Template rendering log',
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cancel Booking')
        self.assertContains(response, 'Payment was already recorded.')
        self.assertContains(response, 'data-cancel-modal')
        self.assertContains(response, 'data-cancel-form')
        self.assertContains(response, 'data-modal-paid-warning')
        self.assertContains(response, 'class="cg-modal-overlay"')
        self.assertContains(response, 'z-index: 99990')
        self.assertContains(response, '.cg-modal-overlay.is-open')
        self.assertContains(response, 'booking-table-scroll')
        self.assertContains(response, 'overscroll-behavior: contain')
        self.assertContains(response, 'data-booking-search')
        self.assertContains(response, 'data-booking-status-filter')
        self.assertContains(response, 'data-booking-active-only')
        self.assertContains(response, 'data-booking-count')
        self.assertContains(response, 'data-cancel-trigger')
        self.assertContains(response, 'event.preventDefault()')
        self.assertContains(response, 'event.stopPropagation()')
        self.assertContains(response, "event.target.closest('[data-cancel-trigger]')")
        self.assertContains(response, 'form.action = cancelTrigger.dataset.cancelUrl;')
        self.assertContains(response, 'Tonio&#x27;s Dink District')
        self.assertContains(
            response,
            (
                'data-cancel-url="'
                + reverse(
                'admin_cancel_booking',
                kwargs={'booking_id': pending_booking.pk},
                )
                + '"'
            ),
        )
        self.assertContains(
            response,
            (
                'data-cancel-url="'
                + reverse(
                'admin_cancel_booking',
                kwargs={'booking_id': paid_booking.pk},
                )
                + '"'
            ),
        )
        self.assertContains(response, 'Delete Log')
        self.assertContains(response, 'Delete All Logs')
        self.assertContains(response, 'data-log-delete-trigger')
        self.assertContains(
            response,
            (
                'data-log-delete-url="'
                + reverse('admin_delete_log', kwargs={'log_id': log_entry.pk})
                + '"'
            ),
        )
        self.assertContains(response, reverse('admin_delete_all_logs'))
        self.assertContains(response, 'data-log-delete-all-modal')
        self.assertContains(response, 'data-log-delete-all-trigger')
        html = response.content.decode()
        modal_start = re.search(
            r'<div\s+class="cg-modal-overlay"\s+data-cancel-modal',
            html,
        ).start()
        self.assertLess(
            html.index('</main>'),
            modal_start,
        )
        modal_end = html.index('data-modal-paid-warning', modal_start)
        self.assertIn('name="csrfmiddlewaretoken"', html[modal_start:modal_end])
        self.assertNotIn(
            'hover-lift mb-4" aria-labelledby="master-bookings-heading"',
            html,
        )
        assert_rendered_scripts_parse(self, html)

    def test_owner_dashboard_renders_isolated_booking_history_controls(self):
        pending_booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=22),
            end_datetime=timezone.now() + timedelta(days=22, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
        )
        Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=23),
            end_datetime=timezone.now() + timedelta(days=23, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
            status=Booking.Status.CANCELLED,
            cancellation_reason='Owner historical cancellation',
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse('owner_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'booking-table-scroll')
        self.assertContains(response, 'overscroll-behavior: contain')
        self.assertContains(response, 'id="owner-booking-search"')
        self.assertContains(response, 'data-booking-status-filter')
        self.assertContains(response, 'data-booking-active-only')
        self.assertContains(response, 'data-booking-count')
        self.assertContains(response, 'Pending Payment')
        self.assertContains(response, 'Payment Received / Paid')
        self.assertContains(response, 'Cancelled')
        self.assertContains(response, pending_booking.payment_reference)
        self.assertContains(response, 'Owner historical cancellation')
        self.assertContains(response, 'data-cancel-modal')
        self.assertContains(response, 'data-cancel-trigger')
        self.assertContains(response, 'data-cancel-form')
        self.assertContains(response, 'class="cg-modal-overlay"')
        self.assertContains(
            response,
            (
                'data-cancel-url="'
                + reverse(
                    'owner_cancel_booking',
                    kwargs={'booking_id': pending_booking.pk},
                )
                + '"'
            ),
        )
        assert_rendered_scripts_parse(self, response.content.decode())

    def test_admin_commission_collection_ledger_tracks_verified_payments(self):
        booking = Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=10),
            end_datetime=timezone.now() + timedelta(days=10, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
            payment_status=Booking.PaymentStatus.PAID,
            payment_verified_at=timezone.now(),
            payment_verified_by=self.owner,
        )
        self.client.force_login(self.admin)

        dashboard = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.context['financial_totals']['platform_fee'], Decimal('10.00'))
        self.assertContains(dashboard, 'Owner Commission Collection Ledger')
        pending_dashboard = self.client.get(
            reverse('admin_dashboard'),
            {'settlement_status': 'pending'},
        )
        self.assertEqual(list(pending_dashboard.context['all_bookings']), [booking])
        paid_dashboard = self.client.get(
            reverse('admin_dashboard'),
            {'settlement_status': 'paid'},
        )
        self.assertEqual(list(paid_dashboard.context['all_bookings']), [])

        response = self.client.post(
            reverse('settle_commission', kwargs={'booking_id': booking.pk}),
        )

        self.assertRedirects(response, reverse('admin_dashboard'))
        booking.refresh_from_db()
        self.assertTrue(booking.platform_fee_collected)
        self.assertEqual(booking.platform_fee_collected_by, self.admin)
        self.assertIsNotNone(booking.platform_fee_collected_at)
        settled_dashboard = self.client.get(
            reverse('admin_dashboard'),
            {'settlement_status': 'paid'},
        )
        self.assertEqual(list(settled_dashboard.context['all_bookings']), [booking])
        self.assertEqual(
            settled_dashboard.context['financial_totals']['platform_fee'],
            Decimal('0.00'),
        )
        self.client.force_login(self.owner)
        owner_dashboard = self.client.get(reverse('owner_dashboard'))
        self.assertEqual(
            owner_dashboard.context['financial_totals']['platform_fee_settled'],
            Decimal('10.00'),
        )
        self.assertContains(owner_dashboard, 'Commission Settled · Paid to Admin')

    def test_owner_cannot_edit_another_owners_facility(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('owner_dashboard'),
            {
                'action': 'save_facility',
                'facility_id': self.other_facility.pk,
                'name': 'Unauthorized Update',
                'capacity': '10',
            },
        )

        self.assertEqual(response.status_code, 404)
        self.other_facility.refresh_from_db()
        self.assertEqual(self.other_facility.name, 'Other Owner Venue')

    def test_owner_portal_and_closure_manager_show_only_owned_venue_data(self):
        own_closure = FacilityClosure.objects.create(
            facility=self.facility,
            resource=self.resource,
            start_datetime=timezone.now() + timedelta(days=4),
            end_datetime=timezone.now() + timedelta(days=4, hours=1),
            reason='Owner maintenance',
        )
        FacilityClosure.objects.create(
            facility=self.other_facility,
            resource=self.other_resource,
            start_datetime=timezone.now() + timedelta(days=5),
            end_datetime=timezone.now() + timedelta(days=5, hours=1),
            reason='Other owner maintenance',
        )
        Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=6),
            end_datetime=timezone.now() + timedelta(days=6, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
            payment_status=Booking.PaymentStatus.PAID,
        )
        Booking.objects.create(
            user=self.customer,
            resource=self.other_resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=7),
            end_datetime=timezone.now() + timedelta(days=7, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('300.00'),
            total_price=Decimal('300.00'),
        )
        self.client.force_login(self.owner)

        owner_response = self.client.get(reverse('owner_dashboard'))
        closure_response = self.client.get(reverse('management_closures'))

        self.assertEqual(owner_response.status_code, 200)
        self.assertContains(owner_response, 'Owner Test Venue')
        self.assertNotContains(owner_response, 'Other Owner Venue')
        self.assertNotContains(owner_response, 'Other Court')
        self.assertNotContains(owner_response, 'Other owner maintenance')
        self.assertEqual(len(owner_response.context['facilities']), 1)
        self.assertEqual(len(owner_response.context['venue_bookings']), 1)
        self.assertEqual(
            owner_response.context['financial_totals']['gross'],
            Decimal('200.00'),
        )

        self.assertEqual(closure_response.status_code, 200)
        self.assertContains(closure_response, 'Owner maintenance')
        self.assertNotContains(closure_response, 'Other owner maintenance')
        self.assertEqual(list(closure_response.context['facilities']), [self.facility])
        self.assertEqual(list(closure_response.context['closures']), [own_closure])
        self.assertEqual(
            list(closure_response.context['closure_form'].fields['facility'].queryset),
            [self.facility],
        )
        self.assertEqual(
            list(closure_response.context['closure_form'].fields['resource'].queryset),
            [self.resource],
        )

    def test_owner_cannot_update_another_owners_rate_or_create_closure_there(self):
        self.client.force_login(self.owner)

        rate_response = self.client.post(
            reverse('owner_dashboard'),
            {
                'action': 'save_rate',
                'facility_sport_id': self.other_facility_sport.pk,
                'hourly_rate': '1.00',
                'is_active': 'on',
            },
        )
        closure_response = self.client.post(
            reverse('management_closures'),
            {
                'action': 'create_closure',
                'facility': self.other_facility.pk,
                'resource': self.other_resource.pk,
                'start_datetime': '2026-11-25T10:00',
                'end_datetime': '2026-11-25T11:00',
                'reason': 'Unauthorized closure',
            },
        )

        self.assertEqual(rate_response.status_code, 404)
        self.assertRedirects(closure_response, reverse('management_closures'))
        self.other_facility_sport.refresh_from_db()
        self.assertEqual(self.other_facility_sport.hourly_rate, Decimal('300.00'))
        self.assertFalse(
            FacilityClosure.objects.filter(reason='Unauthorized closure').exists()
        )

    def test_owner_can_schedule_facility_closure(self):
        self.client.force_login(self.owner)
        start = timezone.localtime(timezone.now() + timedelta(days=2)).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        end = start + timedelta(hours=2)

        response = self.client.post(
            reverse('management_closures'),
            {
                'action': 'create_closure',
                'facility': self.facility.pk,
                'resource': self.resource.pk,
                'start_datetime': start.strftime('%Y-%m-%dT%H:%M'),
                'end_datetime': end.strftime('%Y-%m-%dT%H:%M'),
                'reason': 'Court maintenance',
            },
        )

        self.assertRedirects(response, reverse('management_closures'))
        closure = FacilityClosure.objects.get(facility=self.facility)
        self.assertEqual(closure.resource, self.resource)
        self.assertEqual(closure.created_by, self.owner)
        self.assertEqual(closure.reason, 'Court maintenance')

    def test_platform_admin_can_toggle_facility_verification(self):
        self.facility.business_trade_name = 'Owner Test Business'
        self.facility.business_permit_no = 'PERMIT-OWNER-001'
        self.facility.business_contact_number = '09171234567'
        self.facility.dpa_consent_accepted = True
        self.facility.save(update_fields=(
            'business_trade_name',
            'business_permit_no',
            'business_contact_number',
            'dpa_consent_accepted',
        ))
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('management_facilities'),
            {
                'action': 'toggle_verified',
                'facility_id': self.facility.pk,
            },
        )

        self.assertRedirects(response, reverse('management_facilities'))
        self.facility.refresh_from_db()
        self.assertTrue(self.facility.is_verified)

    def test_owner_dashboard_reports_commission_and_net_payout(self):
        Booking.objects.create(
            user=self.customer,
            resource=self.resource,
            sport=self.sport,
            start_datetime=timezone.now() + timedelta(days=2),
            end_datetime=timezone.now() + timedelta(days=2, hours=1),
            participant_count=2,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
            payment_status=Booking.PaymentStatus.PAID,
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse('owner_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['financial_totals']['gross'], Decimal('200.00'))
        self.assertEqual(
            response.context['financial_totals']['platform_fee'],
            Decimal('10.00'),
        )
        self.assertEqual(
            response.context['financial_totals']['owner_payout'],
            Decimal('190.00'),
        )

    def test_customer_cannot_open_owner_or_management_portals(self):
        self.client.force_login(self.customer)

        self.assertEqual(self.client.get(reverse('owner_dashboard')).status_code, 403)
        self.assertEqual(self.client.get(reverse('management_facilities')).status_code, 403)
        self.assertEqual(self.client.get(reverse('management_closures')).status_code, 403)

    def test_platform_admin_sees_all_facilities_and_closures(self):
        self.client.force_login(self.admin)

        owner_response = self.client.get(reverse('owner_dashboard'))
        closure_response = self.client.get(reverse('management_closures'))

        self.assertEqual(owner_response.status_code, 200)
        self.assertContains(owner_response, 'Owner Test Venue')
        self.assertContains(owner_response, 'Other Owner Venue')
        self.assertEqual(len(owner_response.context['facilities']), 2)
        self.assertEqual(closure_response.status_code, 200)
        self.assertEqual(
            set(closure_response.context['facilities']),
            {self.facility, self.other_facility},
        )


class OwnerVenueUpgradeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(username='venue-upgrade-owner')
        UserProfile.objects.create(user=cls.owner, role=UserProfile.Role.COURT_OWNER)
        cls.other_owner = user_model.objects.create_user(
            username='venue-upgrade-other-owner',
        )
        UserProfile.objects.create(
            user=cls.other_owner,
            role=UserProfile.Role.COURT_OWNER,
        )
        cls.player = user_model.objects.create_user(username='venue-upgrade-player')
        cls.sport = Sport.objects.create(
            name='Upgrade Pickleball',
            slug='upgrade-pickleball',
        )
        cls.facility = Facility.objects.create(
            name="Tonio's Dink District",
            owner=cls.owner,
            capacity=16,
            default_hourly_rate='300.00',
            is_verified=True,
            verification_status=Facility.VerificationStatus.VERIFIED,
        )
        cls.other_facility = Facility.objects.create(
            name='Other Owner Facility',
            owner=cls.other_owner,
        )
        cls.facility_sport = FacilitySport.objects.create(
            facility=cls.facility,
            sport=cls.sport,
            hourly_rate='250.00',
        )
        cls.other_facility_sport = FacilitySport.objects.create(
            facility=cls.other_facility,
            sport=cls.sport,
        )
        cls.court = BookableResource.objects.create(
            facility=cls.facility,
            name='Court 1',
            capacity=16,
        )
        ResourceSport.objects.create(
            resource=cls.court,
            facility_sport=cls.facility_sport,
        )

    def test_owner_can_manage_courts_and_cannot_remove_the_last_active_court(self):
        self.client.force_login(self.owner)
        endpoint = reverse(
            'owner-manage-courts',
            kwargs={'facility_id': self.facility.pk},
        )
        add_response = self.client.post(
            endpoint,
            {
                'action': 'add',
                'name': 'Court 2',
                'capacity': '12',
                'hourly_rate': '275.00',
                'display_order': '1',
                'sports': str(self.facility_sport.pk),
            },
        )
        self.assertRedirects(add_response, reverse('owner_dashboard'))
        court_two = BookableResource.objects.get(
            facility=self.facility,
            name='Court 2',
        )
        self.assertEqual(court_two.hourly_rate, Decimal('275.00'))
        self.assertTrue(court_two.resource_sports.filter(
            facility_sport=self.facility_sport,
        ).exists())

        edit_response = self.client.post(
            endpoint,
            {
                'action': 'save',
                'resource_id': court_two.pk,
                f'court-{court_two.pk}-name': 'Pickleball Court B',
                f'court-{court_two.pk}-capacity': '14',
                f'court-{court_two.pk}-hourly_rate': '',
                f'court-{court_two.pk}-display_order': '2',
                f'court-{court_two.pk}-sports': str(self.facility_sport.pk),
            },
        )
        self.assertRedirects(edit_response, reverse('owner_dashboard'))
        court_two.refresh_from_db()
        self.assertEqual(court_two.name, 'Pickleball Court B')
        self.assertIsNone(court_two.hourly_rate)

        deactivate_first = self.client.post(
            endpoint,
            {'action': 'toggle', 'resource_id': self.court.pk},
        )
        self.assertRedirects(deactivate_first, reverse('owner_dashboard'))
        court_two_id = court_two.pk
        block_last_delete = self.client.post(
            endpoint,
            {'action': 'delete', 'resource_id': court_two_id},
        )
        self.assertRedirects(block_last_delete, reverse('owner_dashboard'))
        self.assertTrue(
            BookableResource.objects.filter(pk=court_two_id).exists(),
        )

        self.client.post(
            endpoint,
            {'action': 'toggle', 'resource_id': self.court.pk},
        )
        delete_response = self.client.post(
            endpoint,
            {'action': 'delete', 'resource_id': court_two_id},
        )
        self.assertRedirects(delete_response, reverse('owner_dashboard'))
        self.assertFalse(
            BookableResource.objects.filter(pk=court_two_id).exists(),
        )

    def test_photo_cover_lifecycle_upload_validation_and_file_cleanup(self):
        self.client.force_login(self.owner)
        endpoint = reverse(
            'owner-manage-photos',
            kwargs={'facility_id': self.facility.pk},
        )
        with TemporaryDirectory() as media_directory, override_settings(
            MEDIA_ROOT=media_directory,
        ):
            first_response = self.client.post(
                endpoint,
                {
                    'action': 'upload',
                    'caption': 'Main court',
                    'category': FacilityPhoto.Category.COURT,
                    'image': SimpleUploadedFile(
                        'main-court.png',
                        _png_image(),
                        content_type='image/png',
                    ),
                },
            )
            self.assertRedirects(first_response, reverse('owner_dashboard'))
            first = FacilityPhoto.objects.get(caption='Main court')
            self.assertTrue(first.is_cover)
            first_file = Path(media_directory) / first.image.name
            self.assertTrue(first_file.exists())

            second_response = self.client.post(
                endpoint,
                {
                    'action': 'upload',
                    'caption': 'Court lights',
                    'category': FacilityPhoto.Category.AMENITY,
                    'image': SimpleUploadedFile(
                        'court-lights.png',
                        _png_image(),
                        content_type='image/png',
                    ),
                },
            )
            self.assertRedirects(second_response, reverse('owner_dashboard'))
            second = FacilityPhoto.objects.get(caption='Court lights')
            self.assertFalse(second.is_cover)
            self.client.post(
                endpoint,
                {'action': 'set_cover', 'photo_id': second.pk},
            )
            first.refresh_from_db()
            second.refresh_from_db()
            self.assertFalse(first.is_cover)
            self.assertTrue(second.is_cover)
            second_file = Path(media_directory) / second.image.name
            with self.captureOnCommitCallbacks(execute=True):
                delete_response = self.client.post(
                    endpoint,
                    {'action': 'delete', 'photo_id': second.pk},
                )
            self.assertRedirects(delete_response, reverse('owner_dashboard'))
            self.assertFalse(second_file.exists())
            first.refresh_from_db()
            self.assertTrue(first.is_cover)

            invalid_type = self.client.post(
                endpoint,
                {
                    'action': 'upload',
                    'caption': 'Not an image',
                    'image': SimpleUploadedFile(
                        'not-an-image.txt',
                        b'not an image',
                        content_type='text/plain',
                    ),
                },
            )
            self.assertRedirects(invalid_type, reverse('owner_dashboard'))
            self.assertFalse(
                FacilityPhoto.objects.filter(caption='Not an image').exists(),
            )

            oversized = self.client.post(
                endpoint,
                {
                    'action': 'upload',
                    'caption': 'Too large',
                    'image': SimpleUploadedFile(
                        'too-large.png',
                        _oversized_png(),
                        content_type='image/png',
                    ),
                },
            )
            self.assertRedirects(oversized, reverse('owner_dashboard'))
            self.assertFalse(
                FacilityPhoto.objects.filter(caption='Too large').exists(),
            )

    def test_owner_can_save_deduplicated_amenities_and_public_discovery_displays_them(self):
        self.client.force_login(self.owner)
        endpoint = reverse(
            'owner-manage-amenities',
            kwargs={'facility_id': self.facility.pk},
        )
        save_response = self.client.post(
            endpoint,
            {
                'amenities': ['Covered Roof', 'Drinking Water'],
                'custom_amenities': ' Drinking Water, Bounce area, Bounce area , Patio ',
            },
        )
        self.assertRedirects(save_response, reverse('owner_dashboard'))
        self.facility.refresh_from_db()
        self.assertEqual(
            self.facility.amenities,
            ['Covered Roof', 'Drinking Water', 'Bounce area', 'Patio'],
        )

        with TemporaryDirectory() as media_directory, override_settings(
            MEDIA_ROOT=media_directory,
        ):
            photo = FacilityPhoto.objects.create(
                facility=self.facility,
                image=SimpleUploadedFile(
                    'venue.png',
                    _png_image(),
                    content_type='image/png',
                ),
                caption='The main court',
            )
            detail = self.client.get(
                reverse('facility-detail-page', kwargs={'pk': self.facility.pk}),
            )
            self.assertEqual(detail.status_code, 200)
            self.assertContains(detail, "Tonio&#x27;s Dink District")
            self.assertContains(detail, 'Venue photo gallery')
            self.assertContains(detail, photo.image.url)
            self.assertContains(detail, 'Covered Roof')
            self.assertContains(detail, 'Court 1')
            assert_rendered_scripts_parse(self, detail.content.decode())

            home = self.client.get(reverse('home'))
            self.assertEqual(home.status_code, 200)
            assert_rendered_scripts_parse(self, home.content.decode())
            discovery = self.client.get(reverse('facility-list'))
            self.assertEqual(discovery.status_code, 200)
            public_facility = next(
                item for item in discovery.data['results']
                if item['id'] == self.facility.pk
            )
            self.assertEqual(public_facility['court_count'], 1)
            self.assertEqual(public_facility['cover_photo_url'], photo.image.url)
            self.assertEqual(public_facility['amenities'], self.facility.amenities)

    def test_owner_mutation_endpoints_require_post_and_enforce_tenant_roles(self):
        endpoints = (
            ('owner-manage-courts', {'action': 'delete', 'resource_id': self.court.pk}),
            ('owner-manage-photos', {'action': 'delete', 'photo_id': 999999}),
            ('owner-manage-amenities', {'custom_amenities': 'Parking'}),
        )
        for route_name, payload in endpoints:
            path = reverse(
                route_name,
                kwargs={'facility_id': self.facility.pk},
            )
            self.assertEqual(self.client.get(path).status_code, 405)
            self.assertEqual(self.client.post(path, payload).status_code, 302)

        self.client.force_login(self.owner)
        for route_name, _payload in endpoints:
            path = reverse(
                route_name,
                kwargs={'facility_id': self.facility.pk},
            )
            self.assertEqual(self.client.get(path).status_code, 405)

        self.client.force_login(self.other_owner)
        for route_name, payload in endpoints:
            path = reverse(
                route_name,
                kwargs={'facility_id': self.facility.pk},
            )
            self.assertEqual(self.client.post(path, payload).status_code, 404)

        self.client.force_login(self.player)
        for route_name, payload in endpoints:
            path = reverse(
                route_name,
                kwargs={'facility_id': self.facility.pk},
            )
            self.assertEqual(self.client.post(path, payload).status_code, 403)

    def test_existing_facilities_without_resources_get_one_default_court_idempotently(self):
        legacy_facility = Facility.objects.create(
            name='Legacy facility without a court',
            owner=self.owner,
        )
        legacy_sport = FacilitySport.objects.create(
            facility=legacy_facility,
            sport=self.sport,
        )
        migration = importlib.import_module(
            'facilities.migrations.0007_bookableresource_display_order_and_more',
        )
        editor = SimpleNamespace(connection=connection)

        migration.create_default_courts(apps, editor)
        migration.create_default_courts(apps, editor)

        self.assertEqual(
            legacy_facility.resources.filter(name='Court 1').count(),
            1,
        )
        default_court = legacy_facility.resources.get(name='Court 1')
        self.assertTrue(default_court.resource_sports.filter(
            facility_sport=legacy_sport,
        ).exists())
        self.assertEqual(self.facility.resources.count(), 1)

    def test_owner_dashboard_gallery_markup_and_inline_javascript_render(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('owner_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Venue photos')
        self.assertContains(response, 'Save Amenities')
        self.assertContains(response, 'Delete Photo')
        assert_rendered_scripts_parse(self, response.content.decode())
