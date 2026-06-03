# -*- coding: utf-8 -*-
"""Verify automatic index-constituent snapshot normalization and merging."""
from __future__ import annotations

import pandas as pd

from functions.data_sources.index_constituents_provider import merge_constituent_snapshot
from functions.investable_universe import build_index_universe_quality_report, normalize_index_constituents


def main():
    first = normalize_index_constituents(
        pd.DataFrame(
            [
                {
                    "index_code": "000300",
                    "index_name": "沪深300",
                    "symbol": "sh600000",
                    "announcement_date": "2024-01-01",
                    "effective_after_close_date": "2024-01-01",
                    "first_trade_date": "2024-01-02",
                    "out_date": pd.NaT,
                    "source": "test_snapshot",
                    "asof_date": "2024-01-02",
                },
                {
                    "index_code": "000300",
                    "index_name": "沪深300",
                    "symbol": "sz000001",
                    "announcement_date": "2024-01-01",
                    "effective_after_close_date": "2024-01-01",
                    "first_trade_date": "2024-01-02",
                    "out_date": pd.NaT,
                    "source": "test_snapshot",
                    "asof_date": "2024-01-02",
                },
            ]
        )
    )
    second = normalize_index_constituents(
        pd.DataFrame(
            [
                {
                    "index_code": "000300",
                    "index_name": "沪深300",
                    "symbol": "sh600000",
                    "announcement_date": "2024-02-01",
                    "effective_after_close_date": "2024-02-01",
                    "first_trade_date": "2024-02-02",
                    "out_date": pd.NaT,
                    "source": "test_snapshot",
                    "asof_date": "2024-02-02",
                },
                {
                    "index_code": "000300",
                    "index_name": "沪深300",
                    "symbol": "sh600001",
                    "announcement_date": "2024-02-01",
                    "effective_after_close_date": "2024-02-01",
                    "first_trade_date": "2024-02-02",
                    "out_date": pd.NaT,
                    "source": "test_snapshot",
                    "asof_date": "2024-02-02",
                },
            ]
        )
    )
    merged = merge_constituent_snapshot(first, second, asof_date="2024-02-02")
    old_removed = merged[(merged["index_code"] == "000300") & (merged["symbol"] == "sz000001")].iloc[0]
    new_added = merged[(merged["index_code"] == "000300") & (merged["symbol"] == "sh600001")].iloc[0]
    assert pd.Timestamp(old_removed["out_date"]) == pd.Timestamp("2024-02-02")
    assert pd.Timestamp(new_added["first_trade_date"]) == pd.Timestamp("2024-02-02")
    report = build_index_universe_quality_report(merged, start_date="2024-01-02", end_date="2024-02-05")
    assert "coverage_ratio" in report.columns
    print("Index constituent builder verification passed.")


if __name__ == "__main__":
    main()
