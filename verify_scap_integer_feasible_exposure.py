"""Verify existing holdings consume slots and buy cash is deducted cumulatively."""
from functions.decision_council.scap_v2_contracts import ActionProposal
from functions.decision_council.scap_v3_lean import (
    _constructive_entry_exposure_bounds,
)


def proposal(symbol: str, cash: float, exposure: float) -> ActionProposal:
    return ActionProposal(
        proposal_id=f"d|{symbol}|entry",
        decision_id="d",
        symbol=symbol,
        action_type="new_entry",
        source_module="test",
        requested_lots=1,
        baseline_action="hold_cash",
        horizon_sessions=20,
        expected_net_profit_amount=50.0,
        robust_net_profit_amount=40.0,
        downside_cvar_amount=100.0,
        exact_cost_amount=10.0,
        funding_cash_amount=cash,
        buy_cash_required_amount=cash,
        market_notional_amount=cash - 10.0,
        exposure_delta=exposure,
        authority_tier="A",
        unit_capital_robust_return=0.01,
    )


items = (
    proposal("new1", 4_000.0, 0.20),
    proposal("new2", 4_000.0, 0.20),
    proposal("new3", 4_000.0, 0.20),
)
signal, feasible = _constructive_entry_exposure_bounds(
    proposals=items,
    current_lots={"held1": 1, "held2": 1},
    current_exposure=0.40,
    max_positions=4,
    available_cash=7_500.0,
    cash_buffer=500.0,
    strategic_budget=0.90,
)
assert abs(signal - 0.80) < 1e-12  # only two remaining Web slots
assert abs(feasible - 0.60) < 1e-12  # only one 4,000 buy fits cumulative cash
print("[PASS] integer-feasible exposure deducts held slots and cumulative exact buy cash")
