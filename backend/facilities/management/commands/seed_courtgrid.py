from datetime import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from bookings.models import UserProfile
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
        owner, _ = user_model.objects.get_or_create(
            username='owner_tonio',
            defaults={
                'email': 'owner_tonio@courtgrid.local',
                'first_name': 'Tonio',
                'last_name': 'Owner',
            },
        )
        owner.set_password('owner123')
        owner.save(update_fields=('password',))
        UserProfile.objects.update_or_create(
            user=owner,
            defaults={
                'role': UserProfile.Role.COURT_OWNER,
                'phone_number': '',
            },
        )

        sports = {}
        for name, slug in SPORTS:
            sports[name], _ = Sport.objects.update_or_create(
                slug=slug,
                defaults={'name': name, 'is_active': True},
            )

        for facility_data in FACILITIES:
            facility, _ = Facility.objects.update_or_create(
                name=facility_data['name'],
                defaults={
                    'owner': owner,
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

        self.stdout.write(self.style.SUCCESS(
            'CourtGrid facilities, sports, resources, and weekly schedules are ready.'
        ))
