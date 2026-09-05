"""
Market Data Scraper
Fetches daily close prices for broad benchmarks and underlying iShares ETFs
from Yahoo Finance using yfinance. Saves to market_data.json.
"""

import yfinance as yf
import json
import os
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DATA_PATH = os.path.join(os.path.dirname(__file__), "market_data.json")
MARKET_TZ = ZoneInfo("America/New_York")
MARKET_CLOSE_BUFFER_MINUTES = 15
PRICE_BASIS = "split_adjusted_price"

INDICES = {
    "^GSPC": "S&P 500",
    "^GSPTSE": "TSX Composite",
    "EFA": "MSCI EAFE ETF (EFA)",
    "XUS.TO": "iShares Core S&P 500 Index ETF (XUS)",
    "XIC.TO": "iShares Core S&P/TSX Capped Composite Index ETF (XIC)",
    "XFH.TO": "iShares Core MSCI EAFE IMI Index ETF (CAD-Hedged) (XFH)",
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
        "comparison_basis": "previous_close",
        "source": "saved",
    }


def intraday_status_for_ticker(intraday_df, ticker, check_time, history):
    try:
        ticker_df = get_ticker_frame(intraday_df, ticker)
        ticker_df = ticker_df[["Close"]].dropna()
    except (KeyError, TypeError):
        return None

    if ticker_df.empty:
        return None

    latest_idx = ticker_df.index[-1]
    latest_time = timestamp_to_eastern(latest_idx)
    eastern_now = check_time.astimezone(MARKET_TZ)

    if latest_time.date() != eastern_now.date() or not is_regular_market_open(check_time):
        return None

    previous = next(
        (row for row in reversed(history) if row["date"] < latest_time.date().isoformat()),
        None,
    )
    if previous is None:
        return None
    previous_close = previous["close"]
    latest_price = float(ticker_df.iloc[-1]["Close"])
    if not previous_close or not math.isfinite(latest_price):
        return None

    absolute = latest_price - previous_close
    return {
        "date": latest_time.date().isoformat(),
        "as_of": iso_utc(latest_time),
        "price": round(latest_price, 6),
        "reference_price": previous_close,
        "change": round(absolute, 2),
        "change_percent": round((absolute / previous_close) * 100, 2),
        "is_open": True,
        "mode": "intraday",
        "label": "Today",
        "comparison_basis": "previous_close",
        "source": "saved",
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
            auto_adjust=False,
            progress=False,
        )
    except Exception as e:
        print(f"  WARNING: Could not fetch intraday status: {e}")
        intraday_df = None

    for ticker in tickers:
        ticker_status = None
        if intraday_df is not None:
            ticker_status = intraday_status_for_ticker(
                intraday_df, ticker, check_time, histories.get(ticker, [])
            )

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

    if date_str < today:
        return True
    if date_str > today:
        return False

    return eastern.weekday() < 5 and current_minutes >= close_ready_minutes


def completed_history(ticker_close, check_time):
    """Replace the entire retained window so splits and corrections stay consistent."""
    rows = {}
    for date, close in ticker_close.items():
        date_str = date.strftime("%Y-%m-%d")
        close = float(close)
        if should_include_daily_row(date_str, check_time) and math.isfinite(close) and close > 0:
            rows[date_str] = {"date": date_str, "close": round(close, 6)}
    return [rows[date] for date in sorted(rows)][-260:]


def main():
    print("Market Data Scraper")
    print("=" * 60)

    data = load_data()
    check_time = now_utc()
    data.setdefault("indices", {})
    for ticker, name in INDICES.items():
        data["indices"].setdefault(ticker, {"name": name, "history": []})
        data["indices"][ticker]["name"] = name

    # Yahoo Close is split-adjusted but excludes dividend adjustments. Refresh
    # the full retained window, including a reference close before the 1Y cutoff.
    tickers = list(INDICES.keys())
    df = yf.download(
        tickers, period="2y", interval="1d", group_by="ticker",
        auto_adjust=False, progress=False,
    )
    history_changed = data.get("price_basis") != PRICE_BASIS
    histories = {}
    failures = []

    for ticker in tickers:
        try:
            ticker_close = df[ticker]["Close"].dropna()
        except (KeyError, TypeError):
            failures.append(ticker)
            continue
        history = completed_history(ticker_close, check_time)
        old_history = data["indices"][ticker]["history"]
        cutoff = (check_time.astimezone(MARKET_TZ).date() - timedelta(days=365)).isoformat()
        if (not history or history[0]["date"] > cutoff
                or (old_history and history[-1]["date"] < old_history[-1]["date"])):
            failures.append(ticker)
            continue
        history_changed |= history != old_history
        data["indices"][ticker]["history"] = history
        histories[ticker] = history
        print(f"  {INDICES[ticker]}: {len(history)} refreshed daily closes")

    if failures:
        raise RuntimeError(f"Incomplete daily history for {', '.join(failures)}; saved data unchanged")
    data["price_basis"] = PRICE_BASIS

    status = build_market_status(tickers, histories, check_time)
    status_changed = status != data.get("status", {})
    if status_changed:
        data["status"] = status
        data["status_last_updated"] = iso_utc(check_time)

    if history_changed or status_changed:
        if history_changed:
            data["last_updated"] = iso_utc(check_time)
        save_data(data)
        print(f"\nData saved to {DATA_PATH}")
    else:
        print("\nNo new market data or status changes found; leaving market_data.json unchanged")


if __name__ == "__main__":
    main()
