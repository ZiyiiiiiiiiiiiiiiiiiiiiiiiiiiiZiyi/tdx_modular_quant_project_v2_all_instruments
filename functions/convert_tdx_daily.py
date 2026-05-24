# -*- coding: utf-8 -*-
import pandas as pd
from tqdm import tqdm

from config import (
    TDX_DIR,
    INCLUDE_MARKETS,
    INCLUDE_INSTRUMENT_TYPES,
    RAW_DAILY_PARQUET,
    FAILED_CODES_CSV,
)
from functions.tdx_day_file_reader import collect_tdx_day_files, read_tdx_day_file

def convert_tdx_daily(limit=None):
    print("TDX_DIR:", TDX_DIR)
    print("TDX exists:", TDX_DIR.exists())
    print("vipdoc exists:", (TDX_DIR / "vipdoc").exists())

    file_rows = collect_tdx_day_files(
        tdx_dir=TDX_DIR,
        include_markets=INCLUDE_MARKETS,
        include_types=INCLUDE_INSTRUMENT_TYPES,
    )

    if limit is not None:
        file_rows = file_rows[:limit]

    print("Total selected instruments:", len(file_rows))
    print("First 20 instruments:")
    for row in file_rows[:20]:
        print(row["symbol"], row["instrument_type"])

    all_data = []
    failed = []

    for row in tqdm(file_rows):
        try:
            df_one = read_tdx_day_file(
                file_path=row["file_path"],
                market=row["market"],
                code=row["code"],
                symbol=row["symbol"],
                instrument_type=row["instrument_type"],
            )
            if df_one is None or df_one.empty:
                failed.append(row)
            else:
                all_data.append(df_one)
        except Exception as e:
            row2 = row.copy()
            row2["error"] = str(e)
            failed.append(row2)

    if len(all_data) == 0:
        raise RuntimeError("No daily data was read. Please check TDX files.")

    data = pd.concat(all_data, ignore_index=True)
    data = data.sort_values(["symbol", "date"])
    data.to_parquet(RAW_DAILY_PARQUET, index=False)

    pd.DataFrame(failed).to_csv(FAILED_CODES_CSV, index=False, encoding="utf-8-sig")

    print("Saved raw daily data:", RAW_DAILY_PARQUET)
    print("Shape:", data.shape)
    print("Instrument count:", data["symbol"].nunique())
    print("Instrument type count:")
    print(data[["symbol", "instrument_type"]].drop_duplicates()["instrument_type"].value_counts())
    print("Failed count:", len(failed))
    print("Failed saved:", FAILED_CODES_CSV)

    return data
