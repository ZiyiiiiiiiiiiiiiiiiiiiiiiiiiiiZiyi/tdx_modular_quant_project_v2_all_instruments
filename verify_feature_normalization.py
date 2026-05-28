# -*- coding: utf-8 -*-
import pandas as pd

from functions.feature_diagnostics import (
    build_feature_correlation_report,
    build_feature_coverage_report,
    build_feature_distribution_report,
    build_feature_stability_report,
)
from functions.feature_normalization import (
    neutralize_by_group_and_size,
    robust_scale_cross_section,
    winsorize_cross_section,
    zscore_cross_section,
)


def verify_feature_normalization():
    failures: list[str] = []
    print("=== Verify feature normalization ===")

    sample = pd.DataFrame(
        {
            "date": ["2024-01-02"] * 4 + ["2024-01-03"] * 4,
            "symbol": ["a", "b", "c", "d"] * 2,
            "sector_parent": ["bank", "bank", "tech", "tech"] * 2,
            "stabilized_float_cap": [10, 20, 30, 40, 12, 22, 32, 42],
            "ret_20": [0.01, 0.02, 0.90, -0.95, 0.03, 0.04, 1.20, -1.10],
            "volatility_20": [0.10, 0.11, 0.40, 0.50, 0.09, 0.10, 0.42, 0.55],
        }
    )
    feature_cols = ["ret_20", "volatility_20"]

    winsorized = winsorize_cross_section(sample, feature_cols)
    if winsorized["ret_20"].max() >= sample["ret_20"].max():
        failures.append("winsorize should clip cross-sectional outliers")
        print("[FAIL] winsorize should clip cross-sectional outliers")
    else:
        print("[PASS] winsorize clips cross-sectional outliers")

    zscored = zscore_cross_section(sample, feature_cols)
    date_means = zscored.groupby("date")[feature_cols].mean().round(6)
    if not (date_means.abs() <= 1e-6).all().all():
        failures.append("zscore means should be ~0 within each date")
        print("[FAIL] zscore means should be ~0 within each date")
    else:
        print("[PASS] zscore centers each cross-section")

    robust_scaled = robust_scale_cross_section(sample, feature_cols)
    if robust_scaled[feature_cols].isna().any().any():
        failures.append("robust scale should not introduce NaN for valid data")
        print("[FAIL] robust scale should not introduce NaN for valid data")
    else:
        print("[PASS] robust scale keeps valid data populated")

    neutralized = neutralize_by_group_and_size(sample, feature_cols)
    neutralized_cols = [f"{col}_neutralized" for col in feature_cols]
    missing_cols = sorted(set(neutralized_cols) - set(neutralized.columns))
    if missing_cols:
        failures.append(f"neutralized columns missing: {missing_cols}")
        print(f"[FAIL] neutralized columns missing: {missing_cols}")
    else:
        print("[PASS] neutralized columns generated")

    coverage = build_feature_coverage_report(sample, feature_cols)
    distribution = build_feature_distribution_report(sample, feature_cols)
    correlation = build_feature_correlation_report(sample, feature_cols)
    stability = build_feature_stability_report(sample, feature_cols)

    for label, report in {
        "coverage": coverage,
        "distribution": distribution,
        "correlation": correlation,
        "stability": stability,
    }.items():
        if report.empty:
            failures.append(f"{label} report should not be empty")
            print(f"[FAIL] {label} report should not be empty")
        else:
            print(f"[PASS] {label} report generated")

    print()
    if failures:
        print("Feature normalization verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Feature normalization verification passed.")


if __name__ == "__main__":
    verify_feature_normalization()
