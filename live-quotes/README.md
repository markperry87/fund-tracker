# Live Market Quotes

This Worker supplies current card prices without waiting for a GitHub Pages
deployment. It reads the same Yahoo Finance quote feed already used by
`market_scraper.py`, restricts requests to the six displayed symbols, and
caches results for 60 seconds.

## Deploy

The deployed endpoint is:
`https://dayline-api.copper-field-7n4q92.workers.dev/quotes`.

To redeploy changes from this folder, run `npx wrangler deploy`.

The webpage calls the endpoint when opened and once per minute while it stays
open. If it is unavailable or has not yet been configured, cards continue to
use `market_data.json`.

Quotes always compare against the previous close. They remain provisional even
after market hours and never replace the scraper's completed daily history.
The cards show the quote date/time and identify saved or stale quotes.

Daily history uses Yahoo's split-adjusted Close (`auto_adjust=False`), excluding
ETF distributions. The scraper refreshes the full retained 260-session window
on each run, so corrections and splits update old dates as well as new ones.

Run the regression checks from the repository root:

```bash
node --test tests/market.test.cjs
python -m unittest discover -s tests -p 'test_*.py'
```
