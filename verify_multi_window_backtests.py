# -*- coding: utf-8 -*-
from pathlib import Path

import pandas as pd

from config import MULTI_WINDOW_BACKTEST_REPORT_MD, MULTI_WINDOW_BACKTEST_SUMMARY_CSV
from functions.date_window import generate_calendar_windows


def verify_multi_window_backtests():
    failures: list[str] = []
    print("=== Verify multi-window backtests ===")

    windows = generate_calendar_windows("2021-01-01", "2021-12-31", window_months=6, step_months=6)
    if len(windows) != 2:
        failures.append(f"expected 2 half-year windows, got {len(windows)}")
        print(f"[FAIL] expected 2 half-year windows, got {len(windows)}")
    else:
        print("[PASS] calendar window helper generated the expected half-year windows")

    summary_path = Path(MULTI_WINDOW_BACKTEST_SUMMARY_CSV)
    report_path = Path(MULTI_WINDOW_BACKTEST_REPORT_MD)
    if not summary_path.exists():
        failures.append(f"missing summary file: {summary_path}")
        print(f"[FAIL] missing summary file: {summary_path}")
    else:
        summary = pd.read_csv(summary_path)
        required_columns = {
            "strategy",
            "window_id",
            "window_start_date",
            "window_end_date",
            "window_months",
            "step_months",
            "date_window",
            "total_return",
            "sharpe",
            "max_drawdown",
        }
        missing = sorted(required_columns - set(summary.columns))
        if missing:
            failures.append(f"multi-window summary missing columns: {missing}")
            print(f"[FAIL] multi-window summary missing columns: {missing}")
        else:
            print("[PASS] multi-window summary columns present")
        if not summary.empty and not summary["date_window"].astype(str).str.contains("->", regex=False).all():
            failures.append("multi-window summary date_window values are not window-specific")
            print("[FAIL] multi-window summary date_window values are not window-specific")
        else:
            print("[PASS] multi-window summary records window-specific date ranges")

    if not report_path.exists():
        failures.append(f"missing report file: {report_path}")
        print(f"[FAIL] missing report file: {report_path}")
    else:
        report_text = report_path.read_text(encoding="utf-8")
        required_sections = {"## Summary", "## Window Records", "## Strategy Averages"}
        missing_sections = sorted(section for section in required_sections if section not in report_text)
        if missing_sections:
            failures.append(f"multi-window report missing sections: {missing_sections}")
            print(f"[FAIL] multi-window report missing sections: {missing_sections}")
        else:
            print("[PASS] multi-window report sections present")

    print()
    if failures:
        print("Multi-window backtest verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Multi-window backtest verification passed.")


if __name__ == "__main__":
    verify_multi_window_backtests()
