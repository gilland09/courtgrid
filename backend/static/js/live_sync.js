(() => {
    let actionBusy = false;
    const controllers = new Set();
    const blocked = () => document.hidden || actionBusy || Boolean(document.querySelector('.cg-modal-overlay.is-open'));

    function start({ node, interval = 3000, canUpdate = () => !blocked(), apply, query = () => ({}) }) {
        let version = node.dataset.liveSyncVersion || '';
        let inFlight = false;
        let stopped = false;
        let timer;
        let failures = 0;
        let revision = 0;
        let waiting = false;
        const schedule = (delay) => {
            clearTimeout(timer);
            if (!stopped) timer = window.setTimeout(poll, delay);
        };
        async function poll() {
            if (stopped || inFlight) return;
            if (!canUpdate()) {
                waiting = true;
                schedule(interval);
                return;
            }
            inFlight = true;
            const requestedRevision = revision;
            try {
                const url = new URL(node.dataset.liveSyncUrl, window.location.href);
                url.searchParams.set('version', version);
                Object.entries(query()).forEach(([key, value]) => url.searchParams.set(key, value));
                const response = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' }, cache: 'no-store' });
                if (response.status === 401 || response.status === 403 || response.redirected) {
                    stopped = true;
                    return;
                }
                if (!response.ok) throw new Error(`Live sync failed (HTTP ${response.status}).`);
                const payload = await response.json();
                if (requestedRevision !== revision || !canUpdate()) {
                    waiting = true;
                    return;
                }
                const changed = payload.changed === undefined ? payload.version !== version : payload.changed;
                if (changed) {
                    await apply(payload);
                    if (!canUpdate()) {
                        waiting = true;
                        return;
                    }
                }
                version = payload.version;
                node.dataset.liveSyncVersion = version;
                failures = 0;
                waiting = false;
            } catch (error) {
                if (!failures) console.warn('Live sync temporarily unavailable.', error);
                failures += 1;
            } finally {
                inFlight = false;
                schedule(failures ? Math.min(interval * (2 ** failures), 60000) : interval);
            }
        }
        const controller = {
            check() { if (!stopped && !inFlight) schedule(0); },
            setVersion(value) { if (value) { revision += 1; version = value; node.dataset.liveSyncVersion = value; } },
        };
        controllers.add(controller);
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) controller.check();
        });
        let wasBlocked = !canUpdate();
        const observer = new MutationObserver(() => {
            const isBlocked = !canUpdate();
            if ((waiting || wasBlocked) && !isBlocked) controller.check();
            wasBlocked = isBlocked;
        });
        observer.observe(document.body, { attributes: true, attributeFilter: ['class'], subtree: true });
        schedule(interval);
        return controller;
    }

    window.CourtGridLive = {
        start,
        setBusy(value) {
            actionBusy = value;
            if (!value) controllers.forEach((controller) => controller.check());
        },
        blocked,
    };

    document.addEventListener('DOMContentLoaded', () => {
        const panel = document.querySelector('[data-booking-panel][data-live-sync-url]');
        if (!panel) return;
        const controller = start({
            node: panel,
            query: () => ({ settlement_status: new URLSearchParams(location.search).get('settlement_status') || 'all' }),
            apply(payload) {
                const scroll = panel.querySelector('.booking-table-scroll');
                const pageY = window.scrollY;
                const tableY = scroll.scrollTop;
                const tableX = scroll.scrollLeft;
                panel.querySelector('tbody').innerHTML = payload.rows_html;
                const closures = document.querySelector('[data-live-closures]');
                if (closures) closures.innerHTML = payload.closures_html;
                const today = document.querySelector('[data-live-today]');
                const ledger = document.querySelector('[data-live-ledger]');
                if (today) today.innerHTML = payload.today_html;
                if (ledger) ledger.innerHTML = payload.ledger_html;
                const venues = document.querySelector('[data-live-venues]');
                if (venues) venues.textContent = `${payload.venues} venues · ${payload.courts} courts`;
                Object.entries(payload.kpis).forEach(([key, value]) => {
                    const target = document.querySelector(`[data-live-kpi="${key}"]`);
                    if (target) target.textContent = `₱${value}`;
                });
                const settled = document.querySelector('[data-live-settled]');
                if (settled) settled.textContent = `Settled: ₱${payload.kpis.platform_fee_settled}`;
                const badge = panel.querySelector('[data-pending-verification-filter] .badge');
                if (badge) badge.textContent = payload.summary.pending;
                panel.applyBookingFilters();
                scroll.scrollTop = tableY;
                scroll.scrollLeft = tableX;
                window.scrollTo(window.scrollX, pageY);
                window.CourtGridToast.show('Bookings were updated live.', 'info');
            },
        });
        panel.liveSync = controller;
    });
})();
