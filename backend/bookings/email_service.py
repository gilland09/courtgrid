import json
import logging
from email.utils import formataddr
from html import escape
from urllib import request

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from .models import Booking
from .batches import BookingBatch

logger = logging.getLogger(__name__)
BREVO_URL = 'https://api.brevo.com/v3/smtp/email'


def _deliver(booking, subject, introduction, details, closing):
    recipient = (booking.user.email or '').strip() or (booking.contact_email or '').strip()
    if not recipient:
        logger.warning('No email address for booking %s', booking.pk)
        return {'sent': False, 'reason': 'No customer email address is available.'}

    text = '\n'.join([introduction, '', *details, '', closing])
    html_details = ''.join(f'<li>{escape(detail)}</li>' for detail in details)
    html = (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">'
        '</head><body style="margin:0;background:#f3f8f5;'
        'font-family:Arial,sans-serif;color:#173b2b">'
        '<main style="max-width:600px;margin:24px auto;padding:24px;'
        'background:#fff;border-top:6px solid #087443">'
        f'<h1 style="color:#087443">CourtGrid</h1><p>{escape(introduction)}</p>'
        f'<ul>{html_details}</ul><p>{escape(closing)}</p></main></body></html>'
    )
    try:
        if settings.BREVO_API_KEY:
            payload = {
                'sender': {'email': settings.BREVO_SENDER_EMAIL, 'name': settings.BREVO_SENDER_NAME},
                'to': [{'email': recipient}],
                'subject': subject,
                'htmlContent': html,
                'textContent': text,
            }
            api_request = request.Request(
                BREVO_URL, data=json.dumps(payload).encode('utf-8'), method='POST',
                headers={
                    'api-key': settings.BREVO_API_KEY,
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
            )
            with request.urlopen(api_request, timeout=10) as response:
                if not 200 <= response.status < 300:
                    raise OSError(f'Email provider returned HTTP {response.status}')
        else:
            email = EmailMultiAlternatives(
                subject, text, formataddr((settings.BREVO_SENDER_NAME, settings.DEFAULT_FROM_EMAIL)),
                [recipient],
            )
            email.attach_alternative(html, 'text/html')
            if email.send() != 1:
                raise OSError('Email backend did not send the message')
            if settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
                logger.warning('Booking email for booking %s was written to the console, not delivered', booking.pk)
                return {'sent': False, 'reason': 'Notification was written to the console, not delivered to the customer.'}
    except Exception:
        logger.exception('Could not send booking email for booking %s', booking.pk)
        return {'sent': False, 'reason': 'Email delivery failed. Please contact the customer directly.'}
    return {'sent': True, 'reason': ''}


def _booking_details(batch):
    booking = batch.first
    facility = booking.resource.facility
    location = ', '.join(part for part in (facility.address, facility.barangay) if part)
    details = [
        f'Batch reference: {batch.reference}',
        f'Reservation references: {batch.references}',
        f'Venue: {facility.name}' + (f' - {location}' if location else ''),
        *(f"Schedule: {item['court']} - {item['start']:%b %d, %Y} "
          f"{item['start'].strftime('%I:%M %p').lstrip('0')} - "
          f"{item['end'].strftime('%I:%M %p').lstrip('0')}"
          for item in batch.schedules),
        f'Booking type: {booking.get_booking_type_display()}',
    ]
    if booking.booking_type == Booking.BookingType.ORGANIZER:
        details.extend([
            f'Organization: {booking.organization_name}',
            f'Event: {booking.event_name}',
            f'Expected participants: {booking.expected_participants}',
        ])
    return details


def send_booking_confirmed_email(booking):
    batch = booking if isinstance(booking, BookingBatch) else BookingBatch([booking])
    booking = batch.first
    details = _booking_details(batch)
    details.extend([
        f'Payment method: {booking.payment_method_label or booking.get_payment_method_display()}',
        f'Total paid: ₱{batch.total:.2f}',
    ])
    return _deliver(
        booking, f'Your CourtGrid booking is confirmed - {batch.reference} ({booking.payment_reference})',
        'Congratulations! Your payment has been verified and your booking is officially confirmed.',
        details, 'Enjoy your time at the venue!',
    )


def send_booking_rejected_email(booking):
    batch = booking if isinstance(booking, BookingBatch) else BookingBatch([booking])
    booking = batch.first
    details = _booking_details(batch)
    details.append(f'Payment method: {booking.payment_method_label or booking.get_payment_method_display()}')
    details.append(f'Total: ₱{batch.total:.2f}')
    details.append(f'Reason: {booking.cancellation_reason}')
    return _deliver(
        booking, f'Your CourtGrid receipt could not be verified - {batch.reference} ({booking.payment_reference})',
        'We are sorry, but the venue could not verify your payment receipt.',
        details, 'This reservation hold has been released. You are welcome to submit a fresh booking.',
    )


def send_booking_cancelled_email(batch):
    booking = batch.first
    details = _booking_details(batch)
    details.extend([
        f'Payment method: {booking.payment_method_label or booking.get_payment_method_display()}',
        f'Cancelled booking total: ₱{batch.total:.2f}',
        *(f'{item.payment_reference}: {item.cancellation_reason}' for item in batch.bookings),
    ])
    closing = (
        'Please coordinate any refund directly with the venue.'
        if batch.any_paid else 'The cancelled slots have been released.'
    )
    return _deliver(
        booking, f'Your CourtGrid booking was cancelled - {batch.reference} ({booking.payment_reference})',
        'We are sorry, but this booking has been cancelled.', details, closing,
    )
