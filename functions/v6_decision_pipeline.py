"""End-to-end V6 decision path: signals -> government -> Kelly -> admission."""
from __future__ import annotations

from dataclasses import asdict
from typing import Iterable, Mapping

import pandas as pd

from functions.data_integrity import data_verified
from functions.decision_council.position_management import (
    aggregate_strategy_signals,
    build_position_management_decisions,
)
from functions.v6_governance import continuous_market_discount


def run_v6_decision_pipeline(
    signals: pd.DataFrame,
    *,
    strategy_stats: pd.DataFrame | None = None,
    correlation_matrix: pd.DataFrame | None = None,
    current_weights: Mapping[str, float] | None = None,
    investable_symbols: Iterable[str] | None = None,
    tradeable_symbols: Iterable[str] | None = None,
    volatility_percentile: float,
    market_breadth: float,
    index_trend: float,
    portfolio_drawdown: float,
    prior_market_discounts: pd.Series | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Run the formal architecture without allowing alpha-score bypasses."""
    government = continuous_market_discount(
        volatility_percentile=volatility_percentile,
        market_breadth=market_breadth,
        index_trend=index_trend,
        portfolio_drawdown=portfolio_drawdown,
        prior_discounts=prior_market_discounts,
    )
    aggregated = aggregate_strategy_signals(
        signals,
        strategy_stats=strategy_stats,
        correlation_matrix=correlation_matrix,
    )
    if aggregated.empty:
        return pd.DataFrame(), asdict(government)
    decisions = build_position_management_decisions(
        aggregated,
        current_weights=current_weights,
        investable_symbols=investable_symbols,
        tradeable_symbols=tradeable_symbols,
        exposure_cap=government.portfolio_exposure_cap,
        risk_level=(
            "crisis"
            if government.emergency_deleveraging_flag
            else "high"
            if government.trading_freeze_flag
            else "normal"
        ),
        risk_discount=government.market_discount,
    )
    decisions = decisions.merge(
        aggregated[
            [
                "symbol",
                "p_win_mean",
                "p_win_lower",
                "p_loss",
                "signal_conflict_score",
                "effective_sample_size",
            ]
        ],
        on="symbol",
        how="left",
    )
    verified = data_verified()
    decisions["research_target_weight"] = decisions["target_weight"]
    decisions["formal_target_weight"] = decisions["target_weight"] if verified else 0.0
    decisions["formal_eligible"] = verified
    decisions["score_authority"] = "bayesian_lower_bound_half_kelly"
    decisions["government_authority"] = "portfolio_risk_only"
    decisions = decisions.sort_values(
        ["kelly_score", "symbol"],
        ascending=[False, True],
    ).reset_index(drop=True)
    return decisions, asdict(government)
