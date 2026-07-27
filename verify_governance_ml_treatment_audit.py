"""Product verification for synchronized Cabinet Native versus ML treatment audit."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.ml_treatment_audit import (
    attach_rank_treatment,
    daily_treatment_summary,
    mature_treatment_effect,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    date = pd.Timestamp("2024-01-02")
    candidates = pd.DataFrame({
        "date": date,
        "symbol": ["A", "B", "C", "D"],
        "cabinet_native_final_score": [0.9, 0.8, 0.7, 0.6],
        "hybrid_final_score": [0.9, 0.6, 0.95, 0.7],
    })
    treated = attach_rank_treatment(candidates, top_k=2)
    groups = treated.set_index("symbol")["ml_treatment_group"]
    check(groups["C"] == "promoted_into_top_k", "ML promotion into executable Top-K is identified")
    check(groups["B"] == "demoted_out_of_top_k", "Cabinet candidate displaced by ML is identified")
    summary = daily_treatment_summary(treated, top_k=2).iloc[0]
    check(summary["top_k_overlap_count"] == 1 and bool(summary["ml_changed_top_k"]), "daily audit measures an actual shortlist change")

    labels = pd.DataFrame({
        "date": date,
        "symbol": ["A", "B", "C", "D"],
        "future_excess_log_return_net": [0.01, -0.02, 0.04, 0.00],
        "label_maturity_date": pd.Timestamp("2024-01-09"),
    })
    effect = mature_treatment_effect(treated, labels).iloc[0]
    expected = np.mean([0.01, 0.04]) - np.mean([0.01, -0.02])
    check(np.isclose(effect["ml_incremental_top_k_net_alpha"], expected), "matured treatment effect is the synchronized hybrid-minus-rule net alpha")
    check(np.isclose(effect["promotion_minus_demotion_net_alpha"], 0.06), "promotion reward compares the exact promoted and displaced candidates")

    unchanged = candidates.copy()
    unchanged["hybrid_final_score"] = unchanged["cabinet_native_final_score"]
    unchanged_summary = daily_treatment_summary(attach_rank_treatment(unchanged, top_k=2), top_k=2).iloc[0]
    check(not bool(unchanged_summary["ml_changed_top_k"]), "zero ML treatment is explicitly distinguished from model availability")
    print("[PASS] ML treatment audit product verification completed")


if __name__ == "__main__":
    main()
