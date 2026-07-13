from __future__ import annotations

import pandas as pd

from functions.decision_council.runtime_maturity import (
    combined_runtime_maturity, covariance_runtime_state,
    reputation_runtime_state, trade_accuracy_runtime_state,
)


def main() -> None:
    assert trade_accuracy_runtime_state(closed_trade_count=0) == "cold_start"
    assert trade_accuracy_runtime_state(closed_trade_count=7) == "warming_up"
    assert trade_accuracy_runtime_state(closed_trade_count=25) == "calibrated"
    covariance = pd.DataFrame([[0.1, 0.0, 0.0], [0.0, 0.1, 0.0], [0.0, 0.0, 0.1]])
    assert covariance_runtime_state(day_index=70, covariance_matrix=covariance) == "calibrated"
    snapshot = pd.DataFrame({"activity_ema": [0.5], "coverage_ema": [0.8]})
    assert reputation_runtime_state(day_index=1000, snapshot=snapshot) == "calibrated"
    assert combined_runtime_maturity(
        probability_state="calibrated", reputation_state="calibrated",
        covariance_state="calibrated", trade_accuracy_state="calibrated", pit_state="available",
    ) == "calibrated"
    assert combined_runtime_maturity(
        probability_state="calibrated", reputation_state="calibrated",
        covariance_state="calibrated", trade_accuracy_state="calibrated", pit_state="degraded",
    ) == "degraded"
    print("[PASS] governance runtime maturity states are independent and fail visibly")


if __name__ == "__main__":
    main()
