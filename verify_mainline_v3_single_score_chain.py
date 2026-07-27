"""Verify lifecycle compatibility and selection share one V3 score authority."""
import pandas as pd

from functions.decision_council.mainline_v3 import apply_mainline_v3_entry_policy


base = pd.DataFrame(
    [
        {
            "symbol": "600001",
            "close_nominal": 10.0,
            "cabinet_native_final_score": 0.90,
            "risk_adjusted_primary_score": 0.70,
            "cabinet_base_entry_score": 0.80,
            "cabinet_timing_score": 0.70,
            "cabinet_liquidity_health_score": 0.80,
            "cabinet_risk_safety_score": 0.80,
            "cabinet_strict_entry_score_coverage": 1.0,
            "entry_confirmed": True,
            "position_state": "blocked",
        },
        {
            "symbol": "600002",
            "close_nominal": 12.0,
            "cabinet_native_final_score": 0.80,
            "risk_adjusted_primary_score": 0.75,
            "cabinet_base_entry_score": 0.75,
            "cabinet_timing_score": 0.75,
            "cabinet_liquidity_health_score": 0.75,
            "cabinet_risk_safety_score": 0.75,
            "cabinet_strict_entry_score_coverage": 1.0,
            "entry_confirmed": False,
            "position_state": "blocked",
        },
    ]
)

compatibility = apply_mainline_v3_entry_policy(
    base,
    ranking_score_column="risk_adjusted_primary_score",
    selection_enabled=False,
    available_cash=20_000.0,
    nominal_nav=20_000.0,
)
assert compatibility["entry_confirmed"].tolist() == [False, True]
# Sorting changed row order, but legacy flags themselves were not overwritten.
assert dict(zip(compatibility["symbol"], compatibility["entry_confirmed"])) == {
    "600001": True,
    "600002": False,
}
assert not compatibility["mainline_v3_selection_evaluated"].any()
assert compatibility["mainline_v3_score_authority"].eq(
    "risk_adjusted_primary_score"
).all()
assert (
    compatibility["entry_matrix_score"]
    == compatibility["risk_adjusted_primary_score"]
).all()

selected = apply_mainline_v3_entry_policy(
    compatibility,
    ranking_score_column="risk_adjusted_primary_score",
    selection_enabled=True,
    max_new_candidates=1,
    available_cash=20_000.0,
    nominal_nav=20_000.0,
)
assert selected["mainline_v3_selection_evaluated"].all()
assert selected.loc[selected["entry_confirmed"], "symbol"].tolist() == ["600002"]
assert selected["mainline_v3_score_authority"].nunique() == 1
print("[PASS] mainline V3 single final score and single optimizer contract")
