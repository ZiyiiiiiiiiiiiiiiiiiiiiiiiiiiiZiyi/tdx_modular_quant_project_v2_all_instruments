"""Versioned default parameters for strategy-signal generation."""
from __future__ import annotations

import hashlib
import json


STRATEGY_PARAMS_VERSION = "strategy_params_v2_p0"

STRATEGY_PARAMS = {
    "macd_trend": {
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "horizon_days": 20,
        "stop_loss_pct": -0.05,
        "take_profit_pct": 0.10,
        "max_holding_days": 20,
    },
    "rsi_reversal": {
        "windows": (6, 14, 24),
        "oversold": 30,
        "overbought": 70,
        "horizon_days": 10,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.08,
        "max_holding_days": 10,
    },
    "turtle_breakout": {
        "entry_window": 20,
        "long_window": 55,
        "atr_window": 20,
        "add_unit_atr": 0.5,
        "max_units": 4,
        "horizon_days": 20,
        "stop_loss_atr": 2.0,
        "take_profit_atr": 4.0,
        "max_holding_days": 55,
    },
    "mean_reversion": {
        "ma_window": 20,
        "long_ma_window": 60,
        "bollinger_std": 2.0,
        "z_entry": -1.5,
        "z_exit": 0.0,
        "horizon_days": 10,
        "stop_loss_pct": -0.04,
        "take_profit_pct": 0.06,
        "max_holding_days": 15,
    },
    "grid_trading": {
        "atr_window": 20,
        "grid_atr_multiplier": 1.0,
        "horizon_days": 5,
        "min_expected_return_to_cost": 3.0,
        "max_position_adjustment": 0.02,
        "max_holding_days": 5,
    },
}


def strategy_params_hash(params=None) -> str:
    payload = {
        "version": STRATEGY_PARAMS_VERSION,
        "params": params or STRATEGY_PARAMS,
    }
    encoded = json.dumps(payload, sort_keys=True, default=list).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
