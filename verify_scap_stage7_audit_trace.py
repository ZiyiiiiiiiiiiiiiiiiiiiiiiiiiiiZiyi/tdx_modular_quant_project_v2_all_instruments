"""Stage-7 checks for SCAP decision-to-report traceability."""
from __future__ import annotations

from types import MethodType

import pandas as pd

from functions.decision_council.runner import GovernanceBacktestRunner


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def _runner_fixture() -> GovernanceBacktestRunner:
    runner = GovernanceBacktestRunner.__new__(GovernanceBacktestRunner)
    runner.shadow_fast_mode = False
    runner.governance_control_mode = "aggressive_profit"
    runner.strategy_logic_version = "mainline_v3_cabinet_native"
    runner.cash = 20_000.0
    runner.capital_profile = {
        "min_cash_buffer": 2_000.0,
        "retail_single_position_cap": 0.40,
        "retail_one_lot_position_cap": 0.40,
        "retail_min_entry_matrix_score": 0.0,
    }
    runner._last_position_mark_rows = []
    runner.entry_formula_audit_rows = []
    runner.retail_executable_rank_rows = []
    runner._retail_cash_required = MethodType(
        lambda self, **kwargs: float(kwargs["price"]) * float(kwargs["shares"]) + 5.0,
        runner,
    )
    runner._forward_return = MethodType(lambda self, *args: pd.NA, runner)
    runner._post_entry_price_diagnostics = MethodType(lambda self, *args: {}, runner)
    return runner


def main() -> None:
    runner = _runner_fixture()
    candidates = pd.DataFrame([
        {
            "symbol": "000001",
            "primary_score": 0.80,
            "entry_matrix_score": 0.95,
            "scap_candidate_utility": 0.20,
            "scap_candidate_utility_version": "scap_candidate_utility_v1",
            "scap_alpha_percentile": 0.80,
            "scap_cost_penalty": 0.02,
            "scap_concentration_penalty": 0.10,
            "scap_cash_fragment_penalty": 0.01,
            "scap_soft_quality_penalty": 0.03,
            "scap_overlap_penalty": 0.0,
            "scap_overlap_penalty_state": "portfolio_optimizer_pending",
            "scap_estimated_round_trip_cost_rate": 0.004,
            "scap_optimizer_selected": False,
            "scap_optimizer_objective": 0.75,
            "scap_optimizer_candidate_pool_size": 2,
            "scap_optimizer_status": "bounded_exact_top15",
            "entry_confirmed": True,
        },
        {
            "symbol": "000002",
            "primary_score": 0.75,
            "entry_matrix_score": 0.60,
            "scap_candidate_utility": 0.55,
            "scap_candidate_utility_version": "scap_candidate_utility_v1",
            "scap_alpha_percentile": 0.75,
            "scap_cost_penalty": 0.01,
            "scap_concentration_penalty": 0.0,
            "scap_cash_fragment_penalty": 0.0,
            "scap_soft_quality_penalty": 0.01,
            "scap_overlap_penalty": 0.0,
            "scap_overlap_penalty_state": "portfolio_optimizer_pending",
            "scap_estimated_round_trip_cost_rate": 0.003,
            "scap_optimizer_selected": True,
            "scap_optimizer_objective": 0.75,
            "scap_optimizer_candidate_pool_size": 2,
            "scap_optimizer_status": "bounded_exact_top15",
            "entry_confirmed": True,
        },
    ])
    daily = pd.DataFrame([
        {"symbol": "000001", "close_nominal": 20.0},
        {"symbol": "000002", "close_nominal": 15.0},
    ])
    runner._record_entry_formula_and_retail_rank(
        date=pd.Timestamp("2025-01-02"),
        candidates=candidates,
        daily=daily,
        exposure={"nominal_nav": 20_000.0},
    )
    audit = pd.DataFrame(runner.entry_formula_audit_rows)
    ranked = pd.DataFrame(runner.retail_executable_rank_rows)
    expected = {
        "scap_candidate_utility", "scap_candidate_utility_version",
        "scap_optimizer_selected", "scap_optimizer_objective",
        "scap_optimizer_candidate_pool_size", "scap_optimizer_status",
        "scap_cost_penalty", "scap_concentration_penalty",
        "scap_cash_fragment_penalty", "scap_soft_quality_penalty",
    }
    _check(expected.issubset(audit.columns), "entry audit persists SCAP utility and optimizer fields")
    _check(audit.iloc[0]["symbol"] == "000002", "SCAP audit prioritizes optimizer-selected candidates")
    _check(
        float(ranked.iloc[0]["retail_executable_score"]) == 0.55,
        "retail ranking uses SCAP utility instead of the legacy entry matrix",
    )
    _check(ranked.iloc[0]["symbol"] == "000002", "retail executable rank agrees with SCAP decision order")


if __name__ == "__main__":
    main()
