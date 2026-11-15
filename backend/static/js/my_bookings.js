const bookingsContainer = document.getElementById('bookings-container');
const bookingTabs = document.getElementById('booking-tabs');
const cancelModalElement = document.getElementById('cancel-booking-modal');
const cancelModal = new bootstrap.Modal(cancelModalElement);
const cancelSummary = document.getElementById('cancel-booking-summary');
const cancelResult = document.getElementById('cancel-booking-result');
const confirmCancelButton = document.getElementById('confirm-cancel-booking');

let allBookings = [];
let currentTab = 'upcoming';
let bookingToCancel = null;

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
    }).format(new Date(value));
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
    return {
        upcoming: allBookings.filter((booking) => (
            booking.status === 'CONFIRMED'
            && new Date(booking.start_datetime).getTime() > now
        )),
        past: allBookings.filter((booking) => (
            booking.status !== 'CONFIRMED'
            || new Date(booking.start_datetime).getTime() <= now
        )),
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
        court.textContent = booking.resource_name;
        titleGroup.append(title, court);
        const status = document.createElement('span');
        status.className = `reservation-status ${booking.status === 'CONFIRMED' ? 'is-confirmed' : 'is-cancelled'}`;
        status.textContent = booking.status === 'CONFIRMED' ? 'Confirmed' : 'Cancelled';
        top.append(titleGroup, status);
        body.append(top);

        addBookingDetail(body, 'Sport', booking.sport_name);
        addBookingDetail(
            body,
            'Date & time',
            `${formatBookingDateTime(booking.start_datetime)} – ${formatBookingDateTime(booking.end_datetime)}`,
        );
        addBookingDetail(body, 'Participants', String(booking.participant_count));
        addBookingDetail(body, 'Price', `${booking.currency} ${booking.total_price}`);

        if (
            booking.status === 'CONFIRMED'
            && new Date(booking.start_datetime).getTime() > Date.now()
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
    cancelSummary.textContent = `${booking.resource_name} · ${formatBookingDateTime(booking.start_datetime)}.`;
    cancelResult.replaceChildren();
    cancelModal.show();
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
            booking.id === bookingToCancel.id
                ? { ...booking, status: 'CANCELLED' }
                : booking
        ));
        renderBookings();
        window.setTimeout(() => cancelModal.hide(), 900);
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
    const button = event.target.closest('[data-booking-id]');
    const booking = allBookings.find((item) => item.id === Number(button?.dataset.bookingId));
    if (button && booking) {
        openCancelModal(booking);
    }
});

confirmCancelButton.addEventListener('click', cancelBooking);
fetchBookings();
