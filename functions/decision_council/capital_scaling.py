"""Capital-scaled position-count and sizing contracts.

The financial position cap, an optional user cap, and the computational search
cap are deliberately separate.  A missing user cap never means "five"; auto
mode derives a daily feasible ceiling from cash, board lots, and fixed costs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import pandas as pd


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
    effective_position_cap: int
    soft_target_positions: int
    spendable_cash: float
    minimum_economic_order_amount: float
    median_one_lot_amount: float
    capacity_risk_room_amount: float
    reason: str

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
    maximum_round_trip_cost_ratio = max(
        float(
            profile.get(
                "scap_max_round_trip_fixed_cost_ratio",
                0.01,
            )
            or 0.01
        ),
        1e-6,
    )
    slippage_rate = max(float(profile.get("slippage_rate", 0.0) or 0.0), 0.0)
    stamp_duty_rate = max(float(profile.get("stamp_duty_rate", 0.0) or 0.0), 0.0)
    transfer_fee_rate = max(float(profile.get("transfer_fee_rate", 0.0) or 0.0), 0.0)
    non_commission_round_trip_rate = (
        2.0 * slippage_rate + stamp_duty_rate + 2.0 * transfer_fee_rate
    )
    residual_cost_budget = maximum_round_trip_cost_ratio - non_commission_round_trip_rate
    minimum_economic_order = (
        2.0 * minimum_commission / residual_cost_budget
        if minimum_commission > 0.0 and residual_cost_budget > 0.0
        else float("inf") if minimum_commission > 0.0 else 0.0
    )
    economic_amounts = [
        max(float(value), minimum_economic_order)
        for value in _ranked_lot_cash(frame, lot_cash).tolist()
        if float(value) > 0.0
    ]
    cumulative = 0.0
    new_name_cap = 0
    for amount in economic_amounts:
        if cumulative + amount > spendable + 1e-8:
            continue
        cumulative += amount
        new_name_cap += 1
        if len(held) + new_name_cap >= search_cap:
            break
    lot_cash_cap = len(held) + new_name_cap
    economic_cap = lot_cash_cap
    if configured is not None and mode == "fixed":
        effective = min(configured, search_cap)
        reason = "fixed_profile_or_user_cap"
    else:
        auto_caps = [economic_cap, len(held) + eligible_count, search_cap]
        if user_hard_cap is not None:
            auto_caps.append(user_hard_cap)
        effective = min(auto_caps)
        reason = (
            "auto_cash_lot_cost_capacity"
            if eligible_count
            else "auto_no_eligible_lot_cash"
        )
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
        effective_position_cap=max(int(effective), len(held), 1),
        soft_target_positions=max(int(soft_target), 0),
        spendable_cash=spendable,
        minimum_economic_order_amount=minimum_economic_order,
        median_one_lot_amount=(
            float(lot_cash.median()) if not lot_cash.empty else 0.0
        ),
        capacity_risk_room_amount=risk_room,
        reason=reason,
    )


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
    """Order capacity tickets by decision evidence, never by cheapest price."""
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
