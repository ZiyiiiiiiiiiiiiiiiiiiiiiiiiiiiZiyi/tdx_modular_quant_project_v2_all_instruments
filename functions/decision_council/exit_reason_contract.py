"""Canonical exit reasons and liquidation semantics."""
from __future__ import annotations


EXIT_REASON_SCHEMA_VERSION = "scap_exit_reason_contract_v1"

EXIT_REASON_PRIORITY = {
    "qualification_exit": 1,
    "profit_hard_stop_exit": 1,
    "loss_containment_exit": 1,
    "alpha_collapse_consensus": 2,
    "trend_break_exit": 3,
    "profit_giveback_exit": 3,
    "post_entry_failure_exit": 3,
    "signal_failure_exit": 3,
    "thesis_failure_exit": 3,
    "stale_time_exit": 3,
    "stale_time_reduce": 4,
    "volume_distribution_exit": 4,
    "replacement_opportunity_exit": 4,
}

EXIT_REASON_CONTROL = {
    "profit_hard_stop_exit": "hard_stop_exit",
    "profit_giveback_exit": "profit_giveback_exit",
    "loss_containment_exit": "loss_containment_exit",
    "post_entry_failure_exit": "post_entry_failure_exit",
    "signal_failure_exit": "signal_failure_exit",
    "thesis_failure_exit": "signal_failure_exit",
    "stale_time_exit": "stale_exit",
    "stale_time_reduce": "stale_exit",
}

FULL_LIQUIDATION_REASONS = frozenset(
    {
        "replacement_opportunity_exit",
        "qualification_exit",
        "profit_hard_stop_exit",
        "loss_containment_exit",
        "alpha_collapse_consensus",
        "profit_giveback_exit",
        "post_entry_failure_exit",
        "signal_failure_exit",
        "thesis_failure_exit",
        "stale_time_exit",
    }
)

_ALIASES = {
    # Historical lifecycle name for the profit-trailing hard stop.
    "hard_stop_exit": "profit_hard_stop_exit",
}


def canonical_exit_reason(value: str) -> str:
    reason = str(value or "").strip().lower()
    return _ALIASES.get(reason, reason)


def control_for_exit_reason(reason: str) -> str:
    return EXIT_REASON_CONTROL.get(canonical_exit_reason(reason), "")


def is_full_liquidation_reason(reason: str) -> bool:
    return canonical_exit_reason(reason) in FULL_LIQUIDATION_REASONS
