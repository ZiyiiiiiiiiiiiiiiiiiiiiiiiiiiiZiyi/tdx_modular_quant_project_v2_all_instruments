"""Cabinet-native candidate policy for governance mainline v3."""
from __future__ import annotations

import pandas as pd

from functions.decision_council.candidate_pool_contract import (
    CANDIDATE_POOL_CONTRACT_VERSION,
    select_feasible_candidate_pool,
)

from config import ALLOW_BSE_MARKET, ALLOW_STAR_MARKET
from functions.decision_council.mainline_v2 import MAINLINE_V3_VERSIONS
from functions.decision_council.scap_v2_contracts import validate_score_columns
from functions.decision_council.small_capital_aggressive import (
    attach_scap_candidate_utility,
)
from functions.execution.security_trading_rules import permission_allows, trading_rule_for


MAINLINE_V3 = "mainline_v3_cabinet_native"


def _pre_slot_qualified_mask(
    *,
    eligible: pd.Series,
    is_held: pd.Series,
    score: pd.Series,
    use_scap_candidate_utility: bool,
) -> pd.Series:
    """Apply every optimizer qualification except its position-slot limit."""
    qualified = eligible.fillna(False).astype(bool) & ~is_held.fillna(False).astype(bool)
    if bool(use_scap_candidate_utility):
        qualified &= pd.to_numeric(score, errors="coerce").gt(0.0)
    return qualified


def apply_mainline_v3_entry_policy(
    candidates: pd.DataFrame,
    *,
    max_new_candidates: int | None = None,
    available_cash: float | None = None,
    nominal_nav: float | None = None,
    min_cash_buffer: float = 0.0,
    max_single_position_weight: float = 1.0,
    held_symbols=(),
    lot_size: int = 100,
    estimated_cost_rate: float = 0.002,
    decision_date=None,
    strategy_logic_version: str = MAINLINE_V3,
    ranking_score_column: str = "cabinet_native_final_score",
    ranking_coverage_column: str = "cabinet_strict_entry_score_coverage",
    use_scap_candidate_utility: bool = False,
    scap_single_position_soft_cap: float = 0.25,
    scap_candidate_minimum_commission: float = 5.0,
    scap_candidate_reward_basis: str = "lcb",
    selection_enabled: bool = True,
    scap_candidate_pool_limit: int = 32,
    scap_candidate_pool_per_thesis: int = 2,
) -> pd.DataFrame:
    """Use cabinet-native ranking while preserving only factual/state hard vetoes."""
    if candidates is None or candidates.empty:
        return candidates
    required = {
        "cabinet_native_final_score",
        "cabinet_base_entry_score",
        "cabinet_timing_score",
        "cabinet_liquidity_health_score",
        "cabinet_risk_safety_score",
    }
    missing = sorted(required - set(candidates.columns))
    if missing:
        raise ValueError(f"mainline v3 candidates are missing cabinet-native scores: {missing}")
    version = str(strategy_logic_version or MAINLINE_V3).strip().lower()
    if version not in MAINLINE_V3_VERSIONS:
        raise ValueError(f"mainline v3 policy received incompatible version: {version}")
    if ranking_score_column not in candidates.columns:
        raise ValueError(f"mainline v3 ranking score is missing: {ranking_score_column}")
    if ranking_coverage_column not in candidates.columns:
        raise ValueError(f"mainline v3 ranking coverage is missing: {ranking_coverage_column}")
    data = candidates.copy()
    data["strategy_logic_version"] = version
    previous = data.get("entry_confirmed", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    ranking_score = pd.to_numeric(data[ranking_score_column], errors="coerce")
    score = ranking_score
    exit_state = data.get("exit_state", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    state = data.get("position_state", pd.Series("", index=data.index)).fillna("").astype(str).str.lower()
    # Legacy lifecycle uses ``blocked`` for candidates that merely missed the
    # old entry matrix. V3 must be allowed to re-evaluate those rows. Exiting,
    # profit protection and cooldown remain genuine lifecycle hard states.
    hard_state_block = exit_state | state.isin({"exiting", "protecting_profit", "cooldown"})
    ranking_coverage = pd.to_numeric(
        data.get(ranking_coverage_column, pd.Series(0.0, index=data.index)),
        errors="coerce",
    ).fillna(0.0)
    held = {str(symbol) for symbol in held_symbols}
    is_held = data["symbol"].astype(str).isin(held)
    data["lifecycle_held_row"] = is_held
    price = pd.to_numeric(
        data.get("close_nominal", data.get("close", pd.Series(float("nan"), index=data.index))),
        errors="coerce",
    )
    del lot_size  # board-specific minimum quantities supersede the legacy global lot size
    minimum_buy_quantity = data["symbol"].astype(str).map(
        lambda symbol: trading_rule_for(symbol, trade_date=decision_date).minimum_buy_quantity
    )
    permission_feasible = data["symbol"].astype(str).map(
        lambda symbol: permission_allows(
            symbol,
            allow_star_market=ALLOW_STAR_MARKET,
            allow_bse_market=ALLOW_BSE_MARKET,
        )
    )
    data["mainline_v3_minimum_buy_quantity"] = minimum_buy_quantity
    data["mainline_v3_market_permission_feasible"] = permission_feasible
    one_lot_market_notional = price * minimum_buy_quantity
    one_lot_cash = one_lot_market_notional * (1.0 + max(float(estimated_cost_rate), 0.0))
    data["mainline_v3_one_lot_market_notional"] = one_lot_market_notional
    data["mainline_v3_one_lot_cash_required"] = one_lot_cash
    if nominal_nav is not None and float(nominal_nav) > 0.0:
        one_lot_weight = one_lot_cash / float(nominal_nav)
    else:
        one_lot_weight = pd.Series(0.0, index=data.index)
    data["mainline_v3_one_lot_weight"] = one_lot_weight
    structural_lot_feasible = (
        price.gt(0.0)
        & permission_feasible
        & one_lot_weight.le(float(max_single_position_weight) + 1e-12)
    )
    cash_feasible = pd.Series(True, index=data.index)
    if available_cash is not None:
        cash_feasible = one_lot_cash.le(
            max(float(available_cash) - float(min_cash_buffer), 0.0) + 1e-12
        )
    lot_feasible = structural_lot_feasible & cash_feasible
    lot_feasible |= is_held
    data["mainline_v3_lot_feasible"] = lot_feasible
    # Replacement challengers are evaluated against post-sale cash later.  A
    # full account therefore must not erase them merely because current cash
    # or free position slots are zero.
    data["mainline_v3_replacement_feasible"] = structural_lot_feasible | is_held
    if bool(use_scap_candidate_utility):
        data = attach_scap_candidate_utility(
            data,
            alpha_score_column=ranking_score_column,
            available_cash=available_cash,
            nominal_nav=nominal_nav,
            min_cash_buffer=min_cash_buffer,
            single_position_soft_cap=scap_single_position_soft_cap,
            single_position_hard_cap=max_single_position_weight,
            candidate_minimum_commission=scap_candidate_minimum_commission,
            estimated_round_trip_variable_rate=2.0 * max(float(estimated_cost_rate), 0.0),
            candidate_reward_basis=scap_candidate_reward_basis,
        )
        decision_utility = pd.to_numeric(data["scap_candidate_utility"], errors="coerce")
        data["scap_decision_utility_amount"] = decision_utility
    else:
        decision_utility = ranking_score
    structural_eligible = (
        decision_utility.notna() & ranking_coverage.gt(0.0) & ~hard_state_block
        & (structural_lot_feasible | is_held)
    )
    eligible = structural_eligible & lot_feasible
    raw_signal = (
        decision_utility.notna()
        & ranking_coverage.gt(0.0)
        & ~hard_state_block
        & ~is_held
    )
    if bool(use_scap_candidate_utility):
        raw_signal &= decision_utility.gt(0.0)
    structural_signal = raw_signal & structural_lot_feasible
    cash_signal = structural_signal & cash_feasible
    data["mainline_v3_raw_signal"] = raw_signal
    data["mainline_v3_structural_feasible"] = structural_signal
    data["mainline_v3_cash_feasible"] = cash_signal
    data["replacement_challenger_eligible"] = structural_eligible & ~is_held
    data["mainline_v3_score_authority"] = str(ranking_score_column)
    data["mainline_v3_score_authority_version"] = "single_final_score_v1"
    data["entry_alpha_score"] = data["cabinet_base_entry_score"]
    data["entry_timing_score"] = data["cabinet_timing_score"]
    data["entry_liquidity_score"] = data["cabinet_liquidity_health_score"]
    # Ranking fields remain dimensionless scores.  Monetary SCAP utility has
    # its own ``*_amount`` authority and must never overwrite this 0-1 chain.
    score = ranking_score.clip(lower=0.0, upper=1.0)
    data["entry_matrix_score"] = score
    data["final_entry_score"] = score
    data["primary_score"] = score
    data["score_contract_version"] = "scap_v2_contracts_v1"
    data["entry_score_unit"] = "dimensionless_0_1"
    data["scap_decision_utility_unit"] = "cny_amount"
    validate_score_columns(data)
    data["state_machine_role_pass"] = ~hard_state_block
    data["state_machine_role_block_reason"] = "cabinet_native_roles_are_continuous"
    data.loc[hard_state_block, "state_machine_role_block_reason"] = "position_state_hard_block"
    data["mainline_v3_selection_evaluated"] = bool(selection_enabled)
    if not bool(selection_enabled):
        data = data.sort_values(
            ["primary_score", "symbol"], ascending=[False, True]
        ).reset_index(drop=True)
        data["candidate_rank"] = range(1, len(data) + 1)
        return data
    selected = pd.Series(False, index=data.index)
    cash_budget = float(available_cash) if available_cash is not None else float("inf")
    remaining_cash = max(cash_budget - float(min_cash_buffer), 0.0)
    runtime_candidate_cap = (
        int(max_new_candidates)
        if max_new_candidates is not None
        else int(data["symbol"].astype(str).nunique())
    )
    remaining_slots = max(max(runtime_candidate_cap, 0) - len(held), 0)
    data["mainline_v3_slot_feasible"] = cash_signal & bool(remaining_slots > 0)
    selected_index = []
    if bool(use_scap_candidate_utility):
        # This is the sole financial-feasibility and computational-compression
        # contract.  Lean must consume this result and may not reselect from the
        # unfiltered table.
        selected_index, factual_pool, positive_pool = select_feasible_candidate_pool(
            data,
            limit=max(int(scap_candidate_pool_limit), 1),
            per_pool_reserve=max(int(scap_candidate_pool_per_thesis), 1),
        )
        data["scap_action_candidate"] = data.index.isin(selected_index)
        data["scap_candidate_pool_factual_feasible"] = factual_pool.reindex(
            data.index, fill_value=False
        )
        data["scap_candidate_pool_positive_feasible"] = positive_pool.reindex(
            data.index, fill_value=False
        )
        data["scap_candidate_pool_contract_version"] = (
            CANDIDATE_POOL_CONTRACT_VERSION
        )
        data["scap_optimizer_selected"] = False
        data["scap_optimizer_objective"] = pd.NA
        data["scap_optimizer_candidate_pool_size"] = int(positive_pool.sum())
        data["scap_optimizer_status"] = "authoritative_feasible_pool_only"
    else:
        for index in score[eligible & ~is_held].sort_values(ascending=False).index:
            if len(selected_index) >= remaining_slots:
                break
            required_cash = float(one_lot_cash.loc[index])
            if required_cash > remaining_cash + 1e-12:
                continue
            selected_index.append(index)
            remaining_cash -= required_cash
    selected.loc[selected_index] = True

    if "target_weight" in data.columns:
        data["pre_v3_target_weight"] = pd.to_numeric(data["target_weight"], errors="coerce")
        data["target_weight"] = 0.0
    data["pre_v3_entry_confirmed"] = previous
    data["mainline_v3_eligible"] = eligible
    # This is deliberately captured before the remaining-position-slot limit.
    # It separates "the signal qualified" from "the optimizer could allocate a
    # new slot", which are different facts for exposure diagnostics.
    pre_slot_qualified = structural_signal
    data["mainline_v3_pre_slot_qualified"] = pre_slot_qualified
    data["mainline_v3_remaining_slot_count"] = int(remaining_slots)
    data["mainline_v3_entry_confirmed"] = selected
    data["mainline_v3_changed_decision"] = previous.ne(selected)
    data["entry_confirmed"] = selected
    data["direct_buy_flag"] = selected
    data["candidate_state"] = "eligible_not_selected"
    data.loc[~eligible, "candidate_state"] = "ineligible"
    data.loc[selected, "candidate_state"] = "entry_selected"
    data["entry_block_reason"] = "mainline_v3_rank_below_cutoff"
    missing_coverage_reason = (
        "mainline_v3_strict_entry_unavailable"
        if ranking_coverage_column == "cabinet_strict_entry_score_coverage"
        else "mainline_v3_ranking_evidence_unavailable"
    )
    data.loc[ranking_coverage.le(0.0), "entry_block_reason"] = missing_coverage_reason
    data.loc[~lot_feasible & ~is_held, "entry_block_reason"] = "mainline_v3_one_lot_infeasible"
    data.loc[~permission_feasible & ~is_held, "entry_block_reason"] = "mainline_v3_market_permission"
    data.loc[hard_state_block, "entry_block_reason"] = "mainline_v3_position_state"
    if remaining_slots <= 0:
        data.loc[
            data["mainline_v3_pre_slot_qualified"] & ~selected,
            "entry_block_reason",
        ] = "mainline_v3_no_remaining_slot"
    data.loc[selected, "entry_block_reason"] = "confirmed"
    # ``entry_size_tier`` is produced by the legacy confirmation matrix and may
    # contain ``blocked`` even after cabinet-native V3 has selected the row.
    # Keeping that value makes the downstream order policy silently reapply the
    # legacy soft veto.  V3 sizing is deliberately deterministic: every new
    # selected entry starts with exactly one lot.
    data.loc[selected, "entry_size_tier"] = "starter_1_lot"
    data.loc[selected, "planned_entry_lots"] = 1
    # A selected candidate is not a position until a buy fill exists.  Keep a
    # separate candidate state and reserve position lifecycle states for held
    # inventory only.
    data.loc[selected & ~is_held, "position_state"] = "flat"
    data = data.sort_values(["primary_score", "symbol"], ascending=[False, True]).reset_index(drop=True)
    data["candidate_rank"] = range(1, len(data) + 1)
    return data
