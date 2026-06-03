"""Additional performance charts and heatmap summaries."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def save_performance_diagnostics(
    *,
    daily_result: pd.DataFrame,
    strategy_name: str,
    output_dir,
    selection: pd.DataFrame | None = None,
) -> dict[str, Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("Skip performance diagnostics: matplotlib is not installed.")
        return {}

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    data = daily_result.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=["date"]).sort_values("date")
    saved = {}
    if not data.empty:
        path = output / f"performance_dashboard_{strategy_name}.png"
        _plot_dashboard(plt, data, path)
        saved["performance_dashboard"] = path
        heatmap_path = output / f"monthly_return_heatmap_{strategy_name}.png"
        summary_path = output / f"monthly_return_heatmap_{strategy_name}.txt"
        monthly = _plot_monthly_heatmap(plt, data, heatmap_path)
        _write_monthly_summary(monthly, summary_path)
        saved["monthly_return_heatmap"] = heatmap_path
        saved["monthly_return_heatmap_summary"] = summary_path
    if selection is not None and not selection.empty:
        kelly_path = output / f"kelly_distribution_{strategy_name}.png"
        summary_path = output / f"kelly_distribution_{strategy_name}.txt"
        if _plot_kelly_distribution(plt, selection, kelly_path):
            _write_kelly_summary(selection, summary_path)
            saved["kelly_distribution"] = kelly_path
            saved["kelly_distribution_summary"] = summary_path
    return saved


def _plot_dashboard(plt, data, output_path):
    net = pd.to_numeric(data["net_value"], errors="coerce")
    initial = float(pd.to_numeric(data.get("initial_cash", pd.Series([net.iloc[0]])), errors="coerce").dropna().iloc[0])
    data = data.copy()
    data["net_value_ratio"] = net / max(initial, 1e-12)
    data["drawdown"] = data.get("drawdown", data["net_value_ratio"] / data["net_value_ratio"].cummax() - 1.0)
    data["daily_return"] = pd.to_numeric(data["daily_return"], errors="coerce").fillna(0.0)
    data["rolling_sharpe_20"] = (
        data["daily_return"].rolling(20, min_periods=5).mean()
        / data["daily_return"].rolling(20, min_periods=5).std().replace(0.0, np.nan)
        * np.sqrt(252)
    )
    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
    axes[0].plot(data["date"], data["net_value_ratio"], linewidth=1.4)
    axes[0].set_ylabel("Net value")
    axes[0].grid(alpha=0.25)
    axes[1].fill_between(data["date"], data["drawdown"], 0.0, alpha=0.35)
    axes[1].set_ylabel("Drawdown")
    axes[1].grid(alpha=0.25)
    axes[2].bar(data["date"], data["daily_return"], width=1.0)
    axes[2].set_ylabel("Daily return")
    axes[2].grid(alpha=0.25)
    axes[3].plot(data["date"], data["rolling_sharpe_20"], linewidth=1.2)
    axes[3].set_ylabel("20D Sharpe")
    axes[3].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_monthly_heatmap(plt, data, output_path):
    monthly = data.set_index("date")["daily_return"].resample("ME").apply(lambda s: (1.0 + s).prod() - 1.0)
    table = monthly.to_frame("monthly_return")
    table["year"] = table.index.year
    table["month"] = table.index.month
    matrix = table.pivot(index="year", columns="month", values="monthly_return")
    fig, axis = plt.subplots(figsize=(12, max(3, len(matrix) * 0.6)))
    image = axis.imshow(matrix.fillna(0.0), aspect="auto", cmap="RdYlGn")
    axis.set_xticks(range(12))
    axis.set_xticklabels([str(i) for i in range(1, 13)])
    axis.set_yticks(range(len(matrix.index)))
    axis.set_yticklabels(matrix.index.astype(str))
    axis.set_xlabel("Month")
    axis.set_ylabel("Year")
    axis.set_title("Monthly return heatmap")
    fig.colorbar(image, ax=axis, fraction=0.025)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return monthly


def _plot_kelly_distribution(plt, selection, output_path):
    score_col = next((col for col in ["kelly_score", "target_weight", "score"] if col in selection.columns), None)
    if score_col is None:
        return False
    values = pd.to_numeric(selection[score_col], errors="coerce").dropna()
    if values.empty:
        return False
    fig, axis = plt.subplots(figsize=(10, 5))
    axis.hist(values, bins=30, alpha=0.85)
    axis.set_title(f"{score_col} distribution")
    axis.set_xlabel(score_col)
    axis.set_ylabel("Count")
    axis.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return True


def _write_monthly_summary(monthly, output_path):
    if monthly.empty:
        text = "No monthly return data available.\n"
    else:
        best = monthly.idxmax()
        worst = monthly.idxmin()
        text = (
            f"Positive months: {(monthly > 0).sum()}/{len(monthly)}.\n"
            f"Best month: {best.date()} return {monthly.loc[best]:.2%}.\n"
            f"Worst month: {worst.date()} return {monthly.loc[worst]:.2%}.\n"
        )
    Path(output_path).write_text(text, encoding="utf-8")


def _write_kelly_summary(selection, output_path):
    score_col = next((col for col in ["kelly_score", "target_weight", "score"] if col in selection.columns), None)
    if score_col is None:
        text = "No Kelly-like score column available.\n"
    else:
        values = pd.to_numeric(selection[score_col], errors="coerce").dropna()
        text = (
            f"{score_col} count: {len(values)}.\n"
            f"Mean: {values.mean():.4f}; median: {values.median():.4f}; "
            f"p90: {values.quantile(0.90):.4f}; max: {values.max():.4f}.\n"
        )
    Path(output_path).write_text(text, encoding="utf-8")
