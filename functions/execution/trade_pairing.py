# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd


def build_trade_pairing_ledgers(
    order_ledger: pd.DataFrame,
    latest_prices: pd.DataFrame | None = None,
    *,
    capital_profile: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if order_ledger is None or order_ledger.empty:
        return pd.DataFrame(), pd.DataFrame(), _empty_trade_summary(capital_profile)

    data = order_ledger.copy()
    data["trade_date"] = pd.to_datetime(_series_or_default(data, "trade_date"), errors="coerce")
    data["side"] = _series_or_default(data, "side").astype(str).str.lower()
    data["executed_shares"] = pd.to_numeric(_series_or_default(data, "executed_shares"), errors="coerce").fillna(0.0)
    data["price"] = pd.to_numeric(_series_or_default(data, "price"), errors="coerce").fillna(0.0)
    data["total_cost"] = pd.to_numeric(_series_or_default(data, "total_cost"), errors="coerce").fillna(0.0)
    data["reason"] = _series_or_default(data, "reason").astype(str)
    data["order_id"] = _series_or_default(data, "order_id").astype(str)
    data["decision_id"] = _series_or_default(data, "decision_id").astype(str)
    data["position_state"] = _series_or_default(data, "position_state").astype(str)
    data["position_exit_reason"] = _series_or_default(data, "position_exit_reason").astype(str)
    data["add_layer"] = pd.to_numeric(_series_or_default(data, "add_layer"), errors="coerce")
    data["entry_matrix_score"] = pd.to_numeric(_series_or_default(data, "entry_matrix_score"), errors="coerce")
    data = data[
        data["trade_date"].notna()
        & data["side"].isin(["buy", "sell"])
        & data["executed_shares"].gt(0.0)
        & data["price"].gt(0.0)
        & _series_or_default(data, "execution_status").astype(str).eq("filled")
    ].copy()
    if data.empty:
        return pd.DataFrame(), pd.DataFrame(), _empty_trade_summary(capital_profile)

    data = data.sort_values(["trade_date", "symbol", "side"]).reset_index(drop=True)
    latest_price_map = _latest_price_map(latest_prices)
    positions: dict[str, dict] = {}
    trade_rows: list[dict] = []
    unmatched_sell_rows: list[dict] = []
    trade_id = 0

    for _, row in data.iterrows():
        symbol = str(row["symbol"])
        shares = float(row["executed_shares"])
        cost_per_share = float(row["total_cost"]) / shares if shares > 0 else 0.0
        if row["side"] == "buy":
            buy_total_cost = shares * float(row["price"]) + float(row["total_cost"])
            position = positions.get(symbol)
            if position is None:
                positions[symbol] = {
                    "entry_date": pd.Timestamp(row["trade_date"]),
                    "shares": shares,
                    "total_cost": buy_total_cost,
                    "entry_reason": str(row.get("reason", "")),
                    "entry_order_id": str(row.get("order_id", "")),
                    "entry_decision_id": str(row.get("decision_id", "")),
                    "entry_matrix_score": row.get("entry_matrix_score", pd.NA),
                    "entry_add_layer": row.get("add_layer", pd.NA),
                    "add_layer_count": 1,
                }
            else:
                position["shares"] = float(position["shares"]) + shares
                position["total_cost"] = float(position["total_cost"]) + buy_total_cost
                position["add_layer_count"] = max(
                    int(position.get("add_layer_count", 1) or 1),
                    int(row.get("add_layer")) if pd.notna(row.get("add_layer")) else int(position.get("add_layer_count", 1) or 1) + 1,
                )
            continue

        position = positions.get(symbol)
        available_shares = float(position["shares"]) if position is not None else 0.0
        matched_shares = min(shares, available_shares)
        if matched_shares > 1e-12 and position is not None:
            avg_cost = float(position["total_cost"]) / max(float(position["shares"]), 1e-12)
            sell_net_proceeds = matched_shares * float(row["price"]) - matched_shares * cost_per_share
            realized_pnl_amount = sell_net_proceeds - matched_shares * avg_cost
            realized_pnl_pct = (
                realized_pnl_amount / (matched_shares * avg_cost)
                if avg_cost > 0.0
                else pd.NA
            )
            trade_id += 1
            entry_date = pd.Timestamp(position["entry_date"])
            exit_date = pd.Timestamp(row["trade_date"])
            trade_rows.append(
                {
                    "trade_id": f"trade_{trade_id}",
                    "symbol": symbol,
                    "entry_date": entry_date,
                    "exit_date": exit_date,
                    "entry_price": avg_cost,
                    "cost_basis": avg_cost,
                    "exit_price": float(row["price"]),
                    "exit_net_price": sell_net_proceeds / matched_shares,
                    "entry_shares": matched_shares,
                    "exit_shares": matched_shares,
                    "holding_days": int(max((exit_date - entry_date).days, 0)),
                    "realized_pnl_amount": float(realized_pnl_amount),
                    "realized_pnl_pct": realized_pnl_pct,
                    "is_win": bool(realized_pnl_amount > 0.0),
                    "entry_reason": str(position.get("entry_reason", "")),
                    "entry_order_id": str(position.get("entry_order_id", "")),
                    "entry_decision_id": str(position.get("entry_decision_id", "")),
                    "entry_matrix_score_at_buy": position.get("entry_matrix_score", pd.NA),
                    "entry_add_layer": position.get("entry_add_layer", pd.NA),
                    "add_layer_count": position.get("add_layer_count", 1),
                    "sell_reason": str(row.get("reason", "")),
                    "sell_order_id": str(row.get("order_id", "")),
                    "sell_decision_id": str(row.get("decision_id", "")),
                    "position_state_at_sell": str(row.get("position_state", "")),
                    "position_exit_reason_at_sell": str(row.get("position_exit_reason", "")),
                    "close_reason": str(row.get("reason", "")) or "sell_fill_weighted_cost",
                    "pairing_method": "weighted_average_cost",
                    "capital_profile": capital_profile,
                }
            )
            position["shares"] = float(position["shares"]) - matched_shares
            position["total_cost"] = max(float(position["total_cost"]) - matched_shares * avg_cost, 0.0)
            if float(position["shares"]) <= 1e-12:
                positions.pop(symbol, None)

        unmatched_shares = shares - matched_shares
        if unmatched_shares > 1e-12:
            unmatched_sell_rows.append(
                {
                    "trade_id": f"{symbol}_unmatched_sell_{len(unmatched_sell_rows) + 1}",
                    "symbol": symbol,
                    "entry_date": pd.NaT,
                    "exit_date": pd.Timestamp(row["trade_date"]),
                    "entry_price": pd.NA,
                    "cost_basis": pd.NA,
                    "exit_price": float(row["price"]),
                    "exit_net_price": float(row["price"]) - cost_per_share,
                    "entry_shares": 0.0,
                    "exit_shares": unmatched_shares,
                    "holding_days": pd.NA,
                    "realized_pnl_amount": pd.NA,
                    "realized_pnl_pct": pd.NA,
                    "is_win": pd.NA,
                    "entry_reason": "",
                    "entry_order_id": "",
                    "entry_decision_id": "",
                    "sell_reason": str(row.get("reason", "")),
                    "sell_order_id": str(row.get("order_id", "")),
                    "sell_decision_id": str(row.get("decision_id", "")),
                    "close_reason": "inventory_underflow",
                    "pairing_method": "weighted_average_cost",
                    "capital_profile": capital_profile,
                }
            )

    trade_pairs = pd.DataFrame(trade_rows + unmatched_sell_rows)
    open_rows: list[dict] = []
    valuation_date = pd.Timestamp(data["trade_date"].max())
    for symbol, position in positions.items():
        total_shares = float(position.get("shares", 0.0) or 0.0)
        if total_shares <= 1e-12:
            continue
        avg_cost = float(position.get("total_cost", 0.0) or 0.0) / max(total_shares, 1e-12)
        latest_price = latest_price_map.get(symbol, pd.NA)
        market_value = float(total_shares * latest_price) if pd.notna(latest_price) else pd.NA
        unrealized_pnl_amount = (
            float(total_shares * (latest_price - avg_cost))
            if pd.notna(latest_price)
            else pd.NA
        )
        unrealized_pnl_pct = (
            unrealized_pnl_amount / float(total_shares * avg_cost)
            if pd.notna(unrealized_pnl_amount) and avg_cost > 0.0
            else pd.NA
        )
        open_rows.append(
            {
                "symbol": symbol,
                "entry_date": pd.Timestamp(position["entry_date"]),
                "avg_cost": float(avg_cost),
                "shares": total_shares,
                "latest_price": latest_price,
                "market_value": market_value,
                "unrealized_pnl_amount": unrealized_pnl_amount,
                "unrealized_pnl_pct": unrealized_pnl_pct,
                "valuation_date": valuation_date,
                "entry_reason": str(position.get("entry_reason", "")),
                "entry_order_id": str(position.get("entry_order_id", "")),
                "entry_decision_id": str(position.get("entry_decision_id", "")),
                "entry_matrix_score_at_buy": position.get("entry_matrix_score", pd.NA),
                "entry_add_layer": position.get("entry_add_layer", pd.NA),
                "add_layer_count": position.get("add_layer_count", 1),
                "pairing_method": "weighted_average_cost",
                "capital_profile": capital_profile,
            }
        )
    open_positions = pd.DataFrame(open_rows)
    summary = _trade_summary(trade_pairs, open_positions, capital_profile)
    return trade_pairs, open_positions, summary


def _latest_price_map(latest_prices: pd.DataFrame | None) -> dict[str, float]:
    if latest_prices is None or latest_prices.empty:
        return {}
    data = latest_prices.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    data["trade_close"] = pd.to_numeric(data.get("trade_close"), errors="coerce")
    data = data.dropna(subset=["date", "symbol", "trade_close"]).sort_values(["symbol", "date"])
    latest = data.groupby("symbol", as_index=False).tail(1)
    return dict(zip(latest["symbol"].astype(str), latest["trade_close"].astype(float)))


def _series_or_default(frame: pd.DataFrame, column_name: str) -> pd.Series:
    if column_name in frame.columns:
        return frame[column_name]
    return pd.Series(pd.NA, index=frame.index)


def _trade_summary(trade_pairs: pd.DataFrame, open_positions: pd.DataFrame, capital_profile: str) -> dict:
    valid_closed = trade_pairs[trade_pairs.get("realized_pnl_amount").notna()].copy() if not trade_pairs.empty else pd.DataFrame()
    pnl = pd.to_numeric(valid_closed.get("realized_pnl_amount", pd.Series(dtype=float)), errors="coerce").dropna()
    win_pnl = pnl[pnl > 0.0]
    loss_pnl = pnl[pnl < 0.0]
    wins = (
        int(pnl.gt(0.0).sum())
        if not valid_closed.empty
        else 0
    )
    losses = (
        int(pnl.lt(0.0).sum())
        if not valid_closed.empty
        else 0
    )
    trade_count = int(len(pnl))
    trade_win_rate = wins / trade_count if trade_count else pd.NA
    gross_profit = float(win_pnl.sum()) if trade_count else 0.0
    gross_loss = float(loss_pnl.sum()) if trade_count else 0.0
    avg_win = float(win_pnl.mean()) if len(win_pnl) else pd.NA
    avg_loss = float(loss_pnl.mean()) if len(loss_pnl) else pd.NA
    payoff_ratio = (
        float(avg_win / abs(avg_loss))
        if pd.notna(avg_win) and pd.notna(avg_loss) and abs(float(avg_loss)) > 1e-12
        else pd.NA
    )
    profit_factor = (
        float(gross_profit / abs(gross_loss))
        if abs(gross_loss) > 1e-12
        else pd.NA
    )
    return {
        "capital_profile": capital_profile,
        "realized_trade_count": trade_count,
        "winning_trade_count": wins,
        "losing_trade_count": losses,
        "trade_win_rate": trade_win_rate,
        "closed_trade_win_rate": trade_win_rate,
        "realized_pnl_amount": float(pnl.sum()) if trade_count else 0.0,
        "realized_pnl": float(pnl.sum()) if trade_count else 0.0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "profit_factor": profit_factor,
        "unrealized_pnl_amount": float(pd.to_numeric(open_positions.get("unrealized_pnl_amount"), errors="coerce").fillna(0.0).sum()) if not open_positions.empty else 0.0,
        "open_position_count": int(len(open_positions)),
        "inventory_underflow_count": int(trade_pairs.get("close_reason", pd.Series(dtype=str)).astype(str).eq("inventory_underflow").sum()) if not trade_pairs.empty else 0,
    }


def _empty_trade_summary(capital_profile: str) -> dict:
    return {
        "capital_profile": capital_profile,
        "realized_trade_count": 0,
        "winning_trade_count": 0,
        "losing_trade_count": 0,
        "trade_win_rate": pd.NA,
        "closed_trade_win_rate": pd.NA,
        "realized_pnl_amount": 0.0,
        "realized_pnl": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "avg_win": pd.NA,
        "avg_loss": pd.NA,
        "payoff_ratio": pd.NA,
        "profit_factor": pd.NA,
        "unrealized_pnl_amount": 0.0,
        "open_position_count": 0,
        "inventory_underflow_count": 0,
    }
