from datetime import timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.test import TestCase

from bookings.models import Booking, UserProfile

from .models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilitySport,
    Sport,
)


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
        image_bytes = b'\x89PNG\r\n\x1a\n' + (b'\x00' * 32)
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
