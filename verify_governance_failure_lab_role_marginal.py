"""Truth, boundary, and product checks for role marginal regressions."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.failure_lab import (
    ROLE_SCORE_COLUMNS,
    build_role_marginal_regression_reports,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def fixture() -> pd.DataFrame:
    rng = np.random.default_rng(911)
    rows = []
    for date in pd.bdate_range("2022-01-03", periods=80):
        latent = rng.normal(size=(100, 3))
        strict = latent[:, 0]
        proxy = 0.65 * strict + np.sqrt(1.0 - 0.65 ** 2) * latent[:, 1]
        timing = latent[:, 2]
        noise_roles = rng.normal(size=(100, 3))
        outcome = 0.020 * strict - 0.015 * proxy + 0.010 * timing + rng.normal(0.0, 0.012, 100)
        for index in range(100):
            rows.append({
                "signal_date": date,
                "symbol": f"S{index:03d}",
                "cabinet_strict_entry_score": strict[index],
                "cabinet_proxy_entry_score": proxy[index],
                "cabinet_timing_score": timing[index],
                "cabinet_risk_safety_score": noise_roles[index, 0],
                "cabinet_liquidity_health_score": noise_roles[index, 1],
                "cabinet_hold_support_score": noise_roles[index, 2],
                "forward_return_5d": outcome[index],
                "forward_return_10d": 1.4 * outcome[index] + rng.normal(0.0, 0.008),
                "forward_return_20d": 1.8 * outcome[index] + rng.normal(0.0, 0.012),
            })
    return pd.DataFrame(rows)


def main() -> None:
    source = fixture()
    before = source.copy(deep=True)
    reports = build_role_marginal_regression_reports(source, confidence=0.90)
    summary = reports["governance_failure_lab_role_marginal_summary"]
    diagnostics = reports["governance_failure_lab_role_regression_diagnostics"]
    strict = summary[summary["feature"].eq("cabinet_strict_entry_score")]
    proxy = summary[summary["feature"].eq("cabinet_proxy_entry_score")]
    noise = summary[summary["feature"].eq("cabinet_hold_support_score")]
    check(len(summary) == len(ROLE_SCORE_COLUMNS) * 3, "all roles are estimated at all registered horizons")
    check(strict["evidence_status"].eq("evidence_positive_marginal_return").all(), "positive strict-entry truth is recovered jointly")
    check(proxy["evidence_status"].eq("evidence_negative_marginal_return").all(), "negative correlated proxy truth is recovered jointly")
    check(noise["mean_coefficient_per_cross_section_sd"].abs().max() < 0.002, "irrelevant hold role remains economically near zero")
    check(diagnostics["status"].eq("estimated").all(), "well-formed cross sections all estimate successfully")
    check(summary["hac_lags"].gt(0).all(), "automatic HAC lag rule accounts for coefficient autocorrelation")
    check(source.equals(before), "role audit does not mutate candidate detail")
    check(summary["causal_interpretation_allowed"].eq(False).all(), "role audit forbids causal overclaiming")

    constant = source.copy()
    constant["cabinet_hold_support_score"] = 0.5
    constant_reports = build_role_marginal_regression_reports(constant)
    constant_summary = constant_reports["governance_failure_lab_role_marginal_summary"]
    check(constant_summary["observed_days"].eq(0).all(), "constant role makes the joint specification fail closed")
    check(constant_reports["governance_failure_lab_role_regression_diagnostics"]["status"].eq("constant_or_missing_feature").all(), "constant-role failure reason is audited")
    short = source[source["signal_date"].isin(source["signal_date"].unique()[:3])]
    short_summary = build_role_marginal_regression_reports(short)["governance_failure_lab_role_marginal_summary"]
    check(short_summary["evidence_status"].eq("insufficient_observed_days").all(), "too few dates cannot produce marginal evidence")
    try:
        build_role_marginal_regression_reports(source.drop(columns="cabinet_timing_score"))
    except ValueError:
        print("[PASS] missing role contract fails loudly")
    else:
        raise AssertionError("missing role contract fails loudly")
    print("[PASS] role marginal regression product verification completed")


if __name__ == "__main__":
    main()
