"""Shared data contracts for daily governance decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from functions.decision_council.portfolio_constraint_contract import PolicyBand
from functions.decision_council.position_sizing_contract import PortfolioSizingIntent


@dataclass(frozen=True)
class SafetyDecision:
    decision_date: pd.Timestamp
    risk_level: str
    exposure_cap: float
    benchmark_drawdown_5d: float | None
    market_liquidity_stress_ratio: float
    proxy_symbol: str | None
    proxy_mode: str
    risk_level_lag_days: int = 0
    degraded: bool = False
    raw_risk_level: str = "normal"
    trigger_source: str = "normal"
    trigger_streak_days: int = 0
    benchmark_drawdown_20d: float | None = None
    benchmark_return_5d: float | None = None
    benchmark_return_20d: float | None = None
    benchmark_underwater_from_peak: float | None = None
    structural_regime_level: str = "bull"
    regime_exposure_budget: float = 1.0
    safety_exposure_cap: float = 1.0
    hard_freeze_active: bool = False


@dataclass(frozen=True)
class BenchmarkLeg:
    """One benchmark with an explicit, non-transferable authority role."""

    benchmark_id: str
    role: str
    as_of_date: pd.Timestamp
    constituent_rule: str
    weighting_rule: str
    rebalance_rule: str
    return_valid: bool
    coverage_ratio: float
    degraded_reasons: tuple[str, ...] = ()
    authority: str = "attribution_only"


@dataclass(frozen=True)
class BenchmarkBundle:
    """Keep performance, opportunity, style and safety benchmarks separate."""

    contract_id: str
    performance_primary: BenchmarkLeg
    opportunity_set: BenchmarkLeg
    style_matched: BenchmarkLeg
    safety_proxy: BenchmarkLeg


@dataclass(frozen=True)
class MarketStateVector:
    """PIT market state and the single effective deployment ceiling."""

    contract_id: str
    decision_date: pd.Timestamp
    safety_proxy_id: str
    fast_shock_state: str
    structural_state: str
    recovery_state: str
    fast_state_streak: int
    structural_state_streak: int
    recovery_streak: int
    return_5d: float | None
    return_20d: float | None
    drawdown_5d: float | None
    drawdown_20d: float | None
    underwater_from_peak: float | None
    liquidity_stress: float | None
    hard_safety_cap: float
    structural_multiplier: float
    recovery_cap: float
    sizing_attainable_cap: float
    effective_deployment_cap: float
    data_quality_state: str
    blocked_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExitSignalObservation:
    """A detected exit signal. Detection alone never grants trade authority."""

    observation_id: str
    decision_id: str
    decision_date: pd.Timestamp
    symbol: str
    signal_type: str
    detected: bool
    detected_score: float | None
    first_detected_date: pd.Timestamp | None
    consecutive_count: int
    confirmation_required: int
    paper_active: bool
    control_enabled: bool
    evidence_as_of_date: pd.Timestamp
    data_quality_state: str = "complete"


@dataclass(frozen=True)
class ExitAuthorityDecision:
    """Trading-authority result for exactly one exit observation."""

    observation_id: str
    authority_active: bool
    selected_exit_reason: str | None
    veto_reasons: tuple[str, ...]
    superseded_by: str | None
    intended_exit_fraction: float
    earliest_execution_date: pd.Timestamp | None
    authority_contract_version: str = "scap_exit_authority_v2"


@dataclass(frozen=True)
class EntryEvidenceSnapshot:
    """PIT evidence used to decide whether an entry may trade."""

    evidence_id: str
    decision_id: str
    decision_date: pd.Timestamp
    symbol: str
    authority_tier: str
    calibration_state: str
    effective_sample_size: float
    unique_session_count: int
    forecast_rank_ic: float | None
    forecast_slope: float | None
    drift_streak: int
    fallback_contract: str | None
    fallback_family: str | None
    fallback_state: str | None
    full_universe_oos_status: str
    evidence_as_of_date: pd.Timestamp


@dataclass(frozen=True)
class EntryQualityAuthority:
    """Size and trade mode derived from entry evidence and one CNY CE."""

    evidence_id: str
    trade_mode: str
    decision_return: float
    decision_return_basis: str
    maximum_lots: int
    maximum_notional: float
    risk_adjusted_ce_amount: float
    authority_reasons: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecisionContext:
    decision_id: str
    decision_date: pd.Timestamp
    candidates: pd.DataFrame
    current_weights: Mapping[str, float]
    holding_days: Mapping[str, int]
    pending_locked_symbols: frozenset[str]
    safety: SafetyDecision
    turnover_budget: float = 0.20
    minimum_holding_days: int = 5
    top_n: int = 20
    entry_rank_limit: int = 20
    hold_rank_limit: int = 100
    allow_normal_rebalance: bool = True
    partial_adjustment_rate: float = 0.25
    catchup_buy_budget: float = 0.0
    catchup_allowed: bool = False
    transition_only: bool = False
    active_replacement_enabled: bool = True
    active_replacement_max_pairs_per_day: int = 1
    hard_qualification_symbols: frozenset[str] = frozenset()
    covariance_matrix: pd.DataFrame | None = None
    scenario_return_matrix: pd.DataFrame | None = None
    nav_amount: float = 1.0
    cash_amount: float = 0.0
    cash_buffer_amount: float = 0.0
    per_name_structural_cap: float = 1.0
    portfolio_stress_budget_amount: float = 1.0e18
    control_mode: str = "normal"
    winner_add_enabled: bool = False
    loser_add_enabled: bool = False
    soft_exit_enabled: bool = True
    forecast_horizon_sessions: int = 10
    forecast_kappa: float = 0.50
    soft_target_positions: int = 4
    execution_cost_profile: Mapping[str, object] | None = None
    desired_exposure_target: float | None = None
    hard_exposure_ceiling: float | None = None
    confirmed_derisk_target: float | None = None
    current_lots_by_symbol: Mapping[str, int] | None = None
    policy_band: PolicyBand | None = None
    sizing_intent: PortfolioSizingIntent | None = None
    recovery_episode_id: str = ""
    recovery_episode_day: int = 0
