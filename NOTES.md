# Fund Tracker - Development Notes

## Overview
Scrapes daily NAV and % change data for 7 RBC mutual funds from rbcgam.com and displays on a GitHub Pages site.

## Architecture

### Data Flow
1. GitHub Actions runs `scraper.py` daily at 6 PM EST (11 PM UTC) on weekdays
2. Scraper visits each fund's individual detail page on RBC's website
3. Extracts NAV, daily change %, and date
4. Updates `data.json` (only if NAV changed from last entry)
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
Each fund has a detail page at:
```
https://www.rbcgam.com/en/ca/products/mutual-funds/{FUND_CODE}/detail
```

### Data Extraction
1. **NAV**: Regex looks for "NAV $" followed by a 4-decimal number (e.g., `14.9716`)
2. **Date**: Looks for M/D/YYYY format (e.g., `2/2/2026`) near the NAV
3. **Daily Change %**: Looks for signed percentage patterns

### Duplicate Prevention
Only adds new history entry if NAV differs from the most recent entry. This prevents duplicate data on weekends/holidays when RBC doesn't update.

### Timestamps
- `last_checked`: UTC timestamp with 'Z' suffix (browser converts to local timezone)
- `rbc_data_date`: The date RBC associates with the fund prices

## Common Issues & Solutions

### Wrong Date Extraction
**Problem**: Scraper grabbed "October 31, 2025" from a capital gains disclaimer instead of actual fund date.
**Solution**: Added 7-day sanity check - only accepts dates within last 7 days. Also prioritizes M/D/YYYY format found near NAV.

### Wrong Daily Change %
**Problem**: List page has multiple % columns (Yield, Daily Change). Scraper grabbed first one.
**Solution**: Switched to individual fund detail pages which have cleaner data structure.

### Stale/Cached Data
**Problem**: RBC's list page sometimes served cached data to headless browsers.
**Solution**: Use individual fund detail pages with cache-busting URL parameters.

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
