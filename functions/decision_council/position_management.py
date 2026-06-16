"""P0 position-management contracts and conservative Kelly decisions.

This module is intentionally independent from the existing phase-one policy so
the new contracts can be verified before the main governance path is switched
from alpha-score allocation to Kelly-led position management.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
from scipy.stats import beta as beta_distribution

from config import (
    DATA_VERSION,
    POSITION_A500_MIN_COVERAGE_RATIO,
    POSITION_BAYES_LOWER_CONFIDENCE,
    POSITION_BAYES_PRIOR_P,
    POSITION_BAYES_PRIOR_SOURCE,
    POSITION_BAYES_PRIOR_STRENGTH,
    POSITION_CONFLICT_BLOCK_THRESHOLD,
    POSITION_CONFLICT_EXIT_THRESHOLD,
    POSITION_DEFAULT_RETURN_HORIZON_DAYS,
    POSITION_EMERGENCY_SINGLE_DAY_DRAWDOWN,
    POSITION_EXIT_EXPECTED_RETURN_20D,
    POSITION_EXIT_HYSTERESIS_DAYS,
    POSITION_HOLD_KELLY_SCORE,
    POSITION_KELLY_SCALE,
    POSITION_MIN_P_WIN,
    POSITION_PAYOFF_MAX,
    POSITION_PAYOFF_MIN,
    POSITION_RISK_DISCOUNT_SMOOTH_DAYS,
    POSITION_SEVERE_EXIT_KELLY_SCORE,
    POSITION_SINGLE_STOCK_CAP,
    POSITION_STRATEGY_GROUP_CAP,
    STRATEGY_PARAMS_VERSION,
    V6_STRATEGY_GROUPS,
)
from functions.decision_council.contracts import SafetyDecision


STRATEGY_SIGNAL_REQUIRED_COLUMNS = (
    "strategy_id",
    "strategy_version",
    "group_id",
    "symbol",
    "event_id",
    "direction",
    "predicted_return",
    "return_horizon_days",
    "confidence",
    "volatility_estimate",
    "stop_loss_pct",
    "take_profit_pct",
    "max_holding_days",
    "exit_signal_confidence",
    "signal_timestamp",
    "tradeable_timestamp",
    "reference_date",
    "signal_source_precision",
    "source_columns",
    "data_version",
    "parameter_version",
)

AGGREGATED_SIGNAL_COLUMNS = (
    "symbol",
    "aggregate_direction",
    "expected_return",
    "return_horizon_days",
    "p_win",
    "p_win_mean",
    "p_win_lower",
    "p_loss",
    "avg_win",
    "avg_loss",
    "payoff_ratio",
    "aggregate_confidence",
    "signal_conflict_score",
    "strategy_vote_count",
    "effective_sample_size",
    "prior_p",
    "prior_strength",
    "prior_source",
    "posterior_alpha",
    "posterior_beta",
    "posterior_sample_count",
)


@dataclass(frozen=True)
class StrategySignal:
    strategy_id: str
    strategy_version: str
    group_id: str
    symbol: str
    event_id: str
    direction: str
    predicted_return: float
    return_horizon_days: int
    confidence: float
    volatility_estimate: float
    stop_loss_pct: float
    take_profit_pct: float
    max_holding_days: int
    exit_signal_confidence: float
    signal_timestamp: pd.Timestamp
    tradeable_timestamp: pd.Timestamp
    reference_date: pd.Timestamp
    signal_source_precision: str
    source_columns: str
    data_version: str
    parameter_version: str

    def to_record(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "group_id": self.group_id,
            "symbol": self.symbol,
            "event_id": self.event_id,
            "direction": self.direction,
            "predicted_return": self.predicted_return,
            "return_horizon_days": self.return_horizon_days,
            "confidence": self.confidence,
            "volatility_estimate": self.volatility_estimate,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "max_holding_days": self.max_holding_days,
            "exit_signal_confidence": self.exit_signal_confidence,
            "signal_timestamp": self.signal_timestamp,
            "tradeable_timestamp": self.tradeable_timestamp,
            "reference_date": self.reference_date,
            "signal_source_precision": self.signal_source_precision,
            "source_columns": self.source_columns,
            "data_version": self.data_version,
            "parameter_version": self.parameter_version,
        }


@dataclass(frozen=True)
class AggregatedSignal:
    symbol: str
    aggregate_direction: str
    expected_return: float
    return_horizon_days: int
    p_win: float
    p_win_mean: float
    p_win_lower: float
    p_loss: float
    avg_win: float
    avg_loss: float
    payoff_ratio: float
    aggregate_confidence: float
    signal_conflict_score: float
    strategy_vote_count: int
    effective_sample_size: float
    prior_p: float
    prior_strength: float
    prior_source: str
    posterior_alpha: float
    posterior_beta: float
    posterior_sample_count: float


@dataclass(frozen=True)
class PositionManagementDecision:
    symbol: str
    current_weight: float
    target_weight: float
    kelly_raw: float
    kelly_scale: float
    risk_discount: float
    kelly_adjusted: float
    kelly_score: float
    position_action: str
    action_reason: str
    exposure_cap: float
    risk_level: str
    expected_return_20d: float
    p_win: float
    payoff_ratio: float
    position_state: str

    def to_safety_decision(
        self,
        *,
        decision_date,
        benchmark_drawdown_5d: float | None = None,
        market_liquidity_stress_ratio: float = 0.0,
        proxy_symbol: str | None = None,
        proxy_mode: str = "position_management_adapter",
        degraded: bool = False,
    ) -> SafetyDecision:
        """Adapt the new position decision to the legacy safety contract."""
        return SafetyDecision(
            decision_date=pd.Timestamp(decision_date),
            risk_level=self.risk_level,
            exposure_cap=float(self.exposure_cap),
            benchmark_drawdown_5d=benchmark_drawdown_5d,
            market_liquidity_stress_ratio=float(market_liquidity_stress_ratio),
            proxy_symbol=proxy_symbol,
            proxy_mode=proxy_mode,
            degraded=bool(degraded),
        )


def validate_strategy_signal_frame(signals: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(STRATEGY_SIGNAL_REQUIRED_COLUMNS) - set(signals.columns))
    if missing:
        raise ValueError(f"StrategySignal missing required columns: {missing}")
    data = signals.copy()
    data["direction"] = data["direction"].astype(str).str.lower()
    allowed = {"long", "short", "flat"}
    bad_directions = sorted(set(data["direction"]) - allowed)
    if bad_directions:
        raise ValueError(f"StrategySignal contains invalid direction values: {bad_directions}")
    data["signal_source_precision"] = data["signal_source_precision"].astype(str).str.lower()
    allowed_precision = {"pre_market", "intraday", "post_market", "unknown"}
    bad_precision = sorted(set(data["signal_source_precision"]) - allowed_precision)
    if bad_precision:
        raise ValueError(f"StrategySignal contains invalid source precision values: {bad_precision}")
    for column in [
        "predicted_return",
        "confidence",
        "volatility_estimate",
        "stop_loss_pct",
        "take_profit_pct",
        "exit_signal_confidence",
    ]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data["return_horizon_days"] = pd.to_numeric(data["return_horizon_days"], errors="coerce").astype("Int64")
    data["max_holding_days"] = pd.to_numeric(data["max_holding_days"], errors="coerce").astype("Int64")
    data["signal_timestamp"] = pd.to_datetime(data["signal_timestamp"], errors="coerce")
    data["tradeable_timestamp"] = pd.to_datetime(data["tradeable_timestamp"], errors="coerce")
    data["reference_date"] = pd.to_datetime(data["reference_date"], errors="coerce")
    if data[list(STRATEGY_SIGNAL_REQUIRED_COLUMNS)].isna().any().any():
        raise ValueError("StrategySignal contains null values in required fields")
    if (data["tradeable_timestamp"] < data["signal_timestamp"]).any():
        raise ValueError("StrategySignal tradeable_timestamp precedes signal_timestamp")
    if (data["reference_date"] < data["tradeable_timestamp"]).any():
        raise ValueError("StrategySignal reference_date precedes tradeable_timestamp")
    duplicate_events = data.duplicated(["strategy_id", "symbol", "event_id"], keep=False)
    if duplicate_events.any():
        raise ValueError("StrategySignal event_id must be unique within strategy and symbol")
    return data


def aggregate_strategy_signals(
    signals: pd.DataFrame,
    *,
    strategy_stats: pd.DataFrame | None = None,
    correlation_matrix: pd.DataFrame | None = None,
    default_horizon_days: int = POSITION_DEFAULT_RETURN_HORIZON_DAYS,
) -> pd.DataFrame:
    """Aggregate strategy signals into calibrated inputs for Kelly sizing.

    `strategy_stats` is expected to contain out-of-sample fields:
    strategy_id, reputation_weight, wins, losses, avg_win, avg_loss.
    Missing stats use the conservative cold-start prior and therefore produce
    near-zero Kelly sizing unless other strategies provide evidence.
    """
    data = validate_strategy_signal_frame(signals)
    if data.empty:
        return pd.DataFrame(columns=AGGREGATED_SIGNAL_COLUMNS)

    stats = _normalize_strategy_stats(strategy_stats)
    data = data.merge(stats, on="strategy_id", how="left")
    for column, default in [
        ("reputation_weight", 1.0),
        ("wins", 0.0),
        ("losses", 0.0),
        ("avg_win", 0.0),
        ("avg_loss", 0.0),
    ]:
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(default)
    data["direction_sign"] = data["direction"].map({"long": 1.0, "flat": 0.0, "short": -1.0})
    data["vote_weight"] = (
        data["reputation_weight"]
        * data["confidence"].clip(0.0, 1.0)
        * data["direction_sign"].abs()
    )
    group_totals = data.groupby(["symbol", "group_id"])["vote_weight"].transform("sum")
    symbol_totals = data.groupby("symbol")["vote_weight"].transform("sum")
    group_share = group_totals / symbol_totals.replace(0.0, np.nan)
    group_scale = (
        float(POSITION_STRATEGY_GROUP_CAP)
        / group_share.replace(0.0, np.nan)
    ).clip(upper=1.0).fillna(1.0)
    data["vote_weight"] *= group_scale

    rows = []
    for symbol, group in data.groupby("symbol", sort=True):
        long_weight = float(group.loc[group["direction"] == "long", "vote_weight"].sum())
        short_weight = float(group.loc[group["direction"] == "short", "vote_weight"].sum())
        total_directional = long_weight + short_weight
        conflict = min(long_weight, short_weight) / total_directional if total_directional > 0 else 0.0
        signed_return = group["predicted_return"] * group["direction_sign"]
        expected_return = _weighted_average(signed_return, group["vote_weight"], fallback=0.0)
        posterior = _beta_binomial_p_win(group)
        p_win_mean = posterior["mean"]
        p_win_lower = posterior["lower"]
        avg_win = _weighted_average(group["avg_win"].clip(lower=0.0), group["reputation_weight"], fallback=0.0)
        avg_loss = _weighted_average(group["avg_loss"].clip(upper=0.0), group["reputation_weight"], fallback=0.0)
        sample_count = float(((group["wins"] + group["losses"]) * group["reputation_weight"].clip(lower=0.0)).sum())
        cold_start_confidence = _weighted_average(
            group["confidence"].clip(0.0, 1.0),
            group["vote_weight"],
            fallback=0.0,
        )
        if sample_count <= 0.0:
            p_win_mean = 0.5
            p_win_lower = 0.5
            avg_win = 0.0
            avg_loss = 0.0
        p_loss = 1.0 - p_win_lower
        if avg_win <= 0.0 or avg_loss >= 0.0:
            payoff_ratio = 1.0
        else:
            payoff_ratio = float(np.clip(avg_win / abs(avg_loss), POSITION_PAYOFF_MIN, POSITION_PAYOFF_MAX))
        n_eff = _effective_sample_size(group, correlation_matrix)
        aggregate_confidence = _aggregate_confidence(group, conflict, n_eff)
        aggregate_direction = "long" if expected_return > 0 and long_weight >= short_weight else "flat"
        valid_horizons = group["return_horizon_days"].dropna()
        if valid_horizons.empty:
            horizon = int(default_horizon_days)
        elif len(valid_horizons) == 1:
            horizon = int(valid_horizons.iloc[0])
        else:
            horizon = int(np.nanmedian(valid_horizons.to_numpy(dtype="float64", copy=False)))
        rows.append(
            {
                "symbol": symbol,
                "aggregate_direction": aggregate_direction,
                "expected_return": float(expected_return),
                "return_horizon_days": horizon,
                "p_win": float(np.clip(p_win_mean, 0.0, 1.0)),
                "p_win_mean": float(np.clip(p_win_mean, 0.0, 1.0)),
                "p_win_lower": float(np.clip(p_win_lower, 0.0, 1.0)),
                "p_loss": float(np.clip(p_loss, 0.0, 1.0)),
                "avg_win": float(avg_win),
                "avg_loss": float(avg_loss),
                "payoff_ratio": float(max(payoff_ratio, 1e-9)),
                "aggregate_confidence": float(np.clip(aggregate_confidence, 0.0, 1.0)),
                "signal_conflict_score": float(np.clip(conflict, 0.0, 1.0)),
                "strategy_vote_count": int(group["strategy_id"].nunique()),
                "effective_sample_size": float(n_eff),
                "prior_p": float(posterior["prior_p"]),
                "prior_strength": float(posterior["prior_strength"]),
                "prior_source": str(posterior["prior_source"]),
                "posterior_alpha": float(posterior["alpha"]),
                "posterior_beta": float(posterior["beta"]),
                "posterior_sample_count": float(posterior["sample_count"]),
            }
        )
    return pd.DataFrame(rows, columns=AGGREGATED_SIGNAL_COLUMNS)


def calculate_kelly_raw(p_win: float, payoff_ratio: float) -> float:
    """Return standard net-odds Kelly: f* = p - q / b.

    p is win probability, q is loss probability, and b is payoff_ratio
    (`avg_win / abs(avg_loss)`). This is deliberately not
    `(p - q) / b`.
    """
    p = float(np.clip(p_win, 0.0, 1.0))
    b = float(payoff_ratio)
    if not np.isfinite(b) or b <= 0.0:
        return 0.0
    q = 1.0 - p
    return float(p - q / b)


def calculate_target_weight(
    *,
    p_win: float,
    payoff_ratio: float,
    risk_discount: float,
    exposure_cap: float,
    kelly_scale: float = POSITION_KELLY_SCALE,
    single_stock_cap: float = POSITION_SINGLE_STOCK_CAP,
) -> dict:
    kelly_raw = calculate_kelly_raw(p_win, payoff_ratio)
    discount = float(np.clip(risk_discount, 0.0, 1.0))
    adjusted = kelly_raw * float(kelly_scale) * discount
    target_raw = max(float(adjusted), 0.0)
    cap = max(min(float(single_stock_cap), float(exposure_cap)), 0.0)
    target_weight = float(np.clip(target_raw, 0.0, cap))
    return {
        "kelly_raw": float(kelly_raw),
        "kelly_scale": float(kelly_scale),
        "risk_discount": discount,
        "kelly_adjusted": float(adjusted),
        "target_weight": target_weight,
        "kelly_score": target_weight,
    }


def choose_position_action(
    *,
    current_weight: float,
    target_weight: float,
    kelly_score: float,
    expected_return_20d: float,
    p_win: float,
    in_investable_pool: bool,
    is_tradeable: bool = True,
    negative_signal_days: int = 0,
    low_p_win_days: int = 0,
    partial_adjustment_rate: float = 0.25,
) -> tuple[str, str, float]:
    """Apply the P0 decision matrix and return action, reason, final target."""
    current = float(current_weight)
    target = float(target_weight)
    score = float(kelly_score)
    expected = float(expected_return_20d)
    if not is_tradeable:
        return "blocked", "not_tradeable", current
    if expected < POSITION_EXIT_EXPECTED_RETURN_20D and int(negative_signal_days) >= POSITION_EXIT_HYSTERESIS_DAYS:
        return "exit", "expected_return_20d_negative_hysteresis", 0.0
    if float(p_win) < POSITION_MIN_P_WIN and int(low_p_win_days) >= POSITION_EXIT_HYSTERESIS_DAYS:
        return "exit", "p_win_below_min_hysteresis", 0.0
    if score < POSITION_SEVERE_EXIT_KELLY_SCORE:
        return "exit", "kelly_score_below_severe_exit", 0.0
    if score < POSITION_HOLD_KELLY_SCORE:
        trimmed = current + (target - current) * float(partial_adjustment_rate)
        return "trim", "kelly_score_below_hold_threshold", max(trimmed, 0.0)
    if not in_investable_pool:
        return "exit", "out_of_investable_pool", 0.0
    if target > current + 1e-12:
        return ("buy" if current <= 1e-12 else "add"), "kelly_target_above_current", target
    return "hold", "kelly_target_not_above_current", current


def build_position_management_decisions(
    aggregated: pd.DataFrame,
    *,
    current_weights: Mapping[str, float] | None = None,
    investable_symbols: Iterable[str] | None = None,
    tradeable_symbols: Iterable[str] | None = None,
    exposure_cap: float = 1.0,
    risk_level: str = "normal",
    risk_discount: float = 1.0,
    negative_signal_days: Mapping[str, int] | None = None,
    low_p_win_days: Mapping[str, int] | None = None,
    partial_adjustment_rate: float = 0.25,
    out_of_universe_symbols: set[str] | None = None,
    universe_mode: str = "index_pool_strict",
) -> pd.DataFrame:
    """Build position management decisions with explicit out-of-universe handling.

    Parameters
    ----------
    out_of_universe_symbols : set[str], optional
        Symbols that are currently held but NOT in today's universe.
        These will get explicit exit decisions.
    universe_mode : str
        One of: "index_pool_strict", "quality_fallback", "blocked"
    """
    current_weights = current_weights or {}
    investable = set(investable_symbols) if investable_symbols is not None else set(aggregated["symbol"])
    tradeable = set(tradeable_symbols) if tradeable_symbols is not None else set(aggregated["symbol"])
    negative_signal_days = negative_signal_days or {}
    low_p_win_days = low_p_win_days or {}
    out_of_universe = out_of_universe_symbols or set()
    rows = []

    # Generate explicit exit decisions for out-of-universe holdings
    for symbol in out_of_universe:
        current_weight = float(current_weights.get(symbol, 0.0))
        if current_weight > 1e-12:
            decision = PositionManagementDecision(
                symbol=symbol,
                current_weight=current_weight,
                target_weight=0.0,
                kelly_raw=0.0,
                kelly_scale=0.0,
                risk_discount=0.0,
                kelly_adjusted=0.0,
                kelly_score=0.0,
                position_action="exit",
                action_reason="out_of_investable_pool",
                exposure_cap=float(exposure_cap),
                risk_level=str(risk_level),
                expected_return_20d=0.0,
                p_win=0.0,
                payoff_ratio=1.0,
                position_state="exit",
            )
            record = decision.__dict__.copy()
            record["out_of_universe"] = True
            record["universe_mode"] = universe_mode
            rows.append(record)

    # Generate decisions for in-universe stocks
    for row in aggregated.to_dict("records"):
        symbol = str(row["symbol"])
        current_weight = float(current_weights.get(symbol, 0.0))
        conflict = float(row.get("signal_conflict_score", 0.0))
        sizing_p_win = float(row.get("p_win_lower", row["p_win"]))
        sizing = calculate_target_weight(
            p_win=sizing_p_win,
            payoff_ratio=float(row["payoff_ratio"]),
            risk_discount=float(row.get("aggregate_confidence", 1.0)) * float(risk_discount),
            exposure_cap=exposure_cap,
        )
        if conflict > POSITION_CONFLICT_BLOCK_THRESHOLD and current_weight <= 1e-12:
            sizing["target_weight"] = 0.0
            sizing["kelly_score"] = 0.0
        elif conflict > POSITION_CONFLICT_EXIT_THRESHOLD and float(row["expected_return"]) < 0.0:
            sizing["target_weight"] = min(sizing["target_weight"], current_weight * 0.5)
            sizing["kelly_score"] = sizing["target_weight"]
        expected_20d = _to_20d_return(
            float(row["expected_return"]),
            int(row.get("return_horizon_days", POSITION_DEFAULT_RETURN_HORIZON_DAYS)),
        )
        action, reason, final_target = choose_position_action(
            current_weight=current_weight,
            target_weight=sizing["target_weight"],
            kelly_score=sizing["kelly_score"],
            expected_return_20d=expected_20d,
            p_win=sizing_p_win,
            in_investable_pool=symbol in investable,
            is_tradeable=symbol in tradeable,
            negative_signal_days=int(negative_signal_days.get(symbol, 0)),
            low_p_win_days=int(low_p_win_days.get(symbol, 0)),
            partial_adjustment_rate=partial_adjustment_rate,
        )
        decision = PositionManagementDecision(
            symbol=symbol,
            current_weight=current_weight,
            target_weight=float(final_target),
            kelly_raw=sizing["kelly_raw"],
            kelly_scale=sizing["kelly_scale"],
            risk_discount=sizing["risk_discount"],
            kelly_adjusted=sizing["kelly_adjusted"],
            kelly_score=sizing["kelly_score"],
            position_action=action,
            action_reason=reason,
            exposure_cap=float(exposure_cap),
            risk_level=str(risk_level),
            expected_return_20d=expected_20d,
            p_win=sizing_p_win,
            payoff_ratio=float(row["payoff_ratio"]),
            position_state=_position_state(
                action,
                in_investable_pool=symbol in investable,
                is_tradeable=symbol in tradeable,
            ),
        )
        record = decision.__dict__.copy()
        record["out_of_universe"] = False
        record["universe_mode"] = universe_mode
        for extra_col in [
            "prior_p",
            "prior_strength",
            "prior_source",
            "posterior_alpha",
            "posterior_beta",
            "posterior_sample_count",
        ]:
            if extra_col in row:
                record[extra_col] = row[extra_col]
        rows.append(record)
    return pd.DataFrame(rows)


def apply_risk_discount_smoothing(
    discount_history: pd.Series,
    *,
    raw_discount: float,
    single_day_drawdown: float = 0.0,
    emergency_triggered: bool = False,
    window: int = POSITION_RISK_DISCOUNT_SMOOTH_DAYS,
) -> float:
    raw = float(np.clip(raw_discount, 0.0, 1.0))
    history = pd.to_numeric(discount_history, errors="coerce").dropna().tail(max(int(window) - 1, 0))
    values = pd.concat([history, pd.Series([raw])], ignore_index=True)
    smoothed = float(values.tail(int(window)).mean()) if not values.empty else raw
    if emergency_triggered or float(single_day_drawdown) > POSITION_EMERGENCY_SINGLE_DAY_DRAWDOWN:
        return min(raw, smoothed)
    return smoothed


def evaluate_index_constituent_coverage(
    constituents: pd.DataFrame,
    *,
    index_code: str,
    start_date,
    end_date,
    min_coverage_ratio: float = POSITION_A500_MIN_COVERAGE_RATIO,
) -> dict:
    """Quantify whether point-in-time index membership is usable."""
    required = {"index_code", "symbol", "first_trade_date", "out_date"}
    missing = sorted(required - set(constituents.columns))
    if missing:
        raise ValueError(f"index constituents missing columns: {missing}")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    trading_days = pd.bdate_range(start, end)
    if trading_days.empty:
        return {"index_code": index_code, "coverage_ratio": 0.0, "status": "coverage_gap", "covered_days": 0, "total_days": 0}
    data = constituents[constituents["index_code"].astype(str) == str(index_code)].copy()
    data["first_trade_date"] = pd.to_datetime(data["first_trade_date"], errors="coerce")
    data["out_date"] = pd.to_datetime(data["out_date"], errors="coerce").fillna(pd.Timestamp.max.normalize())
    covered = []
    for day in trading_days:
        active = data[(data["first_trade_date"] <= day) & (data["out_date"] > day)]
        covered.append(not active.empty)
    covered_days = int(sum(covered))
    ratio = covered_days / len(trading_days)
    return {
        "index_code": str(index_code),
        "coverage_ratio": float(ratio),
        "status": "ok" if ratio >= float(min_coverage_ratio) else "coverage_gap",
        "covered_days": covered_days,
        "total_days": int(len(trading_days)),
        "degraded": bool(ratio < float(min_coverage_ratio)),
    }


def _normalize_strategy_stats(strategy_stats: pd.DataFrame | None) -> pd.DataFrame:
    columns = ["strategy_id", "reputation_weight", "wins", "losses", "avg_win", "avg_loss"]
    if strategy_stats is None or strategy_stats.empty:
        return pd.DataFrame(columns=columns)
    data = strategy_stats.copy()
    missing = sorted({"strategy_id"} - set(data.columns))
    if missing:
        raise ValueError(f"strategy_stats missing required columns: {missing}")
    for column, default in [
        ("reputation_weight", 1.0),
        ("wins", 0.0),
        ("losses", 0.0),
        ("avg_win", 0.0),
        ("avg_loss", 0.0),
    ]:
        if column not in data.columns:
            data[column] = default
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(default)
    return data[columns]


def _beta_binomial_p_win(group: pd.DataFrame) -> dict:
    weights = group["reputation_weight"].clip(lower=0.0)
    weighted_wins = float((group["wins"] * weights).sum())
    weighted_losses = float((group["losses"] * weights).sum())
    if weighted_wins + weighted_losses <= 0.0:
        alpha = POSITION_BAYES_PRIOR_STRENGTH * POSITION_BAYES_PRIOR_P
        beta = POSITION_BAYES_PRIOR_STRENGTH * (1.0 - POSITION_BAYES_PRIOR_P)
        return {
            "mean": 0.5,
            "lower": 0.5,
            "alpha": float(alpha),
            "beta": float(beta),
            "sample_count": 0.0,
            "prior_p": float(POSITION_BAYES_PRIOR_P),
            "prior_strength": float(POSITION_BAYES_PRIOR_STRENGTH),
            "prior_source": str(POSITION_BAYES_PRIOR_SOURCE),
        }
    alpha = weighted_wins + POSITION_BAYES_PRIOR_STRENGTH * POSITION_BAYES_PRIOR_P
    beta = weighted_losses + POSITION_BAYES_PRIOR_STRENGTH * (1.0 - POSITION_BAYES_PRIOR_P)
    mean = alpha / max(alpha + beta, 1e-12)
    lower_tail = 1.0 - POSITION_BAYES_LOWER_CONFIDENCE
    lower = float(beta_distribution.ppf(lower_tail, alpha, beta))
    return {
        "mean": float(mean),
        "lower": lower,
        "alpha": float(alpha),
        "beta": float(beta),
        "sample_count": float(weighted_wins + weighted_losses),
        "prior_p": float(POSITION_BAYES_PRIOR_P),
        "prior_strength": float(POSITION_BAYES_PRIOR_STRENGTH),
        "prior_source": str(POSITION_BAYES_PRIOR_SOURCE),
    }


def _aggregate_confidence(group: pd.DataFrame, conflict: float, n_eff: float) -> float:
    base = _weighted_average(group["confidence"].clip(0.0, 1.0), group["reputation_weight"], fallback=0.0)
    sample_discount = min(float(n_eff) / 2.0, 1.0)
    return float(base * (1.0 - conflict) * sample_discount)


def _effective_sample_size(group: pd.DataFrame, correlation_matrix: pd.DataFrame | None) -> float:
    weights = group.groupby("strategy_id")["reputation_weight"].mean().clip(lower=0.0)
    if weights.empty or float(weights.sum()) <= 0.0:
        return 0.0
    if correlation_matrix is None or correlation_matrix.empty:
        corr = pd.DataFrame(np.eye(len(weights)), index=weights.index, columns=weights.index)
    else:
        corr = correlation_matrix.reindex(index=weights.index, columns=weights.index).fillna(0.0)
        for strategy_id in weights.index:
            corr.loc[strategy_id, strategy_id] = 1.0
    w = weights.to_numpy(dtype=float)
    c = corr.to_numpy(dtype=float)
    denominator = float(w @ c @ w)
    if denominator <= 0.0:
        return 0.0
    return float((w.sum() ** 2) / denominator)


def _weighted_average(values, weights, *, fallback: float) -> float:
    values = pd.to_numeric(pd.Series(values), errors="coerce")
    weights = pd.to_numeric(pd.Series(weights), errors="coerce").fillna(0.0).clip(lower=0.0)
    mask = values.notna() & weights.notna()
    if not mask.any() or float(weights[mask].sum()) <= 0.0:
        return float(fallback)
    return float((values[mask] * weights[mask]).sum() / weights[mask].sum())


def _to_20d_return(expected_return: float, horizon_days: int) -> float:
    horizon = max(int(horizon_days), 1)
    return float(expected_return) * (20.0 / horizon)


def _position_state(
    action: str,
    *,
    in_investable_pool: bool,
    is_tradeable: bool,
) -> str:
    if not is_tradeable:
        return "FROZEN_UNTRADEABLE"
    if action == "exit":
        return "EXIT_PENDING"
    if action == "trim":
        return "REDUCE_LIGHT"
    if action == "buy":
        return "NEW"
    if not in_investable_pool:
        return "HOLD_OUT_OF_POOL"
    return "ACTIVE"
