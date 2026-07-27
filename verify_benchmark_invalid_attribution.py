"""Verify incomplete benchmark returns cannot contaminate attribution."""
import pandas as pd

from functions.decision_council.analytics import build_governance_attribution


def main():
    features = pd.DataFrame([
        {"date": "2024-01-02", "symbol": "A", "close": 100.0, "amount": 300.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-01-02", "symbol": "B", "close": 100.0, "amount": 200.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-01-03", "symbol": "A", "close": 110.0, "amount": 300.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-01-04", "symbol": "A", "close": 121.0, "amount": 300.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-01-04", "symbol": "B", "close": 100.0, "amount": 200.0, "instrument_type": "stock", "is_trading": True},
    ])
    daily = pd.DataFrame([
        {"date": "2024-01-02", "nominal_nav": 100.0, "liquidatable_nav": 100.0, "cash": 0.0, "invested_value": 100.0, "actual_exposure": 1.0},
        {"date": "2024-01-03", "nominal_nav": 101.0, "liquidatable_nav": 101.0, "cash": 0.0, "invested_value": 101.0, "actual_exposure": 1.0},
        {"date": "2024-01-04", "nominal_nav": 102.0, "liquidatable_nav": 102.0, "cash": 0.0, "invested_value": 102.0, "actual_exposure": 1.0},
    ])
    out = build_governance_attribution(
        daily_result=daily,
        feature_data=features,
        benchmark_symbol=None,
        benchmark_top_n=2,
        benchmark_rebalance="monthly",
    ).set_index("date")
    invalid = out.loc[pd.Timestamp("2024-01-03")]
    assert not bool(invalid["benchmark_return_valid"])
    assert pd.notna(invalid["benchmark_daily_return_display"])
    assert pd.isna(invalid["benchmark_daily_return"])
    assert pd.isna(invalid["excess_daily_return"])
    print("[PASS] incomplete benchmark day remains visible but is excluded from attribution")


if __name__ == "__main__":
    main()
