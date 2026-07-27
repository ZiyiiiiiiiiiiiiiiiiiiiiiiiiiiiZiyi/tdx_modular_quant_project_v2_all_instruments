"""Focused verification for SCAP weak-point audit remediation."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.mainline_v3 import _pre_slot_qualified_mask
from functions.decision_council.position_lifecycle import _prioritized_exit_reason
from functions.decision_council.runner import _scap_entry_stage_counts


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    qualification = _pre_slot_qualified_mask(
        eligible=pd.Series([True, True, True]),
        is_held=pd.Series([False, False, True]),
        score=pd.Series([0.20, -0.01, 0.80]),
        use_scap_candidate_utility=True,
    )
    _check(
        qualification.tolist() == [True, False, False],
        "pre-slot SCAP qualification excludes non-positive utility and held rows",
    )

    full_slots = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "mainline_v3_pre_slot_qualified": [True, True, False],
            "entry_confirmed": [False, False, False],
            "state_machine_role_pass": [True, True, True],
        }
    )
    counts = _scap_entry_stage_counts(full_slots)
    _check(
        counts["pre_slot_qualified_entry_count"] == 2,
        "qualified signals survive a zero-remaining-slot condition",
    )
    _check(
        counts["optimizer_selected_entry_count"] == 0,
        "optimizer selection remains zero when no slot can be allocated",
    )

    allocated = full_slots.copy()
    allocated.loc[0, "entry_confirmed"] = True
    counts = _scap_entry_stage_counts(allocated)
    _check(
        counts["pre_slot_qualified_entry_count"] == 2
        and counts["optimizer_selected_entry_count"] == 1,
        "signal qualification and optimizer allocation are independently counted",
    )

    paper_reason = _prioritized_exit_reason(
        hard_stop=False,
        profit_giveback=False,
        peak_decay_exit=False,
        loss_containment=True,
        post_entry_failure=False,
        downtrend_exit=False,
        stale_exit=False,
        signal_failure=False,
    )
    _check(
        paper_reason == "loss_containment_exit",
        "counterfactual loss containment produces an explicit paper exit reason",
    )
    priority_reason = _prioritized_exit_reason(
        hard_stop=False,
        profit_giveback=True,
        peak_decay_exit=False,
        loss_containment=True,
        post_entry_failure=True,
        downtrend_exit=False,
        stale_exit=False,
        signal_failure=False,
    )
    _check(
        priority_reason == "profit_giveback_exit",
        "paper exit reason preserves the registered reason priority",
    )


if __name__ == "__main__":
    main()
