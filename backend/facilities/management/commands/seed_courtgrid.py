from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, UserProfile
from facilities.models import (
    BookableResource,
    Facility,
    FacilityOperatingHours,
    FacilitySport,
    ResourceSport,
    Sport,
    SportSchedule,
)


SEED_SOURCE = 'Project owner-verified facility information'
SPORTS = (
    ('Basketball', 'basketball'),
    ('Volleyball', 'volleyball'),
    ('Pickleball', 'pickleball'),
    ('Badminton', 'badminton'),
)
FACILITIES = (
    {
        'name': 'Naval Municipal Gymnasium',
        'address': 'P. Inocentes Garcia (Pob.), Naval, Biliran',
        'barangay': 'P. Inocentes Garcia (Pob.)',
        'capacity': 30,
        'latitude': '11.560800',
        'longitude': '124.397200',
        'sports': ('Basketball', 'Volleyball'),
        'courts': 2,
        'owner_username': 'owner_municipal',
        'owner_name': 'Naval LGU Sports',
        'wallet_account_name': '',
        'gcash_number': '',
        'maya_number': '',
        'payout_qr_label': '',
    },
    {
        'name': 'BiPSU Sports Complex',
        'address': 'Calumpang, Naval, Biliran',
        'barangay': 'Calumpang',
        'capacity': 30,
        'latitude': '11.564200',
        'longitude': '124.399100',
        'sports': ('Basketball', 'Volleyball', 'Pickleball'),
        'courts': 3,
        'owner_username': 'owner_bipsu',
        'owner_name': 'BiPSU Athletics Office',
        'wallet_account_name': '',
        'gcash_number': '',
        'maya_number': '',
        'payout_qr_label': '',
    },
    {
        'name': 'Caneja Turf & Pickleball Center',
        'address': 'Santissimo Rosario, Naval, Biliran',
        'barangay': 'Santissimo Rosario',
        'capacity': 24,
        'latitude': '11.558500',
        'longitude': '124.395800',
        'sports': ('Pickleball', 'Badminton'),
        'courts': 2,
        'owner_username': 'owner_caneja',
        'owner_name': 'Caneja Turf Management',
        'wallet_account_name': '',
        'gcash_number': '',
        'maya_number': '',
        'payout_qr_label': '',
    },
    {
        'name': 'Santissimo Rosario Barangay Court',
        'address': 'Santissimo Rosario, Naval, Biliran',
        'barangay': 'Santissimo Rosario',
        'capacity': 20,
        'latitude': '11.562000',
        'longitude': '124.401500',
        'sports': ('Basketball',),
        'courts': 1,
        'owner_username': 'owner_santissimo',
        'owner_name': 'Brgy. Santissimo Council',
        'wallet_account_name': '',
        'gcash_number': '',
        'maya_number': '',
        'payout_qr_label': '',
    },
    {
        'name': "Tonio's Dink District",
        'address': 'Atipolo, Naval, Biliran',
        'barangay': 'Atipolo',
        'capacity': 30,
        'latitude': '11.554500',
        'longitude': '124.402500',
        'sports': ('Pickleball',),
        'courts': 3,
        'owner_username': 'owner_tonio',
        'owner_name': 'Tonio Partner',
        'wallet_account_name': '',
        'gcash_number': '',
        'maya_number': '',
        'payout_qr_label': '',
    },
)

SPORT_RATES = {
    'Basketball': '250.00',
    'Volleyball': '250.00',
    'Pickleball': '200.00',
    'Badminton': '200.00',
}


class Command(BaseCommand):
    help = 'Create or update the CourtGrid Naval demo facilities and schedules.'

    @transaction.atomic
    def handle(self, *args, **options):
        user_model = get_user_model()
        owners = {}
        for facility_data in FACILITIES:
            owner, _ = user_model.objects.get_or_create(
                username=facility_data['owner_username'],
                defaults={
                    'email': f"{facility_data['owner_username']}@courtgrid.local",
                },
            )
            first_name, _, last_name = facility_data['owner_name'].partition(' ')
            owner.first_name = first_name
            owner.last_name = last_name
            owner.set_password('owner123')
            owner.save(update_fields=('first_name', 'last_name', 'password'))
            UserProfile.objects.update_or_create(
                user=owner,
                defaults={
                    'role': UserProfile.Role.COURT_OWNER,
                    'phone_number': '',
                },
            )
            owners[owner.username] = owner

        sports = {}
        for name, slug in SPORTS:
            sports[name], _ = Sport.objects.update_or_create(
                slug=slug,
                defaults={'name': name, 'is_active': True},
            )

        for facility_data in FACILITIES:
            owner = owners[facility_data['owner_username']]
            facility, _ = Facility.objects.update_or_create(
                name=facility_data['name'],
                defaults={
                    'owner': owner,
                    'wallet_account_name': facility_data['wallet_account_name'],
                    'gcash_number': facility_data['gcash_number'],
                    'maya_number': facility_data['maya_number'],
                    'payout_qr_label': facility_data['payout_qr_label'],
                    'address': facility_data['address'],
                    'barangay': facility_data['barangay'],
                    'latitude': facility_data['latitude'],
                    'longitude': facility_data['longitude'],
                    'facility_type': 'Sports facility',
                    'capacity': facility_data['capacity'],
                    'is_active': True,
                    'is_demo_data': False,
                    'is_verified': True,
                    'data_source': SEED_SOURCE,
                    'verified_by': 'Project owner',
                    'verification_date': None,
                },
            )

            facility_sports = []
            for sport_name in facility_data['sports']:
                facility_sport, _ = FacilitySport.objects.update_or_create(
                    facility=facility,
                    sport=sports[sport_name],
                    defaults={
                        'is_active': True,
                        'hourly_rate': SPORT_RATES[sport_name],
                    },
                )
                facility_sports.append(facility_sport)

            resources = []
            for court_number in range(1, facility_data['courts'] + 1):
                resource, _ = BookableResource.objects.update_or_create(
                    facility=facility,
                    name=f'Court {court_number}',
                    defaults={
                        'resource_type': 'Court',
                        'capacity': min(facility_data['capacity'], 30),
                        'is_active': True,
                    },
                )
                resources.append(resource)

            for resource in resources:
                for facility_sport in facility_sports:
                    ResourceSport.objects.get_or_create(
                        resource=resource,
                        facility_sport=facility_sport,
                    )

            for day_of_week in range(7):
                FacilityOperatingHours.objects.update_or_create(
                    facility=facility,
                    day_of_week=day_of_week,
                    start_time=time(8),
                    end_time=time(21),
                    defaults={},
                )
                for facility_sport in facility_sports:
                    SportSchedule.objects.update_or_create(
                        facility_sport=facility_sport,
                        resource=None,
                        day_of_week=day_of_week,
                        start_time=time(8),
                        end_time=time(21),
                        defaults={},
                    )

        self.seed_demo_bookings(owners, user_model)
        for booking in Booking.objects.all().iterator():
            booking.save()

        self.stdout.write(self.style.SUCCESS(
            'CourtGrid facilities, sports, resources, and weekly schedules are ready.'
        ))

    @staticmethod
    def seed_demo_bookings(owners, user_model):
        demo_customer, _ = user_model.objects.get_or_create(
            username='demo_player',
            defaults={
                'email': 'demo_player@courtgrid.local',
                'first_name': 'Demo',
                'last_name': 'Player',
            },
        )
        UserProfile.objects.update_or_create(
            user=demo_customer,
            defaults={'role': UserProfile.Role.CUSTOMER},
        )
        demo_slots = (
            ('BiPSU Sports Complex', 'Basketball', 'Court 3', time(18)),
            ("Tonio's Dink District", 'Pickleball', 'Court 3', time(19)),
        )
        local_tomorrow = timezone.localdate() + timedelta(days=1)
        for facility_name, sport_name, resource_name, start_time in demo_slots:
            facility_data = next(item for item in FACILITIES if item['name'] == facility_name)
            owner = owners[facility_data['owner_username']]
            facility = Facility.objects.get(name=facility_name, owner=owner)
            if Booking.objects.filter(
                user=demo_customer,
                resource__facility=facility,
                status=Booking.Status.CONFIRMED,
            ).exists():
                continue
            resource = BookableResource.objects.get(
                facility=facility,
                name=resource_name,
                is_active=True,
            )
            sport = Sport.objects.get(name=sport_name, is_active=True)
            facility_sport = FacilitySport.objects.get(
                facility=facility,
                sport=sport,
                is_active=True,
            )
            hourly_rate = facility_sport.hourly_rate or facility.default_hourly_rate
            start_datetime = timezone.make_aware(
                datetime.combine(local_tomorrow, start_time),
                timezone.get_current_timezone(),
            )
            for day_offset in range(14):
                candidate_start = start_datetime + timedelta(days=day_offset)
                candidate_end = candidate_start + timedelta(hours=1)
                has_overlap = Booking.objects.filter(
                    resource=resource,
                    status=Booking.Status.CONFIRMED,
                    start_datetime__lt=candidate_end,
                    end_datetime__gt=candidate_start,
                ).exists()
                if not has_overlap:
                    Booking.objects.create(
                        user=demo_customer,
                        resource=resource,
                        sport=sport,
                        start_datetime=candidate_start,
                        end_datetime=candidate_end,
                        participant_count=2,
                        participant_names='Demo Player, Alex CourtGrid',
                        contact_email=demo_customer.email,
                        contact_phone='+639171234567',
                        status=Booking.Status.CONFIRMED,
                        rate_snapshot=hourly_rate,
                        total_price=hourly_rate,
                        payment_method=(
                            Booking.PaymentMethod.GCASH
                            if sport_name == 'Basketball'
                            else Booking.PaymentMethod.MAYA
                        ),
                    )
                    break
