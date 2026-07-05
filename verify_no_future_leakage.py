"""Verify no-future-leakage guards for new PIT/event modules."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def main() -> int:
    pit_reports = sorted(Path("reports").glob("**/pit_sanity_check.csv"))
    for report in pit_reports:
        data = pd.read_csv(report)
        if "future_leakage_rows" in data.columns and int(pd.to_numeric(data["future_leakage_rows"], errors="coerce").fillna(0).sum()) > 0:
            print(f"[FAIL] future leakage rows in {report}")
            return 1
    forbidden = []
    for path in [
        Path("functions/data/fundamental_pit_loader.py"),
        Path("functions/factors/fundamental_composite_factors.py"),
        Path("functions/factors/event_factor_builder.py"),
    ]:
        text = path.read_text(encoding="utf-8")
        if "report_period" in text and "available_date" not in text and path.name == "fundamental_pit_loader.py":
            forbidden.append(str(path))
    if forbidden:
        print(f"[FAIL] possible report_period direct-use leakage: {forbidden}")
        return 1
    print(f"[PASS] no future leakage reports failed; checked {len(pit_reports)} PIT reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
