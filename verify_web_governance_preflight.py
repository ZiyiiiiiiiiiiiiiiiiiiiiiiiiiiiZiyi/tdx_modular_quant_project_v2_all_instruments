"""Verify Web blocks date and current-snapshot leakage before launch."""
from __future__ import annotations

from main_launcher_web import _governance_preflight


def main() -> None:
    may_window = _governance_preflight("2025-01", "2026-05")
    assert may_window["requested_end"] == "2026-05-31"
    assert may_window["effective_end"] == "2026-05-29", may_window
    assert may_window["constituent_coverage"]["status"] == "pass", may_window
    assert may_window["status"] == "pass", may_window
    print("[PASS] weekend month-end is normalized to the last observed trading session")

    result = _governance_preflight("2025-01", "2026-06")
    assert result["status"] == "blocked"
    assert result["feature_date_max"] == "2026-06-05"
    assert "current_snapshot_backfilled_before_asof" not in result["reasons"]
    assert "pit_membership_coverage_outside_requested_window" in result["reasons"]
    print("[PASS] Web governance preflight blocks incomplete data and membership extrapolation")

    bounded = _governance_preflight("2025-01", "2026-06", max_days=5)
    assert bounded["requested_end"] == "2026-06-30"
    assert bounded["effective_end"] < "2026-06-05"
    assert not any("2026-06-30" in reason for reason in bounded["reasons"])
    assert bounded["constituent_coverage"]["status"] == "pass", bounded
    print("[PASS] bounded Web preflight uses observed sessions and covered PIT membership")


if __name__ == "__main__":
    main()
