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
