import hashlib
import json
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q, Sum
from django.template.loader import render_to_string
from django.utils import timezone

from facilities.models import (
    BookableResource, Facility, FacilityClosure, FacilityOperatingHours,
    FacilitySport, ResourceSport, SportSchedule,
)

from .batches import group_bookings_into_batches
from .models import Booking
from .serializers import BookingSerializer


def _update_hash(digest, label, queryset, *extra_fields):
    fields = [field.attname for field in queryset.model._meta.concrete_fields]
    digest.update(label.encode('utf-8'))
    for row in queryset.order_by('pk').values_list(*fields, *extra_fields).iterator():
        digest.update(json.dumps(row, cls=DjangoJSONEncoder, separators=(',', ':')).encode('utf-8'))
        digest.update(b'\n')


def booking_version(bookings):
    digest = hashlib.sha256()
    _update_hash(digest, 'bookings', bookings, 'user__username', 'user__first_name',
                 'user__last_name', 'resource__name', 'resource__facility__name', 'sport__name')
    return digest.hexdigest()


def dashboard_version(user, admin=False):
    facilities = Facility.objects.all() if admin else Facility.objects.filter(owner=user)
    bookings = Booking.objects.all() if admin else Booking.objects.filter(resource__facility__owner=user)
    digest = hashlib.sha256(booking_version(bookings).encode('ascii'))
    _update_hash(digest, 'facilities', facilities)
    _update_hash(digest, 'courts', BookableResource.objects.filter(facility__in=facilities))
    _update_hash(digest, 'closures', FacilityClosure.objects.filter(facility__in=facilities))
    if admin:
        now = timezone.now()
        digest.update(timezone.localdate(now).isoformat().encode('ascii'))
        _update_hash(digest, 'active-closures', FacilityClosure.objects.filter(
            facility__in=facilities, start_datetime__lte=now, end_datetime__gte=now,
        ))
        _update_hash(digest, 'facility-owners', facilities,
                     'owner__username', 'owner__first_name', 'owner__last_name')
    return digest.hexdigest()


def availability_version(facility_id):
    digest = hashlib.sha256()
    _update_hash(digest, 'facility', Facility.objects.filter(pk=facility_id))
    _update_hash(digest, 'courts', BookableResource.objects.filter(facility_id=facility_id))
    _update_hash(digest, 'sports', FacilitySport.objects.filter(facility_id=facility_id), 'sport__is_active')
    _update_hash(digest, 'court-sports', ResourceSport.objects.filter(resource__facility_id=facility_id))
    _update_hash(digest, 'hours', FacilityOperatingHours.objects.filter(facility_id=facility_id))
    _update_hash(digest, 'schedules', SportSchedule.objects.filter(facility_sport__facility_id=facility_id))
    _update_hash(digest, 'closures', FacilityClosure.objects.filter(facility_id=facility_id))
    _update_hash(digest, 'bookings', Booking.objects.filter(resource__facility_id=facility_id))
    return digest.hexdigest()


def dashboard_data(request, bookings, dashboard, settlement_status='all'):
    ordered = bookings.select_related('user', 'resource__facility', 'sport').order_by('start_datetime')
    batches = group_bookings_into_batches(ordered)
    if dashboard == 'admin' and settlement_status in ('pending', 'paid'):
        if settlement_status == 'pending':
            batches = [batch for batch in batches if any(
                item.status == Booking.Status.CONFIRMED and item.payment_status == Booking.PaymentStatus.PAID
                and not item.platform_fee_collected for item in batch.bookings
            )]
        else:
            batches = [batch for batch in batches if any(
                item.status == Booking.Status.CONFIRMED and item.platform_fee_collected
                for item in batch.bookings
            )]
    confirmed = bookings.filter(status=Booking.Status.CONFIRMED)
    paid = Q(payment_status=Booking.PaymentStatus.PAID)
    totals = confirmed.aggregate(
        gross=Sum('total_price', filter=Q() if dashboard == 'admin' else paid),
        platform_fee=Sum('platform_fee_amount', filter=paid & Q(platform_fee_collected=False)),
        platform_fee_settled=Sum('platform_fee_amount', filter=paid & Q(platform_fee_collected=True)),
        owner_payout=Sum('owner_payout_amount', filter=paid),
    )
    facilities = Facility.objects.all() if dashboard == 'admin' else Facility.objects.filter(owner=request.user)
    closures = FacilityClosure.objects.filter(facility__in=facilities).select_related('facility', 'resource')
    if dashboard == 'admin':
        now = timezone.now()
        closures = closures.filter(start_datetime__lte=now, end_datetime__gte=now)
    result = {
        'rows_html': render_to_string('booking_batch_rows.html', {
            'booking_batches': batches, 'dashboard': dashboard,
        }, request=request),
        'kpis': {key: str(value or Decimal('0.00')) for key, value in totals.items()},
        'summary': {
            'batches': len(batches),
            'pending': sum(bool(batch.pending) for batch in batches),
            'paid': sum(batch.has_paid for batch in batches),
            'cancelled': sum(batch.has_cancelled for batch in batches),
        },
        'closures_html': render_to_string(
            'admin_live_closures.html' if dashboard == 'admin' else 'owner_live_closures.html',
            {'closures': closures}, request=request,
        ),
    }
    if dashboard == 'admin':
        today = confirmed.filter(start_datetime__date=timezone.localdate()).select_related(
            'user', 'resource__facility', 'sport',
        ).order_by('start_datetime')
        ledger = confirmed.values(
            'resource__facility__owner__username', 'resource__facility__owner__first_name',
            'resource__facility__owner__last_name', 'resource__facility__name',
        ).annotate(
            gross=Sum('total_price'),
            commission_owed=Sum('platform_fee_amount', filter=paid & Q(platform_fee_collected=False)),
        ).order_by('resource__facility__owner__username', 'resource__facility__name')
        result['today_html'] = render_to_string('admin_live_today.html', {'todays_bookings': today}, request=request)
        result['ledger_html'] = render_to_string('admin_live_ledger.html', {'owner_commission_ledger': ledger}, request=request)
        verified = facilities.filter(
            is_active=True, is_verified=True, verification_status=Facility.VerificationStatus.VERIFIED,
        )
        result['venues'] = verified.count()
        result['courts'] = BookableResource.objects.filter(facility__in=verified, is_active=True).count()
    return result


def customer_data(request):
    bookings = list(Booking.objects.filter(user=request.user)
                    .select_related('user', 'resource__facility', 'sport')
                    .order_by('-start_datetime'))
    batches = group_bookings_into_batches(bookings)
    now = timezone.now()
    upcoming = []
    past = []
    for batch in batches:
        active = [item for item in batch.bookings if item.status in (
            Booking.Status.CONFIRMED, Booking.Status.PENDING_VERIFICATION,
        )]
        batch.can_cancel = bool(active) and all(item.start_datetime > now for item in active)
        (upcoming if any(item.start_datetime > now for item in active) else past).append(batch)
    context = {'upcoming_batches': upcoming, 'past_batches': past}
    latest = max(bookings, key=lambda booking: booking.updated_at, default=None)
    return {
        **context,
        'bookings': list(BookingSerializer(bookings, many=True).data),
        'summary': {'upcoming': len(upcoming), 'past': len(past)},
        'latest_status_hint': {'booking_id': latest.pk, 'status': latest.status} if latest else None,
    }
