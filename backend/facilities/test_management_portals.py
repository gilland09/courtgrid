from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
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
