# -*- coding: utf-8 -*-
"""Verify crowding and factor-exposure diagnostics are emitted by backtests."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def verify_risk_monitoring_outputs():
    print("=== Verify risk monitoring outputs ===")
    metrics_path = Path("results/backtest_metrics_low_vol.csv")
    risk_path = Path("results/risk_monitoring_low_vol.csv")
    _expect(metrics_path.exists(), "low_vol metrics should exist")
    _expect(risk_path.exists(), "low_vol risk monitoring csv should exist")

    metrics = pd.read_csv(metrics_path)
    metric_map = dict(zip(metrics["metric"], metrics["value"]))
    for key in [
        "crowding_top_sector_weight",
        "crowding_hot_sector_weight",
        "crowding_unique_sector_count",
        "exposure_ret_20_tilt",
        "exposure_volatility_20_tilt",
        "exposure_close_to_ma20_tilt",
        "exposure_amount_ratio_20_tilt",
    ]:
        _expect(key in metric_map, f"{key} metric should be present")

    risk = pd.read_csv(risk_path)
    required_columns = {
        "rebalance_date",
        "top_sector_weight",
        "hot_sector_weight",
        "unique_sector_count",
        "exposure_ret_20_tilt",
        "exposure_volatility_20_tilt",
        "exposure_close_to_ma20_tilt",
        "exposure_amount_ratio_20_tilt",
    }
    _expect(required_columns.issubset(risk.columns), "risk monitoring csv should contain required columns")
    _expect(not risk.empty, "risk monitoring csv should not be empty")
    print("Risk monitoring verification passed.")


def _expect(condition, message):
    if not condition:
        raise SystemExit(message)
    print(f"[PASS] {message}")


if __name__ == "__main__":
    verify_risk_monitoring_outputs()
