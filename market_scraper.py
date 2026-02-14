"""
Market Index Scraper
Fetches daily close prices for S&P 500, TSX Composite, and EFA (MSCI EAFE ETF)
from Yahoo Finance using yfinance. Saves to market_data.json.
"""

import yfinance as yf
import json
import os
from datetime import datetime, timezone

DATA_PATH = os.path.join(os.path.dirname(__file__), "market_data.json")

INDICES = {
    "^GSPC": "S&P 500",
    "^GSPTSE": "TSX Composite",
    "EFA": "MSCI EAFE ETF (EFA)",
}


def load_data():
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r") as f:
            return json.load(f)
    return {
        "indices": {
            ticker: {"name": name, "history": []} for ticker, name in INDICES.items()
        },
        "last_updated": None,
    }


def save_data(data):
    with open(DATA_PATH, "w") as f:
        json.dump(data, f, indent=2)


def main():
    print("Market Index Scraper")
    print("=" * 60)

    data = load_data()

    # First run (empty history) -> backfill 1 year; otherwise fetch last 5 days
    needs_backfill = any(
        len(data["indices"][t]["history"]) == 0 for t in INDICES
    )
    period = "1y" if needs_backfill else "5d"
    print(f"Fetch period: {period} ({'backfill' if needs_backfill else 'update'})")

    tickers = list(INDICES.keys())
    df = yf.download(tickers, period=period, interval="1d", group_by="ticker")

    for ticker in tickers:
        try:
            ticker_close = df[ticker]["Close"].dropna()
        except KeyError:
            print(f"  WARNING: No data for {ticker}")
            continue

        existing_dates = {h["date"] for h in data["indices"][ticker]["history"]}
        added = 0

        for date, close in ticker_close.items():
            date_str = date.strftime("%Y-%m-%d")
            if date_str not in existing_dates:
                data["indices"][ticker]["history"].append(
                    {"date": date_str, "close": round(float(close), 2)}
                )
                added += 1

        # Sort by date
        data["indices"][ticker]["history"].sort(key=lambda x: x["date"])

        # Cap at ~1 trading year
        if len(data["indices"][ticker]["history"]) > 260:
            data["indices"][ticker]["history"] = data["indices"][ticker]["history"][-260:]

        print(f"  {INDICES[ticker]}: {added} new entries, {len(data['indices'][ticker]['history'])} total")

    data["last_updated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    save_data(data)
    print(f"\nData saved to {DATA_PATH}")


if __name__ == "__main__":
    main()
