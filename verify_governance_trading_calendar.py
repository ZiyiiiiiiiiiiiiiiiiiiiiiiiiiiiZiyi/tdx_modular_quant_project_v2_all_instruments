from __future__ import annotations

import pandas as pd

from functions.data.trading_calendar import TradingCalendar


def main() -> None:
    calendar = TradingCalendar(["2024-09-30", "2024-10-08", "2024-10-09"])
    assert calendar.next_session("2024-09-30") == pd.Timestamp("2024-10-08")
    assert calendar.previous_session("2024-10-08") == pd.Timestamp("2024-09-30")
    assert calendar.contains("2024-10-08")
    assert pd.isna(calendar.next_session("2024-10-09"))
    print("[PASS] governance schedule uses observed exchange sessions across holiday gaps")


if __name__ == "__main__":
    main()
