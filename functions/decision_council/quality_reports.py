"""Research diagnostics for high-exposure governance upgrades.

These reports are intentionally post-trade diagnostics. They do not decide
orders directly; they audit whether probabilities, entry filters, risk budgets,
and capacity assumptions are strong enough to justify higher exposure.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from config import (
    GOVERNANCE_ALPHA_DIVERSIFICATION_RULES,
    GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP,
    GOVERNANCE_ENTRY_CALIBRATION_MAX_OVERCONFIDENCE_GAP,
    GOVERNANCE_ENTRY_CALIBRATION_MIN_BUCKET_SAMPLES,
    GOVERNANCE_ENTRY_CALIBRATION_MIN_EXPECTANCY_10D,
    GOVERNANCE_ENTRY_CALIBRATION_MIN_WILSON_LOWER,
    GOVERNANCE_RESEARCH_MAX_TOP1_ACCOUNT_WEIGHT,
    GOVERNANCE_RESEARCH_MAX_TOP5_ACCOUNT_WEIGHT_SUM,
    GOVERNANCE_RESEARCH_MIN_EFFECTIVE_N,
    GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS,
    GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
    GOVERNANCE_PERFORMANCE_BENCHMARK_TOP_N,
)
from functions.decision_council.analytics import build_top_pool_benchmark_series, factor_module
from functions.decision_council.factor_validation import build_factor_research_reports


PREDICTION_BUCKETS = [0.0, 0.45, 0.50, 0.55, 0.60, 0.65, 1.0]
PREDICTION_LABELS = ["<45%", "45-50%", "50-55%", "55-60%", "60-65%", "65%+"]


def build_governance_quality_reports(
    *,
    ideal_portfolio_plan: pd.DataFrame,
    executable_order_plan: pd.DataFrame,
    execution_ledger: pd.DataFrame,
    alpha_proposals: pd.DataFrame,
    feature_data: pd.DataFrame,
    benchmark_symbol: str | None,
    daily_result: pd.DataFrame | None = None,
    attribution_ledger: pd.DataFrame | None = None,
    return_pivot: pd.DataFrame | None = None,
    runtime_context=None,
    benchmark_top_n: int = GOVERNANCE_PERFORMANCE_BENCHMARK_TOP_N,
    benchmark_rebalance: str = GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
) -> dict[str, pd.DataFrame]:
    _log_quality_stage("prepare_price_frames")
    close_pivot = _close_pivot(feature_data)
    benchmark_returns = _top_pool_benchmark_forward_returns(
        feature_data,
        top_n=benchmark_top_n,
        rebalance=benchmark_rebalance,
    )
    if all(series.empty for series in benchmark_returns.values()):
        benchmark_returns = _benchmark_forward_returns(close_pivot, benchmark_symbol)
    _log_quality_stage("trade_quality_reports")
    reports = {
        "governance_entry_payoff_report": build_entry_payoff_report(
            execution_ledger=execution_ledger,
            close_pivot=close_pivot,
            benchmark_forward_returns=benchmark_returns,
        ),
        "governance_entry_calibration_report": build_entry_calibration_report(
            ideal_portfolio_plan=ideal_portfolio_plan,
            close_pivot=close_pivot,
            benchmark_forward_returns=benchmark_returns,
        ),
        "governance_selection_funnel_attribution": build_selection_funnel_attribution(
            ideal_portfolio_plan=ideal_portfolio_plan,
            execution_ledger=execution_ledger,
            close_pivot=close_pivot,
            benchmark_forward_returns=benchmark_returns,
        ),
        "governance_entry_payoff_by_regime": build_entry_payoff_by_regime(
            execution_ledger=execution_ledger,
            daily_result=daily_result,
            close_pivot=close_pivot,
            benchmark_forward_returns=benchmark_returns,
        ),
        "governance_entry_decision_audit": build_entry_decision_audit(
            ideal_portfolio_plan=ideal_portfolio_plan,
            execution_ledger=execution_ledger,
            close_pivot=close_pivot,
            benchmark_forward_returns=benchmark_returns,
        ),
        "governance_position_lifecycle_report": build_position_lifecycle_report(
            execution_ledger=execution_ledger,
            close_pivot=close_pivot,
            benchmark_forward_returns=benchmark_returns,
        ),
        "governance_capacity_stress_report": build_capacity_stress_report(
            executable_order_plan=executable_order_plan,
            execution_ledger=execution_ledger,
        ),
        "governance_risk_contribution_ledger": build_risk_contribution_ledger(
            ideal_portfolio_plan=ideal_portfolio_plan,
            return_pivot=return_pivot,
        ),
        "governance_factor_redundancy_report": build_factor_redundancy_report(alpha_proposals, runtime_context=runtime_context),
        "governance_factor_role_report": build_factor_role_report(alpha_proposals, runtime_context=runtime_context),
        "governance_alpha_diversification_report": build_alpha_diversification_report(alpha_proposals, runtime_context=runtime_context),
        "governance_trading_evidence_report": build_trading_evidence_report(
            daily_result=daily_result,
            execution_ledger=execution_ledger,
        ),
        "governance_rolling_beat_report": build_rolling_beat_report(attribution_ledger),
        "governance_module_role_summary": build_module_role_summary(ideal_portfolio_plan),
        "governance_portfolio_constraint_report": build_portfolio_constraint_report(daily_result),
    }
    _log_quality_stage("factor_research_reports_lightweight")
    reports.update(
        build_factor_research_reports(
            feature_data,
            horizons=(5, 10),
            emit_quantile_rows=False,
            cluster_max_factors=80,
            max_rows=80_000,
            include_missing_factors=False,
        )
    )
    _log_quality_stage("strategy_validation_reports")
    reports["governance_entry_failure_timing_report"] = build_entry_failure_timing_report(
        execution_ledger=execution_ledger,
        close_pivot=close_pivot,
    )
    reports["governance_entry_gate_policy"] = build_entry_gate_policy_report(
        reports.get("governance_entry_calibration_report", pd.DataFrame()),
        reports.get("governance_entry_payoff_by_regime", pd.DataFrame()),
    )
    reports["governance_rebound_entry_diagnostics"] = build_rebound_entry_diagnostics(
        reports.get("governance_entry_payoff_by_regime", pd.DataFrame()),
        daily_result=daily_result,
    )
    reports["governance_strategy_validation_matrix"] = build_strategy_validation_matrix(reports)
    reports["governance_research_gate_report"] = build_research_gate_report(reports)
    return reports


def _log_quality_stage(stage: str) -> None:
    print(f"[governance] quality_reports: {stage}", flush=True)


def build_module_role_summary(ideal_portfolio_plan: pd.DataFrame) -> pd.DataFrame:
    """Audit whether the role-separated entry chain is doing useful filtering."""
    if ideal_portfolio_plan is None or ideal_portfolio_plan.empty:
        return pd.DataFrame()
    data = ideal_portfolio_plan.copy()
    data["decision_date"] = pd.to_datetime(data.get("decision_date"), errors="coerce")
    if data["decision_date"].isna().all():
        return pd.DataFrame()
    numeric_columns = [
        "orderflow_candidate_score",
        "reversal_entry_score",
        "breakout_gate_score",
        "trend_hold_score",
        "module_candidate_score",
        "module_entry_score",
        "module_hold_score",
        "ideal_weight",
        "expected_edge_10d",
        "conservative_expected_edge_10d",
        "p_win_10d_wilson_lower",
    ]
    for column in numeric_columns:
        if column not in data.columns:
            data[column] = np.nan
        data[column] = pd.to_numeric(data[column], errors="coerce")
    for column in ["entry_confirmed", "orderflow_candidate_pass", "reversal_confirm_pass", "breakout_gate_pass"]:
        if column not in data.columns:
            data[column] = False
        data[column] = data[column].fillna(False).astype(bool)
    rows = []
    for date, group in data.groupby("decision_date", sort=True):
        weighted = group[pd.to_numeric(group["ideal_weight"], errors="coerce").fillna(0.0) > 0.0]
        source = weighted if not weighted.empty else group
        rows.append(
            {
                "date": pd.Timestamp(date),
                "selected_count": int(len(group)),
                "weighted_selected_count": int(len(weighted)),
                "entry_confirmed_count": int(group["entry_confirmed"].sum()),
                "orderflow_pass_count": int(group["orderflow_candidate_pass"].sum()),
                "reversal_pass_count": int(group["reversal_confirm_pass"].sum()),
                "breakout_pass_count": int(group["breakout_gate_pass"].sum()),
                "avg_orderflow_candidate_score": _safe_mean(source["orderflow_candidate_score"]),
                "avg_reversal_entry_score": _safe_mean(source["reversal_entry_score"]),
                "avg_breakout_gate_score": _safe_mean(source["breakout_gate_score"]),
                "avg_trend_hold_score": _safe_mean(source["trend_hold_score"]),
                "avg_module_candidate_score": _safe_mean(source["module_candidate_score"]),
                "avg_module_entry_score": _safe_mean(source["module_entry_score"]),
                "avg_module_hold_score": _safe_mean(source["module_hold_score"]),
                "avg_expected_edge_10d": _safe_mean(source["expected_edge_10d"]),
                "avg_conservative_expected_edge_10d": _safe_mean(source["conservative_expected_edge_10d"]),
                "avg_p_win_10d_wilson_lower": _safe_mean(source["p_win_10d_wilson_lower"]),
            }
        )
    return pd.DataFrame(rows)


def build_rebound_entry_diagnostics(payoff_by_regime: pd.DataFrame, *, daily_result: pd.DataFrame | None) -> pd.DataFrame:
    rows = []
    if payoff_by_regime is not None and not payoff_by_regime.empty:
        data = payoff_by_regime.copy()
        data["horizon_days"] = pd.to_numeric(data.get("horizon_days"), errors="coerce")
        data["sample_count"] = pd.to_numeric(data.get("sample_count"), errors="coerce").fillna(0)
        for horizon in (5, 10, 20):
            group = data[
                data["horizon_days"].eq(int(horizon))
                & data.get("side", pd.Series(dtype=object)).astype(str).eq("buy")
                & data.get("regime_name", pd.Series(dtype=object)).astype(str).eq("rebound")
            ].copy()
            rows.append(
                {
                    "diagnostic": f"rebound_buy_{horizon}d",
                    "horizon_days": int(horizon),
                    "sample_count": int(group["sample_count"].sum()) if not group.empty else 0,
                    "hit_rate": _weighted_metric(group, "hit_rate"),
                    "expectancy": _weighted_metric(group, "expectancy"),
                    "avg_directional_excess_return": _weighted_metric(group, "avg_directional_excess_return"),
                    "passed": bool(_weighted_metric(group, "expectancy") > 0.0 and _weighted_metric(group, "avg_directional_excess_return") > 0.0),
                    "interpretation": "rebound entries have positive absolute and excess expectancy" if _weighted_metric(group, "expectancy") > 0.0 else "rebound entries are not yet reliable",
                }
            )
    if daily_result is not None and not daily_result.empty:
        daily = daily_result.copy()
        regime_col = "structural_regime_level" if "structural_regime_level" in daily.columns else "regime_name" if "regime_name" in daily.columns else None
        if regime_col:
            regime = daily[regime_col].fillna("unknown").astype(str)
            rows.append(
                {
                    "diagnostic": "rebound_day_share",
                    "horizon_days": 0,
                    "sample_count": int(regime.eq("rebound").sum()),
                    "hit_rate": np.nan,
                    "expectancy": np.nan,
                    "avg_directional_excess_return": np.nan,
                    "passed": bool(regime.eq("rebound").mean() <= 0.35),
                    "interpretation": "rebound label is not dominating the sample" if regime.eq("rebound").mean() <= 0.35 else "rebound label may be too broad",
                }
            )
    return pd.DataFrame(rows)


def build_portfolio_constraint_report(
    daily_result: pd.DataFrame | None,
    *,
    min_effective_n: float = GOVERNANCE_RESEARCH_MIN_EFFECTIVE_N,
    max_top1_account_weight: float = GOVERNANCE_RESEARCH_MAX_TOP1_ACCOUNT_WEIGHT,
    max_top5_account_weight_sum: float = GOVERNANCE_RESEARCH_MAX_TOP5_ACCOUNT_WEIGHT_SUM,
    min_sleeve_effective_n_ratio: float = 0.65,
    max_top20pct_sleeve_weight_sum: float = 0.55,
) -> pd.DataFrame:
    """Audit concentration constraints without changing the portfolio."""
    columns = [
        "date",
        "account_effective_n",
        "sleeve_effective_n",
        "sleeve_effective_n_ratio",
        "configured_max_positions",
        "effective_n_required",
        "top1_account_weight",
        "top5_account_weight_sum",
        "top20pct_sleeve_weight_sum",
        "industry_top1_weight",
        "factor_cluster_top1_weight",
        "liquidity_bucket_exposure",
        "holding_count",
        "actual_exposure",
        "constraint_pass",
        "fail_reasons",
        "research_valid",
    ]
    if daily_result is None or daily_result.empty:
        return pd.DataFrame(columns=columns)
    data = daily_result.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    numeric_defaults = {
        "account_effective_n": "effective_n",
        "sleeve_effective_n": "effective_n",
        "sleeve_effective_n_ratio": None,
        "top1_account_weight": "top1_weight",
        "top5_account_weight_sum": "top5_weight_sum",
        "top20pct_sleeve_weight_sum": None,
        "industry_top1_weight": None,
        "factor_cluster_top1_weight": None,
        "liquidity_bucket_exposure": None,
        "holding_count": None,
        "actual_exposure": None,
    }
    for column, fallback in numeric_defaults.items():
        if column not in data.columns and fallback and fallback in data.columns:
            data[column] = data[fallback]
        data[column] = pd.to_numeric(data.get(column, pd.Series(np.nan, index=data.index)), errors="coerce")
    rows = []
    for _, row in data.dropna(subset=["date"]).iterrows():
        configured_max_positions = int(
            _coerce_float(
                row.get(
                    "configured_max_positions",
                    row.get("target_holding_count", row.get("holding_count", 0)),
                )
            )
            or 0
        )
        holding_count = max(int(_coerce_float(row.get("holding_count", 0)) or 0), 0)
        sleeve_effective_n = _coerce_float(row.get("sleeve_effective_n"))
        sleeve_effective_n_ratio = _coerce_float(row.get("sleeve_effective_n_ratio"))
        if not np.isfinite(sleeve_effective_n_ratio):
            sleeve_effective_n_ratio = (
                sleeve_effective_n / holding_count
                if holding_count > 0 and np.isfinite(sleeve_effective_n)
                else 0.0
            )
        effective_n_required = (
            float(min_sleeve_effective_n_ratio) * holding_count
            if holding_count > 0
            else 0.0
        )
        fail_reasons = []
        if holding_count > 0 and (
            not np.isfinite(sleeve_effective_n)
            or sleeve_effective_n < effective_n_required
        ):
            fail_reasons.append("effective_n_below_research_min")
        if holding_count > 0 and sleeve_effective_n_ratio < float(min_sleeve_effective_n_ratio):
            fail_reasons.append("effective_n_ratio_below_research_min")
        # Top-1 remains descriptive across capital scales.  A fixed 25% gate
        # incorrectly rejects a balanced four-name whole-lot portfolio for a
        # sub-percentage rounding difference.  Scale-normalized effective N
        # and top-20% sleeve share are the binding concentration gates.
        top20pct_sleeve = _coerce_float(row.get("top20pct_sleeve_weight_sum"))
        if holding_count > 0 and np.isfinite(top20pct_sleeve) and top20pct_sleeve > float(max_top20pct_sleeve_weight_sum):
            fail_reasons.append("top20pct_sleeve_weight_sum_above_cap")
        rows.append(
            {
                "date": pd.Timestamp(row["date"]),
                "account_effective_n": row["account_effective_n"],
                "sleeve_effective_n": sleeve_effective_n,
                "sleeve_effective_n_ratio": sleeve_effective_n_ratio,
                "configured_max_positions": configured_max_positions,
                "effective_n_required": effective_n_required,
                "top1_account_weight": row["top1_account_weight"],
                "top5_account_weight_sum": row["top5_account_weight_sum"],
                "top20pct_sleeve_weight_sum": top20pct_sleeve,
                "industry_top1_weight": row["industry_top1_weight"],
                "factor_cluster_top1_weight": row["factor_cluster_top1_weight"],
                "liquidity_bucket_exposure": row["liquidity_bucket_exposure"],
                "holding_count": row["holding_count"],
                "actual_exposure": row["actual_exposure"],
                "constraint_pass": not fail_reasons,
                "fail_reasons": "|".join(fail_reasons),
                "research_valid": not fail_reasons,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_entry_failure_timing_report(
    *,
    execution_ledger: pd.DataFrame,
    close_pivot: pd.DataFrame,
    failure_threshold: float = -0.035,
    recovery_threshold: float = 0.015,
    max_horizon_days: int = 60,
) -> pd.DataFrame:
    """Find buys that failed soon after entry and whether exits lagged the signal."""
    columns = [
        "symbol",
        "entry_date",
        "entry_price",
        "entry_reason",
        "entry_matrix_score_at_buy",
        "alpha_quality_at_buy",
        "max_profit_before_failure",
        "max_loss_before_failure",
        "first_failure_signal_date",
        "first_failure_score",
        "actual_exit_date",
        "exit_reason",
        "loss_at_first_failure",
        "loss_at_exit",
        "delay_days",
        "avoidable_loss",
        "should_have_exited_earlier",
        "diagnosis",
    ]
    if execution_ledger is None or execution_ledger.empty or close_pivot.empty:
        return pd.DataFrame(columns=columns)
    trades = execution_ledger.copy()
    trades["trade_date"] = pd.to_datetime(trades.get("trade_date"), errors="coerce")
    trades["symbol"] = trades.get("symbol", pd.Series("", index=trades.index)).astype(str)
    trades["side"] = trades.get("side", pd.Series("", index=trades.index)).astype(str).str.lower()
    trades["price"] = pd.to_numeric(trades.get("price"), errors="coerce")
    trades = trades.dropna(subset=["trade_date", "symbol", "price"]).sort_values(["symbol", "trade_date"])
    sells = trades[trades["side"].eq("sell")].copy()
    rows = []
    for _, buy in trades[trades["side"].eq("buy")].iterrows():
        symbol = str(buy["symbol"])
        if symbol not in close_pivot.columns:
            continue
        entry_date = pd.Timestamp(buy["trade_date"])
        entry_price = float(buy["price"])
        if entry_price <= 0.0:
            continue
        future_sells = sells[(sells["symbol"].eq(symbol)) & (sells["trade_date"] > entry_date)]
        exit_row = future_sells.iloc[0] if not future_sells.empty else None
        exit_date = pd.Timestamp(exit_row["trade_date"]) if exit_row is not None else pd.NaT
        exit_price = float(exit_row["price"]) if exit_row is not None and pd.notna(exit_row["price"]) else np.nan
        path = close_pivot.loc[close_pivot.index >= entry_date, symbol].dropna().head(int(max_horizon_days) + 1)
        if exit_row is not None:
            path = path[path.index <= exit_date]
        if len(path) < 2:
            continue
        rel = path.astype(float) / entry_price - 1.0
        running_mfe = rel.cummax()
        failure_mask = (running_mfe < float(recovery_threshold)) & (rel <= float(failure_threshold))
        if not failure_mask.any():
            continue
        first_failure_date = pd.Timestamp(failure_mask[failure_mask].index[0])
        loss_at_first = float(rel.loc[first_failure_date])
        loss_at_exit = float(exit_price / entry_price - 1.0) if np.isfinite(exit_price) and exit_price > 0.0 else float(rel.iloc[-1])
        delay_days = int(max((exit_date - first_failure_date).days, 0)) if pd.notna(exit_date) else pd.NA
        avoidable_loss = float(loss_at_exit - loss_at_first)
        should_exit = bool(pd.notna(delay_days) and delay_days >= 3 and avoidable_loss < -0.03)
        rows.append(
            {
                "symbol": symbol,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "entry_reason": buy.get("reason", ""),
                "entry_matrix_score_at_buy": buy.get("entry_matrix_score", pd.NA),
                "alpha_quality_at_buy": buy.get("alpha_quality_score", pd.NA),
                "max_profit_before_failure": float(rel.loc[:first_failure_date].max()),
                "max_loss_before_failure": float(rel.loc[:first_failure_date].min()),
                "first_failure_signal_date": first_failure_date,
                "first_failure_score": abs(loss_at_first) / abs(float(failure_threshold)) if failure_threshold else np.nan,
                "actual_exit_date": exit_date,
                "exit_reason": str(exit_row.get("reason", "")) if exit_row is not None else "",
                "loss_at_first_failure": loss_at_first,
                "loss_at_exit": loss_at_exit,
                "delay_days": delay_days,
                "avoidable_loss": avoidable_loss,
                "should_have_exited_earlier": should_exit,
                "diagnosis": "sell_lag_after_failure" if should_exit else "entry_failed_or_exit_timely",
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(["entry_date", "symbol"]).reset_index(drop=True)


def build_entry_gate_policy_report(calibration: pd.DataFrame, payoff_by_regime: pd.DataFrame | None = None) -> pd.DataFrame:
    """Convert calibration buckets into an auditable buy-permission policy table."""
    columns = [
        "regime_name",
        "risk_level",
        "prediction_bucket",
        "sample_count",
        "predicted_p_mean",
        "realized_win_rate",
        "wilson_lower_95",
        "expectancy_10d",
        "forward_excess_10d",
        "allow_buy",
        "max_entry_lots",
        "reason",
    ]
    if calibration is None or calibration.empty:
        return pd.DataFrame(columns=columns)
    data = calibration.copy()
    data["horizon_days"] = pd.to_numeric(data.get("horizon_days"), errors="coerce")
    data = data[data["horizon_days"].eq(10)].copy()
    if data.empty:
        return pd.DataFrame(columns=columns)
    payoff_lookup = _payoff_lookup_by_regime(payoff_by_regime)
    rows = []
    for _, row in data.iterrows():
        regime_name = str(row.get("regime_name", row.get("regime", "all")) or "all")
        prediction_bucket = str(row.get("prediction_bucket", row.get("bucket", "all")) or "all")
        payoff = payoff_lookup.get(regime_name, payoff_lookup.get("all", {}))
        sample_count = int(_coerce_float(row.get("sample_count", row.get("count", 0)), default=0.0))
        predicted = _coerce_float(row.get("predicted_p_mean", row.get("predicted_mean", np.nan)))
        realized = _coerce_float(row.get("realized_win_rate", row.get("actual_win_rate", np.nan)))
        wilson = _coerce_float(row.get("wilson_lower_95", np.nan))
        expectancy = _coerce_float(row.get("expectancy_10d", payoff.get("expectancy", np.nan)))
        excess = _coerce_float(row.get("forward_excess_10d", payoff.get("avg_directional_excess_return", np.nan)))
        reasons = []
        allow_buy = True
        max_lots = 2
        if sample_count < int(GOVERNANCE_ENTRY_CALIBRATION_MIN_BUCKET_SAMPLES):
            allow_buy = False
            max_lots = 0
            reasons.append("sample_count_below_policy_min")
        if np.isfinite(wilson) and wilson < float(GOVERNANCE_ENTRY_CALIBRATION_MIN_WILSON_LOWER):
            allow_buy = False
            max_lots = 0
            reasons.append("wilson_lower_below_policy_min")
        if not np.isfinite(expectancy) or expectancy <= float(GOVERNANCE_ENTRY_CALIBRATION_MIN_EXPECTANCY_10D):
            allow_buy = False
            max_lots = 0
            reasons.append("expectancy_10d_not_positive")
        if np.isfinite(excess) and excess <= 0.0 and allow_buy:
            max_lots = min(max_lots, 1)
            reasons.append("forward_excess_non_positive_limit_to_one_lot")
        if np.isfinite(realized) and np.isfinite(predicted) and realized < predicted - float(GOVERNANCE_ENTRY_CALIBRATION_MAX_OVERCONFIDENCE_GAP):
            max_lots = min(max_lots, 1)
            reasons.append("probability_model_overconfident")
        rows.append(
            {
                "regime_name": regime_name,
                "risk_level": str(row.get("risk_level", "unknown")),
                "prediction_bucket": prediction_bucket,
                "sample_count": sample_count,
                "predicted_p_mean": predicted,
                "realized_win_rate": realized,
                "wilson_lower_95": wilson,
                "expectancy_10d": expectancy,
                "forward_excess_10d": excess,
                "allow_buy": bool(allow_buy),
                "max_entry_lots": int(max_lots),
                "reason": "|".join(reasons) if reasons else "passed",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_research_gate_report(reports: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Top-level research readiness gate assembled from existing diagnostics."""
    rows = []
    payoff = reports.get("governance_entry_payoff_report", pd.DataFrame())
    calibration = reports.get("governance_entry_calibration_report", pd.DataFrame())
    validation = reports.get("governance_factor_validation_report", pd.DataFrame())
    constraints = reports.get("governance_portfolio_constraint_report", pd.DataFrame())
    failures = reports.get("governance_entry_failure_timing_report", pd.DataFrame())
    rolling = reports.get("governance_rolling_beat_report", pd.DataFrame())
    diversity = reports.get("governance_alpha_diversification_report", pd.DataFrame())
    trading_evidence = reports.get("governance_trading_evidence_report", pd.DataFrame())

    if trading_evidence is not None and not trading_evidence.empty:
        evidence = trading_evidence.iloc[-1]
        has_evidence = bool(evidence.get("has_trading_evidence", False))
        value = _coerce_float(evidence.get("avg_actual_exposure", np.nan))
        reason = str(evidence.get("block_reason", ""))
        rows.append(
            _research_gate_row(
                "normal_mode_trading_evidence",
                has_evidence,
                value,
                "closed trades or non-zero average exposure required",
                reason="passed" if has_evidence else reason or "NO_TRADING_EVIDENCE",
            )
        )
    else:
        rows.append(
            _research_gate_row(
                "normal_mode_trading_evidence",
                False,
                np.nan,
                "required",
                reason="NO_TRADING_EVIDENCE_REPORT_MISSING",
            )
        )

    if diversity is not None and not diversity.empty:
        latest_diversity = diversity.iloc[-1]
        passed = bool(latest_diversity.get("pass_flag", False))
        value = _coerce_float(latest_diversity.get("max_module_weight_share", np.nan))
        rows.append(
            _research_gate_row(
                "alpha_diversification_gate",
                passed,
                value,
                "module/family/redundancy limits",
                reason="passed" if passed else str(latest_diversity.get("block_reasons", "failed_alpha_diversification_gate")),
            )
        )
    else:
        rows.append(
            _research_gate_row(
                "alpha_diversification_gate",
                False,
                np.nan,
                "required",
                reason="ALPHA_DIVERSIFICATION_REPORT_MISSING",
            )
        )

    buy10 = payoff[
        pd.to_numeric(payoff.get("horizon_days"), errors="coerce").eq(10)
        & payoff.get("side", pd.Series(dtype=object)).astype(str).eq("buy")
    ] if payoff is not None and not payoff.empty else pd.DataFrame()
    buy_expectancy = _weighted_metric(buy10, "expectancy")
    rows.append(_research_gate_row("buy_expectancy_10d_positive", buy_expectancy > 0.0, buy_expectancy, "> 0"))

    ece10 = calibration[pd.to_numeric(calibration.get("horizon_days"), errors="coerce").eq(10)] if calibration is not None and not calibration.empty else pd.DataFrame()
    ece = float(pd.to_numeric(ece10.get("ece_weighted"), errors="coerce").fillna(0.0).sum()) if not ece10.empty else np.nan
    rows.append(_research_gate_row("entry_calibration_ece", np.isfinite(ece) and ece <= 0.08, ece, "<= 0.08"))

    factor_pass = int(validation.get("pass_flag", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if validation is not None and not validation.empty else 0
    rows.append(_research_gate_row("factor_validation_pass_count", factor_pass >= 5, factor_pass, ">= 5 factor-horizon passes"))

    if constraints is not None and not constraints.empty:
        latest = constraints.sort_values("date").iloc[-1]
        effective_n = _coerce_float(latest.get("sleeve_effective_n", np.nan))
        effective_n_ratio = _coerce_float(
            latest.get("sleeve_effective_n_ratio", np.nan)
        )
        effective_n_required = _coerce_float(latest.get("effective_n_required", 5.0))
        top1_weight = _coerce_float(latest.get("top1_account_weight", np.nan))
        top20pct_weight = _coerce_float(
            latest.get("top20pct_sleeve_weight_sum", np.nan)
        )
        rows.append(_research_gate_row(
            "latest_sleeve_effective_n",
            np.isfinite(effective_n) and np.isfinite(effective_n_required) and effective_n >= effective_n_required,
            effective_n,
            f">= {effective_n_required:g} (active-holding scaled)",
        ))
        rows.append(_research_gate_row(
            "latest_sleeve_effective_n_ratio",
            np.isfinite(effective_n_ratio) and effective_n_ratio >= 0.65,
            effective_n_ratio,
            ">= 0.65",
        ))
        rows.append(_research_gate_row(
            "latest_top1_account_weight_descriptive",
            True,
            top1_weight,
            "descriptive only; normalized breadth gates bind",
            reason="descriptive_only",
        ))
        rows.append(_research_gate_row(
            "latest_top20pct_sleeve_weight_sum",
            np.isfinite(top20pct_weight) and top20pct_weight <= 0.55,
            top20pct_weight,
            "<= 0.55",
        ))
    else:
        rows.append(_research_gate_row("portfolio_constraints_available", False, np.nan, "required"))

    if failures is not None and not failures.empty:
        lag_ratio = float(failures.get("should_have_exited_earlier", pd.Series(False, index=failures.index)).fillna(False).astype(bool).mean())
        rows.append(_research_gate_row("entry_failure_sell_lag_ratio", lag_ratio <= 0.30, lag_ratio, "<= 0.30"))
    else:
        rows.append(_research_gate_row("entry_failure_sell_lag_ratio", True, 0.0, "<= 0.30"))

    roll60 = rolling[
        pd.to_numeric(rolling.get("window_days"), errors="coerce").eq(60)
        & rolling.get("segment", pd.Series("full", index=rolling.index)).astype(str).eq("full")
    ] if rolling is not None and not rolling.empty else pd.DataFrame()
    beat60 = float(pd.to_numeric(roll60.get("account_beat_ratio"), errors="coerce").iloc[0]) if not roll60.empty else np.nan
    rows.append(_research_gate_row("rolling_60d_beat_ratio", np.isfinite(beat60) and beat60 >= 0.52, beat60, ">= 0.52"))

    result = pd.DataFrame(rows)
    critical = result["severity"].eq("critical")
    result["overall_status"] = "research_ready"
    if (critical & ~result["pass_flag"]).any():
        result["overall_status"] = "blocked"
    elif (~result["pass_flag"]).any():
        result["overall_status"] = "exploratory_only"
    return result


def build_strategy_validation_matrix(reports: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Summarize whether high-exposure deployment evidence is internally consistent."""
    calibration = reports.get("governance_entry_calibration_report", pd.DataFrame())
    payoff = reports.get("governance_entry_payoff_report", pd.DataFrame())
    risk = reports.get("governance_risk_contribution_ledger", pd.DataFrame())
    rolling = reports.get("governance_rolling_beat_report", pd.DataFrame())
    lifecycle = reports.get("governance_position_lifecycle_report", pd.DataFrame())
    rebound = reports.get("governance_rebound_entry_diagnostics", pd.DataFrame())

    rows = []
    cal10 = calibration[pd.to_numeric(calibration.get("horizon_days"), errors="coerce").eq(10)] if not calibration.empty else pd.DataFrame()
    if not cal10.empty:
        weighted_ece = float(pd.to_numeric(cal10.get("ece_weighted"), errors="coerce").fillna(0.0).sum())
        best_lower = float(pd.to_numeric(cal10.get("wilson_lower_95"), errors="coerce").max())
        rows.append(_gate_row("entry_probability_calibration", weighted_ece <= 0.06 and best_lower >= 0.48, weighted_ece, "diagnostic only: <=0.06 ECE and best Wilson lower >=0.48"))
        rows.append(_gate_row("entry_probability_lower_bound", best_lower >= 0.50, best_lower, "diagnostic only: >=0.50 lower-bound reference"))
    else:
        rows.append(_gate_row("entry_probability_calibration", False, np.nan, "missing calibration report"))

    buy10 = payoff[
        pd.to_numeric(payoff.get("horizon_days"), errors="coerce").eq(10)
        & payoff.get("side", pd.Series(dtype=object)).astype(str).eq("buy")
    ] if not payoff.empty else pd.DataFrame()
    if not buy10.empty:
        buy_expectancy = float(pd.to_numeric(buy10.get("expectancy"), errors="coerce").mean())
        buy_excess = float(pd.to_numeric(buy10.get("avg_directional_excess_return"), errors="coerce").mean())
        rows.append(_gate_row("buy_10d_expectancy", buy_expectancy > 0.0, buy_expectancy, ">0 after costs/proxy benchmark"))
        rows.append(_gate_row("buy_10d_excess_expectancy", buy_excess > 0.0, buy_excess, ">0 vs top-strength benchmark"))
    else:
        rows.append(_gate_row("buy_10d_expectancy", False, np.nan, "missing executed buy payoff"))

    sell10 = payoff[
        pd.to_numeric(payoff.get("horizon_days"), errors="coerce").eq(10)
        & payoff.get("side", pd.Series(dtype=object)).astype(str).eq("sell")
    ] if not payoff.empty else pd.DataFrame()
    if not sell10.empty:
        sell_expectancy = float(pd.to_numeric(sell10.get("expectancy"), errors="coerce").mean())
        rows.append(_gate_row("sell_10d_directional_expectancy", sell_expectancy > 0.0, sell_expectancy, ">0 means sells avoid forward losses"))

    if not risk.empty and "risk_contribution_share" in risk.columns:
        eligible = risk[
            risk.get("risk_gate_eligible", pd.Series(True, index=risk.index))
            .fillna(False)
            .astype(bool)
        ]
        source = eligible if not eligible.empty else risk
        metric_col = (
            "positive_risk_contribution_share"
            if "positive_risk_contribution_share" in source.columns
            else "risk_contribution_share"
        )
        max_rc = float(pd.to_numeric(source[metric_col], errors="coerce").max())
        rows.append(_gate_row("max_single_name_risk_contribution", max_rc <= 0.35, max_rc, "<=0.35 research, <=0.25 deployment"))
    else:
        rows.append(_gate_row("max_single_name_risk_contribution", False, np.nan, "missing covariance risk contribution report"))

    roll60 = rolling[
        pd.to_numeric(rolling.get("window_days"), errors="coerce").eq(60)
        & rolling.get("segment", pd.Series("full", index=rolling.index)).astype(str).eq("full")
    ] if not rolling.empty else pd.DataFrame()
    if not roll60.empty:
        beat = float(pd.to_numeric(roll60.get("account_beat_ratio"), errors="coerce").iloc[0])
        if np.isfinite(beat):
            rows.append(_gate_row("rolling_60d_top_pool_beat", beat >= 0.50, beat, ">=0.50 vs fixed-N top-liquidity benchmark"))

    if not lifecycle.empty:
        giveback_ratio = float(pd.to_numeric(lifecycle.get("paper_profit_giveback_flag"), errors="coerce").fillna(0.0).mean())
        failure_ratio = float(pd.to_numeric(lifecycle.get("post_entry_failure_flag"), errors="coerce").fillna(0.0).mean())
        rows.append(_gate_row("profit_giveback_unhandled_ratio", giveback_ratio <= 0.25, giveback_ratio, "<=0.25 or sell lifecycle too slow"))
        rows.append(_gate_row("post_entry_failure_ratio", failure_ratio <= 0.25, failure_ratio, "<=0.25 or entry/early-exit loop is weak"))

    if rebound is not None and not rebound.empty:
        r10 = rebound[rebound.get("diagnostic", pd.Series(dtype=object)).astype(str).eq("rebound_buy_10d")]
        if not r10.empty:
            sample_count = float(pd.to_numeric(r10.get("sample_count"), errors="coerce").fillna(0.0).iloc[-1])
            if sample_count > 0:
                value = float(pd.to_numeric(r10.get("expectancy"), errors="coerce").iloc[-1])
                rows.append(_gate_row("rebound_buy_10d_expectancy", value > 0.0, value, ">0 or rebound entries should be blocked/tightened"))

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["gate_status"] = np.where(result["passed"].astype(bool), "pass", "fail")
    result["research_interpretation"] = np.where(
        result["passed"].astype(bool),
        "evidence supports current module",
        "do not rely on this module for high exposure until investigated",
    )
    return result


def _gate_row(name: str, passed: bool, observed_value, threshold: str) -> dict:
    return {
        "gate_name": str(name),
        "passed": bool(passed),
        "observed_value": observed_value,
        "threshold": str(threshold),
    }


def _research_gate_row(
    name: str,
    passed: bool,
    observed_value,
    threshold: str,
    severity: str = "critical",
    reason: str | None = None,
) -> dict:
    return {
        "gate_name": str(name),
        "pass_flag": bool(passed),
        "value": observed_value,
        "threshold": str(threshold),
        "severity": str(severity),
        "reason": str(reason) if reason is not None else ("passed" if bool(passed) else "failed_research_gate"),
    }


def _coerce_float(value, default=np.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result


def _payoff_lookup_by_regime(payoff_by_regime: pd.DataFrame | None) -> dict[str, dict]:
    if payoff_by_regime is None or payoff_by_regime.empty:
        return {}
    data = payoff_by_regime.copy()
    data["horizon_days"] = pd.to_numeric(data.get("horizon_days"), errors="coerce")
    data = data[
        data["horizon_days"].eq(10)
        & data.get("side", pd.Series("buy", index=data.index)).astype(str).eq("buy")
    ].copy()
    if data.empty:
        return {}
    lookup = {}
    for regime, group in data.groupby(data.get("regime_name", pd.Series("all", index=data.index)).fillna("all").astype(str)):
        lookup[str(regime)] = {
            "expectancy": _weighted_metric(group, "expectancy"),
            "avg_directional_excess_return": _weighted_metric(group, "avg_directional_excess_return"),
        }
    lookup["all"] = {
        "expectancy": _weighted_metric(data, "expectancy"),
        "avg_directional_excess_return": _weighted_metric(data, "avg_directional_excess_return"),
    }
    return lookup


def build_rolling_beat_report(attribution_ledger: pd.DataFrame | None, windows=(5, 20, 60, 120, 252)) -> pd.DataFrame:
    if attribution_ledger is None or attribution_ledger.empty:
        return pd.DataFrame()
    required = {"date", "account_net_value", "benchmark_net_value"}
    if not required.issubset(attribution_ledger.columns):
        return pd.DataFrame()
    data = attribution_ledger.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=["date"]).sort_values("date")
    for column in ["account_net_value", "holding_portfolio_net_value", "benchmark_net_value", "excess_net_value"]:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    rows = []
    for window in windows:
        account_return = data["account_net_value"] / data["account_net_value"].shift(int(window)) - 1.0
        benchmark_return = data["benchmark_net_value"] / data["benchmark_net_value"].shift(int(window)) - 1.0
        holding_return = (
            data["holding_portfolio_net_value"] / data["holding_portfolio_net_value"].shift(int(window)) - 1.0
            if "holding_portfolio_net_value" in data.columns
            else pd.Series(np.nan, index=data.index)
        )
        valid = account_return.notna() & benchmark_return.notna()
        valid_holding = holding_return.notna() & benchmark_return.notna()
        rows.append(
            {
                "window_days": int(window),
                "window_count": int(valid.sum()),
                "account_beat_ratio": float((account_return[valid] > benchmark_return[valid]).mean()) if valid.any() else np.nan,
                "account_avg_rolling_excess": float((account_return[valid] - benchmark_return[valid]).mean()) if valid.any() else np.nan,
                "holding_beat_ratio": float((holding_return[valid_holding] > benchmark_return[valid_holding]).mean()) if valid_holding.any() else np.nan,
                "holding_avg_rolling_excess": float((holding_return[valid_holding] - benchmark_return[valid_holding]).mean()) if valid_holding.any() else np.nan,
            }
        )
    for year, group in data.groupby(data["date"].dt.year):
        account_return = group["account_net_value"] / group["account_net_value"].shift(60) - 1.0
        benchmark_return = group["benchmark_net_value"] / group["benchmark_net_value"].shift(60) - 1.0
        valid = account_return.notna() & benchmark_return.notna()
        rows.append(
            {
                "window_days": 60,
                "segment": f"year_{int(year)}",
                "window_count": int(valid.sum()),
                "account_beat_ratio": float((account_return[valid] > benchmark_return[valid]).mean()) if valid.any() else np.nan,
                "account_avg_rolling_excess": float((account_return[valid] - benchmark_return[valid]).mean()) if valid.any() else np.nan,
                "holding_beat_ratio": np.nan,
                "holding_avg_rolling_excess": np.nan,
            }
        )
    result = pd.DataFrame(rows)
    if "segment" not in result.columns:
        result["segment"] = "full"
    result["segment"] = result["segment"].fillna("full")
    return result


def build_entry_calibration_report(
    *,
    ideal_portfolio_plan: pd.DataFrame,
    close_pivot: pd.DataFrame,
    benchmark_forward_returns: dict[int, pd.Series],
    horizons=(5, 10, 20),
) -> pd.DataFrame:
    if ideal_portfolio_plan is None or ideal_portfolio_plan.empty:
        return pd.DataFrame()
    data = ideal_portfolio_plan.copy()
    data["decision_date"] = pd.to_datetime(data.get("decision_date"), errors="coerce")
    data["symbol"] = data.get("symbol", pd.Series(dtype=object)).astype(str)
    rows = []
    for horizon in horizons:
        pred_col = f"p_win_{horizon}d_calibrated"
        if pred_col not in data.columns and horizon == 20:
            pred_col = "p_win_10d_calibrated"
        if pred_col not in data.columns:
            continue
        outcomes = _attach_forward_outcomes(
            data,
            close_pivot=close_pivot,
            benchmark_forward_returns=benchmark_forward_returns,
            horizon=horizon,
            price_column=None,
        )
        if outcomes.empty:
            continue
        outcomes["predicted_p"] = pd.to_numeric(outcomes[pred_col], errors="coerce")
        outcomes = outcomes.dropna(subset=["predicted_p", "forward_return"])
        if outcomes.empty:
            continue
        outcomes["prediction_bucket"] = pd.cut(
            outcomes["predicted_p"].clip(0.0, 1.0),
            bins=PREDICTION_BUCKETS,
            labels=PREDICTION_LABELS,
            include_lowest=True,
        ).astype(str)
        for bucket, group in outcomes.groupby("prediction_bucket", dropna=False):
            if group.empty:
                continue
            wins = group["forward_return"] > 0.0
            realized = float(wins.mean())
            pred = float(group["predicted_p"].mean())
            rows.append(
                {
                    "horizon_days": int(horizon),
                    "prediction_bucket": str(bucket),
                    "sample_count": int(len(group)),
                    "predicted_p_mean": pred,
                    "realized_win_rate": realized,
                    "wilson_lower_95": _wilson_lower(int(wins.sum()), int(len(group))),
                    "brier_score": float(np.mean(np.square(group["predicted_p"].to_numpy(dtype=float) - wins.astype(float).to_numpy()))),
                    "ece_component": float(abs(realized - pred) * len(group)),
                    "avg_forward_return": float(group["forward_return"].mean()),
                    "avg_forward_excess_return": float(group["forward_excess_return"].mean()),
                    "avg_win": _mean_positive(group["forward_return"]),
                    "avg_loss": _mean_loss_abs(group["forward_return"]),
                    "payoff_ratio": _payoff_ratio(group["forward_return"]),
                    "expectancy": _expectancy(group["forward_return"]),
                }
            )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    total_by_horizon = result.groupby("horizon_days")["sample_count"].transform("sum").replace(0, np.nan)
    result["ece_weighted"] = result["ece_component"] / total_by_horizon
    return result.drop(columns=["ece_component"]).sort_values(["horizon_days", "prediction_bucket"]).reset_index(drop=True)


def build_entry_payoff_report(
    *,
    execution_ledger: pd.DataFrame,
    close_pivot: pd.DataFrame,
    benchmark_forward_returns: dict[int, pd.Series],
    horizons=(5, 10, 20),
) -> pd.DataFrame:
    if execution_ledger is None or execution_ledger.empty:
        return pd.DataFrame()
    data = execution_ledger.copy()
    data["decision_date"] = pd.to_datetime(data.get("trade_date"), errors="coerce")
    data["symbol"] = data.get("symbol", pd.Series(dtype=object)).astype(str)
    data["side"] = data.get("side", pd.Series(dtype=object)).astype(str)
    rows = []
    for horizon in horizons:
        outcomes = _attach_forward_outcomes(
            data,
            close_pivot=close_pivot,
            benchmark_forward_returns=benchmark_forward_returns,
            horizon=horizon,
            price_column="price",
        )
        if outcomes.empty:
            continue
        outcomes["correct"] = np.where(
            outcomes["side"].eq("buy"),
            outcomes["forward_return"] > 0.0,
            outcomes["forward_return"] < 0.0,
        )
        for keys, group in outcomes.groupby(["side", "reason"], dropna=False):
            side, reason = keys
            rows.append(_payoff_row(group, horizon=horizon, layer="executed", side=side, reason=reason))
    return _rows_frame(rows, sort_by=["horizon_days", "side", "sample_count"], ascending=[True, True, False])


def build_selection_funnel_attribution(
    *,
    ideal_portfolio_plan: pd.DataFrame,
    execution_ledger: pd.DataFrame,
    close_pivot: pd.DataFrame,
    benchmark_forward_returns: dict[int, pd.Series],
    horizons=(5, 10, 20),
) -> pd.DataFrame:
    frames = []
    if ideal_portfolio_plan is not None and not ideal_portfolio_plan.empty:
        ideal = ideal_portfolio_plan.copy()
        ideal["decision_date"] = pd.to_datetime(ideal.get("decision_date"), errors="coerce")
        ideal["symbol"] = ideal.get("symbol", pd.Series(dtype=object)).astype(str)
        ideal["layer"] = "ideal_selected"
        frames.append(ideal)
    if execution_ledger is not None and not execution_ledger.empty:
        executed = execution_ledger[execution_ledger.get("side", "").astype(str).eq("buy")].copy()
        if not executed.empty:
            executed["decision_date"] = pd.to_datetime(executed.get("trade_date"), errors="coerce")
            executed["symbol"] = executed.get("symbol", pd.Series(dtype=object)).astype(str)
            executed["layer"] = "executed_buy"
            frames.append(executed)
    if not frames:
        return pd.DataFrame()
    rows = []
    data = pd.concat([frame.dropna(axis=1, how="all") for frame in frames], ignore_index=True, sort=False)
    for horizon in horizons:
        outcomes = _attach_forward_outcomes(
            data,
            close_pivot=close_pivot,
            benchmark_forward_returns=benchmark_forward_returns,
            horizon=horizon,
            price_column="price" if "price" in data.columns else None,
        )
        if outcomes.empty:
            continue
        for layer, group in outcomes.groupby("layer", dropna=False):
            rows.append(_payoff_row(group, horizon=horizon, layer=layer, side="", reason=""))
    return _rows_frame(rows, sort_by=["horizon_days", "layer"])


def build_entry_payoff_by_regime(
    *,
    execution_ledger: pd.DataFrame,
    daily_result: pd.DataFrame | None,
    close_pivot: pd.DataFrame,
    benchmark_forward_returns: dict[int, pd.Series],
    horizons=(5, 10, 20),
) -> pd.DataFrame:
    if execution_ledger is None or execution_ledger.empty:
        return pd.DataFrame()
    data = execution_ledger.copy()
    data["decision_date"] = pd.to_datetime(data.get("trade_date"), errors="coerce")
    data["symbol"] = data.get("symbol", pd.Series(dtype=object)).astype(str)
    data["side"] = data.get("side", pd.Series(dtype=object)).astype(str)
    regime_map = _regime_map(daily_result)
    data["regime_name"] = data["decision_date"].dt.normalize().map(regime_map).fillna("unknown")
    rows = []
    for horizon in horizons:
        outcomes = _attach_forward_outcomes(
            data,
            close_pivot=close_pivot,
            benchmark_forward_returns=benchmark_forward_returns,
            horizon=horizon,
            price_column="price",
        )
        if outcomes.empty:
            continue
        outcomes["correct"] = np.where(
            outcomes["side"].eq("buy"),
            outcomes["forward_return"] > 0.0,
            outcomes["forward_return"] < 0.0,
        )
        for keys, group in outcomes.groupby(["regime_name", "side"], dropna=False):
            regime_name, side = keys
            row = _payoff_row(group, horizon=horizon, layer="executed_regime", side=side, reason=str(regime_name))
            row["regime_name"] = str(regime_name)
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return _rows_frame(rows, sort_by=["horizon_days", "regime_name", "side"])


def build_entry_decision_audit(
    *,
    ideal_portfolio_plan: pd.DataFrame,
    execution_ledger: pd.DataFrame,
    close_pivot: pd.DataFrame,
    benchmark_forward_returns: dict[int, pd.Series],
    horizon: int = 10,
) -> pd.DataFrame:
    if ideal_portfolio_plan is None or ideal_portfolio_plan.empty:
        return pd.DataFrame()
    data = ideal_portfolio_plan.copy()
    data["decision_date"] = pd.to_datetime(data.get("decision_date"), errors="coerce")
    data["symbol"] = data.get("symbol", pd.Series(dtype=object)).astype(str)
    data = _attach_forward_outcomes(
        data,
        close_pivot=close_pivot,
        benchmark_forward_returns=benchmark_forward_returns,
        horizon=int(horizon),
        price_column=None,
    )
    if data.empty:
        return pd.DataFrame()
    executed_keys = set()
    if execution_ledger is not None and not execution_ledger.empty:
        trades = execution_ledger.copy()
        trades["trade_date"] = pd.to_datetime(trades.get("trade_date"), errors="coerce")
        trades = trades[trades.get("side", pd.Series(dtype=object)).astype(str).eq("buy")]
        if "decision_id" in trades.columns and "decision_id" in data.columns:
            executed_keys = {(str(row["decision_id"]), str(row["symbol"])) for _, row in trades.iterrows()}
            data["executed_buy"] = [
                (str(row.get("decision_id", "")), str(row["symbol"])) in executed_keys
                for _, row in data.iterrows()
            ]
        else:
            executed_keys = {
                (pd.Timestamp(row["trade_date"]).normalize(), str(row["symbol"]))
                for _, row in trades.dropna(subset=["trade_date"]).iterrows()
            }
            data["executed_buy"] = [
                (pd.Timestamp(row["decision_date"]).normalize(), str(row["symbol"])) in executed_keys
                for _, row in data.iterrows()
            ]
    if "executed_buy" not in data.columns:
        data["executed_buy"] = False
    keep = [
        "decision_id",
        "decision_date",
        "symbol",
        "ideal_weight",
        "executed_buy",
        "alpha_percentile",
        "p_win_10d_calibrated",
        "p_win_10d_wilson_lower",
        "expected_edge_10d",
        "conservative_expected_edge_10d",
        "edge_to_risk_10d",
        "conservative_edge_to_risk_10d",
        "entry_evidence_grade",
        "entry_confirmed",
        "entry_block_reason",
        "forward_return",
        "forward_excess_return",
        "forward_benchmark_return",
    ]
    for column in keep:
        if column not in data.columns:
            data[column] = pd.NA
    return data[keep].sort_values(["decision_date", "ideal_weight"], ascending=[True, False]).reset_index(drop=True)


def build_position_lifecycle_report(
    *,
    execution_ledger: pd.DataFrame,
    close_pivot: pd.DataFrame,
    benchmark_forward_returns: dict[int, pd.Series],
    max_horizon_days: int = 90,
) -> pd.DataFrame:
    if execution_ledger is None or execution_ledger.empty or close_pivot.empty:
        return pd.DataFrame()
    trades = execution_ledger.copy()
    trades["trade_date"] = pd.to_datetime(trades.get("trade_date"), errors="coerce")
    trades["symbol"] = trades.get("symbol", pd.Series(dtype=object)).astype(str)
    trades["side"] = trades.get("side", pd.Series(dtype=object)).astype(str)
    trades["price"] = pd.to_numeric(trades.get("price"), errors="coerce")
    trades = trades.dropna(subset=["trade_date", "symbol", "price"])
    if trades.empty:
        return pd.DataFrame()
    sells = trades[trades["side"].eq("sell")].sort_values(["symbol", "trade_date"])
    rows = []
    for _, buy in trades[trades["side"].eq("buy")].sort_values(["trade_date", "symbol"]).iterrows():
        symbol = str(buy["symbol"])
        entry_date = pd.Timestamp(buy["trade_date"])
        entry_price = float(buy["price"])
        if entry_price <= 0.0 or symbol not in close_pivot.columns:
            continue
        future_sells = sells[(sells["symbol"].eq(symbol)) & (sells["trade_date"] > entry_date)]
        exit_date = pd.Timestamp(future_sells.iloc[0]["trade_date"]) if not future_sells.empty else None
        path = close_pivot.loc[close_pivot.index >= entry_date, symbol].dropna().head(int(max_horizon_days) + 1)
        if exit_date is not None:
            path = path[path.index <= exit_date]
        if path.empty:
            continue
        rel = path.astype(float) / entry_price - 1.0
        mfe = float(rel.max())
        mae = float(rel.min())
        end_return = float(rel.iloc[-1])
        giveback = float((mfe - end_return) / max(mfe, 1e-12)) if mfe > 0.0 else 0.0
        benchmark_10d = benchmark_forward_returns.get(10, pd.Series(dtype=float))
        rows.append(
            {
                "entry_date": entry_date,
                "symbol": symbol,
                "entry_price": entry_price,
                "entry_reason": buy.get("reason", ""),
                "observed_days": int(len(path)),
                "exit_date": exit_date if exit_date is not None else pd.NaT,
                "exit_reason": str(future_sells.iloc[0].get("reason", "")) if not future_sells.empty else "",
                "end_return": end_return,
                "mfe": mfe,
                "mae": mae,
                "giveback_from_peak": giveback,
                "benchmark_forward_10d": float(benchmark_10d.get(entry_date.normalize(), 0.0)) if not benchmark_10d.empty else 0.0,
                "paper_profit_giveback_flag": bool(mfe >= 0.08 and giveback >= 0.45),
                "post_entry_failure_flag": bool(len(path) >= 8 and mfe < 0.015 and end_return < -0.035),
            }
        )
    return _rows_frame(rows, sort_by=["entry_date", "symbol"])


def build_capacity_stress_report(
    *,
    executable_order_plan: pd.DataFrame,
    execution_ledger: pd.DataFrame,
    capital_multipliers=(1, 5, 10, 20),
    participation_limit: float = 0.05,
    min_order_notional: float = 3000.0,
) -> pd.DataFrame:
    source = execution_ledger if execution_ledger is not None and not execution_ledger.empty else executable_order_plan
    if source is None or source.empty:
        return pd.DataFrame()
    data = source.copy()
    notional = pd.to_numeric(data.get("trade_notional", pd.Series(dtype=float)), errors="coerce").abs()
    if notional.empty:
        notional = pd.to_numeric(data.get("delta_weight", pd.Series(dtype=float)), errors="coerce").abs() * 1_000_000.0
    market_amount = pd.to_numeric(data.get("market_amount", pd.Series(np.nan, index=data.index)), errors="coerce")
    rows = []
    for multiplier in capital_multipliers:
        scaled_notional = notional.fillna(0.0) * float(multiplier)
        participation = scaled_notional / market_amount.replace(0.0, np.nan)
        rows.append(
            {
                "capital_multiplier": float(multiplier),
                "order_count": int(len(data)),
                "avg_order_notional": float(scaled_notional.mean()) if len(scaled_notional) else 0.0,
                "median_order_notional": float(scaled_notional.median()) if len(scaled_notional) else 0.0,
                "small_order_ratio": float((scaled_notional < float(min_order_notional)).mean()) if len(scaled_notional) else 0.0,
                "avg_participation_rate": float(participation.replace([np.inf, -np.inf], np.nan).mean()),
                "p95_participation_rate": float(participation.replace([np.inf, -np.inf], np.nan).quantile(0.95)),
                "participation_breach_ratio": float((participation > float(participation_limit)).mean()),
                "capacity_passed": bool((participation.fillna(0.0) <= float(participation_limit)).mean() >= 0.95),
            }
        )
    return pd.DataFrame(rows)


def build_risk_contribution_ledger(
    *,
    ideal_portfolio_plan: pd.DataFrame,
    return_pivot: pd.DataFrame | None,
    lookback_days: int = 60,
    min_gate_weight: float = 0.002,
) -> pd.DataFrame:
    if ideal_portfolio_plan is None or ideal_portfolio_plan.empty or return_pivot is None or return_pivot.empty:
        return pd.DataFrame()
    data = ideal_portfolio_plan.copy()
    data["decision_date"] = pd.to_datetime(data.get("decision_date"), errors="coerce")
    data["symbol"] = data.get(
        "symbol", pd.Series("", index=data.index, dtype=object)
    ).astype(str)
    # Legacy plans call this quantity ``ideal_weight``.  SCAP-V3 Lean's
    # authoritative ActionPlan calls the same post-plan quantity
    # ``target_weight``.  Keep the reporting adapter here and always provide a
    # Series default: pd.to_numeric(np.nan) is a scalar and cannot be fillna'd.
    weight_source = data.get(
        "ideal_weight",
        data.get("target_weight", pd.Series(0.0, index=data.index, dtype=float)),
    )
    data["ideal_weight"] = pd.to_numeric(
        weight_source, errors="coerce"
    ).fillna(0.0)
    rows = []
    for date, group in data.groupby("decision_date", sort=True):
        symbols = [s for s in group["symbol"].astype(str).tolist() if s in return_pivot.columns]
        if len(symbols) < 2:
            continue
        returns = return_pivot.loc[return_pivot.index < pd.Timestamp(date), symbols].tail(int(lookback_days))
        returns = returns.dropna(axis=1, thresh=max(10, int(lookback_days * 0.5))).dropna(how="all")
        if returns.shape[1] < 2:
            continue
        cov = returns.cov().astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        valid = [s for s in group["symbol"].astype(str).tolist() if s in cov.index]
        if len(valid) < 2:
            continue
        weights = group.set_index("symbol").loc[valid, "ideal_weight"].to_numpy(dtype=float)
        total_account_exposure = float(max(weights.sum(), 0.0))
        raw_sigma = cov.loc[valid, valid].to_numpy(dtype=float)
        sigma = 0.70 * raw_sigma + 0.30 * np.diag(np.diag(raw_sigma))
        rc = _risk_contribution(weights, sigma)
        marginal = sigma @ weights if weights.size else np.array([])
        positive_rc = np.clip(np.asarray(rc, dtype=float), 0.0, None)
        positive_total = float(positive_rc.sum())
        normalized_rc = (
            positive_rc / positive_total
            if positive_total > 0.0
            else np.zeros_like(positive_rc)
        )
        risk_hhi = float(np.square(normalized_rc).sum()) if normalized_rc.size else 0.0
        risk_effective_n = float(1.0 / risk_hhi) if risk_hhi > 0.0 else 0.0
        risk_effective_n_ratio = (
            float(risk_effective_n / len(valid)) if valid else 0.0
        )
        top_fraction_count = max(int(np.ceil(0.20 * len(valid))), 1)
        top20pct_risk_sum = float(
            np.sort(normalized_rc)[::-1][:top_fraction_count].sum()
        )
        for symbol, weight, marginal_risk, rc_share in zip(valid, weights, marginal, rc):
            positive_share = float(max(rc_share, 0.0))
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "symbol": symbol,
                    "target_weight": float(weight),
                    "marginal_risk": float(marginal_risk),
                    "risk_contribution_share": float(rc_share),
                    "positive_risk_contribution_share": positive_share,
                    "account_exposure_scaled_risk_share": positive_share * total_account_exposure,
                    "total_account_exposure": total_account_exposure,
                    "risk_gate_eligible": bool(float(weight) >= float(min_gate_weight)),
                    "risk_effective_n": risk_effective_n,
                    "risk_effective_n_ratio": risk_effective_n_ratio,
                    "risk_contribution_hhi": risk_hhi,
                    "top20pct_risk_contribution_sum": top20pct_risk_sum,
                    "covariance_shrinkage_contract": "70pct_sample_plus_30pct_diagonal",
                }
            )
    return pd.DataFrame(rows)


def build_factor_redundancy_report(alpha_proposals: pd.DataFrame, max_rows: int = 200_000, runtime_context=None) -> pd.DataFrame:
    if alpha_proposals is None or alpha_proposals.empty:
        return pd.DataFrame()
    required = {"decision_date", "symbol", "model_name", "predicted_return_5d"}
    if not required.issubset(alpha_proposals.columns):
        return pd.DataFrame()
    data = alpha_proposals[list(required)].copy()
    if len(data) > int(max_rows):
        data = data.sample(n=int(max_rows), random_state=7)
    data["row_key"] = pd.to_datetime(data["decision_date"], errors="coerce").astype(str) + "|" + data["symbol"].astype(str)
    data["predicted_return_5d"] = pd.to_numeric(data["predicted_return_5d"], errors="coerce")
    pivot = data.pivot_table(index="row_key", columns="model_name", values="predicted_return_5d", aggfunc="mean")
    corr = pivot.corr(method="spearman", min_periods=30)
    rows = []
    for model in corr.columns:
        peers = corr[model].drop(labels=[model], errors="ignore").dropna()
        rows.append(
            {
                "model_name": model,
                "sample_rows": int(pivot[model].notna().sum()),
                "avg_abs_rank_corr_to_others": float(peers.abs().mean()) if not peers.empty else 0.0,
                "max_abs_rank_corr_to_other": float(peers.abs().max()) if not peers.empty else 0.0,
                "most_redundant_peer": str(peers.abs().idxmax()) if not peers.empty else "",
                "redundancy_flag": bool((peers.abs().max() if not peers.empty else 0.0) >= 0.85),
            }
        )
    return _rows_frame(rows, sort_by=["max_abs_rank_corr_to_other"], ascending=False)


def build_alpha_diversification_report(alpha_proposals: pd.DataFrame, runtime_context=None) -> pd.DataFrame:
    """Gate whether a candidate alpha bundle is diverse enough for trading use."""
    rules = dict(GOVERNANCE_ALPHA_DIVERSIFICATION_RULES)
    columns = [
        "factor_count",
        "distinct_modules",
        "distinct_families",
        "max_module_weight_share",
        "max_module_factor_count",
        "max_family_count",
        "redundancy_flag_ratio",
        "max_pairwise_rank_corr",
        "range_grid_weight_share",
        "pass_flag",
        "block_reasons",
    ]
    if alpha_proposals is None or alpha_proposals.empty or "model_name" not in alpha_proposals.columns:
        return pd.DataFrame(
            [{
                "factor_count": 0,
                "distinct_modules": 0,
                "distinct_families": 0,
                "max_module_weight_share": 0.0,
                "max_module_factor_count": 0,
                "max_family_count": 0,
                "redundancy_flag_ratio": 1.0,
                "max_pairwise_rank_corr": np.nan,
                "range_grid_weight_share": 0.0,
                "pass_flag": False,
                "block_reasons": "alpha_proposals_missing",
            }],
            columns=columns,
        )
    models = sorted(alpha_proposals["model_name"].dropna().astype(str).unique().tolist())
    if not models:
        return pd.DataFrame(
            [{
                "factor_count": 0,
                "distinct_modules": 0,
                "distinct_families": 0,
                "max_module_weight_share": 0.0,
                "max_module_factor_count": 0,
                "max_family_count": 0,
                "redundancy_flag_ratio": 1.0,
                "max_pairwise_rank_corr": np.nan,
                "range_grid_weight_share": 0.0,
                "pass_flag": False,
                "block_reasons": "alpha_models_missing",
            }],
            columns=columns,
        )
    module_map = getattr(runtime_context, "module_map", None) or {}
    family_map = getattr(runtime_context, "family_map", None) or {}
    modules = pd.Series({model: module_map.get(model, factor_module(model)) for model in models})
    families = pd.Series({model: family_map.get(model, _factor_family(model)) for model in models})
    weights = pd.Series(
        {
            model: float(GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS.get(model, 1.0))
            for model in models
        },
        dtype=float,
    ).clip(lower=0.0)
    if float(weights.sum()) <= 0.0:
        weights = pd.Series(1.0, index=models, dtype=float)
    module_counts = modules.value_counts()
    family_counts = families.value_counts()
    module_weight_share = weights.groupby(modules).sum() / max(float(weights.sum()), 1e-12)
    factor_count = int(len(models))
    max_module_count = int(module_counts.max()) if not module_counts.empty else 0
    max_family_count = int(family_counts.max()) if not family_counts.empty else 0
    max_module_share = float(module_weight_share.max()) if not module_weight_share.empty else 0.0
    range_grid_share = float(module_weight_share.get("range_grid", 0.0))

    redundancy = build_factor_redundancy_report(alpha_proposals, runtime_context=runtime_context)
    if redundancy.empty:
        redundancy_ratio = 1.0
        max_pairwise_corr = np.nan
    else:
        redundancy_ratio = float(redundancy.get("redundancy_flag", pd.Series(False, index=redundancy.index)).fillna(False).astype(bool).mean())
        max_pairwise_corr = _coerce_float(pd.to_numeric(redundancy.get("max_abs_rank_corr_to_other"), errors="coerce").max())

    block_reasons = []
    if int(module_counts.size) < int(rules["min_distinct_modules"]):
        block_reasons.append("distinct_modules_below_min")
    if int(family_counts.size) < int(rules["min_distinct_families"]):
        block_reasons.append("distinct_families_below_min")
    if max_module_share > float(rules["max_module_weight_share"]):
        block_reasons.append("module_weight_share_above_cap")
    if max_module_count > int(rules["max_module_factor_count"]):
        block_reasons.append("module_factor_count_above_cap")
    if max_family_count > int(rules["max_family_count"]):
        block_reasons.append("family_count_above_cap")
    if redundancy_ratio > float(rules["max_redundancy_flag_ratio"]):
        block_reasons.append("redundancy_flag_ratio_above_cap")
    if np.isfinite(max_pairwise_corr) and max_pairwise_corr > float(rules["max_pairwise_rank_corr"]):
        block_reasons.append("pairwise_rank_corr_above_cap")
    if range_grid_share > float(rules["range_grid_max_weight_share"]):
        block_reasons.append("range_grid_weight_share_above_cap")
    return pd.DataFrame(
        [{
            "factor_count": factor_count,
            "distinct_modules": int(module_counts.size),
            "distinct_families": int(family_counts.size),
            "max_module_weight_share": float(max_module_share),
            "max_module_factor_count": max_module_count,
            "max_family_count": max_family_count,
            "redundancy_flag_ratio": float(redundancy_ratio),
            "max_pairwise_rank_corr": max_pairwise_corr,
            "range_grid_weight_share": float(range_grid_share),
            "pass_flag": not block_reasons,
            "block_reasons": "|".join(block_reasons) if block_reasons else "passed",
        }],
        columns=columns,
    )


def build_trading_evidence_report(
    *,
    daily_result: pd.DataFrame | None,
    execution_ledger: pd.DataFrame | None,
) -> pd.DataFrame:
    """Detect empty normal-mode runs so zero-return cash stays blocked."""
    daily = daily_result.copy() if daily_result is not None else pd.DataFrame()
    execution = execution_ledger.copy() if execution_ledger is not None else pd.DataFrame()
    avg_exposure = (
        _coerce_float(pd.to_numeric(daily.get("actual_exposure"), errors="coerce").fillna(0.0).mean(), default=0.0)
        if not daily.empty and "actual_exposure" in daily.columns
        else 0.0
    )
    max_exposure = (
        _coerce_float(pd.to_numeric(daily.get("actual_exposure"), errors="coerce").fillna(0.0).max(), default=0.0)
        if not daily.empty and "actual_exposure" in daily.columns
        else 0.0
    )
    trade_count = int(len(execution)) if execution is not None and not execution.empty else 0
    filled_count = int(
        execution.get("execution_status", pd.Series("", index=execution.index))
        .fillna("")
        .astype(str)
        .str.lower()
        .eq("filled")
        .sum()
    ) if trade_count else 0
    has_evidence = bool(filled_count > 0 or avg_exposure > 1e-6 or max_exposure > 1e-6)
    return pd.DataFrame(
        [{
            "trade_count": trade_count,
            "filled_trade_count": filled_count,
            "avg_actual_exposure": float(avg_exposure),
            "max_actual_exposure": float(max_exposure),
            "has_trading_evidence": has_evidence,
            "block_reason": "passed" if has_evidence else "NO_TRADING_EVIDENCE",
        }]
    )


def build_factor_role_report(alpha_proposals: pd.DataFrame, runtime_context=None) -> pd.DataFrame:
    if alpha_proposals is None or alpha_proposals.empty or "model_name" not in alpha_proposals.columns:
        return pd.DataFrame()
    models = sorted(str(name) for name in alpha_proposals["model_name"].dropna().astype(str).unique())
    rows = []
    for model in models:
        module = (getattr(runtime_context, "module_map", None) or {}).get(model, factor_module(model))
        role = _factor_role(model, module)
        configured_roles = tuple(
            str(item)
            for item in (getattr(runtime_context, "role_map", None) or GOVERNANCE_DIVERSIFIED_PRE_SCREEN_BUNDLE_V2_ROLE_MAP).get(model, ())
        )
        if configured_roles:
            role = {
                **role,
                "primary_role": configured_roles[0],
                "buy_use_allowed": "entry_alpha" in configured_roles or "timing_filter" in configured_roles,
                "hold_validation_allowed": "hold_validation" in configured_roles,
                "sell_trigger_allowed": "sell_trigger" in configured_roles,
                "risk_override_allowed": "risk_override" in configured_roles,
                "role_rationale": "configured governance factor source state-machine roles: "
                + "|".join(configured_roles),
            }
        rows.append(
            {
                "model_name": model,
                "factor_module": module,
                "primary_role": role["primary_role"],
                "buy_use_allowed": role["buy_use_allowed"],
                "hold_validation_allowed": role["hold_validation_allowed"],
                "sell_trigger_allowed": role["sell_trigger_allowed"],
                "risk_override_allowed": role["risk_override_allowed"],
                "role_rationale": role["role_rationale"],
            }
        )
    return pd.DataFrame(rows)


def _factor_family(model_name: str) -> str:
    name = str(model_name).lower()
    if name.startswith("candidate_grid_rank_ratio__rev") and "amihud" in name:
        return "rev_amihud_ratio_grid"
    if name.startswith("candidate_grid_rank_spread__rev") and "amihud" in name:
        return "rev_amihud_spread_grid"
    if name.startswith("candidate_grid_rank_product__ret") and "__rev_" in name:
        return "ret_reversal_interaction_grid"
    if name.startswith("candidate_grid_rank_product__rev") and "__rev_" in name:
        return "reversal_interaction_grid"
    if name.startswith("candidate_grid_rank_product__rev") and "__size_" in name:
        return "rev_size_interaction_grid"
    if name.startswith("candidate_grid_rank_gate_hi__ret") and "__size_" in name:
        return "ret_size_conditional_grid"
    if name.startswith("candidate_grid_rank_gate_hi__rev") and "__size_" in name:
        return "rev_size_conditional_grid"
    if name.startswith("candidate_grid_rank_mean__rev") and "__rev_" in name:
        return "short_medium_reversal_blend_grid"
    if name.startswith("candidate_grid_base_rank__rev"):
        return "single_reversal_grid"
    if name.startswith("candidate_grid_base_rank__vol"):
        return "single_volatility_grid"
    if name.startswith("candidate_grid_base_rank__downvol"):
        return "single_downside_volatility_grid"
    if name.startswith("candidate_size_") or name.startswith("candidate_grid_base_rank__size"):
        return "size_style"
    if name.startswith("candidate_idiosyncratic_vol"):
        return "idiosyncratic_volatility_defense"
    if name.startswith("candidate_downside_volatility"):
        return "downside_volatility_defense"
    if "size_total" in name or "size_float" in name:
        return "size_conditioned_grid"
    if "volatility" in name or "vol_neg" in name or "idiosyncratic_vol" in name:
        return "volatility_defense"
    if "orderflow" in name or "volume" in name or "close_strength" in name:
        return "flow_close"
    if "limit" in name or "event" in name or "holiday" in name:
        return "event_limit"
    if "momentum" in name or "macd" in name or "breakout" in name or "ma_" in name:
        return "trend"
    if "reversal" in name or "decline" in name or "oversold" in name or "pullback" in name:
        return "reversal_pullback"
    tokens = name.split("__")
    return tokens[0] if tokens else name


def _attach_forward_outcomes(
    data: pd.DataFrame,
    *,
    close_pivot: pd.DataFrame,
    benchmark_forward_returns: dict[int, pd.Series],
    horizon: int,
    price_column: str | None,
) -> pd.DataFrame:
    if close_pivot.empty or data.empty:
        return pd.DataFrame()
    out = data.copy()
    dates = pd.to_datetime(out["decision_date"], errors="coerce")
    symbols = out["symbol"].astype(str)
    entry_prices = []
    exit_prices = []
    for date, symbol in zip(dates, symbols):
        if pd.isna(date) or symbol not in close_pivot.columns:
            entry_prices.append(np.nan)
            exit_prices.append(np.nan)
            continue
        path = close_pivot.loc[close_pivot.index >= pd.Timestamp(date), symbol].dropna()
        if len(path) <= int(horizon):
            entry_prices.append(np.nan)
            exit_prices.append(np.nan)
            continue
        entry_prices.append(float(path.iloc[0]))
        exit_prices.append(float(path.iloc[int(horizon)]))
    if price_column and price_column in out.columns:
        supplied = pd.to_numeric(out[price_column], errors="coerce")
        out["_entry_price"] = supplied.where(supplied > 0.0, pd.Series(entry_prices, index=out.index))
    else:
        out["_entry_price"] = entry_prices
    out["_exit_price"] = exit_prices
    out = out.dropna(subset=["_entry_price", "_exit_price"])
    out = out[out["_entry_price"] > 0.0].copy()
    if out.empty:
        return out
    out["forward_return"] = out["_exit_price"] / out["_entry_price"] - 1.0
    benchmark = benchmark_forward_returns.get(int(horizon), pd.Series(dtype=float))
    out["forward_benchmark_return"] = dates.map(benchmark).reindex(out.index)
    out["forward_benchmark_return"] = pd.to_numeric(out["forward_benchmark_return"], errors="coerce").fillna(0.0)
    out["forward_excess_return"] = out["forward_return"] - out["forward_benchmark_return"]
    return out


def _close_pivot(feature_data: pd.DataFrame) -> pd.DataFrame:
    if feature_data is None or feature_data.empty:
        return pd.DataFrame()
    close_col = "close_nominal" if "close_nominal" in feature_data.columns else "close"
    if close_col not in feature_data.columns:
        return pd.DataFrame()
    data = feature_data[["date", "symbol", close_col]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["symbol"] = data["symbol"].astype(str)
    data[close_col] = pd.to_numeric(data[close_col], errors="coerce")
    data = data.dropna(subset=["date", "symbol", close_col])
    if data.empty:
        return pd.DataFrame()
    return data.pivot_table(index="date", columns="symbol", values=close_col, aggfunc="last").sort_index()


def _benchmark_forward_returns(close_pivot: pd.DataFrame, benchmark_symbol: str | None, horizons=(5, 10, 20)) -> dict[int, pd.Series]:
    if close_pivot.empty or not benchmark_symbol or str(benchmark_symbol) not in close_pivot.columns:
        return {int(h): pd.Series(dtype=float) for h in horizons}
    close = close_pivot[str(benchmark_symbol)].dropna()
    return {int(h): close.shift(-int(h)) / close - 1.0 for h in horizons}


def _top_pool_benchmark_forward_returns(
    feature_data: pd.DataFrame,
    horizons=(5, 10, 20),
    *,
    top_n: int = GOVERNANCE_PERFORMANCE_BENCHMARK_TOP_N,
    rebalance: str = GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
) -> dict[int, pd.Series]:
    benchmark = build_top_pool_benchmark_series(feature_data, top_n=top_n, rebalance=rebalance)
    if benchmark.empty:
        return {int(h): pd.Series(dtype=float) for h in horizons}
    data = benchmark.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["benchmark_net_value"] = pd.to_numeric(data["benchmark_net_value"], errors="coerce")
    data = data.dropna(subset=["date", "benchmark_net_value"]).sort_values("date").drop_duplicates("date")
    if data.empty:
        return {int(h): pd.Series(dtype=float) for h in horizons}
    nav = data.set_index("date")["benchmark_net_value"]
    return {int(h): nav.shift(-int(h)) / nav - 1.0 for h in horizons}


def _regime_map(daily_result: pd.DataFrame | None) -> dict:
    if daily_result is None or daily_result.empty or "date" not in daily_result.columns:
        return {}
    data = daily_result.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    regime_col = "regime_name" if "regime_name" in data.columns else (
        "structural_regime_level" if "structural_regime_level" in data.columns else None
    )
    if regime_col is None:
        return {}
    data[regime_col] = data[regime_col].fillna("unknown").astype(str)
    return data.dropna(subset=["date"]).drop_duplicates("date", keep="last").set_index("date")[regime_col].to_dict()


def _factor_role(model_name: str, module: str) -> dict:
    name = str(model_name).lower()
    module = str(module).lower()
    role = {
        "primary_role": "entry_alpha",
        "buy_use_allowed": True,
        "hold_validation_allowed": True,
        "sell_trigger_allowed": False,
        "risk_override_allowed": False,
        "role_rationale": "default alpha signal; cannot force exits without separate sell validation",
    }
    if module in {"trend", "flow_close"}:
        role.update(
            {
                "primary_role": "entry_and_hold_validation",
                "hold_validation_allowed": True,
                "sell_trigger_allowed": True,
                "role_rationale": "trend/flow can validate continuation and warn on deterioration, but needs MFE/MAE confirmation",
            }
        )
    if module in {"reversal_pullback", "range_grid"}:
        role.update(
            {
                "primary_role": "entry_alpha",
                "sell_trigger_allowed": False,
                "role_rationale": "reversal/range signals are entry-timing tools; using them as hard sell triggers is not validated",
            }
        )
    if module in {"event_limit"} or "limit" in name or "event" in name:
        role.update(
            {
                "primary_role": "event_entry_or_risk_watch",
                "hold_validation_allowed": False,
                "sell_trigger_allowed": True,
                "risk_override_allowed": True,
                "role_rationale": "event/limit signals can decay quickly; allow risk-watch exits but not blanket buy/hold confidence",
            }
        )
    if module in {"defensive"} or "lowvol" in name:
        role.update(
            {
                "primary_role": "risk_sizer",
                "buy_use_allowed": False,
                "hold_validation_allowed": True,
                "sell_trigger_allowed": False,
                "risk_override_allowed": True,
                "role_rationale": "defensive/low-vol is mainly a sizing and risk-control signal, not standalone alpha",
            }
        )
    return role


def _payoff_row(group: pd.DataFrame, *, horizon: int, layer: str, side: str, reason: str) -> dict:
    returns = pd.to_numeric(group["forward_return"], errors="coerce").dropna()
    excess = pd.to_numeric(group.get("forward_excess_return"), errors="coerce").dropna()
    if str(side).lower() == "sell":
        directional = -returns
        directional_excess = -excess
    else:
        directional = returns
        directional_excess = excess
    if "correct" in group.columns:
        correct = pd.to_numeric(group["correct"], errors="coerce").dropna()
        hit_rate = float(correct.mean()) if not correct.empty else float((directional > 0.0).mean())
    else:
        hit_rate = float((directional > 0.0).mean()) if not directional.empty else 0.0
    return {
        "horizon_days": int(horizon),
        "layer": str(layer),
        "side": str(side),
        "reason": str(reason),
        "sample_count": int(len(returns)),
        "hit_rate": hit_rate,
        "avg_forward_return": float(returns.mean()) if not returns.empty else 0.0,
        "avg_forward_excess_return": float(excess.mean()) if not excess.empty else 0.0,
        "avg_directional_return": float(directional.mean()) if not directional.empty else 0.0,
        "avg_directional_excess_return": float(directional_excess.mean()) if not directional_excess.empty else 0.0,
        "avg_win": _mean_positive(directional),
        "avg_loss": _mean_loss_abs(directional),
        "payoff_ratio": _payoff_ratio(directional),
        "expectancy": _expectancy(directional),
    }


def _weighted_metric(group: pd.DataFrame, metric: str) -> float:
    if group is None or group.empty or metric not in group.columns:
        return np.nan
    values = pd.to_numeric(group.get(metric), errors="coerce")
    weights = pd.to_numeric(group.get("sample_count", pd.Series(1.0, index=group.index)), errors="coerce").fillna(1.0)
    valid = values.notna() & weights.gt(0)
    if not valid.any():
        return np.nan
    return float((values[valid] * weights[valid]).sum() / max(float(weights[valid].sum()), 1e-12))


def _safe_mean(values) -> float:
    data = pd.to_numeric(values, errors="coerce").dropna()
    return float(data.mean()) if not data.empty else np.nan


def _rows_frame(rows: list[dict], *, sort_by: list[str], ascending=True) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    available = [column for column in sort_by if column in frame.columns]
    if not available:
        return frame.reset_index(drop=True)
    if isinstance(ascending, list):
        ascending = ascending[: len(available)]
    return frame.sort_values(available, ascending=ascending).reset_index(drop=True)


def _mean_positive(values) -> float:
    data = pd.to_numeric(values, errors="coerce").dropna()
    wins = data[data > 0.0]
    return float(wins.mean()) if not wins.empty else 0.0


def _mean_loss_abs(values) -> float:
    data = pd.to_numeric(values, errors="coerce").dropna()
    losses = data[data <= 0.0]
    return abs(float(losses.mean())) if not losses.empty else 0.0


def _payoff_ratio(values) -> float:
    loss = _mean_loss_abs(values)
    return _mean_positive(values) / loss if loss > 1e-12 else 0.0


def _expectancy(values) -> float:
    data = pd.to_numeric(values, errors="coerce").dropna()
    if data.empty:
        return 0.0
    win_rate = float((data > 0.0).mean())
    return win_rate * _mean_positive(data) - (1.0 - win_rate) * _mean_loss_abs(data)


def _wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    phat = float(wins) / float(n)
    denom = 1.0 + z * z / n
    centre = phat + z * z / (2.0 * n)
    margin = z * math.sqrt((phat * (1.0 - phat) + z * z / (4.0 * n)) / n)
    return max(0.0, float((centre - margin) / denom))


def _risk_contribution(weights: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    variance = float(weights @ sigma @ weights)
    if variance <= 1e-18:
        return np.zeros_like(weights)
    marginal = sigma @ weights
    return (weights * marginal) / variance
