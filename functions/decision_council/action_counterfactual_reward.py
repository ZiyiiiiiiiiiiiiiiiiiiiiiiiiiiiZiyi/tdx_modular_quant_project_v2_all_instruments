"""Decision-level, market-neutral rewards for hold, sell, buy and replace actions."""
from __future__ import annotations

import pandas as pd

from config import COMMISSION_RATE, SLIPPAGE_RATE, STAMP_DUTY_RATE, TRANSFER_FEE_RATE
from functions.execution.fee_schedule import stamp_duty_rate_for


HORIZONS = (5, 10, 20)


def build_action_decisions(*, date, candidates: pd.DataFrame, held_symbols, orders: pd.DataFrame, daily: pd.DataFrame) -> list[dict]:
    if candidates is None or candidates.empty:
        return []
    indexed = candidates.drop_duplicates("symbol", keep="first").set_index("symbol", drop=False)
    prices = _price_map(daily)
    order_by_symbol = (
        orders.drop_duplicates("symbol", keep="first").set_index("symbol", drop=False)
        if orders is not None and not orders.empty else pd.DataFrame()
    )
    rows: list[dict] = []
    held_set = {str(symbol) for symbol in held_symbols}
    for symbol in sorted(held_set):
        if symbol not in indexed.index or symbol not in prices:
            continue
        order = order_by_symbol.loc[symbol] if not order_by_symbol.empty and symbol in order_by_symbol.index else None
        side = str(order.get("side", "")) if order is not None else ""
        reason = str(order.get("reason", "")) if order is not None else ""
        action = "sell" if side == "sell" else ("add" if side == "buy" else "hold")
        alternative = str(order.get("replacement_paired_symbol", "")) if reason == "replacement_opportunity_exit" else ""
        if alternative:
            action = "replace"
        if not alternative:
            alternative = _best_comparable_challenger(indexed, held_set, indexed.loc[symbol])
        rows.extend(_decision_horizon_rows(
            date=date, symbol=symbol, action=action, reason=reason or "continue_holding",
            symbol_price=prices[symbol], alternative_symbol=alternative,
            alternative_price=prices.get(alternative), order=order,
        ))

    if orders is not None and not orders.empty:
        buys = orders[orders["side"].astype(str).eq("buy")]
        for _, order in buys.iterrows():
            symbol = str(order["symbol"])
            if symbol in held_set or str(order.get("reason", "")) == "replacement_opportunity_buy" or symbol not in prices:
                continue
            rows.extend(_decision_horizon_rows(
                date=date, symbol=symbol, action="buy", reason=str(order.get("reason", "normal_buy")),
                symbol_price=prices[symbol], alternative_symbol="", alternative_price=None, order=order,
            ))
    return rows


def mature_action_rewards(
    decisions: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    benchmark_symbol: str,
    executions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if decisions is None or decisions.empty:
        return pd.DataFrame()
    history = _history_lookup(prices)
    rows = []
    reconcile_executions = executions is not None
    execution_lookup = _execution_lookup(executions)
    for _, decision in decisions.iterrows():
        row = decision.to_dict()
        horizon = int(row["horizon_days"])
        decision_date = pd.Timestamp(row["decision_date"])
        planned_action = str(row.get("action", "hold"))
        actual = execution_lookup.get((decision_date.normalize(), str(row["symbol"])), {})
        actual_action = _actual_action(planned_action, actual) if reconcile_executions else planned_action
        row["planned_action"] = planned_action
        row["actual_action"] = actual_action
        row["execution_status"] = "filled" if actual else "not_filled"
        row["actual_execution_date"] = actual.get("trade_date", pd.NaT)
        row["actual_execution_price"] = actual.get("price", pd.NA)
        held_start_date = decision_date
        held_start_price = float(row["symbol_price"])
        alternative_start_date = decision_date
        alternative_start = _number(row.get("alternative_price"))
        cost = float(_number(row.get("estimated_action_cost_rate"), 0.0) or 0.0)
        if actual_action in {"sell", "replace"} and _number(actual.get("sell_price")) is not None:
            held_start_date = pd.Timestamp(actual.get("sell_trade_date"))
            held_start_price = float(actual["sell_price"])
            cost = float(_number(actual.get("sell_cost_rate"), 0.0) or 0.0)
        elif actual_action == "buy" and _number(actual.get("buy_price")) is not None:
            held_start_date = pd.Timestamp(actual.get("buy_trade_date"))
            held_start_price = float(actual["buy_price"])
            cost = float(_number(actual.get("buy_cost_rate"), 0.0) or 0.0)
        if actual_action == "replace" and _number(actual.get("paired_buy_price")) is not None:
            alternative_start_date = pd.Timestamp(actual.get("paired_buy_trade_date"))
            alternative_start = float(actual["paired_buy_price"])
            cost += float(_number(actual.get("paired_buy_cost_rate"), 0.0) or 0.0)
        symbol_return, maturity_date = _future_return(
            history.get(str(row["symbol"])), held_start_date, horizon, held_start_price
        )
        benchmark_start = _price_asof(history.get(str(benchmark_symbol)), held_start_date)
        benchmark_return, benchmark_maturity = _future_return(
            history.get(str(benchmark_symbol)), held_start_date, horizon, benchmark_start
        ) if benchmark_start is not None else (None, None)
        if symbol_return is None or benchmark_return is None:
            row.update({"maturity_status": "censored", "maturity_date": pd.NaT, "action_reward": pd.NA})
            rows.append(row)
            continue
        held_alpha = float(symbol_return - benchmark_return)
        alternative_alpha = None
        alternative_benchmark_return = None
        alternative_maturity = None
        alternative = str(row.get("alternative_symbol", "") or "")
        if alternative and alternative_start is not None:
            alternative_return, alternative_maturity = _future_return(
                history.get(alternative), alternative_start_date, horizon, alternative_start
            )
            alternative_benchmark_start = _price_asof(
                history.get(str(benchmark_symbol)), alternative_start_date
            )
            alternative_benchmark_return, alternative_benchmark_maturity = _future_return(
                history.get(str(benchmark_symbol)), alternative_start_date, horizon,
                alternative_benchmark_start,
            ) if alternative_benchmark_start is not None else (None, None)
            if alternative_return is not None and alternative_benchmark_return is not None:
                alternative_alpha = float(alternative_return - alternative_benchmark_return)
                alternative_maturity = max(alternative_maturity, alternative_benchmark_maturity)
        action = actual_action
        if action == "sell":
            reward = -held_alpha - cost
        elif action == "replace":
            reward = (alternative_alpha - held_alpha - cost) if alternative_alpha is not None else pd.NA
        elif action == "hold":
            reward = held_alpha - (alternative_alpha - cost) if alternative_alpha is not None else held_alpha
        elif action in {"buy", "add"}:
            reward = held_alpha - cost
        else:  # an unfilled planned buy is not a portfolio action
            reward = 0.0
        row.update({
            "maturity_status": "matured" if pd.notna(reward) else "censored_alternative",
            "maturity_date": max(
                value for value in (maturity_date, benchmark_maturity, alternative_maturity)
                if value is not None
            ),
            "symbol_return": symbol_return,
            "benchmark_return": benchmark_return,
            "alternative_benchmark_return": alternative_benchmark_return,
            "market_neutral_symbol_return": held_alpha,
            "alternative_market_neutral_return": alternative_alpha,
            "actual_action_cost_rate": cost,
            "reward_start_date": held_start_date,
            "alternative_reward_start_date": alternative_start_date if alternative else pd.NaT,
            "action_reward": reward,
            "reward_formula_version": "market_neutral_actual_fill_cost_counterfactual_v3",
        })
        rows.append(row)
    return pd.DataFrame(rows)


def _decision_horizon_rows(*, date, symbol, action, reason, symbol_price, alternative_symbol, alternative_price, order):
    generic_one_way = COMMISSION_RATE + SLIPPAGE_RATE + TRANSFER_FEE_RATE
    sell_rate = generic_one_way + stamp_duty_rate_for(date, fallback_rate=STAMP_DUTY_RATE)
    if action == "replace":
        cost = _number(order.get("replacement_cost_rate")) if order is not None else None
        cost = float(cost if cost is not None else sell_rate + generic_one_way)
    elif action == "sell":
        cost = float(sell_rate)
    elif action in {"buy", "add"}:
        cost = float(generic_one_way)
    else:
        cost = float(sell_rate + generic_one_way) if alternative_symbol else 0.0
    return [{
        "decision_id": f"action_{pd.Timestamp(date).strftime('%Y%m%d')}_{symbol}_{horizon}",
        "decision_date": pd.Timestamp(date), "symbol": symbol, "action": action,
        "reason": reason, "horizon_days": horizon, "symbol_price": float(symbol_price),
        "alternative_symbol": str(alternative_symbol or ""),
        "alternative_price": alternative_price if alternative_price is not None else pd.NA,
        "estimated_action_cost_rate": cost, "maturity_status": "pending",
        "action_module": (
            str(order.get("unified_action_selected", ""))
            if order is not None
            else "hold"
        ),
        "competing_action_proposals": (
            str(order.get("unified_action_proposals", ""))
            if order is not None
            else "hold"
        ),
        "vetoed_action_proposals": (
            str(order.get("unified_action_vetoed", ""))
            if order is not None
            else ""
        ),
        "action_arbitration_contract": (
            str(order.get("unified_action_contract", ""))
            if order is not None
            else "unified_position_action_v1"
        ),
    } for horizon in HORIZONS]


def _best_comparable_challenger(indexed, held_set, held_row) -> str:
    horizon = _number(held_row.get("comparable_value_horizon_days"))
    if horizon is None:
        return ""
    pool = indexed[
        ~indexed["symbol"].astype(str).isin(held_set)
        & indexed.get("entry_confirmed", pd.Series(False, index=indexed.index)).fillna(False).astype(bool)
        & indexed.get("mainline_v3_lot_feasible", pd.Series(False, index=indexed.index)).fillna(False).astype(bool)
        & pd.to_numeric(indexed.get("comparable_value_horizon_days"), errors="coerce").eq(horizon)
    ].copy().reset_index(drop=True)
    if pool.empty:
        return ""
    pool["_lcb"] = pd.to_numeric(pool.get("comparable_alpha_lcb"), errors="coerce")
    pool = pool.dropna(subset=["_lcb"]).sort_values(["_lcb", "symbol"], ascending=[False, True])
    return str(pool.iloc[0]["symbol"]) if not pool.empty else ""


def _price_map(data):
    if data is None or data.empty:
        return {}
    col = "close_nominal" if "close_nominal" in data.columns else "close"
    frame = data[["symbol", col]].copy()
    frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna()
    return dict(zip(frame["symbol"].astype(str), frame[col].astype(float)))


def _history_lookup(prices):
    if prices is None or prices.empty:
        return {}
    col = "close" if "close" in prices.columns else "close_nominal"
    data = prices[["date", "symbol", col]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna().sort_values(["symbol", "date"])
    return {str(symbol): group[["date", col]].rename(columns={col: "close"}).reset_index(drop=True)
            for symbol, group in data.groupby("symbol", sort=False)}


def _execution_lookup(executions):
    if executions is None or executions.empty:
        return {}
    data = executions.copy()
    data["signal_date"] = pd.to_datetime(
        data.get("signal_date", data.get("decision_date")), errors="coerce"
    ).dt.normalize()
    data["trade_date"] = pd.to_datetime(data.get("trade_date"), errors="coerce")
    status = data.get("execution_status", pd.Series("filled", index=data.index)).astype(str).str.lower()
    shares = pd.to_numeric(data.get("executed_shares"), errors="coerce").fillna(0.0)
    data = data[status.eq("filled") & shares.gt(0.0)]
    if data.empty:
        return {}
    data["_symbol"] = data["symbol"].astype(str)
    data["_side"] = data["side"].astype(str).str.lower()
    data["_pair_id"] = data.get(
        "replacement_pair_id", pd.Series("", index=data.index)
    ).fillna("").astype(str)
    notional = pd.to_numeric(data.get("trade_notional"), errors="coerce")
    total_cost = pd.to_numeric(data.get("total_cost"), errors="coerce")
    data["_cost_rate"] = (total_cost / notional.where(notional.gt(0.0))).fillna(0.0)
    pair_column = data.get("replacement_pair_id", pd.Series("", index=data.index)).fillna("").astype(str)
    pair_sides = {
        str(pair_id): set(group["side"].astype(str).str.lower())
        for pair_id, group in data.assign(_pair_id=pair_column).groupby("_pair_id", sort=False)
        if str(pair_id)
    }
    pair_details = {}
    paired = data[data["_pair_id"].ne("")]
    for (date, pair_id), group in paired.groupby(["signal_date", "_pair_id"], sort=False):
        detail = {}
        for side in ("sell", "buy"):
            leg = group[group["_side"].eq(side)].sort_values("trade_date")
            if leg.empty:
                continue
            item = leg.iloc[0]
            detail.update({
                f"paired_{side}_symbol": str(item["_symbol"]),
                f"paired_{side}_trade_date": item["trade_date"],
                f"paired_{side}_price": _number(item.get("price")),
                f"paired_{side}_cost_rate": float(item.get("_cost_rate", 0.0)),
            })
        pair_details[(pd.Timestamp(date), str(pair_id))] = detail
    lookup = {}
    for (date, symbol), group in data.groupby(["signal_date", "_symbol"], sort=False):
        sides = set(group["side"].astype(str).str.lower())
        ids = set(group.get("replacement_pair_id", pd.Series("", index=group.index)).fillna("").astype(str))
        for pair_id in ids:
            if pair_id:
                sides.update(pair_sides.get(pair_id, set()))
        detail = {
            "sides": sides,
            "pair_ids": ids,
            "trade_date": group["trade_date"].min(),
            "price": pd.to_numeric(group.get("price"), errors="coerce").dropna().iloc[0]
            if pd.to_numeric(group.get("price"), errors="coerce").notna().any() else pd.NA,
        }
        for side in ("sell", "buy"):
            leg = group[group["_side"].eq(side)].sort_values("trade_date")
            if not leg.empty:
                item = leg.iloc[0]
                detail.update({
                    f"{side}_trade_date": item["trade_date"],
                    f"{side}_price": _number(item.get("price")),
                    f"{side}_cost_rate": float(item.get("_cost_rate", 0.0)),
                })
        for pair_id in ids:
            if pair_id:
                detail.update(pair_details.get((pd.Timestamp(date), str(pair_id)), {}))
        lookup[(pd.Timestamp(date), str(symbol))] = detail
    return lookup


def _actual_action(planned_action: str, actual: dict) -> str:
    sides = set(actual.get("sides", set()))
    if planned_action == "replace":
        return "replace" if {"sell", "buy"}.issubset(sides) else ("sell" if "sell" in sides else "hold")
    if planned_action == "sell":
        return "sell" if "sell" in sides else "hold"
    if planned_action in {"buy", "add"}:
        return planned_action if "buy" in sides else "no_trade"
    return "hold"


def _price_asof(history, date):
    if history is None or history.empty:
        return None
    values = history[history["date"] <= pd.Timestamp(date)]
    return float(values.iloc[-1]["close"]) if not values.empty else None


def _future_return(history, date, horizon, start_price):
    if history is None or history.empty or start_price is None or float(start_price) <= 0.0:
        return None, None
    future = history[history["date"] > pd.Timestamp(date)].head(int(horizon))
    if len(future) < int(horizon):
        return None, None
    return float(future.iloc[-1]["close"] / float(start_price) - 1.0), pd.Timestamp(future.iloc[-1]["date"])


def _number(value, default=None):
    result = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return default if pd.isna(result) else float(result)
