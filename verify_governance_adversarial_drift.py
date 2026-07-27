"""Product checks for adversarial train/test drift diagnostics."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.drift_audit import build_adversarial_drift_reports


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def frame(seed, shift=0.0, rows=1600):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "symbol": [f"S{i % 400:04d}" for i in range(rows)],
        "strict": rng.normal(shift, 1.0, rows),
        "timing": rng.normal(-shift * .7, 1.0, rows),
        "risk": rng.standard_t(6, rows) + shift * .3,
    })


def main():
    train = frame(1)
    stable_test = frame(2)
    before = train.copy(deep=True)
    stable = build_adversarial_drift_reports(
        train, stable_test, feature_columns=("strict", "timing", "risk"),
        permutation_samples=200, minimum_domain_rows=100,
    )
    stable_summary = stable["governance_failure_lab_adversarial_drift_summary"].iloc[0]
    check(stable_summary["evidence_status"] == "no_material_drift_detected", "same-distribution fixture is not promoted as material drift")
    check(train.equals(before), "drift audit does not mutate source data")

    shifted = build_adversarial_drift_reports(
        train, frame(3, shift=1.8), feature_columns=("strict", "timing", "risk"),
        permutation_samples=200, minimum_domain_rows=100,
    )
    shifted_summary = shifted["governance_failure_lab_adversarial_drift_summary"].iloc[0]
    shifted_features = shifted["governance_failure_lab_adversarial_drift_features"]
    check(shifted_summary["evidence_status"] == "material_covariate_drift", "planted multivariate period shift is detected")
    check(shifted_summary["heldout_domain_auc"] >= .80, "planted shift produces strong held-out domain separation")
    check(shifted_features["marginal_shift_fdr_05"].all(), "shifted features survive BH-FDR")

    short = build_adversarial_drift_reports(
        train.iloc[:30], stable_test.iloc[:30], feature_columns=("strict",), minimum_domain_rows=100,
    )["governance_failure_lab_adversarial_drift_summary"].iloc[0]
    check(short["evidence_status"] == "insufficient_domain_rows", "short domains fail closed")
    try:
        build_adversarial_drift_reports(train, stable_test, feature_columns=("missing",))
    except ValueError:
        print("[PASS] missing features fail loudly")
    else:
        raise AssertionError("missing features fail loudly")
    print("[PASS] adversarial drift product verification completed")


if __name__ == "__main__":
    main()
