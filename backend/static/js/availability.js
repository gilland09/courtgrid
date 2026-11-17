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
const bookingFields = document.getElementById('booking-fields');
const bookingConfirmedState = document.getElementById('booking-confirmed-state');
const bookingConfirmedSummary = document.getElementById('booking-confirmed-summary');
const rentalBreakdownLabel = document.getElementById('rental-breakdown-label');
const rentalBreakdownAmount = document.getElementById('rental-breakdown-amount');
const platformFeeBreakdown = document.getElementById('platform-fee-breakdown');
const totalDueBreakdown = document.getElementById('total-due-breakdown');
const paymentMethodOptions = document.querySelectorAll('[name="payment_method"]');
const participantCount = document.getElementById('participant-count');
const participantCapacityHelp = document.getElementById('participant-capacity-help');
const playerNamesGrid = document.getElementById('player-names-grid');
const bookerEmail = document.getElementById('booker-email');
const bookerPhone = document.getElementById('booker-phone');
const confirmBookingButton = document.getElementById('confirm-booking');
const facilityResources = JSON.parse(document.getElementById('facility-resources-data').textContent);
const sportRates = JSON.parse(document.getElementById('sport-rates-data').textContent);
const baseToday = availabilityDate.value || getManilaToday();
const availabilityHelpers = window.CourtGridAvailabilityHelpers;

let selectedSlots = [];
let slotButtons = new Map();
let playerNames = [];
let minimumSelectedCapacity = null;
let availabilityRequest = 0;

function getManilaToday() {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Manila',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
    return `${values.year}-${values.month}-${values.day}`;
}

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

function formatCurrency(value) {
    return new Intl.NumberFormat('en-PH', {
        style: 'currency',
        currency: 'PHP',
    }).format(value);
}

function renderQuickDates() {
    quickDatePills.replaceChildren();
    availabilityHelpers.getSevenDayDates(baseToday).forEach((value, offset) => {
        const date = new Date(`${value}T00:00:00Z`);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'quick-date-pill';
        button.dataset.date = value;
        button.classList.toggle('active', value === availabilityDate.value);
        button.setAttribute('aria-pressed', String(value === availabilityDate.value));

        const dayLabel = document.createElement('span');
        dayLabel.className = 'quick-date-day';
        dayLabel.textContent = offset === 0
            ? 'Today'
            : offset === 1
                ? 'Tomorrow'
                : new Intl.DateTimeFormat('en-PH', {
                    weekday: 'short',
                    timeZone: 'UTC',
                }).format(date);
        const dateLabel = document.createElement('span');
        dateLabel.className = 'quick-date-number';
        dateLabel.textContent = new Intl.DateTimeFormat('en-PH', {
            month: 'short',
            day: 'numeric',
            timeZone: 'UTC',
        }).format(date);
        button.append(dayLabel, dateLabel);
        quickDatePills.append(button);
    });
}

function updateActiveDatePill() {
    quickDatePills.querySelectorAll('[data-date]').forEach((pill) => {
        const active = pill.dataset.date === availabilityDate.value;
        pill.classList.toggle('active', active);
        pill.setAttribute('aria-pressed', String(active));
    });
}

function showAvailabilityMessage(message, type = 'info') {
    const alert = document.createElement('div');
    alert.className = `alert alert-${type} availability-message`;
    alert.setAttribute('role', type === 'danger' ? 'alert' : 'status');
    alert.textContent = message;
    availabilityResults.replaceChildren(alert);
}

function resourceForSlot(slot) {
    const resourceId = Number(slot.resourceId ?? slot.resource_id);
    const resource = facilityResources.find((item) => item.id === resourceId);
    return resource || {
        id: resourceId,
        name: slot.resource_name || (Number.isFinite(resourceId) ? `Court ${resourceId}` : 'Court'),
        capacity: null,
    };
}

function selectedTotal() {
    return availabilityHelpers.calculateSlotTotal(selectedSlots, sportRates);
}

function selectedPaymentMethod() {
    return document.querySelector('[name="payment_method"]:checked')?.value || 'gcash';
}

function updatePaymentBreakdown() {
    const gross = selectedTotal();
    const breakdown = availabilityHelpers.calculateFeeBreakdown(gross);
    const slotCount = selectedSlots.length;
    const hourlyRate = slotCount ? Number(sportRates[String(selectedSlots[0].sportId)] || 0) : 0;
    rentalBreakdownLabel.textContent = (
        `Court Rental (${slotCount} ${slotCount === 1 ? 'slot' : 'slots'} × `
        + `${formatCurrency(hourlyRate)}/hr)`
    );
    rentalBreakdownAmount.textContent = formatCurrency(breakdown.gross);
    platformFeeBreakdown.textContent = formatCurrency(breakdown.platformFee);
    totalDueBreakdown.textContent = formatCurrency(breakdown.gross);
}

function updateStickyBar() {
    if (selectedSlots.length === 0 || bookingModalElement.classList.contains('show')) {
        selectedSlotBar.hidden = true;
        selectedSlotBar.classList.add('d-none');
        return;
    }
    const details = selectedSlots.slice(0, 2).map((slot) => {
        const resource = resourceForSlot(slot);
        return `${resource.name} (${formatSlotTime(slot.startTime)}–${formatSlotTime(slot.endTime)})`;
    });
    if (selectedSlots.length > details.length) {
        details.push(`+${selectedSlots.length - details.length} more`);
    }
    selectedSlotLabel.textContent = (
        `${selectedSlots.length} ${selectedSlots.length === 1 ? 'slot' : 'slots'} selected · `
        + `${details.join(' · ')} · ${formatCurrency(selectedTotal())} total`
    );
    selectedSlotBar.hidden = false;
    selectedSlotBar.classList.remove('d-none');
}

function setSlotSelected(slot, selected) {
    const button = slotButtons.get(slot.key);
    if (!button) {
        return;
    }
    button.classList.toggle('is-selected', selected);
    button.setAttribute('aria-pressed', String(selected));
}

function clearSelectedSlots() {
    selectedSlots.forEach((slot) => setSlotSelected(slot, false));
    selectedSlots = [];
    updateStickyBar();
}

function toggleSlot(button) {
    const resourceId = Number(button.dataset.resourceId);
    const startTime = button.dataset.startTime;
    const key = availabilityHelpers.getSlotKey(resourceId, startTime);
    const existingIndex = selectedSlots.findIndex((slot) => slot.key === key);
    if (existingIndex >= 0) {
        const [removed] = selectedSlots.splice(existingIndex, 1);
        setSlotSelected(removed, false);
    } else {
        selectedSlots.push({
            key,
            resourceId,
            sportId: Number(button.dataset.sportId),
            startTime,
            endTime: button.dataset.endTime,
        });
        setSlotSelected(selectedSlots[selectedSlots.length - 1], true);
    }
    updateStickyBar();
    updatePaymentBreakdown();
}

function renderAvailabilitySlots(slots) {
    slotButtons = new Map();
    const slotsByResource = new Map();
    slots.forEach((slot) => {
        if (!slotsByResource.has(slot.resource_id)) {
            slotsByResource.set(slot.resource_id, []);
        }
        slotsByResource.get(slot.resource_id).push(slot);
    });

    const scheduleGrid = document.createElement('div');
    scheduleGrid.className = 'row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3';
    slotsByResource.forEach((resourceSlots) => {
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
            button.setAttribute('aria-pressed', 'false');
            button.textContent = `${formatSlotTime(slot.start_datetime)} – ${formatSlotTime(slot.end_datetime)}`;
            const key = availabilityHelpers.getSlotKey(slot.resource_id, slot.start_datetime);
            slotButtons.set(key, button);
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
    const requestId = ++availabilityRequest;
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
        if (requestId !== availabilityRequest) {
            return;
        }
        if (!Array.isArray(payload.results)) {
            throw new Error('Availability response did not contain a results list.');
        }
        if (payload.results.length === 0) {
            showAvailabilityMessage('No courts are available for this date. Try another day.', 'warning');
            return;
        }
        renderAvailabilitySlots(payload.results);
    } catch (error) {
        if (requestId !== availabilityRequest) {
            return;
        }
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

function selectedCapacity() {
    const capacities = selectedSlots
        .map((slot) => resourceForSlot(slot).capacity)
        .filter((capacity) => Number.isInteger(capacity) && capacity > 0);
    return capacities.length ? Math.min(...capacities) : null;
}

function updatePlayerNameInputs() {
    const count = Math.max(1, Math.min(100, Number(participantCount.value) || 1));
    const visibleValues = Array.from(
        playerNamesGrid.querySelectorAll('[data-player-name]'),
        (input) => input.value,
    );
    playerNames = availabilityHelpers.resizePlayerNames(
        playerNames,
        visibleValues,
        count,
    );
    playerNamesGrid.replaceChildren();
    for (let index = 0; index < count; index += 1) {
        const column = document.createElement('div');
        column.className = 'player-name-field';
        const label = document.createElement('label');
        label.className = 'form-label';
        label.htmlFor = `player-name-${index + 1}`;
        label.textContent = `Player ${index + 1} Name`;
        const input = document.createElement('input');
        input.type = 'text';
        input.id = label.htmlFor;
        input.className = 'form-control';
        input.maxLength = 100;
        input.dataset.playerName = index + 1;
        input.value = playerNames[index] || '';
        input.autocomplete = 'off';
        input.addEventListener('input', () => {
            playerNames[index] = input.value;
        });
        column.append(label, input);
        playerNamesGrid.append(column);
    }
}

function validateContactInput(input, errorElement, message, isValid) {
    const valid = isValid(input.value.trim());
    input.classList.toggle('is-invalid', !valid);
    errorElement.textContent = valid ? '' : message;
    return valid;
}

function validateBookingForm() {
    const emailError = document.getElementById('booker-email-error');
    const phoneError = document.getElementById('booker-phone-error');
    const emailValid = validateContactInput(
        bookerEmail,
        emailError,
        'Enter a valid contact email address.',
        availabilityHelpers.isValidEmail,
    );
    const phoneValid = validateContactInput(
        bookerPhone,
        phoneError,
        'Enter a valid phone number with at least 7 digits.',
        availabilityHelpers.isValidPhone,
    );
    return emailValid && phoneValid;
}

function renderSlotSummary(container, slots) {
    container.replaceChildren();
    slots.forEach((slot) => {
        const resource = resourceForSlot(slot);
        appendSummaryRow(
            container,
            resource.name,
            `${formatDate(availabilityDate.value)} · ${formatSlotTime(slot.startTime)}–${formatSlotTime(slot.endTime)}`,
        );
    });
}

function openBookingModal() {
    if (selectedSlots.length === 0) {
        return;
    }
    const sportName = availabilitySport.selectedOptions[0].textContent.trim();
    bookingSummary.replaceChildren();
    appendSummaryRow(bookingSummary, 'Facility', facilityDetail.dataset.facilityName);
    appendSummaryRow(bookingSummary, 'Sport', sportName);
    renderSlotSummary(bookingSummary, selectedSlots);
    appendSummaryRow(bookingSummary, 'Participants', participantCount.value || '1');
    appendSummaryRow(bookingSummary, 'Hourly rate total', formatCurrency(selectedTotal()));
    updatePaymentBreakdown();

    minimumSelectedCapacity = selectedCapacity();
    participantCount.value = '1';
    if (minimumSelectedCapacity) {
        participantCount.max = minimumSelectedCapacity;
        participantCapacityHelp.textContent = (
            `Maximum ${minimumSelectedCapacity} participants across the selected courts.`
        );
    } else {
        participantCount.removeAttribute('max');
        participantCapacityHelp.textContent = 'Enter at least one participant.';
    }
    playerNames = [];
    updatePlayerNameInputs();
    bookingResult.replaceChildren();
    bookingFields.hidden = false;
    bookingConfirmedState.hidden = true;
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

function showConfirmedState(payload, bookedSlots, names) {
    const bookings = Array.isArray(payload.results) ? payload.results : [payload];
    bookingConfirmedSummary.replaceChildren();
    bookings.forEach((booking, index) => {
        const originalSlot = bookedSlots[index];
        appendSummaryRow(
            bookingConfirmedSummary,
            booking.resource_name || resourceForSlot(originalSlot).name,
            `${formatDate(availabilityDate.value)} · ${formatSlotTime(booking.start_datetime)}–${formatSlotTime(booking.end_datetime)}`,
        );
    });
    appendSummaryRow(
        bookingConfirmedSummary,
        bookings[0]?.payment_status === 'pending' ? 'Total due at venue' : 'Total paid',
        formatCurrency(Number(payload.total_price ?? bookings.reduce(
            (total, booking) => total + Number(booking.total_price || 0),
            0,
        ))),
    );
    const paymentMethod = bookings[0]?.payment_method || 'gcash';
    const paymentLabels = {
        gcash: 'GCash',
        maya: 'Maya',
        card: 'Credit / Debit Card',
        cash: 'Pay at Venue',
    };
    const paymentStatus = bookings[0]?.payment_status || (
        paymentMethod === 'cash' ? 'pending' : 'paid'
    );
    const references = [...new Set(
        bookings.map((booking) => booking.payment_reference).filter(Boolean),
    )];
    appendSummaryRow(
        bookingConfirmedSummary,
        'Payment',
        `${paymentStatus === 'paid' ? 'PAID VIA' : 'PAY AT VENUE'} ${paymentLabels[paymentMethod] || paymentMethod}`,
    );
    appendSummaryRow(
        bookingConfirmedSummary,
        'Payment reference',
        references.join(', ') || 'Pending reference',
    );
    appendSummaryRow(
        bookingConfirmedSummary,
        'Players',
        names.length ? names.join(', ') : 'Names not provided',
    );
    bookingFields.hidden = true;
    bookingResult.replaceChildren();
    bookingConfirmedState.hidden = false;
}

async function submitBooking(event) {
    event.preventDefault();
    if (selectedSlots.length === 0) {
        showBookingError(['Select at least one available court slot first.']);
        return;
    }
    if (!validateBookingForm()) {
        return;
    }

    const count = Number(participantCount.value);
    if (
        !Number.isInteger(count)
        || count < 1
        || (minimumSelectedCapacity && count > minimumSelectedCapacity)
    ) {
        participantCount.setCustomValidity(
            minimumSelectedCapacity
                ? `Enter a number from 1 to ${minimumSelectedCapacity}.`
                : 'Enter a whole number greater than zero.',
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

    const bookedSlots = selectedSlots.map((slot) => ({ ...slot }));
    const names = playerNames.map((name) => name.trim()).filter(Boolean);
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
                sport_id: bookedSlots[0].sportId,
                participant_count: count,
                participant_names: names.join(', '),
                contact_email: bookerEmail.value.trim(),
                contact_phone: bookerPhone.value.trim(),
                payment_method: selectedPaymentMethod(),
                slots: bookedSlots.map((slot) => ({
                    resource_id: slot.resourceId,
                    start_datetime: slot.startTime,
                    end_datetime: slot.endTime,
                })),
            }),
        });
        const payload = await response.json().catch(() => null);
        if (response.status === 201) {
            showConfirmedState(payload, bookedSlots, names);
            clearSelectedSlots();
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
    if (!datePill || datePill.dataset.date === availabilityDate.value) {
        return;
    }
    availabilityDate.value = datePill.dataset.date;
    updateActiveDatePill();
    clearSelectedSlots();
    searchAvailability();
});

availabilitySport.addEventListener('change', () => {
    clearSelectedSlots();
    searchAvailability();
});

availabilityResults.addEventListener('click', (event) => {
    const button = event.target.closest('.slot-button');
    if (button && availabilityResults.contains(button)) {
        toggleSlot(button);
    }
});

selectedSlotBar.addEventListener('click', (event) => {
    if (event.target.closest('#continue-booking')) {
        openBookingModal();
    }
});

participantCount.addEventListener('input', () => {
    participantCount.setCustomValidity('');
    updatePlayerNameInputs();
});

bookerEmail.addEventListener('input', () => {
    if (bookerEmail.classList.contains('is-invalid')) {
        validateContactInput(
            bookerEmail,
            document.getElementById('booker-email-error'),
            'Enter a valid contact email address.',
            availabilityHelpers.isValidEmail,
        );
    }
});
bookerPhone.addEventListener('input', () => {
    if (bookerPhone.classList.contains('is-invalid')) {
        validateContactInput(
            bookerPhone,
            document.getElementById('booker-phone-error'),
            'Enter a valid phone number with at least 7 digits.',
            availabilityHelpers.isValidPhone,
        );
    }
});
bookingForm.addEventListener('submit', submitBooking);
paymentMethodOptions.forEach((option) => {
    option.addEventListener('change', updatePaymentBreakdown);
});

bookingModalElement.addEventListener('show.bs.modal', () => {
    selectedSlotBar.hidden = true;
    selectedSlotBar.classList.add('d-none');
});
bookingModalElement.addEventListener('hidden.bs.modal', updateStickyBar);

document.getElementById('book-more-slots').addEventListener('click', () => {
    bookingConfirmedState.hidden = true;
    bookingFields.hidden = false;
    playerNames = [];
    bookingForm.reset();
    playerNamesGrid.replaceChildren();
    bookingModal.hide();
});

renderQuickDates();
updateActiveDatePill();
updatePlayerNameInputs();
searchAvailability();
