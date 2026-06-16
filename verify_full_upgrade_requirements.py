# -*- coding: utf-8 -*-
"""End-to-end smoke verification for the multi-strategy upgrade requirements."""
from __future__ import annotations

from tempfile import TemporaryDirectory

import pandas as pd

from functions.event_and_hedge import ResearchOnlyHedgeProvider, build_auditable_event_signals
from functions.investable_universe import (
    TARGET_INDEX_POOLS,
    build_index_universe_quality_report,
    filter_investable_universe,
    normalize_index_constituents,
)
from functions.metrics import calc_backtest_metrics
from functions.performance_charts import save_performance_diagnostics
from functions.position_managed_selection import generate_position_managed_selection
from functions.strategy_registry import STRATEGY_REGISTRY
from functions.strategy_signal_generators import build_technical_strategy_features
from config import GOVERNANCE_ALPHA_MODEL_FEATURES


def main():
    features = _features()
    constituents = _constituents(features)
    _verify_universe(features, constituents)
    selection, ledger = _verify_position_managed_selection(features, constituents)
    _verify_events_and_hedge(constituents)
    _verify_expanded_technical_strategies(features)
    _verify_metrics_and_charts(selection)
    print("Full upgrade requirement verification passed.")


def _verify_universe(features, constituents):
    normalized = normalize_index_constituents(constituents)
    report = build_index_universe_quality_report(
        normalized,
        start_date=features["date"].min(),
        end_date=features["date"].max(),
    )
    assert set(report["pool_id"]) == set(TARGET_INDEX_POOLS)
    filtered = filter_investable_universe(features, normalized)
    assert not filtered.empty
    assert set(filtered["instrument_type"]) == {"stock"}
    assert filtered["in_target_index_pool"].all()
    assert "sz000002" not in set(filtered["symbol"])
    print("[PASS] index stock pool and unsuitable-stock filters")


def _verify_position_managed_selection(features, constituents):
    stats = pd.DataFrame(
        [
            {"strategy_id": name, "reputation_weight": 1.0, "wins": 7, "losses": 3, "avg_win": 0.04, "avg_loss": -0.02}
            for name in ["macd_trend", "rsi_reversal", "turtle_breakout", "mean_reversion", "grid_trading"]
        ]
    )
    selection, ledger = generate_position_managed_selection(
        features,
        constituents=normalize_index_constituents(constituents),
        strategy_stats=stats,
        top_n=3,
        freq="ME",
    )
    assert not selection.empty
    assert not ledger.empty
    for column in ["kelly_raw", "kelly_score", "target_weight", "p_win", "payoff_ratio"]:
        assert column in selection.columns
    assert selection["score"].equals(selection["kelly_score"])
    assert (selection["weight"] > 0).all()
    print("[PASS] strategy signals must pass through position management and Kelly scoring")
    return selection, ledger


def _verify_events_and_hedge(constituents):
    actions = pd.DataFrame(
        [
            {
                "symbol": "sh600000",
                "action_date": "2024-03-01",
                "action_type": "dividend",
                "source": "test_corporate_action",
            }
        ]
    )
    events = build_auditable_event_signals(corporate_actions=actions, index_constituents=normalize_index_constituents(constituents))
    assert not events.empty
    assert (events["tradeable_timestamp"] >= events["event_timestamp"]).all()
    hedge = ResearchOnlyHedgeProvider()
    assert hedge.get_available_notional("2024-01-01") == 0.0
    assert hedge.get_hedge_cost("2024-01-01").tracking_error_rate == 0.0
    print("[PASS] event-driven timestamps and alpha-hedge research stub")


def _verify_expanded_technical_strategies(features):
    expanded = build_technical_strategy_features(features)
    strategy_columns = {
        "eod_close_strength": "score_eod_close_strength",
        "limit_up_follow": "score_limit_up_follow",
        "macd_cross": "score_macd_cross",
        "ma_cross": "score_ma_cross",
        "price_volume_breakout": "score_price_volume_breakout",
        "consecutive_decline_rebound": "score_consecutive_decline_rebound",
        "holiday_effect": "score_holiday_effect",
        "kdj_oversold_cross": "score_kdj_oversold_cross",
        "low_volume_pullback": "score_low_volume_pullback",
    }
    assert {"ema_20", "kdj_k", "kdj_d", "kdj_j"}.issubset(expanded.columns)
    for strategy_name, score_col in strategy_columns.items():
        assert strategy_name in STRATEGY_REGISTRY
        assert score_col in expanded.columns
        assert GOVERNANCE_ALPHA_MODEL_FEATURES[strategy_name] == score_col
    print("[PASS] expanded technical indicators and Kelly/governance strategy registration")


def _verify_metrics_and_charts(selection):
    daily = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=45),
            "daily_return": [0.002, -0.001, 0.003, -0.002, 0.001] * 9,
            "initial_cash": 1_000_000.0,
        }
    )
    daily["net_value"] = (1.0 + daily["daily_return"]).cumprod() * daily["initial_cash"]
    metrics, drawdown = calc_backtest_metrics(daily)
    metric_names = set(metrics["metric"])
    assert {"sortino", "calmar", "max_drawdown_duration_days", "monthly_win_rate", "max_consecutive_loss_days"}.issubset(metric_names)
    daily["drawdown"] = drawdown.values
    with TemporaryDirectory() as tmp:
        outputs = save_performance_diagnostics(
            daily_result=daily,
            strategy_name="upgrade_smoke",
            output_dir=tmp,
            selection=selection,
        )
        assert "performance_dashboard" in outputs
        assert "monthly_return_heatmap" in outputs
        assert "monthly_return_heatmap_summary" in outputs
    print("[PASS] enhanced performance metrics, equity curve dashboard, and heatmaps")


def _features():
    dates = pd.bdate_range("2024-01-01", periods=150)
    rows = []
    symbols = ["sh600000", "sz000001", "sz000002"]
    for symbol_index, symbol in enumerate(symbols):
        for i, date in enumerate(dates):
            close = 10.0 + symbol_index + i * (0.05 + symbol_index * 0.01)
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "code": symbol[2:],
                    "market": symbol[:2],
                    "instrument_type": "stock" if symbol != "sz000002" else "etf_fund",
                    "open": close * 0.99,
                    "high": close * 1.02,
                    "low": close * 0.98,
                    "close": close,
                    "amount": 50_000_000.0,
                    "volume": 5_000_000.0,
                    "is_trading": True,
                    "rough_limit_up": False,
                    "rough_limit_down": False,
                    "raw_ret": 0.01,
                    "volatility_20": 0.02,
                    "formal_price_eligible": True,
                }
            )
    return pd.DataFrame(rows)


def _constituents(features):
    start = features["date"].min()
    rows = []
    for spec in TARGET_INDEX_POOLS.values():
        for symbol in ["sh600000", "sz000001", "sz000002"]:
            rows.append(
                {
                    "index_code": spec["index_code"],
                    "index_name": spec["index_name"],
                    "symbol": symbol,
                    "announcement_date": start - pd.offsets.BDay(5),
                    "effective_after_close_date": start - pd.offsets.BDay(2),
                    "first_trade_date": start,
                    "out_date": pd.NaT,
                    "source": "test",
                    "asof_date": start,
                }
            )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    main()
