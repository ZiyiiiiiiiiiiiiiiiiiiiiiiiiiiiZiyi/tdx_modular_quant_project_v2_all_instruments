"""Exposure, weighting, and account audit helpers for governance backtests."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.accounting import build_exposure_snapshot


def record_exposure(runner, date, daily):
    rows = []
    locked_symbols = runner.engine.pending_orders.locked_symbols()
    total_position_value = 0.0
    for symbol, position in runner.positions.items():
        mark = runner.price_ledger.mark(symbol, as_of=date)
        price = float(mark.price) if mark is not None else 0.0
        market_value = float(position.shares) * price
        total_position_value += market_value
        lifecycle = runner._mark_lifecycle(symbol, date=date, price=price)
        rows.append(
            {
                "symbol": symbol,
                "shares": position.shares,
                "price": price,
                "market_value": market_value,
                **lifecycle,
                "lock_days": runner._symbol_lock_days(symbol) if symbol in locked_symbols else 0,
                "stale_days": mark.stale_days if mark is not None else pd.NA,
                "valuation_source": mark.valuation_source if mark is not None else "missing_mark",
                "stale_haircut_ratio": mark.stale_haircut_ratio if mark is not None else 1.0,
            }
        )
    snapshot = build_exposure_snapshot(
        pd.DataFrame(rows, columns=["symbol", "shares", "price", "lock_days"]),
        cash=runner.cash,
        target_exposure=0.0,
    )
    nominal_values = pd.Series(
        [float(row["shares"]) * float(row["price"]) for row in rows],
        dtype=float,
    )
    invested_value = float(total_position_value)
    sleeve_weights = (
        nominal_values / invested_value
        if invested_value > 0 and not nominal_values.empty
        else pd.Series(dtype=float)
    )
    nominal_nav = float(snapshot.get("nominal_nav", 0.0) or 0.0)
    account_weights = (
        nominal_values / nominal_nav
        if nominal_nav > 0 and not nominal_values.empty
        else pd.Series(dtype=float)
    )
    sorted_sleeve_weights = sleeve_weights.sort_values(ascending=False).reset_index(drop=True)
    sorted_account_weights = account_weights.sort_values(ascending=False).reset_index(drop=True)
    snapshot["top1_sleeve_weight"] = float(sorted_sleeve_weights.iloc[0]) if len(sorted_sleeve_weights) else 0.0
    snapshot["top5_sleeve_weight_sum"] = float(sorted_sleeve_weights.head(5).sum()) if len(sorted_sleeve_weights) else 0.0
    sleeve_weight_square_sum = float(sorted_sleeve_weights.pow(2).sum()) if len(sorted_sleeve_weights) else 0.0
    snapshot["sleeve_effective_n"] = float(1.0 / sleeve_weight_square_sum) if sleeve_weight_square_sum > 0 else 0.0
    snapshot["top1_account_weight"] = float(sorted_account_weights.iloc[0]) if len(sorted_account_weights) else 0.0
    snapshot["top5_account_weight_sum"] = float(sorted_account_weights.head(5).sum()) if len(sorted_account_weights) else 0.0
    cash_weight = max(float(runner.cash) / nominal_nav, 0.0) if nominal_nav > 0 else 0.0
    # Account effective N includes cash as an account component. Omitting cash
    # made a 4% single-stock position report an impossible effective N above 600.
    snapshot["account_effective_n"] = _account_effective_n(sorted_account_weights, cash_weight=cash_weight)
    snapshot["top1_weight"] = snapshot["top1_sleeve_weight"]
    snapshot["top5_weight_sum"] = snapshot["top5_sleeve_weight_sum"]
    snapshot["effective_n"] = snapshot["sleeve_effective_n"]
    snapshot["weight_basis"] = "sleeve_weight_legacy"
    snapshot["holding_count"] = int(len(sorted_sleeve_weights))
    snapshot.update({"date": pd.Timestamp(date), "decision_id": f"gov_{pd.Timestamp(date).strftime('%Y%m%d')}", "safety_sell_flow_impact_estimate": 0.0})
    snapshot["stale_price_position_count"] = sum(int(row["valuation_source"] == "last_known_close") for row in rows)
    snapshot["missing_price_position_count"] = sum(int(row["valuation_source"] == "missing_mark") for row in rows)
    snapshot["cash"] = float(runner.cash)
    snapshot["invested_value"] = float(total_position_value)
    runner._last_position_mark_rows = rows
    if rows and not runner.shadow_fast_mode:
        invested_nav = max(float(total_position_value), 1e-12)
        account_nav = max(nominal_nav, 1e-12)
        for row in rows:
            sleeve_weight = float(row["market_value"]) / invested_nav if invested_nav > 0 else 0.0
            account_weight = float(row["market_value"]) / account_nav if account_nav > 0 else 0.0
            runner.holdings_rows.append(
                {
                    "date": pd.Timestamp(date),
                    "decision_id": snapshot["decision_id"],
                    "symbol": row["symbol"],
                    "shares": float(row["shares"]),
                    "price": float(row["price"]),
                    "market_value": float(row["market_value"]),
                    "account_weight": account_weight,
                    "sleeve_weight": sleeve_weight,
                    "portfolio_exposure": float(total_position_value) / account_nav if account_nav > 0 else 0.0,
                    "weight": sleeve_weight,
                    "weight_basis": "sleeve_weight_legacy",
                    "entry_date": row.get("entry_date", pd.NaT),
                    "entry_price": row.get("entry_price", pd.NA),
                    "unrealized_return": row.get("unrealized_return", pd.NA),
                    "mfe": row.get("mfe", pd.NA),
                    "mae": row.get("mae", pd.NA),
                    "giveback_from_peak": row.get("giveback_from_peak", pd.NA),
                    "trend_direction_score": row.get("trend_direction_score", pd.NA),
                    "peak_decay_score": row.get("peak_decay_score", pd.NA),
                    "profit_protection_pressure": row.get("profit_protection_pressure", pd.NA),
                    "dynamic_giveback_limit": row.get("dynamic_giveback_limit", pd.NA),
                    "future_loss_risk_score": row.get("future_loss_risk_score", pd.NA),
                    "profit_giveback_flag": row.get("profit_giveback_flag", False),
                    "post_entry_failure_flag": row.get("post_entry_failure_flag", False),
                    "lock_days": int(row["lock_days"]),
                    "stale_days": row["stale_days"],
                    "valuation_source": row["valuation_source"],
                    "stale_haircut_ratio": row["stale_haircut_ratio"],
                }
            )
    runner.exposure_rows.append(snapshot)
    return snapshot


def _account_effective_n(account_weights: pd.Series, *, cash_weight: float) -> float:
    square_sum = float(pd.to_numeric(account_weights, errors="coerce").fillna(0.0).pow(2).sum())
    square_sum += max(float(cash_weight), 0.0) ** 2
    return float(1.0 / square_sum) if square_sum > 0 else 0.0

def current_weights(runner, daily, nominal_nav):
    if nominal_nav <= 0:
        return {}
    weights = {}
    for symbol, position in runner.positions.items():
        mark = runner.price_ledger.mark(symbol, as_of=daily["date"].iloc[0])
        if mark is not None:
            weights[symbol] = position.shares * float(mark.price) / nominal_nav
    return weights


def record_account_audit(runner, date):
    exposure = runner.exposure_rows[-1]
    marked_position_value = sum(
        float(row["shares"]) * float(row["price"])
        for row in runner._last_position_mark_rows
    )
    independently_rebuilt_nav = float(runner.cash) + marked_position_value
    reconciliation_error = float(exposure["nominal_nav"]) - independently_rebuilt_nav
    runner.account_audit_rows.append(
        {
            "date": pd.Timestamp(date),
            "decision_id": exposure["decision_id"],
            "cash": float(runner.cash),
            "marked_position_value": marked_position_value,
            "nominal_nav": float(exposure["nominal_nav"]),
            "independently_rebuilt_nav": independently_rebuilt_nav,
            "liquidatable_nav": float(exposure["liquidatable_nav"]),
            "reconciliation_error": reconciliation_error,
            "reconciliation_passed": abs(reconciliation_error) <= 1e-8,
            "stale_price_position_count": exposure["stale_price_position_count"],
            "missing_price_position_count": exposure["missing_price_position_count"],
        }
    )


def latest_price_frame_for_trade_pairing(runner, execution_ledger: pd.DataFrame) -> pd.DataFrame:
    if execution_ledger is None or execution_ledger.empty or "symbol" not in execution_ledger.columns:
        return pd.DataFrame(columns=["date", "symbol", "trade_close"])
    price_col = "trade_close" if "trade_close" in runner.features.columns else "close"
    required = {"date", "symbol", price_col}
    if not required.issubset(set(runner.features.columns)):
        return pd.DataFrame(columns=["date", "symbol", "trade_close"])
    symbols = set(execution_ledger["symbol"].astype(str).dropna().unique())
    if not symbols:
        return pd.DataFrame(columns=["date", "symbol", "trade_close"])
    data = runner.features.loc[
        runner.features["symbol"].astype(str).isin(symbols),
        ["date", "symbol", price_col],
    ].copy()
    if price_col != "trade_close":
        data = data.rename(columns={price_col: "trade_close"})
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["trade_close"] = pd.to_numeric(data["trade_close"], errors="coerce")
    return data.dropna(subset=["date", "symbol", "trade_close"])


def trade_pairing_capital_profile(runner) -> str:
    profile_name = str(runner.capital_profile.get("name", "") or "").strip()
    if profile_name:
        return f"{runner.governance_variant}__{profile_name}"
    return str(runner.governance_variant)

