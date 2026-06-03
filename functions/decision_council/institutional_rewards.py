"""Institution-specific reward contracts for governance attribution."""
from __future__ import annotations

import numpy as np
import pandas as pd


def alpha_rank_ic_reward(proposals: pd.DataFrame, realized: pd.DataFrame) -> pd.DataFrame:
    """Score alpha voters only on liquidity-screened cross-sectional ranking skill."""
    required_proposals = {"date", "model_name", "symbol", "predicted_return_5d"}
    required_realized = {"date", "symbol", "future_ret_5", "liquidity_eligible"}
    _require(proposals, required_proposals, "alpha proposals")
    _require(realized, required_realized, "alpha realized labels")
    merged = proposals.merge(realized[list(required_realized)], on=["date", "symbol"], how="inner")
    merged = merged[merged["liquidity_eligible"].fillna(False)].copy()
    rows = []
    for (date, model_name), group in merged.groupby(["date", "model_name"]):
        score = pd.to_numeric(group["predicted_return_5d"], errors="coerce")
        outcome = pd.to_numeric(group["future_ret_5"], errors="coerce")
        rank_ic = score.corr(outcome, method="spearman") if len(group) >= 5 else np.nan
        rows.append({"date": date, "model_name": model_name, "rank_ic_oos": rank_ic, "eligible_symbols": len(group)})
    return pd.DataFrame(rows)


def portfolio_policy_reward(
    *,
    liquidatable_nav_return_5d: float,
    realized_max_drawdown_5d: float,
    drawdown_budget: float = 0.05,
    drawdown_penalty: float = 3.0,
) -> float:
    """Reward the president on portfolio outcome without deducting costs twice."""
    return float(liquidatable_nav_return_5d) - float(drawdown_penalty) * max(
        float(realized_max_drawdown_5d) - float(drawdown_budget),
        0.0,
    )


def safety_agent_reward(
    *,
    outcome: int,
    probability: float,
    false_positive_cost: float,
    false_negative_cost: float,
) -> float:
    """Combine calibration quality with the explicit asymmetric safety cost matrix."""
    y = int(outcome)
    p = min(max(float(probability), 0.0), 1.0)
    predicted = p >= 0.20
    conditional_cost = 0.0
    if predicted and not y:
        conditional_cost = float(false_positive_cost)
    elif not predicted and y:
        conditional_cost = float(false_negative_cost)
    return -((p - y) ** 2) - conditional_cost


def execution_agent_reward(execution_rows: pd.DataFrame) -> float:
    """Penalize fees, slippage, impact, and opportunity cost at the execution layer."""
    if execution_rows.empty:
        return 0.0
    columns = ["commission_cost", "stamp_duty_cost", "transfer_fee_cost", "slippage_cost", "market_impact_cost", "opportunity_cost"]
    cost = sum(_numeric_column(execution_rows, column).sum() for column in columns)
    notional = _numeric_column(execution_rows, "trade_notional").sum()
    return -float(cost) / max(float(notional), 1e-12)


def _require(frame, required, name):
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} missing columns: {missing}")


def _numeric_column(frame, column):
    return pd.to_numeric(frame.get(column, pd.Series(0.0, index=frame.index)), errors="coerce").fillna(0.0)
