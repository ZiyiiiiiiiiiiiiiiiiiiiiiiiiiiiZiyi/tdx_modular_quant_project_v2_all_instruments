# -*- coding: utf-8 -*-
"""Synthetic boundary tests for governance lock, safety, and allocation behavior."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.accounting import build_exposure_snapshot
from functions.decision_council.allocation import allocate_constrained_inverse_vol
from functions.decision_council.contracts import DecisionContext, SafetyDecision
from functions.decision_council.pending_orders import PendingOrderBook
from functions.decision_council.policy import RulesBasedPresidentPolicy
from functions.decision_council.preflight import validate_safety_proxy
from functions.decision_council.safety import RuleBasedSafetyAgent


def main():
    _verify_long_lock_and_double_nav()
    _verify_unresolved_safety_exposure()
    _verify_degraded_proxy_and_impact_alert()
    _verify_recursive_allocation_and_volatility_scale()
    print("Decision council stress verification passed.")


def _verify_long_lock_and_double_nav():
    book = PendingOrderBook()
    book.add_order(
        {
            "decision_id": "stress_lock",
            "symbol": "sh600000",
            "side": "sell",
            "reason": "safety_deleveraging",
            "priority": 0,
            "created_date": "2024-01-02",
            "target_shares": 100,
        }
    )
    for trade_date in pd.bdate_range("2024-01-03", periods=11):
        book.settle_day(trade_date, blocked_symbols=["sh600000"])
    assert book.orders.iloc[0]["status"] == "pending_locked"
    assert len(book.lock_alerts()) == 1
    snapshot = build_exposure_snapshot(
        pd.DataFrame([{"symbol": "sh600000", "shares": 100, "price": 10.0, "lock_days": 11}]),
        cash=1000.0,
        target_exposure=0.0,
    )
    assert snapshot["nominal_nav"] == 2000.0
    assert snapshot["liquidatable_nav"] == 1000.0
    print("[PASS] continuous lock, alert, and double NAV haircut")


def _verify_unresolved_safety_exposure():
    candidates = pd.DataFrame(
        [
            {"symbol": "sh600000", "instrument_type": "stock", "alpha_score": 0.9, "alpha_percentile": 1.0, "volatility_20": 0.02},
            {"symbol": "sz000001", "instrument_type": "stock", "alpha_score": 0.1, "alpha_percentile": 0.1, "volatility_20": 0.02},
        ]
    )
    context = DecisionContext(
        decision_id="stress_safety",
        decision_date=pd.Timestamp("2024-01-31"),
        candidates=candidates,
        current_weights={"sh600000": 0.6, "sz000001": 0.3},
        holding_days={"sh600000": 10, "sz000001": 10},
        pending_locked_symbols=frozenset({"sh600000"}),
        safety=SafetyDecision(pd.Timestamp("2024-01-31"), "crisis", 0.0, 0.05, 0.5, "sh510300", "strict"),
    )
    ideal, orders, diagnostics = RulesBasedPresidentPolicy().decide(context)
    assert "sh600000" in set(ideal["symbol"])
    assert "sh600000" not in set(orders["symbol"])
    assert diagnostics["unresolved_safety_exposure"] >= 0.6 - 1e-12
    _, without_safety_orders, without_safety = RulesBasedPresidentPolicy(enable_safety_agent=False).decide(context)
    assert not (without_safety_orders.get("reason", pd.Series(dtype=object)) == "safety_deleveraging").any()
    assert without_safety["safety_agent_enabled"] is False
    print("[PASS] locked assets remain nominal risk and safety shortfall is disclosed")


def _verify_degraded_proxy_and_impact_alert():
    rows = []
    for date in pd.bdate_range("2024-01-01", periods=25):
        rows.append({"date": date, "symbol": "sh600000", "amount": 100.0, "is_trading": True})
    features = pd.DataFrame(rows)
    dependency = validate_safety_proxy(features, mode="degraded_backtest")
    assert dependency["degraded"] is True
    agent = RuleBasedSafetyAgent(None, proxy_mode="degraded_backtest")
    assert agent.safety_sell_flow_impact(3.0, 100.0) > 0.02
    print("[PASS] degraded safety proxy and market-impact alert threshold")


def _verify_recursive_allocation_and_volatility_scale():
    candidates = pd.DataFrame(
        [
            {"symbol": f"sh6000{index:02d}", "instrument_type": "stock", "volatility_20": 0.01 + index * 0.001}
            for index in range(8)
        ]
    )
    allocated, diagnostics = allocate_constrained_inverse_vol(candidates, exposure_cap=1.0)
    assert float(allocated["target_weight"].max()) <= 0.2 + 1e-12
    assert float(allocated.groupby("prototype_sector")["target_weight"].sum().max()) <= 0.4 + 1e-12
    assert diagnostics["volatility_scale_factor"] <= 1.0
    assert diagnostics["constraint_cash_reserve"] >= 0.6 - 1e-12
    _, uncapped_sector = allocate_constrained_inverse_vol(candidates, exposure_cap=1.0, max_sector_weight=1.0)
    assert uncapped_sector["constraint_cash_reserve"] < diagnostics["constraint_cash_reserve"]
    print("[PASS] recursive allocation caps and terminal cash reserve")


if __name__ == "__main__":
    main()
