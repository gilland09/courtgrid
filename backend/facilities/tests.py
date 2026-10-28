from decimal import Decimal

from rest_framework.test import APITestCase

from .models import BookableResource, Facility, FacilitySport, Sport
from .serializers import FacilitySportSerializer


class FacilityDiscoveryAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.basketball = Sport.objects.create(
            name='Basketball',
            slug='basketball',
        )
        cls.pickleball = Sport.objects.create(
            name='Pickleball',
            slug='pickleball',
        )
        cls.inactive_sport = Sport.objects.create(
            name='Inactive Sport',
            slug='inactive-sport',
            is_active=False,
        )
        cls.shared_facility = Facility.objects.create(
            name='Shared Sports Facility',
            is_demo_data=True,
            latitude='11.000000',
            longitude='124.000000',
        )
        cls.basketball_facility = Facility.objects.create(
            name='Basketball Facility',
        )
        cls.inactive_facility = Facility.objects.create(
            name='Inactive Facility',
            is_active=False,
        )

        FacilitySport.objects.create(
            facility=cls.shared_facility,
            sport=cls.basketball,
            hourly_rate='250.00',
        )
        FacilitySport.objects.create(
            facility=cls.shared_facility,
            sport=cls.pickleball,
            hourly_rate='150.00',
        )
        FacilitySport.objects.create(
            facility=cls.shared_facility,
            sport=cls.inactive_sport,
        )
        FacilitySport.objects.create(
            facility=cls.basketball_facility,
            sport=cls.basketball,
        )
        FacilitySport.objects.create(
            facility=cls.inactive_facility,
            sport=cls.basketball,
        )

        cls.active_resource = BookableResource.objects.create(
            facility=cls.shared_facility,
            name='Multipurpose Court',
            resource_type='multipurpose',
        )
        BookableResource.objects.create(
            facility=cls.shared_facility,
            name='Inactive Court',
            is_active=False,
        )

    def test_sports_endpoint_returns_only_active_sports(self):
        response = self.client.get('/api/sports/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [sport['slug'] for sport in response.data['results']],
            ['basketball', 'pickleball'],
        )

    def test_facilities_default_to_or_matching_and_include_nested_data(self):
        response = self.client.get(
            '/api/facilities/',
            {'sports': 'basketball,pickleball'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['match'], 'any')
        facilities = response.data['results']
        self.assertEqual(
            {facility['name'] for facility in facilities},
            {'Shared Sports Facility', 'Basketball Facility'},
        )
        shared = next(
            facility for facility in facilities
            if facility['name'] == 'Shared Sports Facility'
        )
        self.assertEqual(
            [sport['slug'] for sport in shared['supported_sports']],
            ['basketball', 'pickleball'],
        )
        self.assertEqual(
            [sport['slug'] for sport in shared['matching_sports']],
            ['basketball', 'pickleball'],
        )
        self.assertEqual(
            shared['resources'],
            [{
                'id': self.active_resource.id,
                'name': 'Multipurpose Court',
                'resource_type': 'multipurpose',
            }],
        )
        self.assertIsNone(shared['latitude'])
        self.assertIsNone(shared['longitude'])

    def test_all_matching_requires_each_requested_active_sport(self):
        response = self.client.get(
            '/api/courts/',
            {'sports': 'basketball,pickleball', 'match': 'all'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['match'], 'all')
        self.assertEqual(
            [facility['name'] for facility in response.data['results']],
            ['Shared Sports Facility'],
        )

    def test_invalid_match_mode_returns_bad_request(self):
        response = self.client.get(
            '/api/facilities/',
            {'sports': 'basketball', 'match': 'sometimes'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('match', response.data)

    def test_facility_detail_excludes_inactive_facilities(self):
        response = self.client.get(
            f'/api/facilities/{self.inactive_facility.id}/',
        )

        self.assertEqual(response.status_code, 404)

    def test_verified_real_facility_coordinates_are_serialized(self):
        facility = Facility.objects.create(
            name='Verified Facility',
            is_demo_data=False,
            is_verified=True,
            latitude='11.000000',
            longitude='124.000000',
        )
        response = self.client.get(f'/api/facilities/{facility.id}/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['latitude'], Decimal('11.000000'))
        self.assertEqual(response.data['longitude'], Decimal('124.000000'))

    def test_facility_sport_serializer_includes_sport_and_hourly_rate(self):
        facility_sport = FacilitySport.objects.get(
            facility=self.shared_facility,
            sport=self.basketball,
        )

        serialized = FacilitySportSerializer(facility_sport).data

        self.assertEqual(serialized['sport']['slug'], 'basketball')
        self.assertEqual(serialized['hourly_rate'], '250.00')
