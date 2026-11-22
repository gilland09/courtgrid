import json
import logging
from pathlib import PurePath

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.clickjacking import xframe_options_sameorigin
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from facilities.availability import slot_unavailability_reason
from facilities.models import BookableResource, Facility, FacilityPaymentMethod, FacilitySport, ResourceSport

from .models import Booking
from .email_service import send_booking_confirmed_email, send_booking_rejected_email
from .serializers import (
    BatchCreateBookingSerializer,
    BookingSerializer,
    CreateBookingSerializer,
    PaymentFirstSerializer,
)


OWNER_CANCELLATION_REASON = 'Cancelled by venue owner'
PAID_OWNER_CANCELLATION_REASON = (
    'Cancelled by venue owner after payment was received; '
    'coordinate any refund directly with the player.'
)
logger = logging.getLogger(__name__)


def schedule_booking_email(booking, sender):
    result = {}

    def send_after_commit():
        try:
            result.update(sender(booking))
        except Exception:
            logger.exception('Unexpected booking email failure for booking %s', booking.pk)
            result.update(sent=False, reason='Email delivery failed. Please contact the customer directly.')

    transaction.on_commit(send_after_commit)
    return result


def report_email_result(request, result):
    if not result:
        messages.info(request, 'The customer notification is queued until the transaction commits.')
    elif result['sent']:
        messages.success(request, 'The customer notification was sent.')
    else:
        messages.warning(request, result['reason'])


def owner_booking_scope(user):
    bookings = Booking.objects.select_for_update(of=('self',)).select_related('user', 'resource__facility')
    if not user.is_superuser:
        bookings = bookings.filter(resource__facility__owner=user)
    return bookings


@login_required
@require_POST
def owner_confirm_payment(request, booking_id):
    with transaction.atomic():
        booking = get_object_or_404(owner_booking_scope(request.user), pk=booking_id)
        if (
            booking.status not in (Booking.Status.PENDING_VERIFICATION, Booking.Status.CONFIRMED)
            or booking.payment_status != Booking.PaymentStatus.PENDING
        ):
            messages.warning(request, 'This reservation is not awaiting payment verification.')
            return redirect('owner_dashboard')
        was_pending = booking.status == Booking.Status.PENDING_VERIFICATION
        booking.status = Booking.Status.CONFIRMED
        booking.payment_status = Booking.PaymentStatus.PAID
        booking.payment_verified_at = timezone.now()
        booking.payment_verified_by = request.user
        booking.save(update_fields=(
            'status', 'payment_status', 'payment_verified_at', 'payment_verified_by', 'updated_at',
        ))
        delivery = schedule_booking_email(booking, send_booking_confirmed_email) if was_pending else None
    messages.success(request, f'Payment for reservation {booking.payment_reference} was marked received by the venue.')
    if delivery is not None:
        report_email_result(request, delivery)
    return redirect('owner_dashboard')


@login_required
@require_POST
def owner_reject_receipt(request, booking_id):
    with transaction.atomic():
        booking = get_object_or_404(owner_booking_scope(request.user), pk=booking_id)
        if booking.status != Booking.Status.PENDING_VERIFICATION:
            messages.warning(request, 'Only reservations awaiting verification can be rejected.')
            return redirect('owner_dashboard')
        reason = request.POST.get('rejection_reason', '').strip()
        if not reason or len(reason) > Booking._meta.get_field('cancellation_reason').max_length:
            messages.error(request, 'Provide a rejection reason of at most 180 characters.')
            return redirect('owner_dashboard')
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancellation_reason = reason
        booking.save(update_fields=('status', 'cancelled_at', 'cancellation_reason', 'updated_at'))
        delivery = schedule_booking_email(booking, send_booking_rejected_email)
    messages.success(request, f'Receipt for reservation {booking.payment_reference} was rejected and its slot released.')
    report_email_result(request, delivery)
    return redirect('owner_dashboard')


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

            hourly_rate = resource.effective_hourly_rate_for(facility_sport)
            if hourly_rate is None:
                raise ValidationError({
                    'sport_id': 'No hourly rate is configured for this facility and sport.'
                })

            start_datetime = requested['start_datetime']
            end_datetime = requested['end_datetime']
            has_overlap = Booking.objects.filter(
                resource=resource,
                status__in=(Booking.Status.CONFIRMED, Booking.Status.PENDING_VERIFICATION),
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
                status=Booking.Status.PENDING_VERIFICATION,
                rate_snapshot=hourly_rate,
                total_price=hourly_rate,
                payment_method=requested['payment_method_label'].lower()[:24],
                booking_type=requested['booking_type'],
                organization_name=requested.get('organization_name', ''),
                event_name=requested.get('event_name', ''),
                expected_participants=requested.get('expected_participants'),
                payment_method_used=requested['payment_method_used'],
                payment_method_label=requested['payment_method_label'],
                payment_account_number=requested['payment_account_number'],
                policy_accepted=True,
            )

        return booking

    def post(self, request):
        if not (request.content_type or '').startswith('multipart/form-data'):
            raise ValidationError({'detail': 'Submit the booking as multipart form data with a receipt.'})
        payment_serializer = PaymentFirstSerializer(data=request.data)
        payment_serializer.is_valid(raise_exception=True)
        payment = payment_serializer.validated_data
        is_batch = 'slots' in request.data
        if is_batch:
            try:
                slots = json.loads(request.data['slots'])
            except (TypeError, ValueError) as exc:
                raise ValidationError({'slots': 'Submit slots as a JSON array.'}) from exc
            batch_data = {
                key: request.data.get(key)
                for key in ('sport_id', 'participant_count', 'participant_names', 'contact_email', 'contact_phone')
                if key in request.data
            }
            batch_data['slots'] = slots
            batch_serializer = BatchCreateBookingSerializer(data=batch_data)
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
                })
                serializer.is_valid(raise_exception=True)
                validated_slots.append(serializer.validated_data)

        else:
            serializer = CreateBookingSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            validated_slots = [serializer.validated_data]

        facility_ids = {slot['resource'].facility_id for slot in validated_slots}
        court_ids = {slot['resource'].pk for slot in validated_slots}
        if len(facility_ids) != 1:
            raise ValidationError({'slots': 'All courts must belong to the same facility.'})
        if payment['booking_type'] == Booking.BookingType.PLAYER and len(court_ids) != 1:
            raise ValidationError({'slots': 'Players can book only one court per reservation.'})
        validated_slots.sort(key=lambda slot: (slot['resource'].pk, slot['start_datetime']))
        saved_receipt_name = None
        storage = Booking._meta.get_field('payment_receipt').storage
        try:
            with transaction.atomic():
                facility = Facility.objects.select_for_update().get(pk=next(iter(facility_ids)))
                method = FacilityPaymentMethod.objects.select_for_update().filter(
                    pk=payment['payment_method_used'], facility=facility, is_active=True,
                ).first()
                if method is None:
                    raise ValidationError({'payment_method_used': 'Select an active payment method for this facility.'})
                for slot in validated_slots:
                    slot.update({
                        **payment,
                        'payment_method_used': method,
                        'payment_method_label': method.label,
                        'payment_account_number': method.account_number,
                    })
                bookings = [self.create_booking(slot, request.user) for slot in validated_slots]
                if 'expected_total' in payment and sum(
                    booking.total_price for booking in bookings
                ) != payment['expected_total']:
                    raise BookingConflict('The displayed price is no longer current. Contact the venue before resubmitting.')
                field = Booking._meta.get_field('payment_receipt')
                receipt = payment['payment_receipt']
                saved_receipt_name = storage.save(field.generate_filename(bookings[0], receipt.name), receipt)
                uploaded_at = timezone.now()
                Booking.objects.filter(pk__in=[booking.pk for booking in bookings]).update(
                    payment_receipt=saved_receipt_name,
                    payment_receipt_uploaded_at=uploaded_at,
                )
                for booking in bookings:
                    booking.payment_receipt.name = saved_receipt_name
                    booking.payment_receipt_uploaded_at = uploaded_at
        except Exception:
            if saved_receipt_name:
                storage.delete(saved_receipt_name)
            raise

        if is_batch:
            return Response({
                'results': BookingSerializer(bookings, many=True).data,
                'total_price': str(sum(
                    (booking.total_price for booking in bookings),
                    start=bookings[0].total_price * 0,
                )),
            }, status=status.HTTP_201_CREATED)
        return Response(
            BookingSerializer(bookings[0]).data,
            status=status.HTTP_201_CREATED,
        )


@login_required(login_url='login')
@xframe_options_sameorigin
def booking_receipt_file(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('resource__facility'), pk=booking_id,
    )
    if not (
        request.user.is_superuser
        or booking.user_id == request.user.pk
        or booking.resource.facility.owner_id == request.user.pk
    ):
        raise PermissionDenied
    if not booking.payment_receipt:
        raise Http404('Receipt not found.')
    content_types = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.pdf': 'application/pdf',
    }
    content_type = content_types.get(PurePath(booking.payment_receipt.name).suffix.lower())
    if not content_type:
        raise Http404('Receipt not found.')
    try:
        receipt = booking.payment_receipt.open('rb')
    except FileNotFoundError as exc:
        raise Http404('Receipt not found.') from exc
    response = FileResponse(receipt, content_type=content_type)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response


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

            if booking.status not in (Booking.Status.CONFIRMED, Booking.Status.PENDING_VERIFICATION):
                raise BookingConflict('Only active bookings can be cancelled.')
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


@login_required
@require_POST
def owner_cancel_booking(request, booking_id):
    booking_scope = Booking.objects.select_for_update().select_related(
        'resource__facility',
    )
    if not request.user.is_superuser:
        booking_scope = booking_scope.filter(
            resource__facility__owner=request.user,
        )

    with transaction.atomic():
        booking = get_object_or_404(booking_scope, pk=booking_id)
        if booking.status == Booking.Status.CANCELLED:
            messages.warning(request, 'This reservation is already cancelled.')
            return redirect('owner_dashboard')
        if booking.start_datetime <= timezone.now():
            messages.error(
                request,
                'A reservation cannot be cancelled after it has started.',
            )
            return redirect('owner_dashboard')

        submitted_reason = request.POST.get('cancellation_reason', '').strip()
        was_paid = booking.payment_status == Booking.PaymentStatus.PAID
        if was_paid:
            prefix = 'Cancelled by venue owner after payment was received'
            reason = (
                f'{prefix}: {submitted_reason}'
                if submitted_reason
                else PAID_OWNER_CANCELLATION_REASON
            )
        else:
            reason = submitted_reason or OWNER_CANCELLATION_REASON

        max_reason_length = Booking._meta.get_field(
            'cancellation_reason',
        ).max_length
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancellation_reason = reason[:max_reason_length]
        booking.save(update_fields=(
            'status',
            'cancelled_at',
            'cancellation_reason',
            'updated_at',
        ))

    messages.success(
        request,
        f'Reservation {booking.payment_reference} was cancelled and its time slot released.',
    )
    if was_paid:
        messages.warning(
            request,
            'Payment had already been recorded. Coordinate any refund directly with the player.',
        )
    return redirect('owner_dashboard')
