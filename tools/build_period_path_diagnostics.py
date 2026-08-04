"""Build monthly account/benchmark path evidence from one frozen run."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def build(run_dir: Path, start: str, end: str) -> pd.DataFrame:
    daily = pd.read_csv(run_dir / "governance_daily_result.csv", low_memory=False)
    benchmark = pd.read_csv(
        run_dir / "governance_performance_benchmark.csv", low_memory=False
    )
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
    benchmark["date"] = pd.to_datetime(benchmark["date"], errors="coerce")
    daily = daily.sort_values("date")
    daily["account_daily_return"] = pd.to_numeric(
        daily["nominal_nav"], errors="coerce"
    ).pct_change(fill_method=None)
    merged = daily.merge(
        benchmark[["date", "benchmark_daily_return"]], on="date", how="left"
    )
    window = merged[merged["date"].between(start, end)].copy()
    window["month"] = window["date"].dt.to_period("M").astype(str)

    def summarize(group: pd.DataFrame) -> pd.Series:
        account = pd.to_numeric(group["account_daily_return"], errors="coerce").fillna(0)
        bench = pd.to_numeric(group["benchmark_daily_return"], errors="coerce").fillna(0)
        return pd.Series(
            {
                "trading_days": int(group["date"].nunique()),
                "account_return": float((1.0 + account).prod() - 1.0),
                "benchmark_return": float((1.0 + bench).prod() - 1.0),
                "excess_return_arithmetic": float(
                    (1.0 + account).prod() - (1.0 + bench).prod()
                ),
                "average_exposure": pd.to_numeric(
                    group["actual_exposure"], errors="coerce"
                ).mean(),
                "average_holding_count": pd.to_numeric(
                    group["holding_count"], errors="coerce"
                ).mean(),
                "minimum_holding_count": pd.to_numeric(
                    group["holding_count"], errors="coerce"
                ).min(),
                "maximum_holding_count": pd.to_numeric(
                    group["holding_count"], errors="coerce"
                ).max(),
            }
        )

    rows = []
    for month, group in window.groupby("month", sort=True):
        rows.append({"month": month, **summarize(group).to_dict()})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.run_dir, args.start_date, args.end_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
