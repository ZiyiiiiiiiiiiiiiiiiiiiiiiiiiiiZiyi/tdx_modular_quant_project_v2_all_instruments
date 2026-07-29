"""Focused correctness checks for the SCAP-V3 Lean authority chain."""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import replace
from types import SimpleNamespace

import functions.decision_council.policy as policy_module
from functions.decision_council.contracts import DecisionContext, SafetyDecision
from functions.decision_council.entry_calibration import RollingEntryCalibrator
from functions.decision_council.policy import RulesBasedPresidentPolicy
from functions.decision_council.quality_reports import build_risk_contribution_ledger
from functions.decision_council.retail_execution import adapt_retail_buy_order
from functions.decision_council.scap_v3_lean import build_lean_decision


def passed(message: str) -> None:
    print(f"[PASS] {message}")


def context(*, cash: float = 19_000.0) -> DecisionContext:
    return DecisionContext(
        decision_id="lean_20250110",
        decision_date=pd.Timestamp("2025-01-10"),
        candidates=frame(),
        current_weights={"H": 0.20},
        holding_days={"H": 12},
        pending_locked_symbols=frozenset(),
        safety=SafetyDecision(
            decision_date=pd.Timestamp("2025-01-10"),
            risk_level="normal",
            exposure_cap=0.90,
            benchmark_drawdown_5d=0.0,
            market_liquidity_stress_ratio=0.0,
            proxy_symbol="000300",
            proxy_mode="strict",
        ),
        top_n=5,
        entry_rank_limit=20,
        nav_amount=20_000.0,
        cash_amount=cash,
        cash_buffer_amount=1_000.0,
        per_name_structural_cap=0.40,
        portfolio_stress_budget_amount=8_000.0,
        control_mode="aggressive_lean",
        winner_add_enabled=True,
        loser_add_enabled=False,
        soft_exit_enabled=True,
        forecast_horizon_sessions=10,
        forecast_kappa=0.50,
        soft_target_positions=4,
    )


def frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "H",
                "alpha_score": 0.80,
                "alpha_percentile": 0.80,
                "volatility_20": 0.03,
                "primary_score": 0.80,
                "candidate_rank": 3,
                "mainline_v3_one_lot_cash_required": 2_000.0,
                "mainline_v3_one_lot_weight": 0.10,
                "mainline_v3_lot_feasible": True,
                "position_unrealized_return": 0.06,
                "add_layer": 2,
                "add_expected_net_profit_lcb": 80.0,
                "scap_candidate_utility": 80.0,
                "scap_estimated_total_cost_amount": 10.0,
                "cabinet_entry_thesis": "momentum",
                "entry_confirmed": False,
                "add_allowed": True,
                "add_decision_type": "winner_pyramiding",
                "winner_add_review_passed": True,
                "exit_state": False,
            },
            {
                "symbol": "A",
                "alpha_score": 0.90,
                "alpha_percentile": 0.90,
                "volatility_20": 0.02,
                "primary_score": 0.90,
                "candidate_rank": 1,
                "mainline_v3_one_lot_cash_required": 3_000.0,
                "mainline_v3_one_lot_weight": 0.15,
                "mainline_v3_lot_feasible": True,
                "scap_candidate_utility": 120.0,
                "scap_estimated_total_cost_amount": 10.0,
                "cabinet_entry_thesis": "quality",
                "entry_confirmed": False,
                "add_allowed": False,
                "exit_state": False,
            },
            {
                "symbol": "B",
                "alpha_score": 0.85,
                "alpha_percentile": 0.85,
                "volatility_20": 0.025,
                "primary_score": 0.85,
                "candidate_rank": 2,
                "mainline_v3_one_lot_cash_required": 2_500.0,
                "mainline_v3_one_lot_weight": 0.125,
                "mainline_v3_lot_feasible": True,
                "scap_candidate_utility": 90.0,
                "scap_estimated_total_cost_amount": 10.0,
                "cabinet_entry_thesis": "reversal",
                "entry_confirmed": False,
                "add_allowed": False,
                "exit_state": False,
            },
        ]
    )


base = build_lean_decision(context(), frame())
assert base.diagnostics["optimizer_invocation_count"] == 1
assert base.diagnostics["action_plan_count"] == 1
lean_funnel_counts = [
    base.diagnostics[name]
    for name in (
        "lean_raw_entry_signal_count",
        "lean_structural_feasible_entry_count",
        "lean_cash_feasible_entry_count",
        "lean_slot_feasible_entry_count",
        "lean_optimizer_selected_entry_count",
    )
]
assert all(right <= left for left, right in zip(lean_funnel_counts, lean_funnel_counts[1:]))
passed("one decision creates exactly one optimizer invocation and one ActionPlan")

selected = [
    proposal
    for proposal in base.proposals
    if proposal.proposal_id in set(base.plan.selected_proposal_ids)
]
assert len({proposal.symbol for proposal in selected}) == len(selected)
assert all(proposal.horizon_sessions == 10 for proposal in base.proposals)
passed("lot alternatives cannot be cumulatively selected and all actions share 10 sessions")

assert any(proposal.action_type == "winner_add" for proposal in base.proposals)
assert not any(proposal.action_type == "loser_add" for proposal in base.proposals)
passed("lifecycle-authorized winner add is proposal-reachable; loser add remains disabled")

low_cash = build_lean_decision(context(cash=4_000.0), frame())
base_buy_lots = sum(
    proposal.requested_lots
    for proposal in selected
    if proposal.funding_cash_amount > 0.0
)
low_selected = {
    proposal.proposal_id: proposal for proposal in low_cash.proposals
}
low_buy_lots = sum(
    low_selected[proposal_id].requested_lots
    for proposal_id in low_cash.plan.selected_proposal_ids
    if low_selected[proposal_id].funding_cash_amount > 0.0
)
assert low_buy_lots <= base_buy_lots
assert low_cash.plan.projected_cash >= 0.0
passed("lower available cash cannot increase selected buy lots")

original_legacy_selector = policy_module._select_scap_discrete_entries


def forbidden_legacy_selector(*args, **kwargs):
    raise AssertionError("legacy selector received Lean authority")


policy_module._select_scap_discrete_entries = forbidden_legacy_selector
try:
    ideal, orders, diagnostics = RulesBasedPresidentPolicy().decide(context())
finally:
    policy_module._select_scap_discrete_entries = original_legacy_selector
assert diagnostics["legacy_allocation_authority"] == "shadow_only"
assert diagnostics["optimizer_invocation_count"] == 1
assert set(orders["action_plan_id"].dropna()) == {"lean_20250110|action_plan"}
assert orders["action_proposal_id"].notna().all()
passed("Lean policy bypasses legacy selector/continuous allocation and preserves plan lineage")

assert float(diagnostics["strategic_exposure_budget"]) == 0.90
assert diagnostics["strategic_exposure_budget"] >= diagnostics["signal_supported_exposure"]
assert diagnostics["signal_supported_exposure"] >= diagnostics["integer_feasible_exposure"]
passed("strategic, signal-supported and integer-feasible exposure remain separate")
for required in (
    "unresolved_safety_exposure",
    "planned_safety_sell_weight",
    "constraint_cash_reserve",
):
    assert required in diagnostics
passed("Lean supplies the runner accounting diagnostics formerly owned by allocation")

safety_frame = frame().loc[lambda data: data["symbol"].eq("H")].copy()
safety_peer = safety_frame.copy()
safety_peer["symbol"] = "J"
safety_peer["comparable_expected_alpha"] = -0.02
safety_frame["comparable_expected_alpha"] = 0.01
safety_candidates = pd.concat([safety_frame, safety_peer], ignore_index=True)
safety_context = replace(
    context(),
    candidates=safety_candidates,
    current_weights={"H": 0.30, "J": 0.30},
    holding_days={"H": 12, "J": 8},
    safety=replace(context().safety, risk_level="high", exposure_cap=0.35),
)
safety_decision = build_lean_decision(safety_context, safety_candidates)
safety_selected = {
    proposal.proposal_id: proposal
    for proposal in safety_decision.proposals
    if proposal.proposal_id in set(safety_decision.plan.selected_proposal_ids)
}
assert any(
    proposal.action_type == "safety_exit"
    for proposal in safety_selected.values()
)
assert safety_decision.plan.projected_exposure <= 0.35 + 1e-12
assert safety_decision.diagnostics["planned_safety_sell_weight"] >= 0.30
assert safety_decision.diagnostics["unresolved_safety_exposure"] <= 1e-12
safety_ideal, safety_orders, safety_policy_diagnostics = (
    RulesBasedPresidentPolicy().decide(safety_context)
)
assert not safety_orders.empty
assert safety_orders["side"].astype(str).str.lower().eq("sell").all()
assert safety_orders["reason"].astype(str).eq("safety_deleveraging").all()
assert safety_policy_diagnostics["planned_safety_sell_weight"] >= 0.30
passed("Lean converts a binding lower exposure cap into forced factual exits")

warmup_dates = pd.bdate_range("2024-01-02", periods=120)
warmup_frame = pd.DataFrame(
    [
        {
            "date": date,
            "symbol": symbol,
            "open": 10.0 + index * 0.01,
            "close": 10.0 + index * 0.01 + (0.05 if symbol == "A" else -0.02),
            "ret_20": (index % 20) / 100.0 + (0.01 if symbol == "A" else 0.0),
        }
        for index, date in enumerate(warmup_dates)
        for symbol in ("A", "B")
    ]
)
warmup = RollingEntryCalibrator().warmup_from_feature_history(
    warmup_frame,
    trade_start=warmup_dates[-1] + pd.offsets.BDay(1),
    horizon_days=10,
    lookback_sessions=100,
    score_columns=("ret_20",),
)
assert warmup["status"] == "ready"
assert warmup["unique_sessions"] >= 80
assert warmup["score_column"] == "factor_cabinet_rank_mean"
assert warmup["score_column_count"] == 1
assert pd.Timestamp(warmup["latest_label_date"]) < warmup_dates[-1] + pd.offsets.BDay(1)
passed("Lean warm-up requires at least 80 independent pre-trade sessions")

multi_lot_candidate = pd.DataFrame(
    [
        {
            "symbol": "M",
            "alpha_score": 0.90,
            "alpha_percentile": 0.90,
            "volatility_20": 0.02,
            "primary_score": 0.90,
            "candidate_rank": 1,
            "mainline_v3_one_lot_cash_required": 2_000.0,
            "mainline_v3_one_lot_weight": 0.10,
            "mainline_v3_minimum_buy_quantity": 100,
            "mainline_v3_lot_feasible": True,
            "scap_candidate_utility": -4.0,
            "scap_decision_expected_return": 0.0040,
            "scap_expected_return_point": 0.0045,
            "scap_risk_penalty_amount": 0.0,
            "scap_estimated_total_cost_amount": 10.0,
            "cabinet_entry_thesis": "momentum",
            "exit_state": False,
        }
    ]
)
multi_context = replace(
    context(),
    candidates=multi_lot_candidate,
    current_weights={},
    holding_days={},
)
multi = build_lean_decision(multi_context, multi_lot_candidate)
multi_selected = [
    proposal
    for proposal in multi.proposals
    if proposal.proposal_id in set(multi.plan.selected_proposal_ids)
]
assert multi_selected
assert multi_selected[0].requested_lots > 1
assert multi_selected[0].robust_net_profit_amount > 0.0
passed("multi-lot order pays minimum commission once and can rescue a negative one-lot utility")

lean_risk_dates = pd.date_range("2024-09-02", periods=80, freq="B")
lean_return_pivot = pd.DataFrame(
    {
        "sh600000": np.linspace(-0.01, 0.01, len(lean_risk_dates)),
        "sz000001": np.linspace(0.008, -0.006, len(lean_risk_dates)),
    },
    index=lean_risk_dates,
)
lean_ideal_plan = pd.DataFrame(
    {
        "decision_date": [lean_risk_dates[-1], lean_risk_dates[-1]],
        "symbol": ["sh600000", "sz000001"],
        "target_weight": [0.30, 0.35],
        "action_plan_id": ["plan-1", "plan-1"],
    }
)
lean_risk_report = build_risk_contribution_ledger(
    ideal_portfolio_plan=lean_ideal_plan,
    return_pivot=lean_return_pivot,
)
assert not lean_risk_report.empty
assert abs(float(lean_risk_report["target_weight"].sum()) - 0.65) < 1e-12
passed("quality reports adapt Lean target_weight without scalar/Series contract failure")

lean_authorized_order = {
    "symbol": "A",
    "position_state": "blocked",
    "exit_state": False,
    "action_plan_selected": True,
    "action_plan_id": "plan-1",
    "entry_matrix_score": 0.0,
    "execution_date": pd.Timestamp("2025-01-13"),
}
lean_execution_runner = SimpleNamespace(
    capital_profile={
        "min_cash_buffer": 1_000.0,
        "retail_single_position_cap": 0.40,
        "retail_target_exposure_tolerance": 0.10,
        "retail_one_lot_position_cap": 0.40,
        "retail_min_entry_matrix_score": 0.0,
    },
    capital_usage_mode="allow_cash",
    strategy_logic_version="mainline_v3_cabinet_native",
    cash=20_000.0,
    exposure_rows=[],
)
shares, retail_action, retail_reason = adapt_retail_buy_order(
    lean_execution_runner,
    order=lean_authorized_order,
    strategy_target_notional=6_000.0,
    order_price=30.0,
    nominal_nav=20_000.0,
    reserved_cash=0.0,
    initial_shares=200.0,
    one_lot_cash_required=3_005.0,
)
assert shares == 200.0
assert retail_action == "action_plan_unchanged"
assert retail_reason == ""
passed("legacy soft blocked state cannot veto an authorized Lean ActionPlan")
