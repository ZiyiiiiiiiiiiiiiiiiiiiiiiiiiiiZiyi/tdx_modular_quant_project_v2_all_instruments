"""Capital-scaled position-count and sizing contracts.

The financial position cap, an optional user cap, and the computational search
cap are deliberately separate.  A missing user cap never means "five"; auto
mode derives a daily feasible ceiling from cash, board lots, and fixed costs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import pandas as pd

from functions.decision_council.action_utility import (
    assess_economic_order,
    estimate_lifecycle_cost,
    minimum_economic_order_amount,
)


LOT_CASH_COLUMNS = (
    "mainline_v3_one_lot_cash_required",
    "one_lot_cash_required",
    "lot_cash_required",
)


@dataclass(frozen=True)
class PositionCapacity:
    mode: str
    configured_cap: int | None
    user_hard_cap: int | None
    search_cap: int
    eligible_symbol_count: int
    economic_position_cap: int
    lot_cash_position_cap: int
    cost_feasible_position_cap: int
    risk_feasible_position_cap: int
    effective_position_cap: int
    sizing_reference_positions: int
    soft_target_positions: int
    spendable_cash: float
    minimum_economic_order_amount: float
    median_one_lot_amount: float
    capacity_risk_room_amount: float
    grandfathered_excess_names: int
    reason: str
    risk_capacity_state: str = "not_independently_estimated"

    def as_dict(self) -> dict:
        return asdict(self)


def resolve_position_capacity(
    *,
    capital_profile: dict | None,
    nav_amount: float,
    cash_amount: float,
    risk_exposure_ceiling: float,
    candidates: pd.DataFrame | None,
    current_symbols=(),
    current_exposure: float = 0.0,
) -> PositionCapacity:
    """Return a daily position ceiling without treating a search cap as finance."""
    profile = dict(capital_profile or {})
    configured = _optional_positive_int(profile.get("max_positions"))
    user_hard_cap = _optional_positive_int(profile.get("user_hard_position_cap"))
    mode = str(
        profile.get(
            "position_cap_mode",
            "fixed" if configured is not None else "auto",
        )
        or "auto"
    ).strip().lower()
    if mode not in {"fixed", "auto"}:
        raise ValueError(f"Unknown position_cap_mode: {mode}")
    if mode == "fixed" and configured is None:
        raise ValueError("fixed position_cap_mode requires max_positions")

    search_cap = max(
        int(profile.get("scap_search_position_cap", 32) or 32),
        1,
    )
    frame = candidates if candidates is not None else pd.DataFrame()
    held = {str(symbol) for symbol in current_symbols}
    if held and not frame.empty and "symbol" in frame.columns:
        frame = frame[~frame["symbol"].astype(str).isin(held)]
    lot_cash = _candidate_lot_cash(frame)
    eligible_count = int(len(lot_cash))
    nav = max(float(nav_amount), 0.0)
    cash = max(float(cash_amount), 0.0)
    buffer_amount = max(float(profile.get("min_cash_buffer", 0.0) or 0.0), 0.0)
    risk_budget = nav * min(max(float(risk_exposure_ceiling), 0.0), 1.0)
    current_invested = nav * min(max(float(current_exposure), 0.0), 1.0)
    risk_room = max(risk_budget - current_invested, 0.0)
    spendable = max(min(max(cash - buffer_amount, 0.0), risk_room), 0.0)
    minimum_economic_order = minimum_economic_order_amount(cost_profile=profile)
    hard_minimum_notional_gate = bool(
        profile.get("scap_minimum_economic_notional_hard_gate_enabled", False)
    )
    ranked_lot_cash = _ranked_lot_cash(frame, lot_cash)
    economic_required_cash = _ranked_economic_required_cash(
        frame=frame,
        ranked_lot_cash=ranked_lot_cash,
        spendable_cash=spendable,
        cost_profile=profile,
        search_cap=search_cap,
    )
    economic_amounts = sorted(
        [
        (
            max(float(value), minimum_economic_order)
            if hard_minimum_notional_gate
            else float(value)
        )
        for value in economic_required_cash.tolist()
        if math.isfinite(float(value)) and float(value) > 0.0
        ]
    )
    raw_lot_amounts = sorted(
        [
        float(value) for value in ranked_lot_cash.tolist() if float(value) > 0.0
        ]
    )
    raw_new_name_cap = _cumulative_affordable_count(
        raw_lot_amounts, spendable=spendable, maximum=max(search_cap - len(held), 0)
    )
    new_name_cap = _cumulative_affordable_count(
        economic_amounts, spendable=spendable, maximum=max(search_cap - len(held), 0)
    )
    lot_cash_cap = len(held) + raw_new_name_cap
    economic_cash_cap = len(held) + new_name_cap
    cost_feasible_cap = len(held) + int(len(economic_required_cash))
    risk_feasible_cap = economic_cash_cap
    economic_cap = min(economic_cash_cap, cost_feasible_cap, risk_feasible_cap)
    if configured is not None and mode == "fixed":
        effective = min(configured, search_cap)
        reason = "fixed_profile_or_user_cap"
    else:
        auto_caps = [economic_cap, len(held) + eligible_count, search_cap]
        if user_hard_cap is not None:
            auto_caps.append(user_hard_cap)
        effective = min(auto_caps)
        reason = (
            "auto_cash_lot_candidate_search_capacity"
            if eligible_count
            else "auto_no_eligible_lot_cash"
        )
    total_economic_budget = max(risk_budget - buffer_amount, 0.0)
    if mode == "fixed" and configured is not None:
        sizing_reference = int(configured)
    elif math.isfinite(minimum_economic_order) and minimum_economic_order > 0.0:
        sizing_reference = max(
            int(math.floor(total_economic_budget / minimum_economic_order)),
            1,
        )
    else:
        sizing_reference = max(int(effective), 1)
    sizing_reference = min(sizing_reference, search_cap)
    if user_hard_cap is not None:
        sizing_reference = min(sizing_reference, user_hard_cap)
    # The optimizer may select fewer names.  This field is a reporting target,
    # not a minimum-holdings constraint.
    configured_soft = _optional_nonnegative_int(profile.get("soft_target_positions"))
    soft_target = (
        min(configured_soft, effective)
        if configured_soft is not None and mode == "fixed"
        else 0
    )
    return PositionCapacity(
        mode=mode,
        configured_cap=configured,
        user_hard_cap=user_hard_cap,
        search_cap=search_cap,
        eligible_symbol_count=eligible_count,
        economic_position_cap=economic_cap,
        lot_cash_position_cap=lot_cash_cap,
        cost_feasible_position_cap=cost_feasible_cap,
        risk_feasible_position_cap=risk_feasible_cap,
        effective_position_cap=max(int(effective), len(held), 1),
        sizing_reference_positions=max(int(sizing_reference), 1),
        soft_target_positions=max(int(soft_target), 0),
        spendable_cash=spendable,
        minimum_economic_order_amount=minimum_economic_order,
        median_one_lot_amount=(
            float(lot_cash.median()) if not lot_cash.empty else 0.0
        ),
        capacity_risk_room_amount=risk_room,
        grandfathered_excess_names=max(len(held) - int(effective), 0),
        reason=reason,
        risk_capacity_state="not_independently_estimated_cash_proxy_only",
    )


@dataclass(frozen=True)
class OptimizerSearchBudget:
    """Computational limits; none of these fields is a financial constraint."""

    prefilter_symbol_limit: int
    exact_max_positions: int
    beam_width: int
    search_holding_ceiling: int
    budget_version: str = "scap_optimizer_search_budget_v1"

    def __post_init__(self) -> None:
        if min(
            int(self.prefilter_symbol_limit),
            int(self.exact_max_positions),
            int(self.beam_width),
            int(self.search_holding_ceiling),
        ) <= 0:
            raise ValueError("optimizer search limits must be positive")

    def as_dict(self) -> dict:
        return asdict(self)


def resolve_optimizer_search_budget(
    capital_profile: dict | None,
) -> OptimizerSearchBudget:
    """Resolve search resources independently from trade capacity."""
    profile = dict(capital_profile or {})
    return OptimizerSearchBudget(
        prefilter_symbol_limit=max(
            int(profile.get("scap_optimizer_candidate_limit", 12)),
            1,
        ),
        exact_max_positions=max(
            int(profile.get("scap_optimizer_exact_max_positions", 5)),
            1,
        ),
        beam_width=max(
            int(profile.get("scap_optimizer_beam_width", 256)),
            1,
        ),
        search_holding_ceiling=max(
            int(profile.get("scap_search_position_cap", 32)),
            1,
        ),
    )


def _cumulative_affordable_count(amounts, *, spendable: float, maximum: int) -> int:
    """Maximum feasible name count, independent of alpha ranking.

    The caller supplies ascending unique-symbol cash tickets.  Ranking quality
    belongs to the portfolio optimizer; using a greedy alpha order here would
    turn a soft preference for expensive names into a false hard K ceiling.
    """
    if int(maximum) <= 0:
        return 0
    cumulative = 0.0
    count = 0
    for amount in amounts:
        value = max(float(amount), 0.0)
        if value <= 0.0 or cumulative + value > float(spendable) + 1e-8:
            continue
        cumulative += value
        count += 1
        if count >= int(maximum):
            break
    return count


def _ranked_economic_required_cash(
    *,
    frame: pd.DataFrame,
    ranked_lot_cash: pd.Series,
    spendable_cash: float,
    cost_profile: dict,
    search_cap: int,
) -> pd.Series:
    """Minimum candidate-specific cash that passes full lifecycle economics.

    When the calibrated return contract is not yet attached, capacity remains
    a cash/lot ceiling.  Once it is attached, a cheap one-lot order cannot
    inflate K unless some integer lot size has positive robust CNY value and
    passes the same lifecycle-cost contract consumed by the optimizer.
    """
    if frame.empty or ranked_lot_cash.empty:
        return pd.Series(dtype=float)
    required = {
        "symbol",
        "comparable_alpha_lcb",
    }
    if not required.issubset(frame.columns):
        return ranked_lot_cash.copy()
    price_column = next(
        (column for column in ("close_nominal", "close", "open_nominal", "open") if column in frame.columns),
        None,
    )
    if price_column is None:
        return ranked_lot_cash.copy()
    limited = frame.loc[frame.index.intersection(ranked_lot_cash.index)].copy()
    amounts: list[float] = []
    seen_symbols: set[str] = set()
    for row_index, one_lot_cash in ranked_lot_cash.items():
        if row_index not in limited.index or len(amounts) >= int(search_cap):
            continue
        row = limited.loc[row_index]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        symbol = str(row.get("symbol", ""))
        if not symbol or symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)
        price = float(pd.to_numeric(pd.Series([row.get(price_column)]), errors="coerce").fillna(0.0).iloc[0])
        alpha_lcb = float(pd.to_numeric(pd.Series([row.get("comparable_alpha_lcb")]), errors="coerce").fillna(0.0).iloc[0])
        if price <= 0.0 or alpha_lcb <= 0.0:
            continue
        maximum_lots = min(
            max(int(float(spendable_cash) // max(price * 100.0, 1e-12)), 0),
            100,
        )
        feasible_cash = None
        for lots in range(1, maximum_lots + 1):
            shares = float(lots * 100)
            lifecycle = estimate_lifecycle_cost(
                symbol=str(symbol),
                price=price,
                shares=shares,
                cost_profile=cost_profile,
            )
            notional = price * shares
            gross = alpha_lcb * notional
            robust = gross - lifecycle.total_lifecycle_cost_amount
            assessment = assess_economic_order(
                market_notional_amount=notional,
                lifecycle_cost=lifecycle,
                conservative_gross_profit_amount=gross,
                robust_net_profit_amount=robust,
                cost_profile=cost_profile,
            )
            if assessment.passed:
                feasible_cash = notional + lifecycle.buy_cost_amount
                break
        if feasible_cash is not None:
            amounts.append(float(feasible_cash))
    return pd.Series(amounts, dtype=float)


def scaled_position_weight_caps(
    *,
    target_exposure: float,
    effective_position_cap: int,
    absolute_soft_cap: float,
    absolute_hard_cap: float,
    soft_equal_weight_multiple: float = 1.50,
    hard_equal_weight_multiple: float = 2.30,
) -> tuple[float, float]:
    """Scale concentration limits with endogenous breadth.

    The absolute caps remain disaster ceilings.  At K=5 and E=85%, the
    defaults reproduce approximately 25% soft / 39% hard; at larger K the
    limits decline with equal-weight exposure.
    """
    exposure = min(max(float(target_exposure), 0.0), 1.0)
    count = max(int(effective_position_cap), 1)
    equal_weight = exposure / count
    soft = min(
        max(float(absolute_soft_cap), 0.0),
        max(float(soft_equal_weight_multiple), 0.0) * equal_weight,
    )
    hard = min(
        max(float(absolute_hard_cap), 0.0),
        max(float(hard_equal_weight_multiple), 0.0) * equal_weight,
    )
    hard = max(hard, soft)
    return min(soft, 1.0), min(hard, 1.0)


def scaled_candidate_budgets(
    *,
    effective_position_cap: int,
    pool_count: int,
    minimum_pool_top_m: int = 4,
    optimizer_multiple: float = 4.0,
    search_cap: int = 96,
) -> dict[str, int]:
    """Scale pool and optimizer candidate budgets with feasible breadth."""
    count = max(int(effective_position_cap), 1)
    pools = max(int(pool_count), 1)
    pool_top_m = max(
        int(minimum_pool_top_m),
        int(math.ceil(2.0 * count / pools)),
    )
    optimizer_limit = min(
        max(int(math.ceil(float(optimizer_multiple) * count)), count),
        max(int(search_cap), count),
    )
    thesis_soft = max(int(math.ceil(0.35 * count)), 1)
    thesis_hard = max(int(math.ceil(0.55 * count)), thesis_soft)
    return {
        "pool_top_m": pool_top_m,
        "optimizer_candidate_limit": optimizer_limit,
        "thesis_soft_max_names": thesis_soft,
        "thesis_hard_max_names": thesis_hard,
    }


def _candidate_lot_cash(candidates: pd.DataFrame) -> pd.Series:
    if candidates is None or candidates.empty:
        return pd.Series(dtype=float)
    for column in LOT_CASH_COLUMNS:
        if column in candidates.columns:
            values = pd.to_numeric(candidates[column], errors="coerce")
            values = values[values.gt(0.0) & values.notna()]
            if not values.empty:
                return values
    price_column = next(
        (
            column
            for column in ("close_nominal", "close", "open_nominal", "open")
            if column in candidates.columns
        ),
        None,
    )
    if price_column is None:
        return pd.Series(dtype=float)
    prices = pd.to_numeric(candidates[price_column], errors="coerce")
    return (prices * 100.0)[prices.gt(0.0) & prices.notna()]


def _ranked_lot_cash(candidates: pd.DataFrame, lot_cash: pd.Series) -> pd.Series:
    """Retain deterministic evidence order before economic feasibility review.

    Final hard capacity is computed from ascending feasible cash tickets; this
    ordering is retained only so the review loop and audit remain stable.
    """
    if lot_cash.empty:
        return lot_cash
    frame = candidates.loc[lot_cash.index].copy()
    score_column = next(
        (
            column
            for column in (
                "scap_candidate_utility",
                "risk_adjusted_primary_score",
                "cabinet_native_final_score",
                "primary_score",
            )
            if column in frame.columns
        ),
        None,
    )
    frame["_lot_cash"] = lot_cash
    if score_column is None:
        # Preserve deterministic candidate order; price must not manufacture
        # a larger capacity by moving cheap, weak names to the front.
        return frame["_lot_cash"]
    frame["_capacity_score"] = pd.to_numeric(frame[score_column], errors="coerce")
    return frame.sort_values(
        ["_capacity_score"],
        ascending=[False],
        na_position="last",
        kind="mergesort",
    )["_lot_cash"]


def _optional_positive_int(value) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _optional_nonnegative_int(value) -> int | None:
    if value in (None, ""):
        return None
    return max(int(value), 0)
