import logging
from datetime import datetime, time, timedelta

import requests
from django.conf import settings
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .availability import (
    APPLICATION_TIMEZONE,
    active_resource_offerings,
    evaluate_serial_availability,
    evaluate_serial_slots,
)
from .availability_client import AvailabilityServiceError, fetch_parallel_availability
from .models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilityOperatingHours,
    FacilityPhoto,
    FacilityPaymentMethod,
    FacilitySport,
    Sport,
    SportSchedule,
)
from .serializers import (
    AvailabilitySearchSerializer,
    AvailabilityRangeSerializer,
    FacilitySerializer,
    FacilityPaymentMethodSerializer,
    SportSerializer,
)
from bookings.models import Booking, UserProfile

logger = logging.getLogger(__name__)


class FacilityDiscoveryQuerysetMixin:
    def get_match_mode(self):
        match = self.request.query_params.get('match', 'any').strip().lower()
        if match not in {'any', 'all'}:
            raise ValidationError({'match': 'Use either "any" or "all".'})
        return match

    def get_requested_sports(self):
        return list(dict.fromkeys(
            slug.strip().lower()
            for slug in self.request.query_params.get('sports', '').split(',')
            if slug.strip()
        ))

    def get_facility_queryset(self, apply_sport_filter=True):
        active_facility_sports = FacilitySport.objects.filter(
            is_active=True,
            sport__is_active=True,
        ).select_related('sport')
        queryset = Facility.objects.filter(
            is_active=True,
            is_verified=True,
            verification_status=Facility.VerificationStatus.VERIFIED,
        ).prefetch_related(
            Prefetch(
                'facility_sports',
                queryset=active_facility_sports,
                to_attr='active_facility_sports',
            ),
            Prefetch(
                'resources',
                queryset=BookableResource.objects.filter(
                    is_active=True,
                ).order_by('display_order', 'name'),
                to_attr='active_resources',
            ),
            Prefetch(
                'photos',
                queryset=FacilityPhoto.objects.order_by(
                    '-is_cover',
                    'display_order',
                    'pk',
                ),
                to_attr='ordered_photos',
            ),
            Prefetch(
                'payment_methods',
                queryset=FacilityPaymentMethod.objects.filter(is_active=True),
                to_attr='active_payment_methods',
            ),
        )

        match = self.get_match_mode()
        sports = self.get_requested_sports()
        if not apply_sport_filter or not sports:
            return queryset

        supported_sport_filter = Q(
            facility_sports__is_active=True,
            facility_sports__sport__is_active=True,
        )
        if match == 'all':
            return (
                queryset.annotate(
                    _requested_sport_count=Count(
                        'facility_sports__sport',
                        filter=supported_sport_filter
                        & Q(facility_sports__sport__slug__in=sports),
                        distinct=True,
                    )
                )
                .filter(_requested_sport_count=len(sports))
            )
        return queryset.filter(
            supported_sport_filter,
            facility_sports__sport__slug__in=sports,
        ).distinct()


class SportListView(ListAPIView):
    serializer_class = SportSerializer
    queryset = Sport.objects.filter(is_active=True)

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return Response({'results': response.data})


class FacilityListView(FacilityDiscoveryQuerysetMixin, ListAPIView):
    serializer_class = FacilitySerializer

    def get_queryset(self):
        return self.get_facility_queryset()

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return Response({
            'results': response.data,
            'match': self.get_match_mode(),
        })


class FacilityDetailView(FacilityDiscoveryQuerysetMixin, RetrieveAPIView):
    serializer_class = FacilitySerializer

    def get_queryset(self):
        return self.get_facility_queryset(apply_sport_filter=False)


def facility_detail_view(request, pk):
    from bookings.live_sync import availability_version
    facility = get_object_or_404(
        Facility.objects.filter(
            is_active=True,
            is_verified=True,
            verification_status=Facility.VerificationStatus.VERIFIED,
        ).prefetch_related(
            Prefetch(
                'facility_sports',
                queryset=FacilitySport.objects.filter(
                    is_active=True,
                    sport__is_active=True,
                ).select_related('sport'),
                to_attr='active_facility_sports',
            ),
            Prefetch(
                'operating_hours',
                queryset=FacilityOperatingHours.objects.order_by(
                    'day_of_week',
                    'start_time',
                ),
                to_attr='ordered_operating_hours',
            ),
            Prefetch(
                'photos',
                queryset=FacilityPhoto.objects.order_by(
                    '-is_cover',
                    'display_order',
                    'pk',
                ),
                to_attr='ordered_photos',
            ),
        ),
        pk=pk,
    )
    active_resources = list(
        facility.resources.filter(is_active=True)
        .prefetch_related('sports__sport')
        .order_by('display_order', 'name')
    )
    facility_resources = [
        {
            'id': resource.pk,
            'name': resource.name,
            'capacity': (
                resource.capacity
                if resource.capacity is not None
                else facility.capacity
            ),
            'hourly_rate': (
                str(resource.hourly_rate)
                if resource.hourly_rate is not None
                else None
            ),
        }
        for resource in active_resources
    ]
    facility_courts = []
    for resource in active_resources:
        resource_sports = list(
            resource.sports.select_related('sport').order_by('sport__name')
        )
        rates = []
        for facility_sport in resource_sports:
            amount = resource.effective_hourly_rate_for(facility_sport)
            rates.append({
                'sport': facility_sport.sport.name,
                'amount': amount,
                'has_amount': amount is not None,
            })
        distinct_rates = {item['amount'] for item in rates}
        effective_rate = (
            next(iter(distinct_rates))
            if len(distinct_rates) == 1
            else resource.effective_hourly_rate if not rates else None
        )
        facility_courts.append({
            'resource': resource,
            'sports': [item.sport.name for item in resource_sports],
            'rates': rates,
            'hourly_rate': effective_rate,
            'has_rate': effective_rate is not None,
        })
    sport_rates = {}
    for facility_sport in facility.active_facility_sports:
        rate = facility_sport.hourly_rate
        if rate is None:
            rate = facility.default_hourly_rate
        sport_rates[str(facility_sport.sport_id)] = (
            str(rate) if rate is not None else None
        )
    phone_number = ''
    if request.user.is_authenticated:
        phone_number = (
            UserProfile.objects.filter(user=request.user)
            .values_list('phone_number', flat=True)
            .first()
            or ''
        )
    payment_methods = list(facility.payment_methods.filter(is_active=True))
    return render(request, 'facility_detail.html', {
        'facility': facility,
        'available_payment_methods': facility.available_payment_methods,
        'payment_methods': payment_methods,
        'payment_methods_data': list(FacilityPaymentMethodSerializer(payment_methods, many=True).data),
        'facility_sports': facility.active_facility_sports,
        'operating_hours': facility.ordered_operating_hours,
        'today': timezone.localdate().isoformat(),
        'facility_resources': facility_resources,
        'facility_courts': facility_courts,
        'facility_photos': facility.ordered_photos,
        'amenities': facility.amenities,
        'sport_rates': sport_rates,
        'booker_email': request.user.email if request.user.is_authenticated else '',
        'booker_phone': phone_number,
        'live_version': availability_version(facility.pk),
    })


class AvailabilitySearchView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        return self.search(request.query_params)

    def search(self, params):
        serializer = AvailabilitySearchSerializer(data=params)
        serializer.is_valid(raise_exception=True)
        search_date = serializer.validated_data['date']
        if abs((search_date - timezone.localdate()).days) > 31:
            raise ValidationError({'date': 'Availability can only be searched within 31 days.'})
        facility_id = serializer.validated_data.get('facility')
        sport_filter = None

        sport_value = serializer.validated_data.get('sport')
        if sport_value is not None:
            sport_queryset = Sport.objects.filter(is_active=True)
            if sport_value.isdecimal():
                sport_filter = sport_queryset.filter(pk=int(sport_value)).first()
            else:
                sport_filter = sport_queryset.filter(slug=sport_value.strip().lower()).first()
            if sport_filter is None:
                raise ValidationError({'sport': 'No active sport matches this value.'})

        offerings = active_resource_offerings(
            facility_id=facility_id,
            sport=sport_filter,
        )
        if offerings.values_list('resources__pk', flat=True).distinct().count() > 50:
            raise ValidationError({
                'detail': 'Availability requests are limited to 50 courts.',
            })
        facility_ids = offerings.values_list('facility_id', flat=True).distinct()
        if facility_ids.count() > 50:
            raise ValidationError({
                'detail': 'Availability requests are limited to 50 facilities.',
            })
        if serializer.validated_data['mode'] == 'serial':
            results = evaluate_serial_availability(offerings, search_date)
            slots = evaluate_serial_slots(offerings, search_date)
            return Response({
                'timezone': settings.TIME_ZONE,
                'mode': 'serial',
                'results': results,
                'slots': slots,
            })

        facilities = list(Facility.objects.filter(
            pk__in=facility_ids,
            is_active=True,
        ).order_by('pk'))
        facility_sport_ids = offerings.values_list('pk', flat=True)
        schedule_queryset = SportSchedule.objects.filter(
            facility_sport_id__in=facility_sport_ids,
            day_of_week=search_date.weekday(),
        ).filter(
            Q(effective_from__isnull=True) | Q(effective_from__lte=search_date),
            Q(effective_until__isnull=True) | Q(effective_until__gte=search_date),
        ).select_related('facility_sport').order_by('pk')
        if schedule_queryset.count() > 1000:
            raise ValidationError({
                'detail': 'Availability requests are limited to 1,000 schedules.',
            })
        if (
            FacilityOperatingHours.objects.filter(facility_id__in=facility_ids)
            .values('facility_id')
            .annotate(total=Count('pk'))
            .filter(total__gt=100)
            .exists()
        ):
            raise ValidationError({
                'detail': 'A facility may have at most 100 operating-hour records.',
            })
        schedules = list(schedule_queryset)
        day_start = timezone.make_aware(
            datetime.combine(search_date, time.min),
            APPLICATION_TIMEZONE,
        )
        day_end = day_start + timedelta(days=1)
        closure_queryset = FacilityClosure.objects.filter(
            facility_id__in=facility_ids,
            start_datetime__lt=day_end,
            end_datetime__gt=day_start,
        ).select_related('facility', 'resource').order_by('pk')
        if closure_queryset.count() > 1200:
            raise ValidationError({
                'detail': 'Availability requests are limited to 1,200 closures.',
            })
        closures = list(closure_queryset)
        resource_ids = BookableResource.objects.filter(
            facility_id__in=facility_ids,
            is_active=True,
            resource_sports__facility_sport_id__in=facility_sport_ids,
        ).values_list('pk', flat=True).distinct()
        booking_queryset = Booking.objects.filter(
            resource_id__in=resource_ids,
            status__in=(Booking.Status.CONFIRMED, Booking.Status.PENDING_VERIFICATION),
            start_datetime__lt=day_end,
            end_datetime__gt=day_start,
        ).select_related('resource').order_by('pk')
        if booking_queryset.count() > 1200:
            raise ValidationError({
                'detail': 'Availability requests are limited to 1,200 bookings.',
            })
        existing_bookings = list(booking_queryset)
        try:
            service_response = fetch_parallel_availability(
                target_date=search_date,
                facilities=facilities,
                closures=closures,
                schedules=schedules,
                existing_bookings=existing_bookings,
            )
        except (AvailabilityServiceError, requests.Timeout) as exc:
            logger.warning(
                'FastAPI availability service failed; falling back to serial evaluation: %s',
                exc,
            )
            results = evaluate_serial_availability(offerings, search_date)
            slots = evaluate_serial_slots(offerings, search_date)
            return Response({
                'timezone': settings.TIME_ZONE,
                'mode': 'serial',
                'requested_mode': 'parallel',
                'fallback': True,
                'results': results,
                'slots': slots,
            })

        results = [
            {
                **slot,
                'start_datetime': datetime.fromisoformat(slot['start_datetime']),
                'end_datetime': datetime.fromisoformat(slot['end_datetime']),
            }
            for slot in service_response['available_slots']
        ]
        schedule_slots = service_response.get('slots') or [
            {**slot, 'availability': 'available', 'reason': ''}
            for slot in service_response['available_slots']
        ]
        schedule_slots = [
            {
                **slot,
                'start_datetime': datetime.fromisoformat(slot['start_datetime']),
                'end_datetime': datetime.fromisoformat(slot['end_datetime']),
            }
            for slot in schedule_slots
        ]

        return Response({
            'timezone': settings.TIME_ZONE,
            'mode': 'parallel',
            'fallback': False,
            'parallel_elapsed_time': service_response['parallel_elapsed_time'],
            'results': results,
            'slots': schedule_slots,
        })


class AvailabilityRangeView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = AvailabilityRangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        court_ids = set(data['court_ids'])
        courts = list(BookableResource.objects.filter(
            pk__in=court_ids, is_active=True, facility__is_active=True,
        ))
        if len(courts) != len(court_ids) or len({court.facility_id for court in courts}) != 1:
            raise ValidationError({'court_ids': 'Select active courts from one facility.'})
        available, skipped, modes = [], [], []
        current_date = data['start_date']
        while current_date <= data['end_date']:
            params = {'date': current_date.isoformat(), 'facility': courts[0].facility_id}
            if data.get('sport'):
                params['sport'] = data['sport']
            response = AvailabilitySearchView().search(params)
            modes.append(response.data['mode'])
            for slot in response.data['slots']:
                if slot['resource_id'] not in court_ids:
                    continue
                start = timezone.localtime(slot['start_datetime'], APPLICATION_TIMEZONE).time()
                end = timezone.localtime(slot['end_datetime'], APPLICATION_TIMEZONE).time()
                if data.get('start_time') and (
                    start < data['start_time'] or end > data['end_time']
                ):
                    continue
                (available if slot['availability'] == 'available' else skipped).append(slot)
            current_date += timedelta(days=1)
        return Response({
            'timezone': settings.TIME_ZONE,
            'available_slots': available,
            'skipped_slots': skipped,
            'modes': modes,
        })
