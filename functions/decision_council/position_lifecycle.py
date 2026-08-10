"""Position lifecycle and state constraints for governance backtests."""
from __future__ import annotations

import pandas as pd

from functions.execution.security_trading_rules import trading_rule_for

from config import *  # noqa: F403 - lifecycle rules are config-driven.
from functions.decision_council.mainline_v2 import is_mainline_v3_version
from functions.decision_council.small_capital_aggressive import scap_loss_containment_exit
from functions.decision_council.exit_reason_contract import control_for_exit_reason
from functions.decision_council.decision_arbitration import (
    arbitrate_position_actions,
    arbitrate_exit_signals,
    update_consecutive_confirmation,
)
from functions.decision_council.action_utility import (
    build_incremental_action_utility,
    round_trip_cost_amount,
)
from functions.decision_council.post_drawdown_diagnostics import (
    resolve_post_entry_failure_authority,
)


def _safe_float(value, default=0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _clip01(value) -> float:
    return min(max(_safe_float(value, default=0.0), 0.0), 1.0)


def _active_single_position_cap(runner) -> float:
    dynamic = getattr(runner, "_current_dynamic_single_position_hard_cap", None)
    if dynamic is not None and _safe_float(dynamic, default=0.0) > 0.0:
        return float(dynamic)
    return float(
        runner.capital_profile.get(
            "retail_single_position_cap", GOVERNANCE_MAX_POSITION_WEIGHT
        )
        or GOVERNANCE_MAX_POSITION_WEIGHT
    )


def resolve_scap_loss_limits(
    profile: dict,
    *,
    tail_risk_proxy: float,
    disaster_floor: float = GOVERNANCE_HARD_STOP_LOSS,
) -> tuple[float, float]:
    """Return (adaptive soft stop, immediate disaster floor).

    Higher tail risk tightens the confirmed soft stop.  The disaster floor is
    an independent one-day circuit breaker and therefore never gets widened by
    the adaptive formula.
    """
    disaster = float(profile.get("scap_loss_disaster_stop", disaster_floor))
    configured = float(profile.get("scap_loss_stop", disaster))
    mode = str(profile.get("scap_loss_stop_mode", "fixed") or "fixed").strip().lower()
    if mode != "adaptive_volatility_or_disaster_floor":
        if not disaster < configured < 0.0:
            raise ValueError("loss limits must satisfy disaster_stop < soft_stop < 0")
        return configured, disaster
    tail_proxy = _clip01(tail_risk_proxy)
    soft_base = float(profile.get("scap_loss_soft_base", -0.16))
    tail_tightening = max(float(profile.get("scap_loss_tail_tightening", 0.04)), 0.0)
    soft_tightest = float(profile.get("scap_loss_soft_tightest", -0.12))
    if not disaster < soft_base <= soft_tightest < 0.0:
        raise ValueError(
            "adaptive loss limits must satisfy disaster < soft_base <= soft_tightest < 0"
        )
    adaptive_soft = min(
        max(soft_base + tail_tightening * tail_proxy, soft_base),
        soft_tightest,
    )
    return adaptive_soft, disaster


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


def _prioritized_exit_reason(
    *,
    hard_stop: bool,
    profit_giveback: bool,
    peak_decay_exit: bool,
    loss_containment: bool,
    post_entry_failure: bool,
    downtrend_exit: bool,
    stale_exit: bool,
    signal_failure: bool,
    control_enabled=None,
) -> str:
    """Compatibility wrapper around the single exit authority."""
    return arbitrate_exit_signals(
        {
            "profit_hard_stop_exit": hard_stop,
            "profit_giveback_exit": profit_giveback or peak_decay_exit,
            "loss_containment_exit": loss_containment,
            "post_entry_failure_exit": post_entry_failure,
            "signal_failure_exit": downtrend_exit or signal_failure,
            "stale_time_exit": stale_exit,
        },
        control_enabled=control_enabled,
    ).active_reason


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
    flow_raw = pd.to_numeric(
        candidates.get("entry_orderflow_confirm_count", pd.Series(float("nan"), index=candidates.index)),
        errors="coerce",
    )
    flow_missing = flow_raw.isna()
    flow_count = flow_raw.fillna(0.0)
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
    orderflow_bad = flow_count.le(1).astype(float).where(~flow_missing, 0.5)
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
    ) / 1.05
    score = score.clip(0.0, 1.0)
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
    support_scores = {
        "momentum": _safe_float(signal.get("trend_hold_score") if hasattr(signal, "get") else pd.NA, 0.0),
        "reversal": _safe_float(signal.get("reversal_entry_score") if hasattr(signal, "get") else pd.NA, 0.0),
        "orderflow": _safe_float(signal.get("orderflow_candidate_score") if hasattr(signal, "get") else pd.NA, 0.0),
        "breakout": _safe_float(signal.get("breakout_gate_score") if hasattr(signal, "get") else pd.NA, 0.0),
    }
    cabinet_thesis = str(signal.get("cabinet_entry_thesis", "") if hasattr(signal, "get") else "").strip()
    if cabinet_thesis:
        entry_thesis = cabinet_thesis
        entry_support = _safe_float(signal.get("cabinet_entry_thesis_support"), 0.5)
    else:
        entry_thesis = max(support_scores, key=support_scores.get) if max(support_scores.values()) > 0.0 else "composite"
        entry_support = float(support_scores.get(entry_thesis, 0.0))
    runner.position_lifecycle[symbol] = {
        "entry_date": pd.Timestamp(entry_date),
        "entry_price": float(entry_price),
        "peak_price": max(float(existing.get("peak_price", price)) if existing else price, price),
        "trough_price": min(float(existing.get("trough_price", price)) if existing else price, price),
        "buy_count": int(existing.get("buy_count", 1) + 1) if existing and previous_shares > 0.0 else 1,
        "last_buy_date": pd.Timestamp(date),
        "last_add_date": (
            pd.Timestamp(date)
            if existing and previous_shares > 0.0
            else pd.NaT
        ),
        "last_add_shares": (
            float(shares) if existing and previous_shares > 0.0 else 0.0
        ),
        "entry_alpha_quality_score": (
            float(existing.get("entry_alpha_quality_score", entry_alpha_quality))
            if existing and previous_shares > 0.0
            else float(entry_alpha_quality)
        ),
        "latest_buy_alpha_quality_score": entry_alpha_quality,
        "entry_matrix_score": _safe_float(signal.get("entry_matrix_score") if hasattr(signal, "get") else pd.NA, default=0.0),
        "entry_timing_score": _safe_float(signal.get("entry_timing_score") if hasattr(signal, "get") else pd.NA, default=0.0),
        "entry_size_tier": str(signal.get("entry_size_tier", "") if hasattr(signal, "get") else ""),
        "entry_thesis": str(existing.get("entry_thesis", entry_thesis)) if existing and previous_shares > 0.0 else entry_thesis,
        "entry_module_support": float(existing.get("entry_module_support", entry_support)) if existing and previous_shares > 0.0 else entry_support,
        "entry_logic_version": str(getattr(runner, "strategy_logic_version", "production_v1")),
        "entry_authority_tier": (
            str(existing.get("entry_authority_tier", ""))
            if existing and previous_shares > 0.0
            else str(
                signal.get("scap_v31_authority_tier", "")
                if hasattr(signal, "get")
                else ""
            )
        ),
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

def _carried_unobserved_position_states(
    runner,
    *,
    date,
    exposure: dict,
    observed_symbols: set[str],
) -> list[dict]:
    """Represent held names that have no current feature row without inventing a signal.

    Suspensions and other missing-bar cases remain economically held and are
    valued from the conservative mark ledger.  Their latest *known* lifecycle
    state is carried forward for audit continuity, while every current-day
    action/exit flag is reset and the missing observation is explicit.
    """
    date_ts = pd.Timestamp(date)
    nominal_nav = max(float(exposure.get("nominal_nav", 0.0) or 0.0), 1e-12)
    mark_by_symbol = {
        str(row.get("symbol", "")): row
        for row in getattr(runner, "_last_position_mark_rows", []) or []
    }
    latest_by_symbol: dict[str, dict] = {}
    for prior in getattr(runner, "position_state_rows", []) or []:
        symbol = str(prior.get("symbol", ""))
        prior_date = pd.to_datetime(prior.get("date"), errors="coerce")
        if symbol and pd.notna(prior_date) and prior_date < date_ts:
            latest_by_symbol[symbol] = prior

    carried_rows: list[dict] = []
    for symbol in sorted(set(getattr(runner, "positions", {})) - observed_symbols):
        prior = dict(latest_by_symbol.get(symbol, {}))
        source_date = prior.get("date", pd.NaT)
        mark = mark_by_symbol.get(symbol, {})
        row = {
            **prior,
            "date": date_ts,
            "symbol": symbol,
            "held": True,
            "holding_days": int(getattr(runner, "holding_days", {}).get(symbol, 0)),
            "account_weight": float(mark.get("market_value", 0.0) or 0.0) / nominal_nav,
            "position_state": "held_unobserved",
            "exit_state": False,
            "position_exit_reason": "",
            "paper_exit_reason": "",
            "paper_exit_state": False,
            "add_allowed": False,
            "add_block_reason": "current_feature_observation_missing",
            "add_decision_type": "hold_unobserved",
            "unified_action_selected": "hold",
            "unified_action_proposals": "",
            "unified_action_vetoed": "",
            "unified_action_conflict_count": 0,
            "exit_triggered_reasons": "",
            "exit_authorized_reasons": "",
            "exit_vetoed_reasons": "",
            "exit_conflict_count": 0,
            "state_observation_status": "carried_forward_missing_current_feature",
            "state_source_date": source_date,
            "valuation_source": mark.get("valuation_source", "last_known_close"),
            "stale_days": mark.get("stale_days", pd.NA),
        }
        for key in tuple(row):
            if key.endswith("_exit") or key.startswith("paper_") and key.endswith("_exit"):
                row[key] = False
        carried_rows.append(row)
    return carried_rows


def apply_position_state_constraints(runner, candidates: pd.DataFrame, *, date, exposure: dict) -> pd.DataFrame:
    if candidates is None or candidates.empty:
        runner.position_state_rows.extend(
            _carried_unobserved_position_states(
                runner,
                date=date,
                exposure=exposure,
                observed_symbols=set(),
            )
        )
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
    # SCAP support evidence is calibrated cross-sectionally at the current
    # decision timestamp. Missing inputs stay missing; they are never turned
    # into a neutral 0.5 score.
    def numeric_column(name: str):
        return pd.to_numeric(
            data.get(name, pd.Series(pd.NA, index=data.index)),
            errors="coerce",
        )

    alpha_support = numeric_column("alpha_quality_score")
    conviction_support = numeric_column("cabinet_hold_support_score")
    conviction_support = conviction_support.where(
        conviction_support.notna(),
        numeric_column("final_entry_score"),
    )
    retention_support = numeric_column("trend_hold_score")
    retention_support = retention_support.where(
        retention_support.notna(),
        numeric_column("entry_success_probability"),
    )
    trend_support = numeric_column("trend_stability_score")
    volume_support = numeric_column("volume_health_score")
    support_complete = (
        alpha_support.notna()
        & conviction_support.notna()
        & retention_support.notna()
        & trend_support.notna()
        & volume_support.notna()
    )
    data["scap_hold_support_score"] = (
        0.30 * alpha_support
        + 0.25 * conviction_support
        + 0.20 * retention_support
        + 0.15 * trend_support
        + 0.10 * volume_support
    ).where(support_complete)
    data["scap_hold_support_quantile"] = pd.to_numeric(
        data["scap_hold_support_score"], errors="coerce"
    ).rank(pct=True)
    data["scap_hold_support_state"] = "cross_sectional_fallback"
    data.loc[~support_complete, "scap_hold_support_state"] = "insufficient"

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
        "add_decision_type": "",
        "add_expected_net_profit_lcb": pd.NA,
        "add_utility_calibration_state": "not_evaluated",
        "scap_hold_support_score": pd.NA,
        "scap_hold_support_quantile": pd.NA,
        "scap_hold_support_state": "insufficient",
        "unified_action_selected": "hold",
        "unified_action_proposals": "hold",
        "unified_action_vetoed": "",
        "unified_action_conflict_count": 0,
        "unified_action_contract": "unified_position_action_v1",
        "hard_stop_exit": False,
        "profit_hard_stop_exit": False,
        "signal_failure_exit": False,
        "signal_failure_confirmation_count": 0,
        "signal_failure_confirmation_required": 1,
        "signal_failure_confirmed": False,
        "loss_containment_confirmation_count": 0,
        "loss_containment_confirmation_required": 1,
        "loss_containment_confirmed": False,
        "adaptive_loss_stop": pd.NA,
        "exit_arbitration_contract": "single_exit_authority_v2",
        "exit_triggered_reasons": "",
        "exit_authorized_reasons": "",
        "exit_vetoed_reasons": "",
        "exit_conflict_count": 0,
        "stale_time_reduce": False,
        "stale_time_exit": False,
        "trend_direction_score": pd.NA,
        "peak_decay_score": pd.NA,
        "profit_protection_pressure": pd.NA,
        "dynamic_giveback_limit": pd.NA,
        "future_loss_risk_score": pd.NA,
        "entry_authority_tier": "",
        "winner_add_review_due": False,
        "winner_add_review_passed": True,
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
        entry_thesis = str(lifecycle.get("entry_thesis", "composite"))
        entry_module_support = _safe_float(lifecycle.get("entry_module_support"), default=0.0)
        current_support_by_thesis = {
            "momentum": _safe_float(row.get("trend_hold_score"), default=trend_score),
            "reversal": _safe_float(row.get("reversal_entry_score"), default=entry_score),
            "orderflow": orderflow_score,
            "breakout": _safe_float(row.get("breakout_gate_score"), default=0.0),
            "composite": entry_score,
        }
        cabinet_family_column = "cabinet_family_" + "".join(
            char if char.isalnum() else "_" for char in entry_thesis.lower()
        ).strip("_") + "_score"
        if cabinet_family_column in row.index:
            current_support_by_thesis[entry_thesis] = _safe_float(row.get(cabinet_family_column), default=0.5)
        current_module_support = _clip01(current_support_by_thesis.get(entry_thesis, entry_score))
        support_decay = max(entry_module_support - current_module_support, 0.0)
        last_add_date = pd.to_datetime(
            lifecycle.get("last_add_date", pd.NaT), errors="coerce"
        )
        add_review_age = (
            int((date_ts - last_add_date).days)
            if pd.notna(last_add_date)
            else 0
        )
        winner_add_review_due = bool(
            is_held and pd.notna(last_add_date) and add_review_age >= 10
        )
        winner_add_review_passed = bool(
            not winner_add_review_due
            or (
                _safe_float(row.get("add_expected_net_profit_lcb"), 0.0) > 0.0
                and support_decay < 0.20
            )
        )
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
        if entry_thesis == "composite":
            current_module_support = signal_retention_score
            support_decay = max(entry_module_support - current_module_support, 0.0)
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
        if (
            str(getattr(runner, "governance_control_mode", "")).strip().lower()
            == "aggressive_profit"
            and not bool(
                runner.capital_profile.get(
                    "scap_cooldown_override_enabled", False
                )
            )
        ):
            cooldown_override = False

        net_unrealized = float(unrealized) - _governance_round_trip_cost_rate()
        net_mfe = float(mfe) - _governance_round_trip_cost_rate()
        profit_arm_trigger = float(GOVERNANCE_PROFIT_HARD_STOP_ARM_TRIGGER)
        profit_min_net = float(GOVERNANCE_PROFIT_HARD_STOP_MIN_NET_PROFIT)
        profit_giveback_limit = float(GOVERNANCE_PROFIT_HARD_STOP_TRAIL_GIVEBACK)
        if str(getattr(runner, "governance_control_mode", "")).strip().lower() == "aggressive_lean":
            profit_arm_trigger = float(
                runner.capital_profile.get(
                    "scap_profit_protection_arm", profit_arm_trigger
                )
            )
            profit_min_net = float(
                runner.capital_profile.get(
                    "scap_profit_protection_min_net_profit", profit_min_net
                )
            )
            profit_giveback_limit = float(
                runner.capital_profile.get(
                    "scap_profit_protection_giveback", profit_giveback_limit
                )
            )
        hard_stop = bool(
            is_held
            and net_mfe >= profit_arm_trigger
            and net_unrealized >= profit_min_net
            and (net_mfe - net_unrealized) / max(net_mfe, 1e-12)
            >= profit_giveback_limit
        )
        loss_containment = bool(
            is_held
            and holding_days >= 3
            and net_unrealized <= float(GOVERNANCE_HARD_STOP_LOSS)
        )
        paper_loss_containment = loss_containment
        scap_loss_stop = float(GOVERNANCE_HARD_STOP_LOSS)
        scap_disaster_stop = float(GOVERNANCE_HARD_STOP_LOSS)
        loss_stop_kind = "legacy_hard_stop"
        if str(getattr(runner, "governance_control_mode", "")).strip().lower() in {
            "aggressive_profit",
            "aggressive_lean",
        }:
            scap_loss_stop = float(runner.capital_profile.get("scap_loss_stop", -0.12))
            loss_stop_mode = str(
                runner.capital_profile.get(
                    "scap_loss_stop_mode", "fixed"
                )
                or "fixed"
            ).strip().lower()
            if loss_stop_mode == "adaptive_volatility_or_disaster_floor":
                scap_loss_stop, scap_disaster_stop = resolve_scap_loss_limits(
                    runner.capital_profile,
                    tail_risk_proxy=tail_risk_proxy,
                    disaster_floor=scap_disaster_stop,
                )
                loss_stop_kind = "adaptive_soft_with_disaster_floor"
            disaster_breach = bool(
                is_held and holding_days >= 1 and net_unrealized <= scap_disaster_stop
            )
            paper_loss_containment = bool(
                is_held and holding_days >= 3 and net_unrealized <= scap_loss_stop
            )
            loss_confirmation_required = max(
                int(
                    runner.capital_profile.get(
                        "scap_loss_stop_confirmation_days", 1
                    )
                    or 1
                ),
                1,
            )
            (
                loss_confirmation_count,
                loss_containment_confirmed,
            ) = update_consecutive_confirmation(
                runner.position_exit_confirmations,
                symbol=symbol,
                signal_name="loss_containment",
                date=date_ts,
                triggered=paper_loss_containment,
                required_days=loss_confirmation_required,
            )
            loss_containment = bool(
                disaster_breach
                or (
                    loss_containment_confirmed
                    and scap_loss_containment_exit(
                        exit_stage=str(
                            runner.capital_profile.get(
                                "scap_exit_stage", "E0"
                            )
                            or "E0"
                        ),
                        is_held=is_held,
                        holding_days=holding_days,
                        net_unrealized_return=net_unrealized,
                        loss_stop=scap_loss_stop,
                    )
                )
            )
            if disaster_breach:
                loss_confirmation_count = loss_confirmation_required
                loss_containment_confirmed = True
                loss_stop_kind = "immediate_disaster_floor"
        else:
            loss_confirmation_required = 1
            loss_confirmation_count = int(loss_containment)
            loss_containment_confirmed = bool(loss_containment)
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
        thesis_grace_days = 20 if entry_thesis in {
            "value", "growth", "cashflow_quality", "profitability_quality"
        } else int(GOVERNANCE_STALE_WATCH_DAYS)
        raw_signal_failure = bool(
            is_held
            and holding_days >= int(thesis_grace_days)
            and entry_score < float(GOVERNANCE_ENTRY_MATRIX_EXIT_DECAY_THRESHOLD)
            and trend_score < 0.45
        )
        thesis_failure = bool(
            is_held
            and holding_days >= int(thesis_grace_days)
            and entry_module_support >= 0.45
            and current_module_support < 0.35
            and support_decay >= 0.20
        )
        downtrend_exit = bool(
            is_held
            and (
                not is_mainline_v3_version(getattr(runner, "strategy_logic_version", ""))
                or holding_days >= int(thesis_grace_days)
            )
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

        post_entry_failure_signal = bool(
            early_post_entry_failure or row.get("post_entry_failure_exit", False)
        )
        post_entry_failure_control_enabled = bool(
            runner._control_enabled("post_entry_failure_exit")
        )
        post_entry_failure_mode = str(
            runner.capital_profile.get("scap_post_entry_failure_mode", "legacy")
            or "legacy"
        )
        preliminary_post_entry_authority = resolve_post_entry_failure_authority(
            signal_detected=post_entry_failure_signal,
            strategy_logic_version=getattr(runner, "strategy_logic_version", ""),
            control_mode=getattr(runner, "governance_control_mode", ""),
            control_enabled=post_entry_failure_control_enabled,
            configured_mode=post_entry_failure_mode,
        )
        post_entry_failure_policy_enabled = bool(
            preliminary_post_entry_authority["policy_enabled"]
        )
        active_post_entry_failure = bool(
            post_entry_failure_signal and post_entry_failure_policy_enabled
        )
        signal_failure_raw_any = bool(
            raw_signal_failure or thesis_failure or downtrend_exit
        )
        confirmation_required = 1
        if (
            str(getattr(runner, "governance_control_mode", "")).strip().lower()
            == "aggressive_profit"
        ):
            confirmation_required = int(
                runner.capital_profile.get(
                    "scap_signal_failure_confirmation_days", 3
                )
                or 3
            )
        confirmation_count, signal_failure_confirmed = (
            update_consecutive_confirmation(
                runner.position_exit_confirmations,
                symbol=symbol,
                signal_name="signal_failure_family",
                date=date_ts,
                triggered=signal_failure_raw_any,
                required_days=confirmation_required,
            )
        )
        paper_arbitration = arbitrate_exit_signals(
            {
                "profit_hard_stop_exit": hard_stop,
                "profit_giveback_exit": profit_giveback or peak_decay_exit,
                "loss_containment_exit": loss_containment,
                "post_entry_failure_exit": post_entry_failure_signal,
                "thesis_failure_exit": thesis_failure,
                "signal_failure_exit": raw_signal_failure or downtrend_exit,
                "stale_time_exit": stale_exit,
            }
        )
        active_arbitration = arbitrate_exit_signals(
            {
                "profit_hard_stop_exit": hard_stop,
                "profit_giveback_exit": profit_giveback or peak_decay_exit,
                "loss_containment_exit": paper_loss_containment,
                "post_entry_failure_exit": active_post_entry_failure,
                "thesis_failure_exit": (
                    thesis_failure and signal_failure_confirmed
                ),
                "signal_failure_exit": (
                    (raw_signal_failure or downtrend_exit)
                    and signal_failure_confirmed
                ),
                "stale_time_exit": stale_exit,
            },
            control_enabled=runner._control_enabled,
        )
        exit_reason = active_arbitration.active_reason
        paper_exit_reason = paper_arbitration.paper_reason
        exit_state = bool(exit_reason)
        post_entry_authority = resolve_post_entry_failure_authority(
            signal_detected=post_entry_failure_signal,
            strategy_logic_version=getattr(runner, "strategy_logic_version", ""),
            control_mode=getattr(runner, "governance_control_mode", ""),
            control_enabled=post_entry_failure_control_enabled,
            authorized_reasons=active_arbitration.authorized_reasons,
            selected_reason=exit_reason,
            configured_mode=post_entry_failure_mode,
        )
        post_entry_failure_authority_active = bool(
            post_entry_authority["authority_active"]
        )
        post_entry_failure_veto_reasons = list(
            post_entry_authority["veto_reasons"]
        )

        buy_count = int(lifecycle.get("buy_count", 1 if is_held else 0) or 0)
        next_layer = min(buy_count + 1, max_layers)
        add_allowed = False
        add_block_reason = "not_held"
        add_decision_type = ""
        is_loser_add = bool(is_held and unrealized < 0.0)
        is_winner_add = bool(is_held and unrealized >= 0.0)
        loser_averaging_enabled = bool(
            runner.capital_profile.get("scap_loser_averaging_enabled", False)
        )
        winner_pyramiding_enabled = bool(
            runner.capital_profile.get("scap_winner_pyramiding_enabled", False)
        )
        winner_triggers = tuple(
            float(value)
            for value in runner.capital_profile.get(
                "scap_winner_pyramiding_trigger_returns", (0.05, 0.10)
            )
        )
        hold_support_score = pd.to_numeric(
            pd.Series([row.get("scap_hold_support_score")]), errors="coerce"
        ).iloc[0]
        hold_support_quantile = pd.to_numeric(
            pd.Series([row.get("scap_hold_support_quantile")]), errors="coerce"
        ).iloc[0]
        comparable_lcb = pd.to_numeric(
            pd.Series([row.get("comparable_alpha_lcb")]), errors="coerce"
        ).iloc[0]
        comparable_point = pd.to_numeric(
            pd.Series([row.get("comparable_expected_alpha")]), errors="coerce"
        ).iloc[0]
        one_lot_notional = pd.to_numeric(
            pd.Series([row.get("mainline_v3_one_lot_cash_required")]),
            errors="coerce",
        ).iloc[0]
        rule = trading_rule_for(symbol, trade_date=date_ts)
        close_price = pd.to_numeric(
            pd.Series([row.get("close_nominal", row.get("close"))]),
            errors="coerce",
        ).iloc[0]
        add_cost = (
            round_trip_cost_amount(
                symbol=symbol,
                price=float(close_price),
                shares=float(rule.minimum_buy_quantity),
                trade_date=date_ts,
            )
            if pd.notna(close_price) and float(close_price) > 0.0
            else 0.0
        )
        add_utility = build_incremental_action_utility(
            action_type=(
                "loser_add" if is_loser_add else "winner_add"
            ),
            notional=(
                float(one_lot_notional)
                if pd.notna(one_lot_notional)
                else (
                    float(close_price) * float(rule.minimum_buy_quantity)
                    if pd.notna(close_price)
                    else 0.0
                )
            ),
            expected_return_point=comparable_point,
            expected_return_lcb=comparable_lcb,
            estimated_total_cost=add_cost,
            horizon_days=int(
                pd.to_numeric(
                    pd.Series([row.get("comparable_value_horizon_days", 10)]),
                    errors="coerce",
                ).fillna(10).iloc[0]
            ),
            risk_penalty_amount=(
                max(float(future_loss_risk_score) - 0.50, 0.0)
                * 0.005
                * (
                    float(one_lot_notional)
                    if pd.notna(one_lot_notional)
                    else 0.0
                )
            ),
            calibration_state=(
                "calibrated"
                if pd.notna(comparable_point) and pd.notna(comparable_lcb)
                else "insufficient"
            ),
            decision_return_basis=str(
                runner.capital_profile.get("scap_candidate_reward_basis", "lcb")
                or "lcb"
            ),
            proposal_id=f"{date_ts.date()}|{symbol}|add",
        )
        if is_held:
            if exit_state:
                add_block_reason = f"exit_state:{exit_reason}"
            elif is_loser_add and not loser_averaging_enabled:
                add_block_reason = "scap_loser_averaging_disabled"
            elif is_winner_add and not winner_pyramiding_enabled:
                add_block_reason = "scap_winner_pyramiding_disabled"
            elif stale_reduce and runner._control_enabled("stale_exit"):
                add_block_reason = "stale_time_reduce"
            elif cooldown_active and not cooldown_override and runner._control_enabled("cooldown"):
                add_block_reason = "cooldown_active"
            elif protecting_profit:
                add_block_reason = "protecting_profit_no_add"
            elif buy_count >= max_layers:
                add_block_reason = "max_layers_reached"
            elif account_weight >= _active_single_position_cap(runner):
                add_block_reason = "single_name_account_cap"
            else:
                gap_index = min(max(buy_count - 1, 0), len(add_gaps) - 1)
                winner_index = min(gap_index, max(len(winner_triggers) - 1, 0))
                loser_gap_reached = bool(
                    is_loser_add and unrealized <= add_gaps[gap_index]
                )
                winner_gap_reached = bool(
                    is_winner_add
                    and winner_triggers
                    and unrealized >= winner_triggers[winner_index]
                )
                required_support_quantile = 0.70 if is_loser_add else 0.60
                if not (loser_gap_reached or winner_gap_reached):
                    add_block_reason = (
                        "loser_averaging_gap_not_reached"
                        if is_loser_add
                        else "winner_pyramiding_trigger_not_reached"
                    )
                elif pd.isna(hold_support_quantile):
                    add_block_reason = "hold_support_insufficient"
                elif float(hold_support_quantile) < required_support_quantile:
                    add_block_reason = "hold_support_insufficient"
                elif (
                    is_loser_add
                    and (
                        float(future_loss_risk_score) >= 0.75
                        or float(downtrend_score) >= 0.80
                    )
                ):
                    add_block_reason = "loser_add_tail_risk"
                elif add_utility.incremental_terminal_wealth <= 0.0:
                    add_block_reason = "net_utility_non_positive"
                elif loser_gap_reached:
                    add_allowed = True
                    add_decision_type = "loser_averaging"
                    add_block_reason = "allowed"
                elif winner_gap_reached:
                    add_allowed = True
                    add_decision_type = "winner_pyramiding"
                    add_block_reason = "allowed"

        action_arbitration = arbitrate_position_actions(
            {
                "exit": exit_state,
                "loser_averaging": add_allowed
                and add_decision_type == "loser_averaging",
                "winner_pyramiding": add_allowed
                and add_decision_type == "winner_pyramiding",
                "hold": not exit_state and not add_allowed,
            }
        )

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
        position_cap = _active_single_position_cap(runner)
        add_budget = (
            float(layer_weights[layer_index]) * position_cap
            if add_allowed
            else 0.0
        )
        post_entry_failure = bool(early_post_entry_failure or row.get("post_entry_failure_exit", False))
        configured_cooldown_days = int(
            runner.capital_profile.get(
                "scap_reentry_cooldown_days",
                GOVERNANCE_BUY_SELL_CONFLICT_COOLDOWN_DAYS,
            )
            if str(getattr(runner, "governance_control_mode", "")).strip().lower()
            == "aggressive_profit"
            else GOVERNANCE_BUY_SELL_CONFLICT_COOLDOWN_DAYS
        )
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
            "buy_sell_conflict_cooldown_days": configured_cooldown_days,
            "add_allowed": add_allowed,
            "add_block_reason": add_block_reason,
            "add_layer": next_layer if is_held else 0,
            "add_budget": add_budget,
            "add_decision_type": add_decision_type,
            "add_expected_net_profit_lcb": float(
                add_utility.incremental_terminal_wealth
            ),
            "add_utility_calibration_state": add_utility.calibration_state,
            "scap_hold_support_score": hold_support_score,
            "scap_hold_support_quantile": hold_support_quantile,
            "scap_hold_support_state": row.get(
                "scap_hold_support_state", "insufficient"
            ),
            "unified_action_selected": action_arbitration.selected_action,
            "unified_action_proposals": "|".join(
                action_arbitration.proposed_actions
            ),
            "unified_action_vetoed": "|".join(
                action_arbitration.vetoed_actions
            ),
            "unified_action_conflict_count": action_arbitration.conflict_count,
            "unified_action_contract": action_arbitration.contract,
            "hard_stop_exit": hard_stop and runner._control_enabled("hard_stop_exit"),
            "profit_hard_stop_exit": hard_stop and runner._control_enabled("hard_stop_exit"),
            "paper_hard_stop_exit": hard_stop,
            "paper_profit_hard_stop_exit": hard_stop,
            "loss_containment_exit": loss_containment and runner._control_enabled("loss_containment_exit"),
            "paper_loss_containment_exit": paper_loss_containment,
            "loss_containment_confirmation_count": loss_confirmation_count,
            "loss_containment_confirmation_required": loss_confirmation_required,
            "loss_containment_confirmed": loss_containment_confirmed,
            "adaptive_loss_stop": scap_loss_stop if is_held else pd.NA,
            "disaster_loss_stop": scap_disaster_stop if is_held else pd.NA,
            "loss_stop_kind": loss_stop_kind if is_held else "",
            "hard_stop_net_mfe": net_mfe if is_held else pd.NA,
            "hard_stop_net_unrealized": net_unrealized if is_held else pd.NA,
            "hard_stop_giveback_from_net_peak": (
                (net_mfe - net_unrealized) / max(net_mfe, 1e-12)
                if is_held and net_mfe > 0.0
                else pd.NA
            ),
            "profit_giveback_exit": bool(profit_giveback or peak_decay_exit) and runner._control_enabled("profit_giveback_exit"),
            "paper_profit_giveback_exit": bool(profit_giveback or peak_decay_exit),
            # Legacy *_exit fields mean actual trading authority.  Raw/paper
            # observations are kept separately and must never masquerade as an
            # authorized exit in reports or Web surfaces.
            "post_entry_failure_exit": post_entry_failure_authority_active,
            "paper_post_entry_failure_exit": post_entry_failure,
            "post_entry_failure_detected": post_entry_failure_signal,
            "post_entry_failure_paper_active": post_entry_failure_signal,
            "post_entry_failure_policy_enabled": post_entry_failure_policy_enabled,
            "post_entry_failure_authority_mode": post_entry_failure_mode,
            "post_entry_failure_control_enabled": post_entry_failure_control_enabled,
            "post_entry_failure_authority_active": post_entry_failure_authority_active,
            "post_entry_failure_authority_veto_reasons": "|".join(
                post_entry_failure_veto_reasons
            ),
            "post_entry_failure_selected_exit": bool(
                post_entry_authority["selected_for_exit"]
            ),
            "signal_failure_exit": bool(
                (raw_signal_failure or downtrend_exit)
                and signal_failure_confirmed
                and runner._control_enabled("signal_failure_exit")
            ),
            "paper_signal_failure_exit": bool(raw_signal_failure or downtrend_exit),
            "signal_failure_confirmation_count": confirmation_count,
            "signal_failure_confirmation_required": confirmation_required,
            "signal_failure_confirmed": signal_failure_confirmed,
            "exit_arbitration_contract": active_arbitration.contract,
            "exit_triggered_reasons": "|".join(
                paper_arbitration.triggered_reasons
            ),
            "exit_authorized_reasons": "|".join(
                active_arbitration.authorized_reasons
            ),
            "exit_vetoed_reasons": "|".join(
                active_arbitration.vetoed_reasons
            ),
            "exit_conflict_count": paper_arbitration.conflict_count,
            "entry_thesis": entry_thesis,
            "entry_authority_tier": str(
                lifecycle.get("entry_authority_tier", "")
            ),
            "entry_logic_version": str(lifecycle.get("entry_logic_version", "")),
            "entry_module_support": entry_module_support,
            "current_module_support": current_module_support,
            "support_decay": support_decay,
            "thesis_failure_exit": bool(
                thesis_failure
                and signal_failure_confirmed
                and runner._control_enabled("signal_failure_exit")
            ),
            "paper_thesis_failure_exit": thesis_failure,
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
            "winner_add_review_due": winner_add_review_due,
            "winner_add_review_passed": winner_add_review_passed,
            "factor_conviction_score": factor_conviction_score,
            "signal_retention_score": signal_retention_score,
            "liquidity_decay_score": liquidity_decay_score,
            "risk_contribution_penalty": row.get("risk_contribution_penalty", 0.0),
            "risk_adjusted_primary_score": row.get("risk_adjusted_primary_score", row.get("primary_score", pd.NA)),
            "cabinet_native_final_score": row.get("cabinet_native_final_score", pd.NA),
            "cabinet_strict_entry_score": row.get("cabinet_strict_entry_score", pd.NA),
            "cabinet_proxy_entry_score": row.get("cabinet_proxy_entry_score", pd.NA),
            "cabinet_timing_score": row.get("cabinet_timing_score", pd.NA),
            "cabinet_liquidity_health_score": row.get("cabinet_liquidity_health_score", pd.NA),
            "cabinet_risk_safety_score": row.get("cabinet_risk_safety_score", pd.NA),
            "cabinet_hold_support_score": row.get("cabinet_hold_support_score", pd.NA),
            "comparable_value_horizon_days": row.get("comparable_value_horizon_days", pd.NA),
            "comparable_expected_alpha": row.get("comparable_expected_alpha", pd.NA),
            "comparable_alpha_lcb": row.get("comparable_alpha_lcb", pd.NA),
            "comparable_value_contract": row.get("comparable_value_contract", ""),
            "entry_size_tier": row.get("entry_size_tier", ""),
            "planned_entry_lots": row.get("planned_entry_lots", pd.NA),
            "entry_alpha_quality_at_buy": entry_alpha_quality_at_buy if is_held else pd.NA,
            "alpha_quality_drop_from_entry": alpha_quality_drop_from_entry if is_held else 0.0,
            "downtrend_decay_score": downtrend_score,
            "post_entry_failure_score": post_entry_failure_score,
            "post_entry_failure_threshold": (
                float(early_threshold)
                if early_threshold is not None
                else float(GOVERNANCE_POST_ENTRY_FAILURE_EXIT_SCORE)
            ),
        }
        for key, value in updates.items():
            data.at[idx, key] = value
        if is_held:
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
    state_rows.extend(
        _carried_unobserved_position_states(
            runner,
            date=date_ts,
            exposure=exposure,
            observed_symbols={str(row.get("symbol", "")) for row in state_rows},
        )
    )
    runner.position_state_rows.extend(state_rows)
    return data

def apply_candidate_risk_penalty(
    runner,
    candidates: pd.DataFrame,
    *,
    exposure: dict,
    score_column: str = "primary_score",
) -> pd.DataFrame:
    if candidates is None or candidates.empty:
        return candidates
    data = candidates.copy()
    if score_column not in data.columns:
        return data
    nominal_nav = max(float(exposure.get("nominal_nav", 0.0) or 0.0), 1e-12)
    current_weights = {
        str(row.get("symbol", "")): float(row.get("market_value", 0.0) or 0.0) / nominal_nav
        for row in getattr(runner, "_last_position_mark_rows", []) or []
    }
    primary = pd.to_numeric(data[score_column], errors="coerce")
    account_weight = data["symbol"].astype(str).map(lambda symbol: float(current_weights.get(symbol, 0.0) or 0.0))
    price_col = "close_nominal" if "close_nominal" in data.columns else "close"
    price = pd.to_numeric(data.get(price_col, pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0).clip(lower=0.0)
    planned_lots = pd.to_numeric(data.get("planned_entry_lots", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
    buy_intent = (
        data.get("entry_confirmed", pd.Series(False, index=data.index)).fillna(False).astype(bool)
        | data.get("direct_buy_flag", pd.Series(False, index=data.index)).fillna(False).astype(bool)
        | data.get("surge_buy_flag", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    )
    # Score every possible new entry on the same one-lot prospective basis;
    # restricting the penalty to a previous selection makes ranking path-dependent.
    held_mask = account_weight.gt(0.0)
    planned_lots = planned_lots.where(planned_lots > 0.0, 1.0)
    planned_lots = planned_lots.where(~held_mask | buy_intent, 0.0)
    minimum_buy_quantity = data["symbol"].astype(str).map(
        lambda symbol: float(trading_rule_for(symbol).minimum_buy_quantity)
    )
    prospective_entry_weight = (price * minimum_buy_quantity * planned_lots) / nominal_nav
    projected_weight = account_weight + prospective_entry_weight
    single_cap = _active_single_position_cap(runner)
    research_cap = float(GOVERNANCE_HIGH_EXPOSURE_MAX_TOP1_RISK_CONTRIBUTION)
    soft_cap = max(min(single_cap, research_cap), 1e-12)
    penalty = ((projected_weight / soft_cap) - 1.0).clip(lower=0.0, upper=2.0) * float(GOVERNANCE_RISK_CONTRIBUTION_SCORE_PENALTY)
    # Every possible new entry is evaluated on the same prospective one-lot
    # basis. Applying the penalty only to a previous selection made the final
    # ranking depend on the obsolete first-pass optimizer.
    data["raw_primary_score"] = primary
    data["risk_penalty_source_score"] = str(score_column)
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
    if (
        str(getattr(runner, "governance_control_mode", "")).strip().lower()
        == "aggressive_profit"
    ):
        days = int(
            runner.capital_profile.get(
                "scap_reentry_cooldown_days",
                GOVERNANCE_BUY_SELL_CONFLICT_COOLDOWN_DAYS,
            )
            or GOVERNANCE_BUY_SELL_CONFLICT_COOLDOWN_DAYS
        )
    else:
        days = int(GOVERNANCE_BUY_SELL_CONFLICT_COOLDOWN_DAYS)
    runner.position_cooldowns[str(symbol)] = {
        "cooldown_start": pd.Timestamp(date),
        "cooldown_until": pd.Timestamp(date) + pd.offsets.BDay(days),
        "reason": reason,
        "cooldown_days": days,
    }
