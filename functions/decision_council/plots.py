"""Diagnostic charts emitted after an exploratory governance backtest."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def save_governance_diagnostic_plots(
    *,
    daily_result: pd.DataFrame,
    reputation_ledger: pd.DataFrame,
    safety_ledger: pd.DataFrame,
    execution_ledger: pd.DataFrame,
    feature_data: pd.DataFrame,
    output_dir,
) -> dict[str, Path]:
    """Save three governance charts without making plotting a runtime dependency."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("Skip governance diagnostic plots: matplotlib is not installed.")
        return {}

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    saved = {}
    if not daily_result.empty:
        path = output / "governance_performance_risk.png"
        _plot_performance_risk(plt, daily_result, path)
        saved["governance_performance_risk_plot"] = path
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
    return saved


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
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
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
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
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
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
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
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return True
