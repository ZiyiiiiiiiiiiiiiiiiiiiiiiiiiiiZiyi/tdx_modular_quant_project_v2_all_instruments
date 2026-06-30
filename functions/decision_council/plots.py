"""Diagnostic charts emitted after an exploratory governance backtest."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def save_governance_diagnostic_plots(
    *,
    daily_result: pd.DataFrame,
    holdings_ledger: pd.DataFrame,
    reputation_ledger: pd.DataFrame,
    safety_ledger: pd.DataFrame,
    execution_ledger: pd.DataFrame,
    attribution_ledger: pd.DataFrame | None = None,
    bucket_attribution: pd.DataFrame | None = None,
    factor_weight_ledger: pd.DataFrame | None = None,
    feature_data: pd.DataFrame,
    output_dir,
) -> dict[str, Path]:
    """Save governance diagnostics without making plotting a runtime dependency."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("Skip governance diagnostic plots: matplotlib is not installed.")
        return {}

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    visual_output = output / "visual_exports"
    visual_output.mkdir(parents=True, exist_ok=True)
    saved = {}
    if not daily_result.empty:
        path = output / "governance_performance_risk.png"
        _plot_performance_risk(plt, daily_result, path)
        saved["governance_performance_risk_plot"] = path
        path = output / "governance_capital_allocation.png"
        _plot_capital_allocation(plt, daily_result, path)
        saved["governance_capital_allocation_plot"] = path
    if attribution_ledger is not None and not attribution_ledger.empty:
        path = output / "governance_benchmark_exposure_attribution.png"
        if _plot_benchmark_exposure_attribution(plt, attribution_ledger, path):
            saved["governance_benchmark_exposure_attribution_plot"] = path
        account_png = visual_output / "account_vs_top30_benchmark.png"
        account_gif = visual_output / "account_vs_top30_benchmark.gif"
        account_saved = _plot_account_vs_benchmark_export(plt, attribution_ledger, account_png, account_gif)
        if account_saved is not None:
            saved["governance_account_vs_top30_benchmark_export"] = account_saved
    if bucket_attribution is not None and not bucket_attribution.empty:
        path = output / "governance_bucket_attribution.png"
        if _plot_bucket_attribution(plt, bucket_attribution, path):
            saved["governance_bucket_attribution_plot"] = path
    if factor_weight_ledger is not None and not factor_weight_ledger.empty:
        path = output / "governance_factor_module_weights.png"
        if _plot_factor_module_weights(plt, factor_weight_ledger, path):
            saved["governance_factor_module_weight_plot"] = path
    if not reputation_ledger.empty:
        path = output / "governance_model_reputation_scores.png"
        _plot_model_scores(plt, reputation_ledger, path)
        saved["governance_model_reputation_plot"] = path
    if not daily_result.empty and not safety_ledger.empty:
        path = output / "governance_safety_forced_deleveraging_points.png"
        _plot_safety_points(plt, daily_result, safety_ledger, path)
        saved["governance_safety_points_plot"] = path
    if not execution_ledger.empty and not feature_data.empty:
        path = output / "governance_decision_accuracy.png"
        if _plot_decision_accuracy(plt, execution_ledger, feature_data, path):
            saved["governance_decision_accuracy_plot"] = path
    if not holdings_ledger.empty:
        path = output / "governance_top_holdings_latest.png"
        if _plot_top_holdings_latest(plt, holdings_ledger, path):
            saved["governance_top_holdings_latest_plot"] = path
        animation_path = visual_output / "holding_price_paths_180d.gif"
        static_path = visual_output / "holding_price_paths_180d.png"
        saved_path = _plot_selected_holdings_180d(plt, holdings_ledger, feature_data, animation_path, static_path)
        if saved_path is not None:
            key = "governance_selected_holdings_180d_animation" if saved_path.suffix.lower() == ".gif" else "governance_selected_holdings_180d_plot"
            saved[key] = saved_path
    return saved


def _safe_savefig(fig, output_path, *, dpi=220, bbox_inches="tight"):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches=bbox_inches)


def _plot_performance_risk(plt, daily_result, output_path):
    data = daily_result.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["liquidatable_nav"] = pd.to_numeric(data["liquidatable_nav"], errors="coerce")
    data = data.dropna(subset=["date", "liquidatable_nav"]).sort_values("date")
    nav = data["liquidatable_nav"].clip(lower=1e-12)
    initial_nav = float(nav.iloc[0])
    data["net_value"] = nav / initial_nav
    data["daily_return"] = nav.pct_change(fill_method=None).fillna(0.0)
    data["drawdown"] = data["net_value"] / data["net_value"].cummax() - 1.0
    rolling_mean = data["daily_return"].rolling(20, min_periods=5).mean()
    rolling_std = data["daily_return"].rolling(20, min_periods=5).std(ddof=0)
    data["rolling_sharpe_20d"] = (rolling_mean / rolling_std.replace(0.0, np.nan)) * np.sqrt(252)
    total_return = float(data["net_value"].iloc[-1] - 1.0)
    max_drawdown = float(data["drawdown"].min())
    annual_vol = float(data["daily_return"].std(ddof=0) * np.sqrt(252))
    n_days = len(data)
    annual_return = float((1.0 + total_return) ** (252.0 / max(n_days, 1)) - 1.0)
    sharpe = annual_return / annual_vol if annual_vol > 0 else float("nan")
    calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else float("nan")
    downside = data.loc[data["daily_return"] < 0, "daily_return"]
    downside_vol = float(downside.std(ddof=0) * np.sqrt(252)) if len(downside) > 0 else float("nan")
    sortino = (annual_return - 0.0) / downside_vol if downside_vol and downside_vol > 0 else float("nan")

    # Max drawdown period
    dd_series = data["drawdown"]
    dd_period_str = ""
    if len(dd_series) > 0:
        max_dd_idx = dd_series.idxmin()
        max_dd_date = data.loc[max_dd_idx, "date"] if max_dd_idx in data.index else None
        peak_mask = dd_series[:max_dd_idx + 1] == 0
        if peak_mask.any():
            peak_idx = peak_mask[peak_mask].index[-1]
            dd_start = data.loc[peak_idx, "date"]
        else:
            dd_start = data["date"].iloc[0]
        recovery_mask = dd_series[max_dd_idx:] == 0
        if recovery_mask.any():
            recovery_idx = recovery_mask[recovery_mask].index[0]
            dd_end = data.loc[recovery_idx, "date"]
        else:
            dd_end = data["date"].iloc[-1]
        dd_period_str = f"DD: {dd_start.strftime('%Y-%m-%d') if hasattr(dd_start, 'strftime') else dd_start} -> {dd_end.strftime('%Y-%m-%d') if hasattr(dd_end, 'strftime') else dd_end}"

    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
    axes[0].plot(data["date"], data["net_value"], color="#1f77b4", linewidth=1.4)
    axes[0].set_ylabel("Net value")
    title = (
        f"Governance | Return {total_return:.2%} | Sharpe {sharpe:.3f} | "
        f"Calmar {calmar:.3f} | Sortino {sortino:.3f} | Max DD {max_drawdown:.2%}"
    )
    if dd_period_str:
        title += f"\n{dd_period_str}"
    axes[0].set_title(title, fontsize=10)
    axes[0].grid(alpha=0.25)
    if max_dd_date is not None:
        axes[0].axvline(max_dd_date, color="red", linestyle="--", alpha=0.5, linewidth=0.8)

    axes[1].fill_between(data["date"], data["drawdown"], 0.0, color="#d62728", alpha=0.35)
    axes[1].plot(data["date"], data["drawdown"], color="#d62728", linewidth=1.0)
    axes[1].set_ylabel("Drawdown")
    axes[1].grid(alpha=0.25)

    axes[2].bar(data["date"], data["daily_return"], color=np.where(data["daily_return"] >= 0, "#2ca02c", "#d62728"), width=1.0)
    sharpe_axis = axes[2].twinx()
    sharpe_axis.plot(data["date"], data["rolling_sharpe_20d"], color="#9467bd", linewidth=1.1)
    axes[2].set_ylabel("Daily return")
    sharpe_axis.set_ylabel("20D rolling Sharpe")
    axes[2].grid(alpha=0.25)
    fig.tight_layout()
    _safe_savefig(fig, output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_capital_allocation(plt, daily_result, output_path):
    data = daily_result.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["cash"] = pd.to_numeric(data.get("cash", pd.Series(dtype=float)), errors="coerce")
    data["invested_value"] = pd.to_numeric(data.get("invested_value", pd.Series(dtype=float)), errors="coerce")
    data["nominal_nav"] = pd.to_numeric(data.get("nominal_nav", pd.Series(dtype=float)), errors="coerce")
    data = data.dropna(subset=["date", "nominal_nav"]).sort_values("date")
    if data.empty:
        return

    data["cash_ratio"] = data["cash"] / data["nominal_nav"].replace(0.0, np.nan)
    data["invested_ratio"] = data["invested_value"] / data["nominal_nav"].replace(0.0, np.nan)

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    axes[0].plot(data["date"], data["cash"], color="#c47f17", linewidth=1.2, label="Cash")
    axes[0].plot(data["date"], data["invested_value"], color="#1f77b4", linewidth=1.2, label="Invested")
    axes[0].set_ylabel("Value")
    axes[0].set_title("Governance capital allocation")
    axes[0].legend(loc="best")
    axes[0].grid(alpha=0.25)

    axes[1].fill_between(data["date"], data["cash_ratio"].fillna(0.0), color="#f2c66d", alpha=0.6, label="Cash ratio")
    axes[1].fill_between(data["date"], 0.0, data["invested_ratio"].fillna(0.0), color="#7fb3e6", alpha=0.6, label="Invested ratio")
    axes[1].set_ylabel("Ratio")
    axes[1].set_ylim(0.0, 1.05)
    axes[1].legend(loc="best")
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    _safe_savefig(fig, output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_model_scores(plt, reputation_ledger, output_path):
    data = reputation_ledger.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["score_ema"] = pd.to_numeric(data["score_ema"], errors="coerce")
    data["active_reputation_weight"] = pd.to_numeric(data["active_reputation_weight"], errors="coerce")
    data = data.dropna(subset=["date", "model_name", "score_ema"]).sort_values("date")
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    for model_name, rows in data.groupby("model_name"):
        axes[0].plot(rows["date"], rows["score_ema"], linewidth=1.2, label=str(model_name))
        axes[1].plot(rows["date"], rows["active_reputation_weight"], linewidth=1.2, label=str(model_name))
    axes[0].set_title("Governance model reputation scores")
    axes[0].set_ylabel("Reward EWMA score")
    axes[1].set_ylabel("Active voting weight")
    axes[1].set_xlabel("Date")
    for axis in axes:
        axis.grid(alpha=0.25)
        axis.legend(loc="best")
    fig.tight_layout()
    _safe_savefig(fig, output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_safety_points(plt, daily_result, safety_ledger, output_path):
    daily = daily_result.copy()
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
    daily["liquidatable_nav"] = pd.to_numeric(daily["liquidatable_nav"], errors="coerce")
    daily = daily.dropna(subset=["date", "liquidatable_nav"]).sort_values("date")
    daily["net_value"] = daily["liquidatable_nav"] / max(float(daily["liquidatable_nav"].iloc[0]), 1e-12)

    safety = safety_ledger.copy()
    date_col = "decision_date" if "decision_date" in safety.columns else "date"
    safety["date"] = pd.to_datetime(safety[date_col], errors="coerce")
    safety["exposure_cap"] = pd.to_numeric(safety["exposure_cap"], errors="coerce")
    safety = safety.dropna(subset=["date", "risk_level", "exposure_cap"]).drop_duplicates("date", keep="last")
    merged = daily.merge(safety[["date", "risk_level", "exposure_cap"]], on="date", how="left")
    colors = {"warning": "#ffbf00", "high": "#ff7f0e", "crisis": "#d62728"}

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    axes[0].plot(merged["date"], merged["net_value"], color="#1f77b4", linewidth=1.3, label="Liquidatable net value")
    for level in ("warning", "high", "crisis"):
        points = merged[merged["risk_level"] == level]
        axes[0].scatter(points["date"], points["net_value"], color=colors[level], s=28 if level != "crisis" else 52, label=level, zorder=3)
    axes[0].set_title("Safety-council forced deleveraging and zero-exposure points")
    axes[0].set_ylabel("Net value")
    axes[0].legend(loc="best")
    axes[0].grid(alpha=0.25)

    axes[1].step(merged["date"], merged["exposure_cap"], where="post", color="#444444", linewidth=1.2, label="Safety exposure cap")
    crisis = merged[merged["exposure_cap"] <= 0.0]
    axes[1].scatter(crisis["date"], crisis["exposure_cap"], color="#d62728", marker="x", s=70, label="Forced zero exposure", zorder=3)
    axes[1].set_ylabel("Exposure cap")
    axes[1].set_xlabel("Date")
    axes[1].set_ylim(-0.05, 1.05)
    axes[1].legend(loc="best")
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    _safe_savefig(fig, output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _plot_decision_accuracy(plt, execution_ledger, feature_data, output_path) -> bool:
    decisions = execution_ledger.copy()
    decisions["trade_date"] = pd.to_datetime(decisions["trade_date"], errors="coerce")
    decisions["price"] = pd.to_numeric(decisions["price"], errors="coerce")
    decisions = decisions[
        decisions["execution_status"].astype(str).eq("filled")
        & decisions["side"].astype(str).isin(["buy", "sell"])
    ].copy()
    if decisions.empty:
        return False

    prices = feature_data.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    close_col = "close_nominal" if "close_nominal" in prices.columns else "close"
    prices[close_col] = pd.to_numeric(prices[close_col], errors="coerce")
    prices = prices.dropna(subset=["date", "symbol", close_col]).sort_values(["symbol", "date"])
    prices["future_close_5d"] = prices.groupby("symbol")[close_col].shift(-5)
    prices = prices[["symbol", "date", "future_close_5d"]].rename(columns={"date": "trade_date"})

    scored = decisions.merge(prices, on=["symbol", "trade_date"], how="left")
    scored = scored.dropna(subset=["price", "future_close_5d"]).copy()
    if scored.empty:
        return False

    scored["forward_return_5d"] = scored["future_close_5d"] / scored["price"] - 1.0
    scored["correct"] = np.where(
        scored["side"].eq("buy"),
        scored["forward_return_5d"] > 0.0,
        scored["forward_return_5d"] < 0.0,
    )
    scored["correct_flag"] = scored["correct"].astype(float)
    scored = scored.sort_values("trade_date")
    scored["cumulative_accuracy"] = scored["correct_flag"].expanding().mean()

    reason_accuracy = (
        scored.groupby("reason", dropna=False)["correct_flag"]
        .agg(["mean", "count"])
        .sort_values(["mean", "count"], ascending=[False, False])
        .reset_index()
    )
    side_accuracy = scored.groupby("side", dropna=False)["correct_flag"].mean().reindex(["buy", "sell"]).fillna(0.0)
    overall_accuracy = float(scored["correct_flag"].mean())

    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=False, gridspec_kw={"height_ratios": [2.2, 1.2, 1.2]})
    axes[0].plot(scored["trade_date"], scored["cumulative_accuracy"], color="#1f77b4", linewidth=1.5)
    axes[0].scatter(
        scored["trade_date"],
        scored["cumulative_accuracy"],
        c=np.where(scored["correct"], "#2ca02c", "#d62728"),
        s=18,
        alpha=0.8,
    )
    axes[0].axhline(0.5, color="#666666", linestyle="--", linewidth=1.0)
    axes[0].set_ylim(0.0, 1.0)
    axes[0].set_ylabel("Cumulative accuracy")
    axes[0].set_title(
        f"Governance decision accuracy (5D) | Overall {overall_accuracy:.2%} | Samples {len(scored)}"
    )
    axes[0].grid(alpha=0.25)

    axes[1].bar(side_accuracy.index.astype(str), side_accuracy.to_numpy(dtype=float), color=["#2ca02c", "#d62728"])
    axes[1].axhline(0.5, color="#666666", linestyle="--", linewidth=1.0)
    axes[1].set_ylim(0.0, 1.0)
    axes[1].set_ylabel("Accuracy")
    axes[1].set_title("Accuracy by side")
    axes[1].grid(alpha=0.25, axis="y")

    top_reason = reason_accuracy.head(8).copy()
    labels = [f"{reason}\n(n={count})" for reason, count in zip(top_reason["reason"], top_reason["count"])]
    axes[2].bar(labels, top_reason["mean"].to_numpy(dtype=float), color="#9467bd")
    axes[2].axhline(0.5, color="#666666", linestyle="--", linewidth=1.0)
    axes[2].set_ylim(0.0, 1.0)
    axes[2].set_ylabel("Accuracy")
    axes[2].set_title("Top decision reasons by sample count")
    axes[2].grid(alpha=0.25, axis="y")
    for tick in axes[2].get_xticklabels():
        tick.set_rotation(15)
        tick.set_ha("right")

    fig.tight_layout()
    _safe_savefig(fig, output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return True


def _plot_top_holdings_latest(plt, holdings_ledger, output_path) -> bool:
    data = holdings_ledger.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["market_value"] = pd.to_numeric(data["market_value"], errors="coerce")
    data["weight"] = pd.to_numeric(data.get("weight", pd.Series(dtype=float)), errors="coerce")
    data = data.dropna(subset=["date", "symbol", "market_value"]).sort_values(["date", "market_value"], ascending=[True, False])
    if data.empty:
        return False

    latest_date = data["date"].max()
    latest = data[data["date"] == latest_date].copy().sort_values("market_value", ascending=False).head(12)
    if latest.empty:
        return False

    labels = [str(symbol) for symbol in latest["symbol"]]
    values = latest["market_value"].to_numpy(dtype=float)
    weights = latest["weight"].fillna(0.0).to_numpy(dtype=float)

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    axes[0].barh(labels[::-1], values[::-1], color="#1f77b4")
    axes[0].set_title(f"Top holdings by market value ({latest_date.date()})")
    axes[0].set_xlabel("Market value")
    axes[0].grid(alpha=0.25, axis="x")

    axes[1].barh(labels[::-1], weights[::-1], color="#2ca02c")
    axes[1].set_title("Holding weights")
    axes[1].set_xlabel("Weight")
    axes[1].set_xlim(0.0, max(float(weights.max()) * 1.15, 0.05))
    axes[1].grid(alpha=0.25, axis="x")

    fig.tight_layout()
    _safe_savefig(fig, output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return True


def _plot_benchmark_exposure_attribution(plt, attribution_ledger, output_path) -> bool:
    data = attribution_ledger.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    required = [
        "account_net_value",
        "invested_capital_net_value",
        "valid_invested_capital_net_value",
        "holding_portfolio_net_value",
        "benchmark_net_value",
        "excess_net_value",
        "actual_exposure",
        "account_drawdown",
        "invested_capital_drawdown",
    ]
    for column in required:
        data[column] = pd.to_numeric(data.get(column, pd.Series(dtype=float)), errors="coerce")
    data = data.dropna(subset=["date"]).sort_values("date")
    if data.empty:
        return False

    fig, axes = plt.subplots(3, 1, figsize=(15, 12), sharex=True, gridspec_kw={"height_ratios": [2.0, 1.0, 1.0]})
    axes[0].plot(data["date"], data["account_net_value"], label="Account NAV (cash included)", color="#147a54", linewidth=1.4)
    axes[0].plot(data["date"], data["invested_capital_net_value"], label="Raw invested-capital NAV", color="#9b59b6", linewidth=1.0, alpha=0.55)
    axes[0].plot(data["date"], data["valid_invested_capital_net_value"], label="Valid invested NAV (exposure>=5%)", color="#2c7fb8", linewidth=1.3)
    axes[0].plot(data["date"], data["holding_portfolio_net_value"], label="Holding portfolio NAV approx", color="#0f766e", linewidth=1.1)
    axes[0].plot(data["date"], data["benchmark_net_value"], label="Benchmark NAV", color="#666666", linewidth=1.1)
    axes[0].plot(data["date"], data["excess_net_value"], label="Account excess NAV", color="#d4a84f", linewidth=1.1)
    axes[0].axhline(1.0, color="#999999", linestyle="--", linewidth=0.8)
    axes[0].set_title("Account vs invested capital vs benchmark")
    axes[0].set_ylabel("Net value")
    axes[0].legend(loc="best")
    axes[0].grid(alpha=0.25)

    axes[1].plot(data["date"], data["account_drawdown"], label="Account drawdown", color="#b3403a", linewidth=1.1)
    axes[1].plot(data["date"], data["invested_capital_drawdown"], label="Invested-capital drawdown", color="#7f1d1d", linewidth=1.1)
    axes[1].fill_between(data["date"], data["account_drawdown"].fillna(0.0), 0.0, color="#d9827b", alpha=0.22)
    axes[1].set_ylabel("Drawdown")
    axes[1].legend(loc="best")
    axes[1].grid(alpha=0.25)

    axes[2].fill_between(data["date"], 0.0, data["actual_exposure"].fillna(0.0), color="#2c7fb8", alpha=0.45)
    axes[2].set_ylim(0.0, max(1.0, float(data["actual_exposure"].max(skipna=True) or 0.0) * 1.1))
    axes[2].set_ylabel("Actual exposure")
    axes[2].set_xlabel("Date")
    axes[2].grid(alpha=0.25)

    fig.tight_layout()
    _safe_savefig(fig, output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return True


def _plot_bucket_attribution(plt, bucket_attribution, output_path) -> bool:
    data = bucket_attribution.copy()
    preferred_metric = "valid_invested_excess_total_return" if "valid_invested_excess_total_return" in data.columns else "invested_excess_total_return"
    data[preferred_metric] = pd.to_numeric(data.get(preferred_metric), errors="coerce")
    data["avg_actual_exposure"] = pd.to_numeric(data.get("avg_actual_exposure"), errors="coerce")
    data = data.dropna(subset=["dimension", "bucket"])
    if data.empty:
        return False

    dimensions = [
        "holding_count_bucket",
        "exposure_bucket",
        "factor_entropy_bucket",
        "dominant_factor_module",
    ]
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    axes = axes.ravel()
    for axis, dimension in zip(axes, dimensions):
        subset = data[data["dimension"].astype(str).eq(dimension)].copy()
        subset = subset.sort_values(preferred_metric, ascending=False).head(10)
        if subset.empty:
            axis.set_title(f"{dimension}: no data")
            axis.axis("off")
            continue
        colors = np.where(subset[preferred_metric].fillna(0.0) >= 0, "#147a54", "#b3403a")
        axis.barh(subset["bucket"].astype(str)[::-1], subset[preferred_metric].fillna(0.0)[::-1], color=colors[::-1])
        axis.axvline(0.0, color="#666666", linewidth=0.8)
        axis.set_title(f"{dimension} | {preferred_metric}")
        axis.grid(alpha=0.25, axis="x")
    fig.tight_layout()
    _safe_savefig(fig, output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return True


def _plot_factor_module_weights(plt, factor_weight_ledger, output_path) -> bool:
    data = factor_weight_ledger.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["weight_share"] = pd.to_numeric(data.get("weight_share"), errors="coerce").clip(lower=0.0)
    data["factor_module"] = data.get("factor_module", pd.Series("unknown", index=data.index)).fillna("unknown").astype(str)
    data = data.dropna(subset=["date", "weight_share"])
    if data.empty:
        return False
    pivot = (
        data.groupby(["date", "factor_module"], as_index=False)["weight_share"]
        .sum()
        .pivot(index="date", columns="factor_module", values="weight_share")
        .fillna(0.0)
        .sort_index()
    )
    if pivot.empty:
        return False
    fig, axes = plt.subplots(2, 1, figsize=(15, 10), sharex=True, gridspec_kw={"height_ratios": [1.7, 1.0]})
    pivot.plot.area(ax=axes[0], linewidth=0.0, alpha=0.72)
    axes[0].set_title("Alpha factor module weight share")
    axes[0].set_ylabel("Share")
    axes[0].set_ylim(0.0, max(1.0, float(pivot.sum(axis=1).max()) * 1.05))
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="upper left", ncol=3, fontsize=8)

    top_factor = (
        data.sort_values(["date", "weight_share"], ascending=[True, False])
        .groupby("date", as_index=False)
        .head(1)
        .sort_values("date")
    )
    axes[1].plot(top_factor["date"], top_factor["weight_share"], color="#b3403a", linewidth=1.2, label="Top factor share")
    axes[1].set_ylabel("Top share")
    axes[1].set_xlabel("Date")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best")

    fig.tight_layout()
    _safe_savefig(fig, output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return True


def _plot_selected_holdings_180d(plt, holdings_ledger, feature_data, gif_path, png_path) -> Path | None:
    latest = holdings_ledger.copy()
    latest["date"] = pd.to_datetime(latest["date"], errors="coerce")
    latest["market_value"] = pd.to_numeric(latest.get("market_value"), errors="coerce")
    latest = latest.dropna(subset=["date", "symbol", "market_value"])
    if latest.empty or feature_data is None or feature_data.empty:
        return None
    latest_date = latest["date"].max()
    symbols = (
        latest[latest["date"].eq(latest_date)]
        .sort_values("market_value", ascending=False)["symbol"]
        .astype(str)
        .head(6)
        .tolist()
    )
    if not symbols:
        return None

    prices = feature_data.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    close_col = "close_nominal" if "close_nominal" in prices.columns else "close"
    prices[close_col] = pd.to_numeric(prices[close_col], errors="coerce")
    start_date = latest_date - pd.Timedelta(days=270)
    prices = prices[
        prices["symbol"].astype(str).isin(symbols)
        & prices["date"].between(start_date, latest_date)
    ].dropna(subset=["date", "symbol", close_col]).sort_values(["symbol", "date"])
    if prices.empty:
        return None

    pivot = prices.pivot_table(index="date", columns="symbol", values=close_col, aggfunc="last").sort_index().ffill()
    pivot = pivot.tail(180)
    if len(pivot) < 2:
        return None
    normalized = pivot / pivot.iloc[0].replace(0.0, np.nan)
    latest_rows = (
        latest[latest["date"].eq(latest_date)]
        .sort_values("market_value", ascending=False)
        .drop_duplicates("symbol", keep="first")
        .set_index("symbol")
    )

    fig, axis = plt.subplots(figsize=(15, 8))
    palette = ["#147a54", "#b3403a", "#2c7fb8", "#d4a84f", "#8a5a44", "#465a7a"]
    for idx, column in enumerate(normalized.columns):
        color = palette[idx % len(palette)]
        row = latest_rows.loc[column] if column in latest_rows.index else pd.Series(dtype=object)
        entry_date = pd.to_datetime(row.get("entry_date"), errors="coerce")
        unrealized_return = pd.to_numeric(pd.Series([row.get("unrealized_return")]), errors="coerce").iloc[0]
        entry_suffix = f" entry {unrealized_return:.2%}" if pd.notna(unrealized_return) else ""
        axis.plot(normalized.index, normalized[column], linewidth=1.4, color=color, label=f"{column}{entry_suffix}")
        if pd.notna(entry_date):
            entry_positions = normalized.index[normalized.index >= pd.Timestamp(entry_date)]
            if len(entry_positions) > 0:
                marker_date = entry_positions[0]
                marker_value = normalized.at[marker_date, column]
                if pd.notna(marker_value):
                    axis.scatter([marker_date], [marker_value], color=color, s=36, zorder=4)
                    axis.annotate(
                        pd.Timestamp(entry_date).strftime("%m-%d"),
                        xy=(marker_date, marker_value),
                        xytext=(4, 6),
                        textcoords="offset points",
                        fontsize=8,
                        color=color,
                    )
    axis.axhline(1.0, color="#666666", linestyle="--", linewidth=0.8)
    axis.set_title(f"Latest holdings 180 trading-day normalized price paths ({latest_date.date()})")
    axis.set_ylabel("Normalized close")
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, 1.18), ncol=3, fontsize=8)
    axis.grid(alpha=0.25)
    fig.tight_layout()
    _safe_savefig(fig, png_path, dpi=220, bbox_inches="tight")

    try:
        from matplotlib.animation import PillowWriter

        axis.clear()
        axis.axhline(1.0, color="#666666", linestyle="--", linewidth=0.8)
        axis.set_title(f"Latest holdings 180 trading-day normalized price paths ({latest_date.date()})")
        axis.set_ylabel("Normalized close")
        axis.grid(alpha=0.25)
        lines = []
        for idx, column in enumerate(normalized.columns):
            (line,) = axis.plot([], [], linewidth=1.5, color=palette[idx % len(palette)], label=str(column))
            lines.append((column, line))
        y_min = float(np.nanmin(normalized.to_numpy(dtype=float)))
        y_max = float(np.nanmax(normalized.to_numpy(dtype=float)))
        pad = max((y_max - y_min) * 0.08, 0.02)
        axis.set_ylim(y_min - pad, y_max + pad)
        axis.set_xlim(normalized.index.min(), normalized.index.max())
        axis.legend(loc="upper center", bbox_to_anchor=(0.5, 1.18), ncol=3, fontsize=8)
        fig.tight_layout()
        writer = PillowWriter(fps=7)
        Path(gif_path).parent.mkdir(parents=True, exist_ok=True)
        with writer.saving(fig, str(gif_path), dpi=110):
            for frame in range(len(normalized)):
                frame_data = normalized.iloc[: frame + 1]
                for column, line in lines:
                    line.set_data(frame_data.index, frame_data[column])
                writer.grab_frame()
        plt.close(fig)
        return gif_path
    except Exception:
        plt.close(fig)
        return png_path


def _plot_account_vs_benchmark_export(plt, attribution_ledger, png_path, gif_path) -> Path | None:
    data = attribution_ledger.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    for column in ["account_net_value", "benchmark_net_value", "excess_net_value", "actual_exposure"]:
        data[column] = pd.to_numeric(data.get(column, pd.Series(dtype=float)), errors="coerce")
    data = data.dropna(subset=["date", "account_net_value", "benchmark_net_value"]).sort_values("date")
    if len(data) < 2:
        return None
    fig, axis = plt.subplots(figsize=(15, 7))
    axis.plot(data["date"], data["account_net_value"], label="Account NAV", color="#147a54", linewidth=1.5)
    axis.plot(data["date"], data["benchmark_net_value"], label="Top strength 30% benchmark", color="#b3403a", linewidth=1.2)
    axis.plot(data["date"], data["excess_net_value"], label="Excess NAV", color="#d4a84f", linewidth=1.0)
    axis.axhline(1.0, color="#666666", linestyle="--", linewidth=0.8)
    axis.set_title("Account vs top strength 30% benchmark")
    axis.set_ylabel("Net value")
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, 1.15), ncol=3, fontsize=8)
    axis.grid(alpha=0.25)
    fig.tight_layout()
    _safe_savefig(fig, png_path, dpi=220, bbox_inches="tight")

    try:
        from matplotlib.animation import PillowWriter

        axis.clear()
        axis.axhline(1.0, color="#666666", linestyle="--", linewidth=0.8)
        axis.set_title("Account vs top strength 30% benchmark")
        axis.set_ylabel("Net value")
        axis.grid(alpha=0.25)
        series = [
            ("account_net_value", "Account NAV", "#147a54", 1.5),
            ("benchmark_net_value", "Top strength 30% benchmark", "#b3403a", 1.2),
            ("excess_net_value", "Excess NAV", "#d4a84f", 1.0),
        ]
        lines = []
        for column, label, color, width in series:
            (line,) = axis.plot([], [], label=label, color=color, linewidth=width)
            lines.append((column, line))
        values = data[[column for column, _, _, _ in series]].to_numpy(dtype=float)
        y_min = float(np.nanmin(values))
        y_max = float(np.nanmax(values))
        pad = max((y_max - y_min) * 0.08, 0.03)
        axis.set_ylim(y_min - pad, y_max + pad)
        axis.set_xlim(data["date"].min(), data["date"].max())
        axis.legend(loc="upper center", bbox_to_anchor=(0.5, 1.15), ncol=3, fontsize=8)
        fig.tight_layout()
        writer = PillowWriter(fps=8)
        Path(gif_path).parent.mkdir(parents=True, exist_ok=True)
        step = max(len(data) // 180, 1)
        frame_indexes = list(range(0, len(data), step))
        if frame_indexes[-1] != len(data) - 1:
            frame_indexes.append(len(data) - 1)
        with writer.saving(fig, str(gif_path), dpi=110):
            for frame in frame_indexes:
                frame_data = data.iloc[: frame + 1]
                for column, line in lines:
                    line.set_data(frame_data["date"], frame_data[column])
                writer.grab_frame()
        plt.close(fig)
        return gif_path
    except Exception:
        plt.close(fig)
        return png_path
