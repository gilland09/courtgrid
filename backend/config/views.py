from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from bookings.models import Booking, UserProfile, get_user_role
from facilities.models import FacilityClosure, Sport
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
    return render(request, 'admin_dashboard.html', {
        'todays_bookings': todays_bookings,
        'active_closures': active_closures,
        'all_bookings': all_bookings,
    })


@login_required(login_url='login')
def my_bookings_view(request):
    return render(request, 'my_bookings.html')
