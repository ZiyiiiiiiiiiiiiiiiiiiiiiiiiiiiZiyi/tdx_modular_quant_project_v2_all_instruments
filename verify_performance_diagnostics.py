# -*- coding: utf-8 -*-
"""Verify annual return and alpha-decay diagnostic outputs."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from functions.performance_charts import save_performance_diagnostics


def verify_performance_diagnostics():
    print("=== Verify performance diagnostics ===")
    daily_result = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2021-01-29",
                    "2021-02-26",
                    "2021-12-31",
                    "2022-01-31",
                    "2022-12-30",
                ]
            ),
            "daily_return": [0.01, -0.02, 0.03, 0.01, -0.01],
            "net_value": [1.01, 0.9898, 1.019494, 1.02968894, 1.0193920506],
            "drawdown": [0.0, -0.02, 0.0, 0.0, -0.01],
            "initial_cash": [1.0] * 5,
        }
    )
    selection = pd.DataFrame(
        {
            "rebalance_date": pd.to_datetime(["2021-01-29", "2021-12-31", "2022-01-31"]),
            "symbol": ["sh600000", "sh600000", "sz000001"],
            "score": [0.8, 0.7, 0.9],
            "target_weight": [0.4, 0.5, 0.6],
        }
    )
    feature_data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2021-01-29", "2021-12-31", "2022-01-31"]),
            "symbol": ["sh600000", "sh600000", "sz000001"],
            "future_ret_1": [0.01, 0.02, 0.03],
            "future_ret_5": [0.03, 0.01, 0.05],
            "future_ret_10": [0.04, -0.01, 0.02],
        }
    )

    with TemporaryDirectory() as tmp_dir:
        outputs = save_performance_diagnostics(
            daily_result=daily_result,
            strategy_name="diagnostic_smoke",
            output_dir=tmp_dir,
            selection=selection,
            feature_data=feature_data,
        )
        required_keys = {
            "performance_dashboard",
            "monthly_return_heatmap",
            "monthly_return_heatmap_summary",
            "annual_return_distribution",
            "annual_return_distribution_summary",
            "kelly_distribution",
            "kelly_distribution_summary",
            "alpha_decay_curve",
            "alpha_decay_curve_summary",
        }
        missing = sorted(required_keys - set(outputs))
        _expect(not missing, f"missing diagnostic outputs: {missing}")

        summary_text = Path(outputs["annual_return_distribution_summary"]).read_text(encoding="utf-8")
        _expect("Positive years" in summary_text, "annual summary should mention positive years")
        alpha_text = Path(outputs["alpha_decay_curve_summary"]).read_text(encoding="utf-8")
        _expect("Peak mean forward return horizon" in alpha_text, "alpha decay summary should mention peak horizon")

    print("Performance diagnostics verification passed.")


def _expect(condition, message):
    if not condition:
        raise SystemExit(message)
    print(f"[PASS] {message}")


if __name__ == "__main__":
    verify_performance_diagnostics()
