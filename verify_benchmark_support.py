# -*- coding: utf-8 -*-
"""Verify investable benchmark support in exploratory backtests."""
from __future__ import annotations

import pandas as pd

from functions.backtest_engine import run_backtest
from functions.benchmark import build_benchmark_return_frame, build_investable_benchmark_report


def verify_benchmark_support():
    print("=== Verify benchmark support ===")
    feature_data = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2021-01-29",
                    "2021-02-01",
                    "2021-02-02",
                    "2021-01-29",
                    "2021-02-01",
                    "2021-02-02",
                ]
            ),
            "symbol": ["sh510300", "sh510300", "sh510300", "sh600000", "sh600000", "sh600000"],
            "instrument_type": ["etf_fund", "etf_fund", "etf_fund", "stock", "stock", "stock"],
            "close": [5.0, 5.1, 5.2, 10.0, 10.2, 10.4],
            "close_nominal": [5.0, 5.1, 5.2, 10.0, 10.2, 10.4],
            "open": [5.0, 5.1, 5.2, 10.0, 10.2, 10.4],
            "open_nominal": [5.0, 5.1, 5.2, 10.0, 10.2, 10.4],
            "is_trading": [True] * 6,
            "abnormal_jump": [False] * 6,
            "rough_limit_up": [False] * 6,
            "rough_limit_down": [False] * 6,
            "future_ret_5": [0.02, 0.03, 0.04, 0.05, 0.04, 0.03],
        }
    )
    bench_frame, meta = build_benchmark_return_frame(feature_data)
    _expect(not bench_frame.empty, "benchmark frame should be built from ETF rows")
    _expect(meta["benchmark_symbol"] == "sh510300", "benchmark symbol should resolve to sh510300")

    report = build_investable_benchmark_report()
    _expect("benchmark_id" in report.columns, "benchmark report should expose benchmark_id")

    selection = pd.DataFrame(
        {
            "rebalance_date": pd.to_datetime(["2021-01-29"]),
            "symbol": ["sh600000"],
            "weight": [1.0],
            "strategy_source": ["rule"],
            "weighting_mode": ["equal_weight"],
            "price_basis": ["nominal_unadjusted"],
            "neutralization_mode": ["winsor_only"],
            "ml_runtime_mode": ["not_applicable"],
            "date_window": ["2021-01-01 -> 2021-12-31"],
            "degradation_flags": [""],
        }
    )
    from functions import backtest_engine as engine_module

    original_cache = engine_module._FEATURE_DATA_CACHE
    try:
        engine_module._FEATURE_DATA_CACHE = feature_data.copy()
        daily_result, metrics, _ = run_backtest(
            selection,
            initial_cash=1.0,
            risk_free_rate=0.0,
            strategy_name="benchmark_smoke",
            show_plot=False,
            compute_theoretical_upper_bound=False,
            start_date="2021-01-01",
            end_date="2021-12-31",
        )
    finally:
        engine_module._FEATURE_DATA_CACHE = original_cache

    metric_map = dict(zip(metrics["metric"], metrics["value"]))
    _expect(
        str(metric_map.get("benchmark_status", "")).startswith("available: hs300_etf"),
        "benchmark status should be available",
    )
    _expect(pd.notna(pd.to_numeric(metric_map.get("benchmark_excess_return"), errors="coerce")), "benchmark excess return should be numeric")
    _expect(
        "benchmark_unavailable" not in str(daily_result["degradation_flags"].iloc[0]),
        "degradation flags should not force benchmark_unavailable when ETF benchmark exists",
    )
    print("Benchmark support verification passed.")


def _expect(condition, message):
    if not condition:
        raise SystemExit(message)
    print(f"[PASS] {message}")


if __name__ == "__main__":
    verify_benchmark_support()
