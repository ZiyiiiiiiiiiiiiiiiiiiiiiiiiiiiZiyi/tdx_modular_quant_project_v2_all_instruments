"""Broker-minimum and market-friction stress for SCAP-V1 closed trades."""
from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from config import COMMISSION_RATE
from functions.execution.fee_schedule import commission_cost


SCAP_COST_STRESS_VERSION = "scap_cost_stress_v1"
SCAP_COST_STRESS_COLUMNS = [
    "minimum_commission",
    "market_cost_multiplier",
    "closed_trade_count",
    "gross_pnl_amount",
    "stressed_total_cost",
    "stressed_net_pnl_amount",
    "profit_factor_after_cost",
    "winning_trade_share_after_cost",
    "cost_to_abs_gross_pnl",
    "cost_to_initial_capital",
    "scenario_profitable",
    "scap_cost_stress_version",
]


def build_scap_cost_stress_report(
    trade_pairs: pd.DataFrame,
    execution_ledger: pd.DataFrame,
    *,
    initial_cash: float,
    minimum_commissions: Iterable[float] = (0.0, 1.0, 5.0),
    market_cost_multipliers: Iterable[float] = (1.0, 1.5, 2.0),
    commission_rate: float = COMMISSION_RATE,
) -> pd.DataFrame:
    """Reprice every closed trade under registered small-account cost cases."""
    minimums = tuple(float(value) for value in minimum_commissions)
    multipliers = tuple(float(value) for value in market_cost_multipliers)
    if not minimums or min(minimums) < 0:
        raise ValueError("minimum commissions must be non-empty and non-negative")
    if not multipliers or min(multipliers) < 0:
        raise ValueError("market cost multipliers must be non-empty and non-negative")
    if float(initial_cash) <= 0:
        raise ValueError("initial_cash must be positive")
    # A short smoke run can legitimately finish without a closed trade.  In
    # that case there is nothing to join or reprice, and an empty execution
    # frame is not required to carry the full filled-order schema.
    if trade_pairs is None or trade_pairs.empty:
        return pd.DataFrame(columns=SCAP_COST_STRESS_COLUMNS)
    pair_required = {"entry_order_id", "sell_order_id", "entry_shares", "realized_pnl_amount"}
    ledger_required = {
        "order_id", "side", "price", "executed_shares", "execution_status",
        "stamp_duty_cost", "transfer_fee_cost", "slippage_cost", "market_impact_cost",
    }
    missing_pairs = sorted(pair_required - set(trade_pairs.columns))
    missing_ledger = sorted(ledger_required - set(execution_ledger.columns))
    if missing_pairs or missing_ledger:
        raise ValueError(f"SCAP cost stress missing columns: pairs={missing_pairs}, ledger={missing_ledger}")
    trades = _closed_trade_cost_inputs(trade_pairs, execution_ledger)
    if trades.empty:
        return pd.DataFrame(columns=SCAP_COST_STRESS_COLUMNS)
    rows = []
    for minimum in minimums:
        for multiplier in multipliers:
            scenario = trades.copy()
            scenario["buy_commission"] = scenario["buy_notional"].map(
                lambda value: commission_cost(value, rate=commission_rate, minimum=minimum)
            )
            scenario["sell_commission"] = scenario["sell_notional"].map(
                lambda value: commission_cost(value, rate=commission_rate, minimum=minimum)
            )
            scenario["stressed_cost"] = (
                scenario["buy_commission"]
                + scenario["sell_commission"]
                + scenario["fixed_tax_and_transfer"]
                + multiplier * scenario["market_friction_cost"]
            )
            scenario["stressed_net"] = scenario["gross_pnl"] - scenario["stressed_cost"]
            gross_profit = float(scenario.loc[scenario["stressed_net"] > 0.0, "stressed_net"].sum())
            gross_loss = float(scenario.loc[scenario["stressed_net"] < 0.0, "stressed_net"].sum())
            profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0.0 else np.inf
            stressed_cost = float(scenario["stressed_cost"].sum())
            gross_pnl = float(scenario["gross_pnl"].sum())
            rows.append({
                "minimum_commission": minimum,
                "market_cost_multiplier": multiplier,
                "closed_trade_count": int(len(scenario)),
                "gross_pnl_amount": gross_pnl,
                "stressed_total_cost": stressed_cost,
                "stressed_net_pnl_amount": float(scenario["stressed_net"].sum()),
                "profit_factor_after_cost": profit_factor,
                "winning_trade_share_after_cost": float((scenario["stressed_net"] > 0.0).mean()),
                "cost_to_abs_gross_pnl": stressed_cost / max(float(scenario["gross_pnl"].abs().sum()), 1e-12),
                "cost_to_initial_capital": stressed_cost / float(initial_cash),
                "scenario_profitable": bool(float(scenario["stressed_net"].sum()) > 0.0 and profit_factor > 1.0),
                "scap_cost_stress_version": SCAP_COST_STRESS_VERSION,
            })
    return pd.DataFrame(rows, columns=SCAP_COST_STRESS_COLUMNS)


def _closed_trade_cost_inputs(trade_pairs: pd.DataFrame, execution_ledger: pd.DataFrame) -> pd.DataFrame:
    ledger = execution_ledger.copy()
    ledger = ledger[ledger["execution_status"].astype(str).eq("filled")].copy()
    ledger["order_id"] = ledger["order_id"].astype(str)
    numeric = [
        "price", "executed_shares", "stamp_duty_cost", "transfer_fee_cost",
        "slippage_cost", "market_impact_cost",
    ]
    for column in numeric:
        ledger[column] = pd.to_numeric(ledger[column], errors="coerce").fillna(0.0)
    lookup = ledger.drop_duplicates("order_id", keep="last").set_index("order_id")
    rows = []
    for pair in trade_pairs.itertuples(index=False):
        if pd.isna(getattr(pair, "realized_pnl_amount")):
            continue
        buy_id = str(getattr(pair, "entry_order_id"))
        sell_id = str(getattr(pair, "sell_order_id"))
        if buy_id not in lookup.index or sell_id not in lookup.index:
            continue
        buy = lookup.loc[buy_id]
        sell = lookup.loc[sell_id]
        if str(buy["side"]).lower() != "buy" or str(sell["side"]).lower() != "sell":
            continue
        shares = float(getattr(pair, "entry_shares"))
        if shares <= 0:
            continue
        buy_notional = shares * float(buy["price"])
        sell_notional = shares * float(sell["price"])
        rows.append({
            "buy_notional": buy_notional,
            "sell_notional": sell_notional,
            "gross_pnl": sell_notional - buy_notional,
            "fixed_tax_and_transfer": (
                float(buy["stamp_duty_cost"]) + float(sell["stamp_duty_cost"])
                + float(buy["transfer_fee_cost"]) + float(sell["transfer_fee_cost"])
            ),
            "market_friction_cost": (
                float(buy["slippage_cost"]) + float(sell["slippage_cost"])
                + float(buy["market_impact_cost"]) + float(sell["market_impact_cost"])
            ),
        })
    return pd.DataFrame(rows)
