from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from facilities.models import BookableResource, FacilitySport, ResourceSport

from .models import Booking
from .serializers import BookingSerializer, CreateBookingSerializer


class BookingConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'The requested resource is already booked for this time.'
    default_code = 'booking_conflict'


class MyBookingListView(ListAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = BookingSerializer

    def get_queryset(self):
        return (
            Booking.objects.filter(user=self.request.user)
            .select_related('user', 'resource', 'sport')
        )


class MyBookingDetailView(RetrieveAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = BookingSerializer

    def get_queryset(self):
        return (
            Booking.objects.filter(user=self.request.user)
            .select_related('user', 'resource', 'sport')
        )


class BookingCreateView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = CreateBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested = serializer.validated_data

        with transaction.atomic():
            try:
                resource = (
                    BookableResource.objects.select_for_update()
                    .select_related('facility')
                    .get(
                        pk=requested['resource'].pk,
                        is_active=True,
                        facility__is_active=True,
                    )
                )
            except BookableResource.DoesNotExist as exc:
                raise ValidationError({
                    'resource_id': 'The requested resource is not currently bookable.'
                }) from exc

            sport = requested['sport']
            if not sport.is_active:
                raise ValidationError({
                    'sport_id': 'The requested sport is not currently bookable.'
                })

            try:
                facility_sport = (
                    FacilitySport.objects.select_for_update()
                    .select_related('sport')
                    .get(
                        facility=resource.facility,
                        sport=sport,
                        is_active=True,
                        sport__is_active=True,
                    )
                )
            except FacilitySport.DoesNotExist as exc:
                raise ValidationError({
                    'sport_id': 'This facility does not currently support the requested sport.'
                }) from exc

            if not ResourceSport.objects.select_for_update().filter(
                resource=resource,
                facility_sport=facility_sport,
            ).exists():
                raise ValidationError({
                    'sport_id': 'This resource is not configured for the requested sport.'
                })

            capacity = (
                resource.capacity
                if resource.capacity is not None
                else resource.facility.capacity
            )
            if capacity is not None and requested['participant_count'] > capacity:
                raise ValidationError({
                    'participant_count': (
                        f'Participant count cannot exceed the capacity of {capacity}.'
                    )
                })

            hourly_rate = facility_sport.hourly_rate
            if hourly_rate is None:
                hourly_rate = resource.facility.default_hourly_rate
            if hourly_rate is None:
                raise ValidationError({
                    'sport_id': 'No hourly rate is configured for this facility and sport.'
                })

            start_datetime = requested['start_datetime']
            end_datetime = requested['end_datetime']
            has_overlap = Booking.objects.filter(
                resource=resource,
                status=Booking.Status.CONFIRMED,
                start_datetime__lt=end_datetime,
                end_datetime__gt=start_datetime,
            ).exists()
            if has_overlap:
                raise BookingConflict()

            booking = Booking.objects.create(
                user=request.user,
                resource=resource,
                sport=sport,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                participant_count=requested['participant_count'],
                status=Booking.Status.CONFIRMED,
                rate_snapshot=hourly_rate,
                total_price=hourly_rate,
            )

        return Response(
            BookingSerializer(booking).data,
            status=status.HTTP_201_CREATED,
        )


class BookingCancelView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request, pk):
        with transaction.atomic():
            try:
                booking = Booking.objects.select_for_update().get(
                    pk=pk,
                    user=request.user,
                )
            except Booking.DoesNotExist as exc:
                raise NotFound('Booking not found.') from exc

            if booking.status != Booking.Status.CONFIRMED:
                raise BookingConflict('Only confirmed bookings can be cancelled.')
            if booking.start_datetime <= timezone.now():
                raise ValidationError({
                    'booking': 'A booking cannot be cancelled after it has started.'
                })

            booking.status = Booking.Status.CANCELLED
            booking.cancelled_at = timezone.now()
            booking.save(update_fields=('status', 'cancelled_at', 'updated_at'))

        return Response(BookingSerializer(booking).data, status=status.HTTP_200_OK)
