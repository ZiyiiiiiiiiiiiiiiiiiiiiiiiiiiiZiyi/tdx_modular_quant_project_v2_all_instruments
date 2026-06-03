# -*- coding: utf-8 -*-
import tempfile
from pathlib import Path

import pandas as pd

from functions.market_regime import classify_monthly_market_regime, summarize_strategy_by_regime
from functions.report_builder import build_strategy_report, save_strategy_report


def verify_report_builder():
    failures: list[str] = []
    print("=== Verify report builder ===")

    summary = pd.DataFrame(
        {
            "strategy": ["alpha", "beta"],
            "total_return": [0.2, 0.1],
            "sharpe": [1.2, 0.9],
        }
    )
    benchmark = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=60, freq="D"),
            "benchmark_return": [0.01] * 20 + [-0.01] * 20 + [0.0] * 20,
        }
    )
    strategy_daily = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=60, freq="D"),
            "daily_return": [0.005] * 60,
        }
    )

    regime = classify_monthly_market_regime(benchmark)
    regime_summary = summarize_strategy_by_regime(strategy_daily, regime)
    report_text = build_strategy_report(summary, regime_summary)
    if "Strategy Diagnostic Report" not in report_text:
        failures.append("report text missing title")
        print("[FAIL] report text missing title")
    else:
        print("[PASS] report text generated")

    with tempfile.TemporaryDirectory() as tmpdir:
        output = save_strategy_report(report_text, Path(tmpdir) / "report.md")
        if not output.exists():
            failures.append("report file missing after save")
            print("[FAIL] report file missing after save")
        else:
            print("[PASS] report file saved")

    print()
    if failures:
        print("Report builder verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Report builder verification passed.")


if __name__ == "__main__":
    verify_report_builder()
