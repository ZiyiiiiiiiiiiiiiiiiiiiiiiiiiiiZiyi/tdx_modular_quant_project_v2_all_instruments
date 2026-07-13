"""Post-run diagnostics for governance layer-ablation suites."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


KEY_METRICS = [
    "total_return",
    "sharpe",
    "max_drawdown",
    "avg_actual_exposure",
    "holding_portfolio_return",
    "benchmark_excess_return",
    "buy_expectancy_10d",
    "buy_hit_rate_10d",
    "sell_expectancy_10d",
    "max_risk_contribution_observed",
    "p_win_10d_ece",
    "p_win_10d_best_bucket_wilson_lower",
    "validation_gate_pass_ratio",
]


def _numeric_column(data: pd.DataFrame, column: str, *, default=np.nan) -> pd.Series:
    source = data[column] if column in data.columns else pd.Series(default, index=data.index)
    return pd.to_numeric(source, errors="coerce")


def build_layer_ablation_diagnostics(
    *,
    suite_id: str,
    universe_names: tuple[str, ...],
    suite_steps: tuple[tuple[str, str, str], ...],
    result_dir,
    run_dirs: dict[tuple[str, str], str | Path] | None = None,
) -> dict[str, Path]:
    """Build timestamped CSV, markdown, and plot diagnostics for one suite run."""
    result_root = Path(result_dir)
    output_dir = result_root / "governance" / f"layer_ablation_diagnostics_{suite_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    payoff_rows = []
    calibration_rows = []
    validation_rows = []
    risk_rows = []
    module_rows = []
    reason_rows = []

    for universe_name in universe_names:
        universe_root = result_root / "governance" / universe_name
        for variant_name, alpha_bundle, suite_step in suite_steps:
            mapped_dir = (run_dirs or {}).get((universe_name, suite_step))
            run_dir = Path(mapped_dir) if mapped_dir else _resolve_suite_run_dir(
                universe_root / variant_name / alpha_bundle, suite_id
            )
            context = {
                "suite_id": suite_id,
                "suite_step": suite_step,
                "universe_name": universe_name,
                "variant_name": variant_name,
                "alpha_bundle": alpha_bundle,
                "output_dir": str(run_dir),
            }
            summary_rows.append(_summary_row(run_dir, context))
            payoff_rows.extend(_tagged_rows(run_dir / "governance_entry_payoff_report.csv", context))
            calibration_rows.extend(_tagged_rows(run_dir / "governance_entry_calibration_report.csv", context))
            validation_rows.extend(_tagged_rows(run_dir / "governance_strategy_validation_matrix.csv", context))
            risk_rows.extend(_risk_summary_rows(run_dir / "governance_risk_contribution_ledger.csv", context))
            module_rows.extend(_module_weight_rows(run_dir / "governance_factor_weight_ledger.csv", context))
            reason_rows.extend(_reason_rows(run_dir / "governance_execution_ledger.csv", context))

    summary = pd.DataFrame(summary_rows)
    payoff = pd.DataFrame(payoff_rows)
    calibration = pd.DataFrame(calibration_rows)
    validation = pd.DataFrame(validation_rows)
    risk = pd.DataFrame(risk_rows)
    modules = pd.DataFrame(module_rows)
    reasons = pd.DataFrame(reason_rows)
    increments = _incremental_contribution(summary)
    problems = _problem_ranking(summary, validation)

    saved: dict[str, Path] = {}
    saved["summary"] = _save_csv(summary, output_dir / f"layer_ablation_summary_{suite_id}.csv")
    saved["entry_payoff"] = _save_csv(payoff, output_dir / f"layer_ablation_entry_payoff_{suite_id}.csv")
    saved["calibration"] = _save_csv(calibration, output_dir / f"layer_ablation_calibration_{suite_id}.csv")
    saved["validation"] = _save_csv(validation, output_dir / f"layer_ablation_validation_matrix_{suite_id}.csv")
    saved["risk"] = _save_csv(risk, output_dir / f"layer_ablation_risk_concentration_{suite_id}.csv")
    saved["module_weights"] = _save_csv(modules, output_dir / f"layer_ablation_module_weights_{suite_id}.csv")
    saved["order_reasons"] = _save_csv(reasons, output_dir / f"layer_ablation_order_reasons_{suite_id}.csv")
    saved["incremental_contribution"] = _save_csv(increments, output_dir / f"layer_ablation_incremental_contribution_{suite_id}.csv")
    saved["problem_ranking"] = _save_csv(problems, output_dir / f"layer_ablation_problem_ranking_{suite_id}.csv")
    saved.update(_save_plots(summary, payoff, calibration, risk, modules, increments, output_dir, suite_id))
    saved["report"] = _save_markdown_report(summary, increments, problems, saved, output_dir / f"layer_ablation_diagnostic_report_{suite_id}.md")
    return saved


def _resolve_suite_run_dir(bundle_root: Path, suite_id: str) -> Path:
    direct = bundle_root / suite_id
    if (direct / "governance_strategy_summary.csv").exists():
        return direct
    if direct.exists():
        candidates = list(direct.rglob("governance_strategy_summary.csv"))
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_mtime).parent
    if bundle_root.exists():
        candidates = [
            path for path in bundle_root.rglob("governance_strategy_summary.csv")
            if suite_id in path.parts
        ]
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_mtime).parent
    return direct


def _summary_row(run_dir: Path, context: dict) -> dict:
    row = dict(context)
    summary_path = run_dir / "governance_strategy_summary.csv"
    row["summary_status"] = "missing"
    if not summary_path.exists():
        return row
    try:
        summary = pd.read_csv(summary_path)
    except Exception as exc:
        row["summary_status"] = f"read_error: {exc}"
        return row
    if summary.empty:
        row["summary_status"] = "empty"
        return row
    row.update(summary.iloc[0].to_dict())
    row.update(context)
    row["summary_status"] = "ok"
    return row


def _tagged_rows(path: Path, context: dict) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = pd.read_csv(path)
    except Exception:
        return []
    if data.empty:
        return []
    rows = []
    for _, row in data.iterrows():
        item = dict(context)
        item.update(row.to_dict())
        rows.append(item)
    return rows


def _risk_summary_rows(path: Path, context: dict) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = pd.read_csv(path)
    except Exception:
        return []
    if data.empty:
        return []
    metric_col = "positive_risk_contribution_share" if "positive_risk_contribution_share" in data.columns else "risk_contribution_share"
    data[metric_col] = _numeric_column(data, metric_col)
    data["target_weight"] = _numeric_column(data, "target_weight")
    rows = []
    grouped = data.groupby("date", dropna=False) if "date" in data.columns else [(None, data)]
    for date, group in grouped:
        ranked = group.sort_values(metric_col, ascending=False)
        top_symbols = ranked["symbol"].astype(str).head(5).tolist() if "symbol" in ranked.columns else []
        top_values = pd.to_numeric(ranked.get(metric_col), errors="coerce").head(5).tolist()
        item = dict(context)
        item.update(
            {
                "date": date,
                "max_risk_contribution": float(group[metric_col].max()) if group[metric_col].notna().any() else np.nan,
                "top1_risk_symbol": top_symbols[0] if top_symbols else "",
                "top1_risk_contribution": float(top_values[0]) if top_values else np.nan,
                "top5_risk_symbols": ",".join(top_symbols),
                "top5_risk_contribution_sum": float(np.nansum(top_values)) if top_values else np.nan,
                "mean_risk_contribution": float(group[metric_col].mean()) if group[metric_col].notna().any() else np.nan,
                "max_target_weight": float(group["target_weight"].max()) if group["target_weight"].notna().any() else np.nan,
                "risk_symbol_count": int(group["symbol"].nunique()) if "symbol" in group.columns else int(len(group)),
            }
        )
        rows.append(item)
    return rows


def _incremental_contribution(summary: pd.DataFrame) -> pd.DataFrame:
    if summary is None or summary.empty or "suite_step" not in summary.columns:
        return pd.DataFrame()
    metrics = [
        "total_return",
        "sharpe",
        "max_drawdown",
        "avg_actual_exposure",
        "holding_portfolio_return",
        "benchmark_excess_return",
        "buy_expectancy_10d",
        "sell_expectancy_10d",
        "p_win_10d_ece",
        "max_risk_contribution_observed",
    ]
    group_keys = [key for key in ["suite_id", "universe_name"] if key in summary.columns]
    rows = []
    grouped = summary.groupby(group_keys, dropna=False) if group_keys else [((), summary)]
    for group_key, group in grouped:
        base = group[group["suite_step"].astype(str).eq("01_core_base")]
        if base.empty:
            continue
        base_row = base.iloc[0]
        for _, row in group.iterrows():
            item = {
                "suite_step": row.get("suite_step"),
                "variant_name": row.get("variant_name"),
                "alpha_bundle": row.get("alpha_bundle"),
            }
            if group_keys:
                if not isinstance(group_key, tuple):
                    group_key = (group_key,)
                item.update(dict(zip(group_keys, group_key)))
            for metric in metrics:
                if metric not in group.columns:
                    continue
                observed = pd.to_numeric(pd.Series([row.get(metric)]), errors="coerce").iloc[0]
                baseline = pd.to_numeric(pd.Series([base_row.get(metric)]), errors="coerce").iloc[0]
                item[f"{metric}_value"] = observed
                item[f"{metric}_delta_vs_core_base"] = observed - baseline if pd.notna(observed) and pd.notna(baseline) else np.nan
            item["research_action"] = _incremental_action(item)
            rows.append(item)
    return pd.DataFrame(rows)


def _incremental_action(row: dict) -> str:
    step = str(row.get("suite_step", ""))
    buy_delta = row.get("buy_expectancy_10d_delta_vs_core_base", np.nan)
    hold_delta = row.get("holding_portfolio_return_delta_vs_core_base", np.nan)
    risk_delta = row.get("max_risk_contribution_observed_delta_vs_core_base", np.nan)
    try:
        buy_delta = float(buy_delta)
    except Exception:
        buy_delta = np.nan
    try:
        hold_delta = float(hold_delta)
    except Exception:
        hold_delta = np.nan
    try:
        risk_delta = float(risk_delta)
    except Exception:
        risk_delta = np.nan
    if step == "01_core_base":
        return "baseline"
    if np.isfinite(buy_delta) and buy_delta > 0 and np.isfinite(hold_delta) and hold_delta >= 0 and (not np.isfinite(risk_delta) or risk_delta <= 0.10):
        return "candidate_for_mainline"
    if np.isfinite(buy_delta) and buy_delta < 0 and np.isfinite(hold_delta) and hold_delta < 0:
        return "candidate_to_remove_or_downgrade"
    if np.isfinite(risk_delta) and risk_delta > 0.20:
        return "risk_concentration_warning"
    return "needs_manual_review"


def _module_weight_rows(path: Path, context: dict) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = pd.read_csv(path)
    except Exception:
        return []
    if data.empty or "factor_module" not in data.columns:
        return []
    data["weight_share"] = _numeric_column(data, "weight_share", default=0.0).fillna(0.0)
    data["avg_predicted_return_5d"] = _numeric_column(data, "avg_predicted_return_5d")
    latest_date = pd.to_datetime(data.get("date"), errors="coerce").max() if "date" in data.columns else pd.NaT
    rows = []
    for module, group in data.groupby("factor_module", dropna=False):
        item = dict(context)
        item.update(
            {
                "factor_module": str(module),
                "latest_date": latest_date,
                "avg_weight_share": float(group["weight_share"].mean()),
                "latest_weight_share": _latest_group_sum(group, "weight_share"),
                "avg_predicted_return_5d": float(group["avg_predicted_return_5d"].mean()) if group["avg_predicted_return_5d"].notna().any() else np.nan,
                "factor_count": int(group["model_name"].nunique()) if "model_name" in group.columns else int(len(group)),
                "zero_trade_warning_days": int(pd.to_numeric(group.get("zero_trade_factor_warning"), errors="coerce").fillna(0).sum()) if "zero_trade_factor_warning" in group.columns else 0,
            }
        )
        rows.append(item)
    return rows


def _reason_rows(path: Path, context: dict) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = pd.read_csv(path)
    except Exception:
        return []
    if data.empty or "reason" not in data.columns:
        return []
    rows = []
    for (side, reason), group in data.groupby(["side", "reason"], dropna=False):
        item = dict(context)
        item.update(
            {
                "side": str(side),
                "reason": str(reason),
                "order_count": int(len(group)),
                "filled_count": int(group.get("execution_status", pd.Series(dtype=object)).astype(str).eq("filled").sum()),
                "trade_notional": float(_numeric_column(group, "trade_notional", default=0.0).fillna(0.0).sum()),
                "total_cost": float(_numeric_column(group, "total_cost", default=0.0).fillna(0.0).sum()),
            }
        )
        rows.append(item)
    return rows


def _problem_ranking(summary: pd.DataFrame, validation: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if summary is not None and not summary.empty:
        for _, row in summary.iterrows():
            context = {
                "suite_step": row.get("suite_step"),
                "variant_name": row.get("variant_name"),
                "universe_name": row.get("universe_name"),
            }
            _add_problem(rows, context, "buy_expectancy_10d", row.get("buy_expectancy_10d"), 0.0, "higher", 5)
            _add_problem(rows, context, "p_win_10d_ece", row.get("p_win_10d_ece"), 0.06, "lower", 4)
            _add_problem(rows, context, "p_win_10d_best_bucket_wilson_lower", row.get("p_win_10d_best_bucket_wilson_lower"), 0.50, "higher", 4)
            _add_problem(rows, context, "max_risk_contribution_observed", row.get("max_risk_contribution_observed"), 0.35, "lower", 4)
            _add_problem(rows, context, "holding_portfolio_return", row.get("holding_portfolio_return"), 0.0, "higher", 3)
            _add_problem(rows, context, "benchmark_excess_return", row.get("benchmark_excess_return"), 0.0, "higher", 3)
            _add_problem(rows, context, "sell_expectancy_10d", row.get("sell_expectancy_10d"), 0.0, "higher", 2)
    if validation is not None and not validation.empty:
        failed = validation[validation.get("gate_status", pd.Series(dtype=object)).astype(str).eq("fail")]
        for _, row in failed.iterrows():
            item = {
                "suite_step": row.get("suite_step"),
                "variant_name": row.get("variant_name"),
                "universe_name": row.get("universe_name"),
                "problem": f"validation_fail:{row.get('gate_name')}",
                "observed_value": row.get("observed_value"),
                "threshold": row.get("threshold"),
                "severity": 3,
                "interpretation": row.get("research_interpretation", "validation gate failed"),
            }
            rows.append(item)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["severity", "suite_step", "problem"], ascending=[False, True, True]).reset_index(drop=True)


def _add_problem(rows: list[dict], context: dict, metric: str, value, threshold: float, direction: str, severity: int) -> None:
    try:
        observed = float(value)
    except Exception:
        observed = np.nan
    failed = not np.isfinite(observed)
    if direction == "higher":
        failed = failed or observed <= threshold
    else:
        failed = failed or observed > threshold
    if not failed:
        return
    item = dict(context)
    item.update(
        {
            "problem": metric,
            "observed_value": observed,
            "threshold": threshold,
            "severity": int(severity),
            "interpretation": _metric_interpretation(metric, observed),
        }
    )
    rows.append(item)


def _metric_interpretation(metric: str, observed: float) -> str:
    if metric == "buy_expectancy_10d":
        return "executed buys do not show positive 10-day expectancy; do not raise exposure"
    if metric == "p_win_10d_ece":
        return "probability calibration error is too high for probability-driven sizing"
    if metric == "p_win_10d_best_bucket_wilson_lower":
        return "best probability bucket lower bound is below 50%; p_win cannot justify high exposure"
    if metric == "max_risk_contribution_observed":
        return "single-name or common-factor risk is too concentrated"
    if metric == "holding_portfolio_return":
        return "stock sleeve itself is not profitable"
    if metric == "benchmark_excess_return":
        return "strategy fails to beat the top-strength benchmark"
    if metric == "sell_expectancy_10d":
        return "sell timing does not avoid forward losses reliably"
    return "metric failed diagnostic threshold"


def _latest_group_sum(group: pd.DataFrame, column: str) -> float:
    if "date" not in group.columns:
        return float(pd.to_numeric(group[column], errors="coerce").fillna(0.0).sum())
    dates = pd.to_datetime(group["date"], errors="coerce")
    if dates.notna().any():
        latest = dates.max()
        sub = group[dates.eq(latest)]
    else:
        sub = group.tail(1)
    return float(pd.to_numeric(sub[column], errors="coerce").fillna(0.0).sum())


def _save_csv(data: pd.DataFrame, path: Path) -> Path:
    data.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _save_plots(
    summary: pd.DataFrame,
    payoff: pd.DataFrame,
    calibration: pd.DataFrame,
    risk: pd.DataFrame,
    modules: pd.DataFrame,
    increments: pd.DataFrame,
    output_dir: Path,
    suite_id: str,
) -> dict[str, Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return {}
    saved: dict[str, Path] = {}
    if summary is not None and not summary.empty:
        path = output_dir / f"layer_ablation_overview_{suite_id}.png"
        _plot_overview(plt, summary, path)
        if path.exists():
            saved["overview_plot"] = path
    if payoff is not None and not payoff.empty:
        path = output_dir / f"layer_ablation_entry_sell_payoff_{suite_id}.png"
        _plot_payoff(plt, payoff, path)
        if path.exists():
            saved["payoff_plot"] = path
    if calibration is not None and not calibration.empty:
        path = output_dir / f"layer_ablation_probability_calibration_{suite_id}.png"
        _plot_calibration(plt, calibration, path)
        if path.exists():
            saved["calibration_plot"] = path
    if risk is not None and not risk.empty:
        path = output_dir / f"layer_ablation_risk_concentration_{suite_id}.png"
        _plot_risk(plt, risk, path)
        if path.exists():
            saved["risk_plot"] = path
    if modules is not None and not modules.empty:
        path = output_dir / f"layer_ablation_module_weights_{suite_id}.png"
        _plot_modules(plt, modules, path)
        if path.exists():
            saved["module_plot"] = path
    if increments is not None and not increments.empty:
        path = output_dir / f"layer_ablation_incremental_contribution_{suite_id}.png"
        _plot_incremental(plt, increments, path)
        if path.exists():
            saved["incremental_plot"] = path
    return saved


def _plot_overview(plt, summary: pd.DataFrame, path: Path) -> None:
    data = summary.copy()
    data["label"] = data["suite_step"].astype(str).str.replace("_", "\n", regex=False)
    metrics = [
        ("total_return", "Account Return"),
        ("holding_portfolio_return", "Holding Return"),
        ("benchmark_excess_return", "Top30 Excess"),
        ("buy_expectancy_10d", "Buy Exp 10D"),
        ("max_drawdown", "Max DD"),
        ("max_risk_contribution_observed", "Max Risk Contr."),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(18, 9))
    colors = ["#1f7a5a", "#2c7fb8", "#d4a84f", "#a35f2a", "#b3403a"]
    for axis, (metric, title) in zip(axes.ravel(), metrics):
        vals = _numeric_column(data, metric)
        axis.bar(data["label"], vals, color=colors[: len(data)])
        axis.axhline(0, color="#30343b", linewidth=0.8)
        axis.set_title(title)
        axis.grid(axis="y", alpha=0.25)
        axis.tick_params(axis="x", labelrotation=0, labelsize=8)
    fig.suptitle("Layer Ablation Suite Overview", fontsize=15, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_payoff(plt, payoff: pd.DataFrame, path: Path) -> None:
    data = payoff.copy()
    data["horizon_days"] = _numeric_column(data, "horizon_days")
    data = data[data["horizon_days"].eq(10)]
    data = data[data.get("side", pd.Series(dtype=object)).astype(str).isin(["buy", "sell"])]
    if data.empty:
        return
    pivot = data.pivot_table(index="suite_step", columns="side", values="expectancy", aggfunc="mean").fillna(0.0)
    fig, axis = plt.subplots(figsize=(13, 6))
    pivot.plot(kind="bar", ax=axis, color={"buy": "#2c7fb8", "sell": "#b3403a"})
    axis.axhline(0, color="#30343b", linewidth=0.8)
    axis.set_title("10D Buy/Sell Expectancy by Layer")
    axis.set_ylabel("Expectancy")
    axis.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_calibration(plt, calibration: pd.DataFrame, path: Path) -> None:
    data = calibration.copy()
    data["horizon_days"] = _numeric_column(data, "horizon_days")
    data = data[data["horizon_days"].eq(10)]
    if data.empty:
        return
    fig, axis = plt.subplots(figsize=(14, 7))
    for step, group in data.groupby("suite_step"):
        group = group.sort_values("predicted_p_mean")
        axis.plot(group["predicted_p_mean"], group["realized_win_rate"], marker="o", linewidth=1.2, label=str(step))
    axis.plot([0.35, 0.70], [0.35, 0.70], "--", color="#30343b", alpha=0.6, label="perfect calibration")
    axis.set_title("10D Probability Calibration")
    axis.set_xlabel("Predicted p_win")
    axis.set_ylabel("Realized win rate")
    axis.grid(alpha=0.25)
    axis.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_risk(plt, risk: pd.DataFrame, path: Path) -> None:
    data = risk.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    data["max_risk_contribution"] = _numeric_column(data, "max_risk_contribution")
    data = data.dropna(subset=["date", "max_risk_contribution"])
    if data.empty:
        return
    fig, axis = plt.subplots(figsize=(15, 6))
    for step, group in data.groupby("suite_step"):
        group = group.sort_values("date")
        axis.plot(group["date"], group["max_risk_contribution"].rolling(10, min_periods=1).mean(), linewidth=1.1, label=str(step))
    axis.axhline(0.35, color="#b3403a", linestyle="--", linewidth=1.0, label="research limit 35%")
    axis.axhline(0.25, color="#d4a84f", linestyle="--", linewidth=1.0, label="deployment limit 25%")
    axis.set_title("Rolling Max Risk Contribution by Layer")
    axis.set_ylabel("Max risk contribution")
    axis.grid(alpha=0.25)
    axis.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_modules(plt, modules: pd.DataFrame, path: Path) -> None:
    data = modules.copy()
    data["avg_weight_share"] = _numeric_column(data, "avg_weight_share", default=0.0).fillna(0.0)
    pivot = data.pivot_table(index="suite_step", columns="factor_module", values="avg_weight_share", aggfunc="sum").fillna(0.0)
    if pivot.empty:
        return
    fig, axis = plt.subplots(figsize=(14, 6))
    pivot.plot(kind="bar", stacked=True, ax=axis, colormap="tab20")
    axis.set_title("Average Factor Module Weight Share by Layer")
    axis.set_ylabel("Weight share")
    axis.grid(axis="y", alpha=0.25)
    axis.legend(loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_incremental(plt, increments: pd.DataFrame, path: Path) -> None:
    data = increments.copy()
    if "suite_step" not in data.columns:
        return
    data = data[~data["suite_step"].astype(str).eq("01_core_base")].copy()
    if data.empty:
        return
    data["label"] = data["suite_step"].astype(str).str.replace("_", "\n", regex=False)
    metrics = [
        ("buy_expectancy_10d_delta_vs_core_base", "Buy Exp 10D Delta"),
        ("holding_portfolio_return_delta_vs_core_base", "Holding Return Delta"),
        ("benchmark_excess_return_delta_vs_core_base", "Top30 Excess Delta"),
        ("max_risk_contribution_observed_delta_vs_core_base", "Risk Contribution Delta"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(18, 9))
    for axis, (metric, title) in zip(axes.ravel(), metrics):
        values = _numeric_column(data, metric, default=0.0).fillna(0.0)
        colors = ["#1f7a5a" if value >= 0 else "#b3403a" for value in values]
        axis.bar(data["label"], values, color=colors)
        axis.axhline(0, color="#30343b", linewidth=0.8)
        axis.set_title(title)
        axis.grid(axis="y", alpha=0.25)
        axis.tick_params(axis="x", labelsize=7)
    fig.suptitle("Incremental Contribution vs 01_core_base", fontsize=15, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _save_markdown_report(summary: pd.DataFrame, increments: pd.DataFrame, problems: pd.DataFrame, saved: dict[str, Path], path: Path) -> Path:
    lines = [
        "# Governance Enhanced Module Diagnostic Report",
        "",
        "## Summary",
        "",
    ]
    if summary is None or summary.empty:
        lines.append("No summary rows were available.")
    else:
        display_cols = [col for col in ["suite_step", *KEY_METRICS] if col in summary.columns]
        lines.append(_markdown_table(summary[display_cols]))
    lines.extend(["", "## Incremental Contribution vs 01_core_base", ""])
    if increments is None or increments.empty:
        lines.append("No incremental contribution rows were available.")
    else:
        display_cols = [
            col
            for col in [
                "suite_step",
                "buy_expectancy_10d_delta_vs_core_base",
                "holding_portfolio_return_delta_vs_core_base",
                "benchmark_excess_return_delta_vs_core_base",
                "max_risk_contribution_observed_delta_vs_core_base",
                "research_action",
            ]
            if col in increments.columns
        ]
        lines.append(_markdown_table(increments[display_cols]))
    lines.extend(["", "## Problem Ranking", ""])
    if problems is None or problems.empty:
        lines.append("No diagnostic threshold failures were detected.")
    else:
        display_cols = [col for col in ["severity", "suite_step", "problem", "observed_value", "threshold", "interpretation"] if col in problems.columns]
        lines.append(_markdown_table(problems[display_cols].head(30)))
    lines.extend(["", "## Generated Files", ""])
    for name, file_path in saved.items():
        lines.append(f"- `{name}`: `{file_path}`")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _markdown_table(data: pd.DataFrame) -> str:
    """Render a small Markdown table without requiring the optional tabulate package."""
    if data is None or data.empty:
        return ""
    frame = data.copy()
    for column in frame.columns:
        if pd.api.types.is_float_dtype(frame[column]):
            frame[column] = frame[column].map(lambda value: "" if pd.isna(value) else f"{float(value):.6g}")
        else:
            frame[column] = frame[column].map(lambda value: "" if pd.isna(value) else str(value))
    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in frame.iterrows():
        values = [str(row[column]).replace("|", "\\|") for column in frame.columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)
