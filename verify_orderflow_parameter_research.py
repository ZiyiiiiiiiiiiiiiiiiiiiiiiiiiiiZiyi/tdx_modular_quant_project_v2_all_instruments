from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

from functions.decision_council.orderflow_parameter_research import run_orderflow_parameter_research
from functions.factors.orderflow_parameter_factors import append_parameterized_orderflow_factors


def main() -> None:
    dates = pd.bdate_range("2024-01-02", periods=55)
    symbols = [f"s{i:03d}" for i in range(40)]
    rows = []
    for symbol_index, symbol in enumerate(symbols):
        for day_index, date in enumerate(dates):
            close = 10.0 + symbol_index * 0.02 + day_index * 0.01
            rows.append({
                "date": date, "symbol": symbol, "open": close * 0.995,
                "high": close * 1.01, "low": close * 0.99, "close": close,
                "amount": 1_000_000.0 * (1.0 + (day_index % 7) * 0.03),
                "volume": 100_000.0 * (1.0 + (day_index % 5) * 0.02),
            })
    data = pd.DataFrame(rows)
    requested = {
        "cand_orderflow_amount_shock_w5_s1",
        "cand_orderflow_efficiency_w20_s3",
        "cand_price_volume_breakout_w20_s1",
    }
    result = append_parameterized_orderflow_factors(data, include_columns=requested)
    assert requested.issubset(result.columns)
    assert result["cand_orderflow_amount_shock_w5_s1"].notna().any()
    assert result["cand_orderflow_efficiency_w20_s3"].notna().any()
    assert len(result) == len(data)
    root = Path("reports/verify_orderflow_parameter_research")
    root.mkdir(parents=True, exist_ok=True)
    input_path = root / "synthetic_features.parquet"
    data.assign(
        instrument_type="stock",
        sector_parent=np.where(data["symbol"].str[-1].astype(int) % 2 == 0, "a", "b"),
        stabilized_float_cap=1_000_000_000.0,
    ).to_parquet(input_path, index=False)
    saved = run_orderflow_parameter_research(
        feature_path=input_path,
        output_root=root / "runs",
        start_date="2024-02-01",
        end_date="2024-03-15",
        max_days=12,
        max_variants=3,
        max_runtime_seconds=30,
        run_kind="test",
    )
    summary = pd.read_csv(saved["parameter_summary"])
    assert len(summary) == 12
    assert set(summary["horizon_days"]) == {3, 5, 10, 20}
    print("[PASS] parameterized orderflow research completes bounded end-to-end smoke")


if __name__ == "__main__":
    main()
