from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from bookings.models import Booking, UserProfile, get_user_role
from facilities.models import BookableResource, Facility, FacilityClosure, Sport
from .forms import RegistrationForm


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
        if action not in {'collect_commission', 'verify_payment'}:
            return redirect('admin_dashboard')
        with transaction.atomic():
            bookings = Booking.objects.select_for_update().filter(
                status=Booking.Status.CONFIRMED,
            )
            if action == 'collect_commission':
                bookings = bookings.filter(payment_status=Booking.PaymentStatus.PAID)
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
                    booking.payment_status = Booking.PaymentStatus.PAID
                    booking.payment_verified_at = timezone.now()
                    booking.payment_verified_by = request.user
                    booking.save(update_fields=(
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
        Booking.objects.filter(status=Booking.Status.CONFIRMED)
        .select_related('user', 'resource__facility', 'sport')
        .order_by('start_datetime')
    )
    financial_totals = all_bookings.aggregate(
        gross=Sum('total_price'),
        platform_fee=Sum(
            'platform_fee_amount',
            filter=Q(
                payment_status=Booking.PaymentStatus.PAID,
                platform_fee_collected=False,
            ),
        ),
        owner_payout=Sum(
            'owner_payout_amount',
            filter=Q(payment_status=Booking.PaymentStatus.PAID),
        ),
    )
    owner_commission_ledger = (
        all_bookings.values(
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
        'all_bookings': all_bookings,
        'owner_commission_ledger': owner_commission_ledger,
        'financial_totals': {
            key: value or Decimal('0.00')
            for key, value in financial_totals.items()
        },
        'active_verified_venues': Facility.objects.filter(
            is_active=True,
            is_verified=True,
        ).count(),
        'active_courts': BookableResource.objects.filter(
            is_active=True,
            facility__is_active=True,
            facility__is_verified=True,
        ).count(),
    })


@login_required(login_url='login')
def my_bookings_view(request):
    return render(request, 'my_bookings.html')
