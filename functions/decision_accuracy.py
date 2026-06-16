# -*- coding: utf-8 -*-
"""
Per-decision accuracy analysis for all strategies and governance.

For each strategy selection at rebalance date R:
- "correct" = selected stock's forward return > 0 over holding period
- accuracy = % of correct decisions per rebalance date

For governance trades:
- buy: correct if price goes up after purchase
- sell: correct if price goes down after sale
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config import FEATURE_DAILY_PARQUET, PROCESSED_DIR, RESULT_DIR, STRATEGY_FREQ_OVERRIDES


def analyze_strategy_decision_accuracy(
    strategy_name: str,
    selection_df: pd.DataFrame,
    feature_df: pd.DataFrame | None = None,
    freq: str = "ME",
) -> dict:
    """
    Compute per-rebalance-date accuracy for a strategy.

    Returns dict with:
        - per_date: DataFrame with rebalance_date, n_stocks, n_correct, accuracy
        - overall_accuracy: float
        - accuracy_timeline: DataFrame for plotting
    """
    if selection_df.empty:
        return {"per_date": pd.DataFrame(), "overall_accuracy": 0.0, "accuracy_timeline": pd.DataFrame()}

    if feature_df is None:
        feature_df = _load_feature_subset(strategy_name)

    # Determine forward return column based on frequency
    horizon = _freq_to_horizon(freq)
    ret_col = f"future_ret_{horizon}"
    if ret_col not in feature_df.columns:
        # Try available columns
        for h in [5, 10, 20]:
            if f"future_ret_{h}" in feature_df.columns:
                ret_col = f"future_ret_{h}"
                horizon = h
                break
        else:
            return {"per_date": pd.DataFrame(), "overall_accuracy": 0.0, "accuracy_timeline": pd.DataFrame()}

    # Merge selection with forward returns
    feature_returns = feature_df[["date", "symbol", ret_col]].copy()
    feature_returns["date"] = pd.to_datetime(feature_returns["date"])
    feature_returns = feature_returns.rename(columns={"date": "rebalance_date"})

    merged = selection_df.merge(
        feature_returns,
        on=["rebalance_date", "symbol"],
        how="left",
    )

    if merged.empty:
        return {"per_date": pd.DataFrame(), "overall_accuracy": 0.0, "accuracy_timeline": pd.DataFrame()}

    merged["forward_return"] = pd.to_numeric(merged[ret_col], errors="coerce")
    merged["is_correct"] = (merged["forward_return"] > 0).astype(int)

    # Per-date accuracy
    per_date = merged.groupby("rebalance_date").agg(
        n_stocks=("symbol", "count"),
        n_correct=("is_correct", "sum"),
        avg_forward_return=("forward_return", "mean"),
        median_forward_return=("forward_return", "median"),
    ).reset_index()
    per_date["accuracy"] = per_date["n_correct"] / per_date["n_stocks"]
    per_date = per_date.sort_values("rebalance_date")

    overall_accuracy = float(merged["is_correct"].mean()) if len(merged) > 0 else 0.0

    return {
        "per_date": per_date,
        "overall_accuracy": overall_accuracy,
        "accuracy_timeline": per_date[["rebalance_date", "accuracy", "n_stocks"]].copy(),
        "horizon": horizon,
        "total_decisions": len(merged),
        "correct_decisions": int(merged["is_correct"].sum()),
    }


def analyze_governance_decision_accuracy(
    execution_ledger: pd.DataFrame,
    feature_df: pd.DataFrame | None = None,
    horizon_days: int = 5,
) -> dict:
    """
    Compute per-trade accuracy for governance decisions.

    For buy trades: correct if price goes up over next N days
    For sell trades: correct if price goes down over next N days
    """
    if execution_ledger.empty:
        return {"per_date": pd.DataFrame(), "overall_accuracy": 0.0, "accuracy_timeline": pd.DataFrame()}

    if feature_df is None:
        feature_df = _load_governance_features()

    filled = execution_ledger[execution_ledger["execution_status"] == "filled"].copy()
    if filled.empty:
        return {"per_date": pd.DataFrame(), "overall_accuracy": 0.0, "accuracy_timeline": pd.DataFrame()}

    # Get forward returns from feature data
    ret_col = f"future_ret_{horizon_days}"
    if ret_col not in feature_df.columns:
        for h in [5, 10, 20]:
            if f"future_ret_{h}" in feature_df.columns:
                ret_col = f"future_ret_{h}"
                horizon_days = h
                break
        else:
            return {"per_date": pd.DataFrame(), "overall_accuracy": 0.0, "accuracy_timeline": pd.DataFrame()}

    feature_returns = feature_df[["date", "symbol", ret_col]].copy()
    feature_returns["date"] = pd.to_datetime(feature_returns["date"])
    feature_returns = feature_returns.rename(columns={"date": "trade_date"})

    filled["trade_date"] = pd.to_datetime(filled["trade_date"])
    merged = filled.merge(
        feature_returns,
        on=["trade_date", "symbol"],
        how="left",
    )
    merged["forward_return"] = pd.to_numeric(merged[ret_col], errors="coerce")

    # Buy: correct if forward return > 0
    # Sell: correct if forward return < 0
    merged["is_correct"] = np.where(
        merged["side"] == "buy",
        (merged["forward_return"] > 0).astype(int),
        (merged["forward_return"] < 0).astype(int),
    )

    # Per-date accuracy
    per_date = merged.groupby("trade_date").agg(
        n_trades=("symbol", "count"),
        n_buy=("side", lambda x: (x == "buy").sum()),
        n_sell=("side", lambda x: (x == "sell").sum()),
        n_correct=("is_correct", "sum"),
        avg_forward_return=("forward_return", "mean"),
    ).reset_index()
    per_date["accuracy"] = per_date["n_correct"] / per_date["n_trades"]
    per_date = per_date.sort_values("trade_date")

    overall_accuracy = float(merged["is_correct"].mean()) if len(merged) > 0 else 0.0

    # Buy accuracy and sell accuracy separately
    buy_merged = merged[merged["side"] == "buy"]
    sell_merged = merged[merged["side"] == "sell"]
    buy_accuracy = float(buy_merged["is_correct"].mean()) if len(buy_merged) > 0 else 0.0
    sell_accuracy = float(sell_merged["is_correct"].mean()) if len(sell_merged) > 0 else 0.0

    return {
        "per_date": per_date,
        "overall_accuracy": overall_accuracy,
        "buy_accuracy": buy_accuracy,
        "sell_accuracy": sell_accuracy,
        "accuracy_timeline": per_date[["trade_date", "accuracy", "n_trades"]].copy(),
        "horizon": horizon_days,
        "total_decisions": len(merged),
        "correct_decisions": int(merged["is_correct"].sum()),
        "total_buys": len(buy_merged),
        "total_sells": len(sell_merged),
    }


def build_all_strategies_accuracy_report(
    strategy_names: list[str] | None = None,
    freq_overrides: dict | None = None,
) -> dict:
    """
    Build accuracy report for all strategies and governance.
    """
    if strategy_names is None:
        strategy_names = sorted(
            p.stem for p in PROCESSED_DIR.glob("*.parquet")
            if p.name not in {"tdx_daily_raw.parquet", "tdx_daily_clean.parquet", "tdx_daily_features.parquet", "strategy_selection.parquet"}
        )
    if freq_overrides is None:
        freq_overrides = STRATEGY_FREQ_OVERRIDES

    results = {}
    feature_cache = {}

    for name in strategy_names:
        sel_path = PROCESSED_DIR / f"{name}.parquet"
        if not sel_path.exists():
            continue
        sel = pd.read_parquet(sel_path)
        if sel.empty:
            continue

        freq = freq_overrides.get(name, "ME")
        result = analyze_strategy_decision_accuracy(name, sel, freq=freq)
        results[name] = result

    # Governance
    gov_exec_path = RESULT_DIR / "decision_council" / "governance_execution_ledger.csv"
    if gov_exec_path.exists():
        gov_exec = pd.read_csv(gov_exec_path)
        gov_result = analyze_governance_decision_accuracy(gov_exec, horizon_days=5)
        results["governance"] = gov_result

    return results


def plot_all_accuracy(results: dict, output_dir=None):
    """Plot accuracy charts for all strategies."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("Skip accuracy plot: matplotlib not installed.")
        return

    if output_dir is None:
        output_dir = RESULT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Filter to strategies with data
    valid = {k: v for k, v in results.items() if not v.get("accuracy_timeline", pd.DataFrame()).empty}
    if not valid:
        print("No accuracy data to plot.")
        return

    # 1. Overall accuracy comparison bar chart
    fig, axis = plt.subplots(figsize=(max(8, len(valid) * 1.2), 5))
    names = sorted(valid.keys())
    accuracies = [valid[n]["overall_accuracy"] for n in names]
    colors = ["green" if a > 0.5 else "red" for a in accuracies]
    bars = axis.bar(names, accuracies, color=colors, alpha=0.7)
    axis.axhline(0.5, color="black", linestyle="--", alpha=0.5, label="50% baseline")
    axis.set_ylabel("Accuracy")
    axis.set_title("Per-Decision Accuracy by Strategy")
    axis.set_ylim(0, 1)
    for bar, acc in zip(bars, accuracies):
        axis.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01, f"{acc:.1%}", ha="center", fontsize=9)
    axis.legend()
    axis.grid(axis="y", alpha=0.25)
    plt.xticks(rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(output_dir / "accuracy_comparison_all_strategies.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    # 2. Accuracy timeline for each strategy
    n_strategies = len(valid)
    fig, axes = plt.subplots(n_strategies, 1, figsize=(14, 3.5 * n_strategies), sharex=False)
    if n_strategies == 1:
        axes = [axes]

    for idx, name in enumerate(sorted(valid.keys())):
        ax = axes[idx]
        timeline = valid[name]["accuracy_timeline"]
        if timeline.empty:
            continue

        date_col = "rebalance_date" if "rebalance_date" in timeline.columns else "trade_date"
        ax.plot(timeline[date_col], timeline["accuracy"], linewidth=1.2, marker="o", markersize=3)
        ax.axhline(0.5, color="red", linestyle="--", alpha=0.5)
        ax.fill_between(timeline[date_col], 0.5, timeline["accuracy"], where=timeline["accuracy"] > 0.5, alpha=0.2, color="green")
        ax.fill_between(timeline[date_col], 0.5, timeline["accuracy"], where=timeline["accuracy"] < 0.5, alpha=0.2, color="red")

        overall = valid[name]["overall_accuracy"]
        total = valid[name].get("total_decisions", 0)
        correct = valid[name].get("correct_decisions", 0)
        ax.set_ylabel("Accuracy")
        ax.set_title(f"{name} (overall: {overall:.1%}, {correct}/{total})")
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.25)

    fig.suptitle("Decision Accuracy Timeline (all strategies)", fontsize=14, y=1.01)
    fig.tight_layout()
    fig.savefig(output_dir / "accuracy_timeline_all_strategies.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved accuracy charts to {output_dir}")


def save_accuracy_summary_csv(results: dict, output_dir=None):
    """Save a summary CSV of all strategies' accuracy."""
    if output_dir is None:
        output_dir = RESULT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for name, result in sorted(results.items()):
        row = {
            "strategy": name,
            "overall_accuracy": result.get("overall_accuracy", 0.0),
            "total_decisions": result.get("total_decisions", 0),
            "correct_decisions": result.get("correct_decisions", 0),
            "horizon_days": result.get("horizon", 0),
        }
        if name == "governance":
            row["buy_accuracy"] = result.get("buy_accuracy", 0.0)
            row["sell_accuracy"] = result.get("sell_accuracy", 0.0)
            row["total_buys"] = result.get("total_buys", 0)
            row["total_sells"] = result.get("total_sells", 0)
        rows.append(row)

    df = pd.DataFrame(rows)
    output_path = output_dir / "decision_accuracy_summary.csv"
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Saved accuracy summary: {output_path}")
    return df


def accuracy_report_markdown(results: dict) -> str:
    """Generate markdown report of decision accuracy."""
    lines = [
        "# Decision Accuracy Report",
        "",
        "## Overall Accuracy by Strategy",
        "",
        "| Strategy | Accuracy | Correct/Total | Horizon |",
        "|----------|----------|---------------|---------|",
    ]

    for name, result in sorted(results.items()):
        acc = result.get("overall_accuracy", 0.0)
        total = result.get("total_decisions", 0)
        correct = result.get("correct_decisions", 0)
        horizon = result.get("horizon", 0)
        lines.append(f"| {name} | {acc:.2%} | {correct}/{total} | {horizon}d |")

    # Governance details
    if "governance" in results:
        gov = results["governance"]
        lines.extend([
            "",
            "## Governance Detail",
            "",
            f"- Buy accuracy: {gov.get('buy_accuracy', 0):.2%} ({gov.get('total_buys', 0)} trades)",
            f"- Sell accuracy: {gov.get('sell_accuracy', 0):.2%} ({gov.get('total_sells', 0)} trades)",
            f"- Overall: {gov.get('overall_accuracy', 0):.2%} ({gov.get('correct_decisions', 0)}/{gov.get('total_decisions', 0)})",
        ])

    # Per-strategy details
    lines.extend(["", "## Per-Rebalance-Date Accuracy", ""])
    for name, result in sorted(results.items()):
        per_date = result.get("per_date", pd.DataFrame())
        if per_date.empty:
            continue
        lines.append(f"### {name}")
        date_col = "rebalance_date" if "rebalance_date" in per_date.columns else "trade_date"
        for _, row in per_date.iterrows():
            lines.append(
                f"- {row[date_col].date() if hasattr(row[date_col], 'date') else row[date_col]}: "
                f"{row['accuracy']:.1%} ({int(row.get('n_correct', 0))}/{int(row.get('n_stocks', row.get('n_trades', 0)))})"
            )
        lines.append("")

    return "\n".join(lines)


def _freq_to_horizon(freq: str) -> int:
    """Convert rebalance frequency to forward return horizon."""
    freq = str(freq).upper()
    if freq in {"D", "DAILY"}:
        return 5
    elif freq.startswith("W"):
        return 5
    elif freq == "ME":
        return 20
    elif freq == "QE":
        return 60
    return 20


def _load_feature_subset(strategy_name: str) -> pd.DataFrame:
    """Load minimal feature data needed for accuracy analysis."""
    cols = ["date", "symbol", "future_ret_5", "future_ret_10", "future_ret_20"]
    try:
        import pyarrow.parquet as pq
        schema = pq.read_schema(FEATURE_DAILY_PARQUET)
        available = [c for c in cols if c in schema.names]
        return pd.read_parquet(FEATURE_DAILY_PARQUET, columns=available)
    except Exception:
        return pd.DataFrame()


def _load_governance_features() -> pd.DataFrame:
    """Load minimal feature data for governance accuracy analysis."""
    return _load_feature_subset("governance")
