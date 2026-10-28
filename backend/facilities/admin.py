from django.contrib import admin

from .models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilityOperatingHours,
    FacilitySport,
    ResourceSport,
    Sport,
    SportSchedule,
)


@admin.register(Sport)
class SportAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


class FacilitySportInline(admin.TabularInline):
    model = FacilitySport
    extra = 0


class BookableResourceInline(admin.TabularInline):
    model = BookableResource
    extra = 0


class ResourceSportInline(admin.TabularInline):
    model = ResourceSport
    extra = 0


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('name', 'barangay', 'facility_type', 'is_active', 'is_demo_data', 'is_verified')
    list_filter = ('is_active', 'is_demo_data', 'is_verified', 'facility_type', 'barangay')
    search_fields = ('name', 'barangay', 'address')
    inlines = (FacilitySportInline, BookableResourceInline)


@admin.register(FacilitySport)
class FacilitySportAdmin(admin.ModelAdmin):
    list_display = ('facility', 'sport', 'hourly_rate', 'is_active')
    list_filter = ('is_active', 'sport')
    search_fields = ('facility__name', 'sport__name')


@admin.register(BookableResource)
class BookableResourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'facility', 'resource_type', 'capacity', 'is_active')
    list_filter = ('is_active', 'resource_type', 'facility__barangay')
    search_fields = ('name', 'facility__name')
    inlines = (ResourceSportInline,)


@admin.register(ResourceSport)
class ResourceSportAdmin(admin.ModelAdmin):
    list_display = ('resource', 'facility_sport')
    list_filter = ('facility_sport__sport',)
    search_fields = ('resource__name', 'resource__facility__name', 'facility_sport__sport__name')


@admin.register(FacilityOperatingHours)
class FacilityOperatingHoursAdmin(admin.ModelAdmin):
    list_display = ('facility', 'day_of_week', 'start_time', 'end_time', 'effective_from', 'effective_until')
    list_filter = ('day_of_week', 'facility')


@admin.register(SportSchedule)
class SportScheduleAdmin(admin.ModelAdmin):
    list_display = ('facility_sport', 'resource', 'day_of_week', 'start_time', 'end_time', 'effective_from', 'effective_until')
    list_filter = ('day_of_week', 'facility_sport__sport', 'facility_sport__facility')


@admin.register(FacilityClosure)
class FacilityClosureAdmin(admin.ModelAdmin):
    list_display = ('facility', 'resource', 'start_datetime', 'end_datetime', 'created_by')
    list_filter = ('facility',)
    search_fields = ('facility__name', 'reason')
    readonly_fields = ('created_at',)
