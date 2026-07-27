"""Closed-trade transaction-cost and market-capacity stress diagnostics."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


COST_CAPACITY_VERSION = "cost_capacity_stress_v1"


def build_cost_capacity_stress_reports(
    trade_pairs: pd.DataFrame,
    execution_ledger: pd.DataFrame,
    *,
    cost_multipliers: Iterable[float] = (0.0, 1.0, 2.0, 3.0),
    capital_scales: Iterable[float] = (1.0, 2.0, 5.0, 10.0),
    impact_sqrt_coefficient: float,
    impact_max_rate: float,
    maximum_participation_rate: float = 0.01,
    minimum_closed_trades: int = 10,
) -> dict[str, pd.DataFrame]:
    """Reprice realized trades under fee/slippage and scale stress.

    For trade i and capital scale s:
      gross_i(s) = s * shares_i * (sell_i - buy_i)
      fee_i(s,m) = s * m * observed_fee_i
      impact_i(s) = s * notional_i * min(k*sqrt(s*participation_i), cap)
      stressed_net_i = gross_i(s) - fee_i(s,m) - impact_i(s)

    The square-root impact is deliberately reported as an uncalibrated proxy.
    """
    multipliers = tuple(float(value) for value in cost_multipliers)
    scales = tuple(float(value) for value in capital_scales)
    if not multipliers or min(multipliers) < 0 or not scales or min(scales) <= 0:
        raise ValueError("cost multipliers and capital scales must be non-empty and non-negative/positive")
    if float(impact_sqrt_coefficient) < 0 or float(impact_max_rate) < 0:
        raise ValueError("impact parameters cannot be negative")
    if not 0 < float(maximum_participation_rate) <= 1:
        raise ValueError("maximum_participation_rate must be in (0, 1]")
    pair_required = {"trade_id", "entry_order_id", "sell_order_id", "entry_shares", "realized_pnl_amount"}
    ledger_required = {"order_id", "side", "price", "executed_shares", "total_cost", "market_amount", "execution_status"}
    missing_pairs = sorted(pair_required - set(trade_pairs.columns))
    missing_ledger = sorted(ledger_required - set(execution_ledger.columns))
    if missing_pairs or missing_ledger:
        raise ValueError(f"cost audit missing columns: pairs={missing_pairs}, ledger={missing_ledger}")
    trades = _reconstruct_trades(trade_pairs, execution_ledger)
    if trades.empty:
        summary = _summary("insufficient_closed_trades", 0)
        return _reports(summary, pd.DataFrame(), trades)

    scenario_rows = []
    for scale in scales:
        scaled_participation = (trades["maximum_leg_participation_rate"] * scale).clip(lower=0.0)
        impact_rate = np.minimum(
            float(impact_sqrt_coefficient) * np.sqrt(scaled_participation),
            float(impact_max_rate),
        )
        gross = trades["gross_pnl_amount"] * scale
        scaled_turnover = trades["round_trip_notional"] * scale
        impact_cost = scaled_turnover * impact_rate
        for multiplier in multipliers:
            fee_cost = trades["observed_total_cost"] * scale * multiplier
            stressed = gross - fee_cost - impact_cost
            scenario_rows.append({
                "capital_scale": scale, "cost_multiplier": multiplier,
                "closed_trade_count": len(trades), "gross_pnl_amount": float(gross.sum()),
                "stressed_fee_cost": float(fee_cost.sum()),
                "uncalibrated_impact_cost": float(impact_cost.sum()),
                "stressed_net_pnl_amount": float(stressed.sum()),
                "stressed_return_on_round_trip_notional": float(stressed.sum() / scaled_turnover.sum()) if scaled_turnover.sum() > 0 else np.nan,
                "winning_trade_share": float((stressed > 0).mean()),
                "p95_scaled_participation_rate": float(scaled_participation.quantile(.95)),
                "maximum_scaled_participation_rate": float(scaled_participation.max()),
                "participation_limit_breached": bool((scaled_participation > float(maximum_participation_rate)).any()),
                "impact_model_calibrated": False,
                "cost_capacity_version": COST_CAPACITY_VERSION,
            })
    scenarios = pd.DataFrame(scenario_rows)
    observed_cost = float(trades["observed_total_cost"].sum())
    gross_pnl = float(trades["gross_pnl_amount"].sum())
    break_even = gross_pnl / observed_cost if observed_cost > 0 else np.inf
    base = scenarios[(scenarios["capital_scale"].eq(1.0)) & (scenarios["cost_multiplier"].eq(1.0))]
    status = "insufficient_closed_trades" if len(trades) < int(minimum_closed_trades) else "cost_capacity_stress_pass"
    if status != "insufficient_closed_trades" and (base.empty or float(base.iloc[0]["stressed_net_pnl_amount"]) <= 0):
        status = "fails_observed_cost_case"
    if status == "cost_capacity_stress_pass" and bool(base.iloc[0]["participation_limit_breached"]):
        status = "fails_base_capacity_limit"
    summary = _summary(
        status, len(trades), aggregate_gross_pnl=gross_pnl,
        aggregate_observed_cost=observed_cost,
        observed_net_pnl_reconstructed=gross_pnl - observed_cost,
        ledger_realized_pnl=float(pd.to_numeric(trades["ledger_realized_pnl"], errors="coerce").sum()),
        break_even_cost_multiplier=break_even,
    )
    return _reports(summary, scenarios, trades)


def _reconstruct_trades(pairs, ledger):
    orders = ledger.copy()
    orders = orders[orders["execution_status"].astype(str).eq("filled")].copy()
    orders["order_id"] = orders["order_id"].astype(str)
    for column in ("price", "executed_shares", "total_cost", "market_amount"):
        orders[column] = pd.to_numeric(orders[column], errors="coerce")
    lookup = orders.drop_duplicates("order_id", keep="last").set_index("order_id")
    rows = []
    for pair in pairs.itertuples(index=False):
        if pd.isna(getattr(pair, "realized_pnl_amount")):
            continue
        buy_id, sell_id = str(getattr(pair, "entry_order_id")), str(getattr(pair, "sell_order_id"))
        if buy_id not in lookup.index or sell_id not in lookup.index:
            continue
        buy, sell = lookup.loc[buy_id], lookup.loc[sell_id]
        if str(buy["side"]).lower() != "buy" or str(sell["side"]).lower() != "sell":
            continue
        shares = float(getattr(pair, "entry_shares"))
        if shares <= 0 or not np.isfinite(shares):
            continue
        buy_price, sell_price = float(buy["price"]), float(sell["price"])
        buy_notional, sell_notional = shares * buy_price, shares * sell_price
        buy_market, sell_market = float(buy["market_amount"]), float(sell["market_amount"])
        buy_part = buy_notional / buy_market if buy_market > 0 else np.nan
        sell_part = sell_notional / sell_market if sell_market > 0 else np.nan
        rows.append({
            "trade_id": str(getattr(pair, "trade_id")), "entry_order_id": buy_id, "sell_order_id": sell_id,
            "shares": shares, "buy_price": buy_price, "sell_price": sell_price,
            "gross_pnl_amount": shares * (sell_price - buy_price),
            "observed_total_cost": float(buy["total_cost"]) + float(sell["total_cost"]),
            "ledger_realized_pnl": float(getattr(pair, "realized_pnl_amount")),
            "round_trip_notional": buy_notional + sell_notional,
            "buy_participation_rate": buy_part, "sell_participation_rate": sell_part,
            "maximum_leg_participation_rate": np.nanmax([buy_part, sell_part]) if np.isfinite([buy_part, sell_part]).any() else np.nan,
            "cost_capacity_version": COST_CAPACITY_VERSION,
        })
    return pd.DataFrame(rows)


def _summary(status, trade_count, **values):
    return pd.DataFrame([{**{
        "closed_trade_count": int(trade_count), "evidence_status": status,
        "production_eligible": status == "cost_capacity_stress_pass",
        "impact_model_calibrated": False, "cost_capacity_version": COST_CAPACITY_VERSION,
    }, **values}])


def _reports(summary, scenarios, trades):
    return {
        "governance_failure_lab_cost_capacity_summary": summary,
        "governance_failure_lab_cost_capacity_scenarios": scenarios,
        "governance_failure_lab_cost_capacity_trade_reconstruction": trades,
    }
