"""
Market Index Scraper
Fetches daily close prices for S&P 500, TSX Composite, and EFA (MSCI EAFE ETF)
from Yahoo Finance using yfinance. Saves to market_data.json.
"""

import yfinance as yf
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DATA_PATH = os.path.join(os.path.dirname(__file__), "market_data.json")
MARKET_TZ = ZoneInfo("America/New_York")
MARKET_CLOSE_BUFFER_MINUTES = 15

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
        "status_last_updated": None,
    }


def save_data(data):
    with open(DATA_PATH, "w") as f:
        json.dump(data, f, indent=2)


def now_utc():
    return datetime.now(timezone.utc)


def iso_utc(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def get_ticker_frame(df, ticker):
    if ticker in df:
        return df[ticker]
    return df


def timestamp_to_eastern(ts):
    if hasattr(ts, "tz_convert") and ts.tzinfo is not None:
        return ts.tz_convert(MARKET_TZ)
    if hasattr(ts, "to_pydatetime"):
        dt = ts.to_pydatetime()
    else:
        dt = ts
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MARKET_TZ)
    return dt.astimezone(MARKET_TZ)


def is_regular_market_open(check_time):
    eastern = check_time.astimezone(MARKET_TZ)
    if eastern.weekday() >= 5:
        return False

    minutes = eastern.hour * 60 + eastern.minute
    open_minutes = 9 * 60 + 30
    close_minutes = 16 * 60
    return open_minutes <= minutes < close_minutes


def daily_history_change(history):
    if len(history) < 2:
        return None

    latest = history[-1]
    previous = history[-2]
    if not previous.get("close"):
        return None

    absolute = latest["close"] - previous["close"]
    return {
        "date": latest["date"],
        "as_of": latest["date"],
        "price": latest["close"],
        "reference_price": previous["close"],
        "change": round(absolute, 2),
        "change_percent": round((absolute / previous["close"]) * 100, 2),
        "is_open": False,
        "mode": "1D",
        "label": "1D",
    }


def intraday_status_for_ticker(intraday_df, ticker, check_time):
    try:
        ticker_df = get_ticker_frame(intraday_df, ticker)
        ticker_df = ticker_df[["Open", "Close"]].dropna()
    except (KeyError, TypeError):
        return None

    if ticker_df.empty:
        return None

    latest_idx = ticker_df.index[-1]
    latest_time = timestamp_to_eastern(latest_idx)
    eastern_now = check_time.astimezone(MARKET_TZ)

    if latest_time.date() != eastern_now.date() or not is_regular_market_open(check_time):
        return None

    open_price = float(ticker_df.iloc[0]["Open"])
    latest_price = float(ticker_df.iloc[-1]["Close"])
    if not open_price:
        return None

    absolute = latest_price - open_price
    return {
        "date": latest_time.date().isoformat(),
        "as_of": iso_utc(latest_time),
        "price": round(latest_price, 2),
        "reference_price": round(open_price, 2),
        "change": round(absolute, 2),
        "change_percent": round((absolute / open_price) * 100, 2),
        "is_open": True,
        "mode": "intraday",
        "label": "Today",
    }


def build_market_status(tickers, histories, check_time):
    print("\nFetching intraday market status...")
    status = {}

    try:
        intraday_df = yf.download(
            tickers,
            period="1d",
            interval="5m",
            group_by="ticker",
            prepost=False,
            progress=False,
        )
    except Exception as e:
        print(f"  WARNING: Could not fetch intraday status: {e}")
        intraday_df = None

    for ticker in tickers:
        ticker_status = None
        if intraday_df is not None:
            ticker_status = intraday_status_for_ticker(intraday_df, ticker, check_time)

        if ticker_status is None:
            ticker_status = daily_history_change(histories.get(ticker, []))

        if ticker_status is not None:
            status[ticker] = ticker_status
            mode = "open" if ticker_status["is_open"] else "closed"
            print(
                f"  {INDICES[ticker]}: {mode}, "
                f"{ticker_status['change_percent']:+.2f}%"
            )
        else:
            print(f"  WARNING: No status available for {ticker}")

    return status


def should_include_daily_row(date_str, check_time):
    eastern = check_time.astimezone(MARKET_TZ)
    today = eastern.date().isoformat()
    close_ready_minutes = 16 * 60 + MARKET_CLOSE_BUFFER_MINUTES
    current_minutes = eastern.hour * 60 + eastern.minute

    if date_str != today:
        return True

    return eastern.weekday() < 5 and current_minutes >= close_ready_minutes


def main():
    print("Market Index Scraper")
    print("=" * 60)

    data = load_data()
    check_time = now_utc()

    # First run (empty history) -> backfill 1 year; otherwise fetch last 5 days
    needs_backfill = any(
        len(data["indices"][t]["history"]) == 0 for t in INDICES
    )
    period = "1y" if needs_backfill else "5d"
    print(f"Fetch period: {period} ({'backfill' if needs_backfill else 'update'})")

    tickers = list(INDICES.keys())
    df = yf.download(tickers, period=period, interval="1d", group_by="ticker", progress=False)
    total_added = 0
    histories = {}

    for ticker in tickers:
        try:
            ticker_close = df[ticker]["Close"].dropna()
        except KeyError:
            print(f"  WARNING: No data for {ticker}")
            histories[ticker] = data["indices"].get(ticker, {}).get("history", [])
            continue

        existing_dates = {h["date"] for h in data["indices"][ticker]["history"]}
        added = 0

        for date, close in ticker_close.items():
            date_str = date.strftime("%Y-%m-%d")
            if not should_include_daily_row(date_str, check_time):
                continue
            if date_str not in existing_dates:
                data["indices"][ticker]["history"].append(
                    {"date": date_str, "close": round(float(close), 2)}
                )
                added += 1
                total_added += 1

        # Sort by date
        data["indices"][ticker]["history"].sort(key=lambda x: x["date"])

        # Cap at ~1 trading year
        if len(data["indices"][ticker]["history"]) > 260:
            data["indices"][ticker]["history"] = data["indices"][ticker]["history"][-260:]

        print(f"  {INDICES[ticker]}: {added} new entries, {len(data['indices'][ticker]['history'])} total")
        histories[ticker] = data["indices"][ticker]["history"]

    status = build_market_status(tickers, histories, check_time)
    status_changed = status != data.get("status", {})
    if status_changed:
        data["status"] = status
        data["status_last_updated"] = iso_utc(check_time)

    if total_added or status_changed:
        if total_added:
            data["last_updated"] = iso_utc(check_time)
        save_data(data)
        print(f"\nData saved to {DATA_PATH}")
    else:
        print("\nNo new market data or status changes found; leaving market_data.json unchanged")


if __name__ == "__main__":
    main()
