from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from facilities.models import BookableResource, Sport

from .models import Booking


class BookingSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    resource_id = serializers.IntegerField(read_only=True)
    sport_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Booking
        fields = (
            'id',
            'user',
            'resource_id',
            'sport_id',
            'start_datetime',
            'end_datetime',
            'participant_count',
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
