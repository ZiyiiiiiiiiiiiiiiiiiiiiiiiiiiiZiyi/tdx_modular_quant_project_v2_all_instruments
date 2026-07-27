# -*- coding: utf-8 -*-
from __future__ import annotations

import pandas as pd

from functions.execution.cost_model import estimate_trade_costs


TRADE_PAIR_COLUMNS = (
    "trade_id", "symbol", "entry_date", "exit_date", "entry_price", "cost_basis",
    "exit_price", "exit_net_price", "entry_shares", "exit_shares", "holding_days",
    "realized_pnl_before_corporate_actions", "corporate_action_cash_allocated",
    "stock_dividend_shares_allocated", "realized_pnl_amount",
    "realized_pnl_pct", "is_win", "entry_reason",
    "entry_order_id", "entry_decision_id", "entry_matrix_score_at_buy",
    "entry_add_layer", "add_layer_count", "sell_reason", "sell_order_id",
    "sell_decision_id", "position_state_at_sell", "position_exit_reason_at_sell",
    "close_reason", "pairing_method", "total_return_contract", "capital_profile",
)
OPEN_POSITION_COLUMNS = (
    "symbol", "entry_date", "avg_cost", "shares", "latest_price", "market_value",
    "unrealized_pnl_amount", "unrealized_pnl_pct", "valuation_date", "entry_reason",
    "corporate_action_cash_accrued", "stock_dividend_shares_accrued",
    "entry_order_id", "entry_decision_id", "entry_matrix_score_at_buy",
    "entry_add_layer", "add_layer_count", "pairing_method", "capital_profile",
)


def build_trade_pairing_ledgers(
    order_ledger: pd.DataFrame,
    latest_prices: pd.DataFrame | None = None,
    *,
    capital_profile: str = "",
    corporate_action_ledger: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if order_ledger is None or order_ledger.empty:
        return _empty_trade_pairs(), _empty_open_positions(), _empty_trade_summary(capital_profile)

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
        return _empty_trade_pairs(), _empty_open_positions(), _empty_trade_summary(capital_profile)

    data = data.sort_values(["trade_date", "symbol", "side"]).reset_index(drop=True)
    latest_price_map, latest_price_date_map = _latest_price_snapshot(latest_prices)
    positions: dict[str, dict] = {}
    trade_rows: list[dict] = []
    unmatched_sell_rows: list[dict] = []
    trade_id = 0
    actions = _prepare_corporate_actions(corporate_action_ledger)
    action_cursor = 0

    def apply_actions_through(action_date) -> None:
        nonlocal action_cursor
        while (
            action_cursor < len(actions)
            and pd.Timestamp(actions.iloc[action_cursor]["date"])
            <= pd.Timestamp(action_date)
        ):
            event = actions.iloc[action_cursor]
            position = positions.get(str(event["symbol"]))
            if position is not None:
                cash_delta = float(event["cash_delta"])
                stock_shares = float(event["stock_dividend_shares"])
                position["shares"] = float(position["shares"]) + stock_shares
                position["corporate_action_cash"] = (
                    float(position.get("corporate_action_cash", 0.0)) + cash_delta
                )
                position["stock_dividend_shares"] = (
                    float(position.get("stock_dividend_shares", 0.0)) + stock_shares
                )
            action_cursor += 1

    for _, row in data.iterrows():
        apply_actions_through(row["trade_date"])
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
                    "corporate_action_cash": 0.0,
                    "stock_dividend_shares": 0.0,
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
            realized_before_actions = sell_net_proceeds - matched_shares * avg_cost
            allocation_ratio = matched_shares / max(float(position["shares"]), 1e-12)
            corporate_action_cash = (
                float(position.get("corporate_action_cash", 0.0)) * allocation_ratio
            )
            stock_dividend_shares = (
                float(position.get("stock_dividend_shares", 0.0)) * allocation_ratio
            )
            realized_pnl_amount = realized_before_actions + corporate_action_cash
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
                    "realized_pnl_before_corporate_actions": float(
                        realized_before_actions
                    ),
                    "corporate_action_cash_allocated": float(corporate_action_cash),
                    "stock_dividend_shares_allocated": float(stock_dividend_shares),
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
                    "total_return_contract": "sale_net_proceeds_plus_corporate_action_cash_v1",
                    "capital_profile": capital_profile,
                }
            )
            position["shares"] = float(position["shares"]) - matched_shares
            position["total_cost"] = max(float(position["total_cost"]) - matched_shares * avg_cost, 0.0)
            position["corporate_action_cash"] = max(
                float(position.get("corporate_action_cash", 0.0))
                - corporate_action_cash,
                0.0,
            )
            position["stock_dividend_shares"] = max(
                float(position.get("stock_dividend_shares", 0.0))
                - stock_dividend_shares,
                0.0,
            )
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

    if len(data):
        apply_actions_through(pd.Timestamp.max)
    trade_pairs = pd.DataFrame(trade_rows + unmatched_sell_rows, columns=TRADE_PAIR_COLUMNS)
    open_rows: list[dict] = []
    for symbol, position in positions.items():
        total_shares = float(position.get("shares", 0.0) or 0.0)
        if total_shares <= 1e-12:
            continue
        avg_cost = float(position.get("total_cost", 0.0) or 0.0) / max(total_shares, 1e-12)
        latest_price = latest_price_map.get(symbol, pd.NA)
        market_value = float(total_shares * latest_price) if pd.notna(latest_price) else pd.NA
        corporate_action_cash = float(
            position.get("corporate_action_cash", 0.0) or 0.0
        )
        unrealized_pnl_amount = (
            float(total_shares * (latest_price - avg_cost)) + corporate_action_cash
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
                "valuation_date": latest_price_date_map.get(symbol, pd.NaT),
                "entry_reason": str(position.get("entry_reason", "")),
                "corporate_action_cash_accrued": corporate_action_cash,
                "stock_dividend_shares_accrued": float(
                    position.get("stock_dividend_shares", 0.0) or 0.0
                ),
                "entry_order_id": str(position.get("entry_order_id", "")),
                "entry_decision_id": str(position.get("entry_decision_id", "")),
                "entry_matrix_score_at_buy": position.get("entry_matrix_score", pd.NA),
                "entry_add_layer": position.get("entry_add_layer", pd.NA),
                "add_layer_count": position.get("add_layer_count", 1),
                "pairing_method": "weighted_average_cost",
                "capital_profile": capital_profile,
            }
        )
    open_positions = pd.DataFrame(open_rows, columns=OPEN_POSITION_COLUMNS)
    summary = _trade_summary(trade_pairs, open_positions, capital_profile)
    return trade_pairs, open_positions, summary


def _prepare_corporate_actions(actions: pd.DataFrame | None) -> pd.DataFrame:
    columns = ("date", "symbol", "cash_delta", "stock_dividend_shares")
    if actions is None or actions.empty:
        return pd.DataFrame(columns=columns)
    data = actions.copy()
    data["date"] = pd.to_datetime(_series_or_default(data, "date"), errors="coerce")
    data["symbol"] = _series_or_default(data, "symbol").astype(str)
    for column in ("cash_delta", "stock_dividend_shares"):
        data[column] = pd.to_numeric(
            _series_or_default(data, column), errors="coerce"
        ).fillna(0.0)
    return data.dropna(subset=["date"]).sort_values(
        ["date", "symbol"]
    ).reset_index(drop=True)[list(columns)]


def _latest_price_map(latest_prices: pd.DataFrame | None) -> dict[str, float]:
    prices, _ = _latest_price_snapshot(latest_prices)
    return prices


def _latest_price_snapshot(latest_prices: pd.DataFrame | None) -> tuple[dict[str, float], dict[str, pd.Timestamp]]:
    if latest_prices is None or latest_prices.empty:
        return {}, {}
    data = latest_prices.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    data["trade_close"] = pd.to_numeric(data.get("trade_close"), errors="coerce")
    data = data.dropna(subset=["date", "symbol", "trade_close"]).sort_values(["symbol", "date"])
    latest = data.groupby("symbol", as_index=False).tail(1)
    return (
        dict(zip(latest["symbol"].astype(str), latest["trade_close"].astype(float))),
        dict(zip(latest["symbol"].astype(str), pd.to_datetime(latest["date"]))),
    )


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
    unrealized_pnl = (
        float(
            pd.to_numeric(
                open_positions.get("unrealized_pnl_amount"), errors="coerce"
            )
            .fillna(0.0)
            .sum()
        )
        if not open_positions.empty
        else 0.0
    )
    estimated_exit_cost = 0.0
    if not open_positions.empty:
        cost_rows = open_positions[
            ["symbol", "latest_price", "shares"]
        ].copy()
        cost_rows = cost_rows[
            pd.to_numeric(cost_rows["latest_price"], errors="coerce").gt(0.0)
            & pd.to_numeric(cost_rows["shares"], errors="coerce").gt(0.0)
        ]
        if not cost_rows.empty:
            cost_input = pd.DataFrame(
                {
                    "symbol": cost_rows["symbol"].astype(str),
                    "side": "sell",
                    "price": pd.to_numeric(
                        cost_rows["latest_price"], errors="coerce"
                    ),
                    "target_shares": pd.to_numeric(
                        cost_rows["shares"], errors="coerce"
                    ),
                }
            )
            estimated_exit_cost = float(
                pd.to_numeric(
                    estimate_trade_costs(cost_input)["total_cost"],
                    errors="coerce",
                )
                .fillna(0.0)
                .sum()
            )
    total_return_pnl = float(pnl.sum()) + unrealized_pnl - estimated_exit_cost
    censored_ratio = (
        int(len(open_positions)) / max(int(len(open_positions)) + trade_count, 1)
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
        "unrealized_pnl_amount": unrealized_pnl,
        "estimated_terminal_exit_cost": estimated_exit_cost,
        "terminal_total_return_pnl_after_exit_cost": total_return_pnl,
        "terminal_position_policy": "mark_open_positions_no_forced_liquidation",
        "trade_metric_censoring_ratio": censored_ratio,
        "trade_metric_state": (
            "censored"
            if censored_ratio > 0.25
            else ("closed_only" if trade_count else "insufficient")
        ),
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
        "estimated_terminal_exit_cost": 0.0,
        "terminal_total_return_pnl_after_exit_cost": 0.0,
        "terminal_position_policy": "mark_open_positions_no_forced_liquidation",
        "trade_metric_censoring_ratio": 0.0,
        "trade_metric_state": "insufficient",
        "open_position_count": 0,
        "inventory_underflow_count": 0,
    }


def _empty_trade_pairs() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_PAIR_COLUMNS)


def _empty_open_positions() -> pd.DataFrame:
    return pd.DataFrame(columns=OPEN_POSITION_COLUMNS)
