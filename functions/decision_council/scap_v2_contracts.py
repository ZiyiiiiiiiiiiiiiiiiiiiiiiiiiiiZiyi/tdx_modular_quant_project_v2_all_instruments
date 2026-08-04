"""Typed contracts for the SCAP-V2 decision boundary.

The legacy pipeline moves values through pandas columns, so Python's type
checker cannot prevent a probability, return rate, score, and yuan amount from
being assigned to the same field.  These contracts provide one runtime
boundary shared by scoring, forecasting, action planning, risk authorization,
execution, and reporting.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping

import math
import pandas as pd


SCAP_V2_CONTRACT_VERSION = "scap_v3_2_contracts_v1"


def _finite(value, *, name: str) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return numeric


def _unit_interval(value, *, name: str) -> float:
    numeric = _finite(value, name=name)
    if numeric < -1e-12 or numeric > 1.0 + 1e-12:
        raise ValueError(f"{name} must be in [0, 1], got {numeric!r}")
    return min(max(numeric, 0.0), 1.0)


@dataclass(frozen=True)
class ScoreContract:
    symbol: str
    as_of_date: pd.Timestamp
    ranking_score: float
    score_authority: str
    coverage: float
    thesis: str = ""
    family_scores: Mapping[str, float] = field(default_factory=dict)
    contract_version: str = SCAP_V2_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of_date", pd.Timestamp(self.as_of_date))
        object.__setattr__(
            self, "ranking_score", _unit_interval(self.ranking_score, name="ranking_score")
        )
        object.__setattr__(self, "coverage", _unit_interval(self.coverage, name="coverage"))
        if not str(self.symbol).strip():
            raise ValueError("ScoreContract.symbol is required")
        if not str(self.score_authority).strip():
            raise ValueError("ScoreContract.score_authority is required")
        for key, value in dict(self.family_scores).items():
            _unit_interval(value, name=f"family_scores[{key!r}]")

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ForecastDistribution:
    symbol: str
    as_of_date: pd.Timestamp
    entry_price_basis: str
    horizon_sessions: int
    gross_return_mean: float
    gross_return_se: float
    downside_cvar: float
    p_win_posterior_mean: float
    p_win_lower: float
    effective_sample_size: float
    authority_weight: float
    state: str
    gross_return_quantiles: Mapping[str, float] = field(default_factory=dict)
    rank_ic: float = float("nan")
    rank_ic_lower: float = float("nan")
    calibration_slope: float = float("nan")
    calibration_ece: float = float("nan")
    cost_inclusion_state: str = "gross_only"
    contract_version: str = SCAP_V2_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of_date", pd.Timestamp(self.as_of_date))
        if int(self.horizon_sessions) <= 0:
            raise ValueError("horizon_sessions must be positive")
        _finite(self.gross_return_mean, name="gross_return_mean")
        if _finite(self.gross_return_se, name="gross_return_se") < 0.0:
            raise ValueError("gross_return_se must be non-negative")
        _unit_interval(self.p_win_posterior_mean, name="p_win_posterior_mean")
        _unit_interval(self.p_win_lower, name="p_win_lower")
        _unit_interval(self.authority_weight, name="authority_weight")
        if _finite(self.effective_sample_size, name="effective_sample_size") < 0.0:
            raise ValueError("effective_sample_size must be non-negative")
        if str(self.cost_inclusion_state) != "gross_only":
            raise ValueError("ForecastDistribution must contain gross returns only")
        if str(self.state) != "calibrated" and float(self.authority_weight) > 0.0:
            raise ValueError("non-calibrated forecasts cannot have trading authority")

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    decision_id: str
    symbol: str
    action_type: str
    source_module: str
    requested_lots: int
    baseline_action: str
    horizon_sessions: int
    expected_net_profit_amount: float
    robust_net_profit_amount: float
    downside_cvar_amount: float
    exact_cost_amount: float
    funding_cash_amount: float
    cash_release_amount: float = 0.0
    market_notional_amount: float = 0.0
    buy_cash_required_amount: float = 0.0
    sell_cash_released_amount: float = 0.0
    exposure_delta: float = 0.0
    scenario_delta_wealth: tuple[float, ...] = ()
    hard_veto_reasons: tuple[str, ...] = ()
    replacement_pair_id: str = ""
    score_contract_id: str = ""
    forecast_contract_id: str = ""
    authority_tier: str = "A"
    thesis: str = ""
    pool_id: str = ""
    pool_memberships: tuple[str, ...] = ()
    primary_score: float = 0.0
    primary_rank: float = 0.0
    unit_capital_robust_return: float = 0.0
    authority_penalty_amount: float = 0.0
    execution_class: str = "alpha"
    must_execute: bool = False
    authority_snapshot_id: str = ""
    lifecycle_cost_amount: float = 0.0
    round_trip_cost_ratio: float = 0.0
    lifecycle_cost_to_gross_profit_ratio: float = 0.0
    minimum_economic_order_amount: float = 0.0
    economic_order_pass: bool = True
    economic_order_reason: str = "not_applicable"
    economic_order_warnings: tuple[str, ...] = ()
    p_win_lower: float = 0.0
    avg_win_return: float = 0.0
    avg_loss_return: float = 0.0
    expected_positive_pnl_amount: float = 0.0
    expected_loss_pnl_amount: float = 0.0
    coverage_evidence_authorized: bool = False
    allocation_sleeve: str = "not_applicable"
    calibration_evidence_state: str = "unavailable"
    calibration_effective_sample_size: float = 0.0
    scenario_contract_id: str = ""
    decision_return_basis: str = "legacy_unknown"
    contract_version: str = SCAP_V2_CONTRACT_VERSION

    def __post_init__(self) -> None:
        # Normalize legacy constructors at the typed boundary.  New code must
        # populate the explicit fields; historical proposal factories still
        # map their funding/release aliases deterministically.
        if self.buy_cash_required_amount == 0.0 and self.funding_cash_amount > 0.0:
            object.__setattr__(
                self,
                "buy_cash_required_amount",
                float(self.funding_cash_amount),
            )
        if self.sell_cash_released_amount == 0.0 and self.cash_release_amount > 0.0:
            object.__setattr__(
                self,
                "sell_cash_released_amount",
                float(self.cash_release_amount),
            )
        if not self.proposal_id or not self.decision_id or not self.symbol:
            raise ValueError("proposal_id, decision_id and symbol are required")
        if int(self.requested_lots) < 0:
            raise ValueError("requested_lots must be non-negative")
        if int(self.horizon_sessions) <= 0:
            raise ValueError("horizon_sessions must be positive")
        for name in (
            "expected_net_profit_amount",
            "robust_net_profit_amount",
            "downside_cvar_amount",
            "exact_cost_amount",
            "funding_cash_amount",
            "cash_release_amount",
            "market_notional_amount",
            "buy_cash_required_amount",
            "sell_cash_released_amount",
            "exposure_delta",
            "primary_score",
            "primary_rank",
            "unit_capital_robust_return",
            "authority_penalty_amount",
            "lifecycle_cost_amount",
            "round_trip_cost_ratio",
            "lifecycle_cost_to_gross_profit_ratio",
            "minimum_economic_order_amount",
            "p_win_lower",
            "avg_win_return",
            "avg_loss_return",
            "expected_positive_pnl_amount",
            "expected_loss_pnl_amount",
            "calibration_effective_sample_size",
        ):
            _finite(getattr(self, name), name=name)
        if (
            self.exact_cost_amount < 0.0
            or self.funding_cash_amount < 0.0
            or self.cash_release_amount < 0.0
            or self.market_notional_amount < 0.0
            or self.buy_cash_required_amount < 0.0
            or self.sell_cash_released_amount < 0.0
            or self.authority_penalty_amount < 0.0
            or self.lifecycle_cost_amount < 0.0
            or self.round_trip_cost_ratio < 0.0
            or self.lifecycle_cost_to_gross_profit_ratio < 0.0
            or self.minimum_economic_order_amount < 0.0
            or self.expected_positive_pnl_amount < 0.0
            or self.expected_loss_pnl_amount < 0.0
            or self.calibration_effective_sample_size < 0.0
        ):
            raise ValueError("cost and funding amounts must be non-negative")
        _unit_interval(self.p_win_lower, name="p_win_lower")
        if abs(self.funding_cash_amount - self.buy_cash_required_amount) > 1e-8:
            raise ValueError("funding_cash_amount must equal buy_cash_required_amount")
        if abs(self.cash_release_amount - self.sell_cash_released_amount) > 1e-8:
            raise ValueError("cash_release_amount must equal sell_cash_released_amount")
        for value in self.scenario_delta_wealth:
            _finite(value, name="scenario_delta_wealth")

    @property
    def executable(self) -> bool:
        return not self.hard_veto_reasons and self.requested_lots > 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExposureAuthorization:
    decision_id: str
    nav_amount: float
    risk_exposure_ceiling: float
    cash_buffer_amount: float
    per_name_structural_cap: float
    per_name_stress_budget_amount: float
    portfolio_stress_budget_amount: float
    new_entry_allowed: bool
    add_allowed: bool
    replacement_allowed: bool
    current_cash_amount: float = 0.0
    strategic_exposure_budget: float = 0.0
    signal_supported_exposure: float = 0.0
    integer_feasible_exposure: float = 0.0
    blocking_reasons: tuple[str, ...] = ()
    covariance_state: str = "unavailable"
    fallback_risk_model: str = "per_name_stress_cap"
    tier_b_exposure_cap: float = 0.40
    tier_c_max_names: int = 2
    exploration_exposure_cap: float = 0.55
    thesis_soft_max_names: int = 2
    thesis_hard_max_names: int = 3
    desired_exposure_target: float = 0.0
    effective_deployment_target: float = 0.0
    per_name_soft_cap: float = 0.25
    cash_gap_penalty_rate: float = 0.0
    name_concentration_penalty_rate: float = 0.0
    breadth_near_optimal_tolerance_amount: float = 0.0
    risk_episode_id: str = ""
    risk_reentry_blocked: bool = False
    hard_exposure_ceiling: float = 1.0
    confirmed_derisk_target: float | None = None
    authority_snapshot_id: str = ""
    risk_horizon_sessions: int = 1
    contract_version: str = SCAP_V2_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if _finite(self.nav_amount, name="nav_amount") <= 0.0:
            raise ValueError("nav_amount must be positive")
        _unit_interval(self.risk_exposure_ceiling, name="risk_exposure_ceiling")
        _unit_interval(self.hard_exposure_ceiling, name="hard_exposure_ceiling")
        if self.confirmed_derisk_target is not None:
            _unit_interval(
                self.confirmed_derisk_target,
                name="confirmed_derisk_target",
            )
        if int(self.risk_horizon_sessions) <= 0:
            raise ValueError("risk_horizon_sessions must be positive")
        _unit_interval(self.per_name_structural_cap, name="per_name_structural_cap")
        for name in (
            "current_cash_amount",
            "cash_buffer_amount",
            "per_name_stress_budget_amount",
            "portfolio_stress_budget_amount",
        ):
            if _finite(getattr(self, name), name=name) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        for name in (
            "strategic_exposure_budget",
            "signal_supported_exposure",
            "integer_feasible_exposure",
            "desired_exposure_target",
            "effective_deployment_target",
            "per_name_soft_cap",
        ):
            _unit_interval(getattr(self, name), name=name)
        _unit_interval(self.tier_b_exposure_cap, name="tier_b_exposure_cap")
        _unit_interval(
            self.exploration_exposure_cap, name="exploration_exposure_cap"
        )
        for name in (
            "cash_gap_penalty_rate",
            "name_concentration_penalty_rate",
            "breadth_near_optimal_tolerance_amount",
        ):
            if _finite(getattr(self, name), name=name) < 0.0:
                raise ValueError(f"{name} must be non-negative")

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ActionPlan:
    decision_id: str
    selected_proposal_ids: tuple[str, ...]
    rejected_proposals: tuple[dict, ...]
    target_lots_by_symbol: Mapping[str, int]
    expected_net_profit_amount: float
    robust_net_profit_amount: float
    downside_cvar_amount: float
    exact_cost_amount: float
    projected_cash: float
    projected_exposure: float
    projected_stress_loss: float
    objective_lexicographic_rank: tuple[float, ...]
    constraint_slacks: Mapping[str, float]
    solver_status: str
    plan_id: str = ""
    optimizer_invocation_count: int = 1
    deployment_gap: float = 0.0
    breadth_score: float = 0.0
    authority_penalty_amount: float = 0.0
    concentration_penalty_amount: float = 0.0
    marginal_risk_penalty_amount: float = 0.0
    proposal_robust_profit_amount: float = 0.0
    thesis_penalty_amount: float = 0.0
    deployment_penalty_amount: float = 0.0
    selected_position_count: int = 0
    coverage_evidence_name_count: int = 0
    expected_positive_pnl_amount: float = 0.0
    expected_loss_pnl_amount: float = 0.0
    lifecycle_cost_amount: float = 0.0
    profit_coverage_ratio: float = 0.0
    profit_coverage_probability_lower: float = 0.0
    coverage_penalty_amount: float = 0.0
    expected_log_growth: float = 0.0
    minimum_selected_marginal_utility_amount: float = 0.0
    maximum_rejected_marginal_utility_amount: float = 0.0
    coverage_state: str = "unavailable"
    coverage_mode: str = "diagnostic_shadow"
    hold_baseline_objective_amount: float = 0.0
    incremental_expected_wealth_amount: float = 0.0
    incremental_cvar_amount: float = 0.0
    model_uncertainty_amount: float = 0.0
    scenario_risk_penalty_amount: float = 0.0
    scenario_evidence_state: str = "unavailable"
    scenario_contract_id: str = ""
    scenario_risk_measure: str = "correlated_tail_loss_proxy"
    joint_scenario_count: int = 0
    best_rejected_proposal_ids: tuple[str, ...] = ()
    best_rejected_objective_amount: float = 0.0
    best_rejected_expected_wealth_amount: float = 0.0
    best_rejected_cvar_amount: float = 0.0
    best_rejected_model_uncertainty_amount: float = 0.0
    risk_model_used: str = "fallback_per_name_stress_cap"
    risk_horizon_sessions: int = 1
    risk_episode_id: str = ""
    planned_holding_count: int = 0
    holding_floor_violation_count: int = 0
    exposure_floor_violation: float = 0.0
    wealth_materiality_epsilon_amount: float = 0.0
    objective_components: Mapping[str, float] | None = None
    contract_version: str = SCAP_V2_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("decision_id is required")
        if int(self.optimizer_invocation_count) != 1:
            raise ValueError("each ActionPlan must be produced by exactly one optimizer invocation")
        if len(self.selected_proposal_ids) != len(set(self.selected_proposal_ids)):
            raise ValueError("selected_proposal_ids must be unique")
        if any(int(lots) < 0 for lots in self.target_lots_by_symbol.values()):
            raise ValueError("target lots must be non-negative")
        _unit_interval(self.projected_exposure, name="projected_exposure")
        if _finite(self.projected_cash, name="projected_cash") < -1e-8:
            raise ValueError("projected_cash must be non-negative")
        for name in (
            "expected_net_profit_amount",
            "robust_net_profit_amount",
            "downside_cvar_amount",
            "exact_cost_amount",
            "projected_stress_loss",
            "deployment_gap",
            "breadth_score",
            "authority_penalty_amount",
            "concentration_penalty_amount",
            "marginal_risk_penalty_amount",
            "proposal_robust_profit_amount",
            "thesis_penalty_amount",
            "deployment_penalty_amount",
            "expected_positive_pnl_amount",
            "expected_loss_pnl_amount",
            "lifecycle_cost_amount",
            "profit_coverage_ratio",
            "profit_coverage_probability_lower",
            "coverage_penalty_amount",
            "expected_log_growth",
            "minimum_selected_marginal_utility_amount",
            "maximum_rejected_marginal_utility_amount",
            "hold_baseline_objective_amount",
            "incremental_expected_wealth_amount",
            "incremental_cvar_amount",
            "model_uncertainty_amount",
            "scenario_risk_penalty_amount",
            "best_rejected_objective_amount",
            "best_rejected_expected_wealth_amount",
            "best_rejected_cvar_amount",
            "best_rejected_model_uncertainty_amount",
        ):
            _finite(getattr(self, name), name=name)
        if (
            int(self.selected_position_count) < 0
            or int(self.coverage_evidence_name_count) < 0
            or int(self.planned_holding_count) < 0
            or int(self.holding_floor_violation_count) < 0
        ):
            raise ValueError("position and coverage counts must be non-negative")
        _unit_interval(
            self.exposure_floor_violation,
            name="exposure_floor_violation",
        )
        if self.wealth_materiality_epsilon_amount < 0.0:
            raise ValueError("wealth materiality epsilon must be non-negative")
        if int(self.joint_scenario_count) < 0:
            raise ValueError("joint_scenario_count must be non-negative")
        _unit_interval(
            self.profit_coverage_probability_lower,
            name="profit_coverage_probability_lower",
        )
        if (
            self.incremental_cvar_amount < 0.0
            or self.model_uncertainty_amount < 0.0
            or self.scenario_risk_penalty_amount < 0.0
            or self.best_rejected_cvar_amount < 0.0
            or self.best_rejected_model_uncertainty_amount < 0.0
        ):
            raise ValueError("incremental risk amounts must be non-negative")
        if int(self.risk_horizon_sessions) <= 0:
            raise ValueError("risk_horizon_sessions must be positive")

    def as_dict(self) -> dict:
        return asdict(self)


def validate_score_columns(
    frame: pd.DataFrame,
    *,
    score_columns: tuple[str, ...] = (
        "entry_matrix_score",
        "final_entry_score",
        "primary_score",
    ),
) -> None:
    """Fail closed when a legacy score field contains a non-score unit."""
    if frame is None or frame.empty:
        return
    violations: dict[str, tuple[float, float]] = {}
    for column in score_columns:
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if values.empty:
            continue
        low, high = float(values.min()), float(values.max())
        if low < -1e-12 or high > 1.0 + 1e-12:
            violations[column] = (low, high)
    if violations:
        raise ValueError(f"SCAP score-unit contract violation: {violations}")
