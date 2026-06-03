# -*- coding: utf-8 -*-
"""Build HS300/CSI500/CSI A500 point-in-time constituent parquet.

Examples:
    & "E:\\ForANACONDA\\python.exe" build_index_constituents.py --source file --input data/raw_external/index_constituents.csv
    & "C:\\Users\\Ziyi Wang\\.conda\\envs\\stock_ai\\python.exe" build_index_constituents.py --source akshare --append
"""
from __future__ import annotations

import argparse

import pandas as pd

from functions.data_sources.index_constituents_provider import (
    fetch_current_csindex_constituents_with_akshare,
    merge_constituent_snapshot,
    save_index_constituents,
)
from functions.investable_universe import (
    INDEX_CONSTITUENTS_PARQUET,
    INDEX_UNIVERSE_QUALITY_CSV,
    TARGET_INDEX_POOLS,
    build_index_universe_quality_report,
    load_index_constituents,
    normalize_index_constituents,
    save_index_universe_quality_report,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["akshare", "file"], default="akshare")
    parser.add_argument("--input", default=None, help="CSV/XLSX file for --source file.")
    parser.add_argument("--output", default=str(INDEX_CONSTITUENTS_PARQUET))
    parser.add_argument("--append", action="store_true", help="Append current snapshot and close disappeared names.")
    parser.add_argument("--asof-date", default=None)
    parser.add_argument("--start-date", default="2024-09-23", help="Coverage report start date.")
    parser.add_argument("--end-date", default=None, help="Coverage report end date. Defaults to asof/today.")
    return parser.parse_args()


def main():
    args = parse_args()
    asof = pd.Timestamp(args.asof_date or pd.Timestamp.today().normalize())
    if args.source == "file":
        if not args.input:
            raise SystemExit("--input is required when --source=file")
        snapshot = _read_input_file(args.input)
        snapshot = normalize_index_constituents(snapshot, source="manual_file")
    else:
        result = fetch_current_csindex_constituents_with_akshare(asof_date=asof)
        if not result.errors.empty:
            print("Index constituent fetch errors:")
            print(result.errors.to_string(index=False))
        snapshot = result.data
        if snapshot.empty:
            raise SystemExit("No index constituents were fetched.")

    existing = load_index_constituents(args.output) if args.append else pd.DataFrame()
    final = merge_constituent_snapshot(existing, snapshot, asof_date=asof) if args.append else snapshot
    output = save_index_constituents(final, args.output)
    end_date = pd.Timestamp(args.end_date or asof)
    quality = build_index_universe_quality_report(final, start_date=args.start_date, end_date=end_date)
    quality_path = save_index_universe_quality_report(quality, INDEX_UNIVERSE_QUALITY_CSV)
    print("Saved index constituents:", output)
    print("Saved index universe quality report:", quality_path)
    print(quality.to_string(index=False))
    print("Target pools:", ", ".join(f"{k}={v['index_code']}" for k, v in TARGET_INDEX_POOLS.items()))


def _read_input_file(path):
    value = str(path)
    if value.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(value)
    return pd.read_csv(value, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
