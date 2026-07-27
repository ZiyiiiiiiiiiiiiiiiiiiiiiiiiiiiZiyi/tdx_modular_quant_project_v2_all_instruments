"""Product verification for separate short-entry and medium-hold ML objectives."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.monthly_lgbm_hybrid import (
    OnlineMonthlyLGBMController,
    fit_monthly_lgbm_ranker,
    predict_daily_rank,
)
from functions.decision_council.multi_horizon_value import attach_multi_horizon_value_contract


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main():
    rng = np.random.default_rng(20260720)
    dates = pd.bdate_range("2023-01-02", periods=100)
    rows = []
    for date_index, date in enumerate(dates):
        for symbol_index in range(20):
            short = rng.normal()
            hold = rng.normal()
            rows.append({
                "date": date, "symbol": f"S{symbol_index:02d}",
                "short_signal": short, "hold_signal": hold,
                "label_maturity_date": dates[min(date_index + 20, len(dates) - 1)],
                "future_excess_log_return_net": 0.01 * short + 0.025 * hold + rng.normal(0, 0.01),
            })
    frame = pd.DataFrame(rows)
    artifact = fit_monthly_lgbm_ranker(
        frame, feature_columns=("short_signal", "hold_signal"),
        as_of_date=dates[-1], horizon_days=20, validation_date_count=15,
        model_params={"n_estimators": 40},
    )
    daily = frame[frame["date"].eq(dates[-1])]
    scored = predict_daily_rank(artifact, daily)
    valued = attach_multi_horizon_value_contract(scored)
    check(scored["expected_edge_20d"].notna().all(), "medium model emits calibrated 20-day expected alpha")
    check(scored["conservative_expected_edge_20d"].notna().all(), "medium model emits a same-horizon conservative bound")
    check(valued["comparable_value_horizon_days"].eq(20).all(), "replacement contract consumes the medium forecast without mixing score units")

    base = pd.DataFrame({
        "cabinet_hold_support_score": [0.5],
        "cabinet_strict_entry_score": [0.5],
    })
    short_controller = OnlineMonthlyLGBMController(
        maximum_ml_weight=.2, benchmark_symbol="B", horizon_days=5,
        validation_date_count=10, minimum_training_date_count=40,
        round_trip_cost_rate=.002, include_hold_support=False,
    )
    medium_controller = OnlineMonthlyLGBMController(
        maximum_ml_weight=.2, benchmark_symbol="B", horizon_days=20,
        validation_date_count=10, minimum_training_date_count=40,
        round_trip_cost_rate=.002, include_hold_support=True,
    )
    check("cabinet_hold_support_score" not in short_controller._available_feature_columns(base), "hold-only evidence cannot contaminate the entry model")
    check("cabinet_hold_support_score" in medium_controller._available_feature_columns(base), "hold evidence is reserved for the medium-horizon model")
    print("[PASS] dual-horizon LightGBM product verification completed")


if __name__ == "__main__":
    main()
