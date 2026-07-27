"""Focused mathematical checks for v3 post-entry failure evidence."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.position_lifecycle import _post_entry_failure_score


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    base = pd.DataFrame({
        "post_entry_failure_watch": [True, True],
        "position_unrealized_return": [-0.04, -0.04],
        "alpha_percentile": [0.30, 0.30],
        "alpha_quality_score": [0.40, 0.40],
        "position_entry_alpha_quality_score": [0.70, 0.70],
        "ret_5": [-0.03, -0.03],
        "ret_20": [-0.05, -0.05],
        "close_to_ma20": [-0.04, -0.04],
        "position_mfe": [0.0, 0.0],
        "position_mae": [-0.05, -0.05],
        "downtrend_decay_score": [0.8, 0.8],
        "entry_orderflow_confirm_count": [pd.NA, 0],
        "position_holding_days": [8, 8],
    })
    score = _post_entry_failure_score(base)
    check(score.between(0.0, 1.0).all(), "normalized post-entry score remains a bounded convex score")
    check(score.iloc[0] < score.iloc[1], "missing orderflow is neutral rather than identical to adverse orderflow")
    extreme = base.copy()
    extreme.loc[:, "position_unrealized_return"] = -1.0
    extreme.loc[:, "position_mae"] = -1.0
    check(_post_entry_failure_score(extreme).le(1.0).all(), "extreme evidence cannot exceed one after normalization")
    print("[PASS] v3 lifecycle mathematics verification completed")


if __name__ == "__main__":
    main()
