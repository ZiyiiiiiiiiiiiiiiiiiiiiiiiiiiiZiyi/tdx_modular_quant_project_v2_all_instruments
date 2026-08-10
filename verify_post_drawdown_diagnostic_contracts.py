"""Focused financial and schema checks for post-drawdown diagnostics."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.post_drawdown_diagnostics import (
    build_benchmark_bundle,
    build_entry_quality_authority,
    build_exit_delay_counterfactual,
    build_exit_signal_authority_ledger,
    build_market_state_ledger,
    build_recovery_episode_ledger,
    resolve_post_entry_failure_authority,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> None:
    observed = resolve_post_entry_failure_authority(
        signal_detected=True,
        strategy_logic_version="mainline_v3_cabinet_native",
        control_mode="aggressive_lean",
        control_enabled=True,
        configured_mode="diagnostic",
    )
    check(
        observed["detected"] and not observed["authority_active"]
        and "configured_diagnostic_only" in observed["veto_reasons"],
        "diagnostic post-entry failure cannot masquerade as a sell authority",
    )
    trading = resolve_post_entry_failure_authority(
        signal_detected=True,
        strategy_logic_version="mainline_v3_cabinet_native",
        control_mode="aggressive_lean",
        control_enabled=True,
        authorized_reasons=("post_entry_failure_exit",),
        selected_reason="post_entry_failure_exit",
        configured_mode="trading",
    )
    check(
        trading["authority_active"] and trading["selected_for_exit"],
        "explicit trading mode plus control and arbitration grants authority",
    )

    dates = pd.bdate_range("2026-03-09", periods=25)
    position = pd.DataFrame(
        [
            {
                "date": dates[0], "symbol": "sh600000",
                "post_entry_failure_detected": True,
                "post_entry_failure_paper_active": True,
                "post_entry_failure_policy_enabled": False,
                "post_entry_failure_control_enabled": True,
                "post_entry_failure_authority_active": False,
                "post_entry_failure_authority_veto_reasons": "configured_diagnostic_only",
                "post_entry_failure_score": 0.81,
                "exit_triggered_reasons": "post_entry_failure_exit",
            },
            {
                "date": dates[2], "symbol": "sh600000",
                "post_entry_failure_detected": True,
                "post_entry_failure_paper_active": True,
                "post_entry_failure_policy_enabled": True,
                "post_entry_failure_control_enabled": True,
                "post_entry_failure_authority_active": True,
                "post_entry_failure_score": 0.88,
                "exit_triggered_reasons": "post_entry_failure_exit",
                "exit_authorized_reasons": "post_entry_failure_exit",
                "position_exit_reason": "post_entry_failure_exit",
            },
        ]
    )
    executions = pd.DataFrame(
        [{
            "decision_id": f"gov_{dates[2]:%Y%m%d}", "symbol": "sh600000",
            "side": "sell", "reason": "post_entry_failure_exit",
            "trade_date": dates[3], "price": 9.7, "order_id": "o1", "fill_id": "f1",
        }]
    )
    authority = build_exit_signal_authority_ledger(position, executions)
    check(
        len(authority) == 2 and authority["detected"].all()
        and authority["authority_active"].sum() == 1
        and authority["selected_for_exit"].sum() == 1,
        "exit observation, authority, selection, and fill lineage stay distinct",
    )
    prices = pd.DataFrame({
        "date": dates, "symbol": "sh600000",
        "close_nominal": [10.0 + 0.1 * index for index in range(len(dates))],
    })
    delay = build_exit_delay_counterfactual(authority, prices)
    check(
        len(delay) == 1
        and int(delay.iloc[0]["authority_delay_sessions"]) == 2
        and int(delay.iloc[0]["execution_delay_sessions"]) == 3
        and abs(float(delay.iloc[0]["forward_return_5d"]) - 0.05) < 1e-12,
        "exit delay uses trading sessions and point-in-time closes",
    )

    safety_rows = []
    for index, date in enumerate(dates[:10]):
        safety_rows.append({
            "decision_date": date,
            "risk_level": "crisis" if index == 0 else "normal",
            "structural_regime_level": "neutral",
            "hard_freeze_active": index == 0,
            "exposure_cap": 0.85,
            "benchmark_return_5d": -0.05 if index == 0 else 0.01,
            "benchmark_return_20d": -0.10 if index == 0 else 0.0,
            "benchmark_drawdown_5d": 0.06 if index == 0 else 0.01,
            "benchmark_drawdown_20d": 0.12 if index == 0 else 0.03,
            "benchmark_underwater_from_peak": 0.12 - index * 0.01,
            "market_liquidity_stress_ratio": 0.08,
            "proxy_symbol": "sh510300",
            "degraded": False,
        })
    daily = pd.DataFrame({
        "date": dates[:10],
        "decision_id": [f"gov_{date:%Y%m%d}" for date in dates[:10]],
        "desired_exposure_target": 0.75,
        "integer_attainable_exposure": 0.70,
        "actual_exposure": 0.50,
    })
    market = build_market_state_ledger(daily, pd.DataFrame(safety_rows))
    check(
        market.iloc[0]["recovery_state"] == "BLOCKED"
        and market.iloc[-1]["recovery_state"] == "OPEN",
        "recovery is immediate on deterioration and staged on improvement",
    )
    expected_open_cap = min(0.85, 0.75, 0.85, 0.70)
    check(
        abs(float(market.iloc[-1]["effective_deployment_cap"]) - expected_open_cap) < 1e-12,
        "effective deployment cap is the minimum of safety, structure, recovery, and attainability",
    )
    episodes = build_recovery_episode_ledger(market)
    check(len(episodes) == 1 and bool(episodes.iloc[0]["open_reached"]), "recovery episode preserves the full state path")
    persisted_after_initial_transition = market.iloc[1:5].copy()
    persisted_after_initial_transition.loc[:, "recovery_state"] = [
        "STABILIZING", "STEP1", "STEP2", "OPEN"
    ]
    episodes_without_blocked_row = build_recovery_episode_ledger(
        persisted_after_initial_transition
    )
    check(
        len(episodes_without_blocked_row) == 1
        and int(episodes_without_blocked_row.iloc[0]["days_in_episode"]) == 4
        and bool(episodes_without_blocked_row.iloc[0]["open_reached"]),
        "persisted recovery beginning at STABILIZING remains an episode",
    )

    proposals = pd.DataFrame([
        {
            "proposal_id": "p_c", "decision_id": "gov_20260309", "decision_date": dates[0],
            "symbol": "sz000001", "action_type": "new_entry", "authority_tier": "C",
            "calibration_evidence_state": "drifted", "calibration_effective_sample_size": 12,
            "coverage_evidence_authorized": False, "robust_net_profit_amount": 40.0,
            "authority_penalty_amount": 5.0, "scenario_risk_penalty_amount": 3.0,
            "model_uncertainty_amount": 2.0, "requested_lots": 1,
            "market_notional_amount": 2000.0, "economic_order_pass": True,
        },
        {
            "proposal_id": "p_a", "decision_id": "gov_20260309", "decision_date": dates[0],
            "symbol": "sz000002", "action_type": "new_entry", "authority_tier": "A",
            "calibration_evidence_state": "calibrated", "calibration_effective_sample_size": 200,
            "coverage_evidence_authorized": True, "robust_net_profit_amount": 40.0,
            "authority_penalty_amount": 5.0, "scenario_risk_penalty_amount": 3.0,
            "model_uncertainty_amount": 2.0, "requested_lots": 1,
            "market_notional_amount": 2000.0, "economic_order_pass": True,
        },
    ])
    quality = build_entry_quality_authority(proposals)
    quality = quality.set_index("proposal_id")
    check(
        quality.at["p_c", "trade_mode"] == "shadow_only"
        and int(quality.at["p_c", "maximum_lots"]) == 0,
        "tier C without strict full-universe OOS evidence is shadow-only",
    )
    check(
        quality.at["p_a", "trade_mode"] == "normal"
        and abs(float(quality.at["p_a", "risk_adjusted_ce_amount"]) - 30.0) < 1e-12,
        "entry CE subtracts lifecycle-net robust value and each remaining risk charge once",
    )

    performance = pd.DataFrame([{
        "date": dates[0], "benchmark_scope": "decision", "benchmark_id": "top100",
        "benchmark_constituent_rule": "pit_top_liquidity", "benchmark_weighting": "equal",
        "benchmark_daily_return": 0.01, "benchmark_net_value": 1.01,
        "benchmark_return_valid": True, "benchmark_return_coverage": 0.99,
    }])
    bundle = build_benchmark_bundle(performance, pd.DataFrame(safety_rows[:1]))
    check(
        set(bundle["role"]) == {"performance_primary", "opportunity_set", "style_matched", "safety_proxy"}
        and len(bundle) == 4,
        "four benchmark roles are explicit and unavailable roles fail closed",
    )


if __name__ == "__main__":
    main()
