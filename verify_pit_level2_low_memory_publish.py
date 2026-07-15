from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from functions.data.pit_level2_tdx_builder import publish_research_pit_level2_low_memory


def main() -> int:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        dates = pd.date_range("2024-01-02", periods=80, freq="B")
        source = pd.DataFrame([
            {
                "symbol": symbol, "date": date,
                "stabilized_total_cap": 1_000_000.0 + index,
                "stabilized_float_cap": 800_000.0 + index,
                "source_name": "smoke",
            }
            for symbol in ("sh600000", "sz000001", "sz000002")
            for index, date in enumerate(dates)
        ])
        source_path = root / "market_cap.parquet"
        source.to_parquet(source_path, index=False)
        saved = publish_research_pit_level2_low_memory(
            finance_root=root / "empty_finance",
            market_cap_path=source_path,
            root=root / "pit_level2",
            batch_size=37,
        )
        path = saved.get("valuation_daily_pit")
        if path is None or not path.exists():
            print("[FAIL] streaming valuation publisher did not create its artifact")
            return 1
        output = pd.read_parquet(path)
        if len(output) != len(source) or output["symbol"].nunique() != 3:
            print("[FAIL] streaming valuation publisher lost or duplicated rows")
            return 1
        try:
            publish_research_pit_level2_low_memory(
                finance_root=root / "empty_finance",
                market_cap_path=source_path,
                root=root / "pit_timeout",
                batch_size=37,
                max_runtime_seconds=1e-9,
            )
        except TimeoutError:
            pass
        else:
            print("[FAIL] PIT Level-2 publisher ignored its runtime deadline")
            return 1
    print("[PASS] valuation PIT publisher streams bounded batches without row loss")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
