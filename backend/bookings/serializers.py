import re
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from facilities.models import BookableResource, Sport

from .models import Booking


class BookingSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    resource_id = serializers.IntegerField(read_only=True)
    sport_id = serializers.IntegerField(read_only=True)
    facility_name = serializers.CharField(source='resource.facility.name', read_only=True)
    resource_name = serializers.CharField(source='resource.name', read_only=True)
    sport_name = serializers.CharField(source='sport.name', read_only=True)

    class Meta:
        model = Booking
        fields = (
            'id',
            'user',
            'resource_id',
            'facility_name',
            'resource_name',
            'sport_id',
            'sport_name',
            'start_datetime',
            'end_datetime',
            'participant_count',
            'participant_names',
            'contact_email',
            'contact_phone',
            'status',
            'rate_snapshot',
            'total_price',
            'currency',
            'created_at',
            'updated_at',
            'cancelled_at',
        )
        read_only_fields = fields


class CreateBookingSerializer(serializers.Serializer):
    resource_id = serializers.PrimaryKeyRelatedField(
        queryset=BookableResource.objects.all(),
        source='resource',
    )
    sport_id = serializers.PrimaryKeyRelatedField(
        queryset=Sport.objects.all(),
        source='sport',
    )
    start_datetime = serializers.DateTimeField()
    end_datetime = serializers.DateTimeField()
    participant_count = serializers.IntegerField(min_value=1)
    participant_names = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
    )
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True, max_length=32)

    def validate(self, attrs):
        start_datetime = attrs['start_datetime']
        end_datetime = attrs['end_datetime']

        if not timezone.is_aware(start_datetime) or not timezone.is_aware(end_datetime):
            raise serializers.ValidationError(
                'Start and end datetimes must include a timezone.'
            )
        if start_datetime <= timezone.now():
            raise serializers.ValidationError({
                'start_datetime': 'Booking must start in the future.'
            })
        local_start = timezone.localtime(start_datetime)
        local_end = timezone.localtime(end_datetime)
        if any((
            local_start.minute,
            local_start.second,
            local_start.microsecond,
            local_end.minute,
            local_end.second,
            local_end.microsecond,
        )):
            raise serializers.ValidationError(
                'Bookings must align to exact whole hours.'
            )
        if end_datetime - start_datetime != timedelta(hours=1):
            raise serializers.ValidationError(
                'Bookings must be exactly one hour long.'
            )
        if local_start.date() != local_end.date():
            raise serializers.ValidationError(
                'Bookings cannot cross midnight in the application timezone.'
            )

        resource = attrs['resource']
        sport = attrs['sport']
        if not resource.is_active or not resource.facility.is_active:
            raise serializers.ValidationError({
                'resource_id': 'The requested resource is not currently bookable.'
            })
        if not sport.is_active:
            raise serializers.ValidationError({
                'sport_id': 'The requested sport is not currently bookable.'
            })
        facility_sport = resource.facility.facility_sports.filter(
            sport=sport,
            is_active=True,
        ).first()
        if facility_sport is None:
            raise serializers.ValidationError({
                'sport_id': 'This facility does not currently support the requested sport.'
            })
        if not resource.resource_sports.filter(facility_sport=facility_sport).exists():
            raise serializers.ValidationError({
                'sport_id': 'This resource is not configured for the requested sport.'
            })

        capacity = (
            resource.capacity
            if resource.capacity is not None
            else resource.facility.capacity
        )
        if capacity is not None and attrs['participant_count'] > capacity:
            raise serializers.ValidationError({
                'participant_count': f'Participant count cannot exceed the capacity of {capacity}.'
            })

        return attrs


class BookingSlotInputSerializer(serializers.Serializer):
    resource_id = serializers.PrimaryKeyRelatedField(
        queryset=BookableResource.objects.all(),
    )
    start_datetime = serializers.DateTimeField()
    end_datetime = serializers.DateTimeField()


class BatchCreateBookingSerializer(serializers.Serializer):
    sport_id = serializers.PrimaryKeyRelatedField(queryset=Sport.objects.all())
    participant_count = serializers.IntegerField(min_value=1)
    contact_email = serializers.EmailField()
    contact_phone = serializers.CharField(max_length=32)
    participant_names = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
    )
    slots = BookingSlotInputSerializer(many=True, allow_empty=False, max_length=20)

    def validate_slots(self, slots):
        keys = [
            (slot['resource_id'].pk, slot['start_datetime'])
            for slot in slots
        ]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError(
                'A court and start time can only appear once in a booking request.'
            )
        return slots

    def validate_contact_phone(self, value):
        if (
            not value.strip()
            or len([character for character in value if character.isdigit()]) < 7
            or not re.fullmatch(r'\+?[0-9][0-9\s().-]{5,30}', value.strip())
        ):
            raise serializers.ValidationError('Enter a valid phone number with at least 7 digits.')
        return value.strip()
