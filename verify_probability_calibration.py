"""Verify V6 probability calibration and parameter stability."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.probability_calibration import (
    apply_platt_scaler,
    calibration_metrics,
    calibration_table,
    fit_platt_scaler,
    parameter_stability_report,
)


def main():
    outcomes = pd.Series(([0, 1] * 100), dtype=int)
    poor = pd.Series(np.where(outcomes == 1, 0.60, 0.40))
    metrics = calibration_metrics(poor, outcomes)
    table = calibration_table(poor, outcomes)
    assert metrics.sample_count == 200
    assert 0.0 <= metrics.brier_score <= 1.0
    assert not table.empty

    raw = pd.Series(np.linspace(-2.0, 2.0, 200))
    labels = (raw > 0.0).astype(int)
    scaler = fit_platt_scaler(raw, labels)
    calibrated = apply_platt_scaler(scaler, raw)
    assert calibrated.notna().all()
    assert calibrated.iloc[0] < calibrated.iloc[-1]

    stable = parameter_stability_report(
        pd.DataFrame({"threshold": [29, 30, 31]}),
        parameter_columns=["threshold"],
    )
    assert bool(stable.iloc[0]["stable"])
    print("Probability calibration verification passed.")


if __name__ == "__main__":
    main()
