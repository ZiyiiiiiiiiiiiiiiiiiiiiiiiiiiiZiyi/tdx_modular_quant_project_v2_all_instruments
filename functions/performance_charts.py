"""Additional performance charts and heatmap summaries."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from functions.data_integrity import research_watermark


def save_performance_diagnostics(
    *,
    daily_result: pd.DataFrame,
    strategy_name: str,
    output_dir,
    selection: pd.DataFrame | None = None,
    feature_data: pd.DataFrame | None = None,
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
        annual_chart_path = output / f"annual_return_distribution_{strategy_name}.png"
        annual_summary_path = output / f"annual_return_distribution_{strategy_name}.txt"
        annual = _plot_annual_return_distribution(plt, data, annual_chart_path)
        _write_annual_summary(annual, annual_summary_path)
        saved["annual_return_distribution"] = annual_chart_path
        saved["annual_return_distribution_summary"] = annual_summary_path
        accuracy_chart_path = output / f"accuracy_analysis_{strategy_name}.png"
        accuracy_summary_path = output / f"accuracy_analysis_{strategy_name}.txt"
        accuracy_stats = _plot_accuracy_analysis(plt, data, accuracy_chart_path)
        _write_accuracy_summary(accuracy_stats, accuracy_summary_path)
        saved["accuracy_analysis"] = accuracy_chart_path
        saved["accuracy_analysis_summary"] = accuracy_summary_path
    if selection is not None and not selection.empty:
        kelly_path = output / f"kelly_distribution_{strategy_name}.png"
        summary_path = output / f"kelly_distribution_{strategy_name}.txt"
        if _plot_kelly_distribution(plt, selection, kelly_path):
            _write_kelly_summary(selection, summary_path)
            saved["kelly_distribution"] = kelly_path
            saved["kelly_distribution_summary"] = summary_path
        if feature_data is not None and not feature_data.empty:
            alpha_decay = _build_alpha_decay_table(selection, feature_data)
            alpha_chart_path = output / f"alpha_decay_curve_{strategy_name}.png"
            alpha_summary_path = output / f"alpha_decay_curve_{strategy_name}.txt"
            if _plot_alpha_decay_curve(plt, alpha_decay, alpha_chart_path):
                _write_alpha_decay_summary(alpha_decay, alpha_summary_path)
                saved["alpha_decay_curve"] = alpha_chart_path
                saved["alpha_decay_curve_summary"] = alpha_summary_path
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

    # Compute Calmar, Sortino, max drawdown period
    total_return = float(data["net_value_ratio"].iloc[-1] - 1.0) if len(data) > 0 else 0.0
    n_days = len(data)
    annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1
    max_dd = float(data["drawdown"].min()) if len(data) > 0 else 0.0
    calmar = annual_return / abs(max_dd) if max_dd != 0 else float("nan")
    downside = data.loc[data["daily_return"] < 0, "daily_return"]
    downside_vol = float(downside.std() * np.sqrt(252)) if len(downside) > 0 else float("nan")
    sortino = (annual_return - 0.0) / downside_vol if downside_vol and downside_vol > 0 else float("nan")

    # Max drawdown start/end dates
    dd_series = data["drawdown"]
    if len(dd_series) > 0:
        max_dd_idx = dd_series.idxmin()
        max_dd_date = data.loc[max_dd_idx, "date"] if max_dd_idx in data.index else None
        # Find peak before max drawdown
        peak_mask = dd_series[:max_dd_idx + 1] == 0
        if peak_mask.any():
            peak_idx = peak_mask[peak_mask].index[-1]
            dd_start = data.loc[peak_idx, "date"]
        else:
            dd_start = data["date"].iloc[0]
        # Find recovery after max drawdown
        recovery_mask = dd_series[max_dd_idx:] == 0
        if recovery_mask.any():
            recovery_idx = recovery_mask[recovery_mask].index[0]
            dd_end = data.loc[recovery_idx, "date"]
        else:
            dd_end = data["date"].iloc[-1]
        dd_period_str = f"DD period: {dd_start.strftime('%Y-%m-%d') if hasattr(dd_start, 'strftime') else dd_start} -> {dd_end.strftime('%Y-%m-%d') if hasattr(dd_end, 'strftime') else dd_end}"
    else:
        max_dd_date = None
        dd_period_str = ""

    fig, axes = plt.subplots(4, 1, figsize=(14, 13), sharex=True)
    _apply_watermark(fig)
    axes[0].plot(data["date"], data["net_value_ratio"], linewidth=1.4)
    axes[0].set_ylabel("Net value")
    title = (
        f"Return {total_return:.2%} | Sharpe {data['rolling_sharpe_20'].mean():.3f} | "
        f"Calmar {calmar:.3f} | Sortino {sortino:.3f} | Max DD {max_dd:.2%}"
    )
    if dd_period_str:
        title += f"\n{dd_period_str}"
    axes[0].set_title(title, fontsize=10)
    axes[0].grid(alpha=0.25)
    # Mark max drawdown point
    if max_dd_date is not None:
        axes[0].axvline(max_dd_date, color="red", linestyle="--", alpha=0.5, linewidth=0.8)

    axes[1].fill_between(data["date"], data["drawdown"], 0.0, alpha=0.35)
    axes[1].plot(data["date"], data["drawdown"], linewidth=1.0)
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
    _apply_watermark(fig)
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


def _plot_annual_return_distribution(plt, data, output_path):
    annual = data.set_index("date")["daily_return"].resample("YE").apply(lambda s: (1.0 + s).prod() - 1.0)
    annual.index = annual.index.year
    fig, axis = plt.subplots(figsize=(10, 5))
    _apply_watermark(fig)
    if annual.empty:
        axis.text(0.5, 0.5, "No annual return data", ha="center", va="center")
        axis.set_axis_off()
    else:
        colors = ["#2e8b57" if value >= 0 else "#b22222" for value in annual]
        axis.bar(annual.index.astype(str), annual.values, color=colors, alpha=0.85)
        axis.axhline(0.0, color="black", linewidth=0.8, alpha=0.5)
        axis.set_ylabel("Annual return")
        axis.set_xlabel("Year")
        axis.set_title("Annual return distribution")
        axis.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return annual


def _plot_accuracy_analysis(plt, data, output_path):
    """Plot accuracy/win-rate analysis: rolling win rate, monthly hit rate, win/loss streaks."""
    daily_ret = pd.to_numeric(data["daily_return"], errors="coerce").fillna(0.0)
    dates = data["date"]

    # Rolling 20-day win rate
    rolling_win = (daily_ret > 0).rolling(20, min_periods=5).mean()

    # Monthly win rate
    monthly_data = data.set_index("date")[["daily_return"]].copy()
    monthly_data["is_win"] = monthly_data["daily_return"] > 0
    monthly_win_rate = monthly_data["is_win"].resample("ME").mean()

    # Win/loss streak distribution
    is_win = (daily_ret > 0).astype(int)
    streaks = []
    current_streak = 0
    current_sign = None
    for val in is_win:
        if val == 1:
            if current_sign == 1:
                current_streak += 1
            else:
                if current_streak > 0:
                    streaks.append((current_sign, current_streak))
                current_streak = 1
                current_sign = 1
        else:
            if current_sign == 0:
                current_streak += 1
            else:
                if current_streak > 0:
                    streaks.append((current_sign, current_streak))
                current_streak = 1
                current_sign = 0
    if current_streak > 0:
        streaks.append((current_sign, current_streak))

    win_streaks = [s[1] for s in streaks if s[0] == 1]
    loss_streaks = [s[1] for s in streaks if s[0] == 0]

    # Benchmark hit rate (excess return > 0)
    has_benchmark = "excess_daily_return" in data.columns
    if has_benchmark:
        excess_ret = pd.to_numeric(data["excess_daily_return"], errors="coerce").fillna(0.0)
        benchmark_hit = (excess_ret > 0).rolling(20, min_periods=5).mean()

    # Plot
    n_plots = 4 if has_benchmark else 3
    fig, axes = plt.subplots(n_plots, 1, figsize=(14, 3.5 * n_plots), sharex=True)
    _apply_watermark(fig)

    # 1. Rolling 20-day win rate
    axes[0].plot(dates, rolling_win, linewidth=1.2, color="steelblue")
    axes[0].axhline(0.5, color="red", linestyle="--", alpha=0.6, label="50% baseline")
    axes[0].fill_between(dates, 0.5, rolling_win, where=rolling_win > 0.5, alpha=0.2, color="green")
    axes[0].fill_between(dates, 0.5, rolling_win, where=rolling_win < 0.5, alpha=0.2, color="red")
    axes[0].set_ylabel("Win rate")
    axes[0].set_title("Rolling 20-day win rate")
    axes[0].set_ylim(0, 1)
    axes[0].legend(loc="upper right", fontsize=8)
    axes[0].grid(alpha=0.25)

    # 2. Monthly win rate
    if not monthly_win_rate.empty:
        colors = ["green" if v > 0.5 else "red" for v in monthly_win_rate.values]
        axes[1].bar(monthly_win_rate.index, monthly_win_rate.values, width=20, color=colors, alpha=0.7)
    axes[1].axhline(0.5, color="red", linestyle="--", alpha=0.6)
    axes[1].set_ylabel("Win rate")
    axes[1].set_title("Monthly win rate")
    axes[1].set_ylim(0, 1)
    axes[1].grid(alpha=0.25)

    # 3. Win/loss streak histogram
    if win_streaks or loss_streaks:
        max_streak = max(max(win_streaks, default=0), max(loss_streaks, default=0))
        bins = range(1, min(max_streak + 2, 30))
        axes[2].hist(win_streaks, bins=bins, alpha=0.6, color="green", label=f"Win streaks (n={len(win_streaks)})")
        axes[2].hist(loss_streaks, bins=bins, alpha=0.6, color="red", label=f"Loss streaks (n={len(loss_streaks)})")
    axes[2].set_xlabel("Streak length (days)")
    axes[2].set_ylabel("Frequency")
    axes[2].set_title("Win/loss streak distribution")
    axes[2].legend(loc="upper right", fontsize=8)
    axes[2].grid(alpha=0.25)

    # 4. Benchmark hit rate
    if has_benchmark:
        axes[3].plot(dates, benchmark_hit, linewidth=1.2, color="darkorange")
        axes[3].axhline(0.5, color="red", linestyle="--", alpha=0.6, label="50% baseline")
        axes[3].fill_between(dates, 0.5, benchmark_hit, where=benchmark_hit > 0.5, alpha=0.2, color="green")
        axes[3].fill_between(dates, 0.5, benchmark_hit, where=benchmark_hit < 0.5, alpha=0.2, color="red")
        axes[3].set_ylabel("Hit rate")
        axes[3].set_title("Rolling 20-day benchmark hit rate (excess return > 0)")
        axes[3].set_ylim(0, 1)
        axes[3].legend(loc="upper right", fontsize=8)
        axes[3].grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)

    # Compute summary stats
    overall_win_rate = float((daily_ret > 0).mean()) if len(daily_ret) > 0 else 0.0
    monthly_wr_values = monthly_win_rate.dropna()
    avg_monthly_win_rate = float(monthly_wr_values.mean()) if len(monthly_wr_values) > 0 else 0.0
    best_month_wr = float(monthly_wr_values.max()) if len(monthly_wr_values) > 0 else 0.0
    worst_month_wr = float(monthly_wr_values.min()) if len(monthly_wr_values) > 0 else 0.0
    avg_win_streak = float(np.mean(win_streaks)) if win_streaks else 0.0
    max_win_streak = int(max(win_streaks)) if win_streaks else 0
    avg_loss_streak = float(np.mean(loss_streaks)) if loss_streaks else 0.0
    max_loss_streak = int(max(loss_streaks)) if loss_streaks else 0

    benchmark_hit_rate = float((excess_ret > 0).mean()) if has_benchmark and len(excess_ret) > 0 else None

    stats = {
        "overall_win_rate": overall_win_rate,
        "avg_monthly_win_rate": avg_monthly_win_rate,
        "best_month_win_rate": best_month_wr,
        "worst_month_win_rate": worst_month_wr,
        "avg_win_streak_days": avg_win_streak,
        "max_win_streak_days": max_win_streak,
        "avg_loss_streak_days": avg_loss_streak,
        "max_loss_streak_days": max_loss_streak,
        "total_win_streaks": len(win_streaks),
        "total_loss_streaks": len(loss_streaks),
        "benchmark_hit_rate": benchmark_hit_rate,
    }
    return stats


def _write_accuracy_summary(stats, output_path):
    lines = [
        "Accuracy Analysis Summary",
        "=" * 40,
        f"Overall daily win rate: {stats['overall_win_rate']:.2%}",
        f"Average monthly win rate: {stats['avg_monthly_win_rate']:.2%}",
        f"Best month win rate: {stats['best_month_win_rate']:.2%}",
        f"Worst month win rate: {stats['worst_month_win_rate']:.2%}",
        "",
        "Win/Loss Streaks:",
        f"  Average win streak: {stats['avg_win_streak_days']:.1f} days",
        f"  Max win streak: {stats['max_win_streak_days']} days",
        f"  Average loss streak: {stats['avg_loss_streak_days']:.1f} days",
        f"  Max loss streak: {stats['max_loss_streak_days']} days",
        f"  Total win streaks: {stats['total_win_streaks']}",
        f"  Total loss streaks: {stats['total_loss_streaks']}",
    ]
    if stats["benchmark_hit_rate"] is not None:
        lines.extend([
            "",
            f"Benchmark hit rate (excess > 0): {stats['benchmark_hit_rate']:.2%}",
        ])
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")


def _plot_kelly_distribution(plt, selection, output_path):
    score_col = next((col for col in ["kelly_score", "target_weight", "score"] if col in selection.columns), None)
    if score_col is None:
        return False
    values = pd.to_numeric(selection[score_col], errors="coerce").dropna()
    if values.empty:
        return False
    fig, axis = plt.subplots(figsize=(10, 5))
    _apply_watermark(fig)
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


def _write_annual_summary(annual, output_path):
    if annual.empty:
        text = "No annual return data available.\n"
    else:
        best_year = int(annual.idxmax())
        worst_year = int(annual.idxmin())
        text = (
            f"Positive years: {(annual > 0).sum()}/{len(annual)}.\n"
            f"Best year: {best_year} return {annual.loc[best_year]:.2%}.\n"
            f"Worst year: {worst_year} return {annual.loc[worst_year]:.2%}.\n"
            f"Median annual return: {annual.median():.2%}.\n"
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


def _build_alpha_decay_table(selection, feature_data):
    feature_cols = [col for col in feature_data.columns if str(col).startswith("future_ret_")]
    if not feature_cols:
        return pd.DataFrame(columns=["horizon", "mean_forward_return", "median_forward_return", "sample_count"])

    subset = selection.copy()
    merge_date_col = "rebalance_date" if "rebalance_date" in subset.columns else "date"
    if merge_date_col not in subset.columns or "symbol" not in subset.columns:
        return pd.DataFrame(columns=["horizon", "mean_forward_return", "median_forward_return", "sample_count"])
    subset["date"] = pd.to_datetime(subset[merge_date_col], errors="coerce")
    subset["symbol"] = subset["symbol"].astype(str)

    feature_subset = feature_data.loc[:, ["date", "symbol", *feature_cols]].copy()
    feature_subset["date"] = pd.to_datetime(feature_subset["date"], errors="coerce")
    feature_subset["symbol"] = feature_subset["symbol"].astype(str)

    merged = subset[["date", "symbol"]].merge(feature_subset, on=["date", "symbol"], how="left")
    rows = []
    for column in sorted(feature_cols, key=_future_return_horizon):
        horizon = _future_return_horizon(column)
        values = pd.to_numeric(merged[column], errors="coerce").dropna()
        rows.append(
            {
                "horizon": horizon,
                "mean_forward_return": float(values.mean()) if not values.empty else np.nan,
                "median_forward_return": float(values.median()) if not values.empty else np.nan,
                "sample_count": int(values.shape[0]),
            }
        )
    return pd.DataFrame(rows)


def _plot_alpha_decay_curve(plt, alpha_decay, output_path):
    if alpha_decay is None or alpha_decay.empty:
        return False
    usable = alpha_decay.dropna(subset=["horizon", "mean_forward_return"])
    if usable.empty:
        return False
    fig, axis = plt.subplots(figsize=(10, 5))
    _apply_watermark(fig)
    axis.plot(
        usable["horizon"],
        usable["mean_forward_return"],
        marker="o",
        linewidth=1.5,
        label="Mean forward return",
    )
    axis.plot(
        usable["horizon"],
        usable["median_forward_return"],
        marker="s",
        linewidth=1.2,
        alpha=0.8,
        label="Median forward return",
    )
    axis.axhline(0.0, color="black", linewidth=0.8, alpha=0.5)
    axis.set_xlabel("Forward horizon (days)")
    axis.set_ylabel("Forward return")
    axis.set_title("Alpha decay / signal horizon summary")
    axis.grid(alpha=0.25)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return True


def _write_alpha_decay_summary(alpha_decay, output_path):
    if alpha_decay is None or alpha_decay.empty:
        text = "No alpha decay data available.\n"
    else:
        usable = alpha_decay.dropna(subset=["horizon", "mean_forward_return"])
        if usable.empty:
            text = "No alpha decay data available.\n"
        else:
            peak = usable.loc[usable["mean_forward_return"].idxmax()]
            trough = usable.loc[usable["mean_forward_return"].idxmin()]
            text = (
                f"Peak mean forward return horizon: {int(peak['horizon'])} days, {float(peak['mean_forward_return']):.2%}.\n"
                f"Weakest mean forward return horizon: {int(trough['horizon'])} days, {float(trough['mean_forward_return']):.2%}.\n"
                f"Coverage by horizon: "
                + ", ".join(
                    f"{int(row.horizon)}d={int(row.sample_count)}"
                    for row in usable.itertuples(index=False)
                )
                + ".\n"
            )
    Path(output_path).write_text(text, encoding="utf-8")


def _future_return_horizon(column_name):
    suffix = str(column_name).split("future_ret_", 1)[-1]
    try:
        return int(suffix)
    except ValueError:
        return 10 ** 9


def _apply_watermark(fig):
    watermark = research_watermark()
    if watermark:
        fig.text(
            0.5,
            0.5,
            "RESEARCH ONLY - UNVERIFIED DATA",
            ha="center",
            va="center",
            rotation=24,
            fontsize=18,
            color="red",
            alpha=0.18,
        )
