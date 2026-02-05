"""
RBC GAM Fund NAV Scraper
Scrapes the daily NAV and % change for specified funds from rbcgam.com
Uses the fund prices list page with date parameters to pull historical data
Saves data to JSON file for static site hosting
"""

from playwright.sync_api import sync_playwright
from datetime import datetime, timezone, timedelta
import json
import re
import os
import sys

# Data file path
DATA_PATH = os.path.join(os.path.dirname(__file__), "data.json")

# List of funds to track (fund_code, friendly_name)
FUNDS = [
    ("RBF5736", "RBC Intl Equity Currency Neutral"),
    ("RBF2146", "RBC Global Equity Index"),
    ("RBF2142", "RBC Canadian Equity Index"),
    ("RBF5150", "PH&N Dividend Income"),
    ("RBF2143", "RBC U.S. Equity Index"),
    ("RBF1691", "RBC Core Plus Bond Pool"),
    ("RBF5280", "PH&N High Yield Bond"),
]

# Fund prices list page - supports ?tab=prices&date=YYYYMMDD parameter
PRICES_LIST_URL = "https://www.rbcgam.com/en/ca/products/mutual-funds/"


def load_data():
    """Load existing data from JSON file."""
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r') as f:
            return json.load(f)
    return {"funds": {code: {"name": name, "history": []} for code, name in FUNDS}}


def save_data(data):
    """Save data to JSON file."""
    with open(DATA_PATH, 'w') as f:
        json.dump(data, f, indent=2)


def parse_as_of_date(page_text):
    """Parse the 'Fund price/yield as of' date from the page text. Returns YYYY-MM-DD or None."""
    match = re.search(r'Fund price/yield as of[:\s]*([A-Za-z]+\s+\d{1,2},?\s+\d{4})', page_text)
    if match:
        date_str = match.group(1).replace(',', '')
        for fmt in ['%b %d %Y', '%B %d %Y']:
            try:
                return datetime.strptime(date_str, fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
    return None


def extract_funds_from_list_page(page, page_text, actual_date):
    """
    Extract NAV and change % for all tracked funds from the prices list page text.

    Returns list of fund result dicts.
    """
    results = []

    for fund_code, fund_name in FUNDS:
        result = {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "nav": None,
            "change_percent": None,
            "date": actual_date,
        }

        # Find the fund code in the page text and extract nearby data
        idx = page_text.find(fund_code)
        if idx >= 0:
            nearby = page_text[idx:idx + 1000]

            # NAV - 4 decimal place number (first one after fund code)
            nav_match = re.search(r'(\d+\.\d{4})', nearby)
            if nav_match:
                result["nav"] = float(nav_match.group(1))

            # Change % - signed or unsigned percentage
            change_match = re.search(r'([+-]?\d+\.\d+)\s*%', nearby)
            if change_match:
                result["change_percent"] = float(change_match.group(1))

        results.append(result)

    return results


def get_business_days(num_days, end_date=None):
    """
    Generate a list of business days working backwards from end_date (default: today).
    Skips weekends (Sat/Sun) since RBC doesn't publish fund data on weekends.

    Returns list of date strings in YYYYMMDD format (most recent first).
    """
    dates = []
    current = end_date or datetime.now().date()
    while len(dates) < num_days:
        if current.weekday() < 5:  # Mon=0 through Fri=4
            dates.append(current.strftime('%Y%m%d'))
        current -= timedelta(days=1)
    return dates


def get_missing_dates(num_days):
    """
    Determine which business days in the last num_days we don't have data for yet.
    Checks existing data.json and only returns dates that are missing.

    Returns list of date strings in YYYYMMDD format (most recent first).
    """
    data = load_data()

    # Collect all dates we already have across all funds.
    # A date counts as "present" only if ALL tracked funds have data for it.
    fund_codes = [code for code, _ in FUNDS]
    dates_per_fund = []
    for code in fund_codes:
        if code in data.get('funds', {}):
            fund_dates = {h['date'] for h in data['funds'][code].get('history', [])}
            dates_per_fund.append(fund_dates)
        else:
            dates_per_fund.append(set())

    # Dates we have for ALL funds
    if dates_per_fund:
        existing_dates = set.intersection(*dates_per_fund) if dates_per_fund else set()
    else:
        existing_dates = set()

    # Dates we already know are unavailable (holidays, out of range)
    unavailable = set(data.get('unavailable_dates', []))

    # Generate business days and filter out ones we already have or are unavailable
    all_business_days = get_business_days(num_days)
    missing = []
    for d in all_business_days:
        # Convert YYYYMMDD -> YYYY-MM-DD for comparison
        iso_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if iso_date not in existing_dates and d not in unavailable:
            missing.append(d)

    return missing


def scrape_multiple_dates(dates_to_scrape):
    """
    Scrape fund data for multiple dates using the prices list page.

    Args:
        dates_to_scrape: list of date strings in YYYYMMDD format

    Returns:
        dict mapping actual_date (YYYY-MM-DD) -> list of fund result dicts
    """
    all_results = {}
    skipped_dates = set()  # dates that are out of range or unavailable

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='en-CA',
            timezone_id='America/Toronto',
        )
        page = context.new_page()

        for date_str in dates_to_scrape:
            url = f"{PRICES_LIST_URL}?tab=prices&date={date_str}"
            print(f"Fetching data for {date_str}...")

            try:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(5000)

                page_text = page.inner_text("body")
                actual_date = parse_as_of_date(page_text)

                if not actual_date:
                    print(f"  WARNING: Could not parse 'as of' date for requested {date_str}, skipping")
                    skipped_dates.add(date_str)
                    continue

                # Check if the returned date is far from what we requested (out of range)
                requested = datetime.strptime(date_str, '%Y%m%d').date()
                returned = datetime.strptime(actual_date, '%Y-%m-%d').date()
                if abs((returned - requested).days) > 5:
                    print(f"  Requested {date_str} -> displayed {actual_date} (out of range, skipping)")
                    skipped_dates.add(date_str)
                    continue

                # If RBC returned a different date than requested, this is a holiday/unavailable date
                requested_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                if actual_date != requested_iso:
                    skipped_dates.add(date_str)

                # Skip if we already have this actual date (e.g., requesting Fri and Sat both give Fri)
                if actual_date in all_results:
                    print(f"  Requested {date_str} -> displayed {actual_date} (already scraped, skipping)")
                    continue

                print(f"  Requested {date_str} -> displayed {actual_date}")

                results = extract_funds_from_list_page(page, page_text, actual_date)
                all_results[actual_date] = results

                # Log extracted data
                for r in results:
                    nav_str = f"${r['nav']:.4f}" if r['nav'] else "N/A"
                    change_str = f"{r['change_percent']:+.2f}%" if r['change_percent'] is not None else "N/A"
                    print(f"    {r['fund_code']}: NAV={nav_str}, Change={change_str}")

            except Exception as e:
                print(f"  Error fetching {date_str}: {e}")

        context.close()
        browser.close()

    return all_results, skipped_dates


def update_json_data(all_results, skipped_dates=None):
    """
    Update the JSON data file with results from multiple dates.

    Args:
        all_results: dict mapping date (YYYY-MM-DD) -> list of fund result dicts
    """
    data = load_data()

    for date, results in all_results.items():
        for r in results:
            fund_code = r['fund_code']

            # Initialize fund entry if it doesn't exist
            if fund_code not in data['funds']:
                data['funds'][fund_code] = {
                    "name": r['fund_name'],
                    "history": []
                }

            history = data['funds'][fund_code]['history']

            if r['nav'] is not None:
                # Check if we already have an entry for this exact date
                existing_dates = {h['date'] for h in history}
                if r['date'] not in existing_dates:
                    history.append({
                        "date": r['date'],
                        "nav": r['nav'],
                        "change_percent": r['change_percent']
                    })

        # Sort each fund's history by date
        for fund_code in data['funds']:
            data['funds'][fund_code]['history'].sort(key=lambda x: x['date'])

    # Track dates that RBC doesn't have data for (holidays, out of range)
    # so we don't keep retrying them
    if skipped_dates:
        existing_skipped = set(data.get('unavailable_dates', []))
        existing_skipped.update(skipped_dates)
        data['unavailable_dates'] = sorted(existing_skipped)

    # Update timestamps
    data['last_checked'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    data['last_updated'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    # Set rbc_data_date to the most recent date we have data for
    all_dates = sorted(all_results.keys())
    if all_dates:
        data['rbc_data_date'] = all_dates[-1]

    save_data(data)
    return data


def main():
    print("RBC GAM Fund NAV Scraper")
    print("=" * 60)

    check_datetime = datetime.now()
    print(f"Scraper run date: {check_datetime.strftime('%Y-%m-%d %H:%M:%S')}")

    # --days N: how many business days back to look (default 5)
    # --backfill N: pull N business days, ignoring what's already in data.json
    num_days = 5
    backfill = False
    if '--days' in sys.argv:
        idx = sys.argv.index('--days')
        if idx + 1 < len(sys.argv):
            num_days = int(sys.argv[idx + 1])
    if '--backfill' in sys.argv:
        idx = sys.argv.index('--backfill')
        if idx + 1 < len(sys.argv):
            num_days = int(sys.argv[idx + 1])
            backfill = True

    if backfill:
        dates_to_scrape = get_business_days(num_days)
        print(f"Backfill mode: scraping {len(dates_to_scrape)} business days")
    else:
        dates_to_scrape = get_missing_dates(num_days)
        if not dates_to_scrape:
            print(f"All {num_days} recent business days already in data.json, nothing to scrape.")
            return
        print(f"Found {len(dates_to_scrape)} missing dates out of last {num_days} business days")

    print(f"Dates to scrape: {', '.join(dates_to_scrape)}")
    print("-" * 60)

    try:
        all_results, skipped_dates = scrape_multiple_dates(dates_to_scrape)

        print("\n" + "=" * 60)
        print(f"SUMMARY ({len(all_results)} dates scraped)")
        if skipped_dates:
            print(f"Skipped {len(skipped_dates)} unavailable dates: {', '.join(sorted(skipped_dates))}")
        print("=" * 60)

        for date in sorted(all_results.keys()):
            results = all_results[date]
            print(f"\nDate: {date}")
            print(f"  {'Fund':<35} {'NAV':>12} {'Change':>10}")
            print(f"  {'-'*57}")
            for r in results:
                nav_str = f"${r['nav']:.4f}" if r['nav'] else "N/A"
                if r['change_percent'] is not None:
                    sign = "+" if r['change_percent'] >= 0 else ""
                    change_str = f"{sign}{r['change_percent']:.2f}%"
                else:
                    change_str = "N/A"
                print(f"  {r['fund_name']:<35} {nav_str:>12} {change_str:>10}")

        # Save to JSON
        update_json_data(all_results, skipped_dates)
        print(f"\nData saved to data.json ({len(all_results)} new dates added)")

        return all_results

    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
