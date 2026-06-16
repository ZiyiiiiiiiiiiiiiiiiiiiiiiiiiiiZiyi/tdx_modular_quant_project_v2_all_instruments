# -*- coding: utf-8 -*-
"""Focused verification for position-management P0 contracts."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.position_management import (
    apply_risk_discount_smoothing,
    aggregate_strategy_signals,
    build_position_management_decisions,
    calculate_kelly_raw,
    calculate_target_weight,
    choose_position_action,
    evaluate_index_constituent_coverage,
    validate_strategy_signal_frame,
)


def main():
    _verify_position_managed_required_columns()
    _verify_strategy_signal_contract()
    _verify_aggregation_and_conflict()
    _verify_kelly_field_semantics()
    _verify_decision_matrix_horizon_and_hysteresis()
    _verify_a500_coverage_rule()
    _verify_emergency_risk_discount_bypass()
    print("Position management P0 verification passed.")


def _verify_position_managed_required_columns():
    from functions.feature_engineering import required_feature_columns_for_strategy

    required = set(required_feature_columns_for_strategy("position_managed_kelly"))
    missing = {"open", "high", "low", "close", "volume"} - required
    assert not missing, f"position-managed low-memory contract misses OHLCV: {sorted(missing)}"
    print("[PASS] position-managed low-memory contract includes OHLCV")


def _verify_strategy_signal_contract():
    signals = _signals()
    validated = validate_strategy_signal_frame(signals)
    assert set(validated["direction"]) == {"long", "short", "flat"}
    assert validated["signal_timestamp"].dtype.kind == "M"
    missing = signals.drop(columns=["tradeable_timestamp"])
    try:
        validate_strategy_signal_frame(missing)
    except ValueError as exc:
        assert "tradeable_timestamp" in str(exc)
    else:
        raise AssertionError("missing StrategySignal field should fail")
    print("[PASS] StrategySignal required fields and timestamp contract")


def _verify_aggregation_and_conflict():
    stats = pd.DataFrame(
        [
            {"strategy_id": "macd", "reputation_weight": 1.0, "wins": 7, "losses": 3, "avg_win": 0.04, "avg_loss": -0.02},
            {"strategy_id": "rsi", "reputation_weight": 1.0, "wins": 3, "losses": 7, "avg_win": 0.03, "avg_loss": -0.02},
            {"strategy_id": "turtle", "reputation_weight": 1.0, "wins": 6, "losses": 4, "avg_win": 0.05, "avg_loss": -0.025},
        ]
    )
    corr = pd.DataFrame(
        [[1.0, 0.2, 0.8], [0.2, 1.0, 0.2], [0.8, 0.2, 1.0]],
        index=["macd", "rsi", "turtle"],
        columns=["macd", "rsi", "turtle"],
    )
    aggregated = aggregate_strategy_signals(_signals(), strategy_stats=stats, correlation_matrix=corr)
    row = aggregated.set_index("symbol").loc["sh600000"]
    assert row["signal_conflict_score"] > 0.0
    assert row["aggregate_confidence"] < 0.9
    assert row["effective_sample_size"] < 3.0
    assert row["p_win"] > 0.5

    cold = aggregate_strategy_signals(_signals().head(1), strategy_stats=None)
    cold_row = cold.iloc[0]
    assert cold_row["p_win"] == 0.5
    assert cold_row["payoff_ratio"] == 1.0
    assert calculate_kelly_raw(cold_row["p_win"], cold_row["payoff_ratio"]) == 0.0
    print("[PASS] signal aggregation estimates p_win, conflict, and cold-start prior")


def _verify_kelly_field_semantics():
    assert round(calculate_kelly_raw(0.60, 2.0), 6) == 0.4
    assert round((0.60 - 0.40) / 2.0, 6) == 0.1
    sizing = calculate_target_weight(
        p_win=0.60,
        payoff_ratio=2.0,
        risk_discount=0.5,
        exposure_cap=1.0,
        kelly_scale=0.50,
        single_stock_cap=0.20,
    )
    assert abs(sizing["kelly_raw"] - 0.4) < 1e-12
    assert sizing["kelly_scale"] == 0.50
    assert sizing["risk_discount"] == 0.5
    assert abs(sizing["kelly_adjusted"] - 0.10) < 1e-12
    assert abs(sizing["target_weight"] - 0.10) < 1e-12
    assert sizing["kelly_score"] == sizing["target_weight"]
    print("[PASS] Kelly field semantics are fixed and formula precedence is correct")


def _verify_decision_matrix_horizon_and_hysteresis():
    action, reason, target = choose_position_action(
        current_weight=0.08,
        target_weight=0.10,
        kelly_score=0.10,
        expected_return_20d=-0.006,
        p_win=0.55,
        in_investable_pool=True,
        negative_signal_days=2,
    )
    assert action == "add"
    assert target == 0.10

    action, reason, target = choose_position_action(
        current_weight=0.08,
        target_weight=0.10,
        kelly_score=0.10,
        expected_return_20d=-0.006,
        p_win=0.55,
        in_investable_pool=True,
        negative_signal_days=3,
    )
    assert action == "exit"
    assert reason == "expected_return_20d_negative_hysteresis"
    assert target == 0.0

    aggregated = pd.DataFrame(
        [
            {
                "symbol": "sh600000",
                "expected_return": -0.0025,
                "return_horizon_days": 10,
                "p_win": 0.60,
                "p_loss": 0.40,
                "payoff_ratio": 2.0,
                "aggregate_confidence": 1.0,
            }
        ]
    )
    decisions = build_position_management_decisions(
        aggregated,
        current_weights={"sh600000": 0.05},
        investable_symbols={"sh600000"},
        tradeable_symbols={"sh600000"},
        negative_signal_days={"sh600000": 3},
    )
    row = decisions.iloc[0]
    assert row["expected_return_20d"] == -0.005
    assert row["position_action"] != "exit"
    print("[PASS] decision matrix uses 20-day return thresholds and hysteresis")


def _verify_a500_coverage_rule():
    constituents = pd.DataFrame(
        [
            {
                "index_code": "000510",
                "symbol": "sh600000",
                "first_trade_date": "2024-01-01",
                "out_date": "2024-01-10",
            }
        ]
    )
    report = evaluate_index_constituent_coverage(
        constituents,
        index_code="000510",
        start_date="2024-01-01",
        end_date="2024-01-31",
        min_coverage_ratio=0.80,
    )
    assert report["status"] == "coverage_gap"
    assert report["degraded"] is True
    complete = pd.DataFrame(
        [
            {
                "index_code": "000510",
                "symbol": "sh600000",
                "first_trade_date": "2024-01-01",
                "out_date": pd.NaT,
            }
        ]
    )
    ok = evaluate_index_constituent_coverage(
        complete,
        index_code="000510",
        start_date="2024-01-01",
        end_date="2024-01-31",
    )
    assert ok["status"] == "ok"
    print("[PASS] A500 constituent coverage rule is quantified")


def _verify_emergency_risk_discount_bypass():
    history = pd.Series([0.9, 0.9, 0.9, 0.9])
    normal = apply_risk_discount_smoothing(history, raw_discount=0.2, single_day_drawdown=0.0)
    emergency = apply_risk_discount_smoothing(history, raw_discount=0.2, single_day_drawdown=0.08)
    assert normal > 0.2
    assert emergency == 0.2
    print("[PASS] emergency risk discount bypass avoids slow smoothing in crashes")


def _signals():
    data = pd.DataFrame(
        [
            {
                "strategy_id": "macd",
                "symbol": "sh600000",
                "direction": "long",
                "predicted_return": 0.03,
                "return_horizon_days": 20,
                "confidence": 0.80,
                "volatility_estimate": 0.02,
                "stop_loss_pct": -0.05,
                "take_profit_pct": 0.10,
                "max_holding_days": 20,
                "exit_signal_confidence": 0.20,
                "signal_timestamp": "2024-01-02 15:30:00",
                "tradeable_timestamp": "2024-01-03 09:30:00",
                "signal_source_precision": "post_market",
                "source_columns": "macd_dif,macd_dea",
            },
            {
                "strategy_id": "rsi",
                "symbol": "sh600000",
                "direction": "short",
                "predicted_return": -0.02,
                "return_horizon_days": 20,
                "confidence": 0.70,
                "volatility_estimate": 0.02,
                "stop_loss_pct": -0.04,
                "take_profit_pct": 0.08,
                "max_holding_days": 10,
                "exit_signal_confidence": 0.60,
                "signal_timestamp": "2024-01-02 15:30:00",
                "tradeable_timestamp": "2024-01-03 09:30:00",
                "signal_source_precision": "post_market",
                "source_columns": "rsi_14",
            },
            {
                "strategy_id": "turtle",
                "symbol": "sh600000",
                "direction": "flat",
                "predicted_return": 0.0,
                "return_horizon_days": 20,
                "confidence": 0.50,
                "volatility_estimate": 0.02,
                "stop_loss_pct": -0.05,
                "take_profit_pct": 0.10,
                "max_holding_days": 55,
                "exit_signal_confidence": 0.30,
                "signal_timestamp": "2024-01-02 15:30:00",
                "tradeable_timestamp": "2024-01-03 09:30:00",
                "signal_source_precision": "post_market",
                "source_columns": "turtle_breakout_20",
            },
        ]
    )
    data["strategy_version"] = "test_v1"
    data["group_id"] = data["strategy_id"].map(
        {"macd": "trend", "rsi": "reversal", "turtle": "trend"}
    )
    data["event_id"] = [
        f"{strategy_id}:{symbol}:{index}"
        for index, (strategy_id, symbol) in enumerate(
            zip(data["strategy_id"], data["symbol"]), start=1
        )
    ]
    data["reference_date"] = pd.to_datetime(data["tradeable_timestamp"]) + pd.offsets.BDay(20)
    data["data_version"] = "test_data_v1"
    data["parameter_version"] = "test_params_v1"
    return data


if __name__ == "__main__":
    main()
