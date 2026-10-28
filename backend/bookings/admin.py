from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'resource',
        'sport',
        'start_datetime',
        'end_datetime',
        'participant_count',
        'status',
        'total_price',
    )
    list_filter = ('status', 'sport', 'resource__facility')
    search_fields = ('user__username', 'resource__name', 'resource__facility__name')
    readonly_fields = (
        'rate_snapshot',
        'total_price',
        'currency',
        'created_at',
        'updated_at',
        'cancelled_at',
    )
