"""
RBC GAM Fund NAV Scraper
Scrapes the daily NAV and % change for specified funds from rbcgam.com
Saves data to JSON file for static site hosting
"""

from playwright.sync_api import sync_playwright
from datetime import datetime
import json
import re
import os

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


def extract_rbc_data_date(page) -> str:
    """
    Extract the 'as of' date from the RBC page showing when the price data is from.

    Returns:
        Date string in YYYY-MM-DD format, or None if not found.
    """
    try:
        # Try to find the rendered "Fund price/yield as of:" date element
        # This is more reliable than regex on raw HTML since the page uses Vue.js
        date_locators = [
            # Look for specific price date elements
            page.locator("text=/Fund price.*as of/i"),
            page.locator("text=/Price.*as of/i"),
            page.locator("[class*='date']"),
            page.locator("[class*='asOf']"),
        ]

        for locator in date_locators:
            try:
                if locator.count() > 0:
                    text = locator.first.inner_text()
                    # Extract date from text like "Fund price/yield as of: February 3, 2026"
                    match = re.search(r'(\w+\s+\d{1,2},?\s+\d{4})', text)
                    if match:
                        date_str = match.group(1)
                        for fmt in ['%B %d, %Y', '%B %d %Y', '%b %d, %Y', '%b %d %Y']:
                            try:
                                parsed = datetime.strptime(date_str.replace(',', ''), fmt.replace(',', ''))
                                # Sanity check: date should be within last 7 days
                                if (datetime.now() - parsed).days <= 7:
                                    return parsed.strftime('%Y-%m-%d')
                            except ValueError:
                                continue
            except Exception:
                continue

        # Fallback: search page text but exclude known bad patterns
        page_text = page.inner_text("body")

        # Look for "as of" dates but filter out old ones (capital gains disclaimers, etc.)
        date_patterns = [
            r'[Pp]rice[s]?.*[Aa]s\s+of[:\s]+(\w+\s+\d{1,2},?\s+\d{4})',
            r'[Aa]s\s+of[:\s]+(\w+\s+\d{1,2},?\s+\d{4})',
        ]

        for pattern in date_patterns:
            for match in re.finditer(pattern, page_text):
                date_str = match.group(1)
                for fmt in ['%B %d, %Y', '%B %d %Y', '%b %d, %Y', '%b %d %Y']:
                    try:
                        parsed = datetime.strptime(date_str.replace(',', ''), fmt.replace(',', ''))
                        # Only accept dates within the last 7 days
                        if (datetime.now() - parsed).days <= 7:
                            return parsed.strftime('%Y-%m-%d')
                    except ValueError:
                        continue

        return None
    except Exception:
        return None


def get_all_fund_navs() -> tuple:
    """
    Fetch the NAV and daily change for all tracked funds.

    Returns:
        tuple of (list of fund dicts, rbc_data_date string or None)
        Each fund dict has 'fund_code', 'fund_name', 'nav', 'change_percent', 'date'
    """
    # URLs to scrape - need both equity and fixed income pages
    urls = [
        "https://www.rbcgam.com/en/ca/products/mutual-funds/?series=f&tab=prices",
        "https://www.rbcgam.com/en/ca/products/mutual-funds/?series=f&tab=prices&assetclass=fixedincome",
    ]

    # Track which funds we've found
    found_data = {}
    rbc_data_date = None

    with sync_playwright() as p:
        # Use realistic browser settings to avoid bot detection/cached content
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='en-CA',
            timezone_id='America/Toronto',
        )
        page = context.new_page()

        for url in urls:
            print(f"Fetching: {url.split('?')[1][:50]}...")
            # Add cache-busting timestamp to URL
            cache_bust_url = f"{url}&_t={int(datetime.now().timestamp())}"
            page.goto(cache_bust_url, wait_until="networkidle")

            # Wait longer for JavaScript to fully render
            page.wait_for_timeout(5000)

            # Scroll to load all funds
            for _ in range(10):
                page.keyboard.press("End")
                page.wait_for_timeout(500)
            page.keyboard.press("Home")
            page.wait_for_timeout(2000)

            # Debug: Save screenshot and print first fund row to see what we're getting
            if "fixedincome" not in url:
                page.screenshot(path="debug_screenshot.png", full_page=False)
                # Print the first RBF2142 row text for debugging
                fund_row = page.locator("tr:has-text('RBF2142')")
                if fund_row.count() > 0:
                    print(f"DEBUG RBF2142 row: {fund_row.first.inner_text()}")

            # Try to extract the RBC data date from the first page
            if rbc_data_date is None:
                rbc_data_date = extract_rbc_data_date(page)

            # Use RBC date if found, otherwise fall back to today's date
            data_date = rbc_data_date if rbc_data_date else datetime.now().strftime("%Y-%m-%d")

            # Try to extract each fund we haven't found yet
            for fund_code, fund_name in FUNDS:
                if fund_code not in found_data:
                    result = extract_fund_data(page, fund_code, fund_name, data_date)
                    if result['nav'] is not None:
                        found_data[fund_code] = result

        context.close()
        browser.close()

    # Use RBC date if found, otherwise fall back to today's date
    data_date = rbc_data_date if rbc_data_date else datetime.now().strftime("%Y-%m-%d")

    # Build final results list in original order
    results = []
    for fund_code, fund_name in FUNDS:
        if fund_code in found_data:
            results.append(found_data[fund_code])
        else:
            print(f"  Warning: {fund_code} ({fund_name}) not found")
            results.append({
                "fund_code": fund_code,
                "fund_name": fund_name,
                "nav": None,
                "change_percent": None,
                "date": data_date
            })

    return results, rbc_data_date


def extract_fund_data(page, fund_code: str, fund_name: str, scrape_date: str) -> dict:
    """
    Extract NAV data for a single fund from the already-loaded page.
    """
    # Find the row containing our fund code
    fund_row = page.locator(f"tr:has-text('{fund_code}')")

    if fund_row.count() == 0:
        return {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "nav": None,
            "change_percent": None,
            "date": scrape_date
        }

    # Get the text content of the row
    row_text = fund_row.first.inner_text()

    # Extract NAV - look for dollar amount pattern
    nav_match = re.search(r'\$?([\d,]+\.\d{2,4})', row_text)
    nav_value = float(nav_match.group(1).replace(',', '')) if nav_match else None

    # Extract % change - find ALL percentages and take the LAST one
    # RBC table columns: Yield±, Price, Net change, % Change (daily)
    # The daily % change is the last percentage in the row
    change_matches = re.findall(r'([+-]?\d+\.\d+)\s*%', row_text)
    change_percent = float(change_matches[-1]) if change_matches else None

    return {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "nav": nav_value,
        "change_percent": change_percent,
        "date": scrape_date
    }


def update_json_data(results: list, rbc_data_date: str = None):
    """Update the JSON data file with new results."""
    data = load_data()

    for r in results:
        fund_code = r['fund_code']

        # Initialize fund entry if it doesn't exist
        if fund_code not in data['funds']:
            data['funds'][fund_code] = {
                "name": r['fund_name'],
                "history": []
            }

        history = data['funds'][fund_code]['history']

        # Only add new entry if NAV actually changed from the most recent entry
        # This prevents duplicates when RBC data hasn't updated (weekends, holidays)
        if r['nav'] is not None:
            last_nav = history[-1]['nav'] if history else None
            if last_nav is None or r['nav'] != last_nav:
                history.append({
                    "date": r['date'],
                    "nav": r['nav'],
                    "change_percent": r['change_percent']
                })
                # Sort by date
                history.sort(key=lambda x: x['date'])

    # Update timestamps - when scraper ran and what date RBC data is for
    data['last_checked'] = datetime.now().isoformat()
    data['last_updated'] = datetime.now().isoformat()

    # Always store rbc_data_date - use extracted date, or fall back to the date used in data entries
    if rbc_data_date:
        data['rbc_data_date'] = rbc_data_date
    else:
        # Fall back to the date from the first result with data
        for r in results:
            if r['nav'] is not None:
                data['rbc_data_date'] = r['date']
                break

    save_data(data)
    return data


def main():
    print("RBC GAM Fund NAV Scraper")
    print("=" * 60)

    # Log when the scraper is running
    check_datetime = datetime.now()
    print(f"Scraper run date: {check_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)

    try:
        results, rbc_data_date = get_all_fund_navs()

        # Log the RBC data date
        print("-" * 60)
        if rbc_data_date:
            print(f"RBC website data date: {rbc_data_date}")
        else:
            print("RBC website data date: Could not extract (using current date)")

        # Save to JSON
        update_json_data(results, rbc_data_date)
        print("\nData saved to data.json")

        print(f"\n{'Fund':<35} {'NAV':>10} {'Change':>10} {'Date'}")
        print("-" * 70)

        for r in results:
            nav_str = f"${r['nav']:.4f}" if r['nav'] else "N/A"

            if r['change_percent'] is not None:
                sign = "+" if r['change_percent'] >= 0 else ""
                change_str = f"{sign}{r['change_percent']:.2f}%"
            else:
                change_str = "N/A"

            print(f"{r['fund_name']:<35} {nav_str:>10} {change_str:>10} {r['date']}")

        return results

    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
