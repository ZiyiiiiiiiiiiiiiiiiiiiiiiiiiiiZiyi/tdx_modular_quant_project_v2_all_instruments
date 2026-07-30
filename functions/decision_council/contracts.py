"""Shared data contracts for daily governance decisions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd


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
