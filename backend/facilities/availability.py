from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import (
    BookableResource,
    FacilityClosure,
    FacilityOperatingHours,
    FacilitySport,
    SportSchedule,
)


APPLICATION_TIMEZONE = ZoneInfo(settings.TIME_ZONE)


def local_datetime(value):
    if not timezone.is_aware(value):
        raise ValueError('Availability datetimes must be timezone-aware.')
    return timezone.localtime(value, APPLICATION_TIMEZONE)


def is_within_operating_hours(resource, start_datetime, end_datetime):
    local_start = local_datetime(start_datetime)
    local_end = local_datetime(end_datetime)
    booking_date = local_start.date()

    return FacilityOperatingHours.objects.filter(
        facility=resource.facility,
        day_of_week=local_start.weekday(),
        start_time__lte=local_start.time().replace(tzinfo=None),
        end_time__gte=local_end.time().replace(tzinfo=None),
    ).filter(
        Q(effective_from__isnull=True) | Q(effective_from__lte=booking_date),
        Q(effective_until__isnull=True) | Q(effective_until__gte=booking_date),
    ).exists()


def is_within_sport_schedule(resource, facility_sport, start_datetime, end_datetime):
    local_start = local_datetime(start_datetime)
    local_end = local_datetime(end_datetime)
    booking_date = local_start.date()
    common_filters = {
        'facility_sport': facility_sport,
        'day_of_week': local_start.weekday(),
    }
    effective_filters = (
        Q(effective_from__isnull=True) | Q(effective_from__lte=booking_date),
        Q(effective_until__isnull=True) | Q(effective_until__gte=booking_date),
    )
    schedules = SportSchedule.objects.filter(**common_filters).filter(*effective_filters)
    resource_schedules = schedules.filter(resource=resource)
    if resource_schedules.exists():
        applicable_schedules = resource_schedules
    else:
        applicable_schedules = schedules.filter(resource__isnull=True)
    return applicable_schedules.filter(
        start_time__lte=local_start.time().replace(tzinfo=None),
        end_time__gte=local_end.time().replace(tzinfo=None),
    ).exists()


def is_closed(resource, start_datetime, end_datetime):
    return FacilityClosure.objects.filter(
        facility=resource.facility,
        start_datetime__lt=end_datetime,
        end_datetime__gt=start_datetime,
    ).filter(
        Q(resource__isnull=True) | Q(resource=resource),
    ).exists()


def has_confirmed_booking(resource, start_datetime, end_datetime):
    from bookings.models import Booking

    return Booking.objects.filter(
        resource=resource,
        status=Booking.Status.CONFIRMED,
        start_datetime__lt=end_datetime,
        end_datetime__gt=start_datetime,
    ).exists()


def slot_unavailability_reason(resource, facility_sport, start_datetime, end_datetime):
    local_start = local_datetime(start_datetime)
    local_end = local_datetime(end_datetime)
    if local_start.date() != local_end.date():
        return 'Bookings cannot cross midnight in the application timezone.'
    if not is_within_operating_hours(resource, start_datetime, end_datetime):
        return 'The requested time is outside facility operating hours.'
    if not is_within_sport_schedule(resource, facility_sport, start_datetime, end_datetime):
        return 'The requested time is outside the sport schedule.'
    if is_closed(resource, start_datetime, end_datetime):
        return 'The requested time overlaps a facility or resource closure.'
    return None


def is_slot_available(resource, facility_sport, start_datetime, end_datetime):
    if slot_unavailability_reason(
        resource,
        facility_sport,
        start_datetime,
        end_datetime,
    ) is not None:
        return False
    return not has_confirmed_booking(resource, start_datetime, end_datetime)


def make_local_slot(booking_date, hour):
    start_datetime = datetime.combine(
        booking_date,
        time(hour=hour),
        tzinfo=APPLICATION_TIMEZONE,
    )
    end_datetime = start_datetime + timedelta(hours=1)
    return start_datetime, end_datetime


def active_resource_offerings(facility_id=None, sport=None):
    queryset = FacilitySport.objects.filter(
        is_active=True,
        facility__is_active=True,
        sport__is_active=True,
    ).select_related('facility', 'sport')
    if facility_id is not None:
        queryset = queryset.filter(facility_id=facility_id)
    if sport is not None:
        queryset = queryset.filter(sport=sport)
    return queryset


def active_resources_for_offering(facility_sport):
    return BookableResource.objects.filter(
        facility_id=facility_sport.facility_id,
        is_active=True,
        resource_sports__facility_sport=facility_sport,
    ).select_related('facility').distinct()
