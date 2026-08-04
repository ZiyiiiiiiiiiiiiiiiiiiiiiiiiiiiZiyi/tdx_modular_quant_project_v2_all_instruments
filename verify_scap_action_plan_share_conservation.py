"""Regression checks for ActionPlan lots-to-execution share conservation."""
from __future__ import annotations

from types import SimpleNamespace

from functions.decision_council.execution_runtime import (
    authoritative_action_plan_buy_shares,
)
from functions.decision_council.retail_execution import adapt_retail_buy_order


def _runner(cash: float = 20_000.0):
    profile = {
        "min_cash_buffer": 1_000.0,
        "retail_single_position_cap": 0.80,
        "retail_target_exposure_tolerance": 0.30,
        "commission_rate": 0.0003,
        "minimum_commission": 5.0,
        "stamp_duty_rate": 0.0005,
        "slippage_rate": 0.0005,
        "transfer_fee_rate": 0.00001,
    }
    runner = SimpleNamespace(
        capital_profile=profile,
        cash=cash,
        capital_usage_mode="allow_cash",
        strategy_logic_version="mainline_v3_cabinet_native",
        exposure_rows=[{"target_exposure": 0.90, "nominal_exposure": 0.0}],
    )
    from functions.decision_council.retail_execution import retail_cash_required
    runner._retail_cash_required = lambda **kwargs: retail_cash_required(runner, **kwargs)
    return runner


def main() -> int:
    six = {
        "side": "buy",
        "symbol": "sz002872",
        "action_plan_selected": True,
        "action_plan_id": "plan-20260420",
        "planned_entry_lots": 6,
        "execution_date": "2026-04-21",
        "current_weight": 0.0,
    }
    fourteen = {**six, "symbol": "sz300152", "planned_entry_lots": 14}
    assert authoritative_action_plan_buy_shares(
        six,
        strategy_logic_version="mainline_v3_cabinet_native",
        minimum_buy_quantity=100,
    ) == 600.0
    assert authoritative_action_plan_buy_shares(
        fourteen,
        strategy_logic_version="mainline_v3_cabinet_native",
        minimum_buy_quantity=100,
    ) == 1400.0

    shares, action, reason = adapt_retail_buy_order(
        _runner(),
        order=six,
        strategy_target_notional=3_000.0,
        order_price=5.0,
        nominal_nav=20_000.0,
        reserved_cash=0.0,
        initial_shares=600.0,
    )
    assert shares == 600.0 and action == "action_plan_unchanged" and reason == ""

    shares, action, reason = adapt_retail_buy_order(
        _runner(cash=2_000.0),
        order=fourteen,
        strategy_target_notional=2_800.0,
        order_price=2.0,
        nominal_nav=20_000.0,
        reserved_cash=0.0,
        initial_shares=1400.0,
    )
    assert shares == 0.0 and action == "blocked"
    assert reason == "action_plan_cash_insufficient"

    broken = dict(six)
    broken.pop("planned_entry_lots")
    try:
        authoritative_action_plan_buy_shares(
            broken,
            strategy_logic_version="mainline_v3_cabinet_native",
            minimum_buy_quantity=100,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("selected ActionPlan buy without lots did not fail closed")
    print("[PASS] ActionPlan lots remain exact through execution authorization")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
