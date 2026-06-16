"""Verify bounded V6 portfolio-level controls."""
from __future__ import annotations

import pandas as pd

from functions.v6_governance import (
    MLWeightState,
    calculate_capacity,
    continuous_market_discount,
    detect_liquidity_deterioration,
    update_ml_weight,
)
from functions.decision_council.allocation import allocate_constrained_inverse_vol


def main():
    calm = continuous_market_discount(
        volatility_percentile=0.2,
        market_breadth=0.5,
        index_trend=0.5,
        portfolio_drawdown=-0.01,
    )
    crisis = continuous_market_discount(
        volatility_percentile=0.99,
        market_breadth=-0.8,
        index_trend=-0.8,
        portfolio_drawdown=-0.15,
    )
    assert 0.5 <= crisis.market_discount <= calm.market_discount <= 1.0
    assert crisis.trading_freeze_flag and crisis.emergency_deleveraging_flag

    first = update_ml_weight(
        MLWeightState(),
        brier_improved=True,
        calibration_not_worse=True,
        ranking_improved=True,
        net_return_improved=True,
        risk_not_worse=True,
    )
    second = update_ml_weight(
        first,
        brier_improved=True,
        calibration_not_worse=True,
        ranking_improved=True,
        net_return_improved=True,
        risk_not_worse=True,
    )
    assert abs(first.weight - 0.10) < 1e-12
    assert abs(second.weight - 0.15) < 1e-12
    failed = update_ml_weight(
        second,
        brier_improved=False,
        calibration_not_worse=True,
        ranking_improved=True,
        net_return_improved=True,
        risk_not_worse=True,
    )
    assert failed.weight == 0.10 and failed.consecutive_passes == 0

    capacity = calculate_capacity(
        pd.DataFrame(
            [
                {"symbol": "sh600000", "order_value": 20_000, "adv20": 2_000_000},
                {"symbol": "sh600001", "order_value": 100_000, "adv20": 1_000_000},
            ]
        )
    )
    assert capacity["capacity_passed"].tolist() == [True, False]

    allocated, diagnostics = allocate_constrained_inverse_vol(
        pd.DataFrame(
            [
                {"symbol": "sh600000", "volatility_20": 0.02, "target_weight": 0.03},
                {"symbol": "sh600001", "volatility_20": 0.03, "target_weight": 0.02},
            ]
        ),
        exposure_cap=1.0,
    )
    assert abs(allocated["target_weight"].sum() - 0.05) < 1e-12
    assert abs(diagnostics["constraint_cash_reserve"]) < 1e-12

    dates = pd.bdate_range("2023-01-01", periods=70)
    liquidity = detect_liquidity_deterioration(
        pd.DataFrame(
            {
                "symbol": "sh600000",
                "date": dates,
                "adv20": [1_000_000.0] * 67 + [10_000.0] * 3,
                "amihud": [0.001] * 67 + [1.0] * 3,
            }
        )
    )
    assert bool(liquidity.iloc[-1]["liquidity_alert"])
    print("V6 governance verification passed.")


if __name__ == "__main__":
    main()
