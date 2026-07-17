"""Versioned candidate policy for the experimental governance mainline v2."""
from __future__ import annotations

import pandas as pd


PRODUCTION_V1 = "production_v1"
MAINLINE_V2 = "mainline_v2"
MAINLINE_V3 = "mainline_v3_cabinet_native"
STRATEGY_LOGIC_VERSIONS = (PRODUCTION_V1, MAINLINE_V2, MAINLINE_V3)


def normalize_strategy_logic_version(value: str | None) -> str:
    version = str(value or PRODUCTION_V1).strip().lower()
    if version not in STRATEGY_LOGIC_VERSIONS:
        raise ValueError(f"Invalid strategy_logic_version={version!r}; expected {STRATEGY_LOGIC_VERSIONS}")
    return version


def apply_mainline_v2_entry_policy(
    candidates: pd.DataFrame,
    *,
    risk_level: str,
    max_new_candidates: int = 5,
) -> pd.DataFrame:
    """Replace overlapping soft gates with one ranked decision, preserving hard vetoes."""
    if candidates is None or candidates.empty:
        return candidates
    data = candidates.copy()
    previous = data.get("entry_confirmed", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    role_pass = data.get("state_machine_role_pass", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    liquidity = pd.to_numeric(data.get("entry_liquidity_score", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
    matrix = pd.to_numeric(data.get("entry_matrix_score", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
    final_score = pd.to_numeric(data.get("final_entry_score", matrix), errors="coerce").fillna(matrix)
    ranked_score = final_score + role_pass.astype(float) * 0.05
    exit_state = data.get("exit_state", pd.Series(False, index=data.index)).fillna(False).astype(bool)
    state = data.get("position_state", pd.Series("", index=data.index)).fillna("").astype(str).str.lower()
    hard_state_block = exit_state | state.isin({"blocked", "exiting", "protecting_profit"})
    market_hard_block = str(risk_level or "").lower() in {"high", "crisis"}
    # Role diversity is supporting evidence in V2, not another hard admission
    # gate. Liquidity, minimum alpha matrix, account state and hard market risk
    # retain exclusive veto ownership.
    eligible = liquidity.ge(0.20) & matrix.ge(0.30) & ~hard_state_block
    if market_hard_block:
        eligible &= False
    selected = pd.Series(False, index=data.index)
    eligible_index = ranked_score[eligible].sort_values(ascending=False).head(max(int(max_new_candidates), 1)).index
    selected.loc[eligible_index] = True
    data["production_v1_entry_confirmed"] = previous
    # Legacy Kelly sizing can be effectively zero when calibration is immature.
    # Keep it for comparison, but do not let it become V2's requested portfolio
    # weight. The portfolio constructor will allocate selected names from the
    # authorized account exposure when target_weight has no positive request.
    if "target_weight" in data.columns:
        data["production_v1_target_weight"] = pd.to_numeric(data["target_weight"], errors="coerce")
        data["target_weight"] = 0.0
    data["mainline_v2_eligible"] = eligible
    data["mainline_v2_ranked_score"] = ranked_score
    data["mainline_v2_role_support"] = role_pass
    data["mainline_v2_entry_confirmed"] = selected
    data["mainline_v2_changed_decision"] = previous.ne(selected)
    data["entry_confirmed"] = selected
    data["entry_block_reason"] = "mainline_v2_rank_below_cutoff"
    data.loc[liquidity.lt(0.20), "entry_block_reason"] = "mainline_v2_hard_liquidity"
    data.loc[matrix.lt(0.30), "entry_block_reason"] = "mainline_v2_matrix_floor"
    data.loc[hard_state_block, "entry_block_reason"] = "mainline_v2_position_state"
    if market_hard_block:
        data["entry_block_reason"] = "mainline_v2_market_hard_risk"
    data.loc[selected, "entry_block_reason"] = "confirmed"
    return data


def calibration_runtime_state(*, matured_sample_count: int, day_index: int, degraded: bool = False) -> str:
    if degraded:
        return "degraded"
    samples = max(int(matured_sample_count), 0)
    if int(day_index) < 10 or samples < 20:
        return "cold_start"
    if samples < 80:
        return "warming_up"
    return "calibrated"
