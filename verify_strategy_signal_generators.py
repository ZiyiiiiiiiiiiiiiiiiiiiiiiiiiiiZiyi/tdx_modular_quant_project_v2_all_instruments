# -*- coding: utf-8 -*-
"""Verify first-batch modular technical StrategySignal generators."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.position_management import (
    STRATEGY_SIGNAL_REQUIRED_COLUMNS,
    aggregate_strategy_signals,
    build_position_management_decisions,
)
from functions.strategy_params import STRATEGY_PARAMS_VERSION, strategy_params_hash
from functions.strategy_signal_generators import (
    build_technical_strategy_features,
    build_technical_strategy_signals,
)


def main():
    df = _sample_daily()
    features = build_technical_strategy_features(df)
    for column in [
        "macd_dif",
        "macd_dea",
        "macd_hist",
        "rsi_14",
        "atr_20",
        "turtle_breakout_20",
        "mean_reversion_z20",
        "grid_width_pct",
    ]:
        assert column in features.columns
    assert features["strategy_params_version"].iloc[-1] == STRATEGY_PARAMS_VERSION
    assert features["strategy_params_hash"].iloc[-1] == strategy_params_hash()

    signals = build_technical_strategy_signals(df)
    assert set(STRATEGY_SIGNAL_REQUIRED_COLUMNS).issubset(signals.columns)
    assert set(["macd_trend", "rsi_reversal", "turtle_breakout", "mean_reversion", "grid_trading"]).issubset(
        set(signals["strategy_id"])
    )
    assert (signals["tradeable_timestamp"] > signals["signal_timestamp"]).all()
    assert set(signals["signal_source_precision"]) == {"post_market"}

    stats = pd.DataFrame(
        [
            {"strategy_id": name, "reputation_weight": 1.0, "wins": 6, "losses": 4, "avg_win": 0.04, "avg_loss": -0.02}
            for name in signals["strategy_id"].unique()
        ]
    )
    aggregated = aggregate_strategy_signals(signals, strategy_stats=stats)
    decisions = build_position_management_decisions(
        aggregated,
        current_weights={},
        investable_symbols=set(aggregated["symbol"]),
        tradeable_symbols=set(aggregated["symbol"]),
    )
    assert not aggregated.empty
    assert not decisions.empty
    assert "kelly_score" in decisions.columns
    print("Strategy signal generator verification passed.")


def _sample_daily():
    dates = pd.bdate_range("2024-01-01", periods=80)
    rows = []
    for i, date in enumerate(dates):
        close = 10.0 + i * 0.08 + (0.4 if i > 60 else 0.0)
        rows.append(
            {
                "date": date,
                "symbol": "sh600000",
                "open": close * 0.99,
                "high": close * 1.02,
                "low": close * 0.98,
                "close": close,
                "volume": 1_000_000 + i * 1000,
                "amount": close * (1_000_000 + i * 1000),
                "instrument_type": "stock",
                "is_trading": True,
                "volatility_20": 0.02,
            }
        )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    main()
