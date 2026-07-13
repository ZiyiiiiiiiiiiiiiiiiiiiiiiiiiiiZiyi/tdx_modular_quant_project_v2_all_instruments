"""Contract checks for the isolated governance mainline v2 policy."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.allocation import allocate_constrained_inverse_vol
from functions.decision_council.candidate_funnel_audit import build_control_trigger_summary
from functions.decision_council.mainline_v2 import (
    MAINLINE_V2,
    PRODUCTION_V1,
    apply_mainline_v2_entry_policy,
    calibration_runtime_state,
    normalize_strategy_logic_version,
)
from functions.decision_council.runner import POSITION_STATE_LEDGER_COLUMNS


def main() -> int:
    assert normalize_strategy_logic_version(None) == PRODUCTION_V1
    assert normalize_strategy_logic_version(MAINLINE_V2) == MAINLINE_V2
    candidates = pd.DataFrame([
        {"symbol": f"s{i}", "state_machine_role_pass": True, "entry_liquidity_score": 0.8,
         "entry_matrix_score": 0.5, "final_entry_score": 1.0 - i / 10,
         "entry_confirmed": False, "exit_state": False, "position_state": "eligible",
         "target_weight": 1e-8}
        for i in range(8)
    ])
    result = apply_mainline_v2_entry_policy(candidates, risk_level="normal", max_new_candidates=5)
    assert int(result["entry_confirmed"].sum()) == 5
    assert result.loc[result["entry_confirmed"], "entry_block_reason"].eq("confirmed").all()
    assert result["target_weight"].eq(0.0).all()
    assert result["production_v1_target_weight"].eq(1e-8).all()
    assert calibration_runtime_state(matured_sample_count=0, day_index=0) == "cold_start"
    assert calibration_runtime_state(matured_sample_count=40, day_index=20) == "warming_up"
    assert calibration_runtime_state(matured_sample_count=80, day_index=20) == "calibrated"
    assert calibration_runtime_state(matured_sample_count=80, day_index=20, degraded=True) == "degraded"
    assert {
        "entry_thesis", "entry_module_support", "current_module_support",
        "support_decay", "thesis_failure_exit", "paper_thesis_failure_exit",
    }.issubset(POSITION_STATE_LEDGER_COLUMNS)
    selected = result[result["entry_confirmed"]].copy()
    selected["volatility_20"] = 0.02
    allocated, _ = allocate_constrained_inverse_vol(selected, exposure_cap=0.50, covariance_matrix=None)
    assert float(allocated["target_weight"].sum()) > 0.39
    assert float(allocated["target_weight"].min()) >= 0.05
    gates = result.assign(
        strategy_logic_version=MAINLINE_V2,
        probability_gate_evaluated=True,
        probability_gate_changed_decision=True,
    )
    triggers = build_control_trigger_summary(gates, order_plan=pd.DataFrame(), execution_ledger=pd.DataFrame())
    probability = triggers.loc[triggers["control"].eq("probability_gate")].iloc[0]
    assert int(probability["paper_trigger_count"]) == len(gates)
    assert int(probability["active_trigger_count"]) == 0
    blocked = apply_mainline_v2_entry_policy(candidates, risk_level="crisis", max_new_candidates=5)
    assert not blocked["entry_confirmed"].any()
    role_missing = candidates.iloc[[0]].copy()
    role_missing["state_machine_role_pass"] = False
    continuous = apply_mainline_v2_entry_policy(role_missing, risk_level="normal", max_new_candidates=1)
    assert bool(continuous.iloc[0]["entry_confirmed"]), "role evidence must not duplicate the V2 hard gate"
    print("[PASS] mainline_v2 is versioned, ranked, capped, and preserves hard market veto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
