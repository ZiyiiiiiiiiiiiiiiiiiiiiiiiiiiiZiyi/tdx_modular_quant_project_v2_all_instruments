"""Exhaustive SCAP stage/reason/liquidation contract checks."""
from itertools import product

from functions.decision_council.exit_reason_contract import (
    canonical_exit_reason,
    is_full_liquidation_reason,
)
from functions.decision_council.position_lifecycle import _prioritized_exit_reason
from functions.decision_council.small_capital_aggressive import scap_control_enabled


controls = (
    "signal_failure_exit",
    "stale_exit",
    "post_entry_failure_exit",
    "loss_containment_exit",
    "profit_giveback_exit",
    "hard_stop_exit",
)
expected_minimum = (1, 2, 2, 3, 4, 4)
for stage_level, stage in enumerate(("E0", "E1", "E2", "E3", "E4")):
    for control, minimum in zip(controls, expected_minimum):
        assert scap_control_enabled(exit_stage=stage, control_name=control) is (
            stage_level >= minimum
        )

try:
    scap_control_enabled(exit_stage="E4", control_name="typo_exit")
except ValueError:
    pass
else:
    raise AssertionError("unknown SCAP controls must fail closed")

flags = {
    "hard_stop": True,
    "profit_giveback": True,
    "peak_decay_exit": False,
    "loss_containment": True,
    "post_entry_failure": True,
    "downtrend_exit": True,
    "stale_exit": True,
    "signal_failure": True,
}
for stage in ("E0", "E1", "E2", "E3", "E4"):
    reason = _prioritized_exit_reason(
        **flags,
        control_enabled=lambda name, stage=stage: scap_control_enabled(
            exit_stage=stage, control_name=name
        ),
    )
    assert reason == {
        "E0": "",
        "E1": "signal_failure_exit",
        "E2": "post_entry_failure_exit",
        "E3": "loss_containment_exit",
        "E4": "profit_hard_stop_exit",
    }[stage]

# All 2^8 signal combinations must return only an authorized reason.
for stage in ("E0", "E1", "E2", "E3", "E4"):
    for values in product((False, True), repeat=len(flags)):
        reason = _prioritized_exit_reason(
            **dict(zip(flags, values)),
            control_enabled=lambda name, stage=stage: scap_control_enabled(
                exit_stage=stage, control_name=name
            ),
        )
        if reason:
            assert is_full_liquidation_reason(reason)

assert canonical_exit_reason("hard_stop_exit") == "profit_hard_stop_exit"
for reason in (
    "profit_hard_stop_exit",
    "loss_containment_exit",
    "signal_failure_exit",
    "stale_time_exit",
):
    assert is_full_liquidation_reason(reason)

print("[PASS] SCAP exit authorization, reason, and liquidation contract")
