# -*- coding: utf-8 -*-
"""Regenerate current registered strategy selection parquet files from feature data.

This legacy entry point is intentionally disabled for full runs because it loads
all strategies at once. Use run_strategy_batches.py instead.
"""
from __future__ import annotations

import pandas as pd

from config import FEATURE_DAILY_PARQUET
from functions.feature_engineering import generate_multi_strategies
from functions.strategy_selection import run_strategy_selection


STRATEGY_TOP_N = 20
STRATEGY_FREQ = "ME"
STRATEGY_START_DATE = "2021-01-01"
STRATEGY_END_DATE = None
STRATEGY_INCLUDE_TYPES = ("stock", "etf_fund")
STRATEGY_SCORE_COL = "score_mom_lowvol"


def main():
    raise SystemExit(
        "Use the low-memory runner instead, for example:\n"
        "& \"C:\\Users\\Ziyi Wang\\.conda\\envs\\stock_ai\\python.exe\" "
        "run_strategy_batches.py --mode select --batch-size 1 --batch-index 0"
    )
    features = pd.read_parquet(FEATURE_DAILY_PARQUET)
    strategies = generate_multi_strategies(
        features,
        top_n=STRATEGY_TOP_N,
        freq=STRATEGY_FREQ,
        include_types=STRATEGY_INCLUDE_TYPES,
        start_date=STRATEGY_START_DATE,
        end_date=STRATEGY_END_DATE,
    )
    for name, selection in strategies.items():
        print(f"Saving regenerated strategy: {name}, rows={len(selection)}")
        run_strategy_selection(
            df_features=features,
            df_selection=selection,
            score_col=STRATEGY_SCORE_COL,
            top_n=STRATEGY_TOP_N,
            freq=STRATEGY_FREQ,
            include_types=STRATEGY_INCLUDE_TYPES,
            start_date=STRATEGY_START_DATE,
            end_date=STRATEGY_END_DATE,
            strategy_name=name,
        )
    print(f"Regenerated strategy count: {len(strategies)}")


if __name__ == "__main__":
    main()
