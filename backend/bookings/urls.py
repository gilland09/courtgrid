from django.urls import path

from .views import (
    BookingCancelView,
    BookingCreateView,
    MyBookingDetailView,
    MyBookingListView,
)

urlpatterns = [
    path('bookings/', BookingCreateView.as_view(), name='booking-create'),
    path('bookings/my/', MyBookingListView.as_view(), name='my-booking-list'),
    path('bookings/my/<int:pk>/', MyBookingDetailView.as_view(), name='my-booking-detail'),
    path('bookings/<int:pk>/cancel/', BookingCancelView.as_view(), name='booking-cancel'),
]
