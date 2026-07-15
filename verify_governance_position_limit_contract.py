"""Verify that live positions, not just today's candidates, consume top-N slots."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.contracts import DecisionContext, SafetyDecision
from functions.decision_council.policy import RulesBasedPresidentPolicy
from functions.decision_council.runtime_integrity_audit import build_runtime_integrity_audit
from functions.decision_council.pending_orders import PendingOrderBook


def _candidate(symbol: str, rank: int) -> dict:
    return {
        "symbol": symbol,
        "candidate_rank": rank,
        "alpha_score": 1.0 - rank / 100.0,
        "alpha_percentile": 0.99,
        "volatility_20": 0.02,
        "primary_score": 1.0 - rank / 100.0,
        "entry_confirmed": True,
        "state_machine_role_pass": True,
        "cooldown_active": False,
        "exit_state": False,
        "alpha_collapse_exit": False,
        "position_state": "building",
        "target_weight": 0.2,
    }


def main() -> None:
    policy = RulesBasedPresidentPolicy(enable_safety_agent=False)
    context = DecisionContext(
        decision_id="gov_20240102",
        decision_date=pd.Timestamp("2024-01-02"),
        candidates=pd.DataFrame([_candidate("new", 1)]),
        current_weights={"old_a": 0.2, "old_b": 0.2, "old_c": 0.2},
        holding_days={"old_a": 10, "old_b": 10, "old_c": 10},
        pending_locked_symbols=frozenset(),
        safety=SafetyDecision(
            decision_date=pd.Timestamp("2024-01-02"),
            risk_level="normal",
            exposure_cap=1.0,
            benchmark_drawdown_5d=0.0,
            market_liquidity_stress_ratio=0.0,
            proxy_symbol=None,
            proxy_mode="test",
        ),
        turnover_budget=1.0,
        minimum_holding_days=5,
        top_n=3,
        entry_rank_limit=10,
        hold_rank_limit=10,
        allow_normal_rebalance=True,
        partial_adjustment_rate=1.0,
        catchup_buy_budget=0.0,
        catchup_allowed=False,
        transition_only=False,
        hard_qualification_symbols=frozenset(),
        covariance_matrix=None,
    )
    _, orders, _ = policy.decide(context)
    buys = orders[orders.get("side", pd.Series(dtype=str)).astype(str).eq("buy")]
    assert "new" not in set(buys.get("symbol", pd.Series(dtype=str)).astype(str))

    audit = build_runtime_integrity_audit(
        execution_ledger=pd.DataFrame(),
        account_audit=pd.DataFrame([{"reconciliation_error": 0.0}]),
        daily_result=pd.DataFrame({"holding_count": [1, 3, 4]}),
        max_positions=3,
    )
    row = audit[audit["check"].eq("position_limit_contract")].iloc[0]
    assert not bool(row["passed"]) and "violation_days=1" in str(row["detail"])

    book = PendingOrderBook()
    book.add_order(
        {
            "symbol": "new",
            "side": "buy",
            "target_shares": 100,
            "created_date": pd.Timestamp("2024-01-02"),
            "decision_id": "gov_20240102",
            "reason": "entry",
        }
    )
    changed = book.settle_day(
        pd.Timestamp("2024-01-03"),
        blocked_symbols={"new"},
        blocked_reasons={"new": "position_limit"},
    )
    assert changed.iloc[0]["status"] == "expired"
    assert changed.iloc[0]["block_reason"] == "position_limit"
    assert changed.iloc[0]["expired_reason"] == "position_limit"
    print("[PASS] governance hard position-limit contract")


if __name__ == "__main__":
    main()
