from __future__ import annotations

import pandas as pd

from functions.decision_council.allocation import allocate_constrained_inverse_vol
from functions.decision_council.cabinet_thesis_audit import build_cabinet_thesis_counterfactual
from functions.decision_council.mainline_v2 import normalize_strategy_logic_version
from functions.decision_council.mainline_v3 import MAINLINE_V3, apply_mainline_v3_entry_policy
from functions.decision_council.retail_execution import adapt_retail_buy_order


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def _candidates() -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": ["A", "B", "C", "D"],
        "cabinet_native_final_score": [0.80, 0.70, 0.95, 0.60],
        "cabinet_base_entry_score": [0.75, 0.68, 0.90, 0.58],
        "cabinet_timing_score": [0.60, 0.55, 0.70, 0.45],
        "cabinet_liquidity_health_score": [0.70, 0.60, 0.80, 0.40],
        "cabinet_risk_safety_score": [0.90, 0.10, 0.50, 0.60],
        "cabinet_strict_entry_score_coverage": [1.0, 1.0, 1.0, 0.0],
        "entry_confirmed": [False, False, True, False],
        "entry_size_tier": ["blocked", "blocked", "blocked", "blocked"],
        "planned_entry_lots": [0, 0, 0, 0],
        "exit_state": [False, False, True, False],
        "position_state": ["watching", "blocked", "exiting", "watching"],
        "target_weight": [0.1, 0.1, 0.1, 0.1],
        "volatility_20": [0.02, 0.02, 0.02, 0.02],
        "close_nominal": [10.0, 10.0, 10.0, 10.0],
        "prototype_sector": ["x", "x", "x", "x"],
    })


def main() -> None:
    _check(normalize_strategy_logic_version(MAINLINE_V3) == MAINLINE_V3, "v3 strategy version is registered")
    result = apply_mainline_v3_entry_policy(_candidates(), max_new_candidates=2)
    confirmed = set(result.loc[result["entry_confirmed"], "symbol"])
    _check(confirmed == {"A", "B"}, "v3 selects by cabinet score after factual state/coverage vetoes")
    selected = result[result["entry_confirmed"]]
    _check(selected["entry_size_tier"].eq("starter_1_lot").all(), "v3 replaces legacy blocked tiers with deterministic one-lot entries")
    _check(pd.to_numeric(selected["planned_entry_lots"], errors="coerce").eq(1).all(), "v3 selected entries plan exactly one lot")
    _check(result.loc[result["symbol"].eq("B"), "position_state"].iloc[0] == "building", "v3 can re-evaluate a legacy entry-matrix block")
    _check(result["state_machine_role_pass"].sum() == 3, "legacy role diversity is not a duplicate hard gate")
    _check(result.loc[result["symbol"].eq("C"), "entry_block_reason"].iloc[0] == "mainline_v3_position_state", "position hard block remains active")
    _check(result.loc[result["symbol"].eq("D"), "entry_block_reason"].iloc[0] == "mainline_v3_strict_entry_unavailable", "missing strict entry fails closed")

    allocated, _ = allocate_constrained_inverse_vol(
        result[result["symbol"].isin(["A", "B"])], exposure_cap=0.4, max_position_weight=0.4
    )
    weights = allocated.set_index("symbol")["target_weight"]
    _check(weights["A"] > weights["B"], "risk role changes position preference without deleting candidates")

    states = pd.DataFrame({
        "date": ["2024-01-02"], "symbol": ["A"],
        "paper_exit_reason": ["post_entry_failure_exit"], "entry_thesis": ["value"],
    })
    features = pd.DataFrame({
        "date": pd.date_range("2024-01-02", periods=22, freq="B"),
        "symbol": ["A"] * 22,
        "close_nominal": [10.0 + i * 0.1 for i in range(22)],
    })
    counterfactual = build_cabinet_thesis_counterfactual(states, features)
    _check(len(counterfactual) == 1, "paper lifecycle exit produces one counterfactual row")
    _check(counterfactual["counterfactual_return_20d"].notna().all(), "counterfactual horizons use future trading observations")

    class _RetailRunner:
        strategy_logic_version = MAINLINE_V3
        capital_usage_mode = "allow_cash"
        cash = 20_000.0
        exposure_rows = [{"target_exposure": 1.0, "nominal_exposure": 0.0}]
        capital_profile = {
            "min_cash_buffer": 1_000.0,
            "retail_single_position_cap": 0.40,
            "retail_one_lot_position_cap": 0.40,
            "retail_min_entry_matrix_score": 0.0,
        }

        @staticmethod
        def _retail_cash_required(*, side, price, shares):
            return float(price) * float(shares) * 1.002

    shares, action, reason = adapt_retail_buy_order(
        _RetailRunner(),
        order={
            "position_state": "building",
            "exit_state": False,
            "current_weight": 0.0,
            "entry_matrix_score": 0.70,
            "entry_size_tier": "starter_1_lot",
            "planned_entry_lots": 1,
            "exhaustion_score": 1.0,
            "downtrend_decay_score": 1.0,
        },
        strategy_target_notional=500.0,
        order_price=10.0,
        nominal_nav=20_000.0,
        reserved_cash=0.0,
        initial_shares=0.0,
        one_lot_cash_required=1_002.0,
    )
    _check(shares == 100.0 and not reason, "v3 retail execution does not reapply legacy soft vetoes")
    _check(action == "upgraded_to_one_lot", "v3 retail execution preserves deterministic one-lot sizing")
    print("Governance mainline v3 smoke complete.")


if __name__ == "__main__":
    main()
