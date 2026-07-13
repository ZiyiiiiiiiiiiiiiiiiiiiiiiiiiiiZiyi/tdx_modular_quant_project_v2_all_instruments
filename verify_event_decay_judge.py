"""Verify structured event factor builder and event decay judge."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.decision_council.event_decay_judge import run_event_decay_judge
from functions.factors.event_factor_builder import EVENT_FACTOR_COLUMNS, build_event_daily_features


def main() -> int:
    calendar = pd.bdate_range("2024-01-01", periods=80)
    events = pd.DataFrame(
        [
            {"stock_code": "sh600000", "event_date": calendar[5], "available_date": calendar[5], "event_type": "buyback", "event_direction": "positive", "event_strength": 1, "decay_half_life": 5},
            {"stock_code": "sz000001", "event_date": calendar[10], "available_date": calendar[10], "event_type": "limit_up", "event_direction": "attention", "event_strength": 1, "decay_half_life": 3},
        ]
    )
    features = build_event_daily_features(events, calendar, output_dir="reports/verify_event_decay_judge")
    missing = sorted(set(EVENT_FACTOR_COLUMNS) - set(features.columns))
    if missing:
        print(f"[FAIL] missing event feature columns: {missing}")
        return 1
    price_rows = []
    for symbol in ["sh600000", "sz000001"]:
        for i, date in enumerate(calendar):
            price_rows.append({"stock_code": symbol, "trade_date": date, "close": 10 + i * 0.02})
    saved = run_event_decay_judge(features, pd.DataFrame(price_rows), output_dir=Path("reports/verify_event_decay_judge/event_judge"), min_event_count=1)
    for path in saved.values():
        if not Path(path).exists():
            print(f"[FAIL] missing output: {path}")
            return 1
    print(f"[PASS] event features={features.shape}, outputs={len(saved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
