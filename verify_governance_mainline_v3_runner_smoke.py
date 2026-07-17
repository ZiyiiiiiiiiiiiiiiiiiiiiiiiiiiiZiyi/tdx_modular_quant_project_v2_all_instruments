from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from functions.decision_council.factor_source import (
    FACTOR_SOURCE_SELECTED_CABINET,
    resolve_factor_source,
)
from functions.decision_council.runner import GovernanceBacktestRunner


RUN_ID = "pruned_run20260714_184846_581132_20260715_230524"


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def _features(spec, *, periods: int = 8) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=periods)
    symbols = [("sh510300", "etf_fund")]
    symbols.extend((f"sh600{i:03d}", "stock") for i in range(11))
    rows = []
    raw_columns = tuple(spec.model_feature_map.values())
    for day_index, date in enumerate(dates):
        for symbol_index, (symbol, instrument_type) in enumerate(symbols):
            price = 8.0 + symbol_index * 0.4 + day_index * (0.015 + symbol_index * 0.001)
            row = {
                "date": date,
                "symbol": symbol,
                "instrument_type": instrument_type,
                "open": price,
                "close": price,
                "open_nominal": price,
                "close_nominal": price,
                "amount": 80_000_000.0,
                "amount_ma20": 75_000_000.0,
                "is_trading": True,
                "rough_limit_up": False,
                "rough_limit_down": False,
                "abnormal_jump": False,
                "ret_5": 0.002 * symbol_index,
                "ret_20": 0.006 * symbol_index,
                "close_to_ma20": 0.001 * symbol_index,
                "volatility_20": 0.012 + 0.001 * symbol_index,
                "index_pool_codes": "000300",
                "in_target_index_pool": True,
            }
            for factor_index, column in enumerate(raw_columns):
                row[column] = (
                    0.01 * (factor_index + 1)
                    + 0.03 * symbol_index
                    + 0.001 * day_index
                    + 0.0001 * ((factor_index * symbol_index) % 7)
                )
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    spec = resolve_factor_source(
        factor_source=FACTOR_SOURCE_SELECTED_CABINET,
        factor_cabinet_run_id=RUN_ID,
    )
    output = Path("reports") / f"codex_smoke_mainline_v3_{datetime.now():%Y%m%d_%H%M%S}"
    full_features = _features(spec, periods=30)
    decision_features = full_features[full_features["date"].isin(sorted(full_features["date"].unique())[:8])].copy()
    runner = GovernanceBacktestRunner(
        decision_features,
        audit_price_df=full_features[["date", "symbol", "close"]],
        initial_cash=20_000.0,
        safety_proxy_mode="strict",
        output_dir=output,
        alpha_models=spec.alpha_models,
        enable_shadow_portfolios=False,
        enable_reputation=False,
        governance_variant="governance_layer_validation",
        entry_confirmation_mode="factor_only",
        selection_weight_mode="factor_judged",
        universe_name="synthetic_v3_smoke",
        universe_mode="quality_fallback",
        require_constituents=False,
        allow_fallback=True,
        max_positions=3,
        factor_source_spec=spec,
        strategy_logic_version="mainline_v3_cabinet_native",
        pit_runtime_state="degraded",
        capital_profile={
            "name": "smoke_20k",
            "retail_lot_adapter": False,
            "max_positions": 3,
            "min_cash_buffer": 1000.0,
            "retail_single_position_cap": 0.40,
            "capital_usage_mode": "allow_cash",
        },
    )
    saved = runner.run(max_days=8, show_progress=False, show_live_monitor=False)
    _check(Path(saved["factor_runtime_audit"]).exists(), "runner saves factor runtime audit")
    _check(Path(saved["factor_semantic_contract_audit"]).exists(), "runner saves semantic contract audit")
    _check(Path(saved["governance_factor_semantic_contract"]).exists(), "runner saves all semantic contract rows")
    gates = pd.read_csv(saved["governance_candidate_gate_audit"])
    _check("cabinet_strict_entry_score" in gates.columns, "candidate spool preserves v3 role scores")
    _check(gates["strategy_logic_version"].eq("mainline_v3_cabinet_native").all(), "candidate spool is version isolated")
    _check(gates["mainline_v3_entry_confirmed"].fillna(False).astype(bool).any(), "v3 confirms at least one synthetic candidate")
    daily = pd.read_csv(saved["governance_daily_result"])
    _check(len(daily) == 8, "runner completes the bounded eight-day window")
    executions = pd.read_csv(saved["governance_execution_ledger"])
    filled_buys = executions[
        executions["side"].astype(str).str.lower().eq("buy")
        & executions["execution_status"].astype(str).str.lower().eq("filled")
    ]
    _check(not filled_buys.empty, "v3 candidate reaches a filled 20k-account buy")
    _check(
        pd.to_numeric(filled_buys["target_shares"], errors="coerce").eq(100.0).all()
        and pd.to_numeric(filled_buys["executed_shares"], errors="coerce").eq(100.0).all(),
        "v3 new entries remain exactly one lot without the retail adapter",
    )
    order_plan = pd.read_csv(saved["executable_order_plan"])
    required_trace = {
        "strategy_logic_version",
        "cabinet_native_final_score",
        "cabinet_strict_entry_score",
        "cabinet_risk_safety_score",
        "cabinet_entry_thesis",
        "mainline_v3_one_lot_cash_required",
        "mainline_v3_lot_feasible",
    }
    _check(required_trace.issubset(order_plan.columns), "order plan preserves v3 decision evidence")
    _check(required_trace.issubset(executions.columns), "execution ledger preserves v3 decision evidence")
    _check(
        filled_buys["strategy_logic_version"].eq("mainline_v3_cabinet_native").all(),
        "filled buys retain the v3 strategy version",
    )
    _check(filled_buys["cabinet_entry_thesis"].fillna("").ne("").all(), "filled buys retain cabinet entry thesis")
    _check(
        pd.to_numeric(filled_buys["cabinet_strict_entry_score"], errors="coerce").notna().all(),
        "filled buys retain strict-entry evidence",
    )
    _check(
        {"hold_validation_vote_count", "sell_trigger_vote_count"}.issubset(order_plan.columns),
        "legacy role vote evidence is no longer silently dropped",
    )
    position_state = pd.read_csv(saved["governance_position_state_ledger"])
    held_state = position_state[position_state.get("held", False).fillna(False).astype(bool)]
    _check("entry_logic_version" in position_state.columns, "position state schema records entry logic version")
    _check(
        held_state.empty or held_state["entry_logic_version"].eq("mainline_v3_cabinet_native").all(),
        "held positions retain their entry logic version",
    )
    account = pd.read_csv(saved["governance_account_audit_ledger"])
    _check(account["reconciliation_passed"].fillna(False).astype(bool).all(), "cash and holdings reconcile after v3 fills")
    integrity = pd.read_csv(saved["governance_runtime_integrity_audit"])
    coverage = integrity[integrity["check"].eq("held_state_coverage")]
    _check(
        len(coverage) == 1 and coverage["passed"].fillna(False).astype(bool).all(),
        "every overnight holding is evaluated by the lifecycle state machine",
    )
    layer = pd.read_csv(saved["governance_layer_validation_variant_report"])
    funnel = pd.read_csv(saved["governance_candidate_funnel_summary"])
    l0_count = pd.to_numeric(
        layer.loc[layer["variant"].eq("L0_all_percentile_candidates"), "selected_count"], errors="coerce"
    ).dropna()
    funnel_count = pd.to_numeric(
        funnel.loc[funnel["stage"].eq("candidate_limit_pass_count"), "total_count"], errors="coerce"
    ).dropna()
    _check(
        not l0_count.empty and not funnel_count.empty and l0_count.eq(float(funnel_count.iloc[0])).all(),
        "entry layer audit excludes lifecycle-only held rows",
    )
    observed_20d = pd.to_numeric(
        layer.loc[layer["horizon_days"].eq(20), "observed_count"], errors="coerce"
    ).fillna(0)
    _check(observed_20d.gt(0).any(), "isolated audit tail supplies observed 20-day outcomes")
    transfer = pd.read_csv(saved["governance_factor_ic_transfer_audit"])
    _check(set(transfer["horizon_days"].dropna().astype(int)) == {5, 10, 20}, "factor IC transfer audit covers 5/10/20 days")
    _check(
        pd.to_numeric(transfer["observed_days"], errors="coerce").gt(0).any(),
        "factor IC transfer audit contains observed cross-sectional days",
    )
    print(f"Smoke output: {output.resolve()}")


if __name__ == "__main__":
    main()
