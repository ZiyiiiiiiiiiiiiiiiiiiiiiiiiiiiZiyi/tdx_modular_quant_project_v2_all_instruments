"""Generate Kelly-led position-managed selections for the existing backtester."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import (
    COMMISSION_RATE,
    POSITION_REQUIRE_INDEX_CONSTITUENTS,
    POSITION_ALLOW_QUALITY_FALLBACK,
    POSITION_PAYOFF_TRIM_RATIO,
    POSITION_STRATEGY_STATS_LOOKBACK_DAYS,
    POSITION_STRATEGY_STATS_MIN_SAMPLES,
    PROCESSED_DIR,
    REPORT_DIR,
    SLIPPAGE_RATE,
    STAMP_DUTY_RATE,
    TRANSFER_FEE_RATE,
)
from functions.strategy_params import STRATEGY_PARAMS
from functions.investable_universe import (
    UniverseFilterConfig,
    UNIVERSE_MODE_INDEX_POOL_STRICT,
)
from functions.decision_council.position_management import (
    aggregate_strategy_signals,
    build_position_management_decisions,
)
from functions.investable_universe import filter_investable_universe, load_index_constituents
from functions.output_naming import run_suffix
from functions.strategy_selection import get_rebalance_dates
from functions.strategy_signal_generators import build_technical_strategy_signals
from functions.strategy_signal_generators import has_precomputed_technical_strategy_features


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
    signal_strategy_ids=None,
    use_index_pool: bool = True,
    progress_hook=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create a weighted selection table controlled by Kelly position sizing.

    Universe modes:
    - index_pool_strict: Only stocks in HS300/CSI500/A500 + all ETFs
    - quality_fallback: Full market quality filter (when constituents missing + allowed)
    - blocked: Constituents required but missing, raise error
    """
    data = df_features.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if start_date is not None:
        data = data[data["date"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        data = data[data["date"] <= pd.Timestamp(end_date)]
    if data.empty:
        return _empty_selection(), pd.DataFrame()

    constituents = constituents if constituents is not None else load_index_constituents()

    # Explicit universe mode branching
    if use_index_pool:
        filtered, universe_mode = filter_investable_universe(
            data,
            constituents=constituents,
            require_constituents=POSITION_REQUIRE_INDEX_CONSTITUENTS,
            allow_fallback=POSITION_ALLOW_QUALITY_FALLBACK,
        )
    else:
        # No index pool requested, use quality fallback
        filtered, universe_mode = filter_investable_universe(
            data,
            constituents=None,
            require_constituents=False,
            allow_fallback=True,
        )

    if filtered.empty:
        return _empty_selection(), pd.DataFrame()

    # Store universe_mode for metadata
    constituent_data_status = "available" if universe_mode == UNIVERSE_MODE_INDEX_POOL_STRICT else "missing"

    rebalance_dates = get_rebalance_dates(filtered, freq=freq)
    selections = []
    decision_ledgers = []
    fallback_rows = []
    current_weights = {}
    use_precomputed_signals = has_precomputed_technical_strategy_features(
        filtered,
        strategy_ids=signal_strategy_ids,
    )
    rebalance_set = set(pd.to_datetime(rebalance_dates))
    rebalance_frames = {
        date: frame.copy()
        for date, frame in filtered[filtered["date"].isin(rebalance_set)].groupby("date", sort=True)
    }
    total_rebalances = len(rebalance_dates)
    for rebalance_index, rebalance_date in enumerate(rebalance_dates, start=1):
        if progress_hook is not None:
            progress_hook(
                "rebalance_start",
                f"rebalance {rebalance_index}/{total_rebalances} on {pd.Timestamp(rebalance_date).date()}",
            )
        day_frame = rebalance_frames.get(pd.Timestamp(rebalance_date))
        if day_frame is None or day_frame.empty:
            continue
        day_symbols = set(day_frame["symbol"].astype(str))

        # Include current holdings that are NOT in today's universe for explicit exit
        held_symbols = set(current_weights.keys())
        out_of_universe_symbols = held_symbols - day_symbols

        signal_source = day_frame if use_precomputed_signals else filtered[filtered["date"] <= rebalance_date].copy()
        if signal_source.empty and not out_of_universe_symbols:
            continue

        if progress_hook is not None:
            source_rows = len(signal_source) if not signal_source.empty else 0
            progress_hook(
                "signal_build",
                f"rebalance {rebalance_index}/{total_rebalances}: build signals from {source_rows} rows",
            )
        signals = build_technical_strategy_signals(
            signal_source,
            signal_date=rebalance_date,
            strategy_ids=signal_strategy_ids,
        ) if not signal_source.empty else pd.DataFrame()

        # Add virtual rows for out-of-universe holdings
        if out_of_universe_symbols:
            virtual_rows = []
            for sym in out_of_universe_symbols:
                virtual_rows.append({
                    "symbol": sym,
                    "expected_return_5d": 0.0,
                    "expected_return_20d": 0.0,
                    "p_win": 0.0,
                    "p_win_lower": 0.0,
                    "payoff_ratio": 1.0,
                    "aggregate_direction": "flat",
                    "out_of_universe": True,
                })
            virtual_df = pd.DataFrame(virtual_rows)
            if not signals.empty:
                # Add out_of_universe=False for existing signals
                signals["out_of_universe"] = False
                signals = pd.concat([signals, virtual_df], ignore_index=True)
            else:
                signals = virtual_df

        if signals.empty:
            continue

        signals = signals[signals["symbol"].isin(day_symbols | out_of_universe_symbols)]
        if signals.empty:
            continue

        calibration_stats = strategy_stats
        if calibration_stats is None:
            if progress_hook is not None:
                progress_hook(
                    "calibration",
                    f"rebalance {rebalance_index}/{total_rebalances}: calibrating strategy stats",
                )
            calibration_stats = _calibrate_strategy_stats_from_history(
                filtered,
                rebalance_date=rebalance_date,
                strategy_ids=signal_strategy_ids,
            )

        # Only aggregate signals for in-universe stocks
        in_universe_signals = signals[~signals.get("out_of_universe", pd.Series(False, index=signals.index)).fillna(False)]
        if progress_hook is not None:
            progress_hook(
                "aggregate",
                f"rebalance {rebalance_index}/{total_rebalances}: aggregate {len(in_universe_signals)} signals",
            )
        aggregated = aggregate_strategy_signals(in_universe_signals, strategy_stats=calibration_stats) if not in_universe_signals.empty else pd.DataFrame()

        if aggregated.empty and not out_of_universe_symbols:
            continue

        decisions = build_position_management_decisions(
            aggregated,
            current_weights=current_weights,
            investable_symbols=day_symbols,
            tradeable_symbols=day_symbols,
            out_of_universe_symbols=out_of_universe_symbols,
            universe_mode=universe_mode,
        )
        decisions["rebalance_date"] = rebalance_date
        decision_ledgers.append(decisions)
        buys = decisions[decisions["position_action"].isin(["buy", "add", "hold", "trim"])].copy()
        buys = buys[pd.to_numeric(buys["target_weight"], errors="coerce").fillna(0.0) > 0.0]
        buys = buys.sort_values(["kelly_score", "symbol"], ascending=[False, True]).head(int(top_n))
        if buys.empty:
            current_weights = {}
            continue
        buys["weight"] = pd.to_numeric(buys["target_weight"], errors="coerce").fillna(0.0)
        total = float(buys["weight"].sum())
        if total > 1.0:
            buys["weight"] *= 1.0 / total
        buys["rank"] = range(1, len(buys) + 1)
        buys["score"] = buys["kelly_score"]
        buys["strategy_name"] = strategy_name
        buys["price_basis"] = "nominal_unadjusted"
        buys["neutralization_mode"] = "not_applicable"
        buys["ml_runtime_mode"] = "not_applicable"
        buys["degradation_flags"] = ""
        # Count only real strategy signals, not virtual exit rows
        real_signal_count = int(in_universe_signals.shape[0]) if not in_universe_signals.empty else 0
        buys["signal_candidate_count"] = int(len(day_symbols))
        buys["signal_trigger_count"] = real_signal_count
        buys["signal_trigger_rate"] = (
            0.0 if len(day_symbols) <= 0 else float(real_signal_count) / float(len(day_symbols))
        )
        # Add universe metadata
        buys["universe_mode"] = universe_mode
        buys["constituent_data_status"] = constituent_data_status
        buys["selection_universe_note"] = "hs300_csi500_a500" if universe_mode == UNIVERSE_MODE_INDEX_POOL_STRICT else "fallback_without_constituents"

        day_features = filtered[filtered["date"] == rebalance_date].drop_duplicates("symbol")
        keep_extra = [
            col for col in [
                "symbol",
                "code",
                "market",
                "instrument_type",
                "close",
                "index_pool_codes",
                "feature_price_source",
                "adjustment_coverage_ratio",
                "adjustment_coverage_threshold",
                "price_basis_selection_mode",
                "strategy_params_version",
                "strategy_params_hash",
                "formal_price_eligible",
            ]
            if col in day_features.columns
        ]
        buys = buys.merge(day_features[keep_extra], on="symbol", how="left")
        if "index_pool_codes" not in buys.columns:
            buys["index_pool_codes"] = ""
        if "feature_price_source" in buys.columns:
            buys["price_basis"] = buys["feature_price_source"].fillna("nominal_unadjusted")
        buys["degradation_flags"] = buys.apply(_position_managed_degradation_flags, axis=1)
        output_columns = [
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
            "prior_p",
            "prior_strength",
            "prior_source",
            "posterior_alpha",
            "posterior_beta",
            "posterior_sample_count",
            "price_basis",
            "neutralization_mode",
            "ml_runtime_mode",
            "degradation_flags",
            "signal_candidate_count",
            "signal_trigger_count",
            "signal_trigger_rate",
            "adjustment_coverage_ratio",
            "adjustment_coverage_threshold",
            "price_basis_selection_mode",
            "strategy_params_version",
            "strategy_params_hash",
            "formal_price_eligible",
            "index_pool_codes",
            "universe_mode",
            "constituent_data_status",
            "selection_universe_note",
        ]
        output_columns = [col for col in output_columns if col in buys.columns]
        selections.append(buys[output_columns])
        current_weights = dict(zip(buys["symbol"], buys["weight"]))
        if progress_hook is not None:
            progress_hook(
                "rebalance_done",
                f"rebalance {rebalance_index}/{total_rebalances}: kept {len(buys)} positions",
            )
    selection = pd.concat(selections, ignore_index=True) if selections else _empty_selection()
    ledger_parts = [pd.DataFrame(fallback_rows)] if fallback_rows else []
    if decision_ledgers:
        ledger_parts.append(pd.concat(decision_ledgers, ignore_index=True))
    ledger = pd.concat(ledger_parts, ignore_index=True, sort=False) if ledger_parts else pd.DataFrame()
    return selection, ledger


def save_position_managed_selection(
    selection: pd.DataFrame,
    ledger: pd.DataFrame,
    *,
    strategy_name: str = "position_managed_kelly",
):
    selection_path = PROCESSED_DIR / f"{strategy_name}.parquet"
    ledger_path = REPORT_DIR / f"{strategy_name}_position_management_ledger{run_suffix()}.csv"
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    selection.to_parquet(selection_path, index=False)
    ledger.to_csv(ledger_path, index=False, encoding="utf-8-sig")
    return Path(selection_path), Path(ledger_path)


def _position_managed_degradation_flags(row):
    flags = []
    if str(row.get("price_basis", "")) == "nominal_unadjusted":
        flags.append("price_basis_nominal_fallback")
    if bool(row.get("formal_price_eligible", False)) is False:
        flags.append("formal_price_ineligible")
    return "|".join(dict.fromkeys(flag for flag in flags if flag))


def _quick_filtered_stock_universe(features: pd.DataFrame) -> pd.DataFrame:
    """Fallback filter when index constituents are unavailable.

    NOTE: With POSITION_REQUIRE_INDEX_CONSTITUENTS=True, this path should not be
    reached in normal operation. If called, it marks all stocks as eligible but
    NOT in the target index pool (since we don't have constituent data).
    """
    if POSITION_REQUIRE_INDEX_CONSTITUENTS:
        raise ValueError(
            "Index constituents are required but unavailable. "
            "Build data/processed/index_constituents.parquet first."
        )
    cfg = UniverseFilterConfig()
    data = features.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.sort_values(["symbol", "date"]).copy()
    if "instrument_type" in data.columns:
        data = data[data["instrument_type"] == "stock"]
    for column, required_value in [("is_st", False), ("is_delisting", False), ("is_trading", True)]:
        if column in data.columns:
            data = data[data[column] == required_value]
    if "rough_limit_up" in data.columns:
        data = data[data["rough_limit_up"] == False]
    if "rough_limit_down" in data.columns:
        data = data[data["rough_limit_down"] == False]
    if "raw_ret" in data.columns:
        data = data[pd.to_numeric(data["raw_ret"], errors="coerce").abs().fillna(0.0) <= cfg.abnormal_return_threshold]
    data = data.copy()
    grouped = data.groupby("symbol", group_keys=False)
    data["history_days"] = data.groupby("symbol", group_keys=False).cumcount() + 1
    data = data[data["history_days"] >= cfg.min_history_days]
    data = data.copy()
    grouped = data.groupby("symbol", group_keys=False)
    if "amount" in data.columns:
        data["avg_amount_20"] = grouped["amount"].transform(
            lambda s: pd.to_numeric(s, errors="coerce").rolling(20, min_periods=5).mean()
        )
        data = data[pd.to_numeric(data["avg_amount_20"], errors="coerce").fillna(0.0) >= cfg.min_avg_amount_20]
        data = data.copy()
        grouped = data.groupby("symbol", group_keys=False)
    close_col = "close_nominal" if "close_nominal" in data.columns else "close"
    if close_col in data.columns and "amount" in data.columns:
        ret = grouped[close_col].pct_change(fill_method=None)
        amount = pd.to_numeric(data["amount"], errors="coerce")
        data["amihud_20"] = (ret.abs() / amount.replace(0.0, pd.NA)).groupby(data["symbol"]).transform(
            lambda s: s.rolling(20, min_periods=5).mean()
        )
        data = data[pd.to_numeric(data["amihud_20"], errors="coerce").fillna(0.0) <= cfg.max_amihud_20]
    data = data.copy()
    # Mark as not in index pool (since we don't have constituent data)
    data["in_target_index_pool"] = False
    data["index_pool_codes"] = "no_constituent_data"
    return data


def _calibrate_strategy_stats_from_history(
    features: pd.DataFrame,
    *,
    rebalance_date,
    strategy_ids=None,
    lookback_days: int = POSITION_STRATEGY_STATS_LOOKBACK_DAYS,
    min_samples: int = POSITION_STRATEGY_STATS_MIN_SAMPLES,
) -> pd.DataFrame:
    """Estimate out-of-sample-like win/loss inputs from prior labeled rows.

    The calibration uses only rows strictly before the rebalance date.  It is a
    conservative fallback until a dedicated trade ledger calibration table is
    available.
    """
    date = pd.Timestamp(rebalance_date)
    start = date - pd.Timedelta(days=int(lookback_days) * 2)
    history = features[
        (pd.to_datetime(features["date"], errors="coerce") < date)
        & (pd.to_datetime(features["date"], errors="coerce") >= start)
    ].copy()
    if history.empty:
        return pd.DataFrame()
    strategy_map = {
        "macd_trend": "score_macd_trend",
        "turtle_breakout": "score_turtle_breakout",
        "mean_reversion": "score_mean_reversion",
        "rsi_reversal": "score_rsi_reversal",
        "grid_trading": "score_grid_trading",
        "alpha_hedge": "score_alpha_hedge",
        "event_driven": "score_event_driven",
        "eod_close_strength": "score_eod_close_strength",
        "limit_up_follow": "score_limit_up_follow",
        "macd_cross": "score_macd_cross",
        "ma_cross": "score_ma_cross",
        "price_volume_breakout": "score_price_volume_breakout",
        "consecutive_decline_rebound": "score_consecutive_decline_rebound",
        "holiday_effect": "score_holiday_effect",
        "kdj_oversold_cross": "score_kdj_oversold_cross",
        "low_volume_pullback": "score_low_volume_pullback",
    }
    if strategy_ids is not None:
        wanted = {str(item) for item in strategy_ids}
        strategy_map = {k: v for k, v in strategy_map.items() if k in wanted}
    rows = []
    for strategy_id, score_col in strategy_map.items():
        if score_col not in history.columns:
            continue
        label_col = _realized_return_column_for_strategy(history, strategy_id)
        if label_col is None:
            continue
        horizon = _label_horizon(label_col)
        mature_cutoff = date - pd.offsets.BDay(horizon)
        mature_history = history[pd.to_datetime(history["date"], errors="coerce") <= mature_cutoff]
        if mature_history.empty:
            continue
        realized = pd.to_numeric(mature_history[label_col], errors="coerce")
        round_trip_cost = (
            2.0 * float(COMMISSION_RATE)
            + 2.0 * float(SLIPPAGE_RATE)
            + float(STAMP_DUTY_RATE)
            + 2.0 * float(TRANSFER_FEE_RATE)
        )
        realized = realized - round_trip_cost
        score = pd.to_numeric(mature_history[score_col], errors="coerce")
        sample = pd.DataFrame(
            {
                "symbol": mature_history["symbol"].astype(str),
                "date": pd.to_datetime(mature_history["date"], errors="coerce"),
                "score": score,
                "realized": realized,
            }
        )
        threshold = _strategy_score_threshold(strategy_id)
        sample["signal_active"] = sample["score"].notna() & (
            sample["score"] > threshold
        )
        prior_active = (
            sample.sort_values(["symbol", "date"])
            .groupby("symbol")["signal_active"]
            .shift(1, fill_value=False)
            .astype(bool)
        )
        sample["event_start"] = sample["signal_active"] & ~prior_active
        sample = sample[sample["event_start"]].dropna(subset=["realized"])
        if strategy_id == "grid_trading" and "ret_20" in history.columns:
            ret_20 = pd.to_numeric(mature_history.loc[sample.index, "ret_20"], errors="coerce")
            max_abs_ret = float(STRATEGY_PARAMS["grid_trading"].get("max_abs_ret_20", 0.08))
            sample = sample[ret_20.abs().fillna(float("inf")) <= max_abs_ret]
        if len(sample) < int(min_samples):
            continue
        wins = sample[sample["realized"] > 0.0]["realized"]
        losses = sample[sample["realized"] <= 0.0]["realized"]
        rows.append(
            {
                "strategy_id": strategy_id,
                "reputation_weight": min(len(sample) / max(float(min_samples), 1.0), 5.0),
                "wins": int(len(wins)),
                "losses": int(len(losses)),
                "avg_win": _trimmed_mean(wins, POSITION_PAYOFF_TRIM_RATIO),
                "avg_loss": _trimmed_mean(losses, POSITION_PAYOFF_TRIM_RATIO),
            }
        )
    return pd.DataFrame(rows)


def _realized_return_column_for_strategy(history: pd.DataFrame, strategy_id: str) -> str | None:
    preferred = {
        "grid_trading": "future_ret_5",
        "mean_reversion": "future_ret_10",
        "rsi_reversal": "future_ret_10",
        "eod_close_strength": "future_ret_5",
        "limit_up_follow": "future_ret_5",
        "consecutive_decline_rebound": "future_ret_5",
        "holiday_effect": "future_ret_5",
        "macd_cross": "future_ret_10",
        "ma_cross": "future_ret_10",
        "price_volume_breakout": "future_ret_10",
        "kdj_oversold_cross": "future_ret_10",
        "low_volume_pullback": "future_ret_10",
    }.get(strategy_id, "future_ret_20")
    if preferred in history.columns:
        return preferred
    return "future_ret_20" if "future_ret_20" in history.columns else None


def _label_horizon(label_col: str) -> int:
    try:
        return int(str(label_col).rsplit("_", 1)[-1])
    except (TypeError, ValueError):
        return 20


def _trimmed_mean(values: pd.Series, trim_ratio: float) -> float:
    series = pd.to_numeric(values, errors="coerce").dropna().sort_values()
    if series.empty:
        return 0.0
    trim = int(len(series) * float(trim_ratio))
    if trim > 0 and len(series) > 2 * trim:
        series = series.iloc[trim:-trim]
    return float(series.mean())


def _strategy_score_threshold(strategy_id: str) -> float:
    if strategy_id == "rsi_reversal":
        return 0.40
    return 0.0


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
            "prior_p",
            "prior_strength",
            "prior_source",
            "posterior_alpha",
            "posterior_beta",
            "posterior_sample_count",
            "price_basis",
            "neutralization_mode",
            "ml_runtime_mode",
            "degradation_flags",
            "signal_candidate_count",
            "signal_trigger_count",
            "signal_trigger_rate",
            "adjustment_coverage_ratio",
            "adjustment_coverage_threshold",
            "price_basis_selection_mode",
            "strategy_params_version",
            "strategy_params_hash",
            "formal_price_eligible",
            "index_pool_codes",
            "strategy_name",
            "strategy_source",
            "weighting_mode",
            "governance_variant",
            "configured_start_date",
            "configured_end_date",
            "date_window",
            "universe_mode",
            "constituent_data_status",
            "selection_universe_note",
        ]
    )
