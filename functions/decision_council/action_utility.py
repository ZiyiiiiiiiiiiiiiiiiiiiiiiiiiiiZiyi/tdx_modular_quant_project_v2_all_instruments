"""Comparable monetary utility for SCAP actions.

Every soft action is measured against the same no-action terminal-wealth
baseline.  Scores and percentiles may be evidence, but they are never treated
as returns or multiplied directly by capital.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4

import pandas as pd

from functions.execution.cost_model import estimate_trade_costs


ACTION_UTILITY_CONTRACT_VERSION = "unified_action_utility_v3"


@dataclass(frozen=True)
class ActionUtility:
    proposal_id: str
    action_type: str
    baseline_action: str
    horizon_days: int
    notional: float
    expected_return_point: float
    expected_return_lcb: float
    decision_expected_return: float
    decision_return_basis: str
    baseline_terminal_wealth: float
    action_terminal_wealth: float
    estimated_total_cost: float
    risk_penalty_amount: float
    opportunity_cost_amount: float
    incremental_terminal_wealth: float
    calibration_state: str
    contract_version: str = ACTION_UTILITY_CONTRACT_VERSION

    def as_dict(self) -> dict:
        return asdict(self)


def round_trip_cost_amount(
    *,
    symbol: str,
    price: float,
    shares: float,
    trade_date=None,
) -> float:
    """Estimate buy plus later sell costs once for the proposed quantity."""
    if float(price) <= 0.0 or float(shares) <= 0.0:
        return 0.0
    rows = []
    for side in ("buy", "sell"):
        rows.append(
            {
                "symbol": str(symbol),
                "trade_date": trade_date,
                "side": side,
                "price": float(price),
                "target_shares": float(shares),
            }
        )
    costs = estimate_trade_costs(pd.DataFrame(rows))
    return float(pd.to_numeric(costs["total_cost"], errors="coerce").fillna(0.0).sum())


def build_incremental_action_utility(
    *,
    action_type: str,
    notional: float,
    expected_return_point,
    expected_return_lcb,
    estimated_total_cost: float,
    horizon_days: int,
    baseline_action: str = "hold_cash",
    baseline_expected_return: float = 0.0,
    risk_penalty_amount: float = 0.0,
    opportunity_cost_amount: float = 0.0,
    calibration_state: str = "calibrated",
    decision_return_basis: str = "lcb",
    proposal_id: str | None = None,
) -> ActionUtility:
    """Return incremental terminal wealth relative to one common baseline."""
    notional_value = max(float(notional or 0.0), 0.0)
    point = _number_or_nan(expected_return_point)
    lcb = _number_or_nan(expected_return_lcb)
    reward_basis = str(decision_return_basis or "lcb").strip().lower()
    if reward_basis not in {
        "lcb",
        "point",
        "shrunk_point_minus_0.50_cluster_se",
    }:
        raise ValueError(f"Unsupported decision return basis: {decision_return_basis!r}")
    state = str(calibration_state or "insufficient")
    if pd.isna(point) or pd.isna(lcb):
        point = 0.0 if pd.isna(point) else point
        lcb = 0.0
        state = "insufficient"
    if reward_basis == "point":
        decision_return = point
    elif reward_basis == "shrunk_point_minus_0.50_cluster_se":
        decision_return = point - 0.50 * max(point - lcb, 0.0)
    else:
        decision_return = lcb
    baseline_terminal = notional_value * (1.0 + float(baseline_expected_return))
    action_terminal = notional_value * (1.0 + float(decision_return))
    incremental = (
        action_terminal
        - baseline_terminal
        - max(float(estimated_total_cost or 0.0), 0.0)
        - max(float(risk_penalty_amount or 0.0), 0.0)
        - max(float(opportunity_cost_amount or 0.0), 0.0)
    )
    if state != "calibrated":
        incremental = min(incremental, 0.0)
    return ActionUtility(
        proposal_id=str(proposal_id or uuid4()),
        action_type=str(action_type),
        baseline_action=str(baseline_action),
        horizon_days=max(int(horizon_days), 1),
        notional=notional_value,
        expected_return_point=float(point),
        expected_return_lcb=float(lcb),
        decision_expected_return=float(decision_return),
        decision_return_basis=reward_basis,
        baseline_terminal_wealth=float(baseline_terminal),
        action_terminal_wealth=float(action_terminal),
        estimated_total_cost=max(float(estimated_total_cost or 0.0), 0.0),
        risk_penalty_amount=max(float(risk_penalty_amount or 0.0), 0.0),
        opportunity_cost_amount=max(float(opportunity_cost_amount or 0.0), 0.0),
        incremental_terminal_wealth=float(incremental),
        calibration_state=state,
    )


def _number_or_nan(value) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) else float("nan")
