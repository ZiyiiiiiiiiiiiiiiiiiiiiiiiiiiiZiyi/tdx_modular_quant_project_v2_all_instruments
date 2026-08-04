"""Post-save acceptance for the SCAP portfolio-constraint interface redesign."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


TOL = 1e-9


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _number(row: dict[str, str], name: str) -> float:
    value = float(row[name])
    if not math.isfinite(value):
        raise AssertionError(f"{name} is not finite: {row[name]!r}")
    return value


def _pass(message: str) -> None:
    print(f"[PASS] {message}")


def verify(run_dir: Path) -> None:
    daily = _rows(run_dir / "governance_daily_result.csv")
    plans = _rows(run_dir / "governance_action_plan_ledger.csv")
    proposals = _rows(run_dir / "governance_action_proposal_ledger.csv")
    orders = _rows(run_dir / "executable_order_plan.csv")
    reconciliation = _rows(run_dir / "governance_exposure_reconciliation.csv")

    assert len(daily) == 20, f"expected 20 daily rows, got {len(daily)}"
    required_daily = {
        "policy_band_state",
        "policy_holding_floor",
        "policy_holding_target",
        "policy_exposure_lower",
        "policy_exposure_target",
        "policy_exposure_upper",
        "policy_disaster_exposure_ceiling",
        "post_mandatory_holding_count",
        "post_mandatory_exposure",
        "conditional_holding_floor",
        "conditional_exposure_floor",
        "daily_effective_holding_ceiling",
        "daily_effective_exposure_ceiling",
        "post_mandatory_recovery_authorized",
        "post_mandatory_recovery_episode_id",
        "post_mandatory_recovery_episode_day",
        "planned_holding_count",
        "holding_floor_violation_count",
        "exposure_floor_violation",
        "wealth_materiality_epsilon_amount",
    }
    missing = required_daily.difference(daily[0])
    assert not missing, f"daily ledger misses redesigned fields: {sorted(missing)}"
    always_populated = required_daily.difference({"post_mandatory_recovery_episode_id"})
    assert all(row[name] != "" for row in daily for name in always_populated)
    for row in daily:
        recovery_authorized = row["post_mandatory_recovery_authorized"].strip().lower() in {
            "true",
            "1",
        }
        if recovery_authorized:
            assert row["post_mandatory_recovery_episode_id"] != ""
    _pass("all redesigned policy, projection, conditional-floor and recovery fields persist")

    for row in daily:
        k_min = _number(row, "policy_holding_floor")
        k_target = _number(row, "policy_holding_target")
        k_max = _number(row, "daily_effective_holding_ceiling")
        k_conditional = _number(row, "conditional_holding_floor")
        e_min = _number(row, "policy_exposure_lower")
        e_target = _number(row, "policy_exposure_target")
        e_upper = _number(row, "policy_exposure_upper")
        e_disaster = _number(row, "policy_disaster_exposure_ceiling")
        e_max = _number(row, "daily_effective_exposure_ceiling")
        e_conditional = _number(row, "conditional_exposure_floor")
        assert 0 <= k_conditional <= k_min <= k_target
        assert k_conditional <= k_max
        assert 0 <= e_conditional <= e_min <= e_target <= e_upper <= e_disaster <= 1 + TOL
        assert e_conditional <= e_max + TOL
        assert _number(row, "planned_holding_count") <= k_max + TOL
    _pass("hard ceilings and conditional floors are monotone on every session")

    floor_feasible_by_date = {
        row["date"]: row["policy_floor_feasible_pre_optimizer"].strip().lower()
        in {"true", "1"}
        for row in daily
    }
    feasible_plans = [
        row for row in plans if floor_feasible_by_date.get(row["decision_date"], False)
    ]
    assert feasible_plans, "no pre-optimizer floor-feasible session was saved"
    assert all(
        _number(row, "holding_floor_violation_count") == 0 for row in feasible_plans
    )
    assert all(
        _number(row, "exposure_floor_violation") <= TOL for row in feasible_plans
    )
    assert all(
        _number(row, "projected_exposure") <= _number(row, "hard_exposure_ceiling") + TOL
        for row in plans
    )
    _pass(
        "every pre-optimizer feasible plan satisfies its floor; all plans respect the hard exposure ceiling"
    )

    proposal_by_id = {row["proposal_id"]: row for row in proposals}
    selected_orders = [
        row for row in orders if row.get("action_plan_selected", "").strip().lower() in {"true", "1"}
    ]
    assert selected_orders, "no selected orders were saved"
    for order in selected_orders:
        proposal_id = order["action_proposal_id"]
        assert proposal_id in proposal_by_id, f"missing proposal {proposal_id}"
        proposal_delta = abs(_number(proposal_by_id[proposal_id], "exposure_delta"))
        order_delta = abs(_number(order, "delta_weight"))
        assert abs(proposal_delta - order_delta) <= TOL, (
            f"proposal/order exposure mismatch for {proposal_id}: "
            f"proposal={proposal_delta}, order={order_delta}"
        )
        assert _number(order, "plan_target_exposure") <= _number(
            order, "plan_hard_exposure_ceiling"
        ) + TOL
    _pass("proposal, action-plan and executable-order exposure deltas reconcile exactly")

    for row in reconciliation:
        assert abs(_number(row, "target_gap_reconciliation_error")) <= TOL
        assert abs(_number(row, "lower_gap_reconciliation_error")) <= TOL
        assert abs(_number(row, "reconciliation_error")) <= TOL
    _pass("target-gap and lower-floor reconciliation errors are zero")

    episodes: dict[str, list[int]] = {}
    for row in daily:
        episode_id = row["post_mandatory_recovery_episode_id"]
        if episode_id:
            episodes.setdefault(episode_id, []).append(
                int(float(row["post_mandatory_recovery_episode_day"]))
            )
    for days in episodes.values():
        assert days == sorted(days), f"recovery episode days regress: {days}"
    _pass("recovery episode state is persistent and non-regressing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    verify(args.run_dir.resolve())
    _pass(f"SCAP interface-redesign 20-day acceptance completed: {args.run_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
