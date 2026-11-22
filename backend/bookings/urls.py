from django.urls import path
from .live_views import admin_live_state, customer_live_state, facility_availability_version, owner_live_state

from .views import (
    BookingCancelView,
    BookingCreateView,
    MyBookingDetailView,
    MyBookingListView,
    owner_cancel_booking,
    owner_confirm_payment,
    owner_reject_receipt,
    booking_receipt_file,
)

urlpatterns = [
    path('live/owner/', owner_live_state, name='owner-live-state'),
    path('live/admin/', admin_live_state, name='admin-live-state'),
    path('live/my-bookings/', customer_live_state, name='customer-live-state'),
    path('facilities/<int:pk>/availability-version/', facility_availability_version, name='facility-availability-version'),
    path('bookings/', BookingCreateView.as_view(), name='booking-create'),
    path('bookings/my/', MyBookingListView.as_view(), name='my-booking-list'),
    path('bookings/my/<int:pk>/', MyBookingDetailView.as_view(), name='my-booking-detail'),
    path('bookings/<int:booking_id>/receipt/', booking_receipt_file, name='booking-receipt'),
    path('bookings/<int:pk>/cancel/', BookingCancelView.as_view(), name='booking-cancel'),
    path('bookings/<int:booking_id>/confirm-payment/', owner_confirm_payment, name='owner_confirm_payment'),
    path('bookings/<int:booking_id>/reject-receipt/', owner_reject_receipt, name='owner_reject_receipt'),
    path(
        'bookings/<int:booking_id>/owner-cancel/',
        owner_cancel_booking,
        name='owner_cancel_booking',
    ),
]
