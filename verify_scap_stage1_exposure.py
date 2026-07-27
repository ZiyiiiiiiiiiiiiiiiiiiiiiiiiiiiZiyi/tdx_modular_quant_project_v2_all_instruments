"""Stage-1 checks for non-circular SCAP exposure targets."""
from __future__ import annotations

from functions.decision_council.small_capital_aggressive import (
    build_scap_exposure_targets,
    desired_exposure_from_signal_count,
)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    _check(
        desired_exposure_from_signal_count(actual_exposure=0.10, qualified_entry_count=0) == 0.10,
        "zero signals do not force deployment",
    )
    _check(
        desired_exposure_from_signal_count(actual_exposure=0.10, qualified_entry_count=3) == 0.90,
        "three signals request the registered aggressive exposure",
    )
    targets = build_scap_exposure_targets(
        actual_exposure=0.20,
        authorized_risk_ceiling=0.90,
        feasible_increment=0.15,
        qualified_entry_count=3,
    )
    _check(targets.risk_exposure_ceiling == 0.90, "risk ceiling remains independent")
    _check(targets.desired_exposure_target == 0.90, "desired target is not overwritten by lot feasibility")
    _check(targets.executable_exposure_target == 0.35, "executable target reflects one-lot capacity")
    _check(abs(targets.lot_feasibility_drag - 0.55) < 1e-12, "lot feasibility drag is explicit")
    capped = build_scap_exposure_targets(
        actual_exposure=0.20,
        authorized_risk_ceiling=0.50,
        feasible_increment=0.80,
        qualified_entry_count=4,
    )
    _check(capped.desired_exposure_target == 0.50, "risk ceiling caps desired exposure")
    _check(abs(capped.risk_ceiling_drag - 0.45) < 1e-12, "risk ceiling drag is explicit")
    no_signal = build_scap_exposure_targets(
        actual_exposure=0.30,
        authorized_risk_ceiling=0.90,
        feasible_increment=0.0,
        qualified_entry_count=0,
    )
    _check(no_signal.executable_exposure_target == 0.30, "no-signal executable target preserves current exposure")
    _check(abs(no_signal.signal_cash_drag - 0.60) < 1e-12, "no-signal cash drag is explicit")


if __name__ == "__main__":
    main()
