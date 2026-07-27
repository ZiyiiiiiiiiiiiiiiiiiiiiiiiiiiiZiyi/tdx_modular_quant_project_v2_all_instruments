"""Cost-aware one-for-one replacement decisions for small A-share accounts."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import COMMISSION_RATE, MINIMUM_COMMISSION, SLIPPAGE_RATE, STAMP_DUTY_RATE, TRANSFER_FEE_RATE
from functions.decision_council.multi_horizon_value import comparable_pair
from functions.execution.fee_schedule import commission_cost, stamp_duty_rate_for
from functions.execution.security_trading_rules import trading_rule_for


@dataclass(frozen=True)
class ReplacementPair:
    pair_id: str
    held_symbol: str
    challenger_symbol: str
    horizon_days: int
    expected_net_edge: float
    lcb_net_edge: float
    estimated_cost_rate: float


def choose_active_replacements(
    candidates: pd.DataFrame,
    *,
    current_weights: dict[str, float],
    holding_days: dict[str, int],
    decision_date,
    minimum_holding_days: int,
    max_pairs_per_day: int | None = None,
) -> list[ReplacementPair]:
    if candidates is None or candidates.empty or "symbol" not in candidates.columns:
        return []
    data = candidates.drop_duplicates("symbol", keep="first").set_index("symbol", drop=False)
    logic = data.get("strategy_logic_version", pd.Series("", index=data.index)).astype(str)
    if not logic.str.startswith("mainline_v3").any():
        return []
    held_symbols = [
        str(symbol) for symbol, weight in current_weights.items()
        if float(weight) > 1e-12 and str(symbol) in data.index
    ]
    challengers = data[
        ~data["symbol"].astype(str).isin(held_symbols)
        & data.get(
            "replacement_challenger_eligible",
            data.get("entry_confirmed", pd.Series(False, index=data.index)),
        ).fillna(False).astype(bool)
        & data.get("state_machine_role_pass", pd.Series(True, index=data.index)).fillna(False).astype(bool)
        & data.get(
            "mainline_v3_replacement_feasible",
            data.get("mainline_v3_lot_feasible", pd.Series(False, index=data.index)),
        ).fillna(False).astype(bool)
        & ~data.get("cooldown_active", pd.Series(False, index=data.index)).fillna(False).astype(bool)
        & ~data.get("exit_state", pd.Series(False, index=data.index)).fillna(False).astype(bool)
        & data.get(
            "position_state", pd.Series("building", index=data.index)
        ).fillna("blocked").astype(str).str.lower().isin(
            {"building", "strong_building", "holding", "watching", "adding"}
        )
        & data.get("comparable_value_available", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    ].copy()
    if challengers.empty:
        return []

    proposals: list[tuple[float, str, str, int, float, float, float]] = []
    for held_symbol in held_symbols:
        if int(holding_days.get(held_symbol, 0)) < int(minimum_holding_days):
            continue
        held = data.loc[held_symbol]
        if bool(held.get("exit_state", False)) or bool(held.get("alpha_collapse_exit", False)):
            continue
        for challenger_symbol, challenger in challengers.iterrows():
            if not comparable_pair(held, challenger):
                continue
            holding_expected = _number(held.get("comparable_expected_alpha"))
            challenger_expected = _number(challenger.get("comparable_expected_alpha"))
            challenger_lcb = _number(challenger.get("comparable_alpha_lcb"))
            if None in (holding_expected, challenger_expected, challenger_lcb):
                continue
            cost_rate = _pair_execution_cost_rate(held, challenger, decision_date)
            liquidity_penalty = max(
                _number(challenger.get("estimated_market_impact_rate"), 0.0) or 0.0,
                0.0,
            ) + max(_number(held.get("estimated_market_impact_rate"), 0.0) or 0.0, 0.0)
            total_cost = cost_rate + liquidity_penalty
            expected_net = challenger_expected - holding_expected - total_cost
            # The challenger lower bound is compared with the holding point
            # estimate.  This is deliberately stricter than subtracting two
            # optimistic forecasts.
            lcb_net = challenger_lcb - holding_expected - total_cost
            if lcb_net <= 0.0:
                continue
            horizon = int(challenger["comparable_value_horizon_days"])
            proposals.append((lcb_net, held_symbol, str(challenger_symbol), horizon, expected_net, lcb_net, total_cost))

    proposals.sort(key=lambda row: (-row[0], row[1], row[2]))
    used_held: set[str] = set()
    used_challenger: set[str] = set()
    chosen: list[ReplacementPair] = []
    date_token = pd.Timestamp(decision_date).strftime("%Y%m%d")
    for _, held_symbol, challenger_symbol, horizon, expected_net, lcb_net, total_cost in proposals:
        if max_pairs_per_day is not None and len(chosen) >= max(int(max_pairs_per_day), 0):
            break
        if held_symbol in used_held or challenger_symbol in used_challenger:
            continue
        pair_id = f"replace_{date_token}_{held_symbol}_{challenger_symbol}"
        chosen.append(ReplacementPair(
            pair_id=pair_id,
            held_symbol=held_symbol,
            challenger_symbol=challenger_symbol,
            horizon_days=horizon,
            expected_net_edge=float(expected_net),
            lcb_net_edge=float(lcb_net),
            estimated_cost_rate=float(total_cost),
        ))
        used_held.add(held_symbol)
        used_challenger.add(challenger_symbol)
    return chosen


def _round_trip_cost_rate(decision_date) -> float:
    return float(
        2.0 * (COMMISSION_RATE + SLIPPAGE_RATE + TRANSFER_FEE_RATE)
        + stamp_duty_rate_for(decision_date, fallback_rate=STAMP_DUTY_RATE)
    )


def _pair_execution_cost_rate(held: pd.Series, challenger: pd.Series, decision_date) -> float:
    """Conservative exact one-lot fee rate shared with small-account execution."""
    rates = []
    for row, side in ((held, "sell"), (challenger, "buy")):
        symbol = str(row.get("symbol", ""))
        price = _number(row.get("close_nominal"), _number(row.get("close")))
        if not symbol or price is None or price <= 0.0:
            return _round_trip_cost_rate(decision_date)
        quantity = trading_rule_for(symbol, trade_date=decision_date).minimum_buy_quantity
        notional = float(price) * float(quantity)
        variable_rate = float(SLIPPAGE_RATE + TRANSFER_FEE_RATE)
        if side == "sell":
            variable_rate += float(stamp_duty_rate_for(decision_date, fallback_rate=STAMP_DUTY_RATE))
        fee = commission_cost(notional, rate=COMMISSION_RATE, minimum=MINIMUM_COMMISSION)
        rates.append(float(fee / max(notional, 1e-12) + variable_rate))
    return float(sum(rates))


def _number(value, default=None):
    result = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return default if pd.isna(result) else float(result)
