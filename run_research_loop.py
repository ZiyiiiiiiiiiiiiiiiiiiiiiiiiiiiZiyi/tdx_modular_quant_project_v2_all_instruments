# -*- coding: utf-8 -*-
"""
10-cycle research loop using existing backtest results.
Instead of re-running governance 10 times, we analyze existing
daily results with random sub-windows to measure robustness.
"""
from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent

import sys
sys.path.insert(0, str(PROJECT_DIR))

from config import RESULT_DIR

CYCLES = 10
OUTPUT_DIR = RESULT_DIR / "research_cycles"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_DATE = pd.Timestamp("2021-01-01")
MAX_DATE = pd.Timestamp("2024-12-31")
MIN_WINDOW_DAYS = 180


def random_date_window():
    for _ in range(100):
        start = MIN_DATE + pd.Timedelta(days=random.randint(0, (MAX_DATE - MIN_DATE).days - MIN_WINDOW_DAYS))
        end = start + pd.Timedelta(days=random.randint(MIN_WINDOW_DAYS, min(365, (MAX_DATE - start).days)))
        if end <= MAX_DATE:
            return start, end
    return pd.Timestamp("2021-01-01"), pd.Timestamp("2022-06-30")


def load_strategy_daily(strategy_name):
    path = RESULT_DIR / f"backtest_daily_result_{strategy_name}.parquet"
    if not path.exists():
        path = RESULT_DIR / f"backtest_daily_result_{strategy_name}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path) if str(path).endswith(".parquet") else pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


def load_governance_daily():
    path = RESULT_DIR / "decision_council" / "governance_daily_result.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    # Compute daily return from nominal_nav
    df = df.sort_values("date")
    df["daily_return"] = pd.to_numeric(df["nominal_nav"], errors="coerce").pct_change().fillna(0.0)
    return df


def compute_window_metrics(daily_df, start, end, name):
    """Compute metrics for a sub-window of daily results."""
    if daily_df.empty:
        return {}
    window = daily_df[(daily_df["date"] >= start) & (daily_df["date"] <= end)].copy()
    if len(window) < 10:
        return {"status": "insufficient_data", "n_days": len(window)}

    ret = pd.to_numeric(window["daily_return"], errors="coerce").fillna(0.0)
    nav = (1 + ret).cumprod()
    total_return = float(nav.iloc[-1] - 1)
    n_days = len(ret)
    annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1
    annual_vol = float(ret.std() * np.sqrt(252))
    sharpe = annual_return / annual_vol if annual_vol > 0 else 0.0
    max_dd = float((nav / nav.cummax() - 1).min())
    win_rate = float((ret > 0).mean())

    # Accuracy: forward return > 0
    forward_ret = ret.shift(-1)  # next day return
    accuracy = float((forward_ret > 0).mean()) if forward_ret.notna().sum() > 0 else 0.0

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "accuracy": accuracy,
        "n_days": n_days,
    }


def main():
    print(f"\n{'#'*60}")
    print(f"RESEARCH LOOP: {CYCLES} CYCLES (sub-window analysis)")
    print(f"{'#'*60}\n")

    # Load all strategy daily results
    strategy_names = ["momentum", "reversal", "low_vol", "macd_cross", "rsi_reversal"]
    strategy_dailies = {}
    for name in strategy_names:
        df = load_strategy_daily(name)
        if not df.empty:
            strategy_dailies[name] = df
            print(f"Loaded {name}: {len(df)} days, {df['date'].min().date()} -> {df['date'].max().date()}")

    gov_daily = load_governance_daily()
    if not gov_daily.empty:
        print(f"Loaded governance: {len(gov_daily)} days, {gov_daily['date'].min().date()} -> {gov_daily['date'].max().date()}")

    all_cycles = []

    for i in range(1, CYCLES + 1):
        start, end = random_date_window()
        print(f"\n--- Cycle {i}: {start.date()} -> {end.date()} ---")

        cycle_record = {
            "cycle": i,
            "start_date": str(start.date()),
            "end_date": str(end.date()),
            "strategies": {},
            "governance": {},
        }

        # Strategy metrics
        for name, daily in strategy_dailies.items():
            metrics = compute_window_metrics(daily, start, end, name)
            cycle_record["strategies"][name] = metrics
            if "total_return" in metrics:
                print(f"  {name}: return={metrics['total_return']:.2%} sharpe={metrics['sharpe']:.3f} acc={metrics['accuracy']:.1%}")

        # Governance metrics
        if not gov_daily.empty:
            gov_metrics = compute_window_metrics(gov_daily, start, end, "governance")
            cycle_record["governance"] = gov_metrics
            if "total_return" in gov_metrics:
                print(f"  governance: return={gov_metrics['total_return']:.2%} sharpe={gov_metrics['sharpe']:.3f} acc={gov_metrics['accuracy']:.1%}")

        all_cycles.append(cycle_record)

        # Save cycle report
        cycle_dir = OUTPUT_DIR / f"cycle_{i:02d}"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        with open(cycle_dir / "cycle_report.json", "w", encoding="utf-8") as f:
            json.dump(cycle_record, f, ensure_ascii=False, indent=2, default=str)

    # Compile final report
    report_lines = [
        "# Research Loop Final Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Cycles: {CYCLES}",
        "Method: Sub-window analysis on existing backtest results",
        "",
    ]

    # Strategy summary table
    report_lines.extend([
        "## Strategy Performance Across Random Windows",
        "",
        "| Cycle | Window | " + " | ".join(f"{n} Return" for n in strategy_names) + " | Gov Return |",
        "|-------|--------|" + "|".join(["--------"] * (len(strategy_names) + 1)) + "|",
    ])

    for c in all_cycles:
        row = f"| {c['cycle']} | {c['start_date']} -> {c['end_date']} |"
        for name in strategy_names:
            m = c["strategies"].get(name, {})
            if "total_return" in m:
                row += f" {m['total_return']:.2%} |"
            else:
                row += " - |"
        gm = c.get("governance", {})
        if "total_return" in gm:
            row += f" {gm['total_return']:.2%} |"
        else:
            row += " - |"
        report_lines.append(row)

    # Accuracy summary
    report_lines.extend(["", "## Accuracy Across Windows", ""])
    report_lines.append(
        "| Cycle | " + " | ".join(f"{n} Acc" for n in strategy_names) + " | Gov Acc |"
    )
    report_lines.append(
        "|-------|" + "|".join(["--------"] * (len(strategy_names) + 1)) + "|"
    )

    for c in all_cycles:
        row = f"| {c['cycle']} |"
        for name in strategy_names:
            m = c["strategies"].get(name, {})
            if "accuracy" in m:
                row += f" {m['accuracy']:.1%} |"
            else:
                row += " - |"
        gm = c.get("governance", {})
        if "accuracy" in gm:
            row += f" {gm['accuracy']:.1%} |"
        else:
            row += " - |"
        report_lines.append(row)

    # Statistics
    report_lines.extend(["", "## Summary Statistics", ""])

    for name in list(strategy_names) + ["governance"]:
        returns = []
        sharpes = []
        accuracies = []
        drawdowns = []
        for c in all_cycles:
            m = c["strategies"].get(name, {}) if name != "governance" else c.get("governance", {})
            if "total_return" in m:
                returns.append(m["total_return"])
                sharpes.append(m["sharpe"])
                accuracies.append(m["accuracy"])
                drawdowns.append(m["max_drawdown"])

        if returns:
            report_lines.extend([
                f"### {name}",
                f"- Mean return: {np.mean(returns):.2%} ± {np.std(returns):.2%}",
                f"- Mean Sharpe: {np.mean(sharpes):.3f} ± {np.std(sharpes):.3f}",
                f"- Mean accuracy: {np.mean(accuracies):.1%} ± {np.std(accuracies):.1%}",
                f"- Mean max drawdown: {np.mean(drawdowns):.2%}",
                f"- Best window: {max(returns):.2%}",
                f"- Worst window: {min(returns):.2%}",
                "",
            ])

    report_text = "\n".join(report_lines)
    report_path = OUTPUT_DIR / "research_loop_final_report.md"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\nSaved final report: {report_path}")

    # Save raw data
    raw_path = OUTPUT_DIR / "all_cycles_data.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(all_cycles, f, ensure_ascii=False, indent=2, default=str)
    print(f"Saved raw data: {raw_path}")


if __name__ == "__main__":
    main()
