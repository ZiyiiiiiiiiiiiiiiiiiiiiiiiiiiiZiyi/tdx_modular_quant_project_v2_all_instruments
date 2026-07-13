"""Verify alternative proxy factors do not require fabricated external data."""
from __future__ import annotations

import pandas as pd

from functions.factors.alternative_proxy_factors import ALTERNATIVE_PROXY_COLUMNS, append_alternative_proxy_factors


def main() -> int:
    dates = pd.bdate_range("2024-01-01", periods=80)
    rows = []
    for symbol in ["sh600000", "sz000001"]:
        for i, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close": 10 + i * 0.03,
                    "high": 10.2 + i * 0.03,
                    "low": 9.8 + i * 0.03,
                    "volume": 1000 + i * 10,
                    "amount": 10000 + i * 100,
                    "market_cap": 1_000_000,
                    "turnover_rate": 0.02 + i * 0.0001,
                    "industry": "bank",
                    "limit_up_flag": 1 if i % 20 == 0 else 0,
                    "announcement_density": i % 3,
                }
            )
    out = append_alternative_proxy_factors(pd.DataFrame(rows))
    missing = sorted(set(ALTERNATIVE_PROXY_COLUMNS) - set(out.columns))
    if missing:
        print(f"[FAIL] missing alternative proxy columns: {missing}")
        return 1
    print(f"[PASS] alternative proxy factors generated={len(ALTERNATIVE_PROXY_COLUMNS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
