"""Verify profit objective is yuan-denominated and audit-only."""
import pandas as pd

from functions.decision_council.scap_profit_objective import (
    build_scap_profit_objective_audit,
    summarize_scap_profit_objective,
)


source = pd.DataFrame(
    [
        {
            "decision_id": "d1",
            "date": "2025-01-02",
            "symbol": "600001",
            "one_lot_cash_required": 1000.0,
            "forward_return_20d": 0.10,
            "scap_estimated_round_trip_cost_rate": 0.01,
            "scap_optimizer_selected": True,
            "scap_candidate_utility": 0.8,
            "primary_score": 0.7,
        },
        {
            "decision_id": "d1",
            "date": "2025-01-02",
            "symbol": "600002",
            "one_lot_cash_required": 2000.0,
            "forward_return_20d": -0.02,
            "scap_estimated_round_trip_cost_rate": 0.01,
            "scap_optimizer_selected": False,
            "scap_candidate_utility": 0.4,
            "primary_score": 0.6,
        },
    ]
)
audit = build_scap_profit_objective_audit(source)
assert abs(float(audit.iloc[0]["scap_realized_net_profit_yuan_20d_audit"]) - 90.0) < 1e-12
assert abs(float(audit.iloc[1]["scap_realized_net_profit_yuan_20d_audit"]) + 60.0) < 1e-12
assert audit["scap_profit_objective_runtime_authority"].str.startswith("audit_only").all()
summary = summarize_scap_profit_objective(audit)
assert not summary["runtime_activation_eligible"].any()
assert summary.loc[summary["cohort"].eq("optimizer_selected"), "sample_count"].iloc[0] == 1
print("[PASS] SCAP 20-day net-yuan profit objective remains audit-only")
