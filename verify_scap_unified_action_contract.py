"""Focused contract checks for the enabled SCAP special-version actions."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from config import BACKTEST_CAPITAL_PROFILES
from functions.decision_council.action_counterfactual_reward import (
    build_action_decisions,
)
from functions.decision_council.candidate_funnel_audit import (
    assert_scap_funnel_monotonic,
    classify_scap_registered_buys,
)
from functions.decision_council.decision_arbitration import (
    arbitrate_position_actions,
)
from functions.decision_council.policy import _order_reason


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


profile = BACKTEST_CAPITAL_PROFILES["small_capital_branch"]
check(profile["active_replacement_enabled"] is True, "active replacement is enabled")
check(profile["scap_loser_averaging_enabled"] is True, "loser averaging is enabled")
check(profile["scap_winner_pyramiding_enabled"] is True, "winner pyramiding is enabled")
check(profile["scap_exit_stage"] == "E4", "E2/E3/E4 cumulative trading rights are enabled through E4")
check(
    profile["scap_active_replacement_max_pairs_per_day"] == 1,
    "active replacement is bounded to one complete pair per day",
)

conflict = arbitrate_position_actions(
    {"exit": True, "loser_averaging": True, "winner_pyramiding": False}
)
check(conflict.selected_action == "exit", "exit wins over a conflicting add proposal")
check(
    conflict.vetoed_actions == ("loser_averaging",),
    "the losing module proposal remains auditable",
)

context = SimpleNamespace(
    current_weights={"loser": 0.20, "winner": 0.20},
    hard_qualification_symbols=frozenset(),
)
loser_reason = _order_reason(
    "loser",
    0.05,
    pd.Series({"add_decision_type": "loser_averaging"}),
    context,
)
winner_reason = _order_reason(
    "winner",
    0.05,
    pd.Series({"add_decision_type": "winner_pyramiding"}),
    context,
)
check(loser_reason == "loser_averaging_buy", "loser averaging has an independent order reason")
check(winner_reason == "winner_pyramiding_buy", "winner pyramiding has an independent order reason")

candidates = pd.DataFrame(
    {
        "symbol": ["loser"],
        "close_nominal": [10.0],
        "comparable_value_horizon_days": [20],
    }
)
orders = pd.DataFrame(
    {
        "symbol": ["loser"],
        "side": ["buy"],
        "reason": ["loser_averaging_buy"],
        "unified_action_selected": ["loser_averaging"],
        "unified_action_proposals": ["loser_averaging"],
        "unified_action_vetoed": [""],
        "unified_action_contract": ["unified_position_action_v1"],
    }
)
daily = pd.DataFrame({"symbol": ["loser"], "close_nominal": [10.0]})
decisions = build_action_decisions(
    date="2026-01-05",
    candidates=candidates,
    held_symbols={"loser"},
    orders=orders,
    daily=daily,
)
check(
    {row["action"] for row in decisions} == {"add"},
    "held-position buys are attributed as add rather than hold",
)
check(
    {row["action_module"] for row in decisions} == {"loser_averaging"},
    "counterfactual reward rows preserve the responsible action module",
)

mixed_buys = pd.DataFrame(
    {
        "side": ["buy", "buy", "buy"],
        "reason": [
            "normal_buy",
            "loser_averaging_buy",
            "replacement_opportunity_buy",
        ],
        "current_weight": [0.0, 0.20, 0.0],
    }
)
buy_counts = classify_scap_registered_buys(mixed_buys)
check(
    buy_counts
    == {
        "entry_buy_count": 1,
        "add_buy_count": 1,
        "replacement_buy_count": 1,
    },
    "entry, add and replacement buy scopes are counted independently",
)
assert_scap_funnel_monotonic(
    {
        "scap_raw_signal_count": 1,
        "scap_structural_feasible_count": 1,
        "scap_cash_feasible_count": 1,
        "scap_slot_feasible_count": 0,
        "scap_optimizer_selected_count": 0,
        "scap_registered_buy_count": 0,
        "scap_registered_add_buy_count": 1,
        "scap_registered_replacement_buy_count": 1,
    }
)
check(True, "add and replacement buys no longer corrupt the new-entry funnel")

print("[PASS] SCAP unified action contract verification completed")
