from __future__ import annotations

import pandas as pd

from functions.decision_council.analytics import (
    build_top_pool_benchmark_sensitivity,
    build_top_pool_benchmark_series,
)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    rows = [
        {"date": "2024-01-30", "symbol": "A", "close": 100.0, "amount_ma20": 300.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-01-30", "symbol": "B", "close": 100.0, "amount_ma20": 200.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-01-30", "symbol": "C", "close": 100.0, "amount_ma20": 100.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-01-31", "symbol": "A", "close": 110.0, "amount_ma20": 300.0, "instrument_type": "stock", "is_trading": True},
        # B is deliberately missing on T+1. It must not be removed from the T selection.
        {"date": "2024-01-31", "symbol": "C", "close": 80.0, "amount_ma20": 400.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-02-01", "symbol": "A", "close": 121.0, "amount_ma20": 300.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-02-01", "symbol": "B", "close": 100.0, "amount_ma20": 200.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-02-01", "symbol": "C", "close": 88.0, "amount_ma20": 400.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-02-02", "symbol": "A", "close": 121.0, "amount_ma20": 300.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-02-02", "symbol": "B", "close": 100.0, "amount_ma20": 200.0, "instrument_type": "stock", "is_trading": True},
        {"date": "2024-02-02", "symbol": "C", "close": 96.8, "amount_ma20": 400.0, "instrument_type": "stock", "is_trading": True},
    ]
    out = build_top_pool_benchmark_series(pd.DataFrame(rows), top_n=2, rebalance="monthly").set_index("date")
    jan31 = out.loc[pd.Timestamp("2024-01-31")]
    expect(abs(float(jan31["benchmark_gross_daily_return"]) - 0.05) < 1e-12,
           "missing next-day price stays in the prior-day selected pool without ex-post removal")
    expect(float(jan31["benchmark_daily_return"]) < float(jan31["benchmark_gross_daily_return"]),
           "the primary benchmark deducts its own rebalance cost")
    expect(not bool(jan31["benchmark_return_valid"]),
           "missing constituent prices invalidate rather than silently certify the benchmark return")
    expect(int(jan31["benchmark_member_count"]) == 2 and abs(float(jan31["benchmark_return_coverage"]) - 0.5) < 1e-12,
           "member count is fixed while observed-return coverage is audited separately")
    feb1 = out.loc[pd.Timestamp("2024-02-01")]
    expect(bool(feb1["benchmark_rebalanced"]), "month boundary rebalances using the prior session information")
    expect(str(feb1["benchmark_id"]) == "top_liquidity_2_equal_weight_monthly",
           "benchmark identity discloses fixed cardinality, weighting and cadence")
    feb2 = out.loc[pd.Timestamp("2024-02-02")]
    expect(not bool(feb2["benchmark_rebalanced"]), "benchmark does not silently equal-weight every day")
    expect(abs(float(feb2["benchmark_gross_daily_return"]) - 0.05) < 1e-12,
           "between rebalances portfolio weights drift with constituent returns")
    sensitivity = build_top_pool_benchmark_sensitivity(
        pd.DataFrame(rows), top_n_values=(1, 2, 3), rebalance="monthly"
    )
    expect(
        sensitivity["top_n"].tolist() == [1, 2, 3]
        and sensitivity["selection_policy"].eq("pre_registered_only_do_not_choose_best_ex_post").all(),
        "N sensitivity is reported without ex-post benchmark selection",
    )
    print("[PASS] fixed top-pool benchmark verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
