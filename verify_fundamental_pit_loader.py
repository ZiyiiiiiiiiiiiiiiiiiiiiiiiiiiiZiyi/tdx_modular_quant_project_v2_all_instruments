"""Verify PIT fundamental loader."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from functions.data.fundamental_pit_loader import build_pit_fundamental_daily


def main() -> int:
    reports = pd.DataFrame(
        [
            {"stock_code": "sh600000", "report_period": "2023-12-31", "publish_date": "2024-03-20", "available_date": "2024-03-21", "revenue": 100, "net_profit": 10},
            {"stock_code": "sh600000", "report_period": "2024-03-31", "publish_date": "2024-04-25", "available_date": "2024-04-26", "revenue": 120, "net_profit": 12},
            {"stock_code": "sz000001", "report_period": "2024-03-31", "publish_date": None, "available_date": None, "revenue": 50, "net_profit": 5},
        ]
    )
    out_dir = Path("reports/verify_fundamental_pit_loader")
    daily, quality = build_pit_fundamental_daily(reports, pd.bdate_range("2024-03-01", "2024-05-10"), output_dir=out_dir)
    if daily.empty:
        print("[FAIL] PIT daily output is empty")
        return 1
    if (pd.to_datetime(daily["trade_date"]) < pd.to_datetime(daily["available_date"])).any():
        print("[FAIL] future leakage detected")
        return 1
    for name in ["pit_coverage_report", "pit_missing_publish_date", "pit_sanity_check"]:
        if name not in quality or not (out_dir / f"{name}.csv").exists():
            print(f"[FAIL] missing report: {name}")
            return 1
    print(f"[PASS] PIT rows={len(daily)}, reports={list(quality)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
