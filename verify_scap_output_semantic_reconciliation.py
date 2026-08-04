"""Output and execution semantics must share the production formulas."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from functions.decision_council.candidate_funnel_audit import (
    build_exposure_reconciliation,
)
from functions.decision_council.retail_execution import adapt_retail_buy_order


frame = pd.DataFrame(
    [
        {
            "date": "2025-01-02",
            "decision_id": "d",
            "policy_exposure_target": 0.75,
            "policy_exposure_lower": 0.60,
            "strategic_exposure_target": 0.75,
            "strategic_exposure_lower_bound": 0.60,
            "actual_exposure": 0.30,
            "post_mandatory_exposure": 0.15,
            "optimizer_planned_exposure": 0.60,
            "strategic_exposure_gap": 0.45,
            "exposure_gap": 0.30,
            "qualified_entry_count": 3,
        }
    ]
)
audit = build_exposure_reconciliation(frame)
row = audit.iloc[0]
assert abs(float(row["pretrade_policy_target_gap"]) - 0.45) < 1e-12
assert abs(float(row["pretrade_policy_lower_shortfall"]) - 0.30) < 1e-12
assert abs(float(row["post_mandatory_lower_shortfall"]) - 0.45) < 1e-12
assert abs(float(row["execution_to_plan_exposure_gap"]) - 0.30) < 1e-12
assert abs(float(row["target_gap_reconciliation_error"])) < 1e-12
assert abs(float(row["lower_gap_reconciliation_error"])) < 1e-12
print("[PASS] target and lower-bound exposure gaps reconcile independently")


class Runner(SimpleNamespace):
    def _retail_cash_required(self, *, side, price, shares):
        return float(price) * float(shares)


runner = Runner(
    capital_profile={
        "min_cash_buffer": 1_000.0,
        "retail_single_position_cap": 0.40,
        "retail_one_lot_position_cap": 0.40,
        "retail_target_exposure_tolerance": 0.10,
        "retail_min_entry_matrix_score": 0.0,
    },
    exposure_rows=[
        {
            "target_exposure": 0.60,
            "hard_exposure_ceiling": 0.90,
            "nominal_exposure": 0.60,
        }
    ],
    cash=8_000.0,
    capital_usage_mode="allow_cash",
    strategy_logic_version="mainline_v3",
)
order = {
    "symbol": "sz000001",
    "execution_date": pd.Timestamp("2025-01-03"),
    "position_state": "active",
    "action_plan_selected": True,
    "action_plan_id": "d|plan",
    "current_weight": 0.0,
}
shares, status, reason = adapt_retail_buy_order(
    runner,
    order=order,
    strategy_target_notional=4_000.0,
    order_price=20.0,
    nominal_nav=20_000.0,
    reserved_cash=0.0,
    initial_shares=100.0,
    one_lot_cash_required=2_000.0,
)
assert shares == 100.0 and status == "action_plan_unchanged" and not reason
print("[PASS] authorized ActionPlan is checked against the hard ceiling, not the soft target")

print("[PASS] SCAP output semantic reconciliation verification completed")
