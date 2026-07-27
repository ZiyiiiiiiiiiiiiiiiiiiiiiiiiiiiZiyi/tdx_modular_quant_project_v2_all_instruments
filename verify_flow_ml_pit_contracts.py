from __future__ import annotations

import pandas as pd

from functions.decision_council.flow_state_features import attach_flow_state_features
from functions.decision_council.ml_nested_validation import one_standard_error_choice, purged_walk_forward_splits
from functions.decision_council.pit_feature_contract import audit_pit_feature_availability


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    flow = attach_flow_state_features(pd.DataFrame([
        {"high": 10, "low": 10, "close": 10, "amount": 100, "amount_ma20": 100, "volatility_5": 0.01, "volatility_20": 0.02, "ret_1": 0},
        {"high": 11, "low": 9, "close": 9.2, "amount": 300, "amount_ma20": 100, "volatility_5": 0.03, "volatility_20": 0.02, "ret_1": -0.03},
    ]))
    expect(flow["flow_close_location_value"].between(-1, 1).all(), "CLV is bounded and zero-range safe")
    expect(float(flow.iloc[1]["flow_distribution_proxy"]) > 0.0, "high-volume weak close creates a distribution proxy")
    expect(flow["flow_proxy_identity_contract"].str.contains("not_investor_identity").all(), "OHLCV proxy does not claim dealer identity")

    dates = pd.bdate_range("2024-01-01", periods=80)
    splits = purged_walk_forward_splits(dates, validation_days=10, purge_days=5, minimum_train_days=30)
    expect(bool(splits) and splits[0][0][-1] < splits[0][1][0], "walk-forward split preserves a purge gap")
    choice = one_standard_error_choice(pd.DataFrame([
        {"name": "complex", "score_mean": 0.10, "score_se": 0.03, "complexity": 10},
        {"name": "simple", "score_mean": 0.08, "score_se": 0.02, "complexity": 2},
    ]))
    expect(choice["name"] == "simple", "one-standard-error rule selects the simpler statistically equivalent model")

    pit = pd.DataFrame({"date": ["2024-01-10", "2024-01-10"], "pit_available_at": ["2024-01-09", "2024-01-11"], "valuation_score": [1.0, 2.0]})
    audit = audit_pit_feature_availability(pit, ["valuation_score"])
    expect(audit.iloc[0]["status"] == "fail" and int(audit.iloc[0]["violation_count"]) == 1,
           "PIT contract rejects a feature published after the decision date")
    print("[PASS] flow, ML validation and PIT contracts verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
