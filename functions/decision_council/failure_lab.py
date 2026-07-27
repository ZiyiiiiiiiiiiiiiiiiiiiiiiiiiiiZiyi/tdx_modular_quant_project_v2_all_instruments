"""Falsification-first diagnostics for governance candidate layers.

These reports never alter candidates, orders, positions, or execution.  Layer
spreads are paired by signal date and are association diagnostics, not causal
effect estimates.
"""
from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from statistics import NormalDist

import numpy as np
import pandas as pd

from functions.decision_council.evaluation import paired_block_bootstrap_interval


FAILURE_LAB_VERSION = "failure_lab_v1"
DEFAULT_LAYER_TRANSITIONS = (
    ("L0_all_percentile_candidates", "L1_current_role_confirmation"),
    ("L1_current_role_confirmation", "L2_primary_entry_alpha_top3"),
    ("L2_primary_entry_alpha_top3", "L3_executed_buy"),
    ("L0_all_percentile_candidates", "L3_executed_buy"),
)
ROLE_SCORE_COLUMNS = (
    "cabinet_strict_entry_score",
    "cabinet_proxy_entry_score",
    "cabinet_timing_score",
    "cabinet_risk_safety_score",
    "cabinet_liquidity_health_score",
    "cabinet_hold_support_score",
)


def build_paired_layer_increment_reports(
    layer_daily: pd.DataFrame,
    *,
    transitions: Iterable[tuple[str, str]] = DEFAULT_LAYER_TRANSITIONS,
    horizons: Iterable[int] = (5, 10, 20),
    block_size: int = 5,
    bootstrap_samples: int = 2000,
    confidence: float = 0.90,
    minimum_paired_days: int | None = None,
) -> dict[str, pd.DataFrame]:
    """Measure each layer's same-day incremental return with block-bootstrap CIs."""
    required = {"signal_date", "variant"}
    missing = sorted(required - set(layer_daily.columns))
    if missing:
        raise ValueError(f"layer daily report is missing columns: {missing}")
    size = int(block_size)
    samples = int(bootstrap_samples)
    if size <= 0:
        raise ValueError("block_size must be positive")
    if samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    if not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    required_days = int(minimum_paired_days) if minimum_paired_days is not None else size
    if required_days <= 0:
        raise ValueError("minimum_paired_days must be positive")

    data = layer_daily.copy()
    data["signal_date"] = pd.to_datetime(data["signal_date"], errors="coerce")
    data["variant"] = data["variant"].astype(str)
    data = data.dropna(subset=["signal_date"]).sort_values(["signal_date", "variant"])
    summary_rows: list[dict] = []
    daily_frames: list[pd.DataFrame] = []
    for parent, child in tuple(transitions):
        for horizon in tuple(int(value) for value in horizons):
            column = f"mean_forward_return_{horizon}d"
            if column not in data.columns:
                raise ValueError(f"layer daily report is missing horizon column: {column}")
            parent_daily = data[data["variant"].eq(parent)][["signal_date", column]].rename(
                columns={column: "parent_return"}
            )
            child_daily = data[data["variant"].eq(child)][["signal_date", column]].rename(
                columns={column: "child_return"}
            )
            paired = parent_daily.merge(child_daily, on="signal_date", how="inner").dropna()
            paired = paired.sort_values("signal_date").drop_duplicates("signal_date", keep="last")
            paired["incremental_return"] = paired["child_return"] - paired["parent_return"]
            paired.insert(0, "parent_layer", parent)
            paired.insert(1, "child_layer", child)
            paired.insert(2, "horizon_days", horizon)
            paired["failure_lab_version"] = FAILURE_LAB_VERSION
            daily_frames.append(paired)
            count = len(paired)
            point = float(paired["incremental_return"].mean()) if count else np.nan
            lower = upper = np.nan
            status = "insufficient_paired_days"
            if count >= max(size, required_days):
                lower, upper = paired_block_bootstrap_interval(
                    paired["incremental_return"],
                    block_size=size,
                    samples=samples,
                    confidence=confidence,
                    random_seed=_stable_seed(parent, child, horizon),
                )
                if lower > 0.0:
                    status = "evidence_benefit"
                elif upper < 0.0:
                    status = "evidence_harm"
                else:
                    status = "inconclusive"
            summary_rows.append({
                "parent_layer": parent,
                "child_layer": child,
                "horizon_days": horizon,
                "paired_days": count,
                "mean_parent_return": float(paired["parent_return"].mean()) if count else np.nan,
                "mean_child_return": float(paired["child_return"].mean()) if count else np.nan,
                "mean_incremental_return": point,
                "positive_increment_day_ratio": float(paired["incremental_return"].gt(0.0).mean()) if count else np.nan,
                "bootstrap_confidence": float(confidence),
                "bootstrap_block_size": size,
                "bootstrap_samples": samples,
                "increment_ci_lower": lower,
                "increment_ci_upper": upper,
                "evidence_status": status,
                "causal_interpretation_allowed": False,
                "failure_lab_version": FAILURE_LAB_VERSION,
            })
    daily_detail = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    return {
        "governance_failure_lab_layer_increment": pd.DataFrame(summary_rows),
        "governance_failure_lab_layer_increment_daily": daily_detail,
    }


def _stable_seed(parent: str, child: str, horizon: int) -> int:
    digest = hashlib.sha256(f"{parent}|{child}|{horizon}|{FAILURE_LAB_VERSION}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def build_role_marginal_regression_reports(
    candidate_detail: pd.DataFrame,
    *,
    feature_columns: Iterable[str] = ROLE_SCORE_COLUMNS,
    horizons: Iterable[int] = (5, 10, 20),
    confidence: float = 0.90,
    hac_lags: int | None = None,
    minimum_cross_section: int | None = None,
    minimum_observed_days: int = 5,
) -> dict[str, pd.DataFrame]:
    """Daily standardized cross-sectional OLS with HAC Fama-MacBeth summary."""
    features = tuple(dict.fromkeys(str(column) for column in feature_columns))
    required = {"signal_date", "symbol", *features}
    missing = sorted(required - set(candidate_detail.columns))
    if missing:
        raise ValueError(f"role marginal regression is missing columns: {missing}")
    if not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    min_cross = int(minimum_cross_section) if minimum_cross_section is not None else len(features) + 3
    if min_cross <= len(features) + 1:
        raise ValueError("minimum_cross_section must exceed feature count plus intercept")
    if int(minimum_observed_days) <= 1:
        raise ValueError("minimum_observed_days must exceed one")
    data = candidate_detail.copy()
    data["signal_date"] = pd.to_datetime(data["signal_date"], errors="coerce")
    for column in features:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    coefficient_rows: list[dict] = []
    day_rows: list[dict] = []
    for horizon in tuple(int(value) for value in horizons):
        outcome = f"forward_return_{horizon}d"
        if outcome not in data.columns:
            raise ValueError(f"role marginal regression is missing outcome: {outcome}")
        data[outcome] = pd.to_numeric(data[outcome], errors="coerce")
        for date, group in data[["signal_date", "symbol", outcome, *features]].dropna(
            subset=["signal_date", outcome]
        ).groupby("signal_date", sort=True):
            usable = group.dropna(subset=list(features)).copy()
            if len(usable) < min_cross:
                day_rows.append(_regression_day_row(date, horizon, len(usable), 0, np.nan, np.nan, "insufficient_cross_section"))
                continue
            active = [column for column in features if float(usable[column].std(ddof=0)) > 1e-12]
            if len(active) != len(features):
                day_rows.append(_regression_day_row(date, horizon, len(usable), len(active), np.nan, np.nan, "constant_or_missing_feature"))
                continue
            x = np.column_stack([
                np.ones(len(usable)),
                *(
                    (usable[column].to_numpy(dtype=float) - float(usable[column].mean()))
                    / float(usable[column].std(ddof=0))
                    for column in active
                ),
            ])
            y = usable[outcome].to_numpy(dtype=float)
            condition = float(np.linalg.cond(x))
            if not np.isfinite(condition) or condition > 1e10:
                day_rows.append(_regression_day_row(date, horizon, len(usable), len(active), condition, np.nan, "ill_conditioned"))
                continue
            coefficients, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
            fitted = x @ coefficients
            residual_sum = float(np.square(y - fitted).sum())
            total_sum = float(np.square(y - y.mean()).sum())
            r_squared = 1.0 - residual_sum / total_sum if total_sum > 1e-18 else np.nan
            day_rows.append(_regression_day_row(date, horizon, len(usable), len(active), condition, r_squared, "estimated"))
            for index, feature in enumerate(active, start=1):
                coefficient_rows.append({
                    "signal_date": pd.Timestamp(date),
                    "horizon_days": horizon,
                    "feature": feature,
                    "coefficient_per_cross_section_sd": float(coefficients[index]),
                    "cross_section_count": len(usable),
                    "condition_number": condition,
                    "r_squared": r_squared,
                    "failure_lab_version": FAILURE_LAB_VERSION,
                })
    daily_coefficients = pd.DataFrame(coefficient_rows)
    daily_diagnostics = pd.DataFrame(day_rows)
    summary_rows: list[dict] = []
    z_value = NormalDist().inv_cdf(0.5 + float(confidence) / 2.0)
    for horizon in tuple(int(value) for value in horizons):
        for feature in features:
            if daily_coefficients.empty:
                values = pd.Series(dtype=float)
            else:
                values = daily_coefficients[
                    daily_coefficients["horizon_days"].eq(horizon)
                    & daily_coefficients["feature"].eq(feature)
                ].sort_values("signal_date")["coefficient_per_cross_section_sd"].dropna()
            observed = len(values)
            mean = float(values.mean()) if observed else np.nan
            lags = _automatic_hac_lags(observed) if hac_lags is None else int(hac_lags)
            if lags < 0:
                raise ValueError("hac_lags cannot be negative")
            lags = min(lags, max(observed - 1, 0))
            se = _newey_west_mean_standard_error(values.to_numpy(dtype=float), lags) if observed >= 2 else np.nan
            lower = mean - z_value * se if np.isfinite(se) else np.nan
            upper = mean + z_value * se if np.isfinite(se) else np.nan
            if observed < int(minimum_observed_days) or not np.isfinite(se):
                status = "insufficient_observed_days"
            elif lower > 0.0:
                status = "evidence_positive_marginal_return"
            elif upper < 0.0:
                status = "evidence_negative_marginal_return"
            else:
                status = "inconclusive"
            summary_rows.append({
                "feature": feature,
                "horizon_days": horizon,
                "observed_days": observed,
                "mean_coefficient_per_cross_section_sd": mean,
                "hac_lags": lags,
                "hac_standard_error": se,
                "hac_t_stat": mean / se if np.isfinite(se) and se > 0.0 else np.nan,
                "confidence": float(confidence),
                "coefficient_ci_lower": lower,
                "coefficient_ci_upper": upper,
                "positive_coefficient_day_ratio": float(values.gt(0.0).mean()) if observed else np.nan,
                "evidence_status": status,
                "causal_interpretation_allowed": False,
                "failure_lab_version": FAILURE_LAB_VERSION,
            })
    return {
        "governance_failure_lab_role_marginal_summary": pd.DataFrame(summary_rows),
        "governance_failure_lab_role_marginal_daily": daily_coefficients,
        "governance_failure_lab_role_regression_diagnostics": daily_diagnostics,
    }


def _regression_day_row(date, horizon, count, active_count, condition, r_squared, status) -> dict:
    return {
        "signal_date": pd.Timestamp(date),
        "horizon_days": int(horizon),
        "cross_section_count": int(count),
        "active_feature_count": int(active_count),
        "condition_number": condition,
        "r_squared": r_squared,
        "status": status,
        "failure_lab_version": FAILURE_LAB_VERSION,
    }


def _automatic_hac_lags(observed_days: int) -> int:
    if observed_days <= 1:
        return 0
    return int(math.floor(4.0 * (float(observed_days) / 100.0) ** (2.0 / 9.0)))


def _newey_west_mean_standard_error(values: np.ndarray, lags: int) -> float:
    data = np.asarray(values, dtype=float)
    count = len(data)
    if count < 2:
        return float("nan")
    centered = data - data.mean()
    long_run_variance = float(np.dot(centered, centered) / count)
    for lag in range(1, min(int(lags), count - 1) + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / count)
        long_run_variance += 2.0 * (1.0 - lag / (int(lags) + 1.0)) * covariance
    return float(np.sqrt(max(long_run_variance, 0.0) / count))


def build_negative_control_permutation_report(
    candidate_detail: pd.DataFrame,
    *,
    feature_columns: Iterable[str] = ROLE_SCORE_COLUMNS,
    horizons: Iterable[int] = (5, 10, 20),
    permutation_samples: int = 1000,
    fdr_alpha: float = 0.10,
    minimum_cross_section: int = 5,
    minimum_observed_days: int = 5,
    random_seed: int = 20260717,
) -> dict[str, pd.DataFrame]:
    """Date-stratified permutation tests with deterministic negative controls."""
    features = tuple(dict.fromkeys(str(column) for column in feature_columns))
    required = {"signal_date", "symbol", *features}
    missing = sorted(required - set(candidate_detail.columns))
    if missing:
        raise ValueError(f"negative-control audit is missing columns: {missing}")
    samples = int(permutation_samples)
    if samples <= 0:
        raise ValueError("permutation_samples must be positive")
    if not 0.0 < float(fdr_alpha) < 1.0:
        raise ValueError("fdr_alpha must be in (0, 1)")
    if int(minimum_cross_section) < 3 or int(minimum_observed_days) < 2:
        raise ValueError("negative-control minimum sample constraints are invalid")
    data = candidate_detail.copy()
    data["signal_date"] = pd.to_datetime(data["signal_date"], errors="coerce")
    data["symbol"] = data["symbol"].astype(str)
    for column in features:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    hash_values = pd.util.hash_pandas_object(
        data[["signal_date", "symbol"]], index=False
    ).to_numpy(dtype=np.uint64)
    data["negative_hash_noise"] = hash_values.astype(np.float64) / float(np.iinfo(np.uint64).max)
    first_feature = features[0]
    ordered = data.sort_values(["signal_date", "symbol"]).copy()
    ordered["negative_misaligned_primary"] = ordered.groupby("signal_date", sort=False)[first_feature].transform(
        lambda values: _date_seeded_full_permutation(values)
    )
    data = data.merge(
        ordered[["signal_date", "symbol", "negative_misaligned_primary"]],
        on=["signal_date", "symbol"], how="left", validate="one_to_one",
    )
    audit_features = (*features, "negative_hash_noise", "negative_misaligned_primary")
    feature_types = {
        column: ("negative_control" if column.startswith("negative_") else "candidate_feature")
        for column in audit_features
    }
    rows: list[dict] = []
    for horizon in tuple(int(value) for value in horizons):
        outcome = f"forward_return_{horizon}d"
        if outcome not in data.columns:
            raise ValueError(f"negative-control audit is missing outcome: {outcome}")
        data[outcome] = pd.to_numeric(data[outcome], errors="coerce")
        for feature in audit_features:
            daily_arrays = []
            for _, group in data[["signal_date", feature, outcome]].dropna().groupby("signal_date", sort=True):
                if len(group) < int(minimum_cross_section):
                    continue
                feature_rank = _standardized_rank(group[feature].to_numpy(dtype=float))
                outcome_rank = _standardized_rank(group[outcome].to_numpy(dtype=float))
                if feature_rank is None or outcome_rank is None:
                    continue
                daily_arrays.append((feature_rank, outcome_rank))
            observed_days = len(daily_arrays)
            observed = float(np.mean([np.dot(x, y) for x, y in daily_arrays])) if daily_arrays else np.nan
            null = np.asarray([], dtype=float)
            if observed_days >= int(minimum_observed_days):
                rng = np.random.default_rng(_permutation_seed(random_seed, feature, horizon))
                null_values = []
                for _ in range(samples):
                    correlations = [float(np.dot(x, rng.permutation(y))) for x, y in daily_arrays]
                    null_values.append(float(np.mean(correlations)))
                null = np.asarray(null_values, dtype=float)
                p_value = float((1 + np.sum(np.abs(null) >= abs(observed))) / (samples + 1))
            else:
                p_value = np.nan
            rows.append({
                "feature": feature,
                "feature_type": feature_types[feature],
                "horizon_days": horizon,
                "observed_days": observed_days,
                "mean_daily_rank_ic": observed,
                "permutation_samples": samples,
                "permutation_p_value_two_sided": p_value,
                "null_mean": float(null.mean()) if len(null) else np.nan,
                "null_std": float(null.std(ddof=1)) if len(null) > 1 else np.nan,
                "null_q05": float(np.quantile(null, 0.05)) if len(null) else np.nan,
                "null_q95": float(np.quantile(null, 0.95)) if len(null) else np.nan,
                "failure_lab_version": FAILURE_LAB_VERSION,
            })
    report = pd.DataFrame(rows)
    report["fdr_q_value"] = _benjamini_hochberg(report["permutation_p_value_two_sided"])
    sufficient = report["observed_days"].ge(int(minimum_observed_days))
    significant = sufficient & report["fdr_q_value"].le(float(fdr_alpha))
    report["evidence_status"] = "inconclusive"
    report.loc[~sufficient, "evidence_status"] = "insufficient_observed_days"
    report.loc[significant & report["mean_daily_rank_ic"].gt(0.0), "evidence_status"] = "fdr_positive_predictive_evidence"
    report.loc[significant & report["mean_daily_rank_ic"].lt(0.0), "evidence_status"] = "fdr_negative_predictive_evidence"
    control = report[report["feature_type"].eq("negative_control")]
    control_alerts = control[control["fdr_q_value"].le(float(fdr_alpha)) & sufficient.loc[control.index]]
    audit = pd.DataFrame([{
        "permutation_samples": samples,
        "fdr_alpha": float(fdr_alpha),
        "tested_hypothesis_count": int(report["permutation_p_value_two_sided"].notna().sum()),
        "candidate_feature_significant_count": int(
            report["feature_type"].eq("candidate_feature").mul(significant).sum()
        ),
        "negative_control_test_count": int(len(control)),
        "negative_control_alert_count": int(len(control_alerts)),
        "negative_control_gate_pass": len(control_alerts) == 0,
        "negative_control_alert_features": "|".join(
            f"{row.feature}@{int(row.horizon_days)}d" for row in control_alerts.itertuples()
        ),
        "interpretation": (
            "negative_controls_behave_as_null"
            if control_alerts.empty else "negative_control_significance_requires_leakage_or_ordering_review"
        ),
        "failure_lab_version": FAILURE_LAB_VERSION,
    }])
    return {
        "governance_failure_lab_permutation_report": report,
        "governance_failure_lab_negative_control_audit": audit,
    }


def _standardized_rank(values: np.ndarray) -> np.ndarray | None:
    ranks = pd.Series(values).rank(method="average").to_numpy(dtype=float)
    centered = ranks - ranks.mean()
    norm = float(np.sqrt(np.dot(centered, centered)))
    return centered / norm if norm > 1e-12 else None


def _permutation_seed(base_seed: int, feature: str, horizon: int) -> int:
    digest = hashlib.sha256(f"{base_seed}|{feature}|{horizon}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _date_seeded_full_permutation(values: pd.Series) -> np.ndarray:
    # Hash the sorted member values, producing a deterministic but non-local
    # permutation that changes with each date's cross section.
    payload = "|".join(pd.Series(values).astype(str).tolist())
    seed = int(hashlib.sha256(f"{payload}|negative_control".encode("utf-8")).hexdigest()[:8], 16)
    return np.random.default_rng(seed).permutation(values.to_numpy())


def _benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    values = pd.to_numeric(p_values, errors="coerce")
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna().sort_values()
    count = len(valid)
    if count == 0:
        return result
    adjusted = valid.to_numpy(dtype=float) * count / np.arange(1, count + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result.loc[valid.index] = np.clip(adjusted, 0.0, 1.0)
    return result


def build_failure_lab_overview(
    *,
    layer_increment: pd.DataFrame,
    role_marginal_summary: pd.DataFrame,
    negative_control_audit: pd.DataFrame,
) -> pd.DataFrame:
    """Build a compact, fail-closed product interpretation of failure-lab evidence."""
    layer_status = layer_increment.get("evidence_status", pd.Series(dtype=str)).astype(str)
    role_status = role_marginal_summary.get("evidence_status", pd.Series(dtype=str)).astype(str)
    if negative_control_audit is None or negative_control_audit.empty:
        control_pass = False
        control_alert_count = np.nan
        control_detail = "negative_control_audit_missing"
    else:
        control_row = negative_control_audit.iloc[-1]
        control_pass = bool(control_row.get("negative_control_gate_pass", False))
        control_alert_count = pd.to_numeric(
            pd.Series([control_row.get("negative_control_alert_count")]), errors="coerce"
        ).iloc[0]
        control_detail = str(control_row.get("interpretation", ""))
    rows = [
        {
            "check": "paired_layer_increment",
            "gate_pass": not layer_status.eq("evidence_harm").any() and not layer_status.eq("insufficient_paired_days").all(),
            "harm_or_alert_count": int(layer_status.eq("evidence_harm").sum()),
            "insufficient_count": int(layer_status.eq("insufficient_paired_days").sum()),
            "detail": "paired same-date layer spreads; association only",
        },
        {
            "check": "role_marginal_direction",
            "gate_pass": not role_status.eq("evidence_negative_marginal_return").any() and not role_status.eq("insufficient_observed_days").all(),
            "harm_or_alert_count": int(role_status.eq("evidence_negative_marginal_return").sum()),
            "insufficient_count": int(role_status.eq("insufficient_observed_days").sum()),
            "detail": "joint standardized daily cross-sectional coefficients with HAC uncertainty",
        },
        {
            "check": "negative_controls",
            "gate_pass": control_pass,
            "harm_or_alert_count": control_alert_count,
            "insufficient_count": 0,
            "detail": control_detail,
        },
    ]
    output = pd.DataFrame(rows)
    output["research_gate_status"] = np.where(output["gate_pass"], "pass", "fail")
    output["changes_trading"] = False
    output["failure_lab_version"] = FAILURE_LAB_VERSION
    return output
