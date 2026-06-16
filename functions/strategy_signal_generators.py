"""Technical strategy-signal generators using the P0 StrategySignal contract."""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import DATA_VERSION, V6_STRATEGY_GROUPS
from functions.decision_council.position_management import (
    STRATEGY_SIGNAL_REQUIRED_COLUMNS,
    validate_strategy_signal_frame,
)
from functions.strategy_params import STRATEGY_PARAMS, STRATEGY_PARAMS_VERSION, strategy_params_hash


PRECOMPUTED_TECHNICAL_COLUMNS = {
    "macd_hist",
    "rsi_14",
    "turtle_breakout_20",
    "atr_20",
    "mean_reversion_z20",
    "grid_width_pct",
    "score_alpha_hedge",
    "score_event_driven",
    "ema_20",
    "kdj_k",
    "kdj_d",
    "kdj_j",
    "score_eod_close_strength",
    "score_limit_up_follow",
    "score_macd_cross",
    "score_ma_cross",
    "score_price_volume_breakout",
    "score_consecutive_decline_rebound",
    "score_holiday_effect",
    "score_kdj_oversold_cross",
    "score_low_volume_pullback",
}

PRECOMPUTED_COLUMNS_BY_SIGNAL = {
    "macd_trend": {"macd_hist"},
    "rsi_reversal": {"rsi_14"},
    "turtle_breakout": {"turtle_breakout_20", "atr_20"},
    "mean_reversion": {"mean_reversion_z20"},
    "grid_trading": {"grid_width_pct"},
    "alpha_hedge": {"score_alpha_hedge", "alpha_proxy_20"},
    "event_driven": {"score_event_driven"},
    "eod_close_strength": {"score_eod_close_strength"},
    "limit_up_follow": {"score_limit_up_follow"},
    "macd_cross": {"score_macd_cross"},
    "ma_cross": {"score_ma_cross"},
    "price_volume_breakout": {"score_price_volume_breakout"},
    "consecutive_decline_rebound": {"score_consecutive_decline_rebound"},
    "holiday_effect": {"score_holiday_effect"},
    "kdj_oversold_cross": {"score_kdj_oversold_cross"},
    "low_volume_pullback": {"score_low_volume_pullback"},
}


def has_precomputed_technical_strategy_features(df: pd.DataFrame, strategy_ids=None) -> bool:
    available = set(df.columns)
    if strategy_ids is None:
        required = PRECOMPUTED_TECHNICAL_COLUMNS
    else:
        required = set()
        for strategy_id in strategy_ids:
            required.update(PRECOMPUTED_COLUMNS_BY_SIGNAL.get(str(strategy_id), set()))
    return required.issubset(available)


def build_technical_strategy_features(df: pd.DataFrame, *, params=None) -> pd.DataFrame:
    """Attach MACD, RSI, turtle, mean-reversion, and grid helper fields."""
    params = params or STRATEGY_PARAMS
    input_columns = _technical_feature_input_columns(df)
    data = df.loc[:, input_columns].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.sort_values(["symbol", "date"]).copy()
    original_columns = set(df.columns)
    price_cols = _price_columns(data)
    grouped = data.groupby("symbol", group_keys=False)
    for horizon in (1, 5, 20):
        return_col = f"ret_{horizon}"
        if return_col not in data.columns:
            data[return_col] = grouped[price_cols["close"]].pct_change(horizon, fill_method=None)

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
    data["score_macd_trend"] = data["macd_hist"] / data[price_cols["close"]].replace(0.0, np.nan)
    data["score_macd_cross"] = data["score_macd_trend"].where(data["macd_cross_up"])
    data["ema_20"] = grouped[price_cols["close"]].transform(
        lambda s: s.ewm(span=20, adjust=False).mean()
    )

    for window in params["rsi_reversal"]["windows"]:
        data[f"rsi_{window}"] = grouped[price_cols["close"]].transform(lambda s, n=window: _rsi(s, int(n)))
    data["score_rsi_reversal"] = (50.0 - data.get("rsi_14", np.nan)) / 50.0

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
    data["score_turtle_breakout"] = data["turtle_breakout_20"].where(data["turtle_breakout_20"] > 0.0)

    mean_rev = params["mean_reversion"]
    ma_window = int(mean_rev["ma_window"])
    data["mean_reversion_ma20"] = grouped[price_cols["close"]].transform(lambda s: s.rolling(ma_window, min_periods=ma_window).mean())
    rolling_std = grouped[price_cols["close"]].transform(lambda s: s.rolling(ma_window, min_periods=ma_window).std())
    data["mean_reversion_z20"] = (data[price_cols["close"]] - data["mean_reversion_ma20"]) / rolling_std.replace(0.0, np.nan)
    data["bollinger_position_20"] = data["mean_reversion_z20"] / float(mean_rev["bollinger_std"])
    data["score_mean_reversion"] = -data["mean_reversion_z20"]

    ma_cross = params["ma_cross"]
    fast_window = int(ma_cross["fast"])
    slow_window = int(ma_cross["slow"])
    fast_col = f"ma_{fast_window}"
    slow_col = f"ma_{slow_window}"
    if fast_col not in data.columns:
        data[fast_col] = grouped[price_cols["close"]].transform(
            lambda s: s.rolling(fast_window, min_periods=fast_window).mean()
        )
    if slow_col not in data.columns:
        data[slow_col] = grouped[price_cols["close"]].transform(
            lambda s: s.rolling(slow_window, min_periods=slow_window).mean()
        )
    ma_spread = data[fast_col] / data[slow_col].replace(0.0, np.nan) - 1.0
    prior_ma_spread = data.groupby("symbol")[fast_col].shift(1) / data.groupby("symbol")[slow_col].shift(1).replace(0.0, np.nan) - 1.0
    data["ma_cross_up"] = (ma_spread > 0.0) & (prior_ma_spread <= 0.0)
    data["score_ma_cross"] = ma_spread.where(data["ma_cross_up"])

    kdj_params = params["kdj_oversold_cross"]
    kdj_window = int(kdj_params["window"])
    kdj_low = grouped[price_cols["low"]].transform(
        lambda s: s.rolling(kdj_window, min_periods=kdj_window).min()
    )
    kdj_high = grouped[price_cols["high"]].transform(
        lambda s: s.rolling(kdj_window, min_periods=kdj_window).max()
    )
    data["kdj_rsv"] = (
        (data[price_cols["close"]] - kdj_low)
        / (kdj_high - kdj_low).replace(0.0, np.nan)
        * 100.0
    )
    data["kdj_k"] = data.groupby("symbol")["kdj_rsv"].transform(
        lambda s: s.ewm(alpha=1.0 / 3.0, adjust=False).mean()
    )
    data["kdj_d"] = data.groupby("symbol")["kdj_k"].transform(
        lambda s: s.ewm(alpha=1.0 / 3.0, adjust=False).mean()
    )
    data["kdj_j"] = 3.0 * data["kdj_k"] - 2.0 * data["kdj_d"]
    prior_k = data.groupby("symbol")["kdj_k"].shift(1)
    prior_d = data.groupby("symbol")["kdj_d"].shift(1)
    data["kdj_cross_up"] = (data["kdj_k"] > data["kdj_d"]) & (prior_k <= prior_d)
    kdj_oversold = data[["kdj_k", "kdj_d"]].max(axis=1) <= float(kdj_params["oversold"])
    data["score_kdj_oversold_cross"] = (
        (float(kdj_params["oversold"]) - data["kdj_k"]).clip(lower=0.0)
        / max(float(kdj_params["oversold"]), 1.0)
    ).where(data["kdj_cross_up"] & kdj_oversold)

    price_range = (data[price_cols["high"]] - data[price_cols["low"]]).replace(0.0, np.nan)
    data["close_location"] = (data[price_cols["close"]] - data[price_cols["low"]]) / price_range
    data["intraday_return_proxy"] = data[price_cols["close"]] / data[price_cols["open"]].replace(0.0, np.nan) - 1.0
    if "volume_ma_20" not in data.columns:
        data["volume_ma_20"] = grouped["volume"].transform(
            lambda s: s.rolling(20, min_periods=5).mean()
        )
    data["volume_ratio_20"] = data["volume"] / data["volume_ma_20"].replace(0.0, np.nan)

    eod = params["eod_close_strength"]
    eod_active = (
        (data["close_location"] >= float(eod["min_close_location"]))
        & (data["intraday_return_proxy"] >= float(eod["min_intraday_return"]))
        & (data["volume_ratio_20"] >= float(eod["min_volume_ratio"]))
    )
    data["score_eod_close_strength"] = (
        data["close_location"] * data["intraday_return_proxy"].clip(lower=0.0) * data["volume_ratio_20"]
    ).where(eod_active)

    prior_limit_up = (
        data.groupby("symbol")["rough_limit_up"].shift(1).astype("boolean").fillna(False)
        if "rough_limit_up" in data.columns
        else pd.Series(False, index=data.index, dtype="boolean")
    )
    limit_follow = params["limit_up_follow"]
    limit_follow_active = prior_limit_up.astype(bool) & (
        data["close_location"] >= float(limit_follow["min_close_location"])
    )
    data["score_limit_up_follow"] = (
        data["close_location"] + data["intraday_return_proxy"].clip(lower=0.0)
    ).where(limit_follow_active)

    breakout = params["price_volume_breakout"]
    breakout_window = int(breakout["lookback"])
    prior_high = grouped[price_cols["high"]].transform(
        lambda s: s.shift(1).rolling(breakout_window, min_periods=breakout_window).max()
    )
    breakout_strength = data[price_cols["close"]] / prior_high.replace(0.0, np.nan) - 1.0
    breakout_active = (breakout_strength > 0.0) & (
        data["volume_ratio_20"] >= float(breakout["min_volume_ratio"])
    )
    data["score_price_volume_breakout"] = (
        breakout_strength * data["volume_ratio_20"]
    ).where(breakout_active)

    rebound = params["consecutive_decline_rebound"]
    decline_days = int(rebound["decline_days"])
    prior_decline_count = data.groupby("symbol")["ret_1"].transform(
        lambda s: (s < 0.0).shift(1).rolling(decline_days, min_periods=decline_days).sum()
    )
    prior_decline_return = data[price_cols["close"]].groupby(data["symbol"]).shift(1) / data[price_cols["close"]].groupby(data["symbol"]).shift(decline_days + 1) - 1.0
    rebound_active = (
        (prior_decline_count >= decline_days)
        & (prior_decline_return <= float(rebound["max_prior_return"]))
        & (data["ret_1"] > 0.0)
    )
    data["score_consecutive_decline_rebound"] = (
        -prior_decline_return + data["ret_1"].clip(lower=0.0)
    ).where(rebound_active)

    next_trade_date = pd.Series(
        pd.Index(data["date"].dropna().drop_duplicates().sort_values()).to_series().shift(-1).to_dict()
    )
    data["next_trade_date"] = data["date"].map(next_trade_date)
    data["calendar_gap_days"] = (data["next_trade_date"] - data["date"]).dt.days
    holiday = params["holiday_effect"]
    holiday_active = data["calendar_gap_days"] >= int(holiday["minimum_calendar_gap_days"])
    data["score_holiday_effect"] = (
        0.01 + data["ret_20"].fillna(0.0).clip(lower=-0.02, upper=0.05)
    ).where(holiday_active)

    pullback = params["low_volume_pullback"]
    pullback_active = (
        (data[price_cols["close"]] > data[slow_col])
        & (data["ret_5"] >= float(pullback["min_ret_5"]))
        & (data["ret_5"] < float(pullback["max_ret_5"]))
        & (data["volume_ratio_20"] <= float(pullback["max_volume_ratio"]))
    )
    data["score_low_volume_pullback"] = (
        -data["ret_5"] * (1.0 - data["volume_ratio_20"].clip(lower=0.0, upper=1.0))
    ).where(pullback_active)

    grid = params["grid_trading"]
    data["grid_width_pct"] = (data["atr_20"] * float(grid["grid_atr_multiplier"])) / data[price_cols["close"]]
    data["score_grid_trading"] = data["grid_width_pct"]
    if "ret_20" not in data.columns:
        data["ret_20"] = grouped[price_cols["close"]].pct_change(20, fill_method=None)
    if "volatility_20" not in data.columns:
        data["volatility_20"] = grouped["ret_20"].transform(lambda s: s.rolling(20, min_periods=20).std())
    data["alpha_proxy_20"] = data["ret_20"] - data.groupby("date")["ret_20"].transform("mean")
    vol_col = data["volatility_20"] if "volatility_20" in data.columns else pd.Series(np.nan, index=data.index)
    data["score_alpha_hedge"] = data["alpha_proxy_20"] / vol_col.replace(0.0, np.nan)
    event_flag = pd.Series(False, index=data.index)
    for col in ["market_cap_jump_flag", "float_cap_jump_flag"]:
        if col in data.columns:
            event_flag = event_flag | data[col].astype("boolean").fillna(False).astype(bool)
    if "jump_event_type" in data.columns:
        event_flag = event_flag | data["jump_event_type"].fillna("").astype(str).ne("")
    data["score_event_driven"] = event_flag.astype(float) + data.get("ret_20", 0.0).fillna(0.0)
    data["strategy_params_version"] = STRATEGY_PARAMS_VERSION
    data["strategy_params_hash"] = strategy_params_hash(params)
    if set(input_columns) == original_columns:
        return data
    result = df.copy(deep=False)
    new_columns = [col for col in data.columns if col not in original_columns]
    for column in new_columns:
        result[column] = data[column]
    if "strategy_params_version" not in result.columns:
        result["strategy_params_version"] = STRATEGY_PARAMS_VERSION
    if "strategy_params_hash" not in result.columns:
        result["strategy_params_hash"] = strategy_params_hash(params)
    return result


def build_technical_strategy_signals(
    df: pd.DataFrame,
    *,
    signal_date=None,
    strategy_ids=None,
    params=None,
) -> pd.DataFrame:
    """Build P0 StrategySignal records from the latest available feature date."""
    params = params or STRATEGY_PARAMS
    if has_precomputed_technical_strategy_features(df, strategy_ids=strategy_ids):
        data = df.copy()
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data = data.sort_values(["symbol", "date"]).copy()
    else:
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
    if strategy_ids is not None:
        allowed = {str(item) for item in strategy_ids}
        signals = signals[signals["strategy_id"].astype(str).isin(allowed)].copy()
        if signals.empty:
            return pd.DataFrame(columns=STRATEGY_SIGNAL_REQUIRED_COLUMNS)
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
        ret_20 = _finite_or_default(row.get("ret_20", 0.0), 0.0)
        range_bound = abs(ret_20) <= float(grid_params.get("max_abs_ret_20", 0.08))
        direction = "long" if range_bound else "flat"
        expected_grid_return = min(
            float(grid_width) / max(float(grid_params.get("min_expected_return_to_cost", 3.0)), 1.0),
            float(grid_params.get("max_position_adjustment", 0.02)),
        )
        records.append(
            _record(
                strategy_id="grid_trading",
                symbol=symbol,
                direction=direction,
                predicted_return=expected_grid_return,
                horizon=grid_params["horizon_days"],
                confidence=min(float(grid_width) / 0.05, 1.0) if range_bound else 0.0,
                volatility=float(grid_width),
                stop_loss_pct=-float(grid_width),
                take_profit_pct=float(grid_width),
                max_holding_days=grid_params["max_holding_days"],
                signal_timestamp=signal_timestamp,
                tradeable_timestamp=tradeable_timestamp,
                source_columns="grid_width_pct,atr_20",
            )
        )
    alpha_score = row.get("score_alpha_hedge")
    if pd.notna(alpha_score):
        alpha_conf = min(abs(float(alpha_score)) / 3.0, 1.0)
        records.append(
            _record(
                strategy_id="alpha_hedge",
                symbol=symbol,
                direction="long" if alpha_score > 0 else "flat",
                predicted_return=float(row.get("alpha_proxy_20", 0.0)),
                horizon=20,
                confidence=alpha_conf,
                volatility=row.get("volatility_20", row.get("atr_20", 0.0)),
                stop_loss_pct=-0.05,
                take_profit_pct=0.10,
                max_holding_days=20,
                signal_timestamp=signal_timestamp,
                tradeable_timestamp=tradeable_timestamp,
                source_columns="score_alpha_hedge,alpha_proxy_20,volatility_20",
            )
        )
    event_score = row.get("score_event_driven")
    if pd.notna(event_score):
        event_active = any(
            [
                _truthy_event_flag(row.get("market_cap_jump_flag", False)),
                _truthy_event_flag(row.get("float_cap_jump_flag", False)),
                _has_event_type(row.get("jump_event_type", "")),
            ]
        )
        records.append(
            _record(
                strategy_id="event_driven",
                symbol=symbol,
                direction="long" if event_active and float(event_score) > 0 else "flat",
                predicted_return=float(event_score) / 20.0 if event_active else 0.0,
                horizon=20,
                confidence=1.0 if event_active else 0.25,
                volatility=row.get("volatility_20", row.get("atr_20", 0.0)),
                stop_loss_pct=-0.05,
                take_profit_pct=0.10,
                max_holding_days=20,
                signal_timestamp=signal_timestamp,
                tradeable_timestamp=tradeable_timestamp,
                source_columns="score_event_driven,jump_event_type,market_cap_jump_flag,float_cap_jump_flag",
            )
        )
    auxiliary_specs = {
        "eod_close_strength": ("score_eod_close_strength", "close_location,intraday_return_proxy,volume_ratio_20"),
        "limit_up_follow": ("score_limit_up_follow", "rough_limit_up,close_location,intraday_return_proxy"),
        "macd_cross": ("score_macd_cross", "macd_cross_up,macd_dif,macd_dea,macd_hist"),
        "ma_cross": ("score_ma_cross", "ma_cross_up,ma_5,ma_20"),
        "price_volume_breakout": ("score_price_volume_breakout", "close,prior_high_20,volume_ratio_20"),
        "consecutive_decline_rebound": ("score_consecutive_decline_rebound", "ret_1,prior_decline_return"),
        "holiday_effect": ("score_holiday_effect", "calendar_gap_days,next_trade_date"),
        "kdj_oversold_cross": ("score_kdj_oversold_cross", "kdj_k,kdj_d,kdj_j,kdj_cross_up"),
        "low_volume_pullback": ("score_low_volume_pullback", "ret_5,ma_20,volume_ratio_20"),
    }
    event_confidence_floor = {
        "limit_up_follow": 0.50,
        "macd_cross": 0.50,
        "ma_cross": 0.40,
        "price_volume_breakout": 0.50,
        "holiday_effect": 0.35,
        "kdj_oversold_cross": 0.50,
    }
    for strategy_id, (score_col, source_columns) in auxiliary_specs.items():
        score = row.get(score_col)
        if pd.isna(score):
            continue
        strategy_params = params[strategy_id]
        positive_score = max(float(score), 0.0)
        confidence = max(
            min(positive_score / 0.05, 1.0),
            float(event_confidence_floor.get(strategy_id, 0.0)),
        )
        expected_return = max(positive_score, 0.01 * confidence)
        records.append(
            _record(
                strategy_id=strategy_id,
                symbol=symbol,
                direction="long" if positive_score > 0.0 else "flat",
                predicted_return=min(expected_return, float(strategy_params["take_profit_pct"])),
                horizon=strategy_params["horizon_days"],
                confidence=confidence,
                volatility=row.get("volatility_20", row.get("atr_20", 0.0)),
                stop_loss_pct=strategy_params["stop_loss_pct"],
                take_profit_pct=strategy_params["take_profit_pct"],
                max_holding_days=strategy_params["max_holding_days"],
                signal_timestamp=signal_timestamp,
                tradeable_timestamp=tradeable_timestamp,
                source_columns=source_columns,
            )
        )
    return records


def _technical_feature_input_columns(df: pd.DataFrame) -> list[str]:
    base_columns = {
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "open_adj_pti",
        "high_adj_pti",
        "low_adj_pti",
        "close_adj_pti",
        "volume",
        "rough_limit_up",
        "market_cap_jump_flag",
        "float_cap_jump_flag",
        "jump_event_type",
    }
    available = set(df.columns)
    return [column for column in df.columns if column in base_columns and column in available]


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
    predicted_return = _finite_or_default(predicted_return, 0.0)
    confidence = _finite_or_default(confidence, 0.0)
    volatility = _finite_or_default(volatility, 0.0)
    stop_loss_pct = _finite_or_default(stop_loss_pct, 0.0)
    take_profit_pct = _finite_or_default(take_profit_pct, 0.0)
    reference_date = pd.Timestamp(tradeable_timestamp) + pd.offsets.BDay(max(int(horizon), 1))
    event_stamp = pd.Timestamp(signal_timestamp).strftime("%Y%m%d%H%M%S")
    event_id = f"{strategy_id}:{symbol}:{event_stamp}"
    return {
        "strategy_id": strategy_id,
        "strategy_version": STRATEGY_PARAMS_VERSION,
        "group_id": V6_STRATEGY_GROUPS.get(strategy_id, "observation"),
        "symbol": symbol,
        "event_id": event_id,
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
        "reference_date": reference_date,
        "signal_source_precision": "post_market",
        "source_columns": source_columns,
        "data_version": DATA_VERSION,
        "parameter_version": STRATEGY_PARAMS_VERSION,
    }


def _finite_or_default(value, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not np.isfinite(numeric):
        return float(default)
    return numeric


def _truthy_event_flag(value) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _has_event_type(value) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip() != ""


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
