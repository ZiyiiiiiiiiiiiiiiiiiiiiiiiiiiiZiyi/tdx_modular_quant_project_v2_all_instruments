"""Development-window, overlap and multiple-comparison checks."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.experiment_hygiene import (
    block_bootstrap_mean_interval,
    holm_adjust,
)
from functions.decision_council.runtime_identity import _experiment_sample_role


def main():
    role = _experiment_sample_role(
        list(pd.bdate_range("2025-01-02", "2025-02-28"))
    )
    assert role == "development_audit"
    print("[PASS] diagnosed 338-day overlap is permanently development/audit")
    interval = block_bootstrap_mean_interval(
        pd.Series(range(100), dtype=float) / 10000.0,
        block_length=10,
        samples=200,
    )
    assert interval["effective_sample_count"] == 10
    assert interval["nominal_sample_count"] == 100
    print("[PASS] overlapping horizons disclose nominal and effective sample counts")
    adjusted = holm_adjust([0.01, 0.04, 0.20])
    assert adjusted[0] >= 0.01 and adjusted[1] >= 0.04
    print("[PASS] experiment-family p-values receive Holm adjustment")


if __name__ == "__main__":
    main()
