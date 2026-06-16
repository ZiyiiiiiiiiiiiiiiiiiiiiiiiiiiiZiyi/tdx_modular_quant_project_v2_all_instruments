"""Independent strategy events, mature labels, and conservative statistics."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import beta as beta_distribution

from config import (
    POSITION_BAYES_LOWER_CONFIDENCE,
    POSITION_BAYES_PRIOR_P,
    POSITION_BAYES_PRIOR_SOURCE,
    POSITION_BAYES_PRIOR_STRENGTH,
    POSITION_PAYOFF_MAX,
    POSITION_PAYOFF_MIN,
    POSITION_PAYOFF_TRIM_RATIO,
    V6_EVENT_DENSITY_WARNING_PER_YEAR,
    V6_STRATEGY_COOLDOWN_DAYS,
)


@dataclass(frozen=True)
class BayesianWinRate:
    wins: float
    losses: float
    alpha: float
    beta: float
    mean: float
    lower_bound: float
    sample_count: float
    prior_p: float
    prior_strength: float
    prior_source: str


def beta_binomial_win_rate(
    wins: float,
    losses: float,
    *,
    prior_p: float = POSITION_BAYES_PRIOR_P,
    prior_strength: float = POSITION_BAYES_PRIOR_STRENGTH,
    confidence_level: float = POSITION_BAYES_LOWER_CONFIDENCE,
) -> BayesianWinRate:
    wins = max(float(wins), 0.0)
    losses = max(float(losses), 0.0)
    prior_p = float(np.clip(prior_p, 0.0, 1.0))
    prior_strength = max(float(prior_strength), 0.0)
    alpha = wins + prior_strength * prior_p
    beta = losses + prior_strength * (1.0 - prior_p)
    mean = alpha / max(alpha + beta, 1e-12)
    tail_probability = 1.0 - float(np.clip(confidence_level, 0.5, 0.999))
    lower = float(beta_distribution.ppf(tail_probability, alpha, beta))
    return BayesianWinRate(
        wins,
        losses,
        alpha,
        beta,
        mean,
        lower,
        wins + losses,
        prior_p,
        prior_strength,
        str(POSITION_BAYES_PRIOR_SOURCE),
    )


def kelly_prior_sensitivity_grid(
    *,
    wins: float,
    losses: float,
    payoff_ratio: float,
    prior_ps: list[float],
    prior_strengths: list[float],
    confidence_level: float = POSITION_BAYES_LOWER_CONFIDENCE,
) -> pd.DataFrame:
    rows = []
    for prior_p in prior_ps:
        for prior_strength in prior_strengths:
            posterior = beta_binomial_win_rate(
                wins=wins,
                losses=losses,
                prior_p=float(prior_p),
                prior_strength=float(prior_strength),
                confidence_level=confidence_level,
            )
            lower = float(np.clip(posterior.lower_bound, 0.0, 1.0))
            mean = float(np.clip(posterior.mean, 0.0, 1.0))
            b = float(max(payoff_ratio, 1e-9))
            rows.append(
                {
                    "prior_p": float(prior_p),
                    "prior_strength": float(prior_strength),
                    "prior_source": str(POSITION_BAYES_PRIOR_SOURCE),
                    "wins": float(wins),
                    "losses": float(losses),
                    "posterior_alpha": float(posterior.alpha),
                    "posterior_beta": float(posterior.beta),
                    "posterior_mean": mean,
                    "posterior_lower_bound": lower,
                    "payoff_ratio": b,
                    "kelly_mean": float(mean - (1.0 - mean) / b),
                    "kelly_lower_bound": float(lower - (1.0 - lower) / b),
                }
            )
    return pd.DataFrame(rows)


def robust_payoff_ratio(
    returns: pd.Series,
    *,
    trim_ratio: float = POSITION_PAYOFF_TRIM_RATIO,
    minimum: float = POSITION_PAYOFF_MIN,
    maximum: float = POSITION_PAYOFF_MAX,
) -> dict:
    values = pd.to_numeric(returns, errors="coerce").dropna()
    wins = values[values > 0.0]
    losses = -values[values < 0.0]
    avg_win = _trimmed_mean(wins, trim_ratio)
    avg_loss = _trimmed_mean(losses, trim_ratio)
    raw = avg_win / avg_loss if avg_win > 0.0 and avg_loss > 0.0 else 1.0
    return {
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),
        "payoff_ratio_raw": float(raw),
        "payoff_ratio": float(np.clip(raw, minimum, maximum)),
        "raw_mean": float(values.mean()) if not values.empty else 0.0,
        "median": float(values.median()) if not values.empty else 0.0,
        "tail_loss_95": float(losses.quantile(0.95)) if not losses.empty else 0.0,
    }


def build_independent_events(
    signals: pd.DataFrame,
    *,
    cooldown_days: dict[str, int] | None = None,
) -> pd.DataFrame:
    required = {"strategy_id", "symbol", "signal_timestamp", "direction"}
    missing = sorted(required - set(signals.columns))
    if missing:
        raise ValueError(f"signals missing required columns: {missing}")
    cooldown_days = cooldown_days or V6_STRATEGY_COOLDOWN_DAYS
    data = signals.copy()
    data["signal_timestamp"] = pd.to_datetime(data["signal_timestamp"], errors="coerce")
    data = data.dropna(subset=["strategy_id", "symbol", "signal_timestamp"])
    data = data[data["direction"].astype(str).str.lower() != "flat"]
    data = data.sort_values(["strategy_id", "symbol", "signal_timestamp"])
    records = []
    for (strategy_id, symbol), group in data.groupby(["strategy_id", "symbol"], sort=True):
        cooldown = int(cooldown_days.get(str(strategy_id), 0))
        prior_event_time = None
        sequence = 0
        for row in group.to_dict("records"):
            timestamp = pd.Timestamp(row["signal_timestamp"])
            independent = (
                prior_event_time is None
                or (timestamp.normalize() - prior_event_time.normalize()).days > cooldown
            )
            if independent:
                sequence += 1
                prior_event_time = timestamp
            record = dict(row)
            record["event_id"] = f"{strategy_id}:{symbol}:{sequence:06d}"
            record["is_independent_event"] = bool(independent)
            record["cooldown_days"] = cooldown
            records.append(record)
    return pd.DataFrame(records)


def mature_events(events: pd.DataFrame, decision_date) -> pd.DataFrame:
    if "reference_date" not in events.columns:
        raise ValueError("events missing reference_date")
    data = events.copy()
    data["reference_date"] = pd.to_datetime(data["reference_date"], errors="coerce")
    decision = pd.Timestamp(decision_date)
    return data[
        data["reference_date"].notna()
        & (data["reference_date"] < decision)
        & data.get("is_independent_event", True)
    ].copy()


def attach_event_labels(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    round_trip_cost_rate: float,
) -> pd.DataFrame:
    """Attach cost-after return, ranking, MAE, and MFE to independent events."""
    required_events = {
        "symbol",
        "tradeable_timestamp",
        "reference_date",
        "return_horizon_days",
    }
    missing_events = sorted(required_events - set(events.columns))
    if missing_events:
        raise ValueError(f"events missing label columns: {missing_events}")
    required_prices = {"symbol", "date", "open", "high", "low", "close"}
    missing_prices = sorted(required_prices - set(prices.columns))
    if missing_prices:
        raise ValueError(f"prices missing label columns: {missing_prices}")
    price_data = prices.copy()
    price_data["date"] = pd.to_datetime(price_data["date"], errors="coerce")
    by_symbol = {
        symbol: group.sort_values("date").set_index("date")
        for symbol, group in price_data.groupby("symbol")
    }
    records = []
    for row in events.to_dict("records"):
        record = dict(row)
        trade_date = pd.Timestamp(row["tradeable_timestamp"]).normalize()
        reference_date = pd.Timestamp(row["reference_date"]).normalize()
        history = by_symbol.get(row["symbol"])
        if history is None:
            continue
        window = history.loc[(history.index >= trade_date) & (history.index <= reference_date)]
        if window.empty:
            continue
        entry = float(window.iloc[0]["open"])
        exit_price = float(window.iloc[-1]["close"])
        gross_return = exit_price / entry - 1.0 if entry > 0.0 else np.nan
        net_return = gross_return - float(round_trip_cost_rate)
        record["entry_price"] = entry
        record["exit_price"] = exit_price
        record["gross_return"] = gross_return
        record["net_return"] = net_return
        record["classification_label"] = int(net_return > 0.0)
        record["regression_label"] = net_return
        record["adverse_move"] = float(window["low"].min() / entry - 1.0)
        record["favorable_move"] = float(window["high"].max() / entry - 1.0)
        records.append(record)
    result = pd.DataFrame(records)
    if result.empty:
        return result
    result["ranking_label"] = result.groupby(
        pd.to_datetime(result["tradeable_timestamp"]).dt.normalize()
    )["net_return"].rank(pct=True, method="average").ge(0.80).astype("Int64")
    return result


def build_event_density_report(events: pd.DataFrame) -> pd.DataFrame:
    required = {"strategy_id", "signal_timestamp"}
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError(f"events missing required columns: {missing}")
    data = events.copy()
    data["signal_timestamp"] = pd.to_datetime(data["signal_timestamp"], errors="coerce")
    data["year"] = data["signal_timestamp"].dt.year
    if "is_independent_event" not in data.columns:
        data["is_independent_event"] = True
    rows = []
    for (strategy_id, year), group in data.groupby(["strategy_id", "year"], dropna=False):
        independent = group[group["is_independent_event"].astype(bool)]
        count = int(len(independent))
        rows.append(
            {
                "strategy_id": strategy_id,
                "year": year,
                "raw_signal_rows": int(len(group)),
                "independent_events": count,
                "independent_trade_dates": int(independent["signal_timestamp"].dt.normalize().nunique()),
                "unique_symbols": int(independent["symbol"].nunique()) if "symbol" in independent else 0,
                "density_status": "ok" if count >= V6_EVENT_DENSITY_WARNING_PER_YEAR else "low_density",
            }
        )
    return pd.DataFrame(rows)


def _trimmed_mean(values: pd.Series, trim_ratio: float) -> float:
    values = pd.to_numeric(values, errors="coerce").dropna().sort_values()
    if values.empty:
        return 0.0
    trim = int(np.floor(len(values) * float(np.clip(trim_ratio, 0.0, 0.49))))
    if trim > 0 and len(values) > 2 * trim:
        values = values.iloc[trim:-trim]
    return float(values.mean())
