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

# Base URL for individual fund detail pages
FUND_DETAIL_URL = "https://www.rbcgam.com/en/ca/products/mutual-funds/{fund_code}/detail"


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


def extract_fund_data_from_detail_page(page, fund_code: str, fund_name: str) -> dict:
    """
    Extract NAV data from an individual fund's detail page.
    """
    result = {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "nav": None,
        "change_percent": None,
        "date": None
    }

    try:
        # Get all text from the page
        page_text = page.inner_text("body")

        # Look for the "as of" date - should be near the NAV
        # Pattern: "as of February 3, 2026" or similar
        date_patterns = [
            r'[Aa]s\s+of[:\s]+(\w+\s+\d{1,2},?\s+\d{4})',
            r'[Pp]rice.*[Aa]s\s+of[:\s]+(\w+\s+\d{1,2},?\s+\d{4})',
        ]

        for pattern in date_patterns:
            for match in re.finditer(pattern, page_text):
                date_str = match.group(1)
                for fmt in ['%B %d, %Y', '%B %d %Y', '%b %d, %Y', '%b %d %Y']:
                    try:
                        parsed = datetime.strptime(date_str.replace(',', ''), fmt.replace(',', ''))
                        # Only accept dates within the last 7 days
                        if (datetime.now() - parsed).days <= 7:
                            result["date"] = parsed.strftime('%Y-%m-%d')
                            break
                    except ValueError:
                        continue
                if result["date"]:
                    break
            if result["date"]:
                break

        # Fall back to today's date if not found
        if not result["date"]:
            result["date"] = datetime.now().strftime("%Y-%m-%d")

        # Look for NAV/Price - typically shown prominently on detail page
        # Pattern: "$14.8535" or "NAV: $14.8535"
        nav_patterns = [
            r'(?:NAV|Price|Fund\s+price)[:\s]*\$?([\d,]+\.\d{2,4})',
            r'\$(\d+\.\d{4})',  # 4 decimal places typical for funds
        ]

        for pattern in nav_patterns:
            match = re.search(pattern, page_text)
            if match:
                result["nav"] = float(match.group(1).replace(',', ''))
                break

        # Look for daily change percentage
        # Pattern: "+0.80%" or "-1.20%" or "0.80%"
        change_patterns = [
            r'(?:[Dd]aily\s+)?[Cc]hange[:\s]*([+-]?\d+\.\d+)\s*%',
            r'([+-]\d+\.\d+)\s*%',  # Signed percentage
        ]

        for pattern in change_patterns:
            match = re.search(pattern, page_text)
            if match:
                result["change_percent"] = float(match.group(1))
                break

        # Debug output
        print(f"  {fund_code}: NAV=${result['nav']}, Change={result['change_percent']}%, Date={result['date']}")

    except Exception as e:
        print(f"  Error extracting {fund_code}: {e}")

    return result


def get_all_fund_navs() -> tuple:
    """
    Fetch the NAV and daily change for all tracked funds by visiting each fund's detail page.

    Returns:
        tuple of (list of fund dicts, rbc_data_date string or None)
    """
    results = []
    rbc_data_date = None

    with sync_playwright() as p:
        # Use realistic browser settings
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='en-CA',
            timezone_id='America/Toronto',
        )
        page = context.new_page()

        for fund_code, fund_name in FUNDS:
            url = FUND_DETAIL_URL.format(fund_code=fund_code)
            print(f"Fetching {fund_code}...")

            try:
                # Add cache-busting timestamp
                cache_bust_url = f"{url}?_t={int(datetime.now().timestamp())}"
                page.goto(cache_bust_url, wait_until="networkidle")
                page.wait_for_timeout(3000)  # Wait for JS to render

                # Take screenshot of first fund for debugging
                if fund_code == "RBF2142":
                    page.screenshot(path="debug_screenshot.png", full_page=False)

                result = extract_fund_data_from_detail_page(page, fund_code, fund_name)
                results.append(result)

                # Use the first valid date as the RBC data date
                if rbc_data_date is None and result["date"]:
                    rbc_data_date = result["date"]

            except Exception as e:
                print(f"  Error fetching {fund_code}: {e}")
                results.append({
                    "fund_code": fund_code,
                    "fund_name": fund_name,
                    "nav": None,
                    "change_percent": None,
                    "date": datetime.now().strftime("%Y-%m-%d")
                })

        context.close()
        browser.close()

    return results, rbc_data_date


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
