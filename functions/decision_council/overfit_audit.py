"""Multiple-testing and backtest-overfitting diagnostics for strategy matrices."""
from __future__ import annotations

import hashlib
from statistics import NormalDist

import numpy as np
import pandas as pd

from functions.decision_council.evaluation import probability_of_backtest_overfitting


OVERFIT_AUDIT_VERSION = "overfit_audit_v1"


def build_insufficient_overfit_reports(reason: str) -> dict[str, pd.DataFrame]:
    """Publish a fail-closed contract when no matched strategy matrix exists."""
    detail = str(reason or "matched_strategy_return_matrix_unavailable")
    return {
        "governance_overfit_deflated_sharpe": pd.DataFrame([{
            "strategy": pd.NA, "observations": 0, "evidence_status": "insufficient_observations",
            "detail": detail, "overfit_audit_version": OVERFIT_AUDIT_VERSION,
        }]),
        "governance_overfit_pbo": pd.DataFrame([{
            "observations": 0, "strategy_count": 0, "pbo": np.nan,
            "evidence_status": "insufficient_observations", "detail": detail,
            "overfit_audit_version": OVERFIT_AUDIT_VERSION,
        }]),
        "governance_overfit_spa": pd.DataFrame([{
            "strategy": pd.NA, "observations": 0, "evidence_status": "insufficient_observations",
            "detail": detail, "overfit_audit_version": OVERFIT_AUDIT_VERSION,
        }]),
        "governance_overfit_overview": pd.DataFrame([
            {"check": check, "gate_pass": False, "status": "insufficient", "detail": detail,
             "changes_trading": False, "overfit_audit_version": OVERFIT_AUDIT_VERSION}
            for check in ("deflated_sharpe", "probability_of_backtest_overfitting", "superior_predictive_ability")
        ]),
    }


def build_overfit_audit_reports(
    strategy_returns: pd.DataFrame,
    *,
    baseline_strategy: str,
    annualization: int = 252,
    pbo_blocks: int = 8,
    bootstrap_block_size: int = 5,
    bootstrap_samples: int = 2000,
    minimum_observations: int = 60,
    significance_level: float = 0.10,
    target_strategy: str = "",
    maximum_pbo: float = 0.50,
) -> dict[str, pd.DataFrame]:
    """Build DSR, CSCV/PBO, and conservative studentized SPA-style reports."""
    data = strategy_returns.copy()
    if "date" in data.columns:
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data = data.sort_values("date").set_index("date")
    data = data.apply(pd.to_numeric, errors="coerce").dropna(how="all")
    strategies = tuple(data.columns)
    if baseline_strategy not in strategies:
        raise ValueError(f"baseline strategy is missing: {baseline_strategy}")
    if len(strategies) < 2:
        raise ValueError("overfit audit requires at least two strategies")
    if int(annualization) <= 0 or int(minimum_observations) <= 1:
        raise ValueError("annualization and minimum_observations must be positive")
    if not 0.0 < float(significance_level) < 1.0:
        raise ValueError("significance_level must be in (0, 1)")
    if int(bootstrap_block_size) <= 0 or int(bootstrap_samples) <= 0:
        raise ValueError("bootstrap settings must be positive")

    aligned = data.dropna()
    dsr = _deflated_sharpe_report(
        aligned,
        annualization=int(annualization),
        minimum_observations=int(minimum_observations),
        significance_level=float(significance_level),
    )
    pbo = _pbo_report(aligned, blocks=int(pbo_blocks), minimum_observations=int(minimum_observations))
    spa = _spa_report(
        aligned,
        baseline_strategy=baseline_strategy,
        block_size=int(bootstrap_block_size),
        samples=int(bootstrap_samples),
        minimum_observations=int(minimum_observations),
        significance_level=float(significance_level),
    )
    overview = _overfit_overview(
        dsr, pbo, spa, target_strategy=str(target_strategy), maximum_pbo=float(maximum_pbo)
    )
    return {
        "governance_overfit_deflated_sharpe": dsr,
        "governance_overfit_pbo": pbo,
        "governance_overfit_spa": spa,
        "governance_overfit_overview": overview,
    }


def _deflated_sharpe_report(data, *, annualization, minimum_observations, significance_level):
    daily_sharpes = {}
    annual_sharpes = {}
    for strategy in data:
        values = data[strategy].dropna()
        std = float(values.std(ddof=1))
        daily = float(values.mean() / std) if std > 0.0 else np.nan
        daily_sharpes[strategy] = daily
        annual_sharpes[strategy] = daily * np.sqrt(annualization) if np.isfinite(daily) else np.nan
    annual_values = pd.Series(annual_sharpes).dropna()
    correlation = data.corr()
    upper = correlation.where(np.triu(np.ones(correlation.shape), k=1).astype(bool)).stack()
    mean_correlation = float(upper.mean()) if not upper.empty else 0.0
    effective_trials = float(np.clip(1.0 + (len(data.columns) - 1.0) * (1.0 - mean_correlation), 1.0, len(data.columns)))
    trial_std = float(annual_values.std(ddof=1)) if len(annual_values) > 1 else 0.0
    trial_mean = float(annual_values.mean()) if len(annual_values) else np.nan
    benchmark_annual = _expected_maximum_normal(trial_mean, trial_std, effective_trials)
    benchmark_daily = benchmark_annual / np.sqrt(annualization) if np.isfinite(benchmark_annual) else np.nan
    rows = []
    for strategy in data:
        values = data[strategy].dropna()
        count = len(values)
        daily = daily_sharpes[strategy]
        skew = float(values.skew()) if count >= 3 else np.nan
        kurtosis = float(values.kurt() + 3.0) if count >= 4 else np.nan
        denominator = (
            1.0 - skew * daily + ((kurtosis - 1.0) / 4.0) * daily ** 2
            if np.isfinite(daily) and np.isfinite(skew) and np.isfinite(kurtosis) else np.nan
        )
        z_score = (
            (daily - benchmark_daily) * np.sqrt(max(count - 1, 0)) / np.sqrt(denominator)
            if np.isfinite(denominator) and denominator > 0.0 else np.nan
        )
        probability = NormalDist().cdf(z_score) if np.isfinite(z_score) else np.nan
        if count < minimum_observations:
            status = "insufficient_observations"
        elif np.isfinite(probability) and probability >= 1.0 - significance_level:
            status = "deflated_sharpe_evidence"
        else:
            status = "deflated_sharpe_not_established"
        rows.append({
            "strategy": strategy,
            "observations": count,
            "annualized_sharpe": annual_sharpes[strategy],
            "return_skew": skew,
            "return_kurtosis": kurtosis,
            "tested_strategy_count": len(data.columns),
            "mean_pairwise_strategy_correlation": mean_correlation,
            "effective_trial_count": effective_trials,
            "selection_bias_sharpe_benchmark": benchmark_annual,
            "deflated_sharpe_probability": probability,
            "evidence_status": status,
            "overfit_audit_version": OVERFIT_AUDIT_VERSION,
        })
    return pd.DataFrame(rows)


def _expected_maximum_normal(mean, std, trials):
    if not np.isfinite(mean) or not np.isfinite(std) or std <= 0.0 or trials <= 1.0:
        return float(mean) if np.isfinite(mean) else np.nan
    gamma = 0.5772156649015329
    normal = NormalDist()
    first = normal.inv_cdf(1.0 - 1.0 / trials)
    second = normal.inv_cdf(1.0 - 1.0 / (trials * np.e))
    return float(mean + std * ((1.0 - gamma) * first + gamma * second))


def _pbo_report(data, *, blocks, minimum_observations):
    row = {
        "observations": len(data),
        "strategy_count": data.shape[1],
        "blocks": blocks,
        "pbo": np.nan,
        "cscv_combinations": 0,
        "median_test_rank_logit": np.nan,
        "evidence_status": "insufficient_observations",
        "overfit_audit_version": OVERFIT_AUDIT_VERSION,
    }
    if len(data) < max(minimum_observations, blocks):
        return pd.DataFrame([row])
    try:
        result = probability_of_backtest_overfitting(data, blocks=blocks)
    except ValueError as exc:
        row["evidence_status"] = f"not_estimable:{type(exc).__name__}"
        return pd.DataFrame([row])
    row.update(result)
    row["evidence_status"] = "estimated"
    return pd.DataFrame([row])


def _spa_report(data, *, baseline_strategy, block_size, samples, minimum_observations, significance_level):
    alternatives = [column for column in data.columns if column != baseline_strategy]
    columns = [
        "strategy", "baseline_strategy", "observations", "mean_daily_excess_return",
        "studentized_statistic", "familywise_bootstrap_p_value", "bootstrap_samples",
        "bootstrap_block_size", "null_recentering", "evidence_status", "overfit_audit_version",
    ]
    if len(data) < minimum_observations:
        return pd.DataFrame([
            {
                "strategy": strategy, "baseline_strategy": baseline_strategy,
                "observations": len(data), "mean_daily_excess_return": np.nan,
                "studentized_statistic": np.nan, "familywise_bootstrap_p_value": np.nan,
                "bootstrap_samples": samples, "bootstrap_block_size": block_size,
                "null_recentering": "full_null_conservative", "evidence_status": "insufficient_observations",
                "overfit_audit_version": OVERFIT_AUDIT_VERSION,
            } for strategy in alternatives
        ], columns=columns)
    differences = data[alternatives].sub(data[baseline_strategy], axis=0).to_numpy(dtype=float)
    count = len(differences)
    means = differences.mean(axis=0)
    std = differences.std(axis=0, ddof=1)
    observed = np.divide(np.sqrt(count) * means, std, out=np.zeros_like(means), where=std > 0.0)
    centered = differences - means
    starts = np.arange(0, count - block_size + 1)
    if len(starts) == 0:
        return pd.DataFrame([
            {
                "strategy": strategy, "baseline_strategy": baseline_strategy,
                "observations": count, "mean_daily_excess_return": means[index],
                "studentized_statistic": observed[index], "familywise_bootstrap_p_value": np.nan,
                "bootstrap_samples": samples, "bootstrap_block_size": block_size,
                "null_recentering": "full_null_conservative", "evidence_status": "insufficient_block_history",
                "overfit_audit_version": OVERFIT_AUDIT_VERSION,
            } for index, strategy in enumerate(alternatives)
        ], columns=columns)
    rng = np.random.default_rng(_overfit_seed(baseline_strategy, alternatives, count))
    needed = int(np.ceil(count / block_size))
    maxima = []
    for _ in range(samples):
        chosen = rng.choice(starts, size=needed, replace=True)
        sample = np.concatenate([centered[start:start + block_size] for start in chosen], axis=0)[:count]
        sample_mean = sample.mean(axis=0)
        statistic = np.divide(np.sqrt(count) * sample_mean, std, out=np.zeros_like(means), where=std > 0.0)
        maxima.append(float(np.max(statistic)))
    maxima = np.asarray(maxima)
    rows = []
    for index, strategy in enumerate(alternatives):
        p_value = float((1 + np.sum(maxima >= observed[index])) / (samples + 1))
        status = (
            "superior_predictive_evidence"
            if means[index] > 0.0 and p_value <= significance_level
            else "superiority_not_established"
        )
        rows.append({
            "strategy": strategy,
            "baseline_strategy": baseline_strategy,
            "observations": count,
            "mean_daily_excess_return": means[index],
            "studentized_statistic": observed[index],
            "familywise_bootstrap_p_value": p_value,
            "bootstrap_samples": samples,
            "bootstrap_block_size": block_size,
            "null_recentering": "full_null_conservative",
            "evidence_status": status,
            "overfit_audit_version": OVERFIT_AUDIT_VERSION,
        })
    return pd.DataFrame(rows, columns=columns)


def _overfit_seed(baseline, alternatives, count):
    text = f"{baseline}|{'|'.join(alternatives)}|{count}|{OVERFIT_AUDIT_VERSION}"
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _overfit_overview(dsr, pbo, spa, *, target_strategy="", maximum_pbo=0.50):
    target = str(target_strategy or "").strip()
    dsr_scope = dsr[dsr["strategy"].astype(str).eq(target)] if target else dsr
    spa_scope = spa[spa["strategy"].astype(str).eq(target)] if target else spa
    enough = not dsr_scope.empty and dsr_scope["evidence_status"].ne("insufficient_observations").any()
    dsr_pass = dsr_scope["evidence_status"].eq("deflated_sharpe_evidence").all() if enough else False
    pbo_estimated = not pbo.empty and pbo.iloc[0]["evidence_status"] == "estimated"
    pbo_pass = bool(pbo_estimated and pd.notna(pbo.iloc[0].get("pbo")) and float(pbo.iloc[0]["pbo"]) <= maximum_pbo)
    spa_enough = not spa_scope.empty and spa_scope["evidence_status"].ne("insufficient_observations").any()
    spa_pass = spa_scope["evidence_status"].eq("superior_predictive_evidence").all() if spa_enough else False
    return pd.DataFrame([
        {"check": "deflated_sharpe", "gate_pass": dsr_pass, "status": "estimated" if enough else "insufficient", "target_strategy": target or "any"},
        {"check": "probability_of_backtest_overfitting", "gate_pass": pbo_pass, "status": str(pbo.iloc[0]["evidence_status"]) if not pbo.empty else "missing", "target_strategy": target or "all", "maximum_pbo": maximum_pbo},
        {"check": "superior_predictive_ability", "gate_pass": spa_pass, "status": "estimated" if spa_enough else "insufficient", "target_strategy": target or "any"},
    ]).assign(changes_trading=False, overfit_audit_version=OVERFIT_AUDIT_VERSION)
