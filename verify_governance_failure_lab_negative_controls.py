"""Leakage-sentinel and null-control checks for the failure lab."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.failure_lab import build_negative_control_permutation_report


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def fixture() -> pd.DataFrame:
    rng = np.random.default_rng(75)
    rows = []
    for date in pd.bdate_range("2022-01-03", periods=50):
        signal = rng.normal(size=70)
        outcome = 0.03 * signal + rng.normal(0.0, 0.02, 70)
        noise = rng.normal(size=70)
        for index in range(70):
            rows.append({
                "signal_date": date,
                "symbol": f"S{index:03d}",
                "real_signal": signal[index],
                "independent_noise": noise[index],
                "future_leak_sentinel": outcome[index],
                "forward_return_5d": outcome[index],
            })
    return pd.DataFrame(rows)


def main() -> None:
    source = fixture()
    before = source.copy(deep=True)
    reports = build_negative_control_permutation_report(
        source,
        feature_columns=("real_signal", "independent_noise", "future_leak_sentinel"),
        horizons=(5,),
        permutation_samples=500,
        fdr_alpha=0.10,
    )
    report = reports["governance_failure_lab_permutation_report"]
    audit = reports["governance_failure_lab_negative_control_audit"].iloc[0]
    real = report[report["feature"].eq("real_signal")].iloc[0]
    noise = report[report["feature"].eq("independent_noise")].iloc[0]
    leak = report[report["feature"].eq("future_leak_sentinel")].iloc[0]
    check(real["evidence_status"] == "fdr_positive_predictive_evidence", "genuine planted signal survives date-stratified permutation and FDR")
    check(noise["evidence_status"] == "inconclusive", "independent feature behaves as a null")
    check(leak["evidence_status"] == "fdr_positive_predictive_evidence" and leak["mean_daily_rank_ic"] > 0.99, "future-label sentinel exposes catastrophic leakage")
    check(bool(audit["negative_control_gate_pass"]), "generated hash and misalignment controls pass on a clean fixture")
    check(abs(report["null_mean"].dropna()).max() < 0.02, "permuted null distributions remain centered near zero")
    check(source.equals(before), "negative-control audit does not mutate input")
    repeated = build_negative_control_permutation_report(
        source,
        feature_columns=("real_signal", "independent_noise", "future_leak_sentinel"),
        horizons=(5,), permutation_samples=500, fdr_alpha=0.10,
    )["governance_failure_lab_permutation_report"]
    check(np.allclose(report["permutation_p_value_two_sided"], repeated["permutation_p_value_two_sided"]), "permutation evidence is reproducible")
    short = source[source["signal_date"].isin(source["signal_date"].unique()[:2])]
    short_report = build_negative_control_permutation_report(
        short, feature_columns=("real_signal",), horizons=(5,), permutation_samples=50,
    )["governance_failure_lab_permutation_report"]
    check(short_report["evidence_status"].eq("insufficient_observed_days").all(), "too few days fail closed")
    try:
        build_negative_control_permutation_report(source.drop(columns="symbol"), feature_columns=("real_signal",), horizons=(5,))
    except ValueError:
        print("[PASS] missing key contract fails loudly")
    else:
        raise AssertionError("missing key contract fails loudly")
    print("[PASS] negative-control and permutation product verification completed")


if __name__ == "__main__":
    main()
