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
    annual_return = float((1.0 + total_return) ** (252.0 / max(len(data), 1)) - 1.0)
    sharpe = annual_return / annual_vol if annual_vol > 0 else float("nan")

    fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
    axes[0].plot(data["date"], data["net_value"], color="#1f77b4", linewidth=1.4)
    axes[0].set_ylabel("Net value")
    axes[0].set_title(
        f"Governance daily performance | Return {total_return:.2%} | Sharpe {sharpe:.3f} | Max DD {max_drawdown:.2%}"
    )
    axes[0].grid(alpha=0.25)

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
