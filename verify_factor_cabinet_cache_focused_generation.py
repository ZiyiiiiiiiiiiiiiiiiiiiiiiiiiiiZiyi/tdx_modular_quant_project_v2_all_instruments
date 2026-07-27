from __future__ import annotations

import numpy as np
import pandas as pd

from functions.factors.factor_candidate_pool import append_candidate_factors


def main() -> None:
    dates = pd.date_range("2024-01-01", periods=80, freq="B")
    frame = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": dates,
                    "symbol": symbol,
                    "open": 10.0 + offset + np.arange(len(dates)) * 0.01,
                    "high": 10.2 + offset + np.arange(len(dates)) * 0.01,
                    "low": 9.8 + offset + np.arange(len(dates)) * 0.01,
                    "close": 10.1 + offset + np.arange(len(dates)) * 0.01,
                    "amount": 1_000_000.0 + np.arange(len(dates)) * 100.0,
                    "volume": 100_000.0 + np.arange(len(dates)) * 10.0,
                    "ret_1": 0.001,
                    "stabilized_float_cap": 1e9 * (offset + 1.0),
                    "stabilized_total_cap": 1.5e9 * (offset + 1.0),
                }
            )
            for symbol, offset in (("sh600000", 0.0), ("sz000001", 1.0))
        ],
        ignore_index=True,
    )
    requested = {
        "cand_size_float_cap_neg",
        "cand_size_total_cap_neg",
        "cand_size_float_cap_rank_small",
        "cand_volatility_20_neg",
    }
    focused = append_candidate_factors(frame, include_columns=requested, include_ultra_grid=True)
    assert requested <= set(focused.columns)
    assert "cand_turnover_to_float_cap_20" not in focused.columns
    assert focused["cand_size_float_cap_neg"].notna().all()
    print("[PASS] cabinet cache computes only requested simple/grid/matrix factors")


if __name__ == "__main__":
    main()
