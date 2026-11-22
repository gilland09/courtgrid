const facility = document.getElementById('facility-detail');
const dateInput = document.getElementById('availability-date');
const sportInput = document.getElementById('availability-sport');
const results = document.getElementById('availability-results');
const datePills = document.getElementById('quick-date-pills');
const flow = document.getElementById('booking-flow');
const organizerForm = document.getElementById('organizer-form');
const cart = document.getElementById('booking-cart');
const continueButton = document.getElementById('continue-booking');
const bookingModal = document.getElementById('booking-modal');
const confirmationModal = document.getElementById('booking-confirmation-modal');
const bookingForm = document.getElementById('booking-confirm-form');
const receiptInput = document.getElementById('payment-receipt');
const policyInput = document.getElementById('policy-accepted');
const submitButton = document.getElementById('confirm-booking');
const participantCount = document.getElementById('participant-count');
const resources = JSON.parse(document.getElementById('facility-resources-data').textContent);
const rates = JSON.parse(document.getElementById('sport-rates-data').textContent);
const helpers = window.CourtGridAvailabilityHelpers;
const methods = helpers.getAvailablePaymentMethods(
    JSON.parse(document.getElementById('payment-methods-data').textContent),
);
const mode = new URLSearchParams(location.search).get('mode');
const csrfToken = document.querySelector('#booking-csrf-form [name=csrfmiddlewaretoken]').value;

let slots = [];
let slotButtons = new Map();
let pendingSwitchSlots = [];
let searchSequence = 0;
let submitting = false;
let unknownOutcome = false;
let receiptPreviewUrl = null;
let previousSport = sportInput.value;

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

function formatCurrency(value) {
    return new Intl.NumberFormat('en-PH', { style: 'currency', currency: 'PHP' }).format(value);
}

function formatDate(value) {
    return new Intl.DateTimeFormat('en-PH', {
        timeZone: 'Asia/Manila', dateStyle: 'medium',
    }).format(new Date(value));
}

function slotKey(slot) {
    return helpers.getSlotKey(Number(slot.resourceId), new Date(slot.startTime).toISOString());
}

function normalizeSlot(slot) {
    const item = {
        resourceId: Number(slot.resource_id),
        sportId: Number(slot.sport_id),
        startTime: slot.start_datetime,
        endTime: slot.end_datetime,
    };
    item.key = slotKey(item);
    return item;
}

function resourceFor(slot) {
    return resources.find((resource) => resource.id === slot.resourceId);
}

function rateFor(slot) {
    const resource = resourceFor(slot);
    const rate = resource?.hourly_rate ?? rates[String(slot.sportId)];
    return rate === null || rate === undefined || rate === '' ? null : Number(rate);
}

function slotDescription(slot) {
    return `${resourceFor(slot)?.name || 'Court'} · ${formatDate(slot.startTime)} · `
        + `${helpers.formatSlotTime(slot.startTime)}–${helpers.formatSlotTime(slot.endTime)}`;
}

function total() {
    return helpers.calculateSlotTotal(slots, rates, resources);
}

function setMessage(element, message, type = 'warning') {
    element.className = `alert alert-${type}`;
    element.setAttribute('role', type === 'danger' ? 'alert' : 'status');
    element.textContent = message;
}

function updateSelectedButtons() {
    const keys = new Set(slots.map((slot) => slot.key));
    slotButtons.forEach((button, key) => {
        const selected = keys.has(key);
        button.classList.toggle('is-selected', selected);
        button.setAttribute('aria-pressed', String(selected));
    });
}

function renderSlotList(container) {
    container.replaceChildren();
    if (!slots.length) {
        const empty = document.createElement('p');
        empty.className = 'text-body-secondary mb-0';
        empty.textContent = 'No slots selected yet.';
        container.append(empty);
        return;
    }
    slots.forEach((slot) => {
        const row = document.createElement('div');
        row.className = 'cg-cart-row';
        const details = document.createElement('span');
        details.textContent = slotDescription(slot);
        const price = document.createElement('strong');
        price.textContent = formatCurrency(rateFor(slot));
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'cg-cart-remove';
        remove.dataset.removeSlot = slot.key;
        remove.textContent = '×';
        remove.setAttribute('aria-label', `Remove ${slotDescription(slot)}`);
        row.append(details, price, remove);
        container.append(row);
    });
}

function selectedMethod() {
    const selected = document.querySelector('[name="payment_method_used"]:checked');
    return methods.find((method) => String(method.id) === selected?.value);
}

function receiptIsValid() {
    const file = receiptInput.files[0];
    return Boolean(file && /\.(jpg|jpeg|png|pdf)$/i.test(file.name)
        && file.size > 0 && file.size <= 5 * 1024 * 1024);
}

function updateCheckoutState() {
    const method = selectedMethod();
    const validReceipt = receiptIsValid();
    let hint = 'Ready to submit';
    if (!slots.length) hint = 'Select at least one slot';
    else if (!method) hint = 'Select a payment method';
    else if (!validReceipt) hint = 'Attach a receipt to continue';
    else if (!policyInput.checked) hint = 'Accept the policy to continue';
    else if (facility.dataset.authenticated !== 'true') hint = 'Sign in to continue';
    if (unknownOutcome) hint = 'Check My Bookings before trying again';
    document.getElementById('checkout-hint').textContent = hint;
    submitButton.disabled = submitting || unknownOutcome || !slots.length || !method || !validReceipt
        || !policyInput.checked || facility.dataset.authenticated !== 'true';
    document.getElementById('footer-total').textContent = formatCurrency(total());
    document.getElementById('method-amount').textContent = formatCurrency(total());
}

function updateCart() {
    renderSlotList(cart);
    renderSlotList(document.getElementById('booking-summary'));
    document.getElementById('cart-total').textContent = formatCurrency(total());
    document.getElementById('checkout-total').textContent = `Total due ${formatCurrency(total())}`;
    document.getElementById('checkout-bookings').textContent = `${slots.length} bookings`;
    document.getElementById('checkout-hours').textContent = `${slots.length} hours`;
    continueButton.disabled = !slots.length || !methods.length || facility.dataset.authenticated !== 'true';
    const capacities = slots.map((slot) => resourceFor(slot)?.capacity)
        .filter((capacity) => Number.isInteger(capacity) && capacity > 0);
    const capacity = capacities.length ? Math.min(...capacities) : null;
    if (capacity) participantCount.max = capacity;
    else participantCount.removeAttribute('max');
    document.getElementById('participant-capacity-help').textContent = capacity
        ? `Maximum ${capacity} players per selected court.`
        : 'Enter at least one player per court.';
    updateSelectedButtons();
    updateCheckoutState();
}

function addSlots(items) {
    const unique = items.filter((item) => !slots.some((existing) => existing.key === item.key));
    if (!unique.length) return { added: 0, limited: 0, unrated: 0 };
    if (mode === 'player' && slots.length && unique.some((item) => item.resourceId !== slots[0].resourceId)) {
        pendingSwitchSlots = unique;
        document.getElementById('court-switch-notice').hidden = false;
        return { added: 0, limited: 0, unrated: 0 };
    }
    pendingSwitchSlots = [];
    document.getElementById('court-switch-notice').hidden = true;
    let added = 0;
    let limited = 0;
    let unrated = 0;
    unique.forEach((item) => {
        if (rateFor(item) === null || !Number.isFinite(rateFor(item))) {
            unrated += 1;
        } else if (slots.length >= 20) {
            limited += 1;
        } else {
            slots.push(item);
            added += 1;
        }
    });
    updateCart();
    return { added, limited, unrated };
}

function renderDates() {
    datePills.replaceChildren();
    helpers.getSevenDayDates(dateInput.min).forEach((date, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'quick-date-pill';
        button.dataset.date = date;
        const label = document.createElement('span');
        label.className = 'quick-date-day';
        label.textContent = index === 0 ? 'Today' : index === 1 ? 'Tomorrow' : formatDate(`${date}T12:00:00+08:00`);
        button.append(label);
        datePills.append(button);
    });
    updateDatePills();
}

function updateDatePills() {
    datePills.querySelectorAll('[data-date]').forEach((button) => {
        const selected = button.dataset.date === dateInput.value;
        button.classList.toggle('active', selected);
        button.setAttribute('aria-pressed', String(selected));
    });
}

function renderAvailability(schedule) {
    slotButtons = new Map();
    const grouped = new Map();
    schedule.forEach((item) => {
        if (!grouped.has(item.resource_id)) grouped.set(item.resource_id, []);
        grouped.get(item.resource_id).push(item);
    });
    const grid = document.createElement('div');
    grid.className = 'row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3';
    grouped.forEach((items) => {
        const column = document.createElement('div');
        column.className = 'col';
        const card = document.createElement('section');
        card.className = 'court-schedule-card h-100';
        const title = document.createElement('h3');
        title.className = 'h6';
        title.textContent = resourceFor(normalizeSlot(items[0]))?.name || 'Court';
        const container = document.createElement('div');
        container.className = 'court-time-slots';
        items.forEach((item) => {
            const slot = normalizeSlot(item);
            const state = item.availability || 'available';
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `slot-button book-slot-btn is-${state}`;
            button.disabled = state !== 'available';
            button.textContent = `${helpers.formatSlotTime(slot.startTime)} – ${helpers.formatSlotTime(slot.endTime)}`
                + (state === 'available' ? '' : ` · ${state}`);
            if (item.reason) button.title = item.reason;
            button.addEventListener('click', () => {
                if (slots.some((selected) => selected.key === slot.key)) {
                    slots = slots.filter((selected) => selected.key !== slot.key);
                    updateCart();
                } else {
                    const outcome = addSlots([slot]);
                    if (outcome.limited || outcome.unrated) {
                        setMessage(document.getElementById('range-result'), outcome.unrated
                            ? 'No rate is configured for this court and sport.'
                            : 'A checkout can contain at most 20 slots.');
                    }
                }
            });
            if (!button.disabled) slotButtons.set(slot.key, button);
            container.append(button);
        });
        card.append(title, container);
        column.append(card);
        grid.append(column);
    });
    results.replaceChildren(grid);
    updateSelectedButtons();
}

async function searchAvailability() {
    if (!dateInput.value || !sportInput.value) {
        setMessage(results, 'Choose a date and sport to view available courts.');
        return;
    }
    const requestId = ++searchSequence;
    results.textContent = 'Checking court availability…';
    const query = new URLSearchParams({
        mode: 'parallel', facility: facility.dataset.facilityId,
        sport: sportInput.value, date: dateInput.value,
    });
    try {
        const response = await fetch(`/api/availability/search?${query}`, { credentials: 'same-origin' });
        const payload = await response.json();
        if (!response.ok) throw new Error(errorText(payload));
        if (requestId !== searchSequence) return;
        const schedule = payload.slots || payload.results;
        if (!Array.isArray(schedule)) throw new Error('Invalid availability response.');
        if (!schedule.length) setMessage(results, 'No courts are available for this date. Try another day.');
        else renderAvailability(schedule);
    } catch (error) {
        if (requestId === searchSequence) setMessage(results, `Availability could not be loaded: ${error.message}`, 'danger');
    }
}

function errorText(value) {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.map(errorText).join(' ');
    if (value && typeof value === 'object') {
        return Object.entries(value).map(([field, item]) => (
            field === 'detail' ? errorText(item) : `${field.replaceAll('_', ' ')}: ${errorText(item)}`
        )).join(' ');
    }
    return 'Please try again.';
}

async function addDateRange(event) {
    event.preventDefault();
    const rangeForm = event.currentTarget;
    const message = document.getElementById('range-result');
    const startDate = document.getElementById('range-start').value;
    const endDate = document.getElementById('range-end').value;
    const startTime = document.getElementById('range-start-time').value;
    const endTime = document.getElementById('range-end-time').value;
    const courtIds = Array.from(document.getElementById('range-courts').selectedOptions, (item) => Number(item.value));
    const days = (Date.parse(`${endDate}T00:00:00Z`) - Date.parse(`${startDate}T00:00:00Z`)) / 86400000 + 1;
    if (!Number.isInteger(days) || days < 1 || days > 14) {
        setMessage(message, 'Choose a date range of at most 14 days.');
        return;
    }
    if (!courtIds.length || (mode === 'player' && courtIds.length !== 1)) {
        setMessage(message, mode === 'player' ? 'Players can select only one court.' : 'Select at least one court.');
        return;
    }
    if (!startTime || !endTime || startTime >= endTime) {
        setMessage(message, 'Choose a valid start and end time.');
        return;
    }
    const sport = sportInput.value;
    const button = rangeForm.querySelector('button[type=submit]');
    button.disabled = true;
    setMessage(message, 'Checking availability…', 'info');
    try {
        const response = await fetch('/api/availability/range', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken, Accept: 'application/json' },
            body: JSON.stringify({
                start_date: startDate, end_date: endDate, court_ids: courtIds,
                booking_type: mode, sport, start_time: startTime, end_time: endTime,
            }),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(errorText(payload));
        if (sport !== sportInput.value) throw new Error('Sport changed while searching. Please try again.');
        if (!Array.isArray(payload.available_slots) || !Array.isArray(payload.skipped_slots)) {
            throw new Error('Invalid availability response.');
        }
        const outcome = addSlots(payload.available_slots.map(normalizeSlot));
        const skipped = payload.skipped_slots.map((item) => `${slotDescription(normalizeSlot(item))} (${item.availability})`);
        let text = `Added ${outcome.added} slot(s). ${skipped.length} unavailable slot(s) skipped.`;
        if (skipped.length) text += ` ${skipped.join('; ')}.`;
        if (outcome.limited) text += ` ${outcome.limited} slot(s) omitted because the cart limit is 20.`;
        if (outcome.unrated) text += ` ${outcome.unrated} slot(s) omitted because no rate is configured.`;
        if (pendingSwitchSlots.length) text += ' Switch courts above to replace the current cart.';
        setMessage(message, text, skipped.length || outcome.limited || outcome.unrated || pendingSwitchSlots.length ? 'warning' : 'success');
    } catch (error) {
        setMessage(message, `Date range could not be added: ${error.message}`, 'danger');
    } finally {
        button.disabled = false;
    }
}

function updateMethodDetails() {
    const method = selectedMethod();
    const panel = document.getElementById('payment-details');
    panel.hidden = !method;
    if (method) {
        document.getElementById('method-label').textContent = method.label;
        document.getElementById('method-account-name').textContent = method.account_name || 'Contact the venue';
        document.getElementById('method-account-number').textContent = method.account_number || 'Contact the venue';
        document.getElementById('method-instructions').textContent = method.instructions || '';
        const link = document.getElementById('method-qr-link');
        link.hidden = !method.qr_url;
        if (method.qr_url) {
            link.href = method.qr_url;
            document.getElementById('method-qr').src = method.qr_url;
        }
    }
    updateCheckoutState();
}

function updateReceipt() {
    const file = receiptInput.files[0];
    const valid = receiptIsValid();
    document.getElementById('receipt-filename').textContent = file
        ? `${file.name}${valid && /\.pdf$/i.test(file.name) ? ' · PDF' : ''}` : 'No file selected';
    document.getElementById('receipt-error').textContent = file && !valid
        ? 'Choose a JPG, PNG, or PDF file no larger than 5 MB.' : '';
    const preview = document.getElementById('receipt-preview');
    if (receiptPreviewUrl) URL.revokeObjectURL(receiptPreviewUrl);
    receiptPreviewUrl = null;
    preview.hidden = !(valid && /\.(jpg|jpeg|png)$/i.test(file.name));
    if (!preview.hidden) {
        receiptPreviewUrl = URL.createObjectURL(file);
        preview.src = receiptPreviewUrl;
    } else {
        preview.removeAttribute('src');
    }
    updateCheckoutState();
}

function openCheckout() {
    if (!slots.length || !methods.length) return;
    if (mode === 'organizer' && !organizerForm.reportValidity()) return;
    document.getElementById('checkout-customer-name').textContent = `Customer: ${facility.dataset.customerName}`;
    document.getElementById('checkout-organizer-details').textContent = mode === 'organizer'
        ? `${document.getElementById('organization-name').value.trim()} · ${document.getElementById('event-name').value.trim()} · ${document.getElementById('expected-participants').value} expected participants`
        : 'Player booking';
    document.getElementById('booking-result').replaceChildren();
    updateCart();
    updateMethodDetails();
    openModal(bookingModal);
    document.getElementById('booker-email').focus();
}

async function submitBooking(event) {
    event.preventDefault();
    updateCheckoutState();
    if (submitButton.disabled || !bookingForm.reportValidity()) return;
    if (mode === 'organizer' && !organizerForm.reportValidity()) return;
    if (!helpers.isValidEmail(document.getElementById('booker-email').value)
        || !helpers.isValidPhone(document.getElementById('booker-phone').value)) {
        setMessage(document.getElementById('booking-result'), 'Enter a valid contact email and mobile number.', 'danger');
        return;
    }
    const data = new FormData();
    data.set('booking_type', mode);
    data.set('sport_id', sportInput.value);
    data.set('participant_count', participantCount.value);
    data.set('participant_names', document.getElementById('participant-names').value.trim());
    data.set('contact_email', document.getElementById('booker-email').value.trim());
    data.set('contact_phone', document.getElementById('booker-phone').value.trim());
    data.set('payment_method_used', String(selectedMethod().id));
    data.set('policy_accepted', 'true');
    data.set('payment_receipt', receiptInput.files[0]);
    data.set('expected_total', total().toFixed(2));
    data.set('slots', JSON.stringify(slots.map((slot) => ({
        resource_id: slot.resourceId, start_datetime: slot.startTime, end_datetime: slot.endTime,
    }))));
    if (mode === 'organizer') {
        data.set('organization_name', document.getElementById('organization-name').value.trim());
        data.set('event_name', document.getElementById('event-name').value.trim());
        data.set('expected_participants', document.getElementById('expected-participants').value);
    }
    submitting = true;
    bookingModal.dataset.modalBusy = 'true';
    bookingModal.querySelector('.cg-checkout-body').inert = true;
    bookingModal.querySelector('[data-modal-close]').disabled = true;
    updateCheckoutState();
    let responseReceived = false;
    let successfulResponse = false;
    try {
        const response = await fetch('/api/bookings/', {
            method: 'POST', credentials: 'same-origin',
            headers: { Accept: 'application/json', 'X-CSRFToken': csrfToken }, body: data,
        });
        responseReceived = true;
        successfulResponse = response.ok || response.status >= 500;
        const payload = await response.json();
        if (!response.ok) throw new Error(errorText(payload));
        if (!Array.isArray(payload.results) || !payload.results.length) throw new Error('Invalid booking response.');
        const summary = document.getElementById('booking-confirmed-summary');
        summary.replaceChildren();
        payload.results.forEach((booking) => {
            const row = document.createElement('p');
            row.textContent = `${booking.payment_reference} · ${booking.resource_name} · ${formatDate(booking.start_datetime)} · ${helpers.formatSlotTime(booking.start_datetime)}–${helpers.formatSlotTime(booking.end_datetime)}`;
            summary.append(row);
        });
        slots = [];
        receiptInput.value = '';
        policyInput.checked = false;
        updateReceipt();
        updateCart();
        closeModal(bookingModal);
        openModal(confirmationModal);
        searchAvailability();
    } catch (error) {
        unknownOutcome = !responseReceived || successfulResponse;
        const message = unknownOutcome
            ? 'The booking result could not be confirmed. Check My Bookings before trying again.'
            : error.message;
        setMessage(document.getElementById('booking-result'), message, 'danger');
    } finally {
        submitting = false;
        delete bookingModal.dataset.modalBusy;
        bookingModal.querySelector('.cg-checkout-body').inert = false;
        bookingModal.querySelector('[data-modal-close]').disabled = false;
        updateCheckoutState();
    }
}

if (mode !== 'player' && mode !== 'organizer') {
    document.getElementById('mode-selector').hidden = false;
} else if (mode === 'organizer') {
    organizerForm.hidden = false;
    document.getElementById('progress-one').textContent = '1 Club details';
    document.getElementById('progress-two').textContent = '2 Date & courts';
    document.getElementById('booking-mode-note').textContent = 'Club / Organizer: select slots across multiple courts.';
} else {
    flow.hidden = false;
    document.getElementById('switch-organizer').hidden = false;
    document.getElementById('booking-mode-note').textContent = 'Player booking: 1 court per reservation. Need multiple courts? Switch to Club / Organizer.';
}

organizerForm.addEventListener('submit', (event) => {
    event.preventDefault();
    ['organization-name', 'event-name'].forEach((id) => {
        const input = document.getElementById(id);
        input.setCustomValidity(input.value.trim() ? '' : 'Please enter a value.');
    });
    if (!organizerForm.reportValidity()) return;
    flow.hidden = false;
    flow.scrollIntoView({ behavior: 'smooth', block: 'start' });
});
['organization-name', 'event-name'].forEach((id) => {
    document.getElementById(id).addEventListener('input', (event) => event.target.setCustomValidity(''));
});
document.getElementById('range-form').addEventListener('submit', addDateRange);
datePills.addEventListener('click', (event) => {
    const button = event.target.closest('[data-date]');
    if (!button) return;
    dateInput.value = button.dataset.date;
    updateDatePills();
    searchAvailability();
});
dateInput.addEventListener('change', () => { updateDatePills(); searchAvailability(); });
sportInput.addEventListener('change', () => {
    if (slots.length && !window.confirm('Changing sports clears your booking cart. Continue?')) {
        sportInput.value = previousSport;
        return;
    }
    previousSport = sportInput.value;
    slots = [];
    pendingSwitchSlots = [];
    document.getElementById('court-switch-notice').hidden = true;
    updateCart();
    searchAvailability();
});
document.getElementById('replace-court').addEventListener('click', () => {
    slots = [];
    const replacement = pendingSwitchSlots;
    pendingSwitchSlots = [];
    document.getElementById('court-switch-notice').hidden = true;
    addSlots(replacement);
});
document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-slot]');
    if (!button || submitting) return;
    slots = slots.filter((slot) => slot.key !== button.dataset.removeSlot);
    updateCart();
});
continueButton.addEventListener('click', openCheckout);
bookingForm.addEventListener('submit', submitBooking);
bookingForm.querySelectorAll('[name="payment_method_used"]').forEach((input) => input.addEventListener('change', updateMethodDetails));
receiptInput.addEventListener('change', updateReceipt);
const receiptDropzone = receiptInput.closest('.cg-receipt-dropzone');
['dragenter', 'dragover'].forEach((eventName) => {
    receiptDropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        receiptDropzone.classList.add('is-dragging');
    });
});
['dragleave', 'drop'].forEach((eventName) => {
    receiptDropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        receiptDropzone.classList.remove('is-dragging');
        if (eventName === 'drop' && event.dataTransfer.files.length) {
            receiptInput.files = event.dataTransfer.files;
            updateReceipt();
        }
    });
});
policyInput.addEventListener('change', updateCheckoutState);

renderDates();
updateCart();
if (mode === 'player' || mode === 'organizer') searchAvailability();
