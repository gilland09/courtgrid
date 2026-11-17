from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .management.commands.seed_courtgrid import FACILITIES, SPORT_RATES
from .models import (
    BookableResource,
    Facility,
    FacilityOperatingHours,
    FacilitySport,
    ResourceSport,
    Sport,
    SportSchedule,
)


class SeedCourtGridCommandTests(TestCase):
    def test_seed_command_is_idempotent_and_creates_bookable_verified_facilities(self):
        call_command('seed_courtgrid', verbosity=0)
        call_command('seed_courtgrid', verbosity=0)

        self.assertEqual(Sport.objects.count(), 4)
        self.assertEqual(Facility.objects.count(), 5)
        self.assertEqual(FacilitySport.objects.count(), 9)
        self.assertEqual(BookableResource.objects.count(), 11)
        self.assertEqual(ResourceSport.objects.count(), 21)
        self.assertEqual(FacilityOperatingHours.objects.count(), 35)
        self.assertEqual(SportSchedule.objects.count(), 63)

        owner = get_user_model().objects.get(username='owner_tonio')
        self.assertEqual(owner.courtgrid_profile.role, 'court_owner')
        self.assertTrue(owner.check_password('owner123'))
        self.assertEqual(owner.owned_facilities.count(), 5)

        for facility_data in FACILITIES:
            facility = Facility.objects.get(name=facility_data['name'])
            self.assertEqual(facility.owner, owner)
            self.assertTrue(facility.is_active)
            self.assertFalse(facility.is_demo_data)
            self.assertTrue(facility.is_verified)
            self.assertEqual(facility.address, facility_data['address'])
            self.assertEqual(facility.barangay, facility_data['barangay'])
            self.assertEqual(facility.capacity, facility_data['capacity'])
            self.assertEqual(facility.latitude, Decimal(facility_data['latitude']))
            self.assertEqual(facility.longitude, Decimal(facility_data['longitude']))
            resources = facility.resources.filter(is_active=True)
            self.assertEqual(resources.count(), facility_data['courts'])
            self.assertTrue(all(resource.capacity for resource in resources))
            for facility_sport in facility.facility_sports.select_related('sport'):
                self.assertEqual(
                    facility_sport.hourly_rate,
                    Decimal(SPORT_RATES[facility_sport.sport.name]),
                )

        facility = Facility.objects.get(name="Tonio's Dink District")
        resource = facility.resources.get(name='Court 1')
        sport = Sport.objects.get(slug='pickleball')
        start = timezone.make_aware(datetime.combine(
            timezone.localdate() + timedelta(days=1),
            time(10),
        ))
        self.client.force_login(
            get_user_model().objects.create_user(
                username='seeded-facility-booker',
                password='test-password',
            )
        )
        response = self.client.post(
            '/api/bookings/',
            {
                'resource_id': resource.pk,
                'sport_id': sport.pk,
                'start_datetime': start.isoformat(),
                'end_datetime': (start + timedelta(hours=1)).isoformat(),
                'participant_count': 4,
            },
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['rate_snapshot'], '200.00')
