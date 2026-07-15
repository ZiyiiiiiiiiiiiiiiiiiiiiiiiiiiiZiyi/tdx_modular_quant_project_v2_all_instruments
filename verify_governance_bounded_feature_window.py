"""Verify max_days bounds feature loading before the governance runner starts."""
from __future__ import annotations

import pandas as pd

from run_governance_experiments import _bounded_feature_end_date
from functions.decision_council import runner as governance_runner


def main() -> int:
    bounded = _bounded_feature_end_date("2021-01-01", "2024-12-31", 20)
    assert pd.Timestamp("2021-01-01") <= bounded < pd.Timestamp("2021-04-01"), bounded
    unbounded = _bounded_feature_end_date("2021-01-01", "2024-12-31", None)
    assert unbounded == pd.Timestamp("2024-12-31"), unbounded
    try:
        _bounded_feature_end_date("2021-01-01", "2024-12-31", 0)
    except ValueError:
        pass
    else:
        raise AssertionError("non-positive max_days was accepted")
    runner_source = governance_runner.run_governance_backtest.__code__.co_names
    assert "bounded_observed_feature_end" in runner_source, runner_source
    print(f"[PASS] max_days=20 bounds feature loading at {bounded.date()}")
    print("[PASS] direct governance runner uses the same bounded feature window")
    print("[PASS] unbounded runs preserve the requested end date")
    print("[PASS] non-positive max_days fails closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
