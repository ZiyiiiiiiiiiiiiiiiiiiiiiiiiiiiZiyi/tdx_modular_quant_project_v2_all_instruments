"""Verify the complete V6 signal-to-position path."""
from __future__ import annotations

import pandas as pd

from functions.v6_decision_pipeline import run_v6_decision_pipeline


def main():
    signal_time = pd.Timestamp("2024-01-02 15:30")
    trade_time = pd.Timestamp("2024-01-03 09:30")
    rows = []
    for index, (strategy, group, direction, predicted) in enumerate(
        [
            ("macd_cross", "trend", "long", 0.03),
            ("rsi_reversal", "reversal", "long", 0.02),
            ("low_volume_pullback", "price_volume", "long", 0.02),
            ("limit_up_follow", "event", "short", -0.01),
        ],
        start=1,
    ):
        rows.append(
            {
                "strategy_id": strategy,
                "strategy_version": "test_v1",
                "group_id": group,
                "symbol": "sh600000",
                "event_id": f"{strategy}:sh600000:{index}",
                "direction": direction,
                "predicted_return": predicted,
                "return_horizon_days": 5,
                "confidence": 0.7,
                "volatility_estimate": 0.02,
                "stop_loss_pct": -0.04,
                "take_profit_pct": 0.08,
                "max_holding_days": 10,
                "exit_signal_confidence": 0.0,
                "signal_timestamp": signal_time,
                "tradeable_timestamp": trade_time,
                "reference_date": trade_time + pd.offsets.BDay(5),
                "signal_source_precision": "post_market",
                "source_columns": "test",
                "data_version": "test_data",
                "parameter_version": "test_params",
            }
        )
    stats = pd.DataFrame(
        [
            {
                "strategy_id": strategy,
                "reputation_weight": 1.0,
                "wins": 70,
                "losses": 30,
                "avg_win": 0.04,
                "avg_loss": -0.02,
            }
            for strategy in [
                "macd_cross",
                "rsi_reversal",
                "low_volume_pullback",
                "limit_up_follow",
            ]
        ]
    )
    decisions, government = run_v6_decision_pipeline(
        pd.DataFrame(rows),
        strategy_stats=stats,
        current_weights={},
        investable_symbols={"sh600000"},
        tradeable_symbols={"sh600000"},
        volatility_percentile=0.4,
        market_breadth=0.2,
        index_trend=0.1,
        portfolio_drawdown=-0.02,
    )
    assert len(decisions) == 1
    assert decisions.iloc[0]["score_authority"] == "bayesian_lower_bound_half_kelly"
    assert decisions.iloc[0]["government_authority"] == "portfolio_risk_only"
    assert decisions.iloc[0]["formal_target_weight"] == 0.0
    assert decisions.iloc[0]["research_target_weight"] >= 0.0
    assert 0.5 <= government["market_discount"] <= 1.0
    print("V6 decision pipeline verification passed.")


if __name__ == "__main__":
    main()
