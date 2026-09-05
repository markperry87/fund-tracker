const test = require('node:test');
const assert = require('node:assert/strict');
const { subtractDays, computeChange, mergeLiveQuotes, normalizeMarketStatus } = require('../market-utils.js');

const history = [
    { date: '2026-09-02', close: 99 },
    { date: '2026-09-03', close: 100 }
];
const liveQuote = {
    date: '2026-09-04', as_of: '2026-09-04T19:59:00Z', price: 101,
    reference_price: 100, comparison_basis: 'previous_close', is_open: true, source: 'live'
};
const now = Date.parse('2026-09-04T19:59:30Z');
const normalize = (quote, at = now) => normalizeMarketStatus(
    quote, computeChange(history, 1), history.at(-1), history, at
);

test('period calculations are date-only across daylight saving and leap days', () => {
    for (const timezone of ['America/Vancouver', 'America/Toronto', 'UTC', 'Asia/Tokyo']) {
        const oldTimezone = process.env.TZ;
        process.env.TZ = timezone;
        try {
            assert.equal(subtractDays('2026-11-02', 7), '2026-10-26');
            assert.equal(subtractDays('2026-03-09', 7), '2026-03-02');
            assert.equal(subtractDays('2024-03-01', 1), '2024-02-29');
            assert.equal(computeChange([
                { date: '2026-10-23', close: 90 },
                { date: '2026-10-26', close: 100 },
                { date: '2026-11-02', close: 110 }
            ], 7).percent, 10);
        } finally {
            if (oldTimezone === undefined) delete process.env.TZ;
            else process.env.TZ = oldTimezone;
        }
    }
});

test('periods without enough history show no return instead of a shorter-period return', () => {
    assert.equal(computeChange(history, 365), null);
});

test('after-hours quotes never change completed history or its statistics', () => {
    const saved = { indices: { XUS: { history } }, status: {} };
    const before = structuredClone(saved);
    const merged = mergeLiveQuotes(saved, { quotes: { XUS: { ...liveQuote, is_open: false } } });
    assert.deepEqual(merged.indices.XUS.history, history);
    assert.deepEqual(saved, before);
    assert.equal(merged.status.XUS.price, 101);
    const completed = { indices: { XUS: { history: [...history, { date: '2026-09-04', close: 102 }] } } };
    const result = mergeLiveQuotes(completed, { quotes: { XUS: { ...liveQuote, is_open: false } } });
    assert.equal(result.indices.XUS.history.at(-1).close, 102);
    assert.equal(normalizeMarketStatus(result.status.XUS, { percent: 2, absolute: 2 }, result.indices.XUS.history.at(-1)).price, 102);
});

test('stale and saved intraday quotes expose their age and source', () => {
    assert.equal(normalize(liveQuote).label, 'Today');
    const stale = normalize(liveQuote, Date.parse('2026-09-05T19:59:30Z'));
    assert.equal(stale.label, 'Stale quote');
    assert.match(stale.asOfText, /2026/);
    assert.match(stale.notice, /stale/);
    assert.equal(normalize(liveQuote, now + 21 * 60 * 1000).label, 'Stale quote');
    const saved = normalize({ ...liveQuote, source: 'saved' });
    assert.equal(saved.label, 'Last quote');
    assert.match(saved.notice, /Saved quote.*unavailable/);
});

test('old Worker opening-price comparisons are recalculated from previous close', () => {
    const result = normalize({ ...liveQuote, comparison_basis: undefined, reference_price: 102, change_percent: -0.98 });
    assert.equal(result.percent, 1);
    assert.equal(result.absolute, 1);
});

test('failed or partial live responses preserve saved fallback data', () => {
    const saved = { indices: { XUS: { history } }, status: { XUS: liveQuote } };
    const result = mergeLiveQuotes(saved, { quotes: {}, errors: { XUS: 'Unavailable' } });
    assert.equal(result.status.XUS.source, 'saved');
    assert.match(normalize(result.status.XUS).notice, /unavailable/);
    assert.equal(normalize({ ...liveQuote, as_of: 'invalid' }).price, 100);
    assert.equal(normalize({ ...liveQuote, price: NaN }).price, 100);
});

test('Worker measures against previous close before and after market close', async () => {
    const { buildStatus } = await import('../live-quotes/worker.mjs');
    const start = Date.parse('2026-09-04T13:30:00Z') / 1000;
    const end = Date.parse('2026-09-04T20:00:00Z') / 1000;
    const result = {
        meta: { regularMarketPrice: 101, regularMarketTime: end - 60, chartPreviousClose: 100,
            exchangeTimezoneName: 'America/New_York', currentTradingPeriod: { regular: { start, end } } },
        timestamp: [start, end - 60],
        indicators: { quote: [{ open: [102, 101], close: [102, 101] }] }
    };
    for (const at of [(end - 30) * 1000, (end + 60) * 1000]) {
        const quote = buildStatus(result, at);
        assert.equal(quote.change_percent, 1);
        assert.equal(quote.reference_price, 100);
        assert.equal(quote.comparison_basis, 'previous_close');
        assert.equal(quote.date, '2026-09-04');
    }
});
