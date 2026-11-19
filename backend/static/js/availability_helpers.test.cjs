const test = require('node:test');
const assert = require('node:assert/strict');

require('./availability_helpers.js');

const {
    calculateSlotTotal,
    calculateFeeBreakdown,
    getSevenDayDates,
    getSlotKey,
    formatSlotTime,
    isValidEmail,
    isValidPhone,
    resizePlayerNames,
} = globalThis.CourtGridAvailabilityHelpers;

test('seven date pills stay anchored to the initial Manila date', () => {
    assert.deepEqual(
        getSevenDayDates('2026-11-18'),
        [
            '2026-11-18',
            '2026-11-19',
            '2026-11-20',
            '2026-11-21',
            '2026-11-22',
            '2026-11-23',
            '2026-11-24',
        ],
    );
});

test('slot identity includes both the resource and start time', () => {
    assert.equal(getSlotKey(4, '2026-11-19T17:00:00+08:00'), '4-2026-11-19T17:00:00+08:00');
    assert.notEqual(getSlotKey(4, 'slot-a'), getSlotKey(5, 'slot-a'));
});

test('slot times use 12-hour AM/PM formatting in Manila time', () => {
    assert.equal(formatSlotTime('2026-11-18T08:00:00+08:00'), '8:00 AM');
    assert.equal(formatSlotTime('2026-11-18T13:36:00+08:00'), '1:36 PM');
    assert.equal(formatSlotTime('2026-11-18T21:00:00+08:00'), '9:00 PM');
});

test('selected slots total their per-slot hourly rates', () => {
    assert.equal(
        calculateSlotTotal([{ sportId: 2 }, { sportId: 2 }, { sportId: 3 }], {
            2: '250.00',
            3: '200.00',
        }),
        700,
    );
});

test('commission breakdown rounds to cents and preserves the gross total', () => {
    assert.deepEqual(calculateFeeBreakdown(500), {
        gross: 500,
        platformFee: 25,
        ownerPayout: 475,
    });
});

test('player name values survive decreasing and increasing participant count', () => {
    const reduced = resizePlayerNames(['Alex', 'Sam', 'Jo'], ['Alex', 'Sam'], 2);
    const increased = resizePlayerNames(reduced, ['Alex', 'Sam'], 3);
    assert.deepEqual(increased, ['Alex', 'Sam', 'Jo']);
});

test('contact validators accept valid email and phone values', () => {
    assert.equal(isValidEmail(' player@example.com '), true);
    assert.equal(isValidEmail('not-an-email'), false);
    assert.equal(isValidPhone('+63 (917) 123-4567'), true);
    assert.equal(isValidPhone('123'), false);
});
