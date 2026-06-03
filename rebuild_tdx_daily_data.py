# -*- coding: utf-8 -*-
"""Rebuild local TDX raw and clean daily artifacts only when validation fails."""
from config import READ_LIMIT
from functions.clean_daily_data import clean_daily_data
from functions.convert_tdx_daily import convert_tdx_daily


def main():
    print("Rebuilding local TDX raw daily parquet.")
    convert_tdx_daily(limit=READ_LIMIT)
    print("Rebuilding cleaned TDX daily parquet.")
    clean_daily_data()
    print("Local TDX raw and clean daily artifacts rebuilt.")


if __name__ == "__main__":
    main()
