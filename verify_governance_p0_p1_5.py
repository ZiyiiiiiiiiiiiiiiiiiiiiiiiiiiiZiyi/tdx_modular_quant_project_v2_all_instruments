# -*- coding: utf-8 -*-
"""Focused verification for the governance P0, P0.5, P1, and P1.5 corrections."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from functions.decision_council.account_state import (
    ExploratoryCorporateActionProcessor,
    LastKnownPriceLedger,
)
from functions.decision_council.accounting import build_exposure_snapshot
from functions.decision_council.contracts import DecisionContext, SafetyDecision
from functions.decision_council.policy import RulesBasedPresidentPolicy
from functions.execution.cost_model import estimate_trade_costs


def main():
    _verify_last_known_price_ledger()
    _verify_exploratory_corporate_actions()
    _verify_rank_buffer_minimum_hold_and_weekly_gate()
    _verify_safety_override()
    _verify_impact_proxy()
    print("Governance P0-P1.5 verification passed.")


def _verify_last_known_price_ledger():
    ledger = LastKnownPriceLedger()
    ledger.update(pd.DataFrame([{"symbol": "sh600000", "close_nominal": 10.0}]), as_of="2024-01-02")
    mark = ledger.mark("sh600000", as_of="2024-01-03")
    assert mark is not None
    assert mark.price == 10.0
    assert mark.stale_days == 1
    assert mark.valuation_source == "last_known_close"
    snapshot = build_exposure_snapshot(
        pd.DataFrame(
            [{"symbol": "sh600000", "shares": 100, "price": 10.0, "lock_days": 6, "stale_haircut_ratio": 0.1}]
        ),
        cash=1000.0,
        target_exposure=0.0,
    )
    assert snapshot["effective_liquidatable_haircut"] == 1000.0
    assert snapshot["liquidatable_nav"] == 1000.0
    print("[PASS] missing daily quote carries forward the last known nominal close")


def _verify_exploratory_corporate_actions():
    actions = pd.DataFrame(
        [
            {
                "symbol": "sh600000",
                "action_date": "2024-01-03",
                "action_type": "dividend",
                "cash_dividend": 0.5,
                "stock_dividend_ratio": 0.1,
            }
        ]
    )
    processor = ExploratoryCorporateActionProcessor(actions)
    positions = {"sh600000": SimpleNamespace(shares=100.0)}
    cash, summary = processor.apply(as_of="2024-01-03", positions=positions, cash=1000.0)
    assert cash == 1050.0
    assert positions["sh600000"].shares == 110.0
    assert summary["events"] == 1
    assert processor.audit_frame().iloc[0]["accounting_mode"] == "exploratory_action_date_fallback"
    print("[PASS] exploratory corporate-action fallback posts cash and stock dividends once")


def _verify_rank_buffer_minimum_hold_and_weekly_gate():
    candidates = _candidates()
    safety = _safety("normal", 1.0)
    policy = RulesBasedPresidentPolicy()
    ideal, orders, _ = policy.decide(
        DecisionContext(
            decision_id="buffer",
            decision_date=pd.Timestamp("2024-01-31"),
            candidates=candidates,
            current_weights={"sh600080": 0.20},
            holding_days={"sh600080": 6},
            pending_locked_symbols=frozenset(),
            safety=safety,
            top_n=2,
        )
    )
    assert "sh600080" in set(ideal["symbol"])
    assert not (orders.get("reason", pd.Series(dtype=object)) == "qualification_exit").any()

    _, hold_orders, _ = policy.decide(
        DecisionContext(
            decision_id="min_hold",
            decision_date=pd.Timestamp("2024-01-31"),
            candidates=candidates,
            current_weights={"sh600080": 0.20},
            holding_days={"sh600080": 1},
            pending_locked_symbols=frozenset(),
            safety=safety,
            top_n=1,
        )
    )
    assert "sh600080" not in set(hold_orders.loc[hold_orders["side"] == "sell", "symbol"])

    _, closed_orders, _ = policy.decide(
        DecisionContext(
            decision_id="not_meeting_day",
            decision_date=pd.Timestamp("2024-01-30"),
            candidates=candidates,
            current_weights={},
            holding_days={},
            pending_locked_symbols=frozenset(),
            safety=safety,
            allow_normal_rebalance=False,
        )
    )
    assert closed_orders.empty
    print("[PASS] rank buffer, true minimum holding period, and weekly normal-trading gate")


def _verify_safety_override():
    policy = RulesBasedPresidentPolicy()
    _, orders, diagnostics = policy.decide(
        DecisionContext(
            decision_id="safety_override",
            decision_date=pd.Timestamp("2024-01-30"),
            candidates=_candidates(),
            current_weights={"sh600080": 0.6},
            holding_days={"sh600080": 1},
            pending_locked_symbols=frozenset(),
            safety=_safety("crisis", 0.0),
            allow_normal_rebalance=False,
        )
    )
    assert (orders["reason"] == "safety_deleveraging").any()
    assert diagnostics["planned_safety_sell_weight"] == 0.6
    print("[PASS] daily safety deleveraging bypasses meeting and holding-period gates")


def _verify_impact_proxy():
    costed = estimate_trade_costs(
        pd.DataFrame(
            [{"side": "buy", "price": 10.0, "target_shares": 10_000, "market_amount": 1_000_000.0}]
        )
    )
    row = costed.iloc[0]
    assert row["participation_rate"] == 0.1
    assert row["market_impact_cost"] > 0.0
    assert "uncalibrated" in row["impact_model_version"]
    print("[PASS] execution ledger discloses square-root participation impact proxy")


def _candidates():
    return pd.DataFrame(
        [
            {"symbol": "sh600001", "alpha_score": 1.0, "alpha_percentile": 1.0, "candidate_rank": 1, "volatility_20": 0.02},
            {"symbol": "sh600002", "alpha_score": 0.9, "alpha_percentile": 0.9, "candidate_rank": 2, "volatility_20": 0.02},
            {"symbol": "sh600080", "alpha_score": 0.1, "alpha_percentile": 0.2, "candidate_rank": 80, "volatility_20": 0.02},
        ]
    )


def _safety(level, cap):
    return SafetyDecision(pd.Timestamp("2024-01-31"), level, cap, 0.0, 0.0, "sh510300", "strict")


if __name__ == "__main__":
    main()
