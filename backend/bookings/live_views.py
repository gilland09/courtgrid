from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from facilities.models import Facility

from .live_sync import availability_version, booking_version, customer_data, dashboard_data, dashboard_version
from .models import Booking, UserProfile, get_user_role


@never_cache
@login_required
@require_GET
def owner_live_state(request):
    if get_user_role(request.user) != UserProfile.Role.COURT_OWNER:
        raise PermissionDenied
    bookings = Booking.objects.filter(resource__facility__owner=request.user)
    version = dashboard_version(request.user)
    if request.GET.get('version') == version:
        return JsonResponse({'changed': False, 'version': version})
    return JsonResponse({
        'changed': True, 'version': version,
        **dashboard_data(request, bookings, 'owner'),
    })


@never_cache
@login_required
@require_GET
def admin_live_state(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    bookings = Booking.objects.all()
    version = dashboard_version(request.user, admin=True)
    if request.GET.get('version') == version:
        return JsonResponse({'changed': False, 'version': version})
    return JsonResponse({
        'changed': True, 'version': version,
        **dashboard_data(request, bookings, 'admin', request.GET.get('settlement_status', 'all')),
    })


@never_cache
@login_required
@require_GET
def customer_live_state(request):
    version = booking_version(Booking.objects.filter(user=request.user))
    if request.GET.get('version') == version:
        return JsonResponse({'changed': False, 'version': version})
    data = customer_data(request)
    return JsonResponse({
        'changed': True, 'version': version,
        'rows_html': render_to_string('my_booking_cards.html', data, request=request),
        'bookings': data['bookings'], 'summary': data['summary'],
        'latest_status_hint': data['latest_status_hint'],
    })


@never_cache
@require_GET
def facility_availability_version(request, pk):
    get_object_or_404(Facility, pk=pk)
    return JsonResponse({'version': availability_version(pk)})
