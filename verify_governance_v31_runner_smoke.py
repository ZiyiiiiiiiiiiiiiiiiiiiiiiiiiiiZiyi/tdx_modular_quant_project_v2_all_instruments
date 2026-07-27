"""Eight-day full-runner product smoke for frozen v3.1 reliability ranking."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from functions.decision_council.factor_source import FACTOR_SOURCE_SELECTED_CABINET, resolve_factor_source
from functions.decision_council.reliability_weighted_scoring import MAINLINE_V31_RELIABILITY
from functions.decision_council.runner import GovernanceBacktestRunner
from verify_governance_mainline_v3_runner_smoke import RUN_ID, _check, _features


V31_FIELDS = {
    "v31_reliability_score", "v31_reliability_score_coverage",
    "v31_reliability_contract", "v31_calibration_window",
    "v31_score_formula", "v31_score_authority", "v31_strict_entry_paper_only",
}


def main():
    spec = resolve_factor_source(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=RUN_ID,
    )
    output = Path("reports") / f"codex_smoke_v31_reliability_{datetime.now():%Y%m%d_%H%M%S}"
    full = _features(spec, periods=30)
    decision = full[full["date"].isin(sorted(full["date"].unique())[:8])].copy()
    runner = GovernanceBacktestRunner(
        decision,
        audit_price_df=full[["date", "symbol", "close"]],
        initial_cash=20_000.0,
        safety_proxy_mode="strict",
        output_dir=output,
        alpha_models=spec.alpha_models,
        enable_shadow_portfolios=False,
        enable_reputation=False,
        governance_variant="governance_layer_validation",
        entry_confirmation_mode="factor_only",
        selection_weight_mode="factor_judged",
        universe_name="synthetic_v31_smoke",
        universe_mode="quality_fallback",
        require_constituents=False,
        allow_fallback=True,
        max_positions=3,
        factor_source_spec=spec,
        strategy_logic_version=MAINLINE_V31_RELIABILITY,
        pit_runtime_state="degraded",
        capital_profile={
            "name": "smoke_20k", "retail_lot_adapter": False, "max_positions": 3,
            "min_cash_buffer": 1000.0, "retail_single_position_cap": .40,
            "capital_usage_mode": "allow_cash",
        },
    )
    saved = runner.run(max_days=8, show_progress=False, show_live_monitor=False)
    candidates = pd.read_csv(saved["governance_candidate_gate_audit"])
    orders = pd.read_csv(saved["executable_order_plan"])
    executions = pd.read_csv(saved["governance_execution_ledger"])
    pending = pd.read_csv(saved["pending_order_ledger"])
    positions = pd.read_csv(saved["governance_position_state_ledger"])
    _check(V31_FIELDS.issubset(candidates.columns), "candidate audit retains the complete v3.1 authority contract")
    _check(V31_FIELDS.issubset(orders.columns), "order plan retains v3.1 score provenance")
    _check(V31_FIELDS.issubset(executions.columns), "execution ledger retains v3.1 score provenance")
    _check(V31_FIELDS.issubset(pending.columns), "pending-order ledger retains v3.1 score provenance")
    buys = executions[
        executions["side"].astype(str).str.lower().eq("buy")
        & executions["execution_status"].astype(str).str.lower().eq("filled")
    ]
    _check(not buys.empty, "v3.1 produces a real synthetic filled buy")
    _check(pd.to_numeric(buys["executed_shares"], errors="coerce").eq(100).all(), "v3.1 filled buys remain exactly one lot")
    _check(buys["strategy_logic_version"].eq(MAINLINE_V31_RELIABILITY).all(), "fills retain the isolated v3.1 logic version")
    held = positions[positions["entry_logic_version"].astype(str).eq(MAINLINE_V31_RELIABILITY)]
    _check(not held.empty, "position lifecycle binds holdings to v3.1")
    integrity = pd.read_csv(saved["governance_runtime_integrity_audit"])
    _check(integrity["passed"].fillna(False).astype(bool).all(), "v3.1 cash, holdings, timing and fills reconcile")
    print(f"Smoke output: {output.resolve()}")


if __name__ == "__main__":
    main()
