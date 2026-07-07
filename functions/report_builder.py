# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import (
    FEATURE_COLUMN_COUNT_WARN,
    FEATURE_DAILY_PARQUET,
    FEATURE_MEMORY_REPORT_CSV,
    FEATURE_PARQUET_GB_WARN,
    GOVERNANCE_SUMMARY_CSV,
    REPORT_EFFECTIVE_N_RELATIVE_GAP_WARN,
    REPORT_OUTPUT_MD,
    REPORT_TOP5_WEIGHT_SUM_GAP_WARN,
    RESEARCH_RUN_MODE,
    REGISTRY_FRAMEWORK_VERSION,
    DEFAULT_UNIVERSE_NAME,
    DEFAULT_ALPHA_BUNDLE,
    DEFAULT_GOVERNANCE_VARIANT,
)
from functions.governance import build_research_status, default_fallback_disclosures


def build_strategy_report(
    summary_df,
    regime_breakdown_df=None,
    governance_summary_df=None,
    report_title="Strategy Diagnostic Report",
    universe_name=None,
    variant_name=None,
    alpha_bundle=None,
):
    status = build_research_status()
    disclosures = default_fallback_disclosures()
    summary = _normalize_summary(summary_df)
    governance_summary = _normalize_summary(
        governance_summary_df if governance_summary_df is not None else _load_governance_summary()
    )
    frames = [frame for frame in [summary, governance_summary] if frame is not None and not frame.empty]
    if not frames:
        combined = pd.DataFrame()
    elif len(frames) == 1:
        combined = frames[0].copy()
    else:
        combined = pd.concat([frame.dropna(axis=1, how="all") for frame in frames], ignore_index=True, sort=False)
    resource_summary = _feature_resource_summary()
    degradation_counts = _degradation_counts(combined)
    concentration_notes = _build_concentration_notes(combined)
    governance_notes = _build_governance_notes(governance_summary)

    lines = [
        f"# {report_title}",
        "",
        "## Summary",
        f"- Research mode: `{RESEARCH_RUN_MODE}`",
        f"- Formal status: `{status.formal_status}`",
        f"- Formal eligible: `{status.formal_eligible}`",
        f"- Formal block reasons: `{status.formal_block_reason_code}`",
        "- Default report layers: `Summary -> Total Table -> Category Tables -> Diagnostics -> Resources`",
        "- Cross-class comparison disclaimer: `Rule / Kelly-managed / Governance / ML strategies do not share the same sizing, safety, and execution assumptions.`",
        f"- Run degradation count: `{int(degradation_counts['total_unique_flags'])}` unique flags across `{int(degradation_counts['row_count_with_degradation'])}` rows",
        f"- Feature parquet size: `{resource_summary['feature_parquet_gb']:.3f} GiB` (warn >= `{resource_summary['feature_parquet_gb_warn']:.3f}`)",
        f"- Feature column count: `{int(resource_summary['feature_column_count'])}` (warn >= `{int(resource_summary['feature_column_count_warn'])}`)",
        f"- Feature storage mode: `{resource_summary['feature_storage_mode'] or 'unknown'}`",
        f"- Registry framework version: `{REGISTRY_FRAMEWORK_VERSION}`",
        f"- Universe: `{universe_name or DEFAULT_UNIVERSE_NAME}`",
        f"- Governance variant: `{variant_name or DEFAULT_GOVERNANCE_VARIANT}`",
        f"- Alpha bundle: `{alpha_bundle or DEFAULT_ALPHA_BUNDLE}`",
    ]
    if int(resource_summary.get("feature_dropped_column_count", 0)) > 0:
        lines.append(
            f"- Feature storage pruning: dropped `{int(resource_summary['feature_dropped_column_count'])}` transient columns, saved `{int(resource_summary['feature_memory_saved_bytes'])}` bytes ({float(resource_summary['feature_memory_saved_ratio']):.2%})."
        )
    date_windows = []
    if "date_window" in combined.columns:
        date_windows = [item for item in combined["date_window"].fillna("").astype(str).unique().tolist() if item]
    if len(date_windows) == 1:
        lines.append(f"- Configured strategy date window: `{date_windows[0]}`")
    if summary.empty and governance_summary.empty:
        lines.append("- No strategy summary rows are available.")
    if concentration_notes:
        lines.append("- Concentration comparability alerts:")
        lines.extend([f"  - {note}" for note in concentration_notes])
    if governance_notes:
        lines.append("- Governance highlights:")
        lines.extend([f"  - {note}" for note in governance_notes])
    if disclosures:
        lines.append("- Substitute disclosures remain active in exploratory mode.")
    if resource_summary["alerts"]:
        lines.append("- Resource alerts:")
        lines.extend([f"  - {item}" for item in resource_summary["alerts"]])

    lines.extend(["", "## Total Table"])
    if combined.empty:
        lines.append("No summary rows available.")
    else:
        lines.append(
            "One consolidated table is retained, but rows are segmented by category and must not be read as a single apples-to-apples ranking."
        )
        lines.extend(_segmented_total_table_lines(combined))

    if not combined.empty:
        lines.extend(["", "## Category Tables"])
        for category, frame in _grouped_categories(combined):
            lines.append(f"### `{category}`")
            lines.append(_summary_table(frame).to_markdown(index=False))
            lines.append("")

    lines.extend(["## Diagnostics"])
    if combined.empty:
        lines.append("No diagnostics available.")
    else:
        diag_cols = [
            "strategy",
            "strategy_source",
            "weighting_mode",
            "price_basis",
            "neutralization_mode",
            "ml_runtime_mode",
            "requested_model",
            "runtime_model",
            "training_window_days",
            "training_sample_count",
            "label_purge_periods",
            "prior_p",
            "prior_strength",
            "prior_source",
            "posterior_alpha",
            "posterior_beta",
            "posterior_sample_count",
            "signal_candidate_count",
            "signal_trigger_count",
            "signal_trigger_rate",
            "adjustment_coverage_ratio",
            "adjustment_coverage_threshold",
            "price_basis_selection_mode",
            "strategy_params_version",
            "benchmark_status",
            "benchmark_excess_return",
            "crowding_top_sector_weight",
            "crowding_hot_sector_weight",
            "crowding_unique_sector_count",
            "exposure_ret_20_tilt",
            "exposure_volatility_20_tilt",
            "exposure_close_to_ma20_tilt",
            "exposure_amount_ratio_20_tilt",
            "turnover_ratio",
            "blocked_order_count",
            "participation_rate",
            "capacity_passed_ratio",
            "turnover_budget",
            "governance_variant",
            "safety_proxy_mode",
            "exposure_cap_mode",
            "safety_agent_enabled",
            "reputation_enabled",
            "reputation_window_ready",
            "reputation_window_observed_days",
            "reputation_window_required_days",
            "ml_weight_state",
            "ml_weight_distinction",
            "sector_cap_enabled",
            "portfolio_exposure_cap",
            "trading_freeze_trigger_count",
            "trading_freeze_total_rebalance_periods",
            "trading_freeze_period_lengths",
            "trading_freeze_min_exposure_cap",
            "trading_freeze_min_target_exposure",
            "emergency_deleveraging_trigger_count",
            "emergency_deleveraging_total_rebalance_periods",
            "emergency_deleveraging_period_lengths",
            "emergency_deleveraging_min_exposure_cap",
            "emergency_deleveraging_min_target_exposure",
            "top1_weight",
            "top5_weight_sum",
            "effective_n",
            "research_gate_status",
            "research_gate_fail_count",
            "factor_validation_pass_count",
            "latest_portfolio_constraint_pass",
            "degradation_count",
            "degradation_flags",
        ]
        diag_cols = [col for col in diag_cols if col in combined.columns]
        lines.append(combined.loc[:, diag_cols].to_markdown(index=False))
        if degradation_counts["counts"]:
            lines.append("")
            lines.append("### Degradation Summary")
            lines.append(f"- Unique degradation count: `{int(degradation_counts['total_unique_flags'])}`")
            for flag, count in degradation_counts["counts"]:
                lines.append(f"- `{flag}`: {count}")

    lines.extend(["", "## Resources"])
    lines.append(f"- Feature parquet path: `{FEATURE_DAILY_PARQUET}`")
    lines.append(f"- Feature parquet size GiB: `{resource_summary['feature_parquet_gb']:.3f}`")
    lines.append(f"- Feature column count: `{int(resource_summary['feature_column_count'])}`")
    lines.append(f"- Feature parquet size warn threshold: `{resource_summary['feature_parquet_gb_warn']:.3f}`")
    lines.append(f"- Feature column count warn threshold: `{int(resource_summary['feature_column_count_warn'])}`")
    lines.append(f"- Feature storage mode: `{resource_summary['feature_storage_mode'] or 'unknown'}`")
    lines.append(f"- Feature dropped transient columns: `{int(resource_summary.get('feature_dropped_column_count', 0))}`")
    lines.append(f"- Feature memory saved bytes: `{int(resource_summary.get('feature_memory_saved_bytes', 0))}`")
    lines.append(f"- Feature memory saved ratio: `{float(resource_summary.get('feature_memory_saved_ratio', 0.0)):.2%}`")
    if governance_summary is not None and not governance_summary.empty:
        lines.extend(["", "## Governance Summary"])
        lines.extend(_governance_summary_lines(governance_summary))
    governance_research_sections = _governance_research_report_lines()
    if governance_research_sections:
        lines.extend(["", "## Governance Research Gates"])
        lines.extend(governance_research_sections)

    if regime_breakdown_df is not None and not regime_breakdown_df.empty:
        lines.extend(["", "## Market Regime Breakdown", regime_breakdown_df.to_markdown(index=False)])
    return "\n".join(lines) + "\n"


def save_strategy_report(report_text, output_path=REPORT_OUTPUT_MD):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report_text, encoding="utf-8")
    return output_file


def _normalize_summary(frame):
    if frame is None:
        return pd.DataFrame()
    data = frame.copy()
    if data.empty:
        return data
    defaults = {
        "strategy_source": "unknown",
        "weighting_mode": "equal_weight",
        "price_basis": "nominal_unadjusted",
        "neutralization_mode": "winsor_only",
        "ml_runtime_mode": "not_applicable",
        "requested_model": "",
        "runtime_model": "",
        "training_window_days": pd.NA,
        "training_sample_count": pd.NA,
        "label_purge_periods": pd.NA,
        "prior_p": pd.NA,
        "prior_strength": pd.NA,
        "prior_source": "",
        "posterior_alpha": pd.NA,
        "posterior_beta": pd.NA,
        "posterior_sample_count": pd.NA,
        "signal_candidate_count": pd.NA,
        "signal_trigger_count": pd.NA,
        "signal_trigger_rate": pd.NA,
        "adjustment_coverage_ratio": pd.NA,
        "adjustment_coverage_threshold": pd.NA,
        "price_basis_selection_mode": "",
        "strategy_params_version": "",
        "benchmark_status": "",
        "benchmark_excess_return": pd.NA,
        "crowding_top_sector_weight": pd.NA,
        "crowding_hot_sector_weight": pd.NA,
        "crowding_unique_sector_count": pd.NA,
        "exposure_ret_20_tilt": pd.NA,
        "exposure_volatility_20_tilt": pd.NA,
        "exposure_close_to_ma20_tilt": pd.NA,
        "exposure_amount_ratio_20_tilt": pd.NA,
        "safety_agent_enabled": pd.NA,
        "reputation_enabled": pd.NA,
        "reputation_window_ready": pd.NA,
        "reputation_window_observed_days": pd.NA,
        "reputation_window_required_days": pd.NA,
        "ml_weight_state": "",
        "ml_weight_distinction": pd.NA,
        "sector_cap_enabled": pd.NA,
        "degradation_flags": "",
        "degradation_count": 0,
        "top1_weight": pd.NA,
        "top5_weight_sum": pd.NA,
        "effective_n": pd.NA,
        "research_gate_status": "unknown",
        "research_gate_fail_count": pd.NA,
        "factor_validation_pass_count": pd.NA,
        "latest_portfolio_constraint_pass": pd.NA,
    }
    for key, value in defaults.items():
        if key not in data.columns:
            data[key] = value
    return data


def _summary_table(frame):
    table_cols = [
        "strategy",
        "strategy_source",
        "weighting_mode",
        "total_return",
        "sharpe",
        "max_drawdown",
        "top1_weight",
        "top5_weight_sum",
        "effective_n",
        "degradation_count",
        "benchmark_status",
        "composite_score",
    ]
    cols = [col for col in table_cols if col in frame.columns]
    return frame.loc[:, cols].copy()


def _segmented_total_table_lines(frame):
    lines = []
    for category, category_frame in _grouped_categories(frame):
        lines.append(f"### `{category}` segment")
        if category == "governance":
            lines.append(
                "Governance rows represent dynamic constraint-based portfolio decisions and are not directly comparable to static equal-weight rule strategies."
            )
        lines.append(_summary_table(category_frame).to_markdown(index=False))
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _grouped_categories(frame):
    if frame is None or frame.empty:
        return []
    ordered = frame.copy()
    ordered["_category_order"] = ordered["strategy_source"].map(_category_order).fillna(9)
    ordered = ordered.sort_values(["_category_order", "composite_score"], ascending=[True, False])
    groups = []
    for category in ordered["strategy_source"].drop_duplicates().tolist():
        groups.append((category, ordered[ordered["strategy_source"] == category].drop(columns="_category_order")))
    return groups


def _category_order(category):
    mapping = {
        "rule": 0,
        "technical": 1,
        "research": 1,
        "position_management": 1,
        "governance": 2,
        "ml": 3,
        "classic_ml": 3,
        "quantum_inspired": 3,
    }
    return mapping.get(str(category), 9)


def _degradation_counts(frame):
    counts = {}
    row_count = 0
    if frame is not None and not frame.empty and "degradation_flags" in frame.columns:
        for value in frame["degradation_flags"].fillna("").astype(str):
            flags = [flag.strip() for flag in value.split("|") if flag.strip()]
            if flags:
                row_count += 1
            for flag in flags:
                counts[flag] = counts.get(flag, 0) + 1
    return {
        "counts": sorted(counts.items(), key=lambda item: (-item[1], item[0])),
        "total_unique_flags": len(counts),
        "row_count_with_degradation": row_count,
    }


def _build_concentration_notes(frame):
    if frame is None or frame.empty or "strategy_source" not in frame.columns:
        return []
    required = {"effective_n", "top5_weight_sum"}
    if not required.issubset(frame.columns):
        return []
    grouped = frame.groupby("strategy_source", dropna=False).agg(
        effective_n=("effective_n", "mean"),
        top5_weight_sum=("top5_weight_sum", "mean"),
    ).reset_index()
    if len(grouped) < 2:
        return []
    notes = []
    effective_values = pd.to_numeric(grouped["effective_n"], errors="coerce").dropna()
    top5_values = pd.to_numeric(grouped["top5_weight_sum"], errors="coerce").dropna()
    if not effective_values.empty and effective_values.max() > 0:
        relative_gap = (effective_values.max() - effective_values.min()) / effective_values.max()
        if relative_gap >= float(REPORT_EFFECTIVE_N_RELATIVE_GAP_WARN):
            notes.append(
                f"Concentration differences may affect comparability: effective_n relative gap={relative_gap:.2%}, threshold={float(REPORT_EFFECTIVE_N_RELATIVE_GAP_WARN):.2%}."
            )
            if float(REPORT_EFFECTIVE_N_RELATIVE_GAP_WARN) == 0.50:
                notes.append("Current effective_n threshold uses the default value and can be adjusted in config.")
    if not top5_values.empty:
        absolute_gap = top5_values.max() - top5_values.min()
        if absolute_gap >= float(REPORT_TOP5_WEIGHT_SUM_GAP_WARN):
            notes.append(
                f"Concentration differences may affect comparability: top5_weight_sum gap={absolute_gap:.2%}, threshold={float(REPORT_TOP5_WEIGHT_SUM_GAP_WARN):.2%}."
            )
            if float(REPORT_TOP5_WEIGHT_SUM_GAP_WARN) == 0.20:
                notes.append("Current top5_weight_sum threshold uses the default value and can be adjusted in config.")
    return notes


def _feature_resource_summary():
    path = Path(FEATURE_DAILY_PARQUET)
    size_gb = path.stat().st_size / (1024 ** 3) if path.exists() else 0.0
    column_count = 0
    if path.exists():
        try:
            import pyarrow.parquet as pq

            column_count = len(pq.ParquetFile(path).schema.names)
        except Exception:
            try:
                column_count = len(pd.read_parquet(path).columns)
            except Exception:
                column_count = 0
    alerts = []
    if size_gb >= float(FEATURE_PARQUET_GB_WARN):
        alerts.append("Feature parquet size exceeds the configured warning threshold.")
    if int(column_count) >= int(FEATURE_COLUMN_COUNT_WARN):
        alerts.append("Feature column count exceeds the configured warning threshold.")
    memory_report = pd.DataFrame()
    if Path(FEATURE_MEMORY_REPORT_CSV).exists():
        try:
            memory_report = pd.read_csv(FEATURE_MEMORY_REPORT_CSV)
        except Exception:
            memory_report = pd.DataFrame()
    storage_mode = ""
    memory_saved_bytes = 0
    memory_saved_ratio = 0.0
    dropped_column_count = 0
    if not memory_report.empty:
        row = memory_report.iloc[0]
        storage_mode = str(row.get("feature_storage_mode", ""))
        memory_saved_bytes = int(pd.to_numeric(row.get("memory_saved_bytes", 0), errors="coerce") or 0)
        memory_saved_ratio = float(pd.to_numeric(row.get("memory_saved_ratio", 0.0), errors="coerce") or 0.0)
        dropped_column_count = int(pd.to_numeric(row.get("dropped_column_count", 0), errors="coerce") or 0)
    return {
        "feature_parquet_gb": size_gb,
        "feature_column_count": column_count,
        "feature_parquet_gb_warn": float(FEATURE_PARQUET_GB_WARN),
        "feature_column_count_warn": int(FEATURE_COLUMN_COUNT_WARN),
        "feature_storage_mode": storage_mode,
        "feature_memory_saved_bytes": memory_saved_bytes,
        "feature_memory_saved_ratio": memory_saved_ratio,
        "feature_dropped_column_count": dropped_column_count,
        "alerts": alerts,
    }


def _load_governance_summary():
    path = Path(GOVERNANCE_SUMMARY_CSV)
    if not path.exists():
        candidates = list(path.parent.rglob("governance_strategy_summary.csv"))
        candidates.extend(path.parent.rglob("governance_strategy_summary_run*.csv"))
        if not candidates:
            return pd.DataFrame()
        path = max(candidates, key=lambda item: item.stat().st_mtime)
    return pd.read_csv(path)


def _load_latest_governance_report(filename: str) -> pd.DataFrame:
    root = Path(GOVERNANCE_SUMMARY_CSV).parent
    candidates = [path for path in root.rglob(filename) if "_archive" not in path.parts]
    candidates.extend([path for path in root.rglob(filename.replace(".csv", "_run*.csv")) if "_archive" not in path.parts])
    if not candidates:
        return pd.DataFrame()
    path = max(candidates, key=lambda item: item.stat().st_mtime)
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _governance_research_report_lines():
    lines = []
    gate = _load_latest_governance_report("governance_research_gate_report.csv")
    if not gate.empty:
        cols = [col for col in ["gate_name", "pass_flag", "value", "threshold", "severity", "reason", "overall_status"] if col in gate.columns]
        lines.extend(["### Research Admission Gate", gate.loc[:, cols].to_markdown(index=False), ""])
    validation = _load_latest_governance_report("governance_factor_validation_report.csv")
    if not validation.empty:
        lines.extend(_factor_validation_summary_lines(validation))
    constraints = _load_latest_governance_report("governance_portfolio_constraint_report.csv")
    if not constraints.empty:
        latest = constraints.tail(1).copy()
        cols = [
            col for col in [
                "date",
                "account_effective_n",
                "top1_account_weight",
                "top5_account_weight_sum",
                "constraint_pass",
                "fail_reasons",
                "research_valid",
            ]
            if col in latest.columns
        ]
        lines.extend(["", "### Latest Portfolio Constraints", latest.loc[:, cols].to_markdown(index=False)])
    entry_gate = _load_latest_governance_report("governance_entry_gate_policy.csv")
    if not entry_gate.empty:
        cols = [
            col for col in [
                "regime_name",
                "prediction_bucket",
                "sample_count",
                "wilson_lower_95",
                "expectancy_10d",
                "forward_excess_10d",
                "allow_buy",
                "max_entry_lots",
                "reason",
            ]
            if col in entry_gate.columns
        ]
        lines.extend(["", "### Entry Calibration Policy", entry_gate.loc[:, cols].head(12).to_markdown(index=False)])
    return lines


def _factor_validation_summary_lines(validation: pd.DataFrame):
    data = validation.copy()
    data["pass_flag"] = data.get("pass_flag", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    data["ic_ir"] = pd.to_numeric(data.get("ic_ir"), errors="coerce")
    data["top_bottom_spread"] = pd.to_numeric(data.get("top_bottom_spread"), errors="coerce")
    passed = data[data["pass_flag"]].sort_values(["ic_ir", "top_bottom_spread"], ascending=[False, False]).head(10)
    failed = data[~data["pass_flag"]].copy()
    failed["_fail_weight"] = failed.get("fail_reasons", pd.Series("", index=failed.index)).fillna("").astype(str).str.count(r"\|") + 1
    failed = failed.sort_values(["_fail_weight", "ic_ir"], ascending=[False, True]).head(10)
    cols = [
        col for col in [
            "factor_name",
            "module",
            "candidate_pool",
            "horizon_days",
            "coverage_ratio",
            "rank_ic_mean",
            "ic_ir",
            "rank_ic_positive_ratio",
            "top_bottom_spread",
            "sample_count",
            "pass_flag",
            "fail_reasons",
        ]
        if col in data.columns
    ]
    lines = ["### Factor Validation Summary"]
    lines.append(f"- Factor-horizon passes: `{int(data['pass_flag'].sum())}` / `{len(data)}`")
    if not passed.empty:
        lines.extend(["", "#### Top Effective Factors", passed.loc[:, cols].to_markdown(index=False)])
    if not failed.empty:
        lines.extend(["", "#### Top Failed Factors", failed.loc[:, cols].to_markdown(index=False)])
    return lines


def _build_governance_notes(governance_summary):
    if governance_summary is None or governance_summary.empty:
        return []
    row = governance_summary.iloc[0]
    return [
        (
            f"Variant={row.get('governance_variant', '')}, safety_proxy_mode={row.get('safety_proxy_mode', '')}, "
            f"factor_source={row.get('factor_source', '')}, "
            f"factor_cabinet_run_id={row.get('factor_cabinet_run_id', '')}, "
            f"factor_cabinet_path={row.get('factor_cabinet_path', '')}, "
            f"factor_count={row.get('factor_count', '')}, "
            f"strict_entry_alpha_count={row.get('strict_entry_alpha_count', '')}, "
            f"proxy_entry_alpha_count={row.get('proxy_entry_alpha_count', '')}, "
            f"exposure_cap_mode={row.get('exposure_cap_mode', '')}, "
            f"safety_agent_enabled={_display_text(row.get('safety_agent_enabled'), default='blocked_or_unavailable')}, "
            f"reputation_enabled={_display_text(row.get('reputation_enabled'), default='blocked_or_unavailable')}, "
            f"reputation_window_ready={_display_text(row.get('reputation_window_ready'), default='blocked_or_unavailable')}, "
            f"ml_weight_state={_display_text(row.get('ml_weight_state'), default='blocked_or_unavailable')}, "
            f"sector_cap_enabled={_display_text(row.get('sector_cap_enabled'), default='blocked_or_unavailable')}."
        ),
        (
            "Trading freeze triggers="
            f"{int(pd.to_numeric(row.get('trading_freeze_trigger_count', 0), errors='coerce') or 0)}, "
            "total periods="
            f"{int(pd.to_numeric(row.get('trading_freeze_total_rebalance_periods', 0), errors='coerce') or 0)}, "
            "period lengths="
            f"{_display_text(row.get('trading_freeze_period_lengths'), default='none')}."
        ),
        (
            "Emergency deleveraging triggers="
            f"{int(pd.to_numeric(row.get('emergency_deleveraging_trigger_count', 0), errors='coerce') or 0)}, "
            "total periods="
            f"{int(pd.to_numeric(row.get('emergency_deleveraging_total_rebalance_periods', 0), errors='coerce') or 0)}, "
            "period lengths="
            f"{_display_text(row.get('emergency_deleveraging_period_lengths'), default='none')}."
        ),
    ]


def _governance_summary_lines(governance_summary):
    row = governance_summary.iloc[0]
    lines = [
        _summary_table(governance_summary).to_markdown(index=False),
        "",
        "### Governance Event Summary",
        (
            "- Trading freeze events: "
            f"triggers=`{int(pd.to_numeric(row.get('trading_freeze_trigger_count', 0), errors='coerce') or 0)}`, "
            f"rebalance_periods=`{int(pd.to_numeric(row.get('trading_freeze_total_rebalance_periods', 0), errors='coerce') or 0)}`, "
            f"period_lengths=`{_display_text(row.get('trading_freeze_period_lengths'), default='none')}`, "
            f"min_exposure_cap=`{_display_number(row.get('trading_freeze_min_exposure_cap'))}`, "
            f"min_target_exposure=`{_display_number(row.get('trading_freeze_min_target_exposure'))}`"
        ),
        (
            "- Emergency deleveraging events: "
            f"triggers=`{int(pd.to_numeric(row.get('emergency_deleveraging_trigger_count', 0), errors='coerce') or 0)}`, "
            f"rebalance_periods=`{int(pd.to_numeric(row.get('emergency_deleveraging_total_rebalance_periods', 0), errors='coerce') or 0)}`, "
            f"period_lengths=`{_display_text(row.get('emergency_deleveraging_period_lengths'), default='none')}`, "
            f"min_exposure_cap=`{_display_number(row.get('emergency_deleveraging_min_exposure_cap'))}`, "
            f"min_target_exposure=`{_display_number(row.get('emergency_deleveraging_min_target_exposure'))}`"
        ),
        (
            "- Governance capacity fields: "
            f"turnover_budget=`{_display_number(row.get('turnover_budget'))}`, "
            f"participation_rate=`{_display_number(row.get('participation_rate'))}`, "
            f"capacity_passed_ratio=`{_display_number(row.get('capacity_passed_ratio'))}`, "
            f"portfolio_exposure_cap=`{_display_number(row.get('portfolio_exposure_cap'))}`"
        ),
        (
            "- Governance identity fields: "
            f"variant=`{_display_text(row.get('governance_variant'))}`, "
            f"safety_agent_enabled=`{_display_text(row.get('safety_agent_enabled'))}`, "
            f"reputation_enabled=`{_display_text(row.get('reputation_enabled'))}`, "
            f"reputation_window_ready=`{_display_text(row.get('reputation_window_ready'))}`, "
            f"reputation_window_progress=`{_display_text(_window_progress_text(row))}`, "
            f"ml_weight_state=`{_display_text(row.get('ml_weight_state'))}`, "
            f"ml_weight_distinction=`{_display_number(row.get('ml_weight_distinction'))}`, "
            f"sector_cap_enabled=`{_display_text(row.get('sector_cap_enabled'))}`"
        ),
        "- Governance comparability disclaimer: `This category uses dynamic constraint-based sizing and safety gates; do not compare it directly to static equal-weight rule strategies without context.`",
    ]
    return lines


def _display_number(value, *, default="blocked_or_unavailable"):
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return default
    return f"{float(numeric):.4f}"


def _display_text(value, *, default="blocked_or_unavailable"):
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return default
    return text


def _window_progress_text(row):
    observed = pd.to_numeric(pd.Series([row.get("reputation_window_observed_days")]), errors="coerce").iloc[0]
    required = pd.to_numeric(pd.Series([row.get("reputation_window_required_days")]), errors="coerce").iloc[0]
    if pd.isna(observed) or pd.isna(required):
        return None
    return f"{int(observed)}/{int(required)}"
