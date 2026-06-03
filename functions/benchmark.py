# -*- coding: utf-8 -*-
"""Investable benchmark helpers for exploratory comparison."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import BENCHMARK_REPORT_CSV, FEATURE_DAILY_PARQUET


BENCHMARK_SYMBOLS = {
    "hs300_etf": ("sh510300", "sh510310", "sz159919"),
    "csi500_etf": ("sh510500", "sz159922"),
    "csi1000_etf": ("sh512100", "sz159845"),
}


def build_investable_benchmark_report(feature_path=FEATURE_DAILY_PARQUET):
    path = Path(feature_path)
    if not path.exists():
        return pd.DataFrame(columns=["benchmark_id", "symbol", "status", "detail"])
    features = pd.read_parquet(path, columns=["symbol"]).drop_duplicates()
    available = set(features["symbol"].astype(str))
    rows = []
    for benchmark_id, candidates in BENCHMARK_SYMBOLS.items():
        matched = next((symbol for symbol in candidates if symbol in available), None)
        rows.append(
            {
                "benchmark_id": benchmark_id,
                "symbol": matched or "",
                "status": "available" if matched else "missing",
                "detail": "Tradable ETF found in feature universe" if matched else "No configured ETF found in feature universe",
            }
        )
    rows.extend(
        [
            {"benchmark_id": "same_universe_equal_weight", "symbol": "", "status": "interface_ready", "detail": "Requires strategy-date universe reconstruction."},
            {"benchmark_id": "all_a_investable_equal_weight", "symbol": "", "status": "blocked", "detail": "Requires PIT investable universe."},
        ]
    )
    return pd.DataFrame(rows)


def save_investable_benchmark_report(output_path=BENCHMARK_REPORT_CSV):
    report = build_investable_benchmark_report()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(output_path, index=False, encoding="utf-8-sig")
    return Path(output_path)
