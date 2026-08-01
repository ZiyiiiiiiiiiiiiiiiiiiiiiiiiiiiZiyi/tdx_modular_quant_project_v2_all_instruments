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
    expect((daily["holding_count"] <= daily["effective_position_cap"]).all(), "daily holdings never exceed the effective economic cap")
    expect(bool(constraints["position_limit_pass"].astype(bool).all()), "saved portfolio constraint report agrees with the daily cap")
    expect(int(daily["holding_count"].max()) > 5, "twenty-thousand-yuan run is demonstrably not hard-coded to five names")

    variable_round_trip_rate = 2.0 * 0.0005 + 0.0005 + 2.0 * 0.00001
    expected_minimum_order = 2.0 * 5.0 / (0.005 - variable_round_trip_rate)
    observed_minimum = pd.to_numeric(daily["capacity_minimum_economic_order_amount"], errors="coerce")
    expect(np.allclose(observed_minimum, expected_minimum_order, rtol=0.0, atol=1e-9), "minimum economic order solves the full round-trip friction inequality")

    expect(daily["regime_input_valid"].astype(bool).all() and daily["regime_input_status"].eq("valid").all(), "all decision dates have valid market-state inputs")
    expect(pd.to_numeric(daily["regime_breadth_coverage"], errors="coerce").min() > 0.99, "market breadth covers more than 99 percent of the stock cross-section")
    expect(pd.to_numeric(daily["regime_breadth_score"], errors="coerce").nunique() > 1, "market breadth is observed data rather than a fixed neutral constant")
    expect(daily["regime_diagnostics_enabled"].astype(bool).all(), "market-state diagnostics are enabled")
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

    if not daily["covariance_risk_model_used"].astype(bool).any():
        expect(not plans["risk_model_used"].astype(str).str.contains("covariance", case=False, na=False).any(), "cold-start plans do not falsely claim covariance risk usage")

    exit_summary = pd.read_csv(run_dir / "governance_exit_counterfactual_summary.csv")
    expected_exit_columns = {"cash_exit_reward_amount", "benchmark_exit_reward_amount", "replacement_exit_reward_amount", "summary_contract"}
    expect(expected_exit_columns.issubset(exit_summary.columns), "exit counterfactual summary preserves cash, benchmark and replacement contracts even with no matured exits")
    print(f"[PASS] SCAP 20-day full-chain verification completed: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
