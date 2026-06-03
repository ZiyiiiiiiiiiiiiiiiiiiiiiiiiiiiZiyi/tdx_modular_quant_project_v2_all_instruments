# -*- coding: utf-8 -*-
"""Rebuild and publish a versioned strategy summary from the live pipeline."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import (
    BACKTEST_SUMMARY_V2_CSV,
    FORMAL_MODE_NAME,
    RESEARCH_RUN_MODE,
    RESULT_DIR,
)
from functions.strategy_registry import list_strategy_names


def build_rebuild_plan():
    return {
        "strategy_count": len(list_strategy_names()),
        "strategy_names": list_strategy_names(),
        "result_dir": str(RESULT_DIR),
        "target_summary_path": str(BACKTEST_SUMMARY_V2_CSV),
        "research_run_mode": RESEARCH_RUN_MODE,
    }


def publish_current_summary(
    input_path=RESULT_DIR / "backtest_strategy_summary.csv",
    output_path=BACKTEST_SUMMARY_V2_CSV,
):
    input_file = Path(input_path)
    if not input_file.exists():
        raise FileNotFoundError("Run main.py successfully before publishing a rebuilt summary")
    summary = pd.read_csv(input_file)
    expected = set(list_strategy_names())
    actual = set(summary["strategy"]) if "strategy" in summary.columns else set()
    if actual != expected:
        raise ValueError("Existing backtest summary does not match the currently registered strategy set")
    summary["baseline_status"] = (
        "formal_candidate" if RESEARCH_RUN_MODE == FORMAL_MODE_NAME
        else "exploratory_not_rankable"
    )
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output_file, index=False, encoding="utf-8-sig")
    return output_file


if __name__ == "__main__":
    output = publish_current_summary()
    print(f"Published rebuilt baseline summary: {output}")
