import copy
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

import market_scraper as scraper


class MarketScraperTests(unittest.TestCase):
    def test_intraday_uses_previous_close_and_ignores_opening_gap(self):
        frame = pd.DataFrame(
            {"Open": [102.0, 101.0], "Close": [102.0, 101.0]},
            index=pd.to_datetime(["2026-09-04T13:30:00Z", "2026-09-04T19:55:00Z"]),
        )
        history = [{"date": "2026-09-03", "close": 100}]
        quote = scraper.intraday_status_for_ticker(
            frame, "XUS.TO", datetime(2026, 9, 4, 19, 59, tzinfo=timezone.utc), history
        )
        self.assertEqual(quote["change_percent"], 1)
        self.assertEqual(quote["reference_price"], 100)

    def test_completed_history_excludes_provisional_and_future_rows(self):
        prices = pd.Series([100, 101, 102], index=pd.to_datetime(["2026-09-03", "2026-09-04", "2026-09-07"]))
        before = scraper.completed_history(prices, datetime(2026, 9, 4, 20, 14, tzinfo=timezone.utc))
        after = scraper.completed_history(prices, datetime(2026, 9, 4, 20, 15, tzinfo=timezone.utc))
        self.assertEqual([row["date"] for row in before], ["2026-09-03"])
        self.assertEqual([row["date"] for row in after], ["2026-09-03", "2026-09-04"])

    def daily_frame(self):
        sessions = pd.bdate_range("2025-01-01", "2026-09-04").difference(
            pd.to_datetime(["2025-12-25", "2026-01-01", "2026-07-03"])
        )
        return pd.concat({
            ticker: pd.DataFrame({"Close": 100.0}, index=sessions)
            for ticker in scraper.INDICES
        }, axis=1)

    def saved_data(self):
        return {"indices": {ticker: {"history": [{"date": "2026-09-04", "close": 99.0}]}
                            for ticker in scraper.INDICES}, "status": {}}

    def test_refresh_replaces_old_adjustments_and_preserves_one_year_reference(self):
        old = self.saved_data()
        with patch.object(scraper, "load_data", return_value=old), \
                patch.object(scraper, "now_utc", return_value=datetime(2026, 9, 5, tzinfo=timezone.utc)), \
                patch.object(scraper.yf, "download", return_value=self.daily_frame()) as download, \
                patch.object(scraper, "build_market_status", return_value={}), \
                patch.object(scraper, "save_data") as save:
            scraper.main()
        self.assertFalse(download.call_args.kwargs["auto_adjust"])
        result = save.call_args.args[0]
        self.assertEqual(result["price_basis"], "split_adjusted_price")
        for ticker in scraper.INDICES:
            history = result["indices"][ticker]["history"]
            self.assertEqual(len(history), 260)
            self.assertLessEqual(history[0]["date"], "2025-09-05")
            self.assertEqual(history[-1]["close"], 100)

    def test_incomplete_download_does_not_save_partial_migration(self):
        frame = self.daily_frame().drop(columns="XUS.TO", level=0)
        with patch.object(scraper, "load_data", return_value=copy.deepcopy(self.saved_data())), \
                patch.object(scraper, "now_utc", return_value=datetime(2026, 9, 5, tzinfo=timezone.utc)), \
                patch.object(scraper.yf, "download", return_value=frame), \
                patch.object(scraper, "save_data") as save:
            with self.assertRaisesRegex(RuntimeError, "XUS.TO"):
                scraper.main()
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
