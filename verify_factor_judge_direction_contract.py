"""Verify that factor judge and trading use the same factor direction."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.factor_registry import build_factor_registry
from functions.decision_council.factor_validation import build_factor_research_reports
from functions.decision_council.factor_pool_contract import normalize_factor_module


def main() -> int:
    registry = build_factor_registry()
    for name in (
        "orderflow_efficiency",
        "orderflow_accumulation",
        "orderflow_close_drive",
        "price_volume_breakout",
        "turtle_breakout",
    ):
        assert registry[name]["direction"] == "lower_better", name
    assert normalize_factor_module("flow_close", factor_name="orderflow_amount_shock") == "orderflow"

    rows = []
    dates = pd.date_range("2024-01-01", periods=8, freq="D")
    for symbol_index in range(20):
        symbol = f"s{symbol_index:02d}"
        for day_index, date in enumerate(dates):
            # Lower raw values lead to higher subsequent returns.
            raw = float(symbol_index)
            rows.append({
                "date": date,
                "symbol": symbol,
                "close": 100.0 * (1.0 + (19 - symbol_index) * 0.001) ** day_index,
                "raw": raw,
            })
    data = pd.DataFrame(rows)
    reports = build_factor_research_reports(
        data,
        registry={
            "inverse_test": {
                "factor_name": "inverse_test",
                "raw_column": "raw",
                "module": "orderflow",
                "candidate_pool": "test",
                "direction": "lower_better",
                "min_coverage": 0.0,
                "min_abs_rank_ic": 0.0,
                "min_ic_ir": 0.0,
                "min_rank_ic_positive_ratio": 0.0,
                "min_top_bottom_spread_10d": -1.0,
                "min_sample_count": 1,
            }
        },
        horizons=(1,),
        emit_quantile_rows=False,
        cluster_max_factors=0,
    )
    validation = reports["governance_factor_validation_report"]
    assert float(validation.iloc[0]["rank_ic_mean"]) > 0.99
    print("[PASS] factor judge honors lower_better direction used by trading")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
