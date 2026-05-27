# Live Market Quotes

This Worker supplies current card prices without waiting for a GitHub Pages
deployment. It reads the same Yahoo Finance quote feed already used by
`market_scraper.py`, restricts requests to the six displayed symbols, and
caches results for 60 seconds.

## Deploy

1. Create or sign in to a Cloudflare account and enable its free
   `workers.dev` subdomain.
2. From this folder, run `npx wrangler deploy`.
3. Copy the resulting Worker URL and add `/quotes`, for example:
   `https://fund-tracker-live-quotes.example.workers.dev/quotes`.
4. Put that URL in `liveQuotesEndpoint` in `../live-config.js`, then publish
   that one configuration change to GitHub.

The webpage calls the endpoint when opened and once per minute while it stays
open. If it is unavailable or has not yet been configured, cards continue to
use `market_data.json`.
