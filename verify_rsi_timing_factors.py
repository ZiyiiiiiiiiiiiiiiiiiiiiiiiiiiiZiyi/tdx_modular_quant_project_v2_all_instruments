"""Verify RSI timing factor generation."""
from __future__ import annotations

import pandas as pd

import math

from functions.factors.technical_timing_factors import append_rsi_timing_factors, rsi_timing_registry_rows


def main() -> int:
    dates = pd.bdate_range("2024-01-01", periods=320)
    rows = []
    for symbol, offset in [("sh600000", 0.0), ("sz000001", 0.1)]:
        for i, date in enumerate(dates):
            price = 10.0 + offset + 0.01 * i + 0.8 * math.sin(i / 7.0) + 0.3 * math.sin(i / 19.0)
            rows.append({"date": date, "symbol": symbol, "close_nominal": price})
    data = pd.DataFrame(rows)
    out = append_rsi_timing_factors(data)
    required = {row["raw_column"] for row in rsi_timing_registry_rows()}
    missing = sorted(required - set(out.columns))
    if missing:
        print(f"[FAIL] missing RSI timing columns: {missing}")
        return 1
    non_null = {column: int(out[column].notna().sum()) for column in required}
    if not any(count > 0 for count in non_null.values()):
        print(f"[FAIL] RSI timing columns are all empty: {non_null}")
        return 1
    print(f"[PASS] RSI timing factors generated: {non_null}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
