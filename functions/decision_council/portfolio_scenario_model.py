"""Incremental portfolio scenario-risk model for SCAP.

The optimizer compares every proposed trade set with the factual hold/no-trade
baseline.  All outputs are CNY amounts.  This module deliberately has no order
or execution authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable

import pandas as pd

from functions.decision_council.scap_v2_contracts import ActionProposal


INCREMENTAL_SCENARIO_CONTRACT_VERSION = "scap_incremental_scenario_cvar_v2_single_risk_charge"


@dataclass(frozen=True)
class IncrementalScenarioRisk:
    hold_baseline_objective_amount: float
    incremental_expected_wealth_amount: float
    incremental_robust_wealth_amount: float
    incremental_cvar_amount: float
    model_uncertainty_amount: float
    scenario_risk_penalty_amount: float
    evidence_name_count: int
    evidence_state: str
    dependence_assumption: float
    risk_measure_name: str = "correlated_tail_loss_proxy"
    joint_scenario_count: int = 0
    contract_version: str = INCREMENTAL_SCENARIO_CONTRACT_VERSION

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate_incremental_scenario_risk(
    selected: Iterable[ActionProposal],
    *,
    covariance_matrix: pd.DataFrame | None = None,
    scenario_return_matrix: pd.DataFrame | None = None,
    correlation_floor: float = 0.35,
    cvar_confidence: float = 0.95,
    cvar_risk_aversion: float = 0.05,
    model_uncertainty_risk_aversion: float = 0.10,
    warming_effective_samples: int = 30,
    mature_effective_samples: int = 100,
    minimum_joint_scenarios: int = 30,
) -> IncrementalScenarioRisk:
    """Return conservative incremental risk relative to the no-trade plan.

    Proposal downside CVaR is aggregated with a constant-correlation bound.
    When a complete covariance block is available its average absolute
    correlation may increase, but never reduce, the conservative floor.
    The confidence parameter is part of the immutable contract even though
    proposal CVaR is already expressed at that tail confidence.
    """
    items = tuple(selected)
    buys = tuple(item for item in items if _is_buy_action(item.action_type))
    expected = sum(float(item.expected_net_profit_amount) for item in items)
    robust = sum(
        float(item.robust_net_profit_amount)
        - max(float(item.authority_penalty_amount), 0.0)
        for item in items
    )
    warming_min = max(int(warming_effective_samples), 1)
    mature_min = max(int(mature_effective_samples), warming_min)
    warming_evidence = tuple(
        item
        for item in buys
        if bool(item.coverage_evidence_authorized)
        and float(item.calibration_effective_sample_size) >= warming_min
    )
    mature_evidence = tuple(
        item
        for item in warming_evidence
        if float(item.calibration_effective_sample_size) >= mature_min
    )
    dependence = _dependence_assumption(
        tuple(item.symbol for item in buys),
        covariance_matrix,
        floor=correlation_floor,
    )
    joint_cvar, joint_count = _joint_scenario_cvar(
        buys,
        scenario_return_matrix,
        confidence=cvar_confidence,
        minimum_scenarios=minimum_joint_scenarios,
    )
    if joint_cvar is not None:
        cvar_amount = float(joint_cvar)
        risk_measure_name = "joint_historical_scenario_cvar"
    else:
        tail_losses = [max(float(item.downside_cvar_amount), 0.0) for item in buys]
        sum_sq = sum(value * value for value in tail_losses)
        sum_loss = sum(tail_losses)
        cvar_amount = math.sqrt(
            max((1.0 - dependence) * sum_sq + dependence * sum_loss * sum_loss, 0.0)
        )
        risk_measure_name = "correlated_tail_loss_proxy"
    uncertainty_terms = []
    for item in buys:
        if str(item.decision_return_basis).strip().lower() == "lcb":
            # LCB already contains the forecast-uncertainty haircut.
            uncertainty_terms.append(0.0)
            continue
        forecast_gap = max(
            float(item.expected_net_profit_amount)
            - float(item.robust_net_profit_amount),
            0.0,
        )
        effective_samples = max(float(item.calibration_effective_sample_size), 0.0)
        downside = max(float(item.downside_cvar_amount), 0.0)
        if bool(item.coverage_evidence_authorized) and effective_samples >= mature_min:
            prior_uncertainty = 0.0
        elif bool(item.coverage_evidence_authorized) and effective_samples >= warming_min:
            prior_uncertainty = (
                0.25 * downside * math.sqrt(warming_min / effective_samples)
            )
        else:
            prior_uncertainty = 0.35 * downside
        uncertainty_terms.append(max(forecast_gap, prior_uncertainty))
    model_uncertainty = math.sqrt(sum(value * value for value in uncertainty_terms))
    confidence = min(max(float(cvar_confidence), 0.50), 0.999)
    risk_penalty = (
        max(float(cvar_risk_aversion), 0.0) * cvar_amount
        + max(float(model_uncertainty_risk_aversion), 0.0) * model_uncertainty
    )
    if not buys:
        state = "no_incremental_buy_risk"
    elif joint_cvar is not None and len(mature_evidence) == len(buys):
        state = "mature_pit_joint_historical_scenario"
    elif joint_cvar is not None:
        state = "joint_historical_scenario_with_parameter_uncertainty"
    elif len(mature_evidence) == len(buys):
        state = "mature_pit_incremental_scenario"
    elif len(warming_evidence) == len(buys):
        state = "warming_pit_incremental_scenario"
    elif warming_evidence:
        state = "mixed_pit_and_conservative_prior"
    else:
        state = "conservative_prior_incremental_scenario"
    values = (expected, robust, cvar_amount, model_uncertainty, risk_penalty)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("incremental scenario outputs must be finite CNY amounts")
    return IncrementalScenarioRisk(
        hold_baseline_objective_amount=0.0,
        incremental_expected_wealth_amount=float(expected),
        incremental_robust_wealth_amount=float(robust),
        incremental_cvar_amount=float(cvar_amount),
        model_uncertainty_amount=float(model_uncertainty),
        scenario_risk_penalty_amount=float(risk_penalty),
        evidence_name_count=len(warming_evidence),
        evidence_state=state,
        dependence_assumption=float(dependence),
        risk_measure_name=risk_measure_name,
        joint_scenario_count=int(joint_count),
        contract_version=(
            f"{INCREMENTAL_SCENARIO_CONTRACT_VERSION}|{risk_measure_name}|cvar_{confidence:.3f}"
        ),
    )


def _joint_scenario_cvar(
    buys: tuple[ActionProposal, ...],
    scenario_return_matrix: pd.DataFrame | None,
    *,
    confidence: float,
    minimum_scenarios: int,
) -> tuple[float | None, int]:
    """Return empirical portfolio CVaR from synchronized return scenarios."""
    if not buys or scenario_return_matrix is None or scenario_return_matrix.empty:
        return None, 0
    symbols = tuple(dict.fromkeys(str(item.symbol) for item in buys))
    if any(symbol not in scenario_return_matrix.columns for symbol in symbols):
        return None, 0
    scenarios = scenario_return_matrix.loc[:, list(symbols)].apply(
        pd.to_numeric, errors="coerce"
    ).dropna(how="any")
    if len(scenarios) < max(int(minimum_scenarios), 1):
        return None, int(len(scenarios))
    notionals: dict[str, float] = {}
    for item in buys:
        notionals[str(item.symbol)] = notionals.get(str(item.symbol), 0.0) + max(
            float(item.market_notional_amount), 0.0
        )
    # Candidate net value already includes full lifecycle costs.  The scenario
    # component measures market tail loss only, so costs are not charged twice.
    wealth = pd.Series(0.0, index=scenarios.index, dtype=float)
    for symbol, notional in notionals.items():
        wealth = wealth + scenarios[symbol] * notional
    losses = -wealth
    alpha = min(max(float(confidence), 0.50), 0.999)
    threshold = float(losses.quantile(alpha, interpolation="higher"))
    tail = losses[losses >= threshold]
    if tail.empty:
        tail = losses.nlargest(1)
    value = max(float(tail.mean()), 0.0)
    return value, int(len(scenarios))


def _dependence_assumption(
    symbols: tuple[str, ...],
    covariance_matrix: pd.DataFrame | None,
    *,
    floor: float,
) -> float:
    conservative_floor = min(max(float(floor), 0.0), 1.0)
    unique = tuple(dict.fromkeys(str(symbol) for symbol in symbols))
    if len(unique) < 2 or covariance_matrix is None or covariance_matrix.empty:
        return conservative_floor
    if any(
        symbol not in covariance_matrix.index or symbol not in covariance_matrix.columns
        for symbol in unique
    ):
        return conservative_floor
    block = covariance_matrix.loc[list(unique), list(unique)].apply(
        pd.to_numeric, errors="coerce"
    )
    if block.isna().any().any():
        return conservative_floor
    diagonal = [max(float(block.loc[s, s]), 0.0) ** 0.5 for s in unique]
    correlations = []
    for left_index, left in enumerate(unique):
        for right_index in range(left_index + 1, len(unique)):
            scale = diagonal[left_index] * diagonal[right_index]
            if scale > 1e-12:
                right = unique[right_index]
                correlations.append(abs(float(block.loc[left, right]) / scale))
    empirical = sum(correlations) / len(correlations) if correlations else 0.0
    return min(max(conservative_floor, empirical), 1.0)


def _is_buy_action(action_type: str) -> bool:
    return str(action_type) in {
        "new_entry",
        "winner_add",
        "loser_add",
        "replacement_buy",
    }
