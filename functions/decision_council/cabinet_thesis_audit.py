"""Counterfactual diagnostics for cabinet-native paper lifecycle exits."""
from __future__ import annotations

import pandas as pd


def build_cabinet_thesis_counterfactual(
    position_states: pd.DataFrame,
    feature_data: pd.DataFrame,
    *,
    horizons=(5, 10, 20),
) -> pd.DataFrame:
    empty = _empty_counterfactual(horizons)
    if position_states is None or position_states.empty or feature_data is None or feature_data.empty:
        return empty
    required = {"date", "symbol", "paper_exit_reason"}
    if not required.issubset(position_states.columns):
        return empty
    signals = position_states.copy()
    signals["date"] = pd.to_datetime(signals["date"], errors="coerce")
    signals = signals[
        signals["paper_exit_reason"].astype(str).ne("")
        & signals["symbol"].astype(str).ne("")
    ].drop_duplicates(["date", "symbol", "paper_exit_reason"])
    if signals.empty:
        return empty
    signal_symbols = set(signals["symbol"].astype(str))
    symbol_values = feature_data["symbol"].astype(str)
    price_columns = [column for column in ("date", "symbol", "close_nominal", "close") if column in feature_data.columns]
    if not {"date", "symbol"}.issubset(price_columns) or not ({"close_nominal", "close"} & set(price_columns)):
        return empty
    prices = feature_data.loc[symbol_values.isin(signal_symbols), price_columns].copy()
    price_col = "close_nominal" if "close_nominal" in prices.columns else "close"
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices[price_col] = pd.to_numeric(prices[price_col], errors="coerce")
    prices = prices.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"], keep="last")
    for horizon in horizons:
        prices[f"counterfactual_return_{int(horizon)}d"] = (
            prices.groupby("symbol", sort=False)[price_col].shift(-int(horizon)) / prices[price_col] - 1.0
        )
    keep = ["date", "symbol", price_col] + [f"counterfactual_return_{int(h)}d" for h in horizons]
    result = signals.merge(prices[keep], on=["date", "symbol"], how="left", validate="many_to_one")
    result = result.rename(columns={price_col: "paper_exit_signal_price"})
    result["counterfactual_interpretation"] = "negative_return_means_paper_exit_would_have_avoided_loss"
    return result


def _empty_counterfactual(horizons) -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "date", "symbol", "paper_exit_reason", "paper_exit_signal_price",
        *(f"counterfactual_return_{int(horizon)}d" for horizon in horizons),
        "counterfactual_interpretation",
    ])
