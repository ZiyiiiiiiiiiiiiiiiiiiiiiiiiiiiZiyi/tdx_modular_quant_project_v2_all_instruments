"""Regression checks for monthly portfolio cadence and staged buy persistence."""
from __future__ import annotations

import pandas as pd

from config import get_backtest_capital_profile
from functions.decision_council.pending_orders import PendingOrderBook
from functions.decision_council.capital_scaling import resolve_position_capacity
from functions.decision_council.runner import (
    GovernanceBacktestRunner,
    build_portfolio_rebalance_dates,
)


def _monthly_order() -> dict:
    return {
        "decision_id": "gov_20250127",
        "symbol": "sh600000",
        "side": "buy",
        "reason": "monthly_normal_buy",
        "priority": 10,
        "created_date": pd.Timestamp("2025-01-27"),
        "target_shares": 100.0,
        "order_execution_policy": "monthly_plan_window",
        "maximum_age_sessions": 5,
        "action_plan_id": "gov_20250127|action_plan",
        "action_plan_selected": True,
        "planned_entry_lots": 1,
    }


def main() -> int:
    dates = pd.to_datetime(
        ["2025-01-02", "2025-01-27", "2025-02-05", "2025-02-28", "2025-03-03"]
    )
    monthly = build_portfolio_rebalance_dates(dates, "monthly")
    assert monthly == {
        pd.Timestamp("2025-01-27"),
        pd.Timestamp("2025-02-28"),
        pd.Timestamp("2025-03-03"),
    }
    weekly = build_portfolio_rebalance_dates(dates, "weekly")
    assert pd.Timestamp("2025-01-27") in weekly
    assert monthly != weekly
    full_calendar = pd.to_datetime(
        ["2025-01-27", "2025-02-05", "2025-02-06", "2025-02-28"]
    )
    full_monthly = build_portfolio_rebalance_dates(full_calendar, "monthly")
    truncated_window = {date for date in full_monthly if date <= pd.Timestamp("2025-02-06")}
    assert pd.Timestamp("2025-02-06") not in truncated_window
    assert truncated_window == {pd.Timestamp("2025-01-27")}

    book = PendingOrderBook()
    order_id = book.add_order(_monthly_order())
    book.settle_day(
        pd.Timestamp("2025-02-05"),
        blocked_symbols={"sh600000"},
        blocked_reasons={"sh600000": "monthly_plan_deployment_limit"},
    )
    row = book.orders.loc[book.orders["order_id"].eq(order_id)].iloc[0]
    assert row["status"] == "pending"
    book.settle_day(
        pd.Timestamp("2025-02-06"),
        fills={order_id: {"shares": 100.0, "fill_id": "fill-1"}},
    )
    row = book.orders.loc[book.orders["order_id"].eq(order_id)].iloc[0]
    assert row["status"] == "filled"
    assert float(row["remaining_shares"]) == 0.0

    expired = PendingOrderBook()
    expired_id = expired.add_order(_monthly_order())
    expired.settle_day(
        pd.Timestamp("2025-02-10"),
        blocked_symbols={"sh600000"},
        blocked_reasons={"sh600000": "monthly_plan_signal_expired"},
    )
    row = expired.orders.loc[expired.orders["order_id"].eq(expired_id)].iloc[0]
    assert row["status"] == "expired"

    profile = get_backtest_capital_profile("small_capital_lean")
    runner = GovernanceBacktestRunner.__new__(GovernanceBacktestRunner)
    runner.governance_control_mode = "aggressive_lean"
    runner.capital_profile = profile
    runner.enable_market_regime_policy = False
    runner.market_regime_policy = None
    runner._current_regime = "bear"
    date = pd.Timestamp("2025-02-05")
    runner._regime_diagnostics_cache = {date: {"regime_input_valid": False}}
    assert runner._scap_regime_es_budget_multiplier(date) == 1.0

    capacity = resolve_position_capacity(
        capital_profile=profile,
        nav_amount=20_000.0,
        cash_amount=20_000.0,
        risk_exposure_ceiling=0.90,
        current_exposure=0.0,
        current_symbols=(),
        candidates=pd.DataFrame(
            [
                {
                    "symbol": "sz000001",
                    "close_nominal": 5.0,
                    "mainline_v3_one_lot_cash_required": 505.0,
                    "comparable_alpha_lcb": 0.001,
                },
                {
                    "symbol": "sh600000",
                    "close_nominal": 20.0,
                    "mainline_v3_one_lot_cash_required": 2005.0,
                    "comparable_alpha_lcb": 0.05,
                },
            ]
        ),
    )
    assert capacity.lot_cash_position_cap == 2
    assert capacity.cost_feasible_position_cap == 1
    assert capacity.economic_position_cap == 1

    print("[PASS] monthly cadence, staged pending buys, neutral invalid regime, and cost-feasible K")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
