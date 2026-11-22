(function attachAvailabilityHelpers(global) {
    function addDays(date, days) {
        const value = new Date(`${date}T00:00:00Z`);
        value.setUTCDate(value.getUTCDate() + days);
        return value.toISOString().slice(0, 10);
    }

    function rangeDates(start, end = start) {
        const count = (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000 + 1;
        return Array.from({ length: count }, (_, index) => addDays(start, index));
    }

    function selectCalendarDate(state, date, maxDays) {
        if (!state.startDate || state.endDate || state.startDate === date) {
            return { startDate: date, endDate: null, exceeded: false };
        }
        const [startDate, endDate] = [state.startDate, date].sort();
        if (rangeDates(startDate, endDate).length > maxDays) {
            return { startDate: date, endDate: null, exceeded: true };
        }
        return { startDate, endDate, exceeded: false };
    }

    function clearCalendar(today) {
        return { startDate: today, endDate: null, exceeded: false };
    }

    function selectCourt(selected, id, checked, mode) {
        if (mode === 'player') return checked ? [id] : [];
        return checked ? [...new Set([...selected, id])] : selected.filter((item) => item !== id);
    }

    function getSlotKey(resourceId, startTime) {
        return `${resourceId}-${startTime}`;
    }

    function getAvailablePaymentMethods(configuredMethods) {
        return configuredMethods.filter((method) => method.is_active !== false);
    }

    function formatSlotTime(value) {
        return new Intl.DateTimeFormat('en-US', {
            timeZone: 'Asia/Manila',
            hour: 'numeric',
            minute: '2-digit',
            hour12: true,
        }).format(new Date(value));
    }

    function calculateSlotTotal(slots, rates, resources = []) {
        return slots.reduce(
            (total, slot) => {
                const resourceId = Number(slot.resourceId ?? slot.resource_id);
                const resource = resources.find((item) => item.id === resourceId);
                const resourceRate = resource?.hourly_rate;
                const rate = resourceRate !== null && resourceRate !== undefined
                    ? resourceRate
                    : rates[String(slot.sportId ?? slot.sport_id)];
                return total + Number(rate || 0);
            },
            0,
        );
    }

    function calculateFeeBreakdown(gross, feeRate = 0.05) {
        const total = Number(gross);
        const platformFee = Math.round((total * feeRate + Number.EPSILON) * 100) / 100;
        return {
            gross: total,
            platformFee,
            ownerPayout: Math.round((total - platformFee + Number.EPSILON) * 100) / 100,
        };
    }

    function resizePlayerNames(names, visibleValues, count) {
        const resizedNames = names.slice();
        visibleValues.forEach((value, index) => {
            resizedNames[index] = value;
        });
        while (resizedNames.length < count) {
            resizedNames.push('');
        }
        return resizedNames;
    }

    function isValidEmail(value) {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
    }

    function isValidPhone(value) {
        const phone = value.trim();
        return /^\+?[0-9][0-9\s().-]{5,30}$/.test(phone)
            && (phone.match(/\d/g) || []).length >= 7;
    }

    global.CourtGridAvailabilityHelpers = {
        addDays,
        rangeDates,
        selectCalendarDate,
        clearCalendar,
        selectCourt,
        getSlotKey,
        getAvailablePaymentMethods,
        formatSlotTime,
        calculateSlotTotal,
        calculateFeeBreakdown,
        resizePlayerNames,
        isValidEmail,
        isValidPhone,
    };
}(globalThis));
