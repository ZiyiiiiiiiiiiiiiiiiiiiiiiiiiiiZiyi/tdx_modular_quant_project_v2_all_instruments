"""Pure SCAP-V1 policy helpers.

This module contains no order execution or accounting.  It only derives
auditable research targets so the existing execution engine remains the
single source of truth.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations

import pandas as pd

from functions.decision_council.action_utility import (
    ACTION_UTILITY_CONTRACT_VERSION,
    build_incremental_action_utility,
    round_trip_cost_amount,
)


SCAP_VERSION = "small_capital_aggressive_profit_v1"
SCAP_CONTROL_MODE = "aggressive_profit"
SCAP_EXIT_STAGE_ORDER = {"E0": 0, "E1": 1, "E2": 2, "E3": 3, "E4": 4}
SCAP_CONTROL_MIN_STAGE = {
    # Cooldown is part of the E1 signal-failure lifecycle.  Registering a
    # cooldown while disabling its entry gate created immediate re-entry.
    "cooldown": 1,
    "signal_failure_exit": 1,
    "stale_exit": 2,
    "post_entry_failure_exit": 2,
    "loss_containment_exit": 3,
    "profit_giveback_exit": 4,
    "hard_stop_exit": 4,
}
SCAP_DISABLED_CONTROLS = frozenset(
    {"reputation", "regime", "regime_overlay"}
)


def _clip01(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def scap_exit_stage_level(value: str) -> int:
    stage = str(value or "E0").strip().upper()
    if stage not in SCAP_EXIT_STAGE_ORDER:
        raise ValueError(f"Unknown SCAP exit stage: {value}")
    return SCAP_EXIT_STAGE_ORDER[stage]


def scap_control_enabled(*, exit_stage: str, control_name: str) -> bool:
    """Return the registered E0-E4 permission for one lifecycle control."""
    stage = scap_exit_stage_level(exit_stage)
    control = str(control_name or "").strip().lower()
    if control in SCAP_DISABLED_CONTROLS:
        return False
    if control not in SCAP_CONTROL_MIN_STAGE:
        raise ValueError(f"Unknown SCAP control: {control_name}")
    return stage >= SCAP_CONTROL_MIN_STAGE[control]


def build_scap_exit_stage_contract(
    current_stage: str,
    *,
    active_replacement_enabled: bool = False,
    loser_averaging_enabled: bool = False,
    winner_pyramiding_enabled: bool = False,
) -> pd.DataFrame:
    """Return the preregistered one-variable E0-E4 experiment matrix."""
    current = str(current_stage or "E0").strip().upper()
    scap_exit_stage_level(current)
    rows = []
    for stage in SCAP_EXIT_STAGE_ORDER:
        row = {
            "scap_version": SCAP_VERSION,
            "exit_stage": stage,
            "stage_level": SCAP_EXIT_STAGE_ORDER[stage],
            "is_current_stage": stage == current,
            "reputation_enabled": False,
            "regime_enabled": False,
            "regime_overlay_enabled": False,
            "active_replacement_enabled": bool(active_replacement_enabled),
            "loser_averaging_enabled": bool(loser_averaging_enabled),
            "winner_pyramiding_enabled": bool(winner_pyramiding_enabled),
            "experiment_contract": (
                "exit permissions are cumulative through the selected stage; "
                "action modules share unified_position_action_v1; controlled "
                "economic attribution still requires matched runtime identity"
            ),
        }
        for control in SCAP_CONTROL_MIN_STAGE:
            row[f"{control}_enabled"] = scap_control_enabled(
                exit_stage=stage, control_name=control
            )
        rows.append(row)
    return pd.DataFrame(rows)


def scap_loss_containment_exit(
    *,
    exit_stage: str,
    is_held: bool,
    holding_days: int,
    net_unrealized_return: float,
    loss_stop: float,
) -> bool:
    return bool(
        scap_control_enabled(exit_stage=exit_stage, control_name="loss_containment_exit")
        and bool(is_held)
        and int(holding_days) >= 3
        and float(net_unrealized_return) <= float(loss_stop)
    )


def desired_exposure_from_signal_count(
    *,
    actual_exposure: float,
    qualified_entry_count: int,
) -> float:
    """Return the pre-risk desired exposure without forcing deployment."""
    actual = _clip01(actual_exposure)
    count = max(int(qualified_entry_count), 0)
    if count <= 0:
        target = actual
    elif count == 1:
        target = 0.40
    elif count == 2:
        target = 0.70
    elif count == 3:
        target = 0.90
    else:
        target = 0.95
    return _clip01(max(actual, target))


@dataclass(frozen=True)
class ScapExposureTargets:
    risk_exposure_ceiling: float
    desired_exposure_target: float
    executable_exposure_target: float
    signal_cash_drag: float
    lot_feasibility_drag: float
    risk_ceiling_drag: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def build_scap_exposure_targets(
    *,
    actual_exposure: float,
    authorized_risk_ceiling: float,
    feasible_increment: float,
    qualified_entry_count: int,
) -> ScapExposureTargets:
    """Separate risk, desired, and executable exposure without circular overwrite."""
    actual = _clip01(actual_exposure)
    risk = _clip01(authorized_risk_ceiling)
    unconstrained_desired = desired_exposure_from_signal_count(
        actual_exposure=actual,
        qualified_entry_count=qualified_entry_count,
    )
    desired = min(unconstrained_desired, risk)
    executable_capacity = _clip01(actual + max(float(feasible_increment), 0.0))
    executable = min(desired, executable_capacity)
    return ScapExposureTargets(
        risk_exposure_ceiling=risk,
        desired_exposure_target=desired,
        executable_exposure_target=executable,
        signal_cash_drag=max(risk - unconstrained_desired, 0.0),
        lot_feasibility_drag=max(desired - executable, 0.0),
        risk_ceiling_drag=max(unconstrained_desired - risk, 0.0),
    )


def attach_scap_candidate_utility(
    candidates: pd.DataFrame,
    *,
    alpha_score_column: str,
    available_cash: float | None,
    nominal_nav: float | None,
    min_cash_buffer: float,
    single_position_soft_cap: float = 0.25,
    single_position_hard_cap: float = 0.40,
    candidate_minimum_commission: float = 5.0,
    estimated_round_trip_variable_rate: float = 0.002,
    candidate_reward_basis: str = "lcb",
) -> pd.DataFrame:
    """Attach comparable one-lot net-profit LCB without deleting candidates."""
    if candidates is None or candidates.empty:
        return candidates
    if alpha_score_column not in candidates.columns:
        raise ValueError(f"SCAP alpha score is missing: {alpha_score_column}")
    data = candidates.copy()
    alpha = pd.to_numeric(data[alpha_score_column], errors="coerce")
    data["scap_alpha_percentile"] = alpha.rank(pct=True).fillna(0.0)
    one_lot_cash = pd.to_numeric(
        data.get("mainline_v3_one_lot_cash_required", pd.Series(0.0, index=data.index)),
        errors="coerce",
    ).fillna(0.0)
    if nominal_nav is not None and float(nominal_nav) > 0.0:
        one_lot_weight = one_lot_cash / float(nominal_nav)
    else:
        one_lot_weight = pd.Series(0.0, index=data.index)
    soft_cap = _clip01(single_position_soft_cap)
    hard_cap = max(_clip01(single_position_hard_cap), soft_cap + 1e-12)
    data["scap_concentration_penalty"] = (
        (one_lot_weight - soft_cap).clip(lower=0.0) / (hard_cap - soft_cap)
    ).clip(0.0, 1.0)
    notional = one_lot_cash.clip(lower=0.0)
    fixed_round_trip = 2.0 * max(float(candidate_minimum_commission), 0.0)
    estimated_cost_rate = (
        float(estimated_round_trip_variable_rate)
        + fixed_round_trip / notional.where(notional > 0.0)
    ).replace([float("inf"), float("-inf")], pd.NA).fillna(1.0)
    data["scap_estimated_round_trip_cost_rate"] = estimated_cost_rate
    data["scap_cost_penalty"] = estimated_cost_rate.rank(pct=True).fillna(1.0)
    vol = pd.to_numeric(data.get("volatility_20", pd.Series(pd.NA, index=data.index)), errors="coerce")
    vol_penalty = vol.rank(pct=True).fillna(0.5)
    amount = pd.to_numeric(data.get("amount_ma20", data.get("amount", pd.Series(0.0, index=data.index))), errors="coerce").fillna(0.0)
    liquidity_penalty = 1.0 - amount.rank(pct=True).fillna(0.0)
    ret5 = pd.to_numeric(data.get("ret_5", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
    ret20 = pd.to_numeric(data.get("ret_20", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
    decline_penalty = (
        ((-0.03 - ret5).clip(lower=0.0) / 0.10)
        + ((-0.05 - ret20).clip(lower=0.0) / 0.20)
    ).clip(0.0, 1.0)
    data["scap_soft_quality_penalty"] = (
        0.35 * vol_penalty + 0.30 * liquidity_penalty + 0.35 * decline_penalty
    ).clip(0.0, 1.0)
    median_lot_cash = float(one_lot_cash[one_lot_cash > 0.0].median()) if bool((one_lot_cash > 0.0).any()) else 0.0
    spendable_cash = max(float(available_cash or 0.0) - float(min_cash_buffer), 0.0)
    residual = (spendable_cash - one_lot_cash).clip(lower=0.0)
    if median_lot_cash > 0.0:
        fragment = ((median_lot_cash - residual).clip(lower=0.0) / median_lot_cash).where(
            residual.gt(0.0),
            0.0,
        )
    else:
        fragment = pd.Series(0.0, index=data.index)
    data["scap_cash_fragment_penalty"] = fragment.clip(0.0, 1.0)
    data["scap_overlap_penalty"] = 0.0
    data["scap_overlap_penalty_state"] = "portfolio_optimizer_pending"
    expected_point = pd.to_numeric(
        data.get("comparable_expected_alpha", pd.Series(pd.NA, index=data.index)),
        errors="coerce",
    )
    expected_lcb = pd.to_numeric(
        data.get("comparable_alpha_lcb", pd.Series(pd.NA, index=data.index)),
        errors="coerce",
    )
    authority_tier = data.get(
        "scap_v31_authority_tier", pd.Series("", index=data.index)
    ).fillna("").astype(str).str.upper()
    authority_return = pd.to_numeric(
        data.get(
            "scap_v31_decision_expected_return",
            pd.Series(pd.NA, index=data.index),
        ),
        errors="coerce",
    )
    tier_authorized = authority_tier.isin({"A", "B", "C"})
    expected_lcb = expected_lcb.where(~tier_authorized, authority_return)
    horizon = pd.to_numeric(
        data.get("comparable_value_horizon_days", pd.Series(10, index=data.index)),
        errors="coerce",
    ).fillna(10).clip(lower=1)
    calibration_state_column = "entry_calibration_state_10d"
    authority_column = "forecast_authority_weight_10d"
    if calibration_state_column in data.columns:
        calibration_state = (
            data[calibration_state_column].fillna("insufficient").astype(str).str.lower()
        )
    else:
        calibration_state = (
            data.get(
                "comparable_value_state",
                pd.Series("insufficient", index=data.index),
            )
            .fillna("insufficient")
            .astype(str)
            .str.lower()
        )
    if authority_column in data.columns:
        forecast_authority = pd.to_numeric(
            data[authority_column], errors="coerce"
        ).fillna(0.0).clip(0.0, 1.0)
    else:
        # Compatibility forecasts may be used only when they explicitly call
        # themselves calibrated. Missing state no longer implies authority.
        forecast_authority = calibration_state.eq("calibrated").astype(float)
    data["scap_forecast_authority_weight"] = forecast_authority
    data["scap_utility_calibration_state"] = calibration_state.where(
        forecast_authority.gt(0.0),
        "prior_only",
    )
    data.loc[authority_tier.isin({"A", "B"}), "scap_utility_calibration_state"] = (
        "calibrated"
    )
    data.loc[authority_tier.eq("C"), "scap_utility_calibration_state"] = (
        "pit_fallback_authorized"
    )
    missing_return = expected_point.isna() | expected_lcb.isna()
    data.loc[missing_return, "scap_utility_calibration_state"] = "insufficient"
    data["scap_utility_baseline_action"] = "hold_cash"
    utility_rows = []
    for idx, row in data.iterrows():
        shares = pd.to_numeric(
            pd.Series([row.get("mainline_v3_minimum_buy_quantity", 100)]),
            errors="coerce",
        ).fillna(100.0).iloc[0]
        price = (
            float(one_lot_cash.loc[idx]) / max(float(shares), 1.0)
            if float(one_lot_cash.loc[idx]) > 0.0
            else 0.0
        )
        total_cost = round_trip_cost_amount(
            symbol=str(row.get("symbol", "")),
            price=price,
            shares=float(shares),
        )
        # Concentration and tail evidence are converted to an explicit cash
        # risk budget. They are not also used as hard entry vetoes here.
        risk_penalty = float(notional.loc[idx]) * (
            0.0025 * float(data.at[idx, "scap_concentration_penalty"])
            + 0.0025 * float(data.at[idx, "scap_soft_quality_penalty"])
        )
        reward_basis = (
            "lcb"
            if str(row.get("scap_v31_authority_tier", "")).upper()
            in {"A", "B", "C"}
            else candidate_reward_basis
        )
        utility_rows.append(
            build_incremental_action_utility(
                action_type="new_entry",
                notional=float(notional.loc[idx]),
                expected_return_point=expected_point.loc[idx],
                expected_return_lcb=expected_lcb.loc[idx],
                estimated_total_cost=total_cost,
                horizon_days=int(horizon.loc[idx]),
                risk_penalty_amount=risk_penalty,
                calibration_state=str(data.at[idx, "scap_utility_calibration_state"]),
                decision_return_basis=reward_basis,
                proposal_id=f"entry|{row.get('symbol', '')}",
            ).as_dict()
        )
    utility_frame = pd.DataFrame(utility_rows, index=data.index)
    data["scap_expected_return_point"] = utility_frame["expected_return_point"]
    data["scap_expected_return_lcb"] = utility_frame["expected_return_lcb"]
    data["scap_decision_expected_return"] = utility_frame["decision_expected_return"]
    data["scap_decision_return_basis"] = utility_frame["decision_return_basis"]
    data["scap_estimated_total_cost_amount"] = utility_frame["estimated_total_cost"]
    data["scap_risk_penalty_amount"] = utility_frame["risk_penalty_amount"]
    data["scap_baseline_terminal_wealth"] = utility_frame["baseline_terminal_wealth"]
    data["scap_action_terminal_wealth"] = utility_frame["action_terminal_wealth"]
    data["scap_candidate_utility"] = utility_frame["incremental_terminal_wealth"]
    data["scap_candidate_utility_version"] = ACTION_UTILITY_CONTRACT_VERSION
    return data


@dataclass(frozen=True)
class ScapPortfolioSelection:
    selected_indices: tuple
    objective_value: float
    candidate_pool_size: int
    residual_cash: float
    interaction_penalty: float = 0.0
    optimizer_status: str = "bounded_exact_with_interactions"


def select_scap_one_lot_portfolio(
    candidates: pd.DataFrame,
    *,
    eligible_mask: pd.Series,
    available_cash: float,
    min_cash_buffer: float,
    remaining_slots: int,
    utility_column: str = "scap_candidate_utility",
    cash_column: str = "mainline_v3_one_lot_cash_required",
    sector_column: str = "industry",
    correlation_matrix: pd.DataFrame | None = None,
    correlation_penalty_rate: float = 0.10,
    same_sector_penalty_rate: float = 0.05,
    top_k: int = 15,
) -> ScapPortfolioSelection:
    """Search the bounded one-lot combination instead of using score greedily."""
    if candidates is None or candidates.empty or int(remaining_slots) <= 0:
        return ScapPortfolioSelection((), 0.0, 0, max(float(available_cash) - float(min_cash_buffer), 0.0))
    if utility_column not in candidates.columns or cash_column not in candidates.columns:
        raise ValueError("SCAP portfolio optimizer requires utility and one-lot cash columns")
    eligible = candidates.loc[eligible_mask].copy()
    eligible["_utility"] = pd.to_numeric(eligible[utility_column], errors="coerce")
    eligible["_cash"] = pd.to_numeric(eligible[cash_column], errors="coerce")
    eligible = eligible[
        eligible["_utility"].notna()
        & eligible["_utility"].gt(0.0)
        & eligible["_cash"].gt(0.0)
    ].copy()
    eligible = eligible.sort_values(
        ["_utility", "symbol"],
        ascending=[False, True],
    ).head(max(int(top_k), 1))
    budget = max(float(available_cash) - float(min_cash_buffer), 0.0)
    if eligible.empty or budget <= 0.0:
        return ScapPortfolioSelection((), 0.0, int(len(eligible)), budget)
    best_indices: tuple = ()
    best_objective = 0.0
    best_spend = 0.0
    best_interaction_penalty = 0.0
    index_values = tuple(eligible.index)
    max_size = min(max(int(remaining_slots), 0), len(index_values))
    for size in range(1, max_size + 1):
        for combo in combinations(index_values, size):
            chosen = eligible.loc[list(combo)]
            spend = float(chosen["_cash"].sum())
            if spend > budget + 1e-12:
                continue
            residual = budget - spend
            median_cash = float(eligible["_cash"].median())
            fragment_penalty = (
                (median_cash - residual) / median_cash
                if median_cash > 0.0 and 0.0 < residual < median_cash
                else 0.0
            )
            gross_utility = float(chosen["_utility"].sum())
            interaction_penalty = 0.0
            chosen_symbols = chosen["symbol"].astype(str).tolist()
            if correlation_matrix is not None and not correlation_matrix.empty:
                for left_index, left_symbol in enumerate(chosen_symbols):
                    for right_symbol in chosen_symbols[left_index + 1 :]:
                        if left_symbol in correlation_matrix.index and right_symbol in correlation_matrix.columns:
                            corr = pd.to_numeric(
                                pd.Series([correlation_matrix.at[left_symbol, right_symbol]]),
                                errors="coerce",
                            ).iloc[0]
                            if pd.notna(corr):
                                interaction_penalty += (
                                    max(float(corr), 0.0)
                                    * float(correlation_penalty_rate)
                                    * min(
                                        float(chosen.loc[chosen["symbol"].astype(str).eq(left_symbol), "_utility"].iloc[0]),
                                        float(chosen.loc[chosen["symbol"].astype(str).eq(right_symbol), "_utility"].iloc[0]),
                                    )
                                )
            if sector_column in chosen.columns:
                duplicate_sector_count = int(
                    chosen[sector_column].fillna("").astype(str).loc[
                        lambda values: values.ne("")
                    ].duplicated().sum()
                )
                if duplicate_sector_count:
                    interaction_penalty += (
                        float(same_sector_penalty_rate)
                        * duplicate_sector_count
                        * max(gross_utility, 0.0)
                    )
            # First compare CNY utility net of CNY interaction penalty. Cash
            # fragments are a lower-priority dimensionless tie-break only.
            objective = gross_utility - interaction_penalty
            symbols = tuple(sorted(chosen["symbol"].astype(str)))
            best_symbols = tuple(sorted(eligible.loc[list(best_indices), "symbol"].astype(str))) if best_indices else ()
            if (
                objective > best_objective + 1e-12
                or (
                    abs(objective - best_objective) <= 1e-12
                    and (
                        fragment_penalty
                        < (
                            (
                                float(eligible["_cash"].median())
                                - (budget - best_spend)
                            )
                            / float(eligible["_cash"].median())
                            if best_indices
                            and float(eligible["_cash"].median()) > 0.0
                            and 0.0 < (budget - best_spend) < float(eligible["_cash"].median())
                            else 0.0
                        )
                        - 1e-12
                        or (
                            abs(
                                fragment_penalty
                                - (
                                    (
                                        float(eligible["_cash"].median())
                                        - (budget - best_spend)
                                    )
                                    / float(eligible["_cash"].median())
                                    if best_indices
                                    and float(eligible["_cash"].median()) > 0.0
                                    and 0.0 < (budget - best_spend) < float(eligible["_cash"].median())
                                    else 0.0
                                )
                            )
                            <= 1e-12
                            and (
                                spend < best_spend - 1e-12
                                or (
                                    abs(spend - best_spend) <= 1e-12
                                    and symbols < best_symbols
                                )
                            )
                        )
                    )
                )
            ):
                best_indices = tuple(combo)
                best_objective = objective
                best_spend = spend
                best_interaction_penalty = interaction_penalty
    return ScapPortfolioSelection(
        selected_indices=best_indices,
        objective_value=float(best_objective),
        candidate_pool_size=int(len(eligible)),
        residual_cash=float(budget - best_spend),
        interaction_penalty=float(best_interaction_penalty),
    )
