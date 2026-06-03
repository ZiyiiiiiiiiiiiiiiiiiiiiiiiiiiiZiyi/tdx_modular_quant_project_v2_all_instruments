# -*- coding: utf-8 -*-
"""Synthetic verification for the serial P2-P7 industrial governance contracts."""
from __future__ import annotations

from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from functions.decision_council.advanced_policies import BanditAction, validate_bandit_actions
from functions.decision_council.industrial_pipeline import (
    build_bounded_bandit_actions,
    build_conditional_safety_cost_matrix,
    build_initial_transition_protocol,
    build_model_congress_catalog,
    build_monitoring_rollback_policy,
    fit_serial_safety_model,
    run_industrial_governance_build,
)
from functions.decision_council.evaluation import probability_of_backtest_overfitting
from functions.decision_council.institutional_rewards import (
    alpha_rank_ic_reward,
    execution_agent_reward,
    safety_agent_reward,
)
from functions.decision_council.monitoring import evaluate_daily_rollback


def main():
    _verify_catalog_and_bandit()
    _verify_safety_training()
    _verify_serial_artifacts()
    _verify_rewards_pbo_and_rollback()
    print("Governance industrial P2-P7 verification passed.")


def _verify_catalog_and_bandit():
    congress = build_model_congress_catalog()
    assert {"lower_house", "senate", "safety_council", "president"}.issubset(set(congress["institution"]))
    actions = build_bounded_bandit_actions()
    assert len(actions) >= 4
    try:
        validate_bandit_actions(
            [BanditAction("too_wide", 40, 5, 0.05)],
            baseline=BanditAction("baseline", 20, 5, 0.05),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Broad bandit action should be rejected")
    assert build_initial_transition_protocol()["allow_new_buys"] is False
    assert build_monitoring_rollback_policy()["rollback_target"] == "rules_based_president"
    print("[PASS] congress catalog, sell-only transition, rollback, and bounded bandit")


def _verify_safety_training():
    daily = _synthetic_daily_safety()
    costs = build_conditional_safety_cost_matrix(daily.iloc[:120])
    assert costs.false_negative_cost >= costs.false_positive_cost
    trained = fit_serial_safety_model(daily)
    assert trained["model"]["registry_stage"] == "candidate"
    assert not trained["calibration"].empty
    assert float(trained["evaluation"].iloc[0]["brier_score"]) >= 0.0
    print("[PASS] conditional-cost safety training and validation-only calibration")


def _verify_serial_artifacts():
    features = _synthetic_feature_rows()
    with TemporaryDirectory() as directory:
        feature_path = f"{directory}/features.parquet"
        features.to_parquet(feature_path, index=False)
        saved = run_industrial_governance_build(
            feature_path=feature_path,
            output_dir=f"{directory}/industrial",
            batch_size=97,
        )
        required = {
            "model_congress_catalog",
            "safety_daily_dataset",
            "safety_model",
            "safety_calibration",
            "safety_evaluation",
            "bandit_action_contract",
            "transition_protocol",
            "monitoring_policy",
            "research_references",
            "model_registry",
            "phase_gate_report",
            "industrial_manifest",
        }
        assert required.issubset(saved)
        assert all(path.exists() for path in saved.values())
    print("[PASS] serial low-memory P2-P7 artifact build")


def _verify_rewards_pbo_and_rollback():
    dates = pd.to_datetime(["2024-01-02"] * 5)
    proposals = pd.DataFrame(
        {
            "date": dates,
            "model_name": "alpha",
            "symbol": [f"sh60000{i}" for i in range(5)],
            "predicted_return_5d": [1, 2, 3, 4, 5],
        }
    )
    realized = pd.DataFrame(
        {
            "date": dates,
            "symbol": proposals["symbol"],
            "future_ret_5": [0.01, 0.02, 0.03, 0.04, 0.05],
            "liquidity_eligible": True,
        }
    )
    assert alpha_rank_ic_reward(proposals, realized).iloc[0]["rank_ic_oos"] > 0.99
    assert safety_agent_reward(outcome=1, probability=0.1, false_positive_cost=1.0, false_negative_cost=4.0) < -4.0
    assert execution_agent_reward(pd.DataFrame([{"trade_notional": 1000.0, "market_impact_cost": 1.0}])) < 0
    pbo = probability_of_backtest_overfitting(
        pd.DataFrame({"alpha": [0.01] * 16, "beta": [-0.01] * 16}),
        blocks=8,
    )
    assert 0.0 <= pbo["pbo"] <= 1.0
    rollback = evaluate_daily_rollback(
        pd.DataFrame([{"date": "2024-01-02", "reconciliation_error": 1.0, "missing_price_position_count": 0}])
    )
    assert bool(rollback.iloc[0]["rollback_required"])
    print("[PASS] institution rewards, CSCV/PBO, and deterministic rollback recommendation")


def _synthetic_daily_safety():
    dates = pd.bdate_range("2020-01-01", periods=180)
    wave = np.sin(np.arange(len(dates)) / 9.0)
    close = 100.0 * np.cumprod(1.0 + 0.001 * wave)
    close[80:86] *= np.linspace(1.0, 0.90, 6)
    close[86:92] *= np.linspace(0.91, 1.02, 6)
    frame = pd.DataFrame({"date": dates, "market_proxy_close": close})
    frame["market_return_1d"] = frame["market_proxy_close"].pct_change(fill_method=None)
    frame["market_return_5d"] = frame["market_proxy_close"].pct_change(5, fill_method=None)
    frame["market_return_20d"] = frame["market_proxy_close"].pct_change(20, fill_method=None)
    frame["market_volatility_20d"] = frame["market_return_1d"].rolling(20, min_periods=5).std().fillna(0.01)
    frame["market_liquidity_stress_ratio"] = np.where((np.arange(len(frame)) % 17) == 0, 0.4, 0.1)
    frame["momentum_rebound_regime"] = ((frame["market_return_20d"].shift(5) <= -0.08) & (frame["market_return_5d"] >= 0.03)).astype(int)
    paths = pd.concat([frame["market_proxy_close"].shift(-offset) for offset in range(6)], axis=1)
    peak = paths.cummax(axis=1)
    frame["future_market_max_drawdown_5d"] = ((peak - paths) / peak).max(axis=1)
    frame["market_crash_label_5d"] = (frame["future_market_max_drawdown_5d"] >= 0.05).astype(int)
    return frame


def _synthetic_feature_rows():
    daily = _synthetic_daily_safety()
    rows = []
    for index, row in daily.iterrows():
        for symbol_index, (symbol, instrument_type) in enumerate(
            [("sh510300", "etf_fund"), ("sh600000", "stock"), ("sz000001", "stock")]
        ):
            rows.append(
                {
                    "date": row["date"],
                    "symbol": symbol,
                    "instrument_type": instrument_type,
                    "close_nominal": row["market_proxy_close"] * (1.0 + symbol_index * 0.01),
                    "amount": 1_000_000.0 if index % 17 else 100_000.0,
                    "amount_ma20": 1_000_000.0,
                    "volatility_20": row["market_volatility_20d"],
                    "is_trading": True,
                }
            )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    main()
