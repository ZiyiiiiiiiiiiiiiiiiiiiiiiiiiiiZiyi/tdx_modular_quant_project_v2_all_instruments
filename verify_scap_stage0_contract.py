"""Stage-0 product contract checks for the SCAP-V1 research mode."""
from __future__ import annotations

import argparse

from config import get_backtest_capital_profile
from functions.decision_council.runner import _normalize_governance_control_mode as normalize_runner
from functions.decision_council.runner_summary import _normalize_governance_control_mode as normalize_summary
from main import _governance_control_mode_from_args
from run_governance_experiments import _normalize_governance_control_mode as normalize_experiment


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    expected = "aggressive_profit"
    _check(
        _governance_control_mode_from_args(
            argparse.Namespace(governance_control_mode="scap")
        ) == expected,
        "main CLI accepts SCAP alias",
    )
    _check(normalize_runner("aggressive_profit") == expected, "runner accepts isolated control mode")
    _check(normalize_summary("profit") == expected, "summary accepts profit alias")
    _check(normalize_experiment("scap") == expected, "experiment launcher accepts SCAP alias")
    profile = get_backtest_capital_profile("small_capital_branch")
    _check(
        profile["special_strategy_version"] == "small_capital_aggressive_profit_v1",
        "capital profile exposes SCAP version identity",
    )
    _check(
        profile["objective_metric"] == "terminal_net_profit_after_cost",
        "capital profile exposes the net-profit objective",
    )
    _check(profile["active_replacement_enabled"] is True, "authorized active replacement is explicit")
    _check(profile["scap_loser_averaging_enabled"] is True, "authorized loser averaging is explicit")
    _check(profile["scap_winner_pyramiding_enabled"] is True, "authorized winner pyramiding is explicit")
    _check(profile["scap_exit_stage"] == "E4", "current cumulative exit experiment is E4")


if __name__ == "__main__":
    main()
