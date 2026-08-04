"""SCAP market-state authority and winner-add research-gate checks."""
from __future__ import annotations

import pandas as pd

from config import get_backtest_capital_profile
from functions.decision_council.runner import (
    GovernanceBacktestRunner,
    scap_winner_add_trading_authorized,
)


def main() -> int:
    profile = get_backtest_capital_profile("small_capital_lean")
    assert profile["scap_winner_pyramiding_enabled"] is True
    assert profile["scap_winner_pyramiding_trading_authorized"] is False
    assert not scap_winner_add_trading_authorized(profile)
    assert scap_winner_add_trading_authorized(
        {
            "scap_winner_pyramiding_enabled": True,
            "scap_winner_pyramiding_trading_authorized": True,
        }
    )

    runner = GovernanceBacktestRunner.__new__(GovernanceBacktestRunner)
    runner.governance_control_mode = "aggressive_lean"
    runner.capital_profile = profile
    runner.enable_market_regime_policy = True
    runner.market_regime_policy = object()
    date = pd.Timestamp("2026-01-14")
    runner._regime_diagnostics_cache = {date: {"regime_input_valid": True}}
    observed = {}
    for regime, expected in {
        "bull": 1.05,
        "neutral": 1.00,
        "weak": 0.85,
        "bear": 0.75,
        "crisis": 0.70,
    }.items():
        runner._current_regime = regime
        observed[regime] = runner._scap_regime_es_budget_multiplier(date)
        assert abs(observed[regime] - expected) < 1e-12
    assert min(observed.values()) >= profile["scap_regime_es_multiplier_min"]
    assert max(observed.values()) <= profile["scap_regime_es_multiplier_max"]
    runner.market_regime_policy = None
    assert runner._scap_regime_es_budget_multiplier(date) == 1.0
    runner.market_regime_policy = object()
    runner._regime_diagnostics_cache[date] = {"regime_input_valid": False}
    assert runner._scap_regime_es_budget_multiplier(date) == 1.0
    print("[PASS] market state has bounded ES-only authority and winner add remains research-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
