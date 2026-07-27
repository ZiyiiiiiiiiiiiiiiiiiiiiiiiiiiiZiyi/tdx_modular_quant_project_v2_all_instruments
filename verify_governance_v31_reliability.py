"""Product and bug checks for rolling continuous v3.1 role reliability."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.mainline_v3 import apply_mainline_v3_entry_policy
from functions.decision_council.reliability_weighted_scoring import (
    MAINLINE_V31_RELIABILITY,
    ROLE_COLUMNS,
    RollingRoleReliabilityController,
    attach_reliability_weighted_score,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def fixture(date=None):
    rows = []
    for index in range(8):
        row = {
            "date": date, "symbol": f"S{index}", "close": 10.0 + index,
            "cabinet_native_final_score": .9 - index * .08,
            "cabinet_entry_score_coverage": 1.0,
            "cabinet_base_entry_score": .8 - index * .08,
            "entry_confirmed": False, "position_state": "watching", "exit_state": False,
        }
        for role_index, column in enumerate(ROLE_COLUMNS):
            row[column] = np.clip(.1 + index * .11 if role_index == 0 else .85 - index * .07, 0, 1)
            row[f"{column}_coverage"] = 1.0
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    source = fixture("2024-01-02")
    before = source.copy(deep=True)
    weights = {column: (0.50 if column == "cabinet_strict_entry_score" else 0.10) for column in ROLE_COLUMNS}
    scored = attach_reliability_weighted_score(
        source, as_of_date="2024-02-01", role_weights=weights,
        reliability_blend=0.60, reliability_status="test_active", calibration_window="test",
    )
    changed_strict = source.copy()
    changed_strict["cabinet_strict_entry_score"] = list(reversed(changed_strict["cabinet_strict_entry_score"].tolist()))
    changed = attach_reliability_weighted_score(
        changed_strict, as_of_date="2024-02-01", role_weights=weights,
        reliability_blend=0.60, reliability_status="test_active", calibration_window="test",
    )
    check(not changed["v31_reliability_score"].equals(scored["v31_reliability_score"]), "strict evidence keeps continuous ranking authority")
    check(source.equals(before), "reliability scorer does not mutate candidates")
    fallback = attach_reliability_weighted_score(source, as_of_date="2021-01-04")
    check(fallback["v31_reliability_score"].equals(source["cabinet_native_final_score"]), "insufficient evidence falls back exactly to Cabinet Native")
    check(fallback["v31_temporal_status"].eq("fallback_insufficient_matured_history").all(), "fallback status is explicit")
    check(all(scored[f"v31_authority__{column.removeprefix('cabinet_').removesuffix('_score')}"] .gt(0).all() for column in ROLE_COLUMNS), "no semantic role is permanently deprived of ranking authority")

    dates = pd.bdate_range("2023-11-01", periods=75)
    prices = []
    for day_index, date in enumerate(dates):
        prices.append({"date": date, "symbol": "BENCH", "open": 100.0, "close": 100.0})
        for symbol_index in range(8):
            growth = 1.0 + symbol_index * 0.0008
            close = (10.0 + symbol_index) * growth ** day_index
            prices.append({"date": date, "symbol": f"S{symbol_index}", "open": close, "close": close})
    prices = pd.DataFrame(prices)
    controller = RollingRoleReliabilityController(
        benchmark_symbol="BENCH", horizon_days=5, minimum_dates=20,
        rolling_dates=60, round_trip_cost_rate=0.001,
    )
    latest = None
    for date in dates:
        latest = controller.process_day(fixture(date), as_of_date=date, price_history=prices)
    audit = controller.audit_frame()
    check(not audit.empty and audit["matured_dates"].max() >= 20, "rolling estimator accumulates only matured date panels")
    check(
        {"reliability_blend", "calibration_window", "status"}.issubset(audit.columns),
        "cold-start and active reliability states share one Web/audit schema",
    )
    check(controller.status == "rolling_matured_reliability_active", "positive rolling evidence activates continuous reliability")
    check(0.0 < controller.reliability_blend < 1.0, "finite evidence is shrunk rather than granted binary authority")
    check(all(weight > 0.0 for weight in controller.role_weights.values()), "rolling soft weights retain every role")

    selected = apply_mainline_v3_entry_policy(
        latest, max_new_candidates=2, available_cash=20_000, nominal_nav=20_000,
        max_single_position_weight=.5, strategy_logic_version=MAINLINE_V31_RELIABILITY,
        ranking_score_column="v31_reliability_score",
        ranking_coverage_column="v31_reliability_score_coverage",
    )
    check(selected[selected["entry_confirmed"]]["planned_entry_lots"].eq(1).all(), "v3.1 retains deterministic one-lot entries")
    print("[PASS] v3.1 rolling reliability product verification completed")


if __name__ == "__main__":
    main()
