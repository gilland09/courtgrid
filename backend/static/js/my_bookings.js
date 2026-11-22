const bookingsContainer = document.getElementById('bookings-container');
const bookingTabs = document.getElementById('booking-tabs');
const cancelModalElement = document.getElementById('cancel-booking-modal');
const cancelSummary = document.getElementById('cancel-booking-summary');
const cancelResult = document.getElementById('cancel-booking-result');
const confirmCancelButton = document.getElementById('confirm-cancel-booking');
const receiptModalElement = document.getElementById('booking-receipt-modal');
const receiptContent = document.getElementById('booking-receipt-content');

let allBookings = JSON.parse(document.getElementById('my-bookings-data').textContent);
let currentTab = 'upcoming';
let bookingToCancel = null;
let cancelling = false;

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
    const cookie = document.cookie.split('; ').find((entry) => entry.startsWith('csrftoken='));
    return cookie ? decodeURIComponent(cookie.slice('csrftoken='.length))
        : document.querySelector('#booking-csrf-form [name=csrfmiddlewaretoken]')?.value;
}

function formatBookingDateTime(value) {
    return new Intl.DateTimeFormat('en-PH', {
        timeZone: 'Asia/Manila', dateStyle: 'medium', timeStyle: 'short', hour12: true,
    }).format(new Date(value));
}

function batchFor(id) {
    const anchor = allBookings.find((item) => item.id === Number(id));
    if (!anchor) return null;
    const items = anchor.checkout_batch_id
        ? allBookings.filter((item) => item.facility_id === anchor.facility_id && item.checkout_batch_id === anchor.checkout_batch_id)
        : [anchor];
    return { ...anchor, items, total: items.reduce((sum, item) => sum + Math.round(Number(item.total_price) * 100), 0) / 100 };
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
    const statuses = new Set(booking.items.map((item) => item.payment_status));
    heading.textContent = statuses.size > 1 ? 'CourtGrid Reservation Receipt · Mixed Payment Statuses'
        : booking.payment_status === 'paid' ? 'CourtGrid Verified Payment Receipt'
        : 'CourtGrid Reservation Receipt · Payment Pending';
    receiptContent.append(heading);
    addReceiptRow('Batch reference', booking.checkout_batch_id || booking.payment_reference);
    addReceiptRow('Reservation references', booking.items.map((item) => item.payment_reference).join(', '));
    addReceiptRow('Venue', booking.facility_name);
    addReceiptRow('Merchant account', booking.merchant_account_name || booking.facility_name);
    const merchantNumber = booking.payment_method === 'gcash' ? booking.merchant_gcash_number
        : booking.payment_method === 'maya' ? booking.merchant_maya_number : '';
    if (merchantNumber) addReceiptRow('Merchant number', merchantNumber);
    const ranges = [];
    [...booking.items].sort((a, b) => a.resource_id - b.resource_id || Date.parse(a.start_datetime) - Date.parse(b.start_datetime)).forEach((item) => {
        const previous = ranges[ranges.length - 1];
        const day = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Manila', dateStyle: 'short' }).format(new Date(item.start_datetime));
        if (previous && previous.resourceId === item.resource_id && previous.day === day
            && Date.parse(previous.end) === Date.parse(item.start_datetime)) {
            previous.end = item.end_datetime;
        } else {
            ranges.push({ resourceId: item.resource_id, name: item.resource_name, day,
                start: item.start_datetime, end: item.end_datetime });
        }
    });
    ranges.forEach((range) => addReceiptRow('Schedule',
        `${range.name} · ${formatBookingDateTime(range.start)} – ${formatBookingDateTime(range.end)}`));
    addReceiptRow('Sport', booking.sport_name);
    addReceiptRow('Participant count', String(booking.participant_count));
    addReceiptRow('Player roster', booking.participant_names || 'Names not provided');
    addReceiptRow('Payment method', booking.payment_method_label || booking.payment_method);
    booking.items.forEach((item) => addReceiptRow(item.payment_reference, `${item.status} · ${item.payment_status}`));
    addReceiptRow('Total amount', `${booking.currency || 'PHP'} ${booking.total.toFixed(2)}`);
    const notice = document.createElement('p');
    notice.className = 'payment-processing-notice mb-0 mt-3';
    notice.textContent = statuses.size === 1 && booking.payment_status === 'paid'
        ? `Payment verification recorded${booking.payment_verified_at ? ` on ${formatBookingDateTime(booking.payment_verified_at)}` : ''}.`
        : 'This is a reservation record, not proof of payment. The venue must verify any external wallet transfer.';
    receiptContent.append(notice);
    openModal(receiptModalElement);
}

function selectTab() {
    bookingTabs.querySelectorAll('[data-booking-tab]').forEach((button) => {
        const active = button.dataset.bookingTab === currentTab;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-selected', String(active));
    });
    bookingsContainer.querySelectorAll('[data-booking-list]').forEach((list) => {
        list.hidden = list.dataset.bookingList !== currentTab;
    });
}

function showCancelMessage(message, type = 'danger') {
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.setAttribute('role', type === 'danger' ? 'alert' : 'status');
    alert.textContent = message;
    cancelResult.replaceChildren(alert);
}

const live = window.CourtGridLive.start({
    node: bookingsContainer,
    canUpdate: () => !cancelling && !window.CourtGridLive.blocked(),
    apply(payload) {
        const previous = new Map(allBookings.map((item) => [item.id, item.status]));
        const transitions = payload.bookings.filter((item) => previous.has(item.id) && previous.get(item.id) !== item.status);
        const changed = transitions.find((item) => item.id === payload.latest_status_hint?.booking_id) || transitions[0];
        const pageY = window.scrollY;
        allBookings = payload.bookings;
        bookingsContainer.innerHTML = payload.rows_html;
        Object.entries(payload.summary).forEach(([name, count]) => {
            bookingTabs.querySelector(`[data-booking-count="${name}"]`).textContent = count;
        });
        selectTab();
        window.scrollTo(window.scrollX, pageY);
        const message = changed?.status === 'CONFIRMED' ? 'Your booking has been confirmed.'
            : changed?.status === 'CANCELLED' ? 'Your booking has been cancelled or rejected.'
            : changed ? 'Your booking status was updated live.' : 'Your bookings were updated live.';
        window.CourtGridToast.show(message, 'info');
    },
});

bookingTabs.addEventListener('click', (event) => {
    const button = event.target.closest('[data-booking-tab]');
    if (button) {
        currentTab = button.dataset.bookingTab;
        selectTab();
    }
});

bookingsContainer.addEventListener('click', (event) => {
    const button = event.target.closest('[data-booking-id]');
    if (!button) return;
    const booking = batchFor(button.dataset.bookingId);
    if (!booking) return;
    if (button.classList.contains('booking-receipt-button')) {
        showReceipt(booking);
    } else if (button.classList.contains('booking-cancel-button')) {
        bookingToCancel = booking;
        cancelSummary.textContent = `Cancel all active slots in ${booking.checkout_batch_id || booking.payment_reference}.`;
        cancelResult.replaceChildren();
        openModal(cancelModalElement);
    }
});

confirmCancelButton.addEventListener('click', async () => {
    if (!bookingToCancel || cancelling) return;
    const csrfToken = getCsrfToken();
    if (!csrfToken) {
        showCancelMessage('Unable to verify your session. Reload the page and try again.');
        return;
    }
    cancelling = true;
    cancelModalElement.dataset.modalBusy = 'true';
    confirmCancelButton.disabled = true;
    confirmCancelButton.textContent = 'Cancelling…';
    try {
        const response = await fetch(`/api/bookings/${bookingToCancel.id}/cancel/`, {
            method: 'POST', credentials: 'same-origin',
            headers: { Accept: 'application/json', 'X-CSRFToken': csrfToken },
        });
        if (response.status === 401 || response.status === 403) {
            throw new Error('Your session has expired. Sign in again to continue.');
        }
        if (!response.ok) {
            const payload = await response.json();
            throw new Error(payload.detail || payload.booking || 'The booking could not be cancelled.');
        }
        showCancelMessage('Your booking has been cancelled.', 'success');
        window.setTimeout(() => {
            closeModal(cancelModalElement);
            live.check();
        }, 900);
    } catch (error) {
        showCancelMessage(error.message || 'The cancellation request could not be sent.');
    } finally {
        cancelling = false;
        delete cancelModalElement.dataset.modalBusy;
        confirmCancelButton.disabled = false;
        confirmCancelButton.textContent = 'Cancel Booking';
    }
});

document.getElementById('print-saved-booking-receipt').addEventListener('click', () => window.print());
selectTab();
