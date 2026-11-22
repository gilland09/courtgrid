from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.models import LogEntry
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils._os import safe_join
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.static import serve

from bookings.models import Booking, UserProfile, get_user_role
from facilities.models import BookableResource, Facility, FacilityClosure, Sport
from facilities.management_views import (
    pending_venue_verifications,
    set_facility_verification,
)
from .forms import RegistrationForm


def guarded_media_view(request, path):
    target = Path(safe_join(settings.MEDIA_ROOT, path)).resolve()
    private_root = Path(settings.PRIVATE_RECEIPT_ROOT).resolve()
    if target == private_root or private_root in target.parents:
        raise Http404
    return serve(request, path, document_root=settings.MEDIA_ROOT)


def _dashboard_url(user):
    role = get_user_role(user)
    if role == UserProfile.Role.ADMIN:
        return 'admin_dashboard'
    if role == UserProfile.Role.COURT_OWNER:
        return 'owner_dashboard'
    return 'home'


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_url(request.user))

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        auth_login(request, user)
        return redirect(_dashboard_url(user))

    return render(request, 'login.html', {'form': form})


def register_view(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_url(request.user))

    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
        auth_login(request, user)
        return redirect(_dashboard_url(user))

    return render(request, 'register.html', {'form': form})


@require_POST
def logout_view(request):
    auth_logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('login')


def home_view(request):
    sports = Sport.objects.filter(is_active=True).order_by('name')
    return render(request, 'home.html', {'sports': sports})


@user_passes_test(
    lambda user: get_user_role(user) == UserProfile.Role.ADMIN,
    login_url='login',
)
def admin_dashboard_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action in {'approve_facility', 'reject_facility'}:
            with transaction.atomic():
                facility = get_object_or_404(
                    Facility.objects.select_for_update().filter(
                        verification_status=Facility.VerificationStatus.PENDING,
                        dpa_consent_accepted=True,
                    ),
                    pk=request.POST.get('facility_id'),
                )
                if action == 'approve_facility' and not all((
                    facility.business_trade_name.strip(),
                    facility.business_permit_no.strip(),
                    facility.business_contact_number.strip(),
                )):
                    messages.error(
                        request,
                        'Venue approval requires a trade name, permit number, and business contact number.',
                    )
                    return redirect('admin_dashboard')
                verification_status = (
                    Facility.VerificationStatus.VERIFIED
                    if action == 'approve_facility'
                    else Facility.VerificationStatus.REJECTED
                )
                set_facility_verification(
                    facility,
                    request.user,
                    verification_status,
                )
            messages.success(
                request,
                f'{facility.name} verification marked {facility.get_verification_status_display().lower()}.',
            )
            return redirect('admin_dashboard')
        if action not in {'collect_commission', 'verify_payment'}:
            return redirect('admin_dashboard')
        with transaction.atomic():
            bookings = Booking.objects.select_for_update().filter(
                status__in=(Booking.Status.CONFIRMED, Booking.Status.PENDING_VERIFICATION),
            )
            if action == 'collect_commission':
                bookings = bookings.filter(
                    status=Booking.Status.CONFIRMED,
                    payment_status=Booking.PaymentStatus.PAID,
                )
            booking = get_object_or_404(bookings, pk=request.POST.get('booking_id'))
            if action == 'collect_commission':
                if booking.platform_fee_collected:
                    messages.info(request, 'The commission for this reservation is already marked collected.')
                else:
                    booking.platform_fee_collected = True
                    booking.platform_fee_collected_at = timezone.now()
                    booking.platform_fee_collected_by = request.user
                    booking.save(update_fields=(
                        'platform_fee_collected',
                        'platform_fee_collected_at',
                        'platform_fee_collected_by',
                        'updated_at',
                    ))
                    messages.success(
                        request,
                        f'Commission of ₱{booking.platform_fee_amount} marked collected from {booking.resource.facility.owner or "the venue owner"}.',
                    )
            elif action == 'verify_payment':
                if booking.payment_status != Booking.PaymentStatus.PENDING:
                    messages.info(request, 'This reservation is not awaiting payment verification.')
                else:
                    booking.status = Booking.Status.CONFIRMED
                    booking.payment_status = Booking.PaymentStatus.PAID
                    booking.payment_verified_at = timezone.now()
                    booking.payment_verified_by = request.user
                    booking.save(update_fields=(
                        'status',
                        'payment_status',
                        'payment_verified_at',
                        'payment_verified_by',
                        'updated_at',
                    ))
                    messages.success(request, 'Venue payment marked verified by the platform administrator.')
        return redirect('admin_dashboard')

    now = timezone.now()
    today = timezone.localtime(now).date()
    todays_bookings = (
        Booking.objects.filter(
            status=Booking.Status.CONFIRMED,
            start_datetime__date=today,
        )
        .select_related('user', 'resource__facility', 'sport')
        .order_by('start_datetime')
    )
    active_closures = (
        FacilityClosure.objects.filter(
            start_datetime__lte=now,
            end_datetime__gte=now,
        )
        .select_related('facility', 'resource')
        .order_by('start_datetime')
    )
    all_bookings = (
        Booking.objects.all()
        .select_related('user', 'resource__facility', 'sport')
        .order_by('start_datetime')
    )
    confirmed_bookings = all_bookings.filter(
        status=Booking.Status.CONFIRMED,
    )
    settlement_status = request.GET.get('settlement_status', 'all')
    if settlement_status == 'pending':
        visible_bookings = confirmed_bookings.filter(
            payment_status=Booking.PaymentStatus.PAID,
            platform_fee_collected=False,
        )
    elif settlement_status == 'paid':
        visible_bookings = confirmed_bookings.filter(
            platform_fee_collected=True,
        )
    else:
        settlement_status = 'all'
        visible_bookings = all_bookings
    financial_totals = confirmed_bookings.aggregate(
        gross=Sum('total_price'),
        platform_fee=Sum(
            'platform_fee_amount',
            filter=Q(
                payment_status=Booking.PaymentStatus.PAID,
                platform_fee_collected=False,
            ),
        ),
        platform_fee_settled=Sum(
            'platform_fee_amount',
            filter=Q(
                payment_status=Booking.PaymentStatus.PAID,
                platform_fee_collected=True,
            ),
        ),
        owner_payout=Sum(
            'owner_payout_amount',
            filter=Q(payment_status=Booking.PaymentStatus.PAID),
        ),
    )
    owner_commission_ledger = (
        confirmed_bookings.values(
            'resource__facility__owner__username',
            'resource__facility__owner__first_name',
            'resource__facility__owner__last_name',
            'resource__facility__name',
        )
        .annotate(
            gross=Sum('total_price'),
            commission_owed=Sum(
                'platform_fee_amount',
                filter=Q(
                    payment_status=Booking.PaymentStatus.PAID,
                    platform_fee_collected=False,
                ),
            ),
        )
        .order_by(
            'resource__facility__owner__username',
            'resource__facility__name',
        )
    )
    return render(request, 'admin_dashboard.html', {
        'todays_bookings': todays_bookings,
        'active_closures': active_closures,
        'pending_facilities': pending_venue_verifications(),
        'all_bookings': visible_bookings,
        'settlement_status': settlement_status,
        'owner_commission_ledger': owner_commission_ledger,
        'admin_logs': LogEntry.objects.select_related(
            'user',
            'content_type',
        ).order_by('-action_time', '-pk'),
        'financial_totals': {
            key: value or Decimal('0.00')
            for key, value in financial_totals.items()
        },
        'active_verified_venues': Facility.objects.filter(
            is_active=True,
            is_verified=True,
            verification_status=Facility.VerificationStatus.VERIFIED,
        ).count(),
        'active_courts': BookableResource.objects.filter(
            is_active=True,
            facility__is_active=True,
            facility__is_verified=True,
            facility__verification_status=Facility.VerificationStatus.VERIFIED,
        ).count(),
    })


@login_required(login_url='login')
@require_POST
def admin_cancel_booking(request, booking_id):
    if get_user_role(request.user) != UserProfile.Role.ADMIN:
        raise PermissionDenied

    with transaction.atomic():
        booking = get_object_or_404(
            Booking.objects.select_for_update(),
            pk=booking_id,
        )
        if booking.status == Booking.Status.CANCELLED:
            messages.warning(request, 'This reservation is already cancelled.')
            return redirect('admin_dashboard')
        if booking.start_datetime <= timezone.now():
            messages.error(
                request,
                'A reservation cannot be cancelled after it has started.',
            )
            return redirect('admin_dashboard')

        submitted_reason = request.POST.get('cancellation_reason', '').strip()
        was_paid = booking.payment_status == Booking.PaymentStatus.PAID
        if was_paid:
            prefix = 'Cancelled by platform administrator after payment was received'
            reason = (
                f'{prefix}: {submitted_reason}'
                if submitted_reason
                else (
                    f'{prefix}; coordinate any refund with the facility owner '
                    'and player.'
                )
            )
        else:
            reason = submitted_reason or 'Cancelled by platform administrator'

        max_reason_length = Booking._meta.get_field(
            'cancellation_reason',
        ).max_length
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancellation_reason = reason[:max_reason_length]
        booking.save(update_fields=(
            'status',
            'cancelled_at',
            'cancellation_reason',
            'updated_at',
        ))

    messages.success(
        request,
        f'Reservation {booking.payment_reference} was cancelled and its time slot released.',
    )
    if was_paid:
        messages.warning(
            request,
            'Payment had already been recorded. Coordinate any refund with the facility owner and player.',
        )
    return redirect('admin_dashboard')


@login_required(login_url='login')
@require_POST
def admin_delete_log(request, log_id):
    if get_user_role(request.user) != UserProfile.Role.ADMIN:
        raise PermissionDenied

    with transaction.atomic():
        log_entry = get_object_or_404(
            LogEntry.objects.select_for_update(),
            pk=log_id,
        )
        log_entry.delete()

    messages.success(request, 'The log entry was permanently deleted.')
    return redirect('admin_dashboard')


@login_required(login_url='login')
@require_POST
def admin_delete_all_logs(request):
    if get_user_role(request.user) != UserProfile.Role.ADMIN:
        raise PermissionDenied

    with transaction.atomic():
        log_ids = list(
            LogEntry.objects.select_for_update().values_list('pk', flat=True),
        )
        deleted_count = len(log_ids)
        if log_ids:
            LogEntry.objects.filter(pk__in=log_ids).delete()

    if deleted_count:
        messages.success(
            request,
            f'{deleted_count} log entr{"y" if deleted_count == 1 else "ies"} permanently deleted.',
        )
    else:
        messages.info(request, 'There are no log entries to delete.')
    return redirect('admin_dashboard')


@user_passes_test(
    lambda user: get_user_role(user) == UserProfile.Role.ADMIN,
    login_url='login',
)
@require_POST
def settle_commission_view(request, booking_id):
    with transaction.atomic():
        booking = get_object_or_404(
            Booking.objects.select_for_update().filter(
                status=Booking.Status.CONFIRMED,
                payment_status=Booking.PaymentStatus.PAID,
            ),
            pk=booking_id,
        )
        if booking.platform_fee_collected:
            messages.info(request, 'This commission has already been marked paid to the platform.')
        else:
            booking.platform_fee_collected = True
            booking.platform_fee_collected_at = timezone.now()
            booking.platform_fee_collected_by = request.user
            booking.save(update_fields=(
                'platform_fee_collected',
                'platform_fee_collected_at',
                'platform_fee_collected_by',
                'updated_at',
            ))
            messages.success(
                request,
                f'Commission of ₱{booking.platform_fee_amount} marked paid by {booking.resource.facility.owner or "the venue owner"}.',
            )
    return redirect('admin_dashboard')


@login_required(login_url='login')
def my_bookings_view(request):
    return render(request, 'my_bookings.html')
