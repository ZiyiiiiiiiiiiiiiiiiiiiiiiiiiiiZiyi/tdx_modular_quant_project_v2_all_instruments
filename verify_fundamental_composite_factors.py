"""Verify fundamental composite factor generation."""
from __future__ import annotations

import pandas as pd

from functions.factors.cashflow_quality_factors import CASHFLOW_FACTOR_COLUMNS
from functions.factors.fundamental_composite_factors import FUNDAMENTAL_COMPOSITE_COLUMNS, append_fundamental_composite_factors
from functions.factors.growth_quality_factors import GROWTH_FACTOR_COLUMNS
from functions.factors.profitability_quality_factors import PROFITABILITY_FACTOR_COLUMNS


def main() -> int:
    dates = pd.bdate_range("2023-01-01", periods=320)
    rows = []
    for stock_code in ["sh600000", "sz000001"]:
        for i, date in enumerate(dates):
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": date,
                    "revenue": 100 + i * 0.5,
                    "net_profit": 10 + i * 0.08,
                    "deducted_net_profit": 9 + i * 0.07,
                    "operating_cashflow": 11 + i * 0.09,
                    "total_assets": 500 + i,
                    "total_equity": 250 + i * 0.4,
                    "total_liabilities": 250 + i * 0.6,
                    "market_cap": 1000 + i * 2,
                    "industry": "bank",
                    "gross_profit": 30 + i * 0.1,
                    "operating_profit": 15 + i * 0.08,
                    "capex": 2 + i * 0.01,
                }
            )
    out = append_fundamental_composite_factors(pd.DataFrame(rows))
    required = set(GROWTH_FACTOR_COLUMNS + PROFITABILITY_FACTOR_COLUMNS + CASHFLOW_FACTOR_COLUMNS + FUNDAMENTAL_COMPOSITE_COLUMNS)
    missing = sorted(required - set(out.columns))
    if missing:
        print(f"[FAIL] missing fundamental factors: {missing}")
        return 1
    print(f"[PASS] fundamental factors generated={len(required)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
