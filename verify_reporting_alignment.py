# -*- coding: utf-8 -*-
"""Focused verification for report structure, degradation counting, and governance pages."""
from __future__ import annotations

import pandas as pd

from functions.report_builder import build_strategy_report


def verify_reporting_alignment():
    print("=== Verify reporting alignment ===")
    summary = pd.DataFrame(
        [
            {
                "strategy": "rule_a",
                "strategy_source": "rule",
                "weighting_mode": "equal_weight",
                "total_return": 0.10,
                "sharpe": 1.0,
                "max_drawdown": -0.10,
                "top1_weight": 0.50,
                "top5_weight_sum": 0.90,
                "effective_n": 2.0,
                "degradation_count": 0,
                "degradation_flags": "",
                "benchmark_status": "blocked",
                "composite_score": 80.0,
                "date_window": "2021-01-01 -> 2021-12-31",
            },
            {
                "strategy": "tech_a",
                "strategy_source": "technical",
                "weighting_mode": "kelly_managed",
                "total_return": 0.08,
                "sharpe": 1.2,
                "max_drawdown": -0.08,
                "top1_weight": 0.05,
                "top5_weight_sum": 0.20,
                "effective_n": 20.0,
                "degradation_count": 3,
                "degradation_flags": "price_basis_nominal_fallback|ml_tree_model_proxy_used|benchmark_unavailable",
                "benchmark_status": "blocked",
                "composite_score": 75.0,
                "date_window": "2021-01-01 -> 2021-12-31",
            },
        ]
    )
    governance_summary = pd.DataFrame(
        [
            {
                "strategy": "rules_based_president",
                "strategy_source": "governance",
                "weighting_mode": "dynamic_governance",
                "total_return": 0.02,
                "sharpe": pd.NA,
                "max_drawdown": pd.NA,
                "top1_weight": 0.10,
                "top5_weight_sum": 0.30,
                "effective_n": 8.0,
                "degradation_count": 0,
                "degradation_flags": "",
                "benchmark_status": "blocked",
                "governance_variant": "rules_based_president",
                "safety_proxy_mode": "strict",
                "exposure_cap_mode": "rule_based_safety_agent",
                "safety_agent_enabled": True,
                "reputation_enabled": True,
                "reputation_window_ready": True,
                "reputation_window_observed_days": 65,
                "reputation_window_required_days": 60,
                "ml_weight_state": "reputation_weighted_active",
                "ml_weight_distinction": 0.12,
                "sector_cap_enabled": True,
                "turnover_budget": 0.15,
                "participation_rate": 0.03,
                "capacity_passed_ratio": 1.0,
                "portfolio_exposure_cap": 0.60,
                "trading_freeze_trigger_count": 1,
                "trading_freeze_total_rebalance_periods": 2,
                "trading_freeze_period_lengths": "2",
                "trading_freeze_min_exposure_cap": 0.0,
                "trading_freeze_min_target_exposure": 0.0,
                "emergency_deleveraging_trigger_count": 2,
                "emergency_deleveraging_total_rebalance_periods": 3,
                "emergency_deleveraging_period_lengths": "1,2",
                "emergency_deleveraging_min_exposure_cap": 0.3,
                "emergency_deleveraging_min_target_exposure": 0.3,
                "composite_score": pd.NA,
                "date_window": "2021-01-01 -> 2021-12-31",
            }
        ]
    )
    report_text = build_strategy_report(summary, governance_summary_df=governance_summary)

    _expect("Run degradation count: `3` unique flags across `1` rows" in report_text, "triple degradation count preserved", report_text)
    _expect("### `rule` segment" in report_text, "total table segmented for rule category", report_text)
    _expect("### `governance` segment" in report_text, "total table segmented for governance category", report_text)
    _expect("Current effective_n threshold uses the default value and can be adjusted in config." in report_text, "default effective_n threshold note emitted", report_text)
    _expect("Current top5_weight_sum threshold uses the default value and can be adjusted in config." in report_text, "default top5 threshold note emitted", report_text)
    _expect("### Governance Event Summary" in report_text, "governance event summary section present", report_text)
    _expect("period_lengths=`2`" in report_text, "governance freeze period length rendered", report_text)
    _expect("safety_agent_enabled=`True`" in report_text, "governance identity fields rendered", report_text)
    _expect("reputation_window_ready=`True`" in report_text, "governance reputation readiness rendered", report_text)
    _expect("reputation_window_progress=`65/60`" in report_text, "governance reputation warmup progress rendered", report_text)
    _expect("ml_weight_state=`reputation_weighted_active`" in report_text, "governance ml weight state rendered", report_text)
    _expect("Governance comparability disclaimer" in report_text, "governance comparability disclaimer rendered", report_text)

    print("Reporting alignment verification passed.")


def _expect(condition, label, payload):
    if condition:
        print(f"[PASS] {label}")
        return
    print(f"[FAIL] {label}")
    raise SystemExit(payload)


if __name__ == "__main__":
    verify_reporting_alignment()
