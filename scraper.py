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


def get_all_fund_navs() -> list:
    """
    Fetch the NAV and daily change for all tracked funds.

    Returns:
        list of dicts with 'fund_code', 'fund_name', 'nav', 'change_percent', 'date'
    """
    # Get today's date for the scrape
    scrape_date = datetime.now().strftime("%Y-%m-%d")

    # URLs to scrape - need both equity and fixed income pages
    urls = [
        "https://www.rbcgam.com/en/ca/products/mutual-funds/?series=f&tab=prices",
        "https://www.rbcgam.com/en/ca/products/mutual-funds/?series=f&tab=prices&assetclass=fixedincome",
    ]

    # Track which funds we've found
    found_data = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for url in urls:
            print(f"Fetching: {url.split('?')[1][:50]}...")
            page.goto(url, wait_until="networkidle")

            # Wait for page to load
            page.wait_for_timeout(3000)

            # Scroll to load all funds
            for _ in range(10):
                page.keyboard.press("End")
                page.wait_for_timeout(500)
            page.keyboard.press("Home")
            page.wait_for_timeout(1000)

            # Try to extract each fund we haven't found yet
            for fund_code, fund_name in FUNDS:
                if fund_code not in found_data:
                    result = extract_fund_data(page, fund_code, fund_name, scrape_date)
                    if result['nav'] is not None:
                        found_data[fund_code] = result

        browser.close()

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
                "date": scrape_date
            })

    return results


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

    # Extract % change - look for percentage with optional +/- sign
    change_match = re.search(r'(-?\d+\.\d+)\s*%', row_text)
    change_percent = float(change_match.group(1)) if change_match else None

    return {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "nav": nav_value,
        "change_percent": change_percent,
        "date": scrape_date
    }


def update_json_data(results: list):
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

        # Check if we already have data for this date
        history = data['funds'][fund_code]['history']
        existing_dates = {entry['date'] for entry in history}

        if r['date'] not in existing_dates and r['nav'] is not None:
            history.append({
                "date": r['date'],
                "nav": r['nav'],
                "change_percent": r['change_percent']
            })
            # Sort by date
            history.sort(key=lambda x: x['date'])

    # Update last_updated timestamp
    data['last_updated'] = datetime.now().isoformat()

    save_data(data)
    return data


def main():
    print("RBC GAM Fund NAV Scraper")
    print("=" * 60)

    try:
        results = get_all_fund_navs()

        # Save to JSON
        update_json_data(results)
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
