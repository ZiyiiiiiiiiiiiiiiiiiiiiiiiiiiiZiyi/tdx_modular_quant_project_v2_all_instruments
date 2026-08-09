"""Verify governance Web holding-count history and compatibility contract."""
from __future__ import annotations

from pathlib import Path

from functions.decision_council.live_monitor import GovernanceLiveMonitor


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def main() -> int:
    monitor = GovernanceLiveMonitor.__new__(GovernanceLiveMonitor)
    monitor._closed = False
    monitor._ensure_monitor_process = lambda: None
    monitor._write_state = lambda payload: setattr(monitor, "written", payload)
    monitor._last_day_index = -1
    monitor._chart_history = []
    monitor._last_update_payload = {}
    monitor._run_id = "holding-count-test"
    monitor._title = "holding-count-test"
    monitor._output_dir = ""
    monitor.total_days = 2
    monitor.initial_nav = 20_000.0
    monitor.refresh_every_days = 1
    monitor.max_chart_points = 1200
    monitor.update(
        date="2026-01-05",
        day_index=0,
        exposure={
            "nominal_nav": 20_000.0,
            "cash": 8_000.0,
            "invested_value": 12_000.0,
            "actual_exposure": 0.60,
            "holding_count": 5,
        },
        monitor_state={
            "optimizer_planned_holding_count": 6,
            "minimum_required_holding_count": 5,
            "soft_target_holding_count": 6,
            "maximum_allowed_holding_count": 7,
            "policy_band_state": "normal_neutral",
        },
    )
    point = monitor.written["chart_history"][0]
    check("actual holding count comes from factual exposure", point["actual_holding_count"] == 5)
    check("optimizer holding count is preserved", point["optimizer_planned_holding_count"] == 6)
    check(
        "policy holding boundaries are preserved",
        (
            point["minimum_required_holding_count"],
            point["soft_target_holding_count"],
            point["maximum_allowed_holding_count"],
        )
        == (5, 6, 7),
    )
    check("policy band state is preserved", point["policy_band_state"] == "normal_neutral")

    dashboard = Path(
        "functions/decision_council/live_monitor_dashboard.py"
    ).read_text(encoding="utf-8")
    for required in (
        'id="holdingCountChart"',
        "function drawHoldingCount()",
        "function drawStepLine",
        "nullableNumber(row.actual_holding_count)",
        "nullableNumber(row.optimizer_planned_holding_count)",
        'return drawEmpty(ctx,"历史状态没有持仓数量字段")',
    ):
        check(f"dashboard contains {required}", required in dashboard)
    check(
        "old history is nullable rather than forged as zero",
        'if(value===null||value===undefined||value==="")return null' in dashboard,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
