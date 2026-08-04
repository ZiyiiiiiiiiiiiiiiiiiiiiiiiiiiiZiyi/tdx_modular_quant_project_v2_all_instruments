"""Add capacity, lot, cost and cross-capital fill evidence to a capital matrix."""

from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(
        frame.get(column, pd.Series(np.nan, index=frame.index)), errors="coerce"
    )


def enrich(matrix_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    matrix = pd.read_csv(matrix_path, low_memory=False)
    enriched_rows: list[dict] = []
    fill_keys: dict[float, set[str]] = {}
    for row in matrix.to_dict("records"):
        output_dir = Path(str(row["output_dir"]))
        daily = pd.read_csv(output_dir / "governance_daily_result.csv", low_memory=False)
        execution = pd.read_csv(
            output_dir / "governance_execution_ledger.csv", low_memory=False
        )
        buys = execution[execution["side"].astype(str).eq("buy")].copy()
        initial_cash = float(row["initial_cash"])
        nav = _numeric(daily, "nominal_nav")
        lot = _numeric(daily, "capacity_median_one_lot_amount")
        commission = _numeric(buys, "commission_cost")
        trade_notional = _numeric(execution, "trade_notional")
        total_cost = _numeric(execution, "total_cost")
        holding_floor_violation = _numeric(daily, "holding_floor_violation_count")
        exposure_floor_violation = _numeric(daily, "exposure_floor_violation")
        cap_binding = _numeric(daily, "actual_exposure") >= (
            _numeric(daily, "hard_exposure_ceiling") - 1e-9
        )
        result = dict(row)
        result.update(
            {
                "terminal_profit_amount": initial_cash * float(row["total_return"]),
                "profit_per_10000_initial": 10_000.0 * float(row["total_return"]),
                "average_idle_cash_ratio": _numeric(daily, "idle_cash_ratio").mean(),
                "median_one_lot_to_nav_ratio": (lot / nav.replace(0.0, np.nan)).median(),
                "fixed_min_commission_buy_fill_share": (
                    np.isclose(commission, 5.0, atol=1e-8).mean()
                    if len(commission)
                    else np.nan
                ),
                "observed_commission_to_notional": (
                    _numeric(execution, "commission_cost").sum()
                    / max(trade_notional.sum(), 1e-12)
                ),
                "explicit_cost_to_initial_cash": total_cost.sum()
                / max(initial_cash, 1e-12),
                "gross_turnover_to_average_nav": trade_notional.sum()
                / max(nav.mean(), 1e-12),
                "holding_floor_violation_days": int((holding_floor_violation > 0).sum()),
                "exposure_floor_violation_days": int(
                    exposure_floor_violation.fillna(False).astype(bool).sum()
                ),
                "hard_exposure_cap_binding_days": int(cap_binding.fillna(False).sum()),
            }
        )
        enriched_rows.append(result)
        fill_keys[initial_cash] = set(
            buys["trade_date"].astype(str) + "|" + buys["symbol"].astype(str)
        )

    overlap_rows = []
    for left, right in combinations(sorted(fill_keys), 2):
        a, b = fill_keys[left], fill_keys[right]
        union = a | b
        overlap_rows.append(
            {
                "left_initial_cash": left,
                "right_initial_cash": right,
                "left_buy_keys": len(a),
                "right_buy_keys": len(b),
                "shared_buy_keys": len(a & b),
                "buy_key_jaccard": len(a & b) / len(union) if union else np.nan,
            }
        )
    return pd.DataFrame(enriched_rows), pd.DataFrame(overlap_rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlap-output", type=Path, required=True)
    args = parser.parse_args()
    enriched, overlap = enrich(args.matrix)
    enriched.to_csv(args.output, index=False, encoding="utf-8-sig")
    overlap.to_csv(args.overlap_output, index=False, encoding="utf-8-sig")
    print(enriched.to_string(index=False))
    print(overlap.to_string(index=False))


if __name__ == "__main__":
    main()
