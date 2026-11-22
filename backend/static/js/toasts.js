(() => {
    const stack = document.getElementById('cg-toast-stack');
    const attach = (toast) => {
        let remaining = 4000;
        let started;
        let timer;
        let hovering = false;
        let focused = false;
        const dismiss = () => {
            clearTimeout(timer);
            toast.classList.add('is-dismissing');
            window.setTimeout(() => toast.remove(), 250);
        };
        const pause = () => {
            if (timer) {
                clearTimeout(timer);
                timer = null;
                remaining = Math.max(0, remaining - (Date.now() - started));
            }
        };
        const resume = () => {
            if (hovering || focused || timer) return;
            started = Date.now();
            timer = window.setTimeout(dismiss, remaining);
        };
        toast.addEventListener('mouseenter', () => { hovering = true; pause(); });
        toast.addEventListener('mouseleave', () => { hovering = false; resume(); });
        toast.addEventListener('focusin', () => { focused = true; pause(); });
        toast.addEventListener('focusout', (event) => {
            if (!toast.contains(event.relatedTarget)) { focused = false; resume(); }
        });
        toast.querySelector('button').addEventListener('click', dismiss);
        resume();
    };
    window.CourtGridToast = {
        show(message, level = 'info') {
            const toast = document.createElement('div');
            toast.className = `cg-toast cg-toast-${['success', 'warning', 'error', 'info'].includes(level) ? level : 'info'}`;
            toast.setAttribute('role', 'status');
            const text = document.createElement('span');
            text.textContent = message;
            const close = document.createElement('button');
            close.type = 'button';
            close.setAttribute('aria-label', 'Dismiss notification');
            close.textContent = '×';
            toast.append(text, close);
            stack.append(toast);
            attach(toast);
        },
    };
    stack.querySelectorAll('.cg-toast').forEach(attach);
})();
