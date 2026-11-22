const bookingsContainer = document.getElementById('bookings-container');
const bookingTabs = document.getElementById('booking-tabs');
const cancelModalElement = document.getElementById('cancel-booking-modal');
const cancelSummary = document.getElementById('cancel-booking-summary');
const cancelResult = document.getElementById('cancel-booking-result');
const confirmCancelButton = document.getElementById('confirm-cancel-booking');
const receiptModalElement = document.getElementById('booking-receipt-modal');
const receiptContent = document.getElementById('booking-receipt-content');

let allBookings = [];
let currentTab = 'upcoming';
let bookingToCancel = null;

function openModal(modal) {
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('cg-modal-open');
}

function closeModal(modal) {
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('cg-modal-open');
}

function getCsrfToken() {
    const cookie = document.cookie
        .split('; ')
        .find((entry) => entry.startsWith('csrftoken='));
    if (cookie) {
        return decodeURIComponent(cookie.slice('csrftoken='.length));
    }
    return document.querySelector('#booking-csrf-form [name=csrfmiddlewaretoken]')?.value;
}

function formatBookingDateTime(value) {
    return new Intl.DateTimeFormat('en-PH', {
        timeZone: 'Asia/Manila',
        dateStyle: 'medium',
        timeStyle: 'short',
        hour12: true,
    }).format(new Date(value));
}

function addReceiptRow(label, value) {
    const row = document.createElement('div');
    row.className = 'booking-summary-row';
    const key = document.createElement('span');
    key.textContent = label;
    const content = document.createElement('strong');
    content.textContent = value || '—';
    row.append(key, content);
    receiptContent.append(row);
}

function showReceipt(booking) {
    receiptContent.replaceChildren();
    const heading = document.createElement('h3');
    heading.className = 'h5 mb-3';
    heading.textContent = booking.payment_status === 'mixed'
        ? 'CourtGrid Reservation Receipt · Mixed Payment Statuses'
        : booking.payment_status === 'paid'
        ? 'CourtGrid Verified Payment Receipt'
        : 'CourtGrid Reservation Receipt · Payment Pending';
    receiptContent.append(heading);
    addReceiptRow('Batch reference', booking.checkout_batch_id || booking.payment_reference);
    addReceiptRow('Reservation references', booking.items.map((item) => item.payment_reference).join(', '));
    addReceiptRow('Venue', booking.facility_name);
    addReceiptRow('Merchant account', booking.merchant_account_name || booking.facility_name);
    const merchantNumber = booking.payment_method === 'gcash'
        ? booking.merchant_gcash_number
        : booking.payment_method === 'maya'
            ? booking.merchant_maya_number
            : '';
    if (merchantNumber) {
        addReceiptRow('Merchant number', merchantNumber);
    }
    booking.schedules.forEach((schedule) => addReceiptRow('Schedule', schedule));
    addReceiptRow('Sport', booking.sport_name);
    addReceiptRow('Participant count', String(booking.participant_count));
    addReceiptRow('Player roster', booking.participant_names || 'Names not provided');
    addReceiptRow(
        'Payment method',
        ({
            gcash: 'GCash',
            maya: 'Maya',
            card: 'Credit / Debit Card',
            cash: 'Pay at Venue',
        })[booking.payment_method] || booking.payment_method_label || booking.payment_method,
    );
    addReceiptRow(
        'Payment status',
        booking.payment_status === 'mixed'
            ? 'MIXED · see individual reservations'
            : booking.payment_status === 'paid'
            ? 'PAID · merchant verified'
            : booking.payment_status === 'refunded'
                ? 'REFUNDED'
                : 'PENDING · not verified',
    );
    addReceiptRow('Total amount', `${booking.currency || 'PHP'} ${booking.total_price}`);
    const notice = document.createElement('p');
    notice.className = 'payment-processing-notice mb-0 mt-3';
    notice.textContent = booking.payment_status === 'mixed'
        ? 'Payment statuses differ across this checkout. Contact the venue for details.'
        : booking.payment_status === 'paid'
        ? `Payment verification recorded${booking.payment_verified_at ? ` on ${formatBookingDateTime(booking.payment_verified_at)}` : ''}.`
        : 'This is a reservation record, not proof of payment. The venue must verify any external wallet transfer.';
    receiptContent.append(notice);
    openModal(receiptModalElement);
}

function addBookingDetail(container, label, value) {
    const detail = document.createElement('p');
    detail.className = 'reservation-detail';
    const heading = document.createElement('span');
    heading.textContent = label;
    const content = document.createElement('strong');
    content.textContent = value;
    detail.append(heading, content);
    container.append(detail);
}

function partitionBookings() {
    const now = Date.now();
    const groups = new Map();
    allBookings.forEach((booking) => {
        const key = booking.checkout_batch_id
            ? `${booking.facility_id}:${booking.checkout_batch_id}`
            : `legacy:${booking.id}`;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(booking);
    });
    const batches = Array.from(groups.values(), (items) => {
        items.sort((a, b) => a.resource_id - b.resource_id || Date.parse(a.start_datetime) - Date.parse(b.start_datetime));
        const ranges = [];
        items.forEach((item) => {
            const previous = ranges[ranges.length - 1];
            const date = formatBookingDateTime(item.start_datetime).split(',')[0];
            if (previous && previous.resource_id === item.resource_id
                && Date.parse(previous.end) === Date.parse(item.start_datetime)
                && previous.date === date) {
                previous.end = item.end_datetime;
                previous.slots += 1;
                previous.hours += (Date.parse(item.end_datetime) - Date.parse(item.start_datetime)) / 3600000;
            } else {
                ranges.push({ resource_id: item.resource_id, name: item.resource_name,
                    start: item.start_datetime, end: item.end_datetime, date, slots: 1,
                    hours: (Date.parse(item.end_datetime) - Date.parse(item.start_datetime)) / 3600000 });
            }
        });
        const statuses = new Set(items.map((item) => item.status));
        const payments = new Set(items.map((item) => item.payment_status));
        const active = items.filter((item) => item.status === 'CONFIRMED' || item.status === 'PENDING_VERIFICATION');
        const cents = items.reduce((sum, item) => sum + Math.round(Number(item.total_price) * 100), 0);
        const hours = items.reduce((sum, item) => sum + (Date.parse(item.end_datetime) - Date.parse(item.start_datetime)) / 3600000, 0);
        return {
            ...items[0], items, active,
            status: statuses.size === 1 ? items[0].status : 'MIXED',
            payment_status: payments.size === 1 ? items[0].payment_status : 'mixed',
            total_price: (cents / 100).toFixed(2), hours,
            schedules: ranges.map((range) => `${range.name} · ${formatBookingDateTime(range.start)} – ${formatBookingDateTime(range.end)} (${range.hours} hrs)`),
        };
    });
    return {
        upcoming: batches.filter((batch) => batch.active.some((item) => Date.parse(item.start_datetime) > now)),
        past: batches.filter((batch) => !batch.active.some((item) => Date.parse(item.start_datetime) > now)),
    };
}

function updateBookingTabs(bookings) {
    Object.entries(bookings).forEach(([tab, values]) => {
        const count = bookingTabs.querySelector(`[data-booking-count="${tab}"]`);
        count.textContent = values.length;
    });
    bookingTabs.querySelectorAll('[data-booking-tab]').forEach((button) => {
        const active = button.dataset.bookingTab === currentTab;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-selected', String(active));
    });
}

function renderEmptyState() {
    const empty = document.createElement('section');
    empty.className = 'booking-empty-state';
    const icon = document.createElement('div');
    icon.className = 'ticket-icon';
    icon.setAttribute('aria-hidden', 'true');
    const ticket = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    ticket.setAttribute('viewBox', '0 0 24 24');
    ticket.setAttribute('width', '28');
    ticket.setAttribute('height', '28');
    ticket.setAttribute('fill', 'none');
    ticket.setAttribute('stroke', 'currentColor');
    ticket.setAttribute('stroke-width', '1.8');
    ticket.setAttribute('stroke-linecap', 'round');
    ticket.setAttribute('stroke-linejoin', 'round');
    const ticketPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    ticketPath.setAttribute('d', 'M4 7a2 2 0 0 0 0 4v2a2 2 0 0 0 0 4h16a2 2 0 0 0 0-4v-2a2 2 0 0 0 0-4H4Z');
    const ticketDash = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    ticketDash.setAttribute('d', 'M13 7v2m0 3v2m0 3v2');
    ticket.append(ticketPath, ticketDash);
    icon.append(ticket);
    const title = document.createElement('h2');
    title.className = 'h4';
    title.textContent = 'Nothing here yet';
    const message = document.createElement('p');
    message.className = 'text-body-secondary';
    message.textContent = currentTab === 'upcoming'
        ? 'Ready for your next game? Find a court and reserve your time.'
        : 'Completed and cancelled reservations will appear here.';
    empty.append(icon, title, message);
    if (currentTab === 'upcoming') {
        const link = document.createElement('a');
        link.className = 'btn btn-primary booking-pill-button';
        link.href = '/home/';
        link.textContent = 'Book a court';
        empty.append(link);
    }
    bookingsContainer.replaceChildren(empty);
}

function renderBookings() {
    const partitions = partitionBookings();
    updateBookingTabs(partitions);
    const bookings = partitions[currentTab];
    if (bookings.length === 0) {
        renderEmptyState();
        return;
    }

    const list = document.createElement('div');
    list.className = 'row g-3';
    bookings.forEach((booking) => {
        const column = document.createElement('div');
        column.className = 'col-12 col-lg-6';
        const card = document.createElement('article');
        card.className = 'reservation-card h-100';
        const body = document.createElement('div');
        body.className = 'reservation-card-body';

        const top = document.createElement('div');
        top.className = 'd-flex justify-content-between align-items-start gap-2 mb-3';
        const titleGroup = document.createElement('div');
        const title = document.createElement('h2');
        title.className = 'h5 mb-1';
        title.textContent = booking.facility_name;
        const court = document.createElement('p');
        court.className = 'small text-body-secondary mb-0';
        court.textContent = `${booking.items.length} slots · ${booking.hours} hrs`;
        titleGroup.append(title, court);
        const status = document.createElement('span');
        status.className = `reservation-status ${booking.status === 'CONFIRMED' ? 'is-confirmed' : booking.status === 'PENDING_VERIFICATION' || booking.status === 'MIXED' ? 'is-pending' : 'is-cancelled'}`;
        status.textContent = booking.status === 'MIXED' ? 'Mixed statuses' : booking.status === 'CONFIRMED' ? 'Confirmed'
            : booking.status === 'PENDING_VERIFICATION' ? 'Awaiting Owner Verification' : 'Cancelled';
        top.append(titleGroup, status);
        body.append(top);

        addBookingDetail(body, 'Sport', booking.sport_name);
        booking.schedules.forEach((schedule) => addBookingDetail(body, 'Schedule', schedule));
        addBookingDetail(body, 'Participants', String(booking.participant_count));
        if (booking.booking_type === 'organizer') {
            addBookingDetail(body, 'Organization', booking.organization_name);
            addBookingDetail(body, 'Event', booking.event_name);
            addBookingDetail(body, 'Expected participants', String(booking.expected_participants));
        }
        addBookingDetail(body, 'Price', `${booking.currency} ${booking.total_price}`);
        const paymentMethods = {
            gcash: 'GCash',
            maya: 'Maya',
            card: 'Credit / Debit Card',
            cash: 'Pay at Venue',
        };
        addBookingDetail(
            body,
            'Payment method',
            booking.payment_method_label || paymentMethods[booking.payment_method] || booking.payment_method,
        );
        const paymentBadge = document.createElement('span');
        paymentBadge.className = 'payment-receipt-badge mb-2';
        if (booking.payment_status === 'pending') {
            paymentBadge.classList.add('payment-pending-badge');
        }
        paymentBadge.textContent = booking.payment_status === 'mixed' ? 'Mixed payment statuses' : booking.payment_status === 'pending'
            ? 'Payment pending · venue verification'
            : booking.payment_status === 'refunded'
                ? 'Refunded'
                : 'Paid';
        body.append(paymentBadge);
        addBookingDetail(body, 'Batch reference', booking.checkout_batch_id || booking.payment_reference);
        addBookingDetail(body, 'Reservation references', booking.items.map((item) => item.payment_reference).join(', '));
        if (booking.status === 'MIXED' || booking.payment_status === 'mixed') {
            booking.items.forEach((item) => addBookingDetail(body, item.payment_reference, `${item.status} · ${item.payment_status}`));
        }
        booking.items.filter((item) => item.cancellation_reason).forEach((item) => {
            addBookingDetail(body, `Cancellation reason (${item.payment_reference})`, item.cancellation_reason);
        });

        const receiptButton = document.createElement('button');
        receiptButton.type = 'button';
        receiptButton.className = 'btn btn-outline-primary booking-receipt-button mt-2';
        receiptButton.dataset.bookingId = booking.id;
        receiptButton.textContent = 'View Reservation';
        body.append(receiptButton);
        if (booking.payment_receipt_url) {
            const uploadedReceipt = document.createElement('a');
            uploadedReceipt.className = 'btn btn-outline-primary mt-2 ms-2';
            uploadedReceipt.href = booking.payment_receipt_url;
            uploadedReceipt.textContent = 'View Receipt';
            body.append(uploadedReceipt);
        }

        if (
            booking.active.length > 0
            && booking.active.every((item) => Date.parse(item.start_datetime) > Date.now())
        ) {
            const cancelButton = document.createElement('button');
            cancelButton.type = 'button';
            cancelButton.className = 'btn btn-outline-danger booking-cancel-button mt-2';
            cancelButton.dataset.bookingId = booking.id;
            cancelButton.textContent = 'Cancel Booking';
            body.append(cancelButton);
        }

        card.append(body);
        column.append(card);
        list.append(column);
    });
    bookingsContainer.replaceChildren(list);
}

function showBookingsError(message) {
    const alert = document.createElement('div');
    alert.className = 'alert alert-danger';
    alert.setAttribute('role', 'alert');
    alert.textContent = message;
    bookingsContainer.replaceChildren(alert);
}

async function fetchBookings() {
    bookingsContainer.replaceChildren();
    const loading = document.createElement('p');
    loading.className = 'text-body-secondary';
    loading.textContent = 'Loading your bookings…';
    bookingsContainer.append(loading);

    try {
        const response = await fetch('/api/bookings/my/', {
            headers: { Accept: 'application/json' },
            credentials: 'same-origin',
        });
        if (response.status === 403) {
            window.location.assign('/');
            return;
        }
        if (!response.ok) {
            throw new Error(`Booking request failed with status ${response.status}.`);
        }
        allBookings = await response.json();
        if (!Array.isArray(allBookings)) {
            throw new Error('Booking response was not a list.');
        }
        renderBookings();
    } catch (error) {
        console.error('Unable to load bookings.', error);
        showBookingsError('Your bookings could not be loaded. Please try again later.');
    }
}

function showCancelMessage(message, type = 'danger') {
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.setAttribute('role', type === 'danger' ? 'alert' : 'status');
    alert.textContent = message;
    cancelResult.replaceChildren(alert);
}

function openCancelModal(booking) {
    bookingToCancel = booking;
    cancelSummary.textContent = `Cancel all active slots in ${booking.checkout_batch_id || booking.payment_reference}: ${booking.schedules.join('; ')}.`;
    cancelResult.replaceChildren();
    openModal(cancelModalElement);
}

async function cancelBooking() {
    if (!bookingToCancel) {
        return;
    }
    const csrfToken = getCsrfToken();
    if (!csrfToken) {
        showCancelMessage('Unable to verify your session. Reload the page and try again.');
        return;
    }

    confirmCancelButton.disabled = true;
    confirmCancelButton.textContent = 'Cancelling…';
    try {
        const response = await fetch(`/api/bookings/${bookingToCancel.id}/cancel/`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                Accept: 'application/json',
                'X-CSRFToken': csrfToken,
            },
        });
        if (response.status === 403) {
            showCancelMessage('Your session has expired. Sign in again to continue.');
            return;
        }
        if (!response.ok) {
            const payload = await response.json().catch(() => null);
            showCancelMessage(payload?.detail || 'The booking could not be cancelled.');
            return;
        }
        showCancelMessage('Your booking has been cancelled.', 'success');
        allBookings = allBookings.map((booking) => (
            bookingToCancel.active.some((item) => item.id === booking.id)
                ? {
                    ...booking,
                    status: 'CANCELLED',
                    cancellation_reason: 'Cancelled by customer',
                }
                : booking
        ));
        renderBookings();
        window.setTimeout(() => closeModal(cancelModalElement), 900);
    } catch (error) {
        console.error('Unable to cancel booking.', error);
        showCancelMessage('The cancellation request could not be sent. Please try again.');
    } finally {
        confirmCancelButton.disabled = false;
        confirmCancelButton.textContent = 'Cancel Booking';
    }
}

bookingTabs.addEventListener('click', (event) => {
    const button = event.target.closest('[data-booking-tab]');
    if (button) {
        currentTab = button.dataset.bookingTab;
        renderBookings();
    }
});

bookingsContainer.addEventListener('click', (event) => {
    const receiptButton = event.target.closest('.booking-receipt-button');
    if (receiptButton) {
        const booking = Object.values(partitionBookings()).flat().find(
            (item) => String(item.id) === receiptButton.dataset.bookingId,
        );
        if (booking) {
            showReceipt(booking);
        }
        return;
    }
    const button = event.target.closest('[data-booking-id]');
    const booking = Object.values(partitionBookings()).flat().find((item) => item.id === Number(button?.dataset.bookingId));
    if (button && booking) {
        openCancelModal(booking);
    }
});

document.getElementById('print-saved-booking-receipt').addEventListener('click', () => {
    window.print();
});

confirmCancelButton.addEventListener('click', cancelBooking);
fetchBookings();
