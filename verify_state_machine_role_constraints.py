"""Verify state-machine role constraints block near-relative-only buys.

Run:
& "C:\\Users\\Ziyi Wang\\.conda\\envs\\stock_ai\\python.exe" verify_state_machine_role_constraints.py
"""
from __future__ import annotations

import sys
import inspect

import pandas as pd

from functions.decision_council import runner
from functions.decision_council.contracts import DecisionContext, SafetyDecision
from functions.decision_council.policy import RulesBasedPresidentPolicy


def _candidate(symbol: str, rank: int, role_pass: bool, reason: str) -> dict:
    score = 1.0 - rank * 0.01
    return {
        "symbol": symbol,
        "instrument_type": "stock",
        "alpha_score": score,
        "alpha_percentile": score,
        "primary_score": score,
        "volatility_20": 0.02,
        "candidate_rank": rank,
        "entry_confirmed": True,
        "cooldown_active": False,
        "exit_state": False,
        "position_state": "building",
        "entry_size_tier": "starter_1_lot",
        "add_allowed": False,
        "alpha_collapse_exit": False,
        "state_machine_role_pass": role_pass,
        "state_machine_role_block_reason": reason,
        "alpha_active_model_count": 3 if role_pass else 2,
        "alpha_active_module_count": 3 if role_pass else 1,
        "alpha_active_family_count": 3 if role_pass else 1,
        "alpha_max_active_module_share": 0.45 if role_pass else 1.0,
        "alpha_range_grid_vote_share": 0.20 if role_pass else 1.0,
        "entry_alpha_vote_count": 2,
        "timing_filter_vote_count": 1 if role_pass else 0,
        "risk_override_vote_count": 1 if role_pass else 0,
        "liquidity_guard_vote_count": 0,
    }


def main() -> int:
    candidates = pd.DataFrame(
        [
            _candidate("sh600001", 1, False, "active_modules_below_min|range_grid_vote_share_above_cap"),
            _candidate("sh600002", 2, True, "passed"),
        ]
    )
    context = DecisionContext(
        decision_id="verify_state_machine_role_constraints",
        decision_date=pd.Timestamp("2024-01-02"),
        candidates=candidates,
        current_weights={},
        holding_days={},
        pending_locked_symbols=frozenset(),
        safety=SafetyDecision(
            decision_date=pd.Timestamp("2024-01-02"),
            risk_level="normal",
            exposure_cap=0.20,
            benchmark_drawdown_5d=0.0,
            market_liquidity_stress_ratio=0.0,
            proxy_symbol=None,
            proxy_mode="verify",
        ),
        turnover_budget=0.20,
        minimum_holding_days=1,
        top_n=2,
        entry_rank_limit=2,
        hold_rank_limit=2,
        allow_normal_rebalance=True,
        partial_adjustment_rate=1.0,
    )
    _, orders, diagnostics = RulesBasedPresidentPolicy().decide(context)
    failures = []
    bought = set(orders.loc[orders.get("side", pd.Series(dtype=str)).astype(str).eq("buy"), "symbol"].astype(str))
    if "sh600001" in bought:
        failures.append("near-relative-only candidate produced a buy order")
    if "sh600002" not in bought:
        failures.append("role-diversified candidate did not produce a buy order")
    if diagnostics.get("target_exposure", 0.0) <= 0.0:
        failures.append("target exposure should be positive for the passing candidate")
    source = inspect.getsource(runner.GovernanceBacktestRunner._augment_force_deploy_diversify_orders)
    if "_state_machine_entry_mask" not in source:
        failures.append("force_deploy supplemental buys do not use state-machine role mask")
    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        print(orders.to_string(index=False) if not orders.empty else "orders empty")
        return 1
    print("[PASS] near-relative-only candidate was blocked")
    print("[PASS] role-diversified candidate can buy")
    print("[PASS] force_deploy supplemental buys use the same role gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
