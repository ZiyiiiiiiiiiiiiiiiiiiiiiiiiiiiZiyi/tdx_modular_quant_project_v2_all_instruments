import time

import pandas as pd

from functions.data.pit_level2_store import pit_level2_store_status
from functions.factors.pit_factor_materialization import attach_pit_level2_factors


def main() -> int:
    status = pit_level2_store_status()
    if len(status) != 3 or not status["available"].all():
        print("[FAIL] three published PIT Level-2 research tables are not available")
        return 1
    if status["formal_eligible"].any():
        print("[FAIL] current-snapshot TDX tables must remain research-only")
        return 1
    feature_path = "data/processed/tdx_daily_features.parquet"
    data = pd.read_parquet(
        feature_path,
        columns=["date", "symbol", "close", "sector_parent", "instrument_type"],
        filters=[
            ("date", ">=", pd.Timestamp("2024-01-01")),
            ("date", "<=", pd.Timestamp("2024-06-30")),
            ("instrument_type", "==", "stock"),
        ],
    )
    symbols = set(sorted(
        symbol for symbol in data["symbol"].astype(str).unique()
        if symbol.startswith(("sh", "sz"))
    )[:20])
    data = data[data["symbol"].isin(symbols)].copy()
    requested = {
        "cand_fund_earnings_yield_ttm", "cand_fund_book_to_price",
        "cand_fund_fcf_yield", "cand_fund_roe_ttm_ind_neutral",
        "cand_event_earnings_forecast_positive",
    }
    started = time.monotonic()
    output = attach_pit_level2_factors(data, requested_columns=requested)
    elapsed = time.monotonic() - started
    fundamental = requested - {"cand_event_earnings_forecast_positive"}
    if any(output[column].notna().sum() == 0 for column in fundamental):
        print("[FAIL] real PIT financial factors have zero coverage")
        return 1
    if elapsed > 20.0:
        print(f"[FAIL] 20-symbol PIT smoke exceeded 20 seconds: {elapsed:.2f}")
        return 1
    print(f"[PASS] real PIT Level-2 20-symbol materialization rows={len(output)}, elapsed={elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
