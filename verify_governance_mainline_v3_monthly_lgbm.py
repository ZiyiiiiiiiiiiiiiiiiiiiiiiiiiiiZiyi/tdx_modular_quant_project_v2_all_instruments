"""State-machine product checks for monthly-LightGBM governance v3."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.mainline_v2 import (
    MAINLINE_V3_MONTHLY_LGBM_HYBRID,
    is_mainline_v3_version,
    normalize_strategy_logic_version,
)
from functions.decision_council.mainline_v3 import apply_mainline_v3_entry_policy
from functions.decision_council.monthly_lgbm_hybrid import (
    FusionCalibration,
    apply_continuous_rank_fusion,
)
from functions.decision_council.pending_orders import PENDING_ORDER_COLUMNS, PendingOrderBook
from functions.decision_council.policy import ORDER_COLUMNS


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def candidates() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": pd.Timestamp("2024-01-05"),
            "symbol": ["RULE", "ML", "EXIT", "EXPENSIVE"],
            "close": [10.0, 10.0, 10.0, 1000.0],
            "cabinet_native_final_score": [0.90, 0.60, 0.80, 0.70],
            "monthly_lgbm_raw_score": [0.10, 0.95, 0.70, 0.60],
            "cabinet_base_entry_score": [0.85, 0.60, 0.75, 0.65],
            "cabinet_timing_score": [0.50, 0.70, 0.60, 0.50],
            "cabinet_liquidity_health_score": [0.70, 0.70, 0.70, 0.70],
            "cabinet_risk_safety_score": [0.60, 0.60, 0.60, 0.60],
            "cabinet_strict_entry_score_coverage": [1.0, 1.0, 1.0, 1.0],
            "entry_confirmed": [True, False, True, True],
            "exit_state": [False, False, True, False],
            "position_state": ["watching", "watching", "exiting", "watching"],
        }
    )
    return frame


def main() -> None:
    version = normalize_strategy_logic_version(MAINLINE_V3_MONTHLY_LGBM_HYBRID)
    check(version == MAINLINE_V3_MONTHLY_LGBM_HYBRID, "monthly LightGBM line is a registered strategy version")
    check(is_mainline_v3_version(version), "hybrid version inherits the cabinet-native v3 state-machine family")
    calibration = FusionCalibration(
        ml_weight=0.40,
        unconstrained_weight=0.50,
        reliability=0.80,
        maximum_ml_weight=0.40,
        validation_rank_ic_mean=0.08,
        validation_rank_ic_standard_error=0.02,
        status="active",
    )
    fused = apply_continuous_rank_fusion(candidates(), calibration)
    governed = apply_mainline_v3_entry_policy(
        fused,
        max_new_candidates=2,
        available_cash=20000.0,
        nominal_nav=20000.0,
        max_single_position_weight=0.60,
        strategy_logic_version=version,
        ranking_score_column="hybrid_final_score",
    )
    check(governed["strategy_logic_version"].eq(version).all(), "hybrid version survives v3 policy application")
    check(np.allclose(governed["final_entry_score"], governed["hybrid_final_score"]), "state machine ranks entries by hybrid score")
    check(not governed.set_index("symbol").at["EXIT", "entry_confirmed"], "ML cannot bypass an exiting-position hard block")
    check(not governed.set_index("symbol").at["EXPENSIVE", "entry_confirmed"], "ML cannot bypass one-lot feasibility")
    selected = governed[governed["entry_confirmed"]]
    check(selected["planned_entry_lots"].eq(1).all(), "hybrid v3 new entries remain fixed at one lot")
    hybrid_columns = {
        "monthly_lgbm_raw_score", "monthly_lgbm_rank_percentile", "hybrid_final_score",
        "hybrid_ml_weight", "hybrid_fusion_status",
    }
    check(hybrid_columns.issubset(ORDER_COLUMNS), "policy order metadata preserves hybrid audit fields")
    check(hybrid_columns.issubset(PENDING_ORDER_COLUMNS), "pending-order ledger preserves hybrid audit fields")
    payload = {column: governed.iloc[0].get(column, pd.NA) for column in PENDING_ORDER_COLUMNS}
    payload.update(
        decision_id="test", symbol="RULE", side="buy", reason="test", priority=1,
        created_date=pd.Timestamp("2024-01-05"), target_shares=100,
    )
    book = PendingOrderBook()
    book.add_order(payload)
    check(book.orders.iloc[0]["strategy_logic_version"] == version, "pending-order round trip retains hybrid logic version")
    check(pd.notna(book.orders.iloc[0]["hybrid_final_score"]), "pending-order round trip retains hybrid score")
    print("[PASS] monthly LightGBM v3 state-machine product verification completed")


if __name__ == "__main__":
    main()
