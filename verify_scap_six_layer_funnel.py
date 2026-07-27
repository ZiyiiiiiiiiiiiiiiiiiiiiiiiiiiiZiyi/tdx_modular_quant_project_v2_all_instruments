"""Verify the SCAP candidate funnel is a strict subset chain."""
import pandas as pd

from functions.decision_council.candidate_funnel_audit import (
    assert_scap_funnel_monotonic,
)
from functions.decision_council.mainline_v3 import apply_mainline_v3_entry_policy


rows = []
for index, price in enumerate((10.0, 30.0, 60.0, 250.0)):
    rows.append(
        {
            "symbol": f"60000{index}",
            "close_nominal": price,
            "cabinet_native_final_score": 0.9 - index * 0.05,
            "risk_adjusted_primary_score": 0.9 - index * 0.05,
            "cabinet_base_entry_score": 0.8,
            "cabinet_timing_score": 0.8,
            "cabinet_liquidity_health_score": 0.8,
            "cabinet_risk_safety_score": 0.8,
            "cabinet_strict_entry_score_coverage": 1.0,
            "position_state": "flat",
        }
    )

result = apply_mainline_v3_entry_policy(
    pd.DataFrame(rows),
    ranking_score_column="risk_adjusted_primary_score",
    use_scap_candidate_utility=True,
    available_cash=8_000.0,
    nominal_nav=20_000.0,
    max_single_position_weight=0.40,
    max_new_candidates=2,
)
counts = {
    "scap_raw_signal_count": int(result["mainline_v3_raw_signal"].sum()),
    "scap_structural_feasible_count": int(
        result["mainline_v3_structural_feasible"].sum()
    ),
    "scap_cash_feasible_count": int(result["mainline_v3_cash_feasible"].sum()),
    "scap_slot_feasible_count": int(result["mainline_v3_slot_feasible"].sum()),
    "scap_optimizer_selected_count": int(result["scap_optimizer_selected"].sum()),
    "scap_registered_buy_count": int(result["scap_optimizer_selected"].sum()),
}
assert_scap_funnel_monotonic(counts)
assert counts["scap_raw_signal_count"] >= counts["scap_cash_feasible_count"]

bad = dict(counts)
bad["scap_optimizer_selected_count"] = bad["scap_slot_feasible_count"] + 1
try:
    assert_scap_funnel_monotonic(bad)
except RuntimeError:
    pass
else:
    raise AssertionError("non-monotonic funnel must fail")

print("[PASS] SCAP six-layer candidate funnel contract")
