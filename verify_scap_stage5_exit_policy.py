"""Stage-5 checks for SCAP E0-E4 and loss containment."""
from __future__ import annotations

from functions.decision_council.small_capital_aggressive import (
    scap_control_enabled,
    scap_exit_stage_level,
    scap_loss_containment_exit,
)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    _check(scap_exit_stage_level("e0") == 0 and scap_exit_stage_level("E4") == 4, "exit stages normalize deterministically")
    _check(not scap_control_enabled(exit_stage="E0", control_name="signal_failure_exit"), "E0 keeps alpha exits paper-only")
    _check(scap_control_enabled(exit_stage="E1", control_name="signal_failure_exit"), "E1 enables alpha failure exit")
    _check(scap_control_enabled(exit_stage="E2", control_name="post_entry_failure_exit"), "E2 enables post-entry failure exit")
    _check(not scap_control_enabled(exit_stage="E2", control_name="loss_containment_exit"), "E2 does not silently enable a loss stop")
    _check(scap_control_enabled(exit_stage="E3", control_name="loss_containment_exit"), "E3 enables the registered loss stop")
    _check(scap_control_enabled(exit_stage="E4", control_name="profit_giveback_exit"), "E4 enables right-tail profit protection")
    _check(
        scap_loss_containment_exit(exit_stage="E3", is_held=True, holding_days=5, net_unrealized_return=-0.13, loss_stop=-0.12),
        "E3 exits a mature position beyond the loss boundary",
    )
    _check(
        not scap_loss_containment_exit(exit_stage="E3", is_held=True, holding_days=2, net_unrealized_return=-0.13, loss_stop=-0.12),
        "grace period prevents an immediate loss exit",
    )
    _check(
        not scap_loss_containment_exit(exit_stage="E0", is_held=True, holding_days=5, net_unrealized_return=-0.20, loss_stop=-0.12),
        "E0 remains a true no-loss-stop baseline",
    )
    try:
        scap_exit_stage_level("E9")
    except ValueError:
        print("[PASS] invalid exit stages fail closed")
    else:
        raise AssertionError("invalid exit stage did not fail closed")


if __name__ == "__main__":
    main()
