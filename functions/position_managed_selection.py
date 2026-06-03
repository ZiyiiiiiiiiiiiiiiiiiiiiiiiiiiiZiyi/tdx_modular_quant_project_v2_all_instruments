"""Generate Kelly-led position-managed selections for the existing backtester."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import PROCESSED_DIR, REPORT_DIR
from functions.decision_council.position_management import (
    aggregate_strategy_signals,
    build_position_management_decisions,
)
from functions.investable_universe import filter_investable_universe, load_index_constituents
from functions.strategy_selection import get_rebalance_dates
from functions.strategy_signal_generators import build_technical_strategy_signals


def generate_position_managed_selection(
    df_features: pd.DataFrame,
    *,
    constituents: pd.DataFrame | None = None,
    strategy_stats: pd.DataFrame | None = None,
    top_n: int = 20,
    freq: str = "ME",
    start_date=None,
    end_date=None,
    strategy_name: str = "position_managed_kelly",
    use_index_pool: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create a weighted selection table controlled by Kelly position sizing."""
    data = df_features.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if start_date is not None:
        data = data[data["date"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        data = data[data["date"] <= pd.Timestamp(end_date)]
    if data.empty:
        return _empty_selection(), pd.DataFrame()
    constituents = constituents if constituents is not None else load_index_constituents()
    if use_index_pool and constituents.empty:
        return _empty_selection(), pd.DataFrame(
            [
                {
                    "status": "blocked_missing_index_constituents",
                    "detail": "position_managed_kelly requires HS300/CSI500/CSI A500 point-in-time constituents",
                }
            ]
        )
    filtered = filter_investable_universe(
        data,
        constituents=constituents if use_index_pool and not constituents.empty else None,
    )
    if filtered.empty:
        return _empty_selection(), pd.DataFrame()
    rebalance_dates = get_rebalance_dates(filtered, freq=freq)
    selections = []
    decision_ledgers = []
    current_weights = {}
    for rebalance_date in rebalance_dates:
        history = filtered[filtered["date"] <= rebalance_date].copy()
        if history.empty:
            continue
        day_symbols = set(filtered.loc[filtered["date"] == rebalance_date, "symbol"].astype(str))
        signals = build_technical_strategy_signals(history, signal_date=rebalance_date)
        if signals.empty:
            continue
        signals = signals[signals["symbol"].isin(day_symbols)]
        if signals.empty:
            continue
        aggregated = aggregate_strategy_signals(signals, strategy_stats=strategy_stats)
        if aggregated.empty:
            continue
        decisions = build_position_management_decisions(
            aggregated,
            current_weights=current_weights,
            investable_symbols=day_symbols,
            tradeable_symbols=day_symbols,
        )
        decisions["rebalance_date"] = rebalance_date
        decision_ledgers.append(decisions)
        buys = decisions[decisions["position_action"].isin(["buy", "add", "hold", "trim"])].copy()
        buys = buys[pd.to_numeric(buys["target_weight"], errors="coerce").fillna(0.0) > 0.0]
        buys = buys.sort_values(["kelly_score", "symbol"], ascending=[False, True]).head(int(top_n))
        if buys.empty:
            current_weights = {}
            continue
        total = pd.to_numeric(buys["target_weight"], errors="coerce").sum()
        buys["weight"] = buys["target_weight"] / total if total > 0 else 1.0 / len(buys)
        buys["rank"] = range(1, len(buys) + 1)
        buys["score"] = buys["kelly_score"]
        buys["strategy_name"] = strategy_name
        day_features = filtered[filtered["date"] == rebalance_date].drop_duplicates("symbol")
        keep_extra = [
            col for col in ["symbol", "code", "market", "instrument_type", "close", "index_pool_codes"]
            if col in day_features.columns
        ]
        buys = buys.merge(day_features[keep_extra], on="symbol", how="left")
        selections.append(
            buys[
                [
                    "rebalance_date",
                    "rank",
                    "symbol",
                    "code",
                    "market",
                    "instrument_type",
                    "score",
                    "weight",
                    "close",
                    "kelly_raw",
                    "kelly_scale",
                    "risk_discount",
                    "kelly_adjusted",
                    "kelly_score",
                    "target_weight",
                    "position_action",
                    "action_reason",
                    "expected_return_20d",
                    "p_win",
                    "payoff_ratio",
                    "index_pool_codes",
                ]
            ]
        )
        current_weights = dict(zip(buys["symbol"], buys["weight"]))
    selection = pd.concat(selections, ignore_index=True) if selections else _empty_selection()
    ledger = pd.concat(decision_ledgers, ignore_index=True) if decision_ledgers else pd.DataFrame()
    return selection, ledger


def save_position_managed_selection(
    selection: pd.DataFrame,
    ledger: pd.DataFrame,
    *,
    strategy_name: str = "position_managed_kelly",
):
    selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
    ledger_path = REPORT_DIR / f"{strategy_name}_position_management_ledger.csv"
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    selection.to_parquet(selection_path, index=False)
    ledger.to_csv(ledger_path, index=False, encoding="utf-8-sig")
    return Path(selection_path), Path(ledger_path)


def _empty_selection():
    return pd.DataFrame(
        columns=[
            "rebalance_date",
            "rank",
            "symbol",
            "code",
            "market",
            "instrument_type",
            "score",
            "weight",
            "close",
            "kelly_raw",
            "kelly_scale",
            "risk_discount",
            "kelly_adjusted",
            "kelly_score",
            "target_weight",
            "position_action",
            "action_reason",
            "expected_return_20d",
            "p_win",
            "payoff_ratio",
            "index_pool_codes",
        ]
    )
