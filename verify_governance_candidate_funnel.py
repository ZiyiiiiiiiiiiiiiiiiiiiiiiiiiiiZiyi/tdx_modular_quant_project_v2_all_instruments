"""Standalone checks for governance candidate funnel audit outputs."""
from __future__ import annotations

import sys

import pandas as pd

from functions.decision_council.candidate_funnel_audit import (
    build_candidate_rejection_detail,
    build_control_opportunity_cost,
    build_exposure_reconciliation,
    reconcile_funnel_daily,
    summarize_funnel,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        print(f"[FAIL] {message}")
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    entry = pd.DataFrame(
        [
            {"date": "2024-01-02", "symbol": "A", "entry_confirmed": False,
             "entry_block_reason": "weak", "state_machine_role_pass": True,
             "retail_executable": True, "forward_return_5d": 0.10,
             "forward_return_10d": 0.20, "forward_return_20d": -0.10},
            {"date": "2024-01-02", "symbol": "B", "entry_confirmed": True,
             "state_machine_role_pass": True, "retail_executable": False,
             "retail_block_reason": "cash", "forward_return_5d": -0.10,
             "forward_return_10d": -0.20, "forward_return_20d": 0.10},
        ]
    )
    rejection = build_candidate_rejection_detail(entry)
    check(set(rejection["first_block_stage"]) == {"entry_confirmation", "capital"}, "terminal stages are mutually classified")
    check(rejection["decision_id"].eq("gov_20240102").all(), "decision_id is backfilled deterministically")
    opportunity = build_control_opportunity_cost(rejection)
    check(set(opportunity["control_stage"]) == {"entry_confirmation", "capital"}, "opportunity cost covers rejection stages")

    runtime = pd.DataFrame([{"date": "2024-01-02", "decision_id": "gov_20240102", "universe_count": 100,
                             "proposal_symbol_count": 80, "factor_valid_count": 70, "capital_pass_count": 2}])
    ideal = pd.DataFrame([{"decision_id": "gov_20240102", "symbol": "B"}])
    orders = pd.DataFrame([{"decision_id": "gov_20240102", "symbol": "B", "side": "buy"}])
    executions = pd.DataFrame([{"decision_id": "gov_20240102", "symbol": "B", "side": "buy", "execution_status": "filled"}])
    daily = reconcile_funnel_daily(runtime, ideal_plan=ideal, order_plan=orders, execution_ledger=executions)
    check(int(daily.loc[0, "executed_buy_count"]) == 1, "execution is joined by decision_id")
    check(not summarize_funnel(daily).empty, "funnel summary is generated")

    exposure = build_exposure_reconciliation(pd.DataFrame([
        {"date": "2024-01-02", "decision_id": "gov_20240102", "target_exposure": 0.3,
         "actual_exposure": 0.1, "exposure_gap": 0.2}
    ]))
    check(abs(float(exposure.loc[0, "reconciliation_error"])) < 1e-12, "exposure identity reconciles")
    check("qualified_entry_count" in exposure.columns, "missing optional exposure columns degrade safely")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        sys.exit(1)
