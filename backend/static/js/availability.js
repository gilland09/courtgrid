const availabilityDate = document.getElementById('availability-date');
const availabilitySport = document.getElementById('availability-sport');
const availabilityResults = document.getElementById('availability-results');
const facilityDetail = document.getElementById('facility-detail');
const quickDatePills = document.getElementById('quick-date-pills');
const selectedSlotBar = document.getElementById('selected-slot-bar');
const selectedSlotLabel = document.getElementById('selected-slot-label');
const bookingModalElement = document.getElementById('booking-modal');
const bookingModal = new bootstrap.Modal(bookingModalElement);
const bookingSummary = document.getElementById('booking-summary');
const bookingResult = document.getElementById('booking-result');
const bookingForm = document.getElementById('booking-confirm-form');
const participantCount = document.getElementById('participant-count');
const participantCapacityHelp = document.getElementById('participant-capacity-help');
const confirmBookingButton = document.getElementById('confirm-booking');
const facilityResources = JSON.parse(document.getElementById('facility-resources-data').textContent);
const sportRates = JSON.parse(document.getElementById('sport-rates-data').textContent);

let selectedSlot = null;
let selectedSlotButton = null;

function formatSlotTime(value) {
    return new Intl.DateTimeFormat('en-PH', {
        timeZone: 'Asia/Manila',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).format(new Date(value));
}

function formatDate(value) {
    return new Intl.DateTimeFormat('en-PH', {
        timeZone: 'Asia/Manila',
        dateStyle: 'medium',
    }).format(new Date(`${value}T12:00:00+08:00`));
}

function createDateValue(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function renderQuickDates() {
    quickDatePills.replaceChildren();
    const [year, month, day] = availabilityDate.value.split('-').map(Number);
    const firstDate = new Date(year, month - 1, day);
    const todayValue = availabilityDate.value;

    for (let offset = 0; offset < 7; offset += 1) {
        const date = new Date(firstDate);
        date.setDate(firstDate.getDate() + offset);
        const value = createDateValue(date);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'quick-date-pill';
        button.dataset.date = value;
        button.setAttribute('aria-pressed', String(value === todayValue));

        const dayLabel = document.createElement('span');
        dayLabel.className = 'quick-date-day';
        dayLabel.textContent = offset === 0
            ? 'Today'
            : offset === 1
                ? 'Tomorrow'
                : new Intl.DateTimeFormat('en-PH', { weekday: 'short' }).format(date);
        const dateLabel = document.createElement('span');
        dateLabel.className = 'quick-date-number';
        dateLabel.textContent = new Intl.DateTimeFormat('en-PH', {
            month: 'short',
            day: 'numeric',
        }).format(date);
        button.append(dayLabel, dateLabel);
        button.addEventListener('click', () => {
            availabilityDate.value = value;
            renderQuickDates();
            clearSelectedSlot();
            searchAvailability();
        });
        quickDatePills.append(button);
    }
}

function showAvailabilityMessage(message, type = 'info') {
    const alert = document.createElement('div');
    alert.className = `alert alert-${type} availability-message`;
    alert.setAttribute('role', type === 'danger' ? 'alert' : 'status');
    alert.textContent = message;
    availabilityResults.replaceChildren(alert);
}

function resourceForSlot(slot) {
    return facilityResources.find((resource) => resource.id === slot.resource_id)
        || { id: slot.resource_id, name: `Court ${slot.resource_id}`, capacity: null };
}

function clearSelectedSlot() {
    if (selectedSlotButton) {
        selectedSlotButton.classList.remove('is-selected');
        selectedSlotButton.setAttribute('aria-pressed', 'false');
    }
    selectedSlot = null;
    selectedSlotButton = null;
    selectedSlotBar.hidden = true;
}

function selectSlot(button) {
    if (selectedSlotButton === button) {
        clearSelectedSlot();
        return;
    }
    clearSelectedSlot();
    selectedSlotButton = button;
    selectedSlotButton.classList.add('is-selected');
    selectedSlotButton.setAttribute('aria-pressed', 'true');
    selectedSlot = {
        resourceId: Number(button.dataset.resourceId),
        sportId: Number(button.dataset.sportId),
        startTime: button.dataset.startTime,
        endTime: button.dataset.endTime,
    };
    const resource = resourceForSlot(selectedSlot);
    selectedSlotLabel.textContent = `1 slot selected · ${resource.name} · ${formatSlotTime(selectedSlot.startTime)}`;
    selectedSlotBar.hidden = false;
}

function renderAvailabilitySlots(slots) {
    const slotsByResource = new Map();
    slots.forEach((slot) => {
        if (!slotsByResource.has(slot.resource_id)) {
            slotsByResource.set(slot.resource_id, []);
        }
        slotsByResource.get(slot.resource_id).push(slot);
    });

    const scheduleGrid = document.createElement('div');
    scheduleGrid.className = 'row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3';
    slotsByResource.forEach((resourceSlots, resourceId) => {
        const resource = resourceForSlot(resourceSlots[0]);
        const column = document.createElement('div');
        column.className = 'col';
        const courtCard = document.createElement('section');
        courtCard.className = 'court-schedule-card h-100';

        const heading = document.createElement('div');
        heading.className = 'court-schedule-heading';
        const courtName = document.createElement('h3');
        courtName.className = 'h6 mb-1';
        courtName.textContent = resource.name;
        const capacity = document.createElement('span');
        capacity.className = 'small text-body-secondary';
        capacity.textContent = resource.capacity
            ? `Up to ${resource.capacity} players`
            : 'Capacity not specified';
        heading.append(courtName, capacity);

        const slotsContainer = document.createElement('div');
        slotsContainer.className = 'court-time-slots';
        resourceSlots.forEach((slot) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'slot-button book-slot-btn';
            button.dataset.resourceId = slot.resource_id;
            button.dataset.startTime = slot.start_datetime;
            button.dataset.endTime = slot.end_datetime;
            button.dataset.sportId = slot.sport_id;
            button.dataset.resource = slot.resource_id;
            button.dataset.start = slot.start_datetime;
            button.dataset.end = slot.end_datetime;
            button.setAttribute('aria-pressed', 'false');
            button.textContent = `${formatSlotTime(slot.start_datetime)} – ${formatSlotTime(slot.end_datetime)}`;
            slotsContainer.append(button);
        });

        courtCard.append(heading, slotsContainer);
        column.append(courtCard);
        scheduleGrid.append(column);
    });
    availabilityResults.replaceChildren(scheduleGrid);
}

async function searchAvailability() {
    const date = availabilityDate.value;
    const sportId = availabilitySport.value;
    if (!date || !sportId) {
        showAvailabilityMessage('Choose a date and sport to view available courts.', 'warning');
        return;
    }

    const loading = document.createElement('p');
    loading.className = 'text-body-secondary';
    loading.textContent = 'Checking court availability…';
    availabilityResults.replaceChildren(loading);

    const query = new URLSearchParams({
        mode: 'parallel',
        facility: facilityDetail.dataset.facilityId,
        sport: sportId,
        date,
    });
    try {
        const response = await fetch(`/api/availability/search?${query}`, {
            headers: { Accept: 'application/json' },
            credentials: 'same-origin',
        });
        if (!response.ok) {
            throw new Error(`Availability request failed with status ${response.status}.`);
        }

        const payload = await response.json();
        if (!Array.isArray(payload.results)) {
            throw new Error('Availability response did not contain a results list.');
        }
        if (payload.results.length === 0) {
            showAvailabilityMessage('No courts are available for this date. Try another day.', 'warning');
            return;
        }
        renderAvailabilitySlots(payload.results);
    } catch (error) {
        console.error('Unable to load availability.', error);
        showAvailabilityMessage('Availability could not be loaded. Please try again later.', 'danger');
    }
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

function appendSummaryRow(container, label, value) {
    const row = document.createElement('div');
    row.className = 'booking-summary-row';
    const key = document.createElement('span');
    key.textContent = label;
    const content = document.createElement('strong');
    content.textContent = value;
    row.append(key, content);
    container.append(row);
}

function openBookingModal() {
    if (!selectedSlot) {
        return;
    }
    const resource = resourceForSlot(selectedSlot);
    const sportName = availabilitySport.selectedOptions[0].textContent.trim();
    const rate = sportRates[String(selectedSlot.sportId)];
    bookingSummary.replaceChildren();
    appendSummaryRow(bookingSummary, 'Facility', facilityDetail.dataset.facilityName);
    appendSummaryRow(bookingSummary, 'Court', resource.name);
    appendSummaryRow(bookingSummary, 'Sport', sportName);
    appendSummaryRow(bookingSummary, 'Date', formatDate(availabilityDate.value));
    appendSummaryRow(
        bookingSummary,
        'Time',
        `${formatSlotTime(selectedSlot.startTime)} – ${formatSlotTime(selectedSlot.endTime)} (Asia/Manila)`,
    );
    appendSummaryRow(
        bookingSummary,
        'Hourly rate',
        rate ? `₱${Number(rate).toFixed(2)} / hour` : 'Rate on request',
    );

    participantCount.value = '1';
    if (resource.capacity) {
        participantCount.max = resource.capacity;
        participantCapacityHelp.textContent = `Maximum ${resource.capacity} participants for this court.`;
    } else {
        participantCount.removeAttribute('max');
        participantCapacityHelp.textContent = 'Enter at least one participant.';
    }
    bookingResult.replaceChildren();
    bookingModal.show();
}

function bookingErrors(payload) {
    if (!payload || typeof payload !== 'object') {
        return ['Booking could not be completed. Review the details and try again.'];
    }
    return Object.entries(payload).flatMap(([field, messages]) => {
        const values = Array.isArray(messages) ? messages : [messages];
        return values.map((message) => {
            const text = typeof message === 'string' ? message : JSON.stringify(message);
            return field === 'detail' ? text : `${field.replaceAll('_', ' ')}: ${text}`;
        });
    });
}

function showBookingError(messages, type = 'danger') {
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.setAttribute('role', type === 'danger' ? 'alert' : 'status');
    messages.forEach((message, index) => {
        if (index > 0) {
            alert.append(document.createElement('br'));
        }
        alert.append(document.createTextNode(message));
    });
    bookingResult.replaceChildren(alert);
}

async function submitBooking(event) {
    event.preventDefault();
    if (!selectedSlot) {
        showBookingError(['Select an available court slot first.']);
        return;
    }

    const count = Number(participantCount.value);
    const capacity = resourceForSlot(selectedSlot).capacity;
    if (!Number.isInteger(count) || count < 1 || (capacity && count > capacity)) {
        participantCount.setCustomValidity(
            capacity ? `Enter a number from 1 to ${capacity}.` : 'Enter a whole number greater than zero.',
        );
        participantCount.reportValidity();
        return;
    }
    participantCount.setCustomValidity('');

    const csrfToken = getCsrfToken();
    if (!csrfToken) {
        showBookingError(['Unable to verify your session. Reload the page and try again.']);
        return;
    }

    confirmBookingButton.disabled = true;
    confirmBookingButton.textContent = 'Confirming…';
    try {
        const response = await fetch('/api/bookings/', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                Accept: 'application/json',
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify({
                resource_id: selectedSlot.resourceId,
                sport_id: selectedSlot.sportId,
                start_datetime: selectedSlot.startTime,
                end_datetime: selectedSlot.endTime,
                participant_count: count,
                participant_names: document.getElementById('participant-names').value,
            }),
        });
        const payload = await response.json().catch(() => null);
        if (response.status === 201) {
            const alert = document.createElement('div');
            alert.className = 'alert alert-success';
            alert.setAttribute('role', 'status');
            alert.append(document.createTextNode('Booking confirmed. '));
            const link = document.createElement('a');
            link.href = '/my-bookings/';
            link.className = 'alert-link';
            link.textContent = 'View My Bookings';
            alert.append(link);
            bookingResult.replaceChildren(alert);
            clearSelectedSlot();
            searchAvailability();
            return;
        }
        if (response.status === 403) {
            showBookingError(['Please sign in before confirming your booking.']);
            return;
        }
        showBookingError(
            bookingErrors(payload),
            response.status === 409 ? 'warning' : 'danger',
        );
    } catch (error) {
        console.error('Unable to submit booking.', error);
        showBookingError(['The booking request could not be sent. Please try again.']);
    } finally {
        confirmBookingButton.disabled = false;
        confirmBookingButton.textContent = 'Confirm Booking';
    }
}

quickDatePills.addEventListener('click', (event) => {
    const datePill = event.target.closest('[data-date]');
    if (datePill) {
        quickDatePills.querySelectorAll('[data-date]').forEach((pill) => {
            pill.setAttribute('aria-pressed', String(pill === datePill));
        });
    }
});

availabilitySport.addEventListener('change', () => {
    clearSelectedSlot();
    searchAvailability();
});

availabilityResults.addEventListener('click', (event) => {
    const button = event.target.closest('.slot-button');
    if (button && availabilityResults.contains(button)) {
        selectSlot(button);
    }
});

selectedSlotBar.addEventListener('click', (event) => {
    if (event.target.closest('#continue-booking')) {
        openBookingModal();
    }
});

participantCount.addEventListener('input', () => participantCount.setCustomValidity(''));
bookingForm.addEventListener('submit', submitBooking);

renderQuickDates();
searchAvailability();
