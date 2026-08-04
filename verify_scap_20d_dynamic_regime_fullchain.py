"""Post-save mathematical and financial contract for a SCAP 20-day run."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_scap_20d_dynamic_regime_fullchain.py RUN_DIR")
    run_dir = Path(sys.argv[1]).resolve()
    checkpoint = json.loads((run_dir / "run_checkpoint.json").read_text(encoding="utf-8"))
    complete = json.loads((run_dir / "COMPLETE.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "artifact_manifest.json").read_text(encoding="utf-8"))
    daily = pd.read_csv(run_dir / "governance_daily_result.csv")
    summary = pd.read_csv(run_dir / "governance_strategy_summary.csv").iloc[0]
    benchmark = pd.read_csv(run_dir / "governance_performance_benchmark.csv")
    account = pd.read_csv(run_dir / "governance_account_audit_ledger.csv")
    constraints = pd.read_csv(run_dir / "governance_portfolio_constraint_report.csv")
    execution = pd.read_csv(run_dir / "governance_execution_ledger.csv")
    order_plan = pd.read_csv(run_dir / "executable_order_plan.csv")
    pending = pd.read_csv(run_dir / "pending_order_ledger.csv")
    plans = pd.read_csv(run_dir / "governance_action_plan_ledger.csv")
    integrity = pd.read_csv(run_dir / "governance_runtime_integrity_audit.csv")

    expect(checkpoint["status"] == "complete" and complete["status"] == "complete", "checkpoint and completion marker are complete")
    expect(len(daily) == checkpoint["total_days"] == complete["trading_days"] == 20, "exactly twenty observed trading days are saved")
    expect(manifest["status"] == "complete" and all(bool(manifest[key]) for key in ("core_complete", "audit_complete", "web_complete")), "core, audit and Web artifact stages are complete")

    csv_files = sorted(run_dir.glob("*.csv"))
    for path in csv_files:
        pd.read_csv(path)
    expect(len(csv_files) >= 100, f"all {len(csv_files)} top-level CSV artifacts are readable")

    expect(daily["position_capacity_mode"].eq("auto").all(), "position capacity uses automatic economic mode")
    expect(daily["configured_max_positions"].isna().all() and daily["user_hard_position_cap"].isna().all(), "no fixed or Web hard cap is silently synthesized")
    expect(
        (
            daily["holding_count"]
            <= daily["effective_position_cap"]
            + pd.to_numeric(daily["grandfathered_excess_names"], errors="coerce").fillna(0)
        ).all(),
        "daily holdings never exceed effective capacity plus disclosed grandfathered names",
    )
    expect(bool(constraints["position_limit_pass"].astype(bool).all()), "saved portfolio constraint report agrees with the daily cap")
    expect(
        int(daily["search_position_cap"].max()) > 5,
        "search capacity can exceed five names without forcing uneconomic holdings",
    )
    expect(
        {
            "sizing_reference_positions",
            "selected_position_count",
            "profit_coverage_ratio",
            "profit_coverage_probability_lower",
            "coverage_evidence_name_count",
            "coverage_state",
            "lifecycle_cost_amount",
            "expected_log_growth",
            "minimum_selected_marginal_utility_amount",
            "maximum_rejected_marginal_utility_amount",
            "coverage_mode",
            "hold_baseline_objective_amount",
            "incremental_expected_wealth_amount",
            "incremental_cvar_amount",
            "model_uncertainty_amount",
            "scenario_risk_penalty_amount",
            "scenario_evidence_state",
            "scenario_contract_id",
            "best_rejected_objective_amount",
        }.issubset(daily.columns),
        "dynamic K, lifecycle cost and profit-coverage diagnostics persist daily",
    )
    expect(
        (pd.to_numeric(daily["selected_position_count"], errors="coerce") <= daily["effective_position_cap"]).all(),
        "optimizer-selected K never exceeds the effective economic cap",
    )
    expect(
        pd.to_numeric(daily["lifecycle_cost_amount"], errors="coerce").ge(0.0).all(),
        "saved lifecycle cost is nonnegative even when PIT coverage is cold-start",
    )
    expect(
        daily["coverage_mode"].isin({"diagnostic_shadow", "authorized_ceiling_only"}).all()
        and pd.to_numeric(daily["coverage_penalty_amount"], errors="coerce").eq(0.0).all(),
        "PCR/PCP is diagnostic or a narrow above-target ceiling gate and never creates a NAV penalty",
    )
    expect(
        pd.to_numeric(daily["incremental_cvar_amount"], errors="coerce").ge(0.0).all()
        and pd.to_numeric(daily["model_uncertainty_amount"], errors="coerce").ge(0.0).all()
        and pd.to_numeric(daily["scenario_risk_penalty_amount"], errors="coerce").ge(0.0).all(),
        "incremental scenario risk amounts persist as finite nonnegative CNY values",
    )

    variable_round_trip_rate = 2.0 * 0.0005 + 0.0005 + 2.0 * 0.00001
    expected_minimum_order = 2.0 * 5.0 / (0.005 - variable_round_trip_rate)
    observed_minimum = pd.to_numeric(daily["capacity_minimum_economic_order_amount"], errors="coerce")
    expect(np.allclose(observed_minimum, expected_minimum_order, rtol=0.0, atol=1e-9), "minimum economic order solves the full round-trip friction inequality")

    diagnostics_enabled = daily["regime_diagnostics_enabled"].astype(bool)
    expect(
        diagnostics_enabled.nunique() == 1,
        "market-state diagnostic mode is stable throughout the controlled run",
    )
    if bool(diagnostics_enabled.iloc[0]):
        expect(daily["regime_input_valid"].astype(bool).all() and daily["regime_input_status"].eq("valid").all(), "all enabled market-state inputs are valid")
        expect(pd.to_numeric(daily["regime_breadth_coverage"], errors="coerce").min() > 0.99, "enabled market breadth covers more than 99 percent of the stock cross-section")
        expect(pd.to_numeric(daily["regime_breadth_score"], errors="coerce").nunique() > 1, "enabled market breadth is observed data rather than a fixed neutral constant")
    else:
        expect((~daily["regime_input_valid"].astype(bool)).all() and daily["regime_input_status"].eq("unknown").all(), "disabled market-state inputs remain explicitly unknown")
        expect(daily["regime_overlay_mode"].eq("off").all() and (~daily["regime_control_enabled"].astype(bool)).all(), "disabled market-state controls cannot affect trading")
    expect((~daily["regime_control_authorized"].astype(bool)).all(), "market state remains observation-only with no binary trading authority")
    expect(daily["regime_benchmark_symbol"].eq("sh510300").all() and daily["regime_benchmark_role"].eq("safety_control_proxy").all(), "control benchmark identity is explicit")
    expect(daily["performance_benchmark_distinct_from_regime_proxy"].astype(bool).all(), "performance and control benchmark roles remain separate")

    decision_benchmark = benchmark[benchmark["date"].isin(daily["date"])]
    expect(len(decision_benchmark) == 20 and decision_benchmark["benchmark_return_valid"].astype(bool).all(), "performance benchmark is valid on all decision dates")
    geometric_excess = float(summary["final_net_value"]) / (1.0 + float(summary["benchmark_total_return"])) - 1.0
    expect(abs(geometric_excess - float(summary["benchmark_excess_return"])) <= 1e-12, "saved excess return equals the geometric NAV ratio")
    expect(pd.to_numeric(account["reconciliation_error"], errors="coerce").abs().max() <= 1e-9, "cash plus marked holdings exactly rebuild account NAV")
    expect(pd.to_numeric(execution["executed_shares"], errors="coerce").gt(0).all() and pd.to_numeric(execution["total_cost"], errors="coerce").ge(0).all(), "all saved fills have positive shares and nonnegative modeled cost")
    expect(integrity["passed"].astype(bool).all(), "all runtime-integrity contracts pass")

    ordinary_buys = order_plan[
        order_plan["side"].astype(str).str.lower().eq("buy")
        & order_plan["reason"].astype(str).isin(["normal_buy", "confirmed_entry_buy"])
    ]
    catchup_buys = order_plan[
        order_plan["side"].astype(str).str.lower().eq("buy")
        & order_plan["reason"].astype(str).eq("exposure_catchup_buy")
    ]
    allowed_dates = set(
        daily.loc[daily["allow_normal_rebalance"].astype(bool), "date"].astype(str)
    )
    expect(
        set(ordinary_buys["decision_date"].astype(str)).issubset(allowed_dates),
        "every ordinary Lean buy plan originates on an authorized monthly session",
    )
    catchup_authorized = daily["catchup_allowed"].astype(bool)
    if "post_mandatory_recovery_authorized" in daily.columns:
        catchup_authorized = catchup_authorized | daily[
            "post_mandatory_recovery_authorized"
        ].astype(bool)
    catchup_dates = set(
        daily.loc[catchup_authorized, "date"].astype(str)
    ) - allowed_dates
    expect(
        set(catchup_buys["decision_date"].astype(str)).issubset(catchup_dates),
        "every recovery buy plan originates under explicit non-monthly catch-up authority",
    )
    environment = json.loads((run_dir / "environment_manifest.json").read_text(encoding="utf-8"))
    runtime_identity = environment["runtime_identity"]
    positive_holding_changes = pd.to_numeric(
        daily["holding_count"], errors="coerce"
    ).diff().fillna(daily["holding_count"]).clip(lower=0)
    ordinary_slope = int(runtime_identity["max_daily_new_names"])
    recovery_batch_allowance = pd.to_numeric(
        daily["post_mandatory_recovery_holding_deficit"], errors="coerce"
    ).fillna(0).shift(1, fill_value=0)
    registered_or_recovery_limit = np.maximum(ordinary_slope, recovery_batch_allowance)
    expect(
        positive_holding_changes.le(registered_or_recovery_limit).all(),
        "daily new-name deployment respects the ordinary slope or the prior-session floor-recovery batch",
    )
    if not pending.empty:
        ordinary_pending = pending[
            ~pending["reason"].astype(str).eq("exposure_catchup_buy")
        ]
        recovery_pending = pending[
            pending["reason"].astype(str).eq("exposure_catchup_buy")
        ]
        expect(
            ordinary_pending["order_execution_policy"].astype(str).eq("monthly_plan_window").all()
            and pd.to_numeric(ordinary_pending["signal_age_sessions"], errors="coerce").le(
                pd.to_numeric(ordinary_pending["maximum_age_sessions"], errors="coerce")
            ).all(),
            "pending ordinary buys retain monthly execution policy and valid trading-session age",
        )
        expect(
            recovery_pending["order_execution_policy"].astype(str).eq("next_session_only").all()
            and pd.to_numeric(recovery_pending["maximum_age_sessions"], errors="coerce").eq(1).all(),
            "pending recovery buys retain next-session-only execution policy",
        )
    expect(
        runtime_identity["portfolio_calendar_end"]
        > str(daily["date"].astype(str).max()),
        "runtime identity uses the full requested calendar rather than the truncated experiment tail",
    )

    objective_parts = (
        pd.to_numeric(plans["proposal_robust_profit_amount"], errors="coerce")
        - pd.to_numeric(plans["authority_penalty_amount"], errors="coerce")
        - pd.to_numeric(plans["thesis_penalty_amount"], errors="coerce")
        - pd.to_numeric(plans["concentration_penalty_amount"], errors="coerce")
        - pd.to_numeric(plans["scenario_risk_penalty_amount"], errors="coerce")
        - pd.to_numeric(plans["deployment_penalty_amount"], errors="coerce")
    )
    expect(
        np.allclose(
            objective_parts,
            pd.to_numeric(plans["robust_net_profit_amount"], errors="coerce"),
            rtol=0.0,
            atol=1e-9,
        ),
        "every saved ActionPlan objective is reproducible from its CNY decomposition",
    )
    no_action = plans["selected_proposal_ids"].astype(str).eq("()")
    expect(
        pd.to_numeric(plans.loc[no_action, "robust_net_profit_amount"], errors="coerce").abs().le(1e-12).all()
        and pd.to_numeric(plans.loc[no_action, "deployment_penalty_amount"], errors="coerce").abs().le(1e-12).all(),
        "the factual no-trade baseline remains exactly zero incremental wealth",
    )

    if not daily["covariance_risk_model_used"].astype(bool).any():
        expect(not plans["risk_model_used"].astype(str).str.contains("covariance", case=False, na=False).any(), "cold-start plans do not falsely claim covariance risk usage")

    exit_summary = pd.read_csv(run_dir / "governance_exit_counterfactual_summary.csv")
    expected_exit_columns = {"cash_exit_reward_amount", "benchmark_exit_reward_amount", "replacement_exit_reward_amount", "summary_contract"}
    expect(expected_exit_columns.issubset(exit_summary.columns), "exit counterfactual summary preserves cash, benchmark and replacement contracts even with no matured exits")
    print(f"[PASS] SCAP 20-day full-chain verification completed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
