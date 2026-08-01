"""Dynamic position-cap fields must remain valid through quality-report save logic."""

import numpy as np
import pandas as pd

from functions.decision_council.quality_reports import build_portfolio_constraint_report


base = {
    "date": pd.Timestamp("2026-07-31"),
    "configured_max_positions": np.nan,
    "user_hard_position_cap": np.nan,
    "economic_position_cap": 6,
    "search_position_cap": 12,
    "effective_position_cap": 6,
    "holding_count": 5,
    "account_effective_n": 4.5,
    "sleeve_effective_n": 4.5,
    "sleeve_effective_n_ratio": 0.9,
    "top1_account_weight": 0.2,
    "top5_account_weight_sum": 0.8,
    "top20pct_sleeve_weight_sum": 0.2,
    "actual_exposure": 0.8,
}

valid = build_portfolio_constraint_report(pd.DataFrame([base]))
assert len(valid) == 1
assert pd.isna(valid.loc[0, "configured_max_positions"])
assert pd.isna(valid.loc[0, "user_hard_position_cap"])
assert valid.loc[0, "effective_position_cap"] == 6
assert bool(valid.loc[0, "position_limit_pass"])

invalid = build_portfolio_constraint_report(
    pd.DataFrame([{**base, "holding_count": 7, "sleeve_effective_n": 7.0}])
)
assert not bool(invalid.loc[0, "position_limit_pass"])
assert "holding_count_above_daily_effective_cap" in invalid.loc[0, "fail_reasons"]

print("[PASS] dynamic position cap quality-report contract")
