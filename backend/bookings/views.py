from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from facilities.availability import slot_unavailability_reason
from facilities.models import BookableResource, Facility, FacilitySport, ResourceSport

from .models import Booking
from .serializers import (
    BatchCreateBookingSerializer,
    BookingSerializer,
    CreateBookingSerializer,
)


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
            .select_related('user', 'resource__facility', 'sport')
        )


class MyBookingDetailView(RetrieveAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = BookingSerializer

    def get_queryset(self):
        return (
            Booking.objects.filter(user=self.request.user)
            .select_related('user', 'resource__facility', 'sport')
        )


class BookingCreateView(APIView):
    permission_classes = (IsAuthenticated,)

    @staticmethod
    def validate_schedule_and_closures(resource, facility_sport, start_datetime, end_datetime):
        reason = slot_unavailability_reason(
            resource,
            facility_sport,
            start_datetime,
            end_datetime,
        )
        if reason is not None:
            raise ValidationError({'start_datetime': reason})

    def create_booking(self, requested, user):
        initial_facility_sport = FacilitySport.objects.filter(
            facility=requested['resource'].facility,
            sport=requested['sport'],
            is_active=True,
        ).first()
        if initial_facility_sport is None:
            raise ValidationError({
                'sport_id': 'This facility does not currently support the requested sport.'
            })
        self.validate_schedule_and_closures(
            requested['resource'],
            initial_facility_sport,
            requested['start_datetime'],
            requested['end_datetime'],
        )

        with transaction.atomic():
            try:
                Facility.objects.select_for_update().get(
                    pk=requested['resource'].facility_id,
                    is_active=True,
                )
            except Facility.DoesNotExist as exc:
                raise ValidationError({
                    'resource_id': 'The requested facility is not currently bookable.'
                }) from exc
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

            self.validate_schedule_and_closures(
                resource,
                facility_sport,
                requested['start_datetime'],
                requested['end_datetime'],
            )

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
                user=user,
                resource=resource,
                sport=sport,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                participant_count=requested['participant_count'],
                participant_names=requested.get('participant_names', ''),
                contact_email=requested.get('contact_email', ''),
                contact_phone=requested.get('contact_phone', ''),
                status=Booking.Status.CONFIRMED,
                rate_snapshot=hourly_rate,
                total_price=hourly_rate,
                payment_method=requested.get(
                    'payment_method',
                    Booking.PaymentMethod.GCASH,
                ),
            )

        return booking

    def post(self, request):
        if 'slots' in request.data:
            batch_serializer = BatchCreateBookingSerializer(data=request.data)
            batch_serializer.is_valid(raise_exception=True)
            batch = batch_serializer.validated_data
            validated_slots = []
            for slot in batch['slots']:
                serializer = CreateBookingSerializer(data={
                    'resource_id': slot['resource_id'].pk,
                    'sport_id': batch['sport_id'].pk,
                    'start_datetime': slot['start_datetime'],
                    'end_datetime': slot['end_datetime'],
                    'participant_count': batch['participant_count'],
                    'participant_names': batch.get('participant_names', ''),
                    'contact_email': batch['contact_email'],
                    'contact_phone': batch['contact_phone'],
                    'payment_method': batch['payment_method'],
                })
                serializer.is_valid(raise_exception=True)
                validated_slots.append(serializer.validated_data)

            validated_slots.sort(
                key=lambda slot: (
                    slot['resource'].pk,
                    slot['start_datetime'],
                )
            )
            with transaction.atomic():
                bookings = [
                    self.create_booking(slot, request.user)
                    for slot in validated_slots
                ]

            serialized_bookings = BookingSerializer(bookings, many=True).data
            return Response({
                'results': serialized_bookings,
                'total_price': str(sum(
                    (booking.total_price for booking in bookings),
                    start=bookings[0].total_price * 0,
                )),
            }, status=status.HTTP_201_CREATED)

        serializer = CreateBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = self.create_booking(serializer.validated_data, request.user)
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
            booking.cancellation_reason = 'Cancelled by customer'
            booking.save(update_fields=(
                'status',
                'cancelled_at',
                'cancellation_reason',
                'updated_at',
            ))

        return Response(BookingSerializer(booking).data, status=status.HTTP_200_OK)
