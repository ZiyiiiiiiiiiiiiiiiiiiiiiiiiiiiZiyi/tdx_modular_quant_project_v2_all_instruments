"""Comparable monetary utility for SCAP actions.

Every soft action is measured against the same no-action terminal-wealth
baseline.  Scores and percentiles may be evidence, but they are never treated
as returns or multiplied directly by capital.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4

import pandas as pd

from functions.execution.cost_model import cost_kwargs_from_profile, estimate_trade_costs


ACTION_UTILITY_CONTRACT_VERSION = "unified_action_utility_v4_single_net_value"


@dataclass(frozen=True)
class LifecycleCostEstimate:
    buy_cost_amount: float
    sell_cost_amount: float
    expected_add_cost_amount: float
    expected_replacement_cost_amount: float
    total_lifecycle_cost_amount: float
    round_trip_cost_ratio: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EconomicOrderAssessment:
    passed: bool
    reason: str
    market_notional_amount: float
    minimum_economic_order_amount: float
    lifecycle_cost_amount: float
    round_trip_cost_ratio: float
    lifecycle_cost_to_gross_profit_ratio: float
    robust_net_profit_amount: float
    robust_profit_hurdle_amount: float
    exception_used: bool = False
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


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
    cost_profile=None,
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
    costs = estimate_trade_costs(
        pd.DataFrame(rows),
        **cost_kwargs_from_profile(cost_profile),
    )
    return float(pd.to_numeric(costs["total_cost"], errors="coerce").fillna(0.0).sum())


def minimum_economic_order_amount(*, cost_profile=None) -> float:
    """Return the notional where the configured round trip meets its cost cap.

    This closed form is a capacity hint.  Real orders must still pass
    :func:`assess_economic_order`, which uses exact side-specific costs.
    """
    profile = dict(cost_profile or {})
    minimum_commission = max(
        float(
            profile.get(
                "scap_candidate_minimum_commission",
                profile.get("minimum_commission", 0.0),
            )
            or 0.0
        ),
        0.0,
    )
    maximum_ratio = max(
        float(profile.get("scap_max_round_trip_fixed_cost_ratio", 0.01) or 0.01),
        1e-12,
    )
    variable_rate = (
        2.0 * max(float(profile.get("slippage_rate", 0.0) or 0.0), 0.0)
        + max(float(profile.get("stamp_duty_rate", 0.0) or 0.0), 0.0)
        + 2.0 * max(float(profile.get("transfer_fee_rate", 0.0) or 0.0), 0.0)
    )
    residual = maximum_ratio - variable_rate
    if minimum_commission <= 0.0:
        return 0.0
    if residual <= 0.0:
        return float("inf")
    return float(2.0 * minimum_commission / residual)


def estimate_lifecycle_cost(
    *,
    symbol: str,
    price: float,
    shares: float,
    trade_date=None,
    cost_profile=None,
    expected_add_probability: float | None = None,
    expected_replacement_probability: float | None = None,
) -> LifecycleCostEstimate:
    """Estimate all expected cost legs known at the entry decision.

    The factual entry/exit round trip is always included. Optional future add
    and replacement legs are probability weighted and separately disclosed;
    defaults are explicit profile parameters rather than hidden constants.
    """
    profile = dict(cost_profile or {})
    notional = max(float(price), 0.0) * max(float(shares), 0.0)
    buy_cost = single_side_cost_amount(
        symbol=symbol,
        side="buy",
        price=price,
        shares=shares,
        trade_date=trade_date,
        cost_profile=profile,
    )
    sell_cost = single_side_cost_amount(
        symbol=symbol,
        side="sell",
        price=price,
        shares=shares,
        trade_date=trade_date,
        cost_profile=profile,
    )
    add_probability = min(
        max(
            float(
                profile.get("scap_expected_add_probability", 0.0)
                if expected_add_probability is None
                else expected_add_probability
            ),
            0.0,
        ),
        1.0,
    )
    replacement_probability = min(
        max(
            float(
                profile.get("scap_expected_replacement_probability", 0.0)
                if expected_replacement_probability is None
                else expected_replacement_probability
            ),
            0.0,
        ),
        1.0,
    )
    round_trip = buy_cost + sell_cost
    expected_add = add_probability * round_trip
    expected_replacement = replacement_probability * round_trip
    total = round_trip + expected_add + expected_replacement
    return LifecycleCostEstimate(
        buy_cost_amount=float(buy_cost),
        sell_cost_amount=float(sell_cost),
        expected_add_cost_amount=float(expected_add),
        expected_replacement_cost_amount=float(expected_replacement),
        total_lifecycle_cost_amount=float(total),
        round_trip_cost_ratio=(float(round_trip / notional) if notional > 0.0 else float("inf")),
    )


def assess_economic_order(
    *,
    market_notional_amount: float,
    lifecycle_cost: LifecycleCostEstimate,
    conservative_gross_profit_amount: float,
    robust_net_profit_amount: float,
    cost_profile=None,
    high_confidence_exception: bool = False,
) -> EconomicOrderAssessment:
    """Require positive conservative net value; keep quality ratios diagnostic."""
    profile = dict(cost_profile or {})
    notional = max(float(market_notional_amount), 0.0)
    minimum_amount = minimum_economic_order_amount(cost_profile=profile)
    maximum_round_trip_ratio = max(
        float(profile.get("scap_max_round_trip_fixed_cost_ratio", 0.01) or 0.01),
        0.0,
    )
    maximum_cost_share = max(
        float(profile.get("scap_max_lifecycle_cost_to_gross_profit_ratio", 0.30) or 0.30),
        0.0,
    )
    hard_maximum_cost_share = max(
        float(profile.get("scap_hard_max_lifecycle_cost_to_gross_profit_ratio", 0.60) or 0.60),
        maximum_cost_share,
    )
    minimum_hurdle = max(
        float(profile.get("scap_minimum_robust_profit_hurdle_amount", 15.0) or 15.0),
        0.0,
    )
    gross_profit = max(float(conservative_gross_profit_amount), 0.0)
    cost_share = (
        float(lifecycle_cost.total_lifecycle_cost_amount / gross_profit)
        if gross_profit > 0.0
        else float("inf")
    )
    exception_enabled = bool(profile.get("scap_high_confidence_small_order_exception_enabled", False))
    exception_used = bool(exception_enabled and high_confidence_exception)
    hard_ratio_gate = bool(
        profile.get("scap_round_trip_cost_ratio_hard_gate_enabled", False)
    )
    hard_minimum_notional_gate = bool(
        profile.get("scap_minimum_economic_notional_hard_gate_enabled", False)
    )
    checks = (
        (notional > 0.0, "non_positive_notional"),
        (
            not hard_ratio_gate
            or lifecycle_cost.round_trip_cost_ratio <= maximum_round_trip_ratio + 1e-12,
            "round_trip_cost_ratio",
        ),
        (
            cost_share <= hard_maximum_cost_share + 1e-12,
            "extreme_lifecycle_cost_share",
        ),
        (float(robust_net_profit_amount) > 1e-12, "non_positive_conservative_net_value"),
    )
    failed = [reason for passed, reason in checks if not passed]
    below_minimum = notional + 1e-8 < minimum_amount and not exception_used
    if hard_minimum_notional_gate and below_minimum:
        failed.insert(0, "minimum_economic_notional")
    warnings = []
    if below_minimum:
        warnings.append("minimum_economic_notional")
    if lifecycle_cost.round_trip_cost_ratio > maximum_round_trip_ratio + 1e-12:
        warnings.append("round_trip_cost_ratio")
    if cost_share > maximum_cost_share + 1e-12:
        warnings.append("lifecycle_cost_share_quality_band")
    if 0.0 < float(robust_net_profit_amount) < minimum_hurdle - 1e-12:
        warnings.append("robust_profit_below_quality_hurdle")
    return EconomicOrderAssessment(
        passed=not failed,
        reason="economic_order_pass" if not failed else "|".join(dict.fromkeys(failed)),
        market_notional_amount=notional,
        minimum_economic_order_amount=float(minimum_amount),
        lifecycle_cost_amount=float(lifecycle_cost.total_lifecycle_cost_amount),
        round_trip_cost_ratio=float(lifecycle_cost.round_trip_cost_ratio),
        lifecycle_cost_to_gross_profit_ratio=float(cost_share),
        robust_net_profit_amount=float(robust_net_profit_amount),
        robust_profit_hurdle_amount=float(minimum_hurdle),
        exception_used=exception_used,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def single_side_cost_amount(
    *,
    symbol: str,
    side: str,
    price: float,
    shares: float,
    trade_date=None,
    cost_profile=None,
) -> float:
    """Return the exact configured one-side cost for one factual quantity."""
    normalized_side = str(side).strip().lower()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError(f"side must be buy or sell, got {side!r}")
    if float(price) <= 0.0 or float(shares) <= 0.0:
        return 0.0
    costs = estimate_trade_costs(
        pd.DataFrame(
            [
                {
                    "symbol": str(symbol),
                    "trade_date": trade_date,
                    "side": normalized_side,
                    "price": float(price),
                    "target_shares": float(shares),
                }
            ]
        ),
        **cost_kwargs_from_profile(cost_profile),
    )
    return float(pd.to_numeric(costs["total_cost"], errors="coerce").fillna(0.0).iloc[0])


def buy_cash_required_amount(**kwargs) -> float:
    """Market notional plus exact configured buy-side costs."""
    notional = max(float(kwargs["price"]), 0.0) * max(float(kwargs["shares"]), 0.0)
    return notional + single_side_cost_amount(side="buy", **kwargs)


def sell_cash_released_amount(**kwargs) -> float:
    """Market notional less exact configured sell-side costs."""
    notional = max(float(kwargs["price"]), 0.0) * max(float(kwargs["shares"]), 0.0)
    return max(notional - single_side_cost_amount(side="sell", **kwargs), 0.0)


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
    if state not in {
        "calibrated",
        "pit_fallback_authorized",
        "recovery_authorized",
    }:
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
