# -*- coding: utf-8 -*-
"""Investable benchmark helpers for exploratory comparison."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import (
    BENCHMARK_REPORT_CSV,
    DEFAULT_INVESTABLE_BENCHMARK_ID,
    DEFAULT_INVESTABLE_BENCHMARK_PRICE_COL,
    FEATURE_DAILY_PARQUET,
)


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


def resolve_investable_benchmark_symbol(
    feature_data: pd.DataFrame,
    *,
    benchmark_id: str = DEFAULT_INVESTABLE_BENCHMARK_ID,
) -> tuple[str | None, str]:
    if benchmark_id not in BENCHMARK_SYMBOLS:
        return None, f"unknown benchmark id: {benchmark_id}"
    available = set(feature_data.get("symbol", pd.Series(dtype=str)).astype(str).unique().tolist())
    candidates = BENCHMARK_SYMBOLS[benchmark_id]
    matched = next((symbol for symbol in candidates if symbol in available), None)
    if matched is None:
        return None, f"no configured symbol available for {benchmark_id}"
    return matched, "ok"


def build_benchmark_return_frame(
    feature_data: pd.DataFrame,
    *,
    benchmark_id: str = DEFAULT_INVESTABLE_BENCHMARK_ID,
    price_col: str = DEFAULT_INVESTABLE_BENCHMARK_PRICE_COL,
) -> tuple[pd.DataFrame, dict]:
    symbol, status = resolve_investable_benchmark_symbol(feature_data, benchmark_id=benchmark_id)
    meta = {
        "benchmark_id": benchmark_id,
        "benchmark_symbol": symbol or "",
        "benchmark_status": status,
    }
    if symbol is None:
        return pd.DataFrame(columns=["date", "benchmark_return", "benchmark_nav"]), meta

    available_columns = set(feature_data.columns)
    usable_price_col = price_col if price_col in available_columns else ("close" if "close" in available_columns else None)
    if usable_price_col is None:
        meta["benchmark_status"] = "benchmark price column unavailable"
        return pd.DataFrame(columns=["date", "benchmark_return", "benchmark_nav"]), meta

    bench = feature_data.loc[feature_data["symbol"].astype(str) == symbol, ["date", usable_price_col]].copy()
    bench["date"] = pd.to_datetime(bench["date"], errors="coerce")
    bench = bench.dropna(subset=["date"]).sort_values("date").drop_duplicates("date")
    bench["benchmark_price"] = pd.to_numeric(bench[usable_price_col], errors="coerce")
    bench["benchmark_return"] = bench["benchmark_price"].pct_change().fillna(0.0)
    bench["benchmark_nav"] = (1.0 + bench["benchmark_return"]).cumprod()
    meta["benchmark_status"] = f"available: {benchmark_id} via {symbol}"
    return bench[["date", "benchmark_return", "benchmark_nav"]].copy(), meta
