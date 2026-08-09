"""Static and payload checks for the six-layer SCAP sizing Web contract."""
from __future__ import annotations

from functions.decision_council.live_monitor_web import _current_sizing_contract
from functions.decision_council.live_monitor_dashboard import HTML


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


payload = {
    "run_id": "run-test",
    "date": "2026-08-09",
    "exposure": {"holding_count": 3, "actual_exposure": 0.42},
    "monitor_state": {
        "sizing_contract_id": "decision|v2|hash",
        "sizing_contract_version": "scap_portfolio_sizing_v2",
        "policy_holding_target": 6,
        "executable_target_holding_count": 6,
        "authority_attainable_holding_count": 5,
        "policy_exposure_target": 0.85,
        "executable_target_exposure": 0.85,
        "authority_attainable_exposure": 0.72,
        "optimizer_planned_exposure": 0.70,
        "policy_floor_feasible_after_authority": True,
    },
}
contract = _current_sizing_contract(payload)
check(contract["status"] == "ok", "versioned sizing payload is not marked legacy")
check(contract["contract"]["actual_holding_count"] == 3, "actual holdings come from factual exposure")
check(abs(contract["contract"]["actual_exposure"] - 0.42) < 1e-12, "actual exposure comes from factual exposure")

legacy = _current_sizing_contract({"monitor_state": {}, "exposure": {}})
check(legacy["status"] == "legacy_contract_unavailable", "legacy missing fields are not forged as zero")

for token in (
    'id="exposureContractChart"',
    "function drawExposureContract()",
    "authorityAttainableHoldingCount",
    "authorityAttainableExposure",
    "policy_floor_feasible_after_authority",
    "/api/sizing-contract",
    "/api/sizing-export?format=csv",
    "历史合同无此字段",
    "旧分仓参考（影子）",
):
    check(token in HTML, f"dashboard contains {token}")

print("[PASS] SCAP sizing Web contract verification completed")
