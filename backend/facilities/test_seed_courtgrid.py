from datetime import datetime, time, timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from bookings.models import Booking

from .management.commands.seed_courtgrid import FACILITIES, SPORT_RATES
from .models import (
    BookableResource,
    Facility,
    FacilityOperatingHours,
    FacilityPaymentMethod,
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

        expected_owners = {
            "Tonio's Dink District": ('owner_tonio', 'Tonio', 'Partner'),
            'BiPSU Sports Complex': ('owner_bipsu', 'BiPSU', 'Athletics Office'),
            'Naval Municipal Gymnasium': ('owner_municipal', 'Naval', 'LGU Sports'),
            'Caneja Turf & Pickleball Center': (
                'owner_caneja',
                'Caneja',
                'Turf Management',
            ),
            'Santissimo Rosario Barangay Court': (
                'owner_santissimo',
                'Brgy.',
                'Santissimo Council',
            ),
        }
        for facility_name, (username, first_name, last_name) in expected_owners.items():
            owner = get_user_model().objects.get(username=username)
            self.assertEqual(owner.courtgrid_profile.role, 'court_owner')
            self.assertTrue(owner.check_password('owner123'))
            self.assertEqual((owner.first_name, owner.last_name), (first_name, last_name))
            self.assertEqual(
                list(owner.owned_facilities.values_list('name', flat=True)),
                [facility_name],
            )

        seeded_bookings = Booking.objects.filter(user__username='demo_player')
        self.assertEqual(seeded_bookings.count(), 2)
        self.assertTrue(all(booking.payment_reference for booking in seeded_bookings))
        self.assertTrue(all(booking.payment_status == 'pending' for booking in seeded_bookings))
        self.assertEqual(
            sum(
                seeded_bookings.values_list('platform_fee_amount', flat=True),
                Decimal('0.00'),
            ),
            Decimal('22.50'),
        )

        for facility_data in FACILITIES:
            facility = Facility.objects.get(name=facility_data['name'])
            self.assertEqual(
                facility.owner.username,
                expected_owners[facility_data['name']][0],
            )
            self.assertTrue(facility.is_active)
            self.assertFalse(facility.is_demo_data)
            self.assertTrue(facility.is_verified)
            self.assertEqual(
                facility.verification_status,
                Facility.VerificationStatus.VERIFIED,
            )
            self.assertEqual(facility.address, facility_data['address'])
            self.assertEqual(facility.barangay, facility_data['barangay'])
            self.assertEqual(facility.capacity, facility_data['capacity'])
            self.assertEqual(
                facility.wallet_account_name,
                facility_data['wallet_account_name'],
            )
            self.assertEqual(facility.gcash_number, facility_data['gcash_number'])
            self.assertEqual(facility.maya_number, facility_data['maya_number'])
            self.assertEqual(
                facility.payout_qr_label,
                facility_data['payout_qr_label'],
            )
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
        self.assertTrue(
            Booking.objects.filter(
                resource__facility__name="Tonio's Dink District",
                status=Booking.Status.CONFIRMED,
            ).exists()
        )
        self.assertTrue(
            Booking.objects.filter(
                resource__facility__name='BiPSU Sports Complex',
                status=Booking.Status.CONFIRMED,
            ).exists()
        )

        facility = Facility.objects.get(name="Tonio's Dink District")
        self.assertFalse(facility.has_arranged_payment_method)
        method = FacilityPaymentMethod.objects.create(
            facility=facility, label='Test wallet', account_name='Test',
            account_number='12345',
        )
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
        with TemporaryDirectory() as directory, override_settings(PRIVATE_RECEIPT_ROOT=directory):
            response = self.client.post(
                '/api/bookings/',
                {
                    'resource_id': resource.pk,
                    'sport_id': sport.pk,
                    'start_datetime': start.isoformat(),
                    'end_datetime': (start + timedelta(hours=1)).isoformat(),
                    'participant_count': 4,
                    'booking_type': 'player',
                    'payment_method_used': method.pk,
                    'policy_accepted': 'true',
                    'payment_receipt': SimpleUploadedFile('receipt.pdf', b'%PDF-1.4 test'),
                },
            )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['rate_snapshot'], '200.00')
