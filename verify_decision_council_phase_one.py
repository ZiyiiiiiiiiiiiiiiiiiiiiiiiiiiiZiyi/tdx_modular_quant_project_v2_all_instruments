# -*- coding: utf-8 -*-
"""Focused verification for the phase-one rules-based decision council."""
from __future__ import annotations

from tempfile import TemporaryDirectory

import pandas as pd

from functions.decision_council.accounting import build_exposure_snapshot, calculate_five_day_reward
from functions.decision_council.advanced_policies import (
    BanditAction,
    BanditDelegatingPresidentPolicy,
    ContextualBanditPresidentPolicy,
    ModelBasedSafetyAgent,
    fit_isotonic_calibration_table,
)
from functions.decision_council.alpha import alpha_collapse_symbols, combine_alpha_proposals
from functions.decision_council.allocation import allocate_constrained_inverse_vol, classify_prototype_sector
from functions.decision_council.contracts import DecisionContext, SafetyDecision
from functions.decision_council.engine import PhaseOneDecisionCouncilEngine
from functions.decision_council.evaluation import evaluate_phase_two_admission
from functions.decision_council.labels import apply_governance_labels
from functions.decision_council.leakage import (
    audit_timestamp_watermarks,
    audit_training_window_boundaries,
    validate_governance_split,
)
from functions.decision_council.pending_orders import PendingOrderBook
from functions.decision_council.policy import RulesBasedPresidentPolicy
from functions.decision_council.preflight import DataDependencyError, validate_safety_proxy
from functions.decision_council.reputation import ReputationLedger
from functions.decision_council.runner import GovernanceBacktestRunner
from functions.decision_council.safety import RuleBasedSafetyAgent
from functions.decision_council.shadow import ShadowPortfolioLedger


def verify_decision_council_phase_one():
    failures = []
    print("=== Verify decision council phase one ===")
    _verify_preflight_and_safety(failures)
    _verify_pending_orders_and_accounting(failures)
    _verify_allocation_and_policy(failures)
    _verify_reputation_shadow_and_leakage(failures)
    _verify_runner_and_advanced_policies(failures)
    print()
    if failures:
        print("Decision council verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)
    print("Decision council phase-one verification passed.")


def _verify_preflight_and_safety(failures):
    dates = pd.bdate_range("2024-01-01", periods=25)
    rows = []
    for index, date in enumerate(dates):
        rows.extend(
            [
                {"date": date, "symbol": "sh510300", "instrument_type": "etf_fund", "close": 100 - index * 0.3, "amount": 100.0, "is_trading": True},
                {"date": date, "symbol": "sh600000", "instrument_type": "stock", "close": 10.0, "amount": 20.0 if index == 24 else 100.0, "is_trading": True},
                {"date": date, "symbol": "sz000001", "instrument_type": "stock", "close": 12.0, "amount": 20.0 if index == 24 else 100.0, "is_trading": True},
            ]
        )
    features = pd.DataFrame(rows)
    proxy = validate_safety_proxy(features, mode="strict")
    _expect(proxy["proxy_symbol"] == "sh510300", "strict safety proxy should resolve HS300 ETF", failures)
    degraded = validate_safety_proxy(features[features["symbol"] != "sh510300"], mode="degraded_backtest")
    _expect(degraded["degraded"], "degraded safety mode should disclose missing proxy", failures)
    try:
        validate_safety_proxy(features[features["symbol"] != "sh510300"], mode="strict")
    except DataDependencyError:
        pass
    else:
        failures.append("strict safety mode should reject missing proxy")

    signals = RuleBasedSafetyAgent("sh510300").build_daily_signals(features)
    latest = signals.iloc[-1]
    _expect(latest["risk_level"] in {"warning", "high", "crisis"}, "safety signal should react to stress", failures)
    _expect(float(latest["exposure_cap"]) < 1.0, "safety exposure cap should fall under stress", failures)
    engine = PhaseOneDecisionCouncilEngine(features, safety_proxy_mode="strict")
    _expect(engine.manifest["benchmark_proxy_symbol"] == "sh510300", "engine should freeze selected safety proxy", failures)
    engine_candidates = pd.DataFrame(
        [
            {"symbol": "sh600000", "instrument_type": "stock", "volatility_20": 0.02, "alpha_score": 0.9, "alpha_percentile": 1.0},
            {"symbol": "sz000001", "instrument_type": "stock", "volatility_20": 0.03, "alpha_score": 0.8, "alpha_percentile": 0.5},
        ]
    )
    ideal, _, _ = engine.decide_day(
        decision_id="engine_smoke",
        decision_date=dates[-1],
        candidates=engine_candidates,
        current_weights={},
        holding_days={},
        top_n=2,
    )
    _expect(not ideal.empty or float(latest["exposure_cap"]) == 0.0, "engine should produce a daily plan when exposure is allowed", failures)
    print("[PASS] preflight strict/degraded modes and safety thresholds")


def _verify_pending_orders_and_accounting(failures):
    book = PendingOrderBook()
    payload = {
        "decision_id": "d1",
        "symbol": "sh600000",
        "side": "sell",
        "reason": "safety_deleveraging",
        "priority": 0,
        "created_date": "2024-01-02",
        "target_shares": 100,
    }
    first = book.upsert_sell_intent(payload)
    second = book.upsert_sell_intent({**payload, "decision_id": "d2", "target_shares": 200})
    _expect(first == second and len(book.orders) == 1, "locked sell intent should be deduplicated", failures)
    for offset in range(6):
        book.settle_day(pd.Timestamp("2024-01-03") + pd.offsets.BDay(offset), blocked_symbols=["sh600000"])
    _expect(book.orders.iloc[0]["status"] == "pending_locked", "sell intent should become pending_locked", failures)
    book.settle_day("2024-01-12", blocked_symbols=[])
    _expect(book.orders.iloc[0]["status"] == "pending", "unlocked sell intent should return to pending", failures)
    buy_book = PendingOrderBook()
    buy_book.add_order({**payload, "side": "buy", "reason": "normal_buy", "priority": 5})
    buy_book.settle_day("2024-01-03", blocked_symbols=["sh600000"])
    _expect(buy_book.orders.iloc[0]["status"] == "expired", "blocked ordinary buy should expire after one attempt", failures)

    positions = pd.DataFrame(
        [
            {"symbol": "sh600000", "shares": 100, "price": 10.0, "lock_days": 6},
            {"symbol": "sz000001", "shares": 100, "price": 10.0, "lock_days": 0},
        ]
    )
    snapshot = build_exposure_snapshot(positions, cash=1000.0, target_exposure=0.7)
    _expect(snapshot["nominal_nav"] == 3000.0, "nominal NAV should retain legal position value", failures)
    _expect(snapshot["liquidatable_nav"] == 2000.0, "liquidatable NAV should haircut locked position", failures)
    reward = calculate_five_day_reward(pd.Series([100.0, 105.0, 103.0, 101.0, 99.0, 102.0]), executed_turnover_5d=0.1)
    _expect("reward" in reward and reward["reward"] < reward["liquidatable_nav_return_5d"], "reward should penalize turnover", failures)
    print("[PASS] pending_locked lifecycle, double NAV, and reward accounting")


def _verify_allocation_and_policy(failures):
    candidates = pd.DataFrame(
        [
            {"symbol": "sh600000", "instrument_type": "stock", "volatility_20": 0.01, "alpha_score": 0.9, "alpha_percentile": 1.0},
            {"symbol": "sh600001", "instrument_type": "stock", "volatility_20": 0.02, "alpha_score": 0.8, "alpha_percentile": 0.8},
            {"symbol": "sz300001", "instrument_type": "stock", "volatility_20": 0.03, "alpha_score": 0.7, "alpha_percentile": 0.6},
            {"symbol": "sh688001", "instrument_type": "stock", "volatility_20": 0.04, "alpha_score": 0.6, "alpha_percentile": 0.4},
            {"symbol": "sz159919", "instrument_type": "etf_fund", "volatility_20": 0.05, "alpha_score": 0.5, "alpha_percentile": 0.2},
        ]
    )
    allocated, diagnostics = allocate_constrained_inverse_vol(candidates, exposure_cap=1.0)
    _expect(float(allocated["target_weight"].max()) <= 0.2000001, "position cap should hold", failures)
    _expect(float(allocated.groupby("prototype_sector")["target_weight"].sum().max()) <= 0.4000001, "prototype sector cap should hold", failures)
    _expect(diagnostics["volatility_scale_factor"] <= 1.0, "volatility scale factor should never increase weights", failures)
    _expect(classify_prototype_sector("sh688001") == "star_market", "prototype sector classification mismatch", failures)

    safety = SafetyDecision(pd.Timestamp("2024-01-31"), "high", 0.3, 0.03, 0.2, "sh510300", "strict")
    context = DecisionContext(
        decision_id="decision_001",
        decision_date=pd.Timestamp("2024-01-31"),
        candidates=candidates,
        current_weights={"sh600000": 0.4, "sz000001": 0.3},
        holding_days={"sh600000": 10, "sz000001": 10},
        pending_locked_symbols=frozenset({"sz000001"}),
        safety=safety,
        top_n=3,
    )
    ideal, orders, policy_diagnostics = RulesBasedPresidentPolicy().decide(context)
    _expect("sz000001" in set(ideal["symbol"]), "locked legal position should remain visible in plan", failures)
    _expect("sz000001" not in set(orders.get("symbol", [])), "locked position should be excluded from new sell orders", failures)
    _expect((orders["reason"] == "safety_deleveraging").any(), "safety cap reduction should create forced sell", failures)
    _expect(policy_diagnostics["unresolved_safety_exposure"] >= 0.0, "policy should disclose unresolved safety exposure", failures)
    alpha_proposals = pd.DataFrame(
        [
            {"symbol": "sh600000", "model_name": "elasticnet", "predicted_return_5d": -0.05, "prediction_std": 0.001, "reputation_weight": 1.0},
            {"symbol": "sh600000", "model_name": "xgboost", "predicted_return_5d": -0.04, "prediction_std": 0.001, "reputation_weight": 1.0},
            {"symbol": "sz000001", "model_name": "elasticnet", "predicted_return_5d": 0.05, "prediction_std": 0.001, "reputation_weight": 1.0},
            {"symbol": "sz000001", "model_name": "xgboost", "predicted_return_5d": 0.04, "prediction_std": 0.001, "reputation_weight": 1.0},
        ]
    )
    combined = combine_alpha_proposals(alpha_proposals)
    combined.loc[combined["symbol"] == "sh600000", "alpha_percentile"] = 0.1
    collapse = alpha_collapse_symbols(alpha_proposals, combined, {"sh600000": 2})
    _expect("sh600000" in collapse, "high-confidence negative alpha consensus should trigger collapse exit", failures)
    print("[PASS] constrained allocation, volatility scaling, and safety-order policy")


def _verify_reputation_shadow_and_leakage(failures):
    ledger = ReputationLedger(["alpha", "beta", "gamma"])
    for day in range(256):
        snapshot = ledger.record_rewards(
            {"alpha": 0.10, "beta": 0.0, "gamma": -0.10},
            as_of=pd.Timestamp("2024-01-01") + pd.offsets.BDay(day),
            trading_day_index=day,
        )
    weights = ledger.weights()
    _expect(weights["alpha"] > weights["beta"] > weights["gamma"], "reputation mapping should differentiate models", failures)
    _expect(max(weights.values()) <= 4.0 and min(weights.values()) >= 0.25, "reputation bounds should hold", failures)

    shadow = ShadowPortfolioLedger("alpha")
    for day, nav in enumerate([100, 101, 102, 101, 103, 104]):
        shadow.append(date=pd.Timestamp("2024-01-01") + pd.offsets.BDay(day), nominal_nav=nav, liquidatable_nav=nav, executed_turnover=0.01)
    _expect(shadow.mature_reward()["model_name"] == "alpha", "shadow reward should mature with shared contract", failures)

    audit = audit_timestamp_watermarks(
        pd.DataFrame(
            {
                "decision_date": ["2024-01-02", "2024-01-03"],
                "feature_available_at": ["2024-01-02", "2024-01-04"],
                "label_window_start": ["2024-01-03", "2024-01-04"],
            }
        )
    )
    _expect((audit["status"] == "failed").any(), "timestamp audit should reject late feature availability", failures)
    _expect(validate_governance_split(5, 5), "governance split should reject insufficient purge", failures)
    _expect(not validate_governance_split(20, 5), "governance split should accept purge=20 embargo=5", failures)
    split_audit = audit_training_window_boundaries(
        pd.DataFrame(
            {
                "train_label_window_end": ["2024-01-09", "2024-01-18"],
                "validation_start": ["2024-01-17", "2024-01-22"],
            }
        )
    )
    _expect((split_audit["status"] == "failed").any(), "training split audit should reject labels crossing embargo boundary", failures)
    print("[PASS] reputation differentiation, shadow reward, and leakage gates")


def _verify_runner_and_advanced_policies(failures):
    dates = pd.bdate_range("2024-01-01", periods=32)
    symbols = [
        ("sh510300", "etf_fund"),
        ("sh600000", "stock"),
        ("sh600001", "stock"),
        ("sz000001", "stock"),
        ("sz300001", "stock"),
        ("sh688001", "stock"),
    ]
    rows = []
    for day_index, date in enumerate(dates):
        for symbol_index, (symbol, instrument_type) in enumerate(symbols):
            price = 10.0 + symbol_index + day_index * (0.01 + symbol_index * 0.002)
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "instrument_type": instrument_type,
                    "open": price,
                    "close": price,
                    "open_nominal": price,
                    "close_nominal": price,
                    "amount": 1_000_000.0,
                    "is_trading": True,
                    "rough_limit_up": False,
                    "rough_limit_down": False,
                    "abnormal_jump": False,
                    "ret_20": 0.01 * (symbol_index + 1),
                    "score_mom_lowvol": 0.008 * (symbol_index + 1),
                    "close_to_ma20": 0.006 * (symbol_index + 1),
                    "volatility_20": 0.01 + symbol_index * 0.002,
                }
            )
    features = pd.DataFrame(rows)
    with TemporaryDirectory() as output_dir:
        saved = GovernanceBacktestRunner(
            features,
            safety_proxy_mode="strict",
            output_dir=output_dir,
        ).run()
        required_outputs = {
            "ideal_portfolio_plan",
            "executable_order_plan",
            "actual_exposure_ledger",
            "pending_order_ledger",
            "safety_decision_ledger",
            "constraint_allocation_ledger",
            "reputation_ledger",
            "shadow_portfolio_ledger",
            "leakage_audit_report",
            "governance_daily_result",
            "governance_execution_ledger",
            "governance_reward_ledger",
            "governance_alpha_proposals",
            "governance_alpha_collapse_exit_diagnostics",
            "governance_account_audit_ledger",
            "governance_corporate_action_ledger",
            "governance_rollback_recommendation_ledger",
            "governance_performance_risk_plot",
            "governance_model_reputation_plot",
            "governance_safety_points_plot",
            "environment_manifest",
        }
        _expect(required_outputs.issubset(saved), "runner should save all governance ledgers", failures)
        daily = pd.read_csv(saved["governance_daily_result"])
        _expect(len(daily) == len(dates), "runner should produce one exposure row per date", failures)
        _expect(pd.read_csv(saved["governance_execution_ledger"]).shape[0] > 0, "runner should execute synthetic orders", failures)
        account_audit = pd.read_csv(saved["governance_account_audit_ledger"])
        _expect(account_audit["reconciliation_passed"].all(), "daily account reconciliation should remain exact", failures)

    calibration = fit_isotonic_calibration_table(
        [0.1, 0.2, 0.3, 0.4, 0.8, 0.9],
        [0, 0, 1, 0, 1, 1],
    )
    _expect(calibration["calibrated_probability"].is_monotonic_increasing, "isotonic safety calibration should be monotonic", failures)
    model_safety = ModelBasedSafetyAgent(calibration)
    _expect(model_safety.decide(0.5)["exposure_cap"] <= 0.3, "calibrated safety agent should apply frozen probability table", failures)
    bandit = ContextualBanditPresidentPolicy(
        [
            BanditAction("balanced", 20, 5, 0.20),
            BanditAction("defensive", 30, 10, 0.10),
        ],
        context_size=2,
    )
    selected = bandit.select_action([1.0, 0.0])
    bandit.update(selected.action_id, [1.0, 0.0], 0.1)
    _expect(bandit.select_action([1.0, 0.0]).action_id in {"balanced", "defensive"}, "bandit selector should remain callable after update", failures)
    adapter = BanditDelegatingPresidentPolicy(bandit)
    _, _, bandit_diagnostics = adapter.decide(
        DecisionContext(
            decision_id="bandit_smoke",
            decision_date=pd.Timestamp("2024-01-31"),
            candidates=features.loc[features["date"] == dates[-1], ["symbol", "instrument_type", "volatility_20"]].assign(
                alpha_score=1.0,
                alpha_percentile=1.0,
            ),
            current_weights={},
            holding_days={},
            pending_locked_symbols=frozenset(),
            safety=SafetyDecision(pd.Timestamp("2024-01-31"), "normal", 1.0, 0.0, 0.0, "sh510300", "strict"),
        ),
        context_vector=[1.0, 0.0],
    )
    adapter.update_last_action(0.01)
    _expect("bandit_action_id" in bandit_diagnostics, "bandit adapter should delegate through deterministic constraints", failures)
    labeled = apply_governance_labels(features)
    required_labels = {"future_max_drawdown_5", "market_crash_label_5d", "liquidity_lock_label_5d", "label_window_end"}
    _expect(required_labels.issubset(labeled.columns), "governance labels should be generated", failures)
    comparison_dates = pd.bdate_range("2020-01-01", periods=63 * 8)
    governance_daily = pd.DataFrame({"date": comparison_dates, "daily_return": [0.002] * len(comparison_dates)})
    baseline_daily = pd.DataFrame({"date": comparison_dates, "daily_return": [0.0] * len(comparison_dates)})
    admission = evaluate_phase_two_admission(governance_daily, baseline_daily)
    _expect(admission["eligible_for_phase_two"], "strong synthetic governance results should pass phase-two admission", failures)
    print("[PASS] historical runner outputs and replaceable advanced policies")


def _expect(condition, message, failures):
    if not bool(condition):
        failures.append(message)


if __name__ == "__main__":
    verify_decision_council_phase_one()
