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
    transition_only: bool = False
    hard_qualification_symbols: frozenset[str] = frozenset()
