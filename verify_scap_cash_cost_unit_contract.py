"""Verify SCAP market notional, buy cash and sell release use distinct units."""
import pandas as pd

from functions.decision_council.action_utility import (
    buy_cash_required_amount,
    sell_cash_released_amount,
    single_side_cost_amount,
)
from functions.decision_council.scap_v2_contracts import ActionProposal


kwargs = {
    "symbol": "600001",
    "price": 10.0,
    "shares": 500.0,
    "trade_date": pd.Timestamp("2025-01-02"),
    "cost_profile": {
        "commission_rate": 0.0003,
        "minimum_commission": 5.0,
        "stamp_duty_rate": 0.0005,
        "slippage_rate": 0.0005,
        "transfer_fee_rate": 0.00001,
    },
}
market_notional = kwargs["price"] * kwargs["shares"]
buy_cost = single_side_cost_amount(side="buy", **kwargs)
sell_cost = single_side_cost_amount(side="sell", **kwargs)
buy_cash = buy_cash_required_amount(**kwargs)
sell_release = sell_cash_released_amount(**kwargs)
assert abs(buy_cash - (market_notional + buy_cost)) < 1e-12
assert abs(sell_release - (market_notional - sell_cost)) < 1e-12
assert sell_cost > buy_cost  # sell stamp duty is quantity-scaled

proposal = ActionProposal(
    proposal_id="d|600001|exit",
    decision_id="d",
    symbol="600001",
    action_type="hard_exit",
    source_module="test",
    requested_lots=5,
    baseline_action="hold_position",
    horizon_sessions=20,
    expected_net_profit_amount=0.0,
    robust_net_profit_amount=0.0,
    downside_cvar_amount=0.0,
    exact_cost_amount=sell_cost,
    funding_cash_amount=0.0,
    cash_release_amount=sell_release,
    market_notional_amount=market_notional,
    buy_cash_required_amount=0.0,
    sell_cash_released_amount=sell_release,
    exposure_delta=-0.25,
)
assert proposal.market_notional_amount == 5000.0
assert proposal.cash_release_amount == proposal.sell_cash_released_amount
print("[PASS] market notional, buy cash, sell release and quantity-scaled costs are distinct")
