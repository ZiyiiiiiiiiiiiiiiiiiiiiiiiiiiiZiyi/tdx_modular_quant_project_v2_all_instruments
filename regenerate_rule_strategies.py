# -*- coding: utf-8 -*-
"""Regenerate rule-based strategy selection parquet files from feature data.

This legacy entry point is intentionally disabled for full runs because the new
batch runner gives safer memory control. Use run_strategy_batches.py instead.
"""
from __future__ import annotations

import pandas as pd

from config import (
    FEATURE_DAILY_PARQUET,
    STRATEGY_END_DATE,
    STRATEGY_FREQ,
    STRATEGY_INCLUDE_TYPES,
    STRATEGY_SCORE_COL,
    STRATEGY_START_DATE,
    STRATEGY_TOP_N,
)
from functions.feature_engineering import select_instruments_by_score
from functions.strategy_registry import STRATEGY_REGISTRY
from functions.strategy_selection import run_strategy_selection

def main():
    raise SystemExit(
        "Use the low-memory runner instead, for example:\n"
        "& \"C:\\Users\\Ziyi Wang\\.conda\\envs\\stock_ai\\python.exe\" "
        "run_strategy_batches.py --mode select --sources rule --batch-size 1 --batch-index 0"
    )
    rule_specs = [spec for spec in STRATEGY_REGISTRY.values() if spec.source == "rule"]
    required_cols = {
        "date",
        "symbol",
        "close",
        "instrument_type",
        "is_trading",
        "abnormal_jump",
        "formal_price_eligible",
        "sector_parent",
        "sector_parent_heat",
        "sector_branch_heat",
    }
    required_cols.update(spec.score_col for spec in rule_specs)
    feature_cols = pd.read_parquet(
        FEATURE_DAILY_PARQUET,
        columns=[col for col in required_cols if col],
    )

    for spec in rule_specs:
        selection = select_instruments_by_score(
            feature_cols,
            spec.score_col,
            top_n=STRATEGY_TOP_N,
            freq=STRATEGY_FREQ,
            include_types=STRATEGY_INCLUDE_TYPES,
            start_date=STRATEGY_START_DATE,
            end_date=STRATEGY_END_DATE,
            ascending=spec.ascending,
        )
        print(f"Saving regenerated rule strategy: {spec.name}, rows={len(selection)}")
        run_strategy_selection(
            df_features=feature_cols,
            df_selection=selection,
            score_col=STRATEGY_SCORE_COL,
            top_n=STRATEGY_TOP_N,
            freq=STRATEGY_FREQ,
            include_types=STRATEGY_INCLUDE_TYPES,
            start_date=STRATEGY_START_DATE,
            end_date=STRATEGY_END_DATE,
            strategy_name=spec.name,
        )
    print(f"Regenerated rule strategy count: {len(rule_specs)}")


if __name__ == "__main__":
    main()
