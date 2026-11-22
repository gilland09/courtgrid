document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!form.matches('[data-booking-action], [data-reject-form], [data-cancel-form]')) return;
    event.preventDefault();
    const button = event.submitter || form.querySelector('[type="submit"]');
    if (!button || button.disabled) return;
    const label = button.textContent;
    const overlay = form.closest('.cg-modal-overlay');
    const panel = document.querySelector('[data-booking-panel]');
    const scroll = panel?.querySelector('.booking-table-scroll');
    const pageY = window.scrollY;
    const tableY = scroll?.scrollTop;
    const tableX = scroll?.scrollLeft;
    button.disabled = true;
    button.textContent = 'Working…';
    if (overlay) overlay.dataset.modalBusy = 'true';
    try {
        const response = await fetch(form.action, {
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
            body: new FormData(form),
            credentials: 'same-origin',
        });
        let payload;
        try {
            payload = await response.json();
        } catch (error) {
            throw new Error(`The booking action returned an unexpected response (HTTP ${response.status}).`);
        }
        if (!response.ok || !payload.success) throw new Error(payload.error || 'The booking action failed.');
        if (overlay) {
            delete overlay.dataset.modalBusy;
            overlay.querySelector('[data-modal-close]').click();
        }
        payload.messages.forEach((notice) => window.CourtGridToast.show(notice.message, notice.level));
        const page = await fetch(window.location.href, { credentials: 'same-origin' });
        if (!page.ok) throw new Error('The action succeeded, but the dashboard could not be refreshed. Reload the page.');
        const updated = new DOMParser().parseFromString(await page.text(), 'text/html');
        const newPanel = updated.querySelector('[data-booking-panel]');
        const finance = document.querySelector('.finance-kpis');
        const newFinance = updated.querySelector('.finance-kpis');
        if (!panel || !scroll || !newPanel || !finance || !newFinance) {
            throw new Error('The action succeeded, but the dashboard could not be refreshed. Reload the page.');
        }
        panel.querySelector('tbody').replaceWith(newPanel.querySelector('tbody'));
        const badge = panel.querySelector('[data-pending-verification-filter] .badge');
        const newBadge = newPanel.querySelector('[data-pending-verification-filter] .badge');
        if (badge && newBadge) badge.textContent = newBadge.textContent;
        finance.replaceWith(newFinance);
        ['today-bookings-heading', 'owner-commission-ledger-heading'].forEach((id) => {
            const current = document.getElementById(id)?.closest('section');
            const replacement = updated.getElementById(id)?.closest('section');
            if (current && replacement) current.replaceWith(replacement);
        });
        panel.applyBookingFilters();
        scroll.scrollTop = tableY;
        scroll.scrollLeft = tableX;
        window.scrollTo(window.scrollX, pageY);
    } catch (error) {
        console.error('Booking action failed.', error);
        window.CourtGridToast.show(error.message || 'The booking action could not be completed.', 'error');
    } finally {
        if (overlay) delete overlay.dataset.modalBusy;
        button.disabled = false;
        button.textContent = label;
    }
});
