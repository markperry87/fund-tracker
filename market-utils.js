/* Shared by the browser and the market regression tests. */
(function(root) {
    function subtractDays(date, days) {
        const result = new Date(`${date}T00:00:00Z`);
        result.setUTCDate(result.getUTCDate() - days);
        return result.toISOString().slice(0, 10);
    }

    function computeChange(history, days) {
        if (history.length < 2) return null;
        const latest = history[history.length - 1];
        const target = subtractDays(latest.date, days);
        const reference = days === 1
            ? history[history.length - 2]
            : [...history].reverse().find(entry => entry.date <= target);
        if (!reference || reference.close <= 0) return null;
        const absolute = latest.close - reference.close;
        return { percent: absolute / reference.close * 100, absolute };
    }

    function mergeLiveQuotes(marketData, liveData) {
        const merged = JSON.parse(JSON.stringify(marketData));
        merged.status = merged.status || {};
        for (const ticker of Object.keys(merged.indices || {})) {
            if (merged.status[ticker]) merged.status[ticker].source = 'saved';
            const quote = liveData?.quotes?.[ticker];
            const history = merged.indices[ticker].history || [];
            const latest = history[history.length - 1];
            // Intraday quotes are provisional, even after the exchange closes.
            // They never modify daily history or replace a completed daily close.
            if (!quote?.date || !Number.isFinite(quote.price) || quote.price <= 0
                || (latest && quote.date <= latest.date)) continue;
            const saved = merged.status[ticker];
            if (saved?.as_of && Date.parse(saved.as_of) > Date.parse(quote.as_of)) continue;
            merged.status[ticker] = { ...quote, source: 'live' };
        }
        return merged;
    }

    function exchangeDate(now) {
        const parts = new Intl.DateTimeFormat('en-CA', {
            timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit'
        }).formatToParts(new Date(now));
        const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
        return `${values.year}-${values.month}-${values.day}`;
    }

    function normalizeMarketStatus(raw, dayChange, latest, history = [latest], now = Date.now()) {
        const daily = dayChange ? {
            date: latest.date, label: '1D', price: latest.close,
            percent: dayChange.percent, absolute: dayChange.absolute,
            detail: 'since prev close', asOfText: `Close · ${latest.date}`,
            notice: 'Saved daily close'
        } : null;
        if (!raw?.date || raw.date <= latest.date || !Number.isFinite(raw.price)
            || raw.price <= 0) return daily;

        const timestamp = Date.parse(raw.as_of);
        if (!Number.isFinite(timestamp) || timestamp > now + 60000) return daily;
        const previous = [...history].reverse().find(row => row.date < raw.date);
        // Older deployed Workers used the opening price. Recompute those quotes
        // against saved daily history until the new Worker has been deployed.
        const reference = raw.comparison_basis === 'previous_close'
            ? raw.reference_price : previous?.close;
        if (!Number.isFinite(reference) || reference <= 0) return daily;

        const sameDay = raw.date === exchangeDate(now);
        const stale = raw.is_open && (!sameDay || now - timestamp > 20 * 60 * 1000);
        const live = raw.source === 'live';
        const absolute = raw.price - reference;
        return {
            date: raw.date,
            label: stale ? 'Stale quote' : live && raw.is_open && sameDay ? 'Today' : 'Last quote',
            price: raw.price, percent: absolute / reference * 100, absolute,
            detail: 'since prev close',
            asOfText: new Date(timestamp).toLocaleString([], {
                year: 'numeric', month: 'short', day: 'numeric',
                hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
            }),
            notice: `${live ? 'Market quote' : 'Saved quote · live feed unavailable'}${stale ? ' · stale' : ''}`
        };
    }

    const api = { subtractDays, computeChange, mergeLiveQuotes, normalizeMarketStatus };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.MarketUtils = api;
})(globalThis);
