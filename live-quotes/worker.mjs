const SITE_ORIGIN = 'https://markperry87.github.io';
const ALLOWED_SYMBOLS = new Set([
    '^GSPC',
    '^GSPTSE',
    'EFA',
    'XUS.TO',
    'XIC.TO',
    'XFH.TO'
]);
const CACHE_SECONDS = 60;

export default {
    async fetch(request, env, ctx) {
        const url = new URL(request.url);
        const origin = request.headers.get('Origin');

        if (origin && origin !== SITE_ORIGIN) {
            return jsonResponse({ error: 'Origin not allowed.' }, 403);
        }

        if (request.method === 'OPTIONS') {
            return new Response(null, { status: 204, headers: corsHeaders() });
        }

        if (request.method !== 'GET' || url.pathname !== '/quotes') {
            return jsonResponse({ error: 'Use GET /quotes.' }, 404);
        }

        const symbols = requestedSymbols(url.searchParams.get('symbols'));
        const cacheUrl = new URL(url);
        cacheUrl.search = `?symbols=${encodeURIComponent(symbols.join(','))}`;
        const cacheKey = new Request(cacheUrl.toString(), { method: 'GET' });
        const cached = await caches.default.match(cacheKey);
        if (cached) return cached;

        const results = await Promise.all(symbols.map(fetchQuote));
        const quotes = {};
        const errors = {};

        results.forEach((result, index) => {
            const symbol = symbols[index];
            if (result.quote) {
                quotes[symbol] = result.quote;
            } else {
                errors[symbol] = result.error;
            }
        });

        const response = jsonResponse({
            quotes,
            errors,
            fetched_at: new Date().toISOString(),
            source: 'Yahoo Finance'
        });
        ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
        return response;
    }
};

function requestedSymbols(parameter) {
    const symbols = (parameter || Array.from(ALLOWED_SYMBOLS).join(','))
        .split(',')
        .map(symbol => symbol.trim())
        .filter(symbol => ALLOWED_SYMBOLS.has(symbol));

    return symbols.length ? Array.from(new Set(symbols)) : Array.from(ALLOWED_SYMBOLS);
}

async function fetchQuote(symbol) {
    try {
        const querySymbol = encodeURIComponent(symbol);
        const sourceUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${querySymbol}?range=1d&interval=5m&includePrePost=false&events=history`;
        const response = await fetch(sourceUrl, {
            headers: { 'User-Agent': 'fund-tracker-live-quotes/1.0' }
        });
        if (!response.ok) throw new Error(`Quote response ${response.status}`);

        const payload = await response.json();
        const result = payload.chart?.result?.[0];
        if (!result) throw new Error('No quote data returned');

        return { quote: buildStatus(result) };
    } catch (error) {
        return { error: error.message || 'Quote unavailable' };
    }
}

function buildStatus(result) {
    const meta = result.meta || {};
    const timestamps = result.timestamp || [];
    const series = result.indicators?.quote?.[0] || {};
    const closes = series.close || [];
    const latestPrice = numberOrFallback(meta.regularMarketPrice, lastNumber(closes));
    const latestTimestamp = numberOrFallback(meta.regularMarketTime, lastNumber(timestamps));
    const previousClose = numberOrFallback(meta.chartPreviousClose, meta.previousClose);
    const regular = meta.currentTradingPeriod?.regular;
    const now = Date.now() / 1000;
    const isOpen = Boolean(regular && now >= regular.start && now < regular.end);

    if (!Number.isFinite(latestPrice) || !Number.isFinite(latestTimestamp)) {
        throw new Error('Incomplete quote data');
    }

    let referencePrice = previousClose;
    let label = '1D';

    if (isOpen) {
        const openingIndex = timestamps.findIndex(
            timestamp => timestamp >= regular.start && timestamp < regular.end
        );
        const openingValue = openingIndex >= 0
            ? numberOrFallback(series.open?.[openingIndex], closes[openingIndex])
            : null;
        if (Number.isFinite(openingValue)) referencePrice = openingValue;
        label = 'Today';
    }

    if (!Number.isFinite(referencePrice) || referencePrice === 0) {
        throw new Error('No comparison price returned');
    }

    const change = latestPrice - referencePrice;
    return {
        date: exchangeDate(latestTimestamp, meta.exchangeTimezoneName),
        as_of: new Date(latestTimestamp * 1000).toISOString(),
        price: roundTwo(latestPrice),
        reference_price: roundTwo(referencePrice),
        change: roundTwo(change),
        change_percent: roundTwo((change / referencePrice) * 100),
        is_open: isOpen,
        mode: isOpen ? 'intraday' : '1D',
        label
    };
}

function numberOrFallback(value, fallback) {
    return Number.isFinite(value) ? value : fallback;
}

function lastNumber(values) {
    for (let i = values.length - 1; i >= 0; i -= 1) {
        if (Number.isFinite(values[i])) return values[i];
    }
    return null;
}

function exchangeDate(timestamp, timezone) {
    const formatter = new Intl.DateTimeFormat('en-CA', {
        timeZone: timezone || 'America/New_York',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    });
    const parts = Object.fromEntries(
        formatter.formatToParts(new Date(timestamp * 1000))
            .filter(part => part.type !== 'literal')
            .map(part => [part.type, part.value])
    );
    return `${parts.year}-${parts.month}-${parts.day}`;
}

function roundTwo(value) {
    return Math.round(value * 100) / 100;
}

function corsHeaders() {
    return {
        'Access-Control-Allow-Origin': SITE_ORIGIN,
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Cache-Control': `public, max-age=${CACHE_SECONDS}`,
        'Content-Type': 'application/json; charset=utf-8',
        'Vary': 'Origin'
    };
}

function jsonResponse(body, status = 200) {
    return new Response(JSON.stringify(body), {
        status,
        headers: corsHeaders()
    });
}
