"""Position lifecycle and state constraints for governance backtests."""
from __future__ import annotations

import pandas as pd

from config import *  # noqa: F403 - lifecycle rules are config-driven.


def _safe_float(value, default=0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _clip01(value) -> float:
    return min(max(_safe_float(value, default=0.0), 0.0), 1.0)


def _dynamic_giveback_limit(
    *,
    mfe: float,
    trend_direction_score: float = 0.50,
    peak_decay_score: float = 0.0,
    orderflow_decay_score: float = 0.0,
) -> float:
    mfe = max(_safe_float(mfe, default=0.0), 0.0)
    if mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_3):
        base = float(GOVERNANCE_PROFIT_GIVEBACK_3)
    elif mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_2):
        base = float(GOVERNANCE_PROFIT_GIVEBACK_2)
    else:
        base = float(GOVERNANCE_PROFIT_GIVEBACK_1)
    trend_decay_penalty = max(0.55 - _safe_float(trend_direction_score, default=0.50), 0.0) * 0.30
    peak_decay_penalty = _clip01(peak_decay_score) * 0.12
    orderflow_penalty = _clip01(orderflow_decay_score) * 0.08
    return max(base - trend_decay_penalty - peak_decay_penalty - orderflow_penalty, 0.08)


def _governance_round_trip_cost_rate() -> float:
    return float(COMMISSION_RATE) * 2.0 + float(SLIPPAGE_RATE) * 2.0 + float(STAMP_DUTY_RATE) + float(TRANSFER_FEE_RATE) * 2.0


def _post_entry_failure_score(candidates: pd.DataFrame) -> pd.Series:
    if candidates is None or candidates.empty:
        return pd.Series(dtype=float)
    watch = candidates.get("post_entry_failure_watch", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
    unrealized = pd.to_numeric(candidates.get("position_unrealized_return", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    alpha = pd.to_numeric(candidates.get("alpha_percentile", pd.Series(0.5, index=candidates.index)), errors="coerce").fillna(0.5)
    alpha_quality = pd.to_numeric(candidates.get("alpha_quality_score", pd.Series(0.5, index=candidates.index)), errors="coerce").fillna(0.5)
    entry_alpha_quality = pd.to_numeric(
        candidates.get("position_entry_alpha_quality_score", pd.Series(alpha_quality, index=candidates.index)),
        errors="coerce",
    ).fillna(alpha_quality)
    alpha_quality_drop = (entry_alpha_quality - alpha_quality).clip(lower=0.0, upper=1.0)
    ret5 = pd.to_numeric(candidates.get("ret_5", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    ret20 = pd.to_numeric(candidates.get("ret_20", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    close_to_ma20 = pd.to_numeric(candidates.get("close_to_ma20", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    mfe = pd.to_numeric(candidates.get("position_mfe", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    mae = pd.to_numeric(candidates.get("position_mae", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    downtrend_decay = pd.to_numeric(candidates.get("downtrend_decay_score", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    flow_count = pd.to_numeric(candidates.get("entry_orderflow_confirm_count", pd.Series(0, index=candidates.index)), errors="coerce").fillna(0)
    holding_days = pd.to_numeric(candidates.get("position_holding_days", pd.Series(0, index=candidates.index)), errors="coerce").fillna(0)
    alpha_collapse = (
        alpha.lt(0.45).astype(float) * 0.35
        + alpha_quality.lt(0.55).astype(float) * 0.25
        + (alpha_quality_drop / 0.12).clip(0.0, 1.0) * 0.40
    ).clip(0.0, 1.0)
    trend_weak = (
        ret5.lt(-0.02).astype(float) * 0.35
        + ret20.lt(-0.04).astype(float) * 0.35
        + close_to_ma20.lt(-0.03).astype(float) * 0.30
    ).clip(0.0, 1.0)
    orderflow_bad = flow_count.le(1).astype(float)
    loss_bad = ((-unrealized - 0.015) / 0.055).clip(0.0, 1.0)
    poor_excursion = (
        mfe.lt(0.02).astype(float) * 0.45
        + ((-mae - 0.02) / 0.08).clip(0.0, 1.0) * 0.35
        + downtrend_decay.clip(0.0, 1.0) * 0.20
    ).clip(0.0, 1.0)
    stale_bad = ((holding_days - 6.0) / 14.0).clip(0.0, 1.0)
    score = (
        0.25 * loss_bad
        + 0.25 * alpha_collapse
        + 0.20 * poor_excursion
        + 0.15 * orderflow_bad
        + 0.15 * trend_weak
        + 0.05 * stale_bad
    ).clip(0.0, 1.0)
    return score.where(watch | holding_days.ge(3), 0.0)


def update_lifecycle_on_buy(runner, symbol: str, *, date, price: float, shares: float, current, signal=None) -> None:
    symbol = str(symbol)
    price = float(price)
    shares = float(shares)
    if price <= 0.0 or shares <= 0.0:
        return
    existing = runner.position_lifecycle.get(symbol)
    previous_shares = float(current.shares) if current is not None else 0.0
    if existing and previous_shares > 0.0:
        old_entry = float(existing.get("entry_price", price) or price)
        entry_price = (old_entry * previous_shares + price * shares) / max(previous_shares + shares, 1e-12)
        entry_date = existing.get("entry_date", pd.Timestamp(date))
    else:
        entry_price = price
        entry_date = pd.Timestamp(date)
    signal = signal if signal is not None else {}
    entry_alpha_quality = _safe_float(
        signal.get("alpha_quality_score") if hasattr(signal, "get") else pd.NA,
        default=float(existing.get("entry_alpha_quality_score", 0.0)) if existing else 0.0,
    )
    runner.position_lifecycle[symbol] = {
        "entry_date": pd.Timestamp(entry_date),
        "entry_price": float(entry_price),
        "peak_price": max(float(existing.get("peak_price", price)) if existing else price, price),
        "trough_price": min(float(existing.get("trough_price", price)) if existing else price, price),
        "buy_count": int(existing.get("buy_count", 1) + 1) if existing and previous_shares > 0.0 else 1,
        "last_buy_date": pd.Timestamp(date),
        "entry_alpha_quality_score": (
            float(existing.get("entry_alpha_quality_score", entry_alpha_quality))
            if existing and previous_shares > 0.0
            else float(entry_alpha_quality)
        ),
        "latest_buy_alpha_quality_score": entry_alpha_quality,
        "entry_matrix_score": _safe_float(signal.get("entry_matrix_score") if hasattr(signal, "get") else pd.NA, default=0.0),
        "entry_timing_score": _safe_float(signal.get("entry_timing_score") if hasattr(signal, "get") else pd.NA, default=0.0),
        "entry_size_tier": str(signal.get("entry_size_tier", "") if hasattr(signal, "get") else ""),
    }

def mark_lifecycle(runner, symbol: str, *, date, price: float) -> dict:
    symbol = str(symbol)
    price = float(price)
    state = runner.position_lifecycle.get(symbol)
    if state is None or price <= 0.0:
        return {
            "entry_date": pd.NaT,
            "entry_price": pd.NA,
            "unrealized_return": pd.NA,
            "mfe": pd.NA,
            "mae": pd.NA,
            "giveback_from_peak": pd.NA,
            "trend_direction_score": pd.NA,
            "peak_decay_score": pd.NA,
            "profit_protection_pressure": pd.NA,
            "dynamic_giveback_limit": pd.NA,
            "future_loss_risk_score": pd.NA,
            "profit_giveback_flag": False,
            "post_entry_failure_flag": False,
            "entry_alpha_quality_score": pd.NA,
        }
    state["peak_price"] = max(float(state.get("peak_price", price)), price)
    state["trough_price"] = min(float(state.get("trough_price", price)), price)
    entry_price = float(state.get("entry_price", price) or price)
    entry_date = pd.Timestamp(state.get("entry_date", date))
    unrealized = price / entry_price - 1.0 if entry_price > 0.0 else 0.0
    mfe = float(state["peak_price"]) / entry_price - 1.0 if entry_price > 0.0 else 0.0
    mae = float(state["trough_price"]) / entry_price - 1.0 if entry_price > 0.0 else 0.0
    giveback = (mfe - unrealized) / max(mfe, 1e-12) if mfe > 0.0 else 0.0
    holding_days = int(runner.holding_days.get(symbol, 0))
    market_shape = runner._lifecycle_market_shape(symbol=symbol, date=date, entry_price=entry_price, peak_price=float(state["peak_price"]))
    trend_direction_score = _safe_float(market_shape.get("trend_direction_score"), default=0.50)
    peak_decay_score = _safe_float(market_shape.get("peak_decay_score"), default=0.0)
    dynamic_giveback_limit = _dynamic_giveback_limit(
        mfe=mfe,
        trend_direction_score=trend_direction_score,
        peak_decay_score=peak_decay_score,
        orderflow_decay_score=0.0,
    )
    profit_protection_pressure = _clip01(
        0.45 * (giveback / max(dynamic_giveback_limit, 1e-12))
        + 0.30 * peak_decay_score
        + 0.25 * (1.0 - trend_direction_score)
    ) if mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_1) else 0.0
    future_loss_risk_score = _clip01(
        0.35 * peak_decay_score
        + 0.30 * (1.0 - trend_direction_score)
        + 0.20 * max(-unrealized / 0.12, 0.0)
        + 0.15 * max(giveback - dynamic_giveback_limit, 0.0) / max(1.0 - dynamic_giveback_limit, 1e-12)
    )
    return {
        "entry_date": entry_date,
        "entry_price": entry_price,
        "unrealized_return": float(unrealized),
        "mfe": float(mfe),
        "mae": float(mae),
        "giveback_from_peak": float(giveback),
        "trend_direction_score": float(trend_direction_score),
        "peak_decay_score": float(peak_decay_score),
        "profit_protection_pressure": float(profit_protection_pressure),
        "dynamic_giveback_limit": float(dynamic_giveback_limit),
        "future_loss_risk_score": float(future_loss_risk_score),
        "profit_giveback_flag": bool(mfe >= 0.08 and giveback >= dynamic_giveback_limit and holding_days >= 3),
        "post_entry_failure_flag": bool(holding_days >= 6 and mfe < 0.02 and unrealized < -0.02),
        "entry_alpha_quality_score": state.get("entry_alpha_quality_score", pd.NA),
    }

def lifecycle_market_shape(runner, *, symbol: str, date, entry_price: float, peak_price: float) -> dict:
    history = runner._close_history(str(symbol))
    if history.empty:
        return {"trend_direction_score": 0.50, "peak_decay_score": 0.0}
    data = history.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data.dropna(subset=["date", "close"])
    data = data[data["date"] <= pd.Timestamp(date)].tail(60).copy()
    if len(data) < 8:
        return {"trend_direction_score": 0.50, "peak_decay_score": 0.0}
    close = data["close"].astype(float).reset_index(drop=True)
    latest = float(close.iloc[-1])
    ma5 = close.rolling(5, min_periods=3).mean()
    ma10 = close.rolling(10, min_periods=5).mean()
    ma20 = close.rolling(20, min_periods=10).mean()
    ma_slope = 0.0
    if len(ma20.dropna()) >= 6:
        ma_slope = float(ma20.dropna().iloc[-1] / max(ma20.dropna().iloc[-6], 1e-12) - 1.0)
    recent = close.tail(10)
    previous = close.iloc[-25:-10] if len(close) >= 25 else close.iloc[:-10]
    recent_high = float(recent.max())
    recent_low = float(recent.min())
    previous_high = float(previous.max()) if len(previous) else recent_high
    previous_low = float(previous.min()) if len(previous) else recent_low
    higher_high_low_score = _clip01(
        0.50
        + 5.0 * (recent_high / max(previous_high, 1e-12) - 1.0)
        + 5.0 * (recent_low / max(previous_low, 1e-12) - 1.0)
    )
    ma_slope_score = _clip01(0.50 + 8.0 * ma_slope)
    twenty_high = float(close.tail(20).max())
    twenty_low = float(close.tail(20).min())
    pullback_recovery_score = _clip01((latest - twenty_low) / max(twenty_high - twenty_low, 1e-12))
    short_ma_reclaim_score = _clip01(0.50 + 0.25 * (latest >= float(ma5.iloc[-1])) + 0.25 * (latest >= float(ma10.iloc[-1])))
    drawdown_from_peak = max(float(peak_price) - latest, 0.0) / max(float(peak_price), 1e-12)
    trend_direction_score = _clip01(
        0.25 * higher_high_low_score
        + 0.25 * ma_slope_score
        + 0.20 * pullback_recovery_score
        + 0.15 * short_ma_reclaim_score
        + 0.15 * (1.0 - min(drawdown_from_peak / 0.20, 1.0))
    )
    peak_lower_ratio = max(float(peak_price) - recent_high, 0.0) / max(float(peak_price), 1e-12)
    below_ma20 = 1.0 if pd.notna(ma20.iloc[-1]) and latest < float(ma20.iloc[-1]) else 0.0
    peak_decay_score = _clip01(
        0.35 * min(drawdown_from_peak / 0.12, 1.0)
        + 0.30 * min(peak_lower_ratio / 0.04, 1.0)
        + 0.20 * (1.0 - trend_direction_score)
        + 0.15 * below_ma20
    )
    return {
        "trend_direction_score": float(trend_direction_score),
        "peak_decay_score": float(peak_decay_score),
    }

def attach_position_lifecycle_signals(runner, candidates: pd.DataFrame, *, date) -> pd.DataFrame:
    if candidates is None or candidates.empty:
        return candidates
    data = candidates.copy()
    flags = {}
    for row in getattr(runner, "_last_position_mark_rows", []) or []:
        symbol = str(row.get("symbol", ""))
        flags[symbol] = {
            "profit_giveback_exit": bool(row.get("profit_giveback_flag", False)),
            "post_entry_failure_watch": bool(row.get("post_entry_failure_flag", False)),
            "position_unrealized_return": row.get("unrealized_return", pd.NA),
            "position_mfe": row.get("mfe", pd.NA),
            "position_mae": row.get("mae", pd.NA),
            "position_giveback_from_peak": row.get("giveback_from_peak", pd.NA),
            "trend_direction_score": row.get("trend_direction_score", pd.NA),
            "peak_decay_score": row.get("peak_decay_score", pd.NA),
            "profit_protection_pressure": row.get("profit_protection_pressure", pd.NA),
            "dynamic_giveback_limit": row.get("dynamic_giveback_limit", pd.NA),
            "future_loss_risk_score": row.get("future_loss_risk_score", pd.NA),
            "position_holding_days": int(runner.holding_days.get(symbol, 0)),
            "position_entry_alpha_quality_score": row.get("entry_alpha_quality_score", pd.NA),
        }
    for column, default in (
        ("profit_giveback_exit", False),
        ("post_entry_failure_watch", False),
        ("position_unrealized_return", pd.NA),
        ("position_mfe", pd.NA),
        ("position_mae", pd.NA),
        ("position_giveback_from_peak", pd.NA),
        ("trend_direction_score", pd.NA),
        ("peak_decay_score", pd.NA),
        ("profit_protection_pressure", pd.NA),
        ("dynamic_giveback_limit", pd.NA),
        ("future_loss_risk_score", pd.NA),
        ("position_holding_days", 0),
        ("position_entry_alpha_quality_score", pd.NA),
    ):
        data[column] = data["symbol"].astype(str).map(lambda symbol: flags.get(symbol, {}).get(column, default))
    data["post_entry_failure_score"] = _post_entry_failure_score(data)
    data["post_entry_failure_exit"] = data["post_entry_failure_score"].ge(float(GOVERNANCE_POST_ENTRY_FAILURE_EXIT_SCORE))
    return data

def apply_position_state_constraints(runner, candidates: pd.DataFrame, *, date, exposure: dict) -> pd.DataFrame:
    if candidates is None or candidates.empty:
        return candidates
    data = candidates.copy()
    date_ts = pd.Timestamp(date)
    runner._expire_position_cooldowns(date_ts)
    held_symbols = set(runner.positions)
    nominal_nav = max(float(exposure.get("nominal_nav", 0.0) or 0.0), 1e-12)
    current_weights = {
        str(row.get("symbol", "")): float(row.get("market_value", 0.0) or 0.0) / nominal_nav
        for row in getattr(runner, "_last_position_mark_rows", []) or []
    }
    state_rows = []
    max_layers = runner._max_add_layers()
    add_gaps = tuple(float(value) for value in GOVERNANCE_LAYER_ADD_GAPS)
    layer_weights = tuple(float(value) for value in GOVERNANCE_LAYER_WEIGHTS)

    defaults = {
        "position_state": "new",
        "exit_state": False,
        "position_exit_reason": "",
        "cooldown_active": False,
        "cooldown_until": pd.NaT,
        "cooldown_reason": "",
        "cooldown_override": False,
        "protecting_profit": False,
        "profit_protection_triggered": False,
        "buy_sell_conflict_cooldown_days": int(GOVERNANCE_BUY_SELL_CONFLICT_COOLDOWN_DAYS),
        "add_allowed": False,
        "add_block_reason": "not_held",
        "add_layer": 0,
        "add_budget": 0.0,
        "hard_stop_exit": False,
        "profit_hard_stop_exit": False,
        "signal_failure_exit": False,
        "stale_time_reduce": False,
        "stale_time_exit": False,
        "trend_direction_score": pd.NA,
        "peak_decay_score": pd.NA,
        "profit_protection_pressure": pd.NA,
        "dynamic_giveback_limit": pd.NA,
        "future_loss_risk_score": pd.NA,
    }
    for column, default in defaults.items():
        if column not in data.columns:
            data[column] = default

    for idx, row in data.iterrows():
        symbol = str(row.get("symbol", ""))
        is_held = symbol in held_symbols
        lifecycle = runner.position_lifecycle.get(symbol, {})
        holding_days = int(runner.holding_days.get(symbol, 0))
        unrealized = _safe_float(row.get("position_unrealized_return"), default=0.0)
        mfe = _safe_float(row.get("position_mfe"), default=0.0)
        mae = _safe_float(row.get("position_mae"), default=0.0)
        giveback = _safe_float(row.get("position_giveback_from_peak"), default=0.0)
        entry_score = _safe_float(row.get("entry_matrix_score"), default=0.0)
        alpha_quality_score = _safe_float(row.get("alpha_quality_score"), default=entry_score)
        entry_alpha_quality_at_buy = _safe_float(row.get("position_entry_alpha_quality_score"), default=alpha_quality_score)
        alpha_quality_drop_from_entry = max(entry_alpha_quality_at_buy - alpha_quality_score, 0.0)
        surge_score = _safe_float(row.get("surge_capture_score"), default=0.0)
        follow_through_score = _safe_float(row.get("follow_through_score"), default=0.0)
        exhaustion_score = _safe_float(row.get("exhaustion_score"), default=0.0)
        entry_success_probability = _safe_float(row.get("entry_success_probability"), default=0.0)
        empirical_distribution_score = _safe_float(row.get("empirical_distribution_score"), default=0.0)
        final_entry_score = _safe_float(row.get("final_entry_score"), default=entry_score)
        tail_risk_proxy = _safe_float(row.get("tail_risk_proxy"), default=0.0)
        downtrend_score = _safe_float(row.get("downtrend_decay_score"), default=0.0)
        post_entry_failure_score = _safe_float(row.get("post_entry_failure_score"), default=0.0)
        trend_score = _safe_float(row.get("trend_stability_score"), default=0.0)
        volume_score = _safe_float(row.get("volume_health_score"), default=0.0)
        trend_direction_score = _safe_float(row.get("trend_direction_score"), default=0.50)
        peak_decay_score = _safe_float(row.get("peak_decay_score"), default=0.0)
        orderflow_score = _safe_float(row.get("orderflow_candidate_score"), default=0.50)
        orderflow_decay_score = max(0.55 - orderflow_score, 0.0) / 0.55
        liquidity_decay_score = max(0.55 - volume_score, 0.0) / 0.55
        factor_conviction_score = _clip01(
            0.35 * alpha_quality_score
            + 0.25 * entry_success_probability
            + 0.20 * trend_score
            + 0.10 * volume_score
            + 0.10 * final_entry_score
        )
        signal_retention_score = _clip01(
            0.35 * (1.0 - min(alpha_quality_drop_from_entry / 0.20, 1.0))
            + 0.25 * trend_score
            + 0.20 * volume_score
            + 0.20 * orderflow_score
        )
        dynamic_giveback_limit = _dynamic_giveback_limit(
            mfe=mfe,
            trend_direction_score=trend_direction_score,
            peak_decay_score=peak_decay_score,
            orderflow_decay_score=orderflow_decay_score,
        )
        profit_protection_pressure = _clip01(
            0.40 * (giveback / max(dynamic_giveback_limit, 1e-12))
            + 0.25 * peak_decay_score
            + 0.20 * (1.0 - trend_direction_score)
            + 0.15 * orderflow_decay_score
        ) if mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_1) else 0.0
        future_loss_risk_score = _clip01(
            0.30 * peak_decay_score
            + 0.25 * (1.0 - trend_direction_score)
            + 0.20 * downtrend_score
            + 0.15 * tail_risk_proxy
            + 0.10 * post_entry_failure_score
        )
        account_weight = float(current_weights.get(symbol, 0.0) or 0.0)
        cooldown = runner.position_cooldowns.get(symbol)
        cooldown_active = bool(cooldown and pd.Timestamp(cooldown.get("cooldown_until")) >= date_ts)
        cooldown_override = bool(
            cooldown_active
            and entry_score >= float(GOVERNANCE_ENTRY_MATRIX_EXTREME_THRESHOLD)
            and trend_score >= 0.55
            and volume_score >= 0.55
        )

        net_unrealized = float(unrealized) - _governance_round_trip_cost_rate()
        net_mfe = float(mfe) - _governance_round_trip_cost_rate()
        hard_stop = bool(
            is_held
            and net_mfe >= float(GOVERNANCE_PROFIT_HARD_STOP_ARM_TRIGGER)
            and net_unrealized >= float(GOVERNANCE_PROFIT_HARD_STOP_MIN_NET_PROFIT)
            and (net_mfe - net_unrealized) / max(net_mfe, 1e-12) >= float(GOVERNANCE_PROFIT_HARD_STOP_TRAIL_GIVEBACK)
        )
        profit_giveback = bool(
            is_held
            and mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_1)
            and giveback >= dynamic_giveback_limit
            and profit_protection_pressure >= 0.70
        )
        protecting_profit = bool(
            is_held
            and holding_days >= int(GOVERNANCE_PROTECTING_PROFIT_MIN_HOLD_DAYS)
            and mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_1)
            and not hard_stop
            and not profit_giveback
        )
        peak_decay_exit = bool(
            is_held
            and holding_days >= int(GOVERNANCE_PROTECTING_PROFIT_MIN_HOLD_DAYS)
            and mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_1)
            and peak_decay_score >= 0.62
            and trend_direction_score < 0.48
            and giveback >= max(dynamic_giveback_limit * 0.75, 0.18)
        )
        signal_failure = bool(
            is_held
            and holding_days >= int(GOVERNANCE_STALE_WATCH_DAYS)
            and entry_score < float(GOVERNANCE_ENTRY_MATRIX_EXIT_DECAY_THRESHOLD)
            and trend_score < 0.45
        )
        downtrend_exit = bool(
            is_held
            and downtrend_score >= float(GOVERNANCE_DOWNTREND_DECAY_EXIT)
            and follow_through_score < 0.45
        )
        stale_failure_context = bool(
            is_held
            and mfe <= float(GOVERNANCE_STALE_EXIT_MAX_MFE)
            and alpha_quality_drop_from_entry >= float(GOVERNANCE_STALE_EXIT_MIN_ALPHA_DROP)
            and liquidity_decay_score >= float(GOVERNANCE_STALE_EXIT_MIN_LIQUIDITY_DECAY)
        )
        stale_reduce = bool(
            stale_failure_context
            and holding_days >= int(GOVERNANCE_STALE_REDUCE_DAYS)
            and unrealized <= 0.0
        )
        stale_exit = bool(
            stale_failure_context
            and holding_days >= int(GOVERNANCE_STALE_EXIT_DAYS)
            and unrealized <= 0.0
        )
        early_threshold = None
        threshold_pairs = tuple(GOVERNANCE_POST_ENTRY_FAILURE_EARLY_EXIT_THRESHOLDS or ())
        if threshold_pairs:
            for day_threshold, score_threshold in sorted(
                ((int(day), float(score)) for day, score in threshold_pairs),
                reverse=True,
            ):
                if holding_days >= day_threshold:
                    early_threshold = score_threshold
                    break
        else:
            early_failure_days = tuple(int(day) for day in GOVERNANCE_POST_ENTRY_FAILURE_EARLY_DAYS)
            if holding_days >= min(early_failure_days or (3,)):
                early_threshold = float(GOVERNANCE_POST_ENTRY_FAILURE_EARLY_EXIT_SCORE)
        early_post_entry_failure = bool(
            is_held
            and early_threshold is not None
            and post_entry_failure_score >= float(early_threshold)
            and (
                mfe <= 0.02
                or mae <= -0.025
                or alpha_quality_drop_from_entry >= 0.12
                or downtrend_score >= 0.55
            )
        )

        exit_reason = ""
        if hard_stop:
            exit_reason = "profit_hard_stop_exit"
        elif profit_giveback:
            exit_reason = "profit_giveback_exit"
        elif peak_decay_exit:
            exit_reason = "profit_giveback_exit"
        elif early_post_entry_failure or bool(row.get("post_entry_failure_exit", False)):
            exit_reason = "post_entry_failure_exit"
        elif downtrend_exit:
            exit_reason = "signal_failure_exit"
        elif stale_exit:
            exit_reason = "stale_time_exit"
        elif signal_failure:
            exit_reason = "signal_failure_exit"
        paper_exit_reason = exit_reason
        if exit_reason in {"hard_stop_exit", "profit_hard_stop_exit"} and not runner._control_enabled("hard_stop_exit"):
            exit_reason = ""
        elif exit_reason == "profit_giveback_exit" and not runner._control_enabled("profit_giveback_exit"):
            exit_reason = ""
        elif exit_reason == "post_entry_failure_exit" and not runner._control_enabled("post_entry_failure_exit"):
            exit_reason = ""
        elif exit_reason in {"signal_failure_exit", "stale_time_exit", "stale_time_reduce"} and not runner._control_enabled("signal_failure_exit"):
            exit_reason = ""
        exit_state = bool(exit_reason)

        buy_count = int(lifecycle.get("buy_count", 1 if is_held else 0) or 0)
        next_layer = min(buy_count + 1, max_layers)
        add_allowed = False
        add_block_reason = "not_held"
        if is_held:
            if exit_state:
                add_block_reason = f"exit_state:{exit_reason}"
            elif stale_reduce and runner._control_enabled("stale_exit"):
                add_block_reason = "stale_time_reduce"
            elif cooldown_active and not cooldown_override and runner._control_enabled("cooldown"):
                add_block_reason = "cooldown_active"
            elif protecting_profit:
                add_block_reason = "protecting_profit_no_add"
            elif buy_count >= max_layers:
                add_block_reason = "max_layers_reached"
            elif entry_score < 0.65:
                add_block_reason = "entry_matrix_score_low"
            elif downtrend_score >= float(GOVERNANCE_DOWNTREND_DECAY_ADD_BLOCK):
                add_block_reason = "downtrend_decay_block"
            elif exhaustion_score >= float(GOVERNANCE_EXHAUSTION_ADD_MAX):
                add_block_reason = "exhaustion_block"
            elif post_entry_failure_score >= 0.55:
                add_block_reason = "post_entry_failure_risk"
            elif alpha_quality_score < 0.68:
                add_block_reason = "alpha_quality_low"
            elif factor_conviction_score < float(GOVERNANCE_ADD_MIN_FACTOR_CONVICTION):
                add_block_reason = "factor_conviction_low"
            elif signal_retention_score < float(GOVERNANCE_ADD_MIN_SIGNAL_RETENTION):
                add_block_reason = "signal_retention_low"
            elif trend_score < 0.40:
                add_block_reason = "trend_stability_low"
            elif volume_score < 0.40:
                add_block_reason = "volume_health_low"
            elif account_weight >= float(runner.capital_profile.get("retail_single_position_cap", GOVERNANCE_MAX_POSITION_WEIGHT) or GOVERNANCE_MAX_POSITION_WEIGHT):
                add_block_reason = "single_name_account_cap"
            else:
                gap_index = min(max(buy_count - 1, 0), len(add_gaps) - 1)
                if unrealized <= add_gaps[gap_index]:
                    add_allowed = True
                    add_block_reason = "allowed"
                else:
                    add_block_reason = "add_gap_not_reached"

        if is_held:
            if exit_state:
                position_state = "exiting"
            elif protecting_profit:
                position_state = "protecting_profit"
            else:
                position_state = "adding" if add_allowed else "holding"
        elif cooldown_active and not cooldown_override and runner._control_enabled("cooldown"):
            position_state = "cooldown"
        elif exhaustion_score >= float(GOVERNANCE_EXHAUSTION_BUY_MAX):
            position_state = "watching" if entry_score >= float(GOVERNANCE_ENTRY_MATRIX_WATCH_THRESHOLD) else "blocked"
        elif str(row.get("entry_size_tier", "")).strip().lower() == "starter_strong":
            position_state = "strong_building"
        elif (
            str(row.get("entry_size_tier", "")).strip().lower() in {"basket_1_lot", "starter_1_lot", "starter_2_lot", "diversify_1_lot"}
            and bool(row.get("entry_confirmed", False))
        ):
            position_state = "building"
        elif bool(row.get("direct_buy_flag", False)) or bool(row.get("surge_buy_flag", False)):
            position_state = "building"
        elif bool(row.get("watchlist_flag", False)):
            position_state = "watching"
        else:
            position_state = "blocked"

        if not is_held and exhaustion_score >= float(GOVERNANCE_EXHAUSTION_BUY_MAX):
            data.at[idx, "entry_confirmed"] = False
            data.at[idx, "entry_block_reason"] = "exhaustion_block"
        if cooldown_active and not cooldown_override and not is_held and runner._control_enabled("cooldown"):
            data.at[idx, "entry_confirmed"] = False
            data.at[idx, "entry_block_reason"] = "cooldown_active"

        layer_index = min(max(next_layer - 1, 0), len(layer_weights) - 1)
        add_budget = float(layer_weights[layer_index]) * float(GOVERNANCE_MAX_POSITION_WEIGHT) if add_allowed else 0.0
        post_entry_failure = bool(early_post_entry_failure or row.get("post_entry_failure_exit", False))
        updates = {
            "position_state": position_state,
            "exit_state": exit_state,
            "position_exit_reason": exit_reason,
            "paper_exit_reason": paper_exit_reason,
            "paper_exit_state": bool(paper_exit_reason),
            "cooldown_active": cooldown_active and not cooldown_override and runner._control_enabled("cooldown"),
            "paper_cooldown_active": cooldown_active and not cooldown_override,
            "cooldown_until": cooldown.get("cooldown_until") if cooldown else pd.NaT,
            "cooldown_reason": cooldown.get("reason", "") if cooldown else "",
            "cooldown_override": cooldown_override,
            "protecting_profit": protecting_profit,
            "profit_protection_triggered": bool(hard_stop or profit_giveback or protecting_profit),
            "buy_sell_conflict_cooldown_days": int(GOVERNANCE_BUY_SELL_CONFLICT_COOLDOWN_DAYS),
            "add_allowed": add_allowed,
            "add_block_reason": add_block_reason,
            "add_layer": next_layer if is_held else 0,
            "add_budget": add_budget,
            "hard_stop_exit": hard_stop and runner._control_enabled("hard_stop_exit"),
            "profit_hard_stop_exit": hard_stop and runner._control_enabled("hard_stop_exit"),
            "paper_hard_stop_exit": hard_stop,
            "paper_profit_hard_stop_exit": hard_stop,
            "hard_stop_net_mfe": net_mfe if is_held else pd.NA,
            "hard_stop_net_unrealized": net_unrealized if is_held else pd.NA,
            "hard_stop_giveback_from_net_peak": (
                (net_mfe - net_unrealized) / max(net_mfe, 1e-12)
                if is_held and net_mfe > 0.0
                else pd.NA
            ),
            "profit_giveback_exit": bool(profit_giveback or peak_decay_exit) and runner._control_enabled("profit_giveback_exit"),
            "paper_profit_giveback_exit": bool(profit_giveback or peak_decay_exit),
            "post_entry_failure_exit": post_entry_failure and runner._control_enabled("post_entry_failure_exit"),
            "paper_post_entry_failure_exit": post_entry_failure,
            "signal_failure_exit": bool(signal_failure or downtrend_exit) and runner._control_enabled("signal_failure_exit"),
            "paper_signal_failure_exit": bool(signal_failure or downtrend_exit),
            "stale_time_reduce": stale_reduce and runner._control_enabled("stale_exit"),
            "paper_stale_time_reduce": stale_reduce,
            "stale_time_exit": stale_exit and runner._control_enabled("stale_exit"),
            "paper_stale_time_exit": stale_exit,
            "early_post_entry_failure_exit": early_post_entry_failure,
            "alpha_quality_score": alpha_quality_score,
            "surge_capture_score": surge_score,
            "follow_through_score": follow_through_score,
            "exhaustion_score": exhaustion_score,
            "entry_success_probability": entry_success_probability,
            "empirical_distribution_score": empirical_distribution_score,
            "final_entry_score": final_entry_score,
            "tail_risk_proxy": tail_risk_proxy,
            "trend_direction_score": trend_direction_score,
            "peak_decay_score": peak_decay_score,
            "profit_protection_pressure": profit_protection_pressure,
            "dynamic_giveback_limit": dynamic_giveback_limit,
            "future_loss_risk_score": future_loss_risk_score,
            "factor_conviction_score": factor_conviction_score,
            "signal_retention_score": signal_retention_score,
            "liquidity_decay_score": liquidity_decay_score,
            "risk_contribution_penalty": row.get("risk_contribution_penalty", 0.0),
            "risk_adjusted_primary_score": row.get("risk_adjusted_primary_score", row.get("primary_score", pd.NA)),
            "entry_size_tier": row.get("entry_size_tier", ""),
            "planned_entry_lots": row.get("planned_entry_lots", pd.NA),
            "entry_alpha_quality_at_buy": entry_alpha_quality_at_buy if is_held else pd.NA,
            "alpha_quality_drop_from_entry": alpha_quality_drop_from_entry if is_held else 0.0,
            "downtrend_decay_score": downtrend_score,
            "post_entry_failure_score": post_entry_failure_score,
        }
        for key, value in updates.items():
            data.at[idx, key] = value
        state_rows.append(
            {
                "date": date_ts,
                "symbol": symbol,
                "held": is_held,
                "holding_days": holding_days,
                "account_weight": account_weight,
                "entry_matrix_score": entry_score,
                "trend_stability_score": trend_score,
                "volume_health_score": volume_score,
                "trend_direction_score": trend_direction_score,
                "peak_decay_score": peak_decay_score,
                "profit_protection_pressure": profit_protection_pressure,
                "dynamic_giveback_limit": dynamic_giveback_limit,
                "future_loss_risk_score": future_loss_risk_score,
                "unrealized_return": unrealized,
                "mfe": mfe,
                "giveback_from_peak": giveback,
                **updates,
            }
        )
    runner.position_state_rows.extend(state_rows)
    return data

def apply_candidate_risk_penalty(runner, candidates: pd.DataFrame, *, exposure: dict) -> pd.DataFrame:
    if candidates is None or candidates.empty:
        return candidates
    data = candidates.copy()
    if "primary_score" not in data.columns:
        return data
    nominal_nav = max(float(exposure.get("nominal_nav", 0.0) or 0.0), 1e-12)
    current_weights = {
        str(row.get("symbol", "")): float(row.get("market_value", 0.0) or 0.0) / nominal_nav
        for row in getattr(runner, "_last_position_mark_rows", []) or []
    }
    primary = pd.to_numeric(data["primary_score"], errors="coerce")
    account_weight = data["symbol"].astype(str).map(lambda symbol: float(current_weights.get(symbol, 0.0) or 0.0))
    price_col = "close_nominal" if "close_nominal" in data.columns else "close"
    price = pd.to_numeric(data.get(price_col, pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0).clip(lower=0.0)
    planned_lots = pd.to_numeric(data.get("planned_entry_lots", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
    buy_intent = (
        data.get("entry_confirmed", pd.Series(False, index=data.index)).fillna(False).astype(bool)
        | data.get("direct_buy_flag", pd.Series(False, index=data.index)).fillna(False).astype(bool)
        | data.get("surge_buy_flag", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    )
    planned_lots = planned_lots.where(planned_lots > 0.0, 1.0).where(buy_intent, 0.0)
    prospective_entry_weight = (price * float(MIN_LOT_SIZE) * planned_lots) / nominal_nav
    projected_weight = account_weight + prospective_entry_weight
    single_cap = float(runner.capital_profile.get("retail_single_position_cap", GOVERNANCE_MAX_POSITION_WEIGHT) or GOVERNANCE_MAX_POSITION_WEIGHT)
    research_cap = float(GOVERNANCE_HIGH_EXPOSURE_MAX_TOP1_RISK_CONTRIBUTION)
    soft_cap = max(min(single_cap, research_cap), 1e-12)
    penalty = ((projected_weight / soft_cap) - 1.0).clip(lower=0.0, upper=2.0) * float(GOVERNANCE_RISK_CONTRIBUTION_SCORE_PENALTY)
    state = data.get("position_state", pd.Series("", index=data.index)).astype(str).str.lower()
    add_or_build = state.isin(["adding", "building", "strong_building"])
    penalty = penalty.where(add_or_build | buy_intent | account_weight.gt(0.0), 0.0)
    data["raw_primary_score"] = primary
    data["risk_contribution_pre_trade_weight"] = account_weight
    data["risk_contribution_projected_weight"] = projected_weight
    data["risk_contribution_penalty"] = penalty
    data["risk_adjusted_primary_score"] = primary - penalty
    data["primary_score"] = data["risk_adjusted_primary_score"]
    data = data.sort_values(["primary_score", "symbol"], ascending=[False, True]).reset_index(drop=True)
    data["candidate_rank"] = range(1, len(data) + 1)
    return data

def expire_position_cooldowns(runner, date) -> None:
    date_ts = pd.Timestamp(date)
    expired = [
        symbol
        for symbol, payload in runner.position_cooldowns.items()
        if pd.Timestamp(payload.get("cooldown_until")) < date_ts
    ]
    for symbol in expired:
        runner.position_cooldowns.pop(symbol, None)

def max_add_layers(runner) -> int:
    if float(runner.initial_cash) <= 30_000:
        return int(GOVERNANCE_MAX_ADD_LAYERS_RETAIL_20K)
    return int(GOVERNANCE_MAX_ADD_LAYERS_LARGE)


def register_position_cooldown(runner, symbol: str, *, date, reason: str) -> None:
    reason = str(reason or "normal_sell")
    days = int(GOVERNANCE_BUY_SELL_CONFLICT_COOLDOWN_DAYS)
    runner.position_cooldowns[str(symbol)] = {
        "cooldown_start": pd.Timestamp(date),
        "cooldown_until": pd.Timestamp(date) + pd.offsets.BDay(days),
        "reason": reason,
        "cooldown_days": days,
    }


