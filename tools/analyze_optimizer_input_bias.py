"""Audit notional and ranking bias on the proposals actually seen by SCAP.

This tool is diagnostic-only.  It reads the append-only proposal ledger and
never reconstructs optimizer selection from pre-optimizer candidate flags.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


NUMERIC_COLUMNS = [
    "robust_net_profit_amount",
    "market_notional_amount",
    "unit_capital_robust_return",
    "primary_rank",
    "primary_score",
    "expected_net_profit_amount",
]


def build_audit(path: Path, start_date: str, end_date: str) -> dict[str, object]:
    data = pd.read_csv(path, low_memory=False)
    data["decision_date"] = pd.to_datetime(data["decision_date"], errors="coerce")
    mask = (
        data["action_type"].astype(str).eq("new_entry")
        & data["decision_date"].between(start_date, end_date)
    )
    proposals = data.loc[mask].copy()
    for column in NUMERIC_COLUMNS:
        proposals[column] = pd.to_numeric(proposals[column], errors="coerce")
    proposals["selected"] = (
        proposals["selected_by_plan"].astype(str).str.lower().eq("true")
    )

    correlations = (
        proposals[NUMERIC_COLUMNS]
        .corr(method="spearman")["robust_net_profit_amount"]
        .dropna()
        .to_dict()
    )
    medians = proposals.groupby("selected", dropna=False)[NUMERIC_COLUMNS].median()
    thesis_counts = pd.crosstab(proposals["thesis"], proposals["selected"])
    monthly_counts = proposals.groupby(
        proposals["decision_date"].dt.to_period("M").astype(str)
    ).size()
    return {
        "source_ledger": str(path),
        "start_date": start_date,
        "end_date": end_date,
        "proposal_rows": int(len(proposals)),
        "decision_dates": int(proposals["decision_date"].nunique()),
        "selected_rows": int(proposals["selected"].sum()),
        "spearman_vs_robust_profit": {
            key: float(value) for key, value in correlations.items()
        },
        "median_by_selected": {
            str(index): {
                key: (None if pd.isna(value) else float(value))
                for key, value in row.items()
            }
            for index, row in medians.iterrows()
        },
        "thesis_counts": {
            str(index): {str(key): int(value) for key, value in row.items()}
            for index, row in thesis_counts.iterrows()
        },
        "monthly_proposal_rows": {
            str(key): int(value) for key, value in monthly_counts.items()
        },
        "scope_note": (
            "actual append-only new_entry proposal ledger; selected_by_plan is "
            "the authoritative historical optimizer outcome"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_audit(args.ledger, args.start_date, args.end_date)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
