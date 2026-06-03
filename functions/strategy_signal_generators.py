"""Technical strategy-signal generators using the P0 StrategySignal contract."""
from __future__ import annotations

import numpy as np
import pandas as pd

from functions.decision_council.position_management import (
    STRATEGY_SIGNAL_REQUIRED_COLUMNS,
    validate_strategy_signal_frame,
)
from functions.strategy_params import STRATEGY_PARAMS, STRATEGY_PARAMS_VERSION, strategy_params_hash


def build_technical_strategy_features(df: pd.DataFrame, *, params=None) -> pd.DataFrame:
    """Attach MACD, RSI, turtle, mean-reversion, and grid helper fields."""
    params = params or STRATEGY_PARAMS
    data = df.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.sort_values(["symbol", "date"]).copy()
    price_cols = _price_columns(data)
    grouped = data.groupby("symbol", group_keys=False)

    macd = params["macd_trend"]
    fast = grouped[price_cols["close"]].transform(lambda s: s.ewm(span=int(macd["fast"]), adjust=False).mean())
    slow = grouped[price_cols["close"]].transform(lambda s: s.ewm(span=int(macd["slow"]), adjust=False).mean())
    data["macd_dif"] = fast - slow
    data["macd_dea"] = data.groupby("symbol")["macd_dif"].transform(
        lambda s: s.ewm(span=int(macd["signal"]), adjust=False).mean()
    )
    data["macd_hist"] = data["macd_dif"] - data["macd_dea"]
    data["macd_cross_up"] = (data["macd_hist"] > 0) & (grouped["macd_hist"].shift(1) <= 0)
    data["macd_cross_down"] = (data["macd_hist"] < 0) & (grouped["macd_hist"].shift(1) >= 0)

    for window in params["rsi_reversal"]["windows"]:
        data[f"rsi_{window}"] = grouped[price_cols["close"]].transform(lambda s, n=window: _rsi(s, int(n)))

    turtle = params["turtle_breakout"]
    entry = int(turtle["entry_window"])
    long_window = int(turtle["long_window"])
    data["turtle_high_20"] = grouped[price_cols["high"]].transform(lambda s: s.shift(1).rolling(entry, min_periods=entry).max())
    data["turtle_low_20"] = grouped[price_cols["low"]].transform(lambda s: s.shift(1).rolling(entry, min_periods=entry).min())
    data["turtle_high_55"] = grouped[price_cols["high"]].transform(lambda s: s.shift(1).rolling(long_window, min_periods=long_window).max())
    prev_close = grouped[price_cols["close"]].shift(1)
    high_low = data[price_cols["high"]] - data[price_cols["low"]]
    high_close = (data[price_cols["high"]] - prev_close).abs()
    low_close = (data[price_cols["low"]] - prev_close).abs()
    data["true_range"] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    data["atr_20"] = grouped["true_range"].transform(
        lambda s: s.rolling(int(turtle["atr_window"]), min_periods=int(turtle["atr_window"])).mean()
    )
    data["turtle_breakout_20"] = data[price_cols["close"]] / data["turtle_high_20"] - 1.0
    data["turtle_breakout_55"] = data[price_cols["close"]] / data["turtle_high_55"] - 1.0

    mean_rev = params["mean_reversion"]
    ma_window = int(mean_rev["ma_window"])
    data["mean_reversion_ma20"] = grouped[price_cols["close"]].transform(lambda s: s.rolling(ma_window, min_periods=ma_window).mean())
    rolling_std = grouped[price_cols["close"]].transform(lambda s: s.rolling(ma_window, min_periods=ma_window).std())
    data["mean_reversion_z20"] = (data[price_cols["close"]] - data["mean_reversion_ma20"]) / rolling_std.replace(0.0, np.nan)
    data["bollinger_position_20"] = data["mean_reversion_z20"] / float(mean_rev["bollinger_std"])

    grid = params["grid_trading"]
    data["grid_width_pct"] = (data["atr_20"] * float(grid["grid_atr_multiplier"])) / data[price_cols["close"]]
    data["strategy_params_version"] = STRATEGY_PARAMS_VERSION
    data["strategy_params_hash"] = strategy_params_hash(params)
    return data


def build_technical_strategy_signals(
    df: pd.DataFrame,
    *,
    signal_date=None,
    params=None,
) -> pd.DataFrame:
    """Build P0 StrategySignal records from the latest available feature date."""
    params = params or STRATEGY_PARAMS
    data = build_technical_strategy_features(df, params=params)
    if signal_date is not None:
        data = data[data["date"] <= pd.Timestamp(signal_date)]
    if data.empty:
        return pd.DataFrame(columns=STRATEGY_SIGNAL_REQUIRED_COLUMNS)
    latest_date = data["date"].max()
    latest = data[data["date"] == latest_date].copy()
    price_cols = _price_columns(latest)
    records = []
    for row in latest.to_dict("records"):
        records.extend(_signals_for_row(row, price_cols, params))
    signals = pd.DataFrame(records, columns=STRATEGY_SIGNAL_REQUIRED_COLUMNS)
    if signals.empty:
        return signals
    return validate_strategy_signal_frame(signals)


def _signals_for_row(row: dict, price_cols: dict, params: dict) -> list[dict]:
    symbol = str(row["symbol"])
    close = float(row[price_cols["close"]])
    signal_timestamp = pd.Timestamp(row["date"]) + pd.Timedelta(hours=15, minutes=30)
    tradeable_timestamp = pd.Timestamp(row["date"]) + pd.offsets.BDay(1) + pd.Timedelta(hours=9, minutes=30)
    records = []

    macd_params = params["macd_trend"]
    if pd.notna(row.get("macd_hist")):
        direction = "long" if row["macd_hist"] > 0 else "short"
        confidence = min(abs(float(row["macd_hist"])) / max(close * 0.01, 1e-12), 1.0)
        records.append(
            _record(
                strategy_id="macd_trend",
                symbol=symbol,
                direction=direction,
                predicted_return=float(row.get("macd_hist", 0.0)) / max(close, 1e-12),
                horizon=macd_params["horizon_days"],
                confidence=confidence,
                volatility=row.get("volatility_20", row.get("atr_20", 0.0)),
                stop_loss_pct=macd_params["stop_loss_pct"],
                take_profit_pct=macd_params["take_profit_pct"],
                max_holding_days=macd_params["max_holding_days"],
                signal_timestamp=signal_timestamp,
                tradeable_timestamp=tradeable_timestamp,
                source_columns="macd_dif,macd_dea,macd_hist",
            )
        )

    rsi_params = params["rsi_reversal"]
    rsi_14 = row.get("rsi_14")
    if pd.notna(rsi_14):
        direction = "long" if rsi_14 <= rsi_params["oversold"] else "short" if rsi_14 >= rsi_params["overbought"] else "flat"
        distance = min(abs(float(rsi_14) - 50.0) / 50.0, 1.0)
        records.append(
            _record(
                strategy_id="rsi_reversal",
                symbol=symbol,
                direction=direction,
                predicted_return=(50.0 - float(rsi_14)) / 1000.0,
                horizon=rsi_params["horizon_days"],
                confidence=distance,
                volatility=row.get("volatility_20", row.get("atr_20", 0.0)),
                stop_loss_pct=rsi_params["stop_loss_pct"],
                take_profit_pct=rsi_params["take_profit_pct"],
                max_holding_days=rsi_params["max_holding_days"],
                signal_timestamp=signal_timestamp,
                tradeable_timestamp=tradeable_timestamp,
                source_columns="rsi_6,rsi_14,rsi_24",
            )
        )

    turtle_params = params["turtle_breakout"]
    breakout = row.get("turtle_breakout_20")
    atr = row.get("atr_20")
    if pd.notna(breakout) and pd.notna(atr) and close > 0:
        direction = "long" if breakout > 0 else "flat"
        atr_pct = float(atr) / close if close > 0 else 0.0
        stop = -float(turtle_params["stop_loss_atr"]) * atr_pct
        take = float(turtle_params["take_profit_atr"]) * atr_pct
        records.append(
            _record(
                strategy_id="turtle_breakout",
                symbol=symbol,
                direction=direction,
                predicted_return=float(breakout),
                horizon=turtle_params["horizon_days"],
                confidence=min(max(float(breakout), 0.0) / max(atr_pct, 1e-12), 1.0),
                volatility=atr_pct,
                stop_loss_pct=stop,
                take_profit_pct=take,
                max_holding_days=turtle_params["max_holding_days"],
                signal_timestamp=signal_timestamp,
                tradeable_timestamp=tradeable_timestamp,
                source_columns="turtle_breakout_20,turtle_high_20,atr_20",
            )
        )

    mean_params = params["mean_reversion"]
    z20 = row.get("mean_reversion_z20")
    if pd.notna(z20):
        direction = "long" if z20 <= mean_params["z_entry"] else "flat"
        confidence = min(abs(float(z20)) / max(abs(float(mean_params["z_entry"])), 1e-12), 1.0)
        records.append(
            _record(
                strategy_id="mean_reversion",
                symbol=symbol,
                direction=direction,
                predicted_return=-float(z20) / 100.0,
                horizon=mean_params["horizon_days"],
                confidence=confidence,
                volatility=row.get("volatility_20", row.get("atr_20", 0.0)),
                stop_loss_pct=mean_params["stop_loss_pct"],
                take_profit_pct=mean_params["take_profit_pct"],
                max_holding_days=mean_params["max_holding_days"],
                signal_timestamp=signal_timestamp,
                tradeable_timestamp=tradeable_timestamp,
                source_columns="mean_reversion_z20,bollinger_position_20",
            )
        )

    grid_params = params["grid_trading"]
    grid_width = row.get("grid_width_pct")
    if pd.notna(grid_width) and float(grid_width) > 0:
        records.append(
            _record(
                strategy_id="grid_trading",
                symbol=symbol,
                direction="flat",
                predicted_return=float(grid_width),
                horizon=grid_params["horizon_days"],
                confidence=min(float(grid_width) / 0.05, 1.0),
                volatility=float(grid_width),
                stop_loss_pct=-float(grid_width),
                take_profit_pct=float(grid_width),
                max_holding_days=grid_params["max_holding_days"],
                signal_timestamp=signal_timestamp,
                tradeable_timestamp=tradeable_timestamp,
                source_columns="grid_width_pct,atr_20",
            )
        )
    return records


def _record(
    *,
    strategy_id,
    symbol,
    direction,
    predicted_return,
    horizon,
    confidence,
    volatility,
    stop_loss_pct,
    take_profit_pct,
    max_holding_days,
    signal_timestamp,
    tradeable_timestamp,
    source_columns,
):
    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "direction": direction,
        "predicted_return": float(predicted_return),
        "return_horizon_days": int(horizon),
        "confidence": float(np.clip(confidence, 0.0, 1.0)),
        "volatility_estimate": float(max(float(volatility), 0.0)),
        "stop_loss_pct": float(stop_loss_pct),
        "take_profit_pct": float(take_profit_pct),
        "max_holding_days": int(max_holding_days),
        "exit_signal_confidence": 0.0,
        "signal_timestamp": pd.Timestamp(signal_timestamp),
        "tradeable_timestamp": pd.Timestamp(tradeable_timestamp),
        "signal_source_precision": "post_market",
        "source_columns": source_columns,
    }


def _price_columns(data: pd.DataFrame) -> dict:
    return {
        "open": "open_adj_pti" if "open_adj_pti" in data.columns else "open",
        "high": "high_adj_pti" if "high_adj_pti" in data.columns else "high",
        "low": "low_adj_pti" if "low_adj_pti" in data.columns else "low",
        "close": "close_adj_pti" if "close_adj_pti" in data.columns else "close",
    }


def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0).rolling(window, min_periods=window).mean()
    loss = (-delta.clip(upper=0.0)).rolling(window, min_periods=window).mean()
    rs = gain / loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.mask((loss == 0.0) & (gain > 0.0), 100.0)
    rsi = rsi.mask((gain == 0.0) & (loss > 0.0), 0.0)
    return rsi
