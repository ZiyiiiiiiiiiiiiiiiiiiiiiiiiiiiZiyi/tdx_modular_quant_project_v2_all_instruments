"""Product and bug checks for paired layer-increment falsification reports."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.failure_lab import build_paired_layer_increment_reports


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def fixture() -> pd.DataFrame:
    rng = np.random.default_rng(20260717)
    rows = []
    dates = pd.bdate_range("2023-01-02", periods=60)
    for index, date in enumerate(dates):
        common = 0.002 * np.sin(index / 4.0) + rng.normal(0.0, 0.001)
        values = {
            "L0_all_percentile_candidates": common,
            "L1_current_role_confirmation": common - 0.010 + rng.normal(0.0, 0.001),
            "L2_primary_entry_alpha_top3": common - 0.004 + rng.normal(0.0, 0.001),
            "L3_executed_buy": common - 0.012 + rng.normal(0.0, 0.001),
        }
        for variant, base in values.items():
            rows.append({
                "signal_date": date,
                "variant": variant,
                "selected_count": 3,
                "mean_forward_return_5d": base,
                "mean_forward_return_10d": 1.5 * base,
                "mean_forward_return_20d": 2.0 * base,
            })
    return pd.DataFrame(rows)


def expect_value_error(callable_, message: str) -> None:
    try:
        callable_()
    except ValueError:
        print(f"[PASS] {message}")
        return
    raise AssertionError(message)


def main() -> None:
    source = fixture()
    before = source.copy(deep=True)
    reports = build_paired_layer_increment_reports(
        source,
        block_size=5,
        bootstrap_samples=500,
        confidence=0.90,
    )
    summary = reports["governance_failure_lab_layer_increment"]
    daily = reports["governance_failure_lab_layer_increment_daily"]
    harm = summary[
        summary["parent_layer"].eq("L0_all_percentile_candidates")
        & summary["child_layer"].eq("L1_current_role_confirmation")
    ]
    benefit = summary[
        summary["parent_layer"].eq("L1_current_role_confirmation")
        & summary["child_layer"].eq("L2_primary_entry_alpha_top3")
    ]
    check(len(summary) == 12, "four registered transitions cover three horizons")
    check(harm["evidence_status"].eq("evidence_harm").all(), "planted harmful confirmation layer is rejected")
    check(benefit["evidence_status"].eq("evidence_benefit").all(), "planted beneficial ranking layer is detected")
    check(harm["increment_ci_upper"].lt(0.0).all(), "harm classification is backed by an all-negative interval")
    check(daily.groupby(["parent_layer", "child_layer", "horizon_days"]).size().eq(60).all(), "same-date pairing retains every overlapping day")
    check(summary["causal_interpretation_allowed"].eq(False).all(), "report forbids causal overclaiming")
    check(source.equals(before), "diagnostic does not mutate its source frame")
    repeated = build_paired_layer_increment_reports(source, block_size=5, bootstrap_samples=500)["governance_failure_lab_layer_increment"]
    check(np.allclose(summary["increment_ci_lower"], repeated["increment_ci_lower"]), "bootstrap output is reproducible")

    short = source[source["signal_date"].isin(source["signal_date"].unique()[:3])]
    short_report = build_paired_layer_increment_reports(short, block_size=5)["governance_failure_lab_layer_increment"]
    check(short_report["evidence_status"].eq("insufficient_paired_days").all(), "short samples fail closed without fabricated confidence intervals")
    no_child = source[~source["variant"].eq("L3_executed_buy")]
    missing_pair = build_paired_layer_increment_reports(no_child, block_size=5)["governance_failure_lab_layer_increment"]
    check(missing_pair[missing_pair["child_layer"].eq("L3_executed_buy")]["paired_days"].eq(0).all(), "missing child layer is disclosed as zero paired days")
    expect_value_error(
        lambda: build_paired_layer_increment_reports(source.drop(columns="signal_date")),
        "missing date contract fails loudly",
    )
    expect_value_error(
        lambda: build_paired_layer_increment_reports(source, confidence=1.0),
        "invalid confidence level fails loudly",
    )
    print("[PASS] paired layer-increment product verification completed")


if __name__ == "__main__":
    main()
