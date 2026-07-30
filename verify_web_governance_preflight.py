"""Verify Web blocks date and current-snapshot leakage before launch."""
from __future__ import annotations

from main_launcher_web import _governance_preflight


def main() -> None:
    may_window = _governance_preflight(
        "2024-01",
        "2026-05",
        universe_ids=["all_a_share_research"],
    )
    assert may_window["requested_start"] == "2024-01-01"
    assert may_window["requested_end"] == "2026-05-31"
    assert may_window["effective_end"] == "2026-05-29", may_window
    assert may_window["constituent_coverage"]["status"] == "not_required", may_window
    assert may_window["constituent_status"] == "not_required", may_window
    assert may_window["status"] == "pass", may_window
    print("[PASS] all-A-share window ignores unrelated index membership coverage")

    result = _governance_preflight(
        "2024-01",
        "2026-05",
        universe_ids=["a500_strict"],
    )
    assert result["status"] == "blocked"
    assert "current_snapshot_backfilled_before_asof" not in result["reasons"]
    assert "pit_membership_coverage_outside_requested_window" in result["reasons"]
    print("[PASS] strict index universe still blocks membership extrapolation")

    bounded = _governance_preflight(
        "2025-01",
        "2026-06",
        max_days=5,
        universe_ids=["a500_strict"],
    )
    assert bounded["requested_end"] == "2026-06-30"
    assert bounded["effective_end"] < "2026-06-05"
    assert not any("2026-06-30" in reason for reason in bounded["reasons"])
    assert bounded["constituent_coverage"]["status"] == "pass", bounded
    print("[PASS] bounded Web preflight uses observed sessions and covered PIT membership")


if __name__ == "__main__":
    main()
