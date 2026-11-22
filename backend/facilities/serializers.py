from rest_framework import serializers

from .models import BookableResource, Facility, FacilitySport, Sport


class SportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sport
        fields = ('id', 'name', 'slug', 'description')


class BookableResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookableResource
        fields = ('id', 'name', 'resource_type')


class FacilitySportSerializer(serializers.ModelSerializer):
    sport = SportSerializer(read_only=True)

    class Meta:
        model = FacilitySport
        fields = ('sport', 'hourly_rate')


class AvailabilitySearchSerializer(serializers.Serializer):
    date = serializers.DateField()
    sport = serializers.CharField(required=False, allow_blank=False)
    facility = serializers.IntegerField(required=False, min_value=1)
    mode = serializers.ChoiceField(
        choices=('serial', 'parallel'),
        default='parallel',
    )


class FacilitySerializer(serializers.ModelSerializer):
    latitude = serializers.SerializerMethodField()
    longitude = serializers.SerializerMethodField()
    supported_sports = serializers.SerializerMethodField()
    matching_sports = serializers.SerializerMethodField()
    court_count = serializers.SerializerMethodField()
    cover_photo_url = serializers.SerializerMethodField()
    resources = BookableResourceSerializer(many=True, read_only=True, source='active_resources')

    class Meta:
        model = Facility
        fields = (
            'id',
            'name',
            'address',
            'barangay',
            'latitude',
            'longitude',
            'facility_type',
            'capacity',
            'is_demo_data',
            'is_verified',
            'verification_status',
            'supported_sports',
            'matching_sports',
            'amenities',
            'court_count',
            'cover_photo_url',
            'resources',
        )

    def get_latitude(self, obj):
        if (
            obj.is_verified
            and obj.verification_status == Facility.VerificationStatus.VERIFIED
        ):
            return float(obj.latitude) if obj.latitude is not None else None
        return None

    def get_longitude(self, obj):
        if (
            obj.is_verified
            and obj.verification_status == Facility.VerificationStatus.VERIFIED
        ):
            return float(obj.longitude) if obj.longitude is not None else None
        return None

    def get_supported_sports(self, obj):
        facility_sports = getattr(obj, 'active_facility_sports', None)
        if facility_sports is None:
            facility_sports = obj.facility_sports.filter(
                is_active=True,
                sport__is_active=True,
            ).select_related('sport')
        return SportSerializer(
            [facility_sport.sport for facility_sport in facility_sports],
            many=True,
        ).data

    def get_matching_sports(self, obj):
        request = self.context.get('request')
        if request is None:
            return []

        selected_slugs = {
            slug.strip().lower()
            for slug in request.query_params.get('sports', '').split(',')
            if slug.strip()
        }
        if not selected_slugs:
            return []

        facility_sports = getattr(obj, 'active_facility_sports', None)
        if facility_sports is None:
            facility_sports = obj.facility_sports.filter(
                is_active=True,
                sport__is_active=True,
            ).select_related('sport')
        return SportSerializer(
            [
                facility_sport.sport
                for facility_sport in facility_sports
                if facility_sport.sport.slug in selected_slugs
            ],
            many=True,
        ).data

    def get_court_count(self, obj):
        resources = getattr(obj, 'active_resources', None)
        if resources is not None:
            return len(resources)
        return obj.resources.filter(is_active=True).count()

    def get_cover_photo_url(self, obj):
        photos = getattr(obj, 'ordered_photos', None)
        if photos is None:
            photos = list(obj.photos.all())
        cover = next((photo for photo in photos if photo.is_cover), None)
        photo = cover or (photos[0] if photos else None)
        return photo.image.url if photo else None
