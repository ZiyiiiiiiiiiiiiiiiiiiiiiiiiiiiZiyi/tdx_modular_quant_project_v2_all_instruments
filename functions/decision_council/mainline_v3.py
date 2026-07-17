"""Cabinet-native candidate policy for governance mainline v3."""
from __future__ import annotations

import pandas as pd


MAINLINE_V3 = "mainline_v3_cabinet_native"


def apply_mainline_v3_entry_policy(
    candidates: pd.DataFrame,
    *,
    max_new_candidates: int = 5,
    available_cash: float | None = None,
    nominal_nav: float | None = None,
    min_cash_buffer: float = 0.0,
    max_single_position_weight: float = 1.0,
    held_symbols=(),
    lot_size: int = 100,
    estimated_cost_rate: float = 0.002,
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
    data = candidates.copy()
    data["strategy_logic_version"] = MAINLINE_V3
    previous = data.get("entry_confirmed", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    score = pd.to_numeric(data["cabinet_native_final_score"], errors="coerce")
    exit_state = data.get("exit_state", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    state = data.get("position_state", pd.Series("", index=data.index)).fillna("").astype(str).str.lower()
    # Legacy lifecycle uses ``blocked`` for candidates that merely missed the
    # old entry matrix. V3 must be allowed to re-evaluate those rows. Exiting,
    # profit protection and cooldown remain genuine lifecycle hard states.
    hard_state_block = exit_state | state.isin({"exiting", "protecting_profit", "cooldown"})
    strict_coverage = pd.to_numeric(
        data.get("cabinet_strict_entry_score_coverage", pd.Series(0.0, index=data.index)),
        errors="coerce",
    ).fillna(0.0)
    held = {str(symbol) for symbol in held_symbols}
    is_held = data["symbol"].astype(str).isin(held)
    data["lifecycle_held_row"] = is_held
    price = pd.to_numeric(
        data.get("close_nominal", data.get("close", pd.Series(float("nan"), index=data.index))),
        errors="coerce",
    )
    one_lot_cash = price * max(int(lot_size), 1) * (1.0 + max(float(estimated_cost_rate), 0.0))
    data["mainline_v3_one_lot_cash_required"] = one_lot_cash
    if nominal_nav is not None and float(nominal_nav) > 0.0:
        one_lot_weight = one_lot_cash / float(nominal_nav)
    else:
        one_lot_weight = pd.Series(0.0, index=data.index)
    data["mainline_v3_one_lot_weight"] = one_lot_weight
    lot_feasible = price.gt(0.0) & one_lot_weight.le(float(max_single_position_weight) + 1e-12)
    if available_cash is not None:
        lot_feasible &= one_lot_cash.le(max(float(available_cash) - float(min_cash_buffer), 0.0) + 1e-12)
    lot_feasible |= is_held
    data["mainline_v3_lot_feasible"] = lot_feasible
    eligible = score.notna() & strict_coverage.gt(0.0) & ~hard_state_block & lot_feasible
    selected = pd.Series(False, index=data.index)
    cash_budget = float(available_cash) if available_cash is not None else float("inf")
    remaining_cash = max(cash_budget - float(min_cash_buffer), 0.0)
    selected_index = []
    for index in score[eligible & ~is_held].sort_values(ascending=False).index:
        required_cash = float(one_lot_cash.loc[index])
        if required_cash > remaining_cash + 1e-12:
            continue
        selected_index.append(index)
        remaining_cash -= required_cash
        if len(selected_index) >= max(int(max_new_candidates), 1):
            break
    selected.loc[selected_index] = True

    if "target_weight" in data.columns:
        data["pre_v3_target_weight"] = pd.to_numeric(data["target_weight"], errors="coerce")
        data["target_weight"] = 0.0
    data["pre_v3_entry_confirmed"] = previous
    data["mainline_v3_eligible"] = eligible
    data["mainline_v3_entry_confirmed"] = selected
    data["mainline_v3_changed_decision"] = previous.ne(selected)
    data["entry_confirmed"] = selected
    data["direct_buy_flag"] = selected
    data["entry_alpha_score"] = data["cabinet_base_entry_score"]
    data["entry_timing_score"] = data["cabinet_timing_score"]
    data["entry_liquidity_score"] = data["cabinet_liquidity_health_score"]
    data["entry_matrix_score"] = data["cabinet_native_final_score"]
    data["final_entry_score"] = data["cabinet_native_final_score"]
    data["primary_score"] = data["cabinet_native_final_score"]
    data["state_machine_role_pass"] = ~hard_state_block
    data["state_machine_role_block_reason"] = "cabinet_native_roles_are_continuous"
    data.loc[hard_state_block, "state_machine_role_block_reason"] = "position_state_hard_block"
    data["entry_block_reason"] = "mainline_v3_rank_below_cutoff"
    data.loc[strict_coverage.le(0.0), "entry_block_reason"] = "mainline_v3_strict_entry_unavailable"
    data.loc[~lot_feasible & ~is_held, "entry_block_reason"] = "mainline_v3_one_lot_infeasible"
    data.loc[hard_state_block, "entry_block_reason"] = "mainline_v3_position_state"
    data.loc[selected, "entry_block_reason"] = "confirmed"
    # ``entry_size_tier`` is produced by the legacy confirmation matrix and may
    # contain ``blocked`` even after cabinet-native V3 has selected the row.
    # Keeping that value makes the downstream order policy silently reapply the
    # legacy soft veto.  V3 sizing is deliberately deterministic: every new
    # selected entry starts with exactly one lot.
    data.loc[selected, "entry_size_tier"] = "starter_1_lot"
    data.loc[selected, "planned_entry_lots"] = 1
    data.loc[selected & state.isin({"", "watching", "candidate", "blocked"}), "position_state"] = "building"
    data = data.sort_values(["primary_score", "symbol"], ascending=[False, True]).reset_index(drop=True)
    data["candidate_rank"] = range(1, len(data) + 1)
    return data
