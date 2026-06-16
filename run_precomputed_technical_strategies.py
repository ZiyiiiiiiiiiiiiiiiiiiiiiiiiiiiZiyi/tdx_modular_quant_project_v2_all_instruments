# -*- coding: utf-8 -*-
"""Fast runner for precomputed technical/research Kelly strategies."""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from config import (
    BACKTEST_INITIAL_CASH,
    BACKTEST_RISK_FREE_RATE,
    COMMISSION_RATE,
    FEATURE_DAILY_PARQUET,
    POSITION_KELLY_SCALE,
    POSITION_REQUIRE_INDEX_CONSTITUENTS,
    POSITION_SINGLE_STOCK_CAP,
    POSITION_STRATEGY_STATS_MIN_SAMPLES,
    PRECOMPUTED_STRATEGY_CONFIGS,
    REPORT_DIR,
    SLIPPAGE_RATE,
    STAMP_DUTY_RATE,
    START_DATE,
    STRATEGY_END_DATE,
    STRATEGY_PARAMS,
    STRATEGY_START_DATE,
    STRATEGY_TOP_N,
    TRANSFER_FEE_RATE,
    V6_STRATEGY_COOLDOWN_DAYS,
    V6_STRATEGY_TARGET_HORIZONS,
    assert_valid_configuration,
)
from functions.backtest_engine import run_backtest
from functions.decision_council.position_management import calculate_kelly_raw
from functions.event_statistics import beta_binomial_win_rate, robust_payoff_ratio
from functions.investable_universe import filter_investable_universe, load_index_constituents
from functions.strategy_registry import STRATEGY_FACTOR_DESCRIPTIONS
from functions.strategy_selection import get_rebalance_dates, run_strategy_selection


STRATEGY_CONFIGS = PRECOMPUTED_STRATEGY_CONFIGS


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", default=list(STRATEGY_CONFIGS))
    parser.add_argument("--start-date", default=STRATEGY_START_DATE)
    parser.add_argument("--end-date", default=STRATEGY_END_DATE)
    parser.add_argument("--top-n", type=int, default=STRATEGY_TOP_N)
    return parser.parse_args()


def main():
    assert_valid_configuration()
    args = parse_args()
    names = [name for name in args.only if name in STRATEGY_CONFIGS]
    missing = sorted(set(args.only) - set(names))
    if missing:
        raise KeyError(f"Unknown precomputed strategies: {missing}")
    columns = _required_columns(names)
    print("Load feature columns:", len(columns))
    features = pd.read_parquet(
        FEATURE_DAILY_PARQUET,
        columns=columns,
        filters=[
            ("date", ">=", pd.Timestamp(START_DATE)),
            ("date", "<=", pd.Timestamp(args.end_date)),
        ],
    )
    features["date"] = pd.to_datetime(features["date"], errors="coerce")
    features = features.sort_values(["symbol", "date"]).copy()
    for name in names:
        horizon = int(
            V6_STRATEGY_TARGET_HORIZONS.get(
                name,
                STRATEGY_PARAMS.get(name, {}).get("horizon_days", 20),
            )
        )
        label_col = f"future_ret_{horizon}"
        if label_col not in features.columns:
            future_close = features.groupby("symbol")["close"].shift(-horizon)
            features[label_col] = future_close / features["close"] - 1.0
    features = _filter_fast_universe(features)
    constituents = load_index_constituents()
    if constituents.empty:
        if POSITION_REQUIRE_INDEX_CONSTITUENTS:
            raise RuntimeError(
                "Formal V6 run requires point-in-time HS300/CSI500/CSI A500 constituents."
            )
        print(
            "Exploratory fallback: point-in-time index constituents are missing; "
            "formal admission remains blocked."
        )
    else:
        features = filter_investable_universe(features, constituents=constituents)
    print("Filtered feature rows:", len(features))
    for strategy_name in names:
        selection = _build_selection(
            features,
            strategy_name,
            top_n=args.top_n,
            selection_start_date=args.start_date,
            selection_end_date=args.end_date,
        )
        _save_and_backtest(
            selection,
            strategy_name,
            start_date=args.start_date,
            end_date=args.end_date,
        )


def _required_columns(names):
    columns = {
        "date",
        "symbol",
        "code",
        "market",
        "instrument_type",
        "close",
        "amount",
        "raw_ret",
        "is_trading",
        "rough_limit_up",
        "rough_limit_down",
        "volatility_20",
    }
    for name in names:
        columns.add(STRATEGY_CONFIGS[name]["score_col"])
        horizon = int(
            V6_STRATEGY_TARGET_HORIZONS.get(
                name,
                STRATEGY_PARAMS.get(name, {}).get("horizon_days", 20),
            )
        )
        if horizon in {5, 10, 20}:
            columns.add(f"future_ret_{horizon}")
    return sorted(columns)


def _filter_fast_universe(frame):
    data = frame.copy()
    if "instrument_type" in data.columns:
        data = data[data["instrument_type"] == "stock"]
    if "is_trading" in data.columns:
        data = data[data["is_trading"] == True]
    for col in ["rough_limit_up", "rough_limit_down"]:
        if col in data.columns:
            data = data[data[col] == False]
    if "raw_ret" in data.columns:
        data = data[pd.to_numeric(data["raw_ret"], errors="coerce").abs().fillna(0.0) <= 0.11]
    if "amount" in data.columns:
        data = data[pd.to_numeric(data["amount"], errors="coerce").fillna(0.0) >= 10_000_000.0]
    return data.sort_values(["symbol", "date"]).copy()


def _build_selection(
    features,
    strategy_name,
    top_n,
    *,
    selection_start_date=None,
    selection_end_date=None,
):
    cfg = STRATEGY_CONFIGS[strategy_name]
    score_col = cfg["score_col"]
    data = features.dropna(subset=["date", "symbol", "close", score_col]).copy()
    if data.empty:
        return _empty_selection()
    selection_scope = data
    if selection_start_date is not None:
        selection_scope = selection_scope[
            selection_scope["date"] >= pd.Timestamp(selection_start_date)
        ]
    if selection_end_date is not None:
        selection_scope = selection_scope[
            selection_scope["date"] <= pd.Timestamp(selection_end_date)
        ]
    rebalance_dates = get_rebalance_dates(selection_scope, freq="ME")
    rows = []
    calibration_rows = []
    for rebalance_date, day in data[data["date"].isin(rebalance_dates)].groupby("date", sort=True):
        calibration = _calibrate_strategy(data, strategy_name, rebalance_date)
        if calibration is None:
            calibration_rows.append(
                {
                    "strategy_id": strategy_name,
                    "rebalance_date": rebalance_date,
                    "status": "insufficient_mature_independent_events",
                }
            )
            continue
        calibration_rows.append(
            {
                "strategy_id": strategy_name,
                "rebalance_date": rebalance_date,
                "status": "positive_kelly" if calibration["kelly_raw"] > 0.0 else "non_positive_kelly",
                **calibration,
            }
        )
        if calibration["kelly_raw"] <= 0.0:
            continue
        ranked = day.sort_values(score_col, ascending=False).head(int(top_n)).copy()
        if ranked.empty:
            continue
        score = (
            pd.to_numeric(ranked[score_col], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
        )
        ranked = ranked[score > _score_threshold(strategy_name)].copy()
        if ranked.empty:
            continue
        score = score.reindex(ranked.index)
        ranked["p_win"] = float(calibration["p_win_lower"])
        ranked["p_win_mean"] = float(calibration["p_win_mean"])
        ranked["payoff_ratio"] = float(calibration["payoff_ratio"])
        ranked["effective_sample_size"] = int(calibration["sample_count"])
        ranked["kelly_raw"] = [
            calculate_kelly_raw(p, calibration["payoff_ratio"]) for p in ranked["p_win"]
        ]
        ranked["risk_discount"] = 1.0
        ranked["kelly_scale"] = POSITION_KELLY_SCALE
        ranked["kelly_adjusted"] = ranked["kelly_raw"].clip(lower=0.0) * ranked["kelly_scale"] * ranked["risk_discount"]
        ranked["kelly_score"] = ranked["kelly_adjusted"].clip(0.0, POSITION_SINGLE_STOCK_CAP)
        ranked = ranked[ranked["kelly_score"] > 0.0].copy()
        if ranked.empty:
            continue
        ranked = ranked.sort_values(["kelly_score", "symbol"], ascending=[False, True]).head(int(top_n))
        ranked["rebalance_date"] = rebalance_date
        ranked["rank"] = range(1, len(ranked) + 1)
        ranked["weight"] = ranked["kelly_score"]
        ranked["score"] = ranked["kelly_score"]
        ranked["target_weight"] = ranked["kelly_score"]
        ranked["position_action"] = "buy"
        ranked["action_reason"] = "mature_event_bayesian_kelly"
        ranked["expected_return_20d"] = float(calibration["expected_return_20d"])
        ranked["index_pool_codes"] = ""
        rows.append(ranked[_selection_columns()])
    calibration_path = REPORT_DIR / f"v6_calibration_{strategy_name}.csv"
    pd.DataFrame(calibration_rows).to_csv(
        calibration_path,
        index=False,
        encoding="utf-8-sig",
    )
    return pd.concat(rows, ignore_index=True) if rows else _empty_selection()


def _calibrate_strategy(data, strategy_name, rebalance_date):
    score_col = STRATEGY_CONFIGS[strategy_name]["score_col"]
    horizon = int(
        V6_STRATEGY_TARGET_HORIZONS.get(
            strategy_name,
            STRATEGY_PARAMS.get(strategy_name, {}).get("horizon_days", 20),
        )
    )
    label_col = f"future_ret_{horizon}"
    if label_col not in data.columns:
        return None
    cutoff = pd.Timestamp(rebalance_date) - pd.offsets.BDay(horizon)
    sample = data[pd.to_datetime(data["date"], errors="coerce") <= cutoff].copy()
    sample["score_value"] = pd.to_numeric(sample[score_col], errors="coerce")
    sample["net_return"] = (
        pd.to_numeric(sample[label_col], errors="coerce") - _round_trip_cost()
    )
    sample["signal_active"] = sample["score_value"].notna() & (
        sample["score_value"] > _score_threshold(strategy_name)
    )
    prior_active = (
        sample.sort_values(["symbol", "date"])
        .groupby("symbol")["signal_active"]
        .shift(1, fill_value=False)
        .astype(bool)
    )
    sample["event_start"] = sample["signal_active"] & ~prior_active
    sample = sample[sample["event_start"] & sample["net_return"].notna()]
    sample = _independent_samples(
        sample,
        cooldown_days=int(V6_STRATEGY_COOLDOWN_DAYS.get(strategy_name, 3)),
    )
    if len(sample) < int(POSITION_STRATEGY_STATS_MIN_SAMPLES):
        return None
    wins = int((sample["net_return"] > 0.0).sum())
    losses = int((sample["net_return"] <= 0.0).sum())
    probability = beta_binomial_win_rate(wins, losses)
    payoff = robust_payoff_ratio(sample["net_return"])
    kelly_raw = calculate_kelly_raw(
        probability.lower_bound,
        payoff["payoff_ratio"],
    )
    return {
        "p_win_mean": probability.mean,
        "p_win_lower": probability.lower_bound,
        "payoff_ratio": payoff["payoff_ratio"],
        "sample_count": len(sample),
        "expected_return_20d": float(sample["net_return"].mean()) * (20.0 / horizon),
        "kelly_raw": kelly_raw,
    }


def _independent_samples(sample: pd.DataFrame, *, cooldown_days: int) -> pd.DataFrame:
    selected = []
    for _, group in sample.sort_values(["symbol", "date"]).groupby("symbol", sort=False):
        prior_date = None
        for index, row in group.iterrows():
            date = pd.Timestamp(row["date"])
            if prior_date is None or (date.normalize() - prior_date.normalize()).days > cooldown_days:
                selected.append(index)
                prior_date = date
    return sample.loc[selected].copy() if selected else sample.iloc[0:0].copy()


def _score_threshold(strategy_name: str) -> float:
    if strategy_name == "rsi_reversal":
        return 0.40
    return 0.0


def _round_trip_cost() -> float:
    return (
        2.0 * float(COMMISSION_RATE)
        + 2.0 * float(SLIPPAGE_RATE)
        + float(STAMP_DUTY_RATE)
        + 2.0 * float(TRANSFER_FEE_RATE)
    )


def _selection_columns():
    return [
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
        "p_win_mean",
        "payoff_ratio",
        "effective_sample_size",
        "index_pool_codes",
    ]


def _empty_selection():
    return pd.DataFrame(columns=_selection_columns())


def _save_and_backtest(selection, strategy_name, *, start_date=None, end_date=None):
    print(f"Save selection {strategy_name}: rows={len(selection)}")
    run_strategy_selection(
        df_features=selection,
        df_selection=selection,
        score_col="kelly_score",
        top_n=20,
        freq="ME",
        include_types=("stock",),
        start_date=start_date,
        end_date=end_date,
        strategy_name=strategy_name,
    )
    if selection.empty:
        print(f"Skip backtest {strategy_name}: empty selection")
        return
    _, metrics, _ = run_backtest(
        df_selection=selection,
        initial_cash=BACKTEST_INITIAL_CASH,
        risk_free_rate=BACKTEST_RISK_FREE_RATE,
        show_plot=False,
        strategy_name=strategy_name,
        factor_description=STRATEGY_FACTOR_DESCRIPTIONS.get(strategy_name),
        compute_theoretical_upper_bound=False,
        start_date=start_date,
        end_date=end_date,
    )
    print(metrics.to_string(index=False))


if __name__ == "__main__":
    main()
