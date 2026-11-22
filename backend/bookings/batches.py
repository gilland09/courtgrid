from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from .models import Booking


@dataclass
class BookingBatch:
    bookings: list

    @property
    def first(self):
        return self.bookings[0]

    @property
    def reference(self):
        return self.first.checkout_batch_id or self.first.payment_reference

    @property
    def references(self):
        return ', '.join(booking.payment_reference for booking in self.bookings)

    @property
    def total(self):
        return sum((booking.total_price for booking in self.bookings), Decimal('0.00'))

    @property
    def fee(self):
        return sum((booking.platform_fee_amount for booking in self.bookings
                    if booking.status == Booking.Status.CONFIRMED
                    and booking.payment_status == Booking.PaymentStatus.PAID), Decimal('0.00'))

    @property
    def outstanding_fee(self):
        return sum((booking.platform_fee_amount for booking in self.bookings
                    if booking.status == Booking.Status.CONFIRMED
                    and booking.payment_status == Booking.PaymentStatus.PAID
                    and not booking.platform_fee_collected), Decimal('0.00'))

    @property
    def payout(self):
        return sum((booking.owner_payout_amount for booking in self.bookings
                    if booking.status == Booking.Status.CONFIRMED
                    and booking.payment_status == Booking.PaymentStatus.PAID), Decimal('0.00'))

    @property
    def slot_count(self):
        return len(self.bookings)

    @property
    def hours(self):
        return sum(
            (booking.end_datetime - booking.start_datetime).total_seconds()
            for booking in self.bookings
        ) / 3600

    @property
    def schedules(self):
        slots = sorted(self.bookings, key=lambda booking: (
            booking.resource_id, booking.start_datetime,
        ))
        ranges = []
        for booking in slots:
            start = timezone.localtime(booking.start_datetime)
            end = timezone.localtime(booking.end_datetime)
            if (
                ranges and ranges[-1]['resource_id'] == booking.resource_id
                and ranges[-1]['end'] == start
                and ranges[-1]['start'].date() == start.date()
            ):
                ranges[-1]['end'] = end
                ranges[-1]['slots'] += 1
                ranges[-1]['hours'] += (booking.end_datetime - booking.start_datetime).total_seconds() / 3600
            else:
                ranges.append({
                    'resource_id': booking.resource_id,
                    'court': booking.resource.name,
                    'start': start,
                    'end': end,
                    'slots': 1,
                    'hours': (booking.end_datetime - booking.start_datetime).total_seconds() / 3600,
                })
        return ranges

    @property
    def status(self):
        statuses = {booking.status for booking in self.bookings}
        return next(iter(statuses)) if len(statuses) == 1 else 'MIXED'

    @property
    def payment_status(self):
        statuses = {booking.payment_status for booking in self.bookings}
        return next(iter(statuses)) if len(statuses) == 1 else 'mixed'

    @property
    def pending(self):
        return next((booking for booking in self.bookings
                     if booking.status == Booking.Status.PENDING_VERIFICATION), None)

    @property
    def verifiable(self):
        return self.pending or next((booking for booking in self.bookings
                                    if booking.status == Booking.Status.CONFIRMED
                                    and booking.payment_status == Booking.PaymentStatus.PENDING), None)

    @property
    def receipt(self):
        return next((booking for booking in self.bookings if booking.payment_receipt), None)

    @property
    def has_cancelled(self):
        return any(booking.status == Booking.Status.CANCELLED for booking in self.bookings)

    @property
    def has_paid(self):
        return any(booking.status == Booking.Status.CONFIRMED
                   and booking.payment_status == Booking.PaymentStatus.PAID for booking in self.bookings)

    @property
    def has_unpaid(self):
        return any(booking.status in (Booking.Status.CONFIRMED, Booking.Status.PENDING_VERIFICATION)
                   and booking.payment_status == Booking.PaymentStatus.PENDING for booking in self.bookings)

    @property
    def active(self):
        return next((booking for booking in self.bookings
                     if booking.status in (Booking.Status.CONFIRMED, Booking.Status.PENDING_VERIFICATION)), None)

    @property
    def any_paid(self):
        return any(booking.payment_status == Booking.PaymentStatus.PAID for booking in self.bookings)

    @property
    def last_active_start(self):
        return max((booking.start_datetime for booking in self.bookings
                    if booking.status in (Booking.Status.CONFIRMED, Booking.Status.PENDING_VERIFICATION)),
                   default=self.first.start_datetime)

    @property
    def search_text(self):
        return ' '.join([
            self.reference, self.references, self.first.user.get_username(),
            self.first.user.get_full_name(), self.first.resource.facility.name,
            *(f'{booking.resource.name} {timezone.localtime(booking.start_datetime):%Y-%m-%d %b %d, %Y %I:%M %p}'
              for booking in self.bookings),
            *(f'{timezone.localtime(booking.start_datetime):%b} '
              f'{timezone.localtime(booking.start_datetime).day}, '
              f'{timezone.localtime(booking.start_datetime):%Y} '
              f"{timezone.localtime(booking.start_datetime).strftime('%I:%M %p').lstrip('0')}"
              for booking in self.bookings),
        ])


def group_bookings_into_batches(bookings):
    grouped = {}
    for booking in bookings:
        key = (
            booking.resource.facility_id,
            booking.user_id,
            booking.checkout_batch_id or f'legacy-{booking.pk}',
        )
        grouped.setdefault(key, []).append(booking)
    return [BookingBatch(items) for items in grouped.values()]
