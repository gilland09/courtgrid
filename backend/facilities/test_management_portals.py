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
