"""Focused properties for the SCAP-V3.2 aggressive small-capital contract."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pandas as pd

from functions.decision_council.integer_action_optimizer import (
    _pareto_reduce,
    optimize_action_proposals,
)
from functions.decision_council.position_lifecycle import (
    _carried_unobserved_position_states,
)
from functions.decision_council.scap_v2_contracts import (
    ActionProposal,
    ExposureAuthorization,
)
from functions.decision_council.scap_v3_lean import (
    _available_slots_after_exits,
    _append_exposure_cap_safety_exits,
    _append_held_proposals,
    _attach_pool_contract,
    _deduplicate_pool_rows,
)


def passed(message: str) -> None:
    print(f"[PASS] {message}")


def proposal(
    symbol: str,
    *,
    funding: float,
    robust: float,
    score: float,
    rank: float,
    pool: str,
    tier: str = "C",
) -> ActionProposal:
    return ActionProposal(
        proposal_id=f"d|{symbol}|entry",
        decision_id="d",
        symbol=symbol,
        action_type="new_entry",
        source_module="v32_test",
        requested_lots=1,
        baseline_action="hold_cash",
        horizon_sessions=10,
        expected_net_profit_amount=robust,
        robust_net_profit_amount=robust,
        downside_cvar_amount=funding * 0.10,
        exact_cost_amount=8.0,
        funding_cash_amount=funding,
        exposure_delta=funding / 20_000.0,
        authority_tier=tier,
        thesis=pool,
        pool_id=pool,
        pool_memberships=(pool,),
        primary_score=score,
        primary_rank=rank,
        unit_capital_robust_return=robust / funding,
    )


def authorization(**overrides) -> ExposureAuthorization:
    base = ExposureAuthorization(
        decision_id="d",
        nav_amount=20_000.0,
        risk_exposure_ceiling=0.90,
        cash_buffer_amount=1_000.0,
        per_name_structural_cap=0.40,
        per_name_stress_budget_amount=3_200.0,
        portfolio_stress_budget_amount=8_000.0,
        new_entry_allowed=True,
        add_allowed=True,
        replacement_allowed=False,
        current_cash_amount=20_000.0,
        strategic_exposure_budget=0.90,
        signal_supported_exposure=0.90,
        integer_feasible_exposure=0.90,
        tier_b_exposure_cap=1.0,
        tier_c_max_names=5,
        exploration_exposure_cap=1.0,
        desired_exposure_target=0.85,
        effective_deployment_target=0.85,
        per_name_soft_cap=0.25,
    )
    return replace(base, **overrides)


def verify_pool_deduplication() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["s1", "s1", "s2"],
            "cabinet_entry_thesis": ["momentum", "quality", "reversal"],
            "primary_score": [0.80, 0.70, 0.60],
        }
    )
    rows = _deduplicate_pool_rows(_attach_pool_contract(frame))
    assert set(rows) == {"s1", "s2"}
    assert rows["s1"]["scap_v32_pool_memberships"] == "momentum|quality"
    assert float(rows["s1"]["primary_score"]) == 0.80
    passed("cross-pool duplicate symbols produce one proposal row with all memberships")


def verify_price_scale_does_not_override_score() -> None:
    cheap_better = proposal(
        "cheap_better",
        funding=2_000.0,
        robust=40.0,
        score=0.90,
        rank=1.0,
        pool="momentum",
    )
    expensive_worse = proposal(
        "expensive_worse",
        funding=6_000.0,
        robust=120.0,
        score=0.50,
        rank=2.0,
        pool="momentum",
    )
    # Both have exactly 2% robust value per yuan. The cabinet score/rank must
    # decide the bounded candidate slot, not the absolute lot notional.
    reduced = _pareto_reduce((expensive_worse, cheap_better), limit=1)
    assert reduced == (cheap_better,)
    passed("one-lot price alone cannot override a better pool score")


def verify_multiple_c_names_are_feasible() -> None:
    items = tuple(
        proposal(
            f"c{index}",
            funding=3_000.0,
            robust=45.0 - index,
            score=0.90 - index * 0.01,
            rank=float(index),
            pool=f"pool_{index}",
        )
        for index in range(1, 5)
    )
    plan = optimize_action_proposals(
        items,
        authorization=authorization(),
        current_lots_by_symbol={},
        current_weights_by_symbol={},
        current_exposure=0.0,
        max_positions=5,
        thesis_by_symbol={item.symbol: item.thesis for item in items},
        max_names_per_thesis=3,
        candidate_limit=24,
    )
    assert len(plan.selected_proposal_ids) == 4
    assert plan.projected_exposure == 0.60
    assert plan.deployment_gap == 0.25
    assert abs(plan.breadth_score - 3.8) < 1e-12
    passed("four positive C names can coexist under the five-name portfolio cap")


def verify_gap_cannot_resurrect_negative_edge() -> None:
    item = replace(
        proposal(
            "negative_after_authority",
            funding=6_000.0,
            robust=4.0,
            score=0.99,
            rank=1.0,
            pool="momentum",
        ),
        authority_penalty_amount=6.0,
    )
    plan = optimize_action_proposals(
        (item,),
        authorization=replace(
            authorization(),
            cash_gap_penalty_rate=0.50,
        ),
        current_lots_by_symbol={},
        current_weights_by_symbol={},
        current_exposure=0.0,
        max_positions=5,
        thesis_by_symbol={item.symbol: item.thesis},
    )
    assert not plan.selected_proposal_ids
    passed("deployment-gap pressure cannot resurrect negative post-authority edge")


def verify_safety_no_trade_band() -> None:
    context = SimpleNamespace(
        execution_cost_profile={
            "scap_safety_no_trade_band": 0.015,
            "scap_safety_confirmation_days": 2,
        },
        safety=SimpleNamespace(
            risk_level="warning",
            hard_freeze_active=False,
            trigger_streak_days=2,
        ),
        decision_id="d",
        decision_date=pd.Timestamp("2025-01-10"),
        forecast_horizon_sessions=10,
        nav_amount=20_000.0,
        current_weights={"held": 0.36},
    )
    rows = {
        "held": pd.Series(
            {
                "comparable_expected_alpha": 0.01,
                "scap_estimated_total_cost_amount": 10.0,
            }
        )
    }
    proposals = []
    proposal_rows = {}
    planned = _append_exposure_cap_safety_exits(
        proposals,
        proposal_rows,
        context=context,
        rows=rows,
        current_weights={"held": 0.36},
        current_lots={"held": 1},
        current_exposure=0.36,
        strategic_budget=0.35,
    )
    assert planned == 0.0
    assert not proposals
    planned = _append_exposure_cap_safety_exits(
        proposals,
        proposal_rows,
        context=context,
        rows=rows,
        current_weights={"held": 0.38},
        current_lots={"held": 1},
        current_exposure=0.38,
        strategic_budget=0.35,
    )
    assert planned == 0.38
    assert proposals[-1].action_type == "safety_exit"
    passed("confirmed warning uses a no-trade band before whole-lot deleveraging")


def verify_atomic_exit_releases_slot() -> None:
    exit_proposal = replace(
        proposal(
            "held_1",
            funding=2_000.0,
            robust=10.0,
            score=0.5,
            rank=1.0,
            pool="momentum",
        ),
        action_type="hard_exit",
        funding_cash_amount=0.0,
        buy_cash_required_amount=0.0,
        exposure_delta=-0.20,
    )
    remaining, released, available = _available_slots_after_exits(
        current_lots={f"held_{index}": 1 for index in range(1, 6)},
        proposals=(exit_proposal,),
        max_positions=5,
    )
    assert (remaining, released, available) == (0, 1, 1)
    passed("a factual full exit releases one slot inside the atomic ActionPlan")


def verify_winner_add_does_not_consume_a_name_slot() -> None:
    current_lots = {f"held_{index}": 1 for index in range(1, 6)}
    current_weights = {symbol: 0.10 for symbol in current_lots}
    item = replace(
        proposal(
            "held_1",
            funding=2_000.0,
            robust=60.0,
            score=0.95,
            rank=1.0,
            pool="momentum",
            tier="B",
        ),
        proposal_id="d|held_1|winner_add",
        action_type="winner_add",
    )
    plan = optimize_action_proposals(
        (item,),
        authorization=authorization(
            current_cash_amount=10_000.0,
            cash_buffer_amount=1_000.0,
        ),
        current_lots_by_symbol=current_lots,
        current_weights_by_symbol=current_weights,
        current_exposure=0.50,
        max_positions=5,
        thesis_by_symbol={"held_1": "momentum"},
        max_names_per_thesis=3,
    )
    assert plan.selected_proposal_ids == (item.proposal_id,)
    assert len([lots for lots in plan.target_lots_by_symbol.values() if lots > 0]) == 5
    assert plan.target_lots_by_symbol["held_1"] == 2
    passed("winner add on an existing name does not consume a sixth position slot")


def verify_unobserved_holding_state_is_carried_without_action() -> None:
    runner = SimpleNamespace(
        positions={"suspended": 100},
        holding_days={"suspended": 9},
        _last_position_mark_rows=[
            {
                "symbol": "suspended",
                "market_value": 3_000.0,
                "valuation_source": "last_known_close",
                "stale_days": 1,
            }
        ],
        position_state_rows=[
            {
                "date": pd.Timestamp("2025-01-09"),
                "symbol": "suspended",
                "held": True,
                "entry_logic_version": "mainline_v3_cabinet_native",
                "cabinet_native_final_score": 0.8,
                "hard_stop_exit": True,
            }
        ],
    )
    rows = _carried_unobserved_position_states(
        runner,
        date=pd.Timestamp("2025-01-10"),
        exposure={"nominal_nav": 20_000.0},
        observed_symbols=set(),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["state_observation_status"] == "carried_forward_missing_current_feature"
    assert row["state_source_date"] == pd.Timestamp("2025-01-09")
    assert row["valuation_source"] == "last_known_close"
    assert row["account_weight"] == 0.15
    assert row["add_allowed"] is False
    assert row["hard_stop_exit"] is False
    assert row["cabinet_native_final_score"] == 0.8
    passed("missing current feature carries known state but cannot create an action")


def verify_lifecycle_winner_permission_reaches_action_plan() -> None:
    context = SimpleNamespace(
        decision_id="d",
        forecast_horizon_sessions=10,
        current_weights={"winner": 0.15},
        nav_amount=20_000.0,
        winner_add_enabled=True,
        loser_add_enabled=False,
        per_name_structural_cap=0.60,
        cash_amount=20_000.0,
        cash_buffer_amount=2_000.0,
        decision_date=pd.Timestamp("2025-01-10"),
        execution_cost_profile={"scap_max_winner_add_layers": 1},
    )
    permitted = pd.Series(
        {
            "exit_state": False,
            "position_unrealized_return": 0.06,
            # Runtime lifecycle shape: initial buy_count=1 publishes the next
            # buy count (2) for the first winner-add decision.
            "add_layer": 2,
            "add_allowed": True,
            "add_decision_type": "winner_pyramiding",
            "winner_add_review_passed": True,
            "entry_authority_tier": "C",
            "scap_v32_current_authority_tier": "C",
            "scap_v31_max_lots": 4,
            "add_expected_net_profit_lcb": 30.0,
            "scap_estimated_total_cost_amount": 8.0,
            "entry_thesis": "momentum",
            "scap_authority_snapshot_id": "d|authority",
        }
    )
    proposals: list[ActionProposal] = []
    rows: dict[str, pd.Series] = {}
    _append_held_proposals(
        proposals,
        rows,
        context=context,
        symbol="winner",
        row=permitted,
        old_weight=0.15,
        lot_cash=3_000.0,
        lot_weight=0.15,
    )
    assert len(proposals) == 1
    assert proposals[0].action_type == "winner_add"
    assert proposals[0].authority_tier == "B"
    assert proposals[0].requested_lots == 3

    blocked = permitted.copy()
    blocked["add_allowed"] = False
    blocked["add_block_reason"] = "protecting_profit_no_add"
    proposals.clear()
    rows.clear()
    _append_held_proposals(
        proposals,
        rows,
        context=context,
        symbol="winner",
        row=blocked,
        old_weight=0.15,
        lot_cash=3_000.0,
        lot_weight=0.15,
    )
    assert not proposals
    passed("lifecycle winner permission is neither dropped nor bypassed")


if __name__ == "__main__":
    verify_pool_deduplication()
    verify_price_scale_does_not_override_score()
    verify_multiple_c_names_are_feasible()
    verify_gap_cannot_resurrect_negative_edge()
    verify_safety_no_trade_band()
    verify_atomic_exit_releases_slot()
    verify_winner_add_does_not_consume_a_name_slot()
    verify_unobserved_holding_state_is_carried_without_action()
    verify_lifecycle_winner_permission_reaches_action_plan()
    print("SCAP-V3.2 aggressive contract verification passed.")
