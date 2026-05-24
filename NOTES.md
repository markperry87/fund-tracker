# Fund Tracker - Development Notes

## Overview
Scrapes daily NAV and % change data for 7 RBC mutual funds from rbcgam.com and displays on a GitHub Pages site.

## Architecture

### Data Flow
1. GitHub Actions runs `scraper.py` hourly through the evening on weekdays
2. Scraper visits RBC's mutual fund prices list page with recent date parameters
3. Extracts NAV, daily change %, and date
4. Updates `data.json` when new dated NAV entries are found
5. Commits and pushes to GitHub
6. GitHub Pages serves `index.html` which loads `data.json`

### Key Files
| File | Purpose |
|------|---------|
| `scraper.py` | Playwright-based scraper, extracts fund data |
| `data.json` | JSON data store with fund history |
| `index.html` | Frontend - table + Chart.js growth chart |
| `.github/workflows/scrape.yml` | GitHub Actions workflow |

### Tracked Funds
```
RBF5736 - RBC Intl Equity Currency Neutral
RBF2146 - RBC Global Equity Index
RBF2142 - RBC Canadian Equity Index
RBF5150 - PH&N Dividend Income
RBF2143 - RBC U.S. Equity Index
RBF1691 - RBC Core Plus Bond Pool
RBF5280 - PH&N High Yield Bond
```

## How the Scraper Works

### URL Pattern
The prices list supports a date parameter:
```
https://www.rbcgam.com/en/ca/products/mutual-funds/?tab=prices&date=YYYYMMDD
```

### Data Extraction
1. **Date**: Parses the list page's "Fund price/yield as of" date
2. **NAV**: Finds each fund code, then reads the first 4-decimal NAV value nearby
3. **Daily Change %**: Looks for a signed percentage shortly after the NAV

### Duplicate Prevention
Only adds a new history entry if that fund does not already have an entry for the scraped date.

### Timestamps
- `last_checked`: UTC timestamp with 'Z' suffix (browser converts to local timezone)
- `rbc_data_date`: The date RBC associates with the fund prices

## Common Issues & Solutions

### Wrong Date Extraction
**Problem**: Scraper grabbed "October 31, 2025" from a capital gains disclaimer instead of actual fund date.
**Solution**: Added 7-day sanity check - only accepts dates within last 7 days. Also prioritizes M/D/YYYY format found near NAV.

### Wrong Daily Change %
**Problem**: List page has multiple % columns (Yield, Daily Change). Scraper grabbed first one.
**Solution**: Search for the percentage in a narrow window after the NAV so values from the next fund row are not captured.

### Stale/Cached Data
**Problem**: RBC's list page sometimes served cached data to headless browsers.
**Solution**: Query recent date parameters repeatedly instead of trusting a single same-day request.

### Late RBC Price Updates
**Problem**: If RBC returned the previous available price date before publishing the requested date later that evening, the scraper stored the requested date as unavailable and skipped it forever.
**Solution**: Treat unavailable dates as run-local only. Recent missing business days are retried on later scheduled runs until data appears or the date falls out of the lookback window.

### Timezone Display
**Problem**: "Last checked" showed wrong time (UTC interpreted as local).
**Solution**: Store timestamps with 'Z' suffix to indicate UTC, browser then converts correctly.

## Manual Operations

### Trigger Scraper Manually
```bash
gh workflow run scrape.yml --repo markperry87/fund-tracker
```

### Watch Workflow Progress
```bash
gh run list --repo markperry87/fund-tracker --limit 1
gh run watch --repo markperry87/fund-tracker {RUN_ID}
```

### View Workflow Logs
```bash
gh run view {RUN_ID} --repo markperry87/fund-tracker --log
```

## Data Structure

### data.json Format
```json
{
  "funds": {
    "RBF2142": {
      "name": "RBC Canadian Equity Index",
      "history": [
        {
          "date": "2026-02-02",
          "nav": 14.9716,
          "change_percent": 0.8
        }
      ]
    }
  },
  "last_checked": "2026-02-04T06:52:00Z",
  "last_updated": "2026-02-04T06:52:00Z",
  "rbc_data_date": "2026-02-02"
}
```

## Browser Settings (Anti-Bot)
The scraper uses realistic browser settings to avoid cached/bot-filtered content:
- Chrome user-agent
- 1920x1080 viewport
- Canadian locale (en-CA)
- Toronto timezone
- Cache-busting timestamp in URL

## Future Considerations
- Daily change % extraction could be improved - currently None for some funds on detail pages
- Could add email/notification alerts for significant changes
- Could track more funds by adding to FUNDS list in scraper.py
