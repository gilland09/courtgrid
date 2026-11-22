(function attachAvailabilityHelpers(global) {
    function getSevenDayDates(baseDate) {
        const [year, month, day] = baseDate.split('-').map(Number);
        const firstDate = new Date(Date.UTC(year, month - 1, day));
        return Array.from({ length: 7 }, (_, offset) => {
            const date = new Date(firstDate);
            date.setUTCDate(firstDate.getUTCDate() + offset);
            return date.toISOString().slice(0, 10);
        });
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
        getSevenDayDates,
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
