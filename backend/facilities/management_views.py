from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from bookings.models import Booking, UserProfile, get_user_role

from .models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilityOperatingHours,
    FacilitySport,
)
from .portal_forms import (
    AdminFacilityForm,
    BookableResourceForm,
    FacilityClosureForm,
    FacilityForm,
    FacilityOperatingHoursForm,
    FacilitySportForm,
)


def roles_required(*roles):
    def decorate(view):
        @wraps(view)
        @login_required(login_url='login')
        def guarded(request, *args, **kwargs):
            if get_user_role(request.user) not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return guarded

    return decorate


def owner_facilities(user):
    if get_user_role(user) == UserProfile.Role.ADMIN:
        return Facility.objects.all()
    return Facility.objects.filter(owner=user)


def owner_dashboard_context(user, facility_form=None):
    facilities = owner_facilities(user).prefetch_related(
        'facility_sports__sport',
        'resources',
        'operating_hours',
    )
    facility_panels = []
    for facility in facilities:
        facility_panels.append({
            'facility': facility,
            'facility_form': FacilityForm(instance=facility),
            'rates': [
                {'sport': item, 'form': FacilitySportForm(instance=item)}
                for item in facility.facility_sports.all()
            ],
            'hours': [
                {'schedule': item, 'form': FacilityOperatingHoursForm(instance=item)}
                for item in facility.operating_hours.all()
            ],
        })
    facility_ids = facilities.values_list('pk', flat=True)
    closures = (
        FacilityClosure.objects.filter(facility_id__in=facility_ids)
        .select_related('facility', 'resource')
    )
    bookings = (
        Booking.objects.filter(
            resource__facility_id__in=facility_ids,
            status=Booking.Status.CONFIRMED,
        )
        .select_related('user', 'resource__facility', 'sport')
        .order_by('start_datetime')
    )
    return {
        'facilities': facilities,
        'facility_panels': facility_panels,
        'facility_form': facility_form or FacilityForm(),
        'hours_form': FacilityOperatingHoursForm(),
        'closure_form': FacilityClosureForm(facilities=facilities),
        'closures': closures,
        'venue_bookings': bookings,
    }


def portal_error(request, form, message):
    messages.error(request, message)
    if form is not None:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f'{field}: {error}')


@roles_required(UserProfile.Role.COURT_OWNER, UserProfile.Role.ADMIN)
def owner_dashboard_view(request):
    facilities = owner_facilities(request.user)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_facility':
            facility_id = request.POST.get('facility_id')
            instance = get_object_or_404(facilities, pk=facility_id) if facility_id else None
            form = FacilityForm(request.POST, instance=instance)
            if form.is_valid():
                facility = form.save(commit=False)
                if instance is None:
                    facility.owner = request.user
                facility.save()
                messages.success(request, 'Facility details saved.')
            else:
                portal_error(request, form, 'Please correct the facility details.')
                context = owner_dashboard_context(request.user)
                context['facility_form'] = form
                return render(request, 'owner_dashboard.html', context)
        elif action == 'save_resource':
            facility = get_object_or_404(facilities, pk=request.POST.get('facility_id'))
            resource_id = request.POST.get('resource_id')
            instance = (
                get_object_or_404(facility.resources, pk=resource_id)
                if resource_id else None
            )
            form = BookableResourceForm(request.POST, instance=instance)
            if form.is_valid():
                resource = form.save(commit=False)
                resource.facility = facility
                resource.resource_type = resource.resource_type or 'Court'
                resource.save()
                messages.success(request, 'Court details saved.')
            else:
                portal_error(request, form, 'Please correct the court details.')
        elif action == 'save_rate':
            facility_sport = get_object_or_404(
                FacilitySport.objects.filter(facility__in=facilities),
                pk=request.POST.get('facility_sport_id'),
            )
            form = FacilitySportForm(request.POST, instance=facility_sport)
            if form.is_valid():
                form.save()
                messages.success(request, 'Sport rate and availability saved.')
            else:
                portal_error(request, form, 'Please correct the sport rate.')
        elif action == 'save_hours':
            facility = get_object_or_404(facilities, pk=request.POST.get('facility_id'))
            hours_id = request.POST.get('hours_id')
            instance = (
                get_object_or_404(facility.operating_hours, pk=hours_id)
                if hours_id else None
            )
            form = FacilityOperatingHoursForm(request.POST, instance=instance)
            if form.is_valid():
                hours = form.save(commit=False)
                hours.facility = facility
                hours.save()
                messages.success(request, 'Operating hours saved.')
            else:
                portal_error(request, form, 'Please correct the operating hours.')
        elif action == 'create_closure':
            form = FacilityClosureForm(request.POST, facilities=facilities)
            if form.is_valid():
                closure = form.save(commit=False)
                closure.created_by = request.user
                closure.save()
                messages.success(request, 'Court closure scheduled.')
            else:
                portal_error(request, form, 'Please correct the closure details.')
        elif action == 'delete_closure':
            closure = get_object_or_404(
                FacilityClosure.objects.filter(facility__in=facilities),
                pk=request.POST.get('closure_id'),
            )
            closure.delete()
            messages.success(request, 'Court closure removed.')
        else:
            raise PermissionDenied('Unknown management action.')
        return redirect('owner_dashboard')

    return render(
        request,
        'owner_dashboard.html',
        owner_dashboard_context(request.user),
    )


@roles_required(UserProfile.Role.ADMIN)
def management_facilities_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        facility = get_object_or_404(Facility, pk=request.POST.get('facility_id'))
        if action == 'toggle_verified':
            facility.is_verified = not facility.is_verified
            facility.save(update_fields=('is_verified',))
            messages.success(request, 'Facility verification status updated.')
        elif action == 'toggle_active':
            facility.is_active = not facility.is_active
            facility.save(update_fields=('is_active',))
            messages.success(request, 'Facility active status updated.')
        elif action == 'save_facility':
            form = AdminFacilityForm(request.POST, instance=facility)
            if form.is_valid():
                form.save()
                messages.success(request, 'Facility details saved.')
            else:
                portal_error(request, form, 'Please correct the facility details.')
        elif action == 'save_rate':
            facility_sport = get_object_or_404(
                facility.facility_sports,
                pk=request.POST.get('facility_sport_id'),
            )
            form = FacilitySportForm(request.POST, instance=facility_sport)
            if form.is_valid():
                form.save()
                messages.success(request, 'Sport rate saved.')
            else:
                portal_error(request, form, 'Please correct the sport rate.')
        else:
            raise PermissionDenied('Unknown management action.')
        return redirect('management_facilities')

    facilities = list(Facility.objects.select_related('owner').prefetch_related(
        'facility_sports__sport',
    ))
    facility_panels = [
        {
            'facility': facility,
            'form': AdminFacilityForm(instance=facility),
            'rates': [
                {'sport': item, 'form': FacilitySportForm(instance=item)}
                for item in facility.facility_sports.all()
            ],
        }
        for facility in facilities
    ]
    return render(request, 'management_facilities.html', {
        'facilities': facilities,
        'facility_panels': facility_panels,
    })


def closure_management_context(user):
    facilities = owner_facilities(user)
    closures = (
        FacilityClosure.objects.filter(facility__in=facilities)
        .select_related('facility', 'resource', 'created_by')
    )
    return {
        'facilities': facilities,
        'closures': closures,
        'closure_form': FacilityClosureForm(facilities=facilities),
    }


@roles_required(UserProfile.Role.COURT_OWNER, UserProfile.Role.ADMIN)
def management_closures_view(request):
    facilities = owner_facilities(request.user)
    if request.method == 'POST':
        if request.POST.get('action') == 'delete_closure':
            closure = get_object_or_404(
                FacilityClosure.objects.filter(facility__in=facilities),
                pk=request.POST.get('closure_id'),
            )
            closure.delete()
            messages.success(request, 'Court closure removed.')
        elif request.POST.get('action') == 'create_closure':
            form = FacilityClosureForm(request.POST, facilities=facilities)
            if form.is_valid():
                closure = form.save(commit=False)
                closure.created_by = request.user
                closure.save()
                messages.success(request, 'Court closure scheduled.')
            else:
                portal_error(request, form, 'Please correct the closure details.')
        else:
            raise PermissionDenied('Unknown management action.')
        return redirect('management_closures')
    return render(
        request,
        'management_closures.html',
        closure_management_context(request.user),
    )
