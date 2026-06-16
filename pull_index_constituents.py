# -*- coding: utf-8 -*-
"""Pull index constituents for target stock pools."""
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

OUTPUT_PATH = PROJECT_DIR / "data" / "processed" / "index_constituents.parquet"

TARGET_INDICES = {
    "000300": "沪深300",
    "000905": "中证500",
    "000903": "中证100",
    "000016": "上证50",
    "000510": "中证A500",
}


def pull_index_constituents():
    import akshare as ak

    all_rows = []
    errors = []

    for index_code, index_name in TARGET_INDICES.items():
        print(f"Pulling {index_name} ({index_code})...", end=" ", flush=True)
        try:
            raw = ak.index_stock_cons_csindex(symbol=index_code)
            if raw is None or raw.empty:
                print("EMPTY")
                errors.append({"index_code": index_code, "status": "empty"})
                continue

            code_col = next((c for c in ["成分券代码", "证券代码", "品种代码"] if c in raw.columns), None)
            if code_col is None:
                print(f"NO CODE COL: {raw.columns.tolist()}")
                errors.append({"index_code": index_code, "status": "no_code_column"})
                continue

            for _, row in raw.iterrows():
                code = str(row[code_col]).strip()
                digits = "".join(ch for ch in code if ch.isdigit())[-6:].zfill(6)
                if digits.startswith(("0", "1", "2", "3")):
                    symbol = f"sz{digits}"
                else:
                    symbol = f"sh{digits}"

                all_rows.append({
                    "index_code": index_code,
                    "index_name": index_name,
                    "symbol": symbol,
                    "first_trade_date": pd.Timestamp("2020-01-01"),
                    "out_date": pd.NaT,
                    "source": "akshare_csindex",
                    "asof_date": pd.Timestamp.today().normalize(),
                })

            print(f"OK ({len(raw)} stocks)")
            time.sleep(2)

        except Exception as e:
            print(f"ERROR: {str(e)[:60]}")
            errors.append({"index_code": index_code, "status": str(e)[:80]})
            time.sleep(2)

    if not all_rows:
        print("\nNo data pulled!")
        return

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=["index_code", "symbol"])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PATH, index=False)

    print(f"\n{'=' * 60}")
    print(f"Saved {len(df)} records to {OUTPUT_PATH}")
    print(f"\nPer index:")
    for code, name in TARGET_INDICES.items():
        count = len(df[df["index_code"] == code])
        print(f"  {name}: {count} stocks")

    unique_symbols = df["symbol"].nunique()
    print(f"\nUnique symbols across all indices: {unique_symbols}")

    if errors:
        print(f"\nErrors:")
        for e in errors:
            print(f"  {e['index_code']}: {e['status']}")


if __name__ == "__main__":
    pull_index_constituents()
