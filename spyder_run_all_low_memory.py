# -*- coding: utf-8 -*-
"""Spyder-friendly one-click low-memory runner.

Open this file in Spyder and press Run.  It runs main.py one small batch at a
time in a fresh Python subprocess, so memory is released between batches.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from functions.governance import print_runtime_disclosure
from functions.strategy_registry import list_strategy_names

PROJECT_DIR = Path(r"F:\通信达量化\tdx_modular_quant_project_v2_all_instruments")
PYTHON_EXE = Path(r"E:\ForANACONDA\python.exe")

# Safest setting for a 5GB usable-memory machine.  Change to 4 only after the
# full batch-size-1 run is stable on your machine.
BATCH_SIZE = 1

# Keep batch planning aligned with the active registry.
TOTAL_STRATEGIES = len(list_strategy_names())

# Keep this True for normal use.  It reuses existing converted/clean/features
# parquet files and avoids rebuilding the 5GB feature table.
SKIP_DATA_STEPS = True

# Restart from a later batch if a previous Spyder session stopped midway.
START_BATCH_INDEX = 0

# Set to True to skip already written selection/backtest outputs.
RESUME = False


def main():
    if not PYTHON_EXE.exists():
        raise FileNotFoundError(f"Python interpreter not found: {PYTHON_EXE}")
    if not PROJECT_DIR.exists():
        raise FileNotFoundError(f"Project directory not found: {PROJECT_DIR}")

    batch_count = (TOTAL_STRATEGIES + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_index in range(START_BATCH_INDEX, batch_count):
        cmd = [
            str(PYTHON_EXE),
            "main.py",
            "--low-memory",
            "--mode",
            "all",
            "--batch-size",
            str(BATCH_SIZE),
            "--batch-index",
            str(batch_index),
        ]
        if SKIP_DATA_STEPS:
            cmd.append("--skip-data-steps")
        if RESUME:
            cmd.append("--resume")

        print("=" * 80)
        print(f"Running batch {batch_index + 1}/{batch_count}")
        print(" ".join(cmd))
        result = subprocess.run(cmd, cwd=PROJECT_DIR)
        if result.returncode != 0:
            raise RuntimeError(f"Batch {batch_index} failed with exit code {result.returncode}")

    print("=" * 80)
    print("All low-memory batches completed.")


if __name__ == "__main__":
    try:
        main()
    finally:
        print_runtime_disclosure()
