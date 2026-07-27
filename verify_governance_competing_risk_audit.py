"""Product checks for candidate paper-entry competing risks."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.survival_audit import build_candidate_competing_risk_reports


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def fixture():
    rng = np.random.default_rng(21)
    rows, histories = [], {}
    # Every synthetic entry receives an independent full 20-session path.
    dates = pd.bdate_range("2023-01-02", periods=50)
    for date_index, date in enumerate(dates[:25]):
        for symbol_index in range(18):
            symbol = f"D{date_index:02d}S{symbol_index:02d}"
            score = symbol_index / 17.0
            drift = -0.010 if score >= 2.0 / 3.0 else (0.010 if score <= 1.0 / 3.0 else 0.0)
            prices = [10.0]
            for _ in range(20):
                prices.append(prices[-1] * (1.0 + drift + rng.normal(0.0, 0.002)))
            histories[symbol] = pd.DataFrame({"date": dates[date_index:date_index + 21], "close": prices})
            rows.append({"signal_date": date, "symbol": symbol, "confirmed": True, "strict": score})
    return pd.DataFrame(rows), histories


def main():
    candidates, histories = fixture()
    before = candidates.copy(deep=True)
    reports = build_candidate_competing_risk_reports(
        candidates,
        close_history_getter=lambda symbol: histories.get(symbol),
        feature_columns=("strict",),
        entry_mask_column="confirmed",
        horizon_days=20,
        profit_barrier=0.08,
        loss_barrier=-0.10,
        bootstrap_samples=400,
        minimum_entry_dates=5,
    )
    events = reports["governance_failure_lab_competing_risk_events"]
    summary = reports["governance_failure_lab_competing_risk_summary"].iloc[0]
    curves = reports["governance_failure_lab_competing_risk_curves"]
    check(set(events["event_type"]) == {"profit_barrier", "loss_barrier", "censored"}, "profit, loss, and censoring events are all represented")
    three = candidates.groupby("signal_date", sort=False).head(3).copy()
    three_reports = build_candidate_competing_risk_reports(
        three, close_history_getter=lambda symbol: histories.get(symbol), feature_columns=("strict",),
        entry_mask_column="confirmed", horizon_days=20, profit_barrier=.08, loss_barrier=-.10,
        bootstrap_samples=20, minimum_entry_dates=5,
    )
    three_events = three_reports["governance_failure_lab_competing_risk_events"]
    cohort_counts = three_events.groupby(["signal_date", "strict__cohort"]).size().unstack(fill_value=0)
    check((cohort_counts[["low", "middle", "high"]] == 1).all().all(), "three-candidate dates form balanced one/one/one tertiles")
    check(summary["evidence_status"] == "high_score_increases_loss_incidence", "planted harmful high-score cohort is exposed")
    check(summary["loss_difference_ci_lower"] > 0.0, "harm conclusion has an all-positive loss-incidence interval")
    check(curves.groupby(["feature", "cohort"]).size().eq(20).all(), "each cohort publishes a complete daily incidence curve")
    check((curves["profit_cumulative_incidence"] + curves["loss_cumulative_incidence"] + curves["survival_probability"] - 1.0).abs().max() < 1e-9, "competing-risk probabilities conserve mass")
    check(candidates.equals(before), "survival audit does not mutate candidates")
    missing = candidates.iloc[:1].copy()
    missing_report = build_candidate_competing_risk_reports(
        missing, close_history_getter=lambda symbol: None, feature_columns=("strict",),
        entry_mask_column="confirmed", horizon_days=20, profit_barrier=.08, loss_barrier=.10,
        bootstrap_samples=20, minimum_entry_dates=2,
    )
    check(missing_report["governance_failure_lab_competing_risk_events"]["event_type"].eq("missing_path").all(), "missing price paths are explicitly audited")
    try:
        build_candidate_competing_risk_reports(
            candidates, close_history_getter=lambda symbol: histories.get(symbol), feature_columns=("strict",),
            entry_mask_column="confirmed", horizon_days=0, profit_barrier=.08, loss_barrier=.10,
        )
    except ValueError:
        print("[PASS] invalid horizon fails loudly")
    else:
        raise AssertionError("invalid horizon fails loudly")
    print("[PASS] competing-risk product verification completed")


if __name__ == "__main__":
    main()
