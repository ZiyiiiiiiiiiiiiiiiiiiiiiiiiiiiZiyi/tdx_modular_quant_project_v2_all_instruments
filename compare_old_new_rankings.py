# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import BACKTEST_SUMMARY_V2_CSV, STRATEGY_RANK_SHIFT_REPORT_CSV


REQUIRED_COMPARISON_COLUMNS = [
    "strategy",
    "old_total_return",
    "new_total_return",
    "old_sharpe",
    "new_sharpe",
    "old_rank",
    "new_rank",
    "rank_shift",
]


def build_rank_shift_report(old_summary_path, new_summary_path):
    old_df = pd.read_csv(old_summary_path).copy()
    new_df = pd.read_csv(new_summary_path).copy()

    old_df["old_rank"] = (
        pd.to_numeric(old_df["composite_score"], errors="coerce")
        .rank(method="first", ascending=False)
    )
    new_df["new_rank"] = (
        pd.to_numeric(new_df["composite_score"], errors="coerce")
        .rank(method="first", ascending=False)
    )

    merged = old_df[["strategy", "total_return", "sharpe", "old_rank"]].rename(
        columns={
            "total_return": "old_total_return",
            "sharpe": "old_sharpe",
        }
    ).merge(
        new_df[["strategy", "total_return", "sharpe", "new_rank"]].rename(
            columns={
                "total_return": "new_total_return",
                "sharpe": "new_sharpe",
            }
        ),
        on="strategy",
        how="outer",
    )

    merged["rank_shift"] = pd.to_numeric(merged["old_rank"], errors="coerce") - pd.to_numeric(
        merged["new_rank"],
        errors="coerce",
    )
    return merged[REQUIRED_COMPARISON_COLUMNS].copy()


def save_rank_shift_report(report_df, output_path=STRATEGY_RANK_SHIFT_REPORT_CSV):
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    report_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    return output_file


if __name__ == "__main__":
    old_path = Path("results") / "backtest_strategy_summary.csv"
    new_path = Path(BACKTEST_SUMMARY_V2_CSV)
    if not old_path.exists() or not new_path.exists():
        raise SystemExit("Comparison inputs are missing.")
    report = build_rank_shift_report(old_path, new_path)
    output = save_rank_shift_report(report)
    print(f"Saved rank shift report: {output}")
