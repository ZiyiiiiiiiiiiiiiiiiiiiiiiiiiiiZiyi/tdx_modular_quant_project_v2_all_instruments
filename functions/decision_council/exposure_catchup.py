"""Exposure catch-up policy for governance portfolios."""
from __future__ import annotations

from dataclasses import dataclass

from config import (
    ENABLE_GOVERNANCE_EXPOSURE_CATCHUP,
    GOVERNANCE_CATCHUP_EXTRA_BUDGET_NORMAL,
    GOVERNANCE_CATCHUP_EXTRA_BUDGET_WARNING,
    GOVERNANCE_CATCHUP_GAP_TRIGGER,
    GOVERNANCE_CATCHUP_MAX_BUDGET,
    GOVERNANCE_CATCHUP_MAX_LIQUIDITY_STRESS,
    GOVERNANCE_CATCHUP_MIN_ENTRY_COUNT,
    GOVERNANCE_CATCHUP_RATE_NORMAL_BEAR,
    GOVERNANCE_CATCHUP_RATE_NORMAL_BULL,
    GOVERNANCE_CATCHUP_RATE_NORMAL_NEUTRAL,
    GOVERNANCE_CATCHUP_RATE_NORMAL_WEAK,
    GOVERNANCE_CATCHUP_RATE_WARNING,
)


@dataclass(frozen=True)
class ExposureCatchupDecision:
    actual_exposure: float
    target_exposure: float
    exposure_gap: float
    catchup_allowed: bool
    catchup_rate: float
    catchup_buy_budget: float
    catchup_extra_turnover_budget: float
    catchup_block_reason: str
    qualified_entry_count: int
    catchup_tier: str = "none"
    accuracy_multiplier: float = 0.0
    catchup_gap_trigger: float = 0.0


def decide_exposure_catchup(
    *,
    actual_exposure: float,
    target_exposure: float,
    risk_level: str,
    structural_regime_level: str,
    market_liquidity_stress_ratio: float,
    qualified_entry_count: int,
    transition_only: bool,
    trailing_buy_accuracy_5d: float | None = None,
    risk_contribution_gate_pass: bool = True,
    top5_risk_contribution_sum: float = 0.0,
    top20pct_risk_contribution_sum: float = 0.0,
    risk_effective_n_ratio: float = 1.0,
    risk_symbol_count: int = 999,
    hard_risk_gate_enabled: bool = False,
    representative_one_lot_weight: float | None = None,
) -> ExposureCatchupDecision:
    """Decide whether and how much extra buy budget can pursue target exposure."""
    actual = max(float(actual_exposure), 0.0)
    target = max(float(target_exposure), 0.0)
    gap = max(target - actual, 0.0)
    risk = str(risk_level).lower()
    regime = str(structural_regime_level).lower()
    rate = _catchup_rate(risk, regime)
    extra_budget = _extra_turnover_budget(risk)
    tier, tier_multiplier = _catchup_tier(int(qualified_entry_count))
    accuracy_multiplier = _accuracy_multiplier(trailing_buy_accuracy_5d)
    configured_gap_trigger = float(GOVERNANCE_CATCHUP_GAP_TRIGGER)
    if (
        representative_one_lot_weight is not None
        and float(representative_one_lot_weight) > 0.0
    ):
        adaptive_gap_trigger = min(
            configured_gap_trigger,
            max(float(representative_one_lot_weight), 0.01),
        )
    else:
        adaptive_gap_trigger = configured_gap_trigger

    block_reason = "allowed"
    if not ENABLE_GOVERNANCE_EXPOSURE_CATCHUP:
        block_reason = "disabled"
    elif transition_only:
        block_reason = "transition_only"
    elif gap < adaptive_gap_trigger:
        block_reason = "gap_below_trigger"
    elif risk not in {"normal", "warning"}:
        block_reason = "risk_level_blocks_catchup"
    elif float(market_liquidity_stress_ratio) > float(GOVERNANCE_CATCHUP_MAX_LIQUIDITY_STRESS):
        block_reason = "liquidity_stress"
    elif tier == "none":
        block_reason = "insufficient_confirmed_entries"
    elif bool(hard_risk_gate_enabled) and not bool(risk_contribution_gate_pass):
        block_reason = "risk_contribution_gate_blocks_catchup"
    elif bool(hard_risk_gate_enabled) and (
        float(top20pct_risk_contribution_sum) > 0.55
        or float(risk_effective_n_ratio) < 0.55
    ):
        block_reason = "scale_normalized_risk_contribution_blocks_catchup"
    elif rate <= 0.0:
        block_reason = "zero_catchup_rate"

    allowed = block_reason == "allowed"
    budget = min(
        gap * rate * tier_multiplier * accuracy_multiplier,
        extra_budget,
        float(GOVERNANCE_CATCHUP_MAX_BUDGET),
    ) if allowed else 0.0

    return ExposureCatchupDecision(
        actual_exposure=actual,
        target_exposure=target,
        exposure_gap=gap,
        catchup_allowed=allowed,
        catchup_rate=rate,
        catchup_buy_budget=max(float(budget), 0.0),
        catchup_extra_turnover_budget=extra_budget if allowed else 0.0,
        catchup_block_reason=block_reason,
        qualified_entry_count=int(qualified_entry_count),
        catchup_tier=tier if allowed else "none",
        accuracy_multiplier=accuracy_multiplier if allowed else 0.0,
        catchup_gap_trigger=float(adaptive_gap_trigger),
    )


def _catchup_rate(risk_level: str, structural_regime_level: str) -> float:
    if risk_level == "warning":
        return float(GOVERNANCE_CATCHUP_RATE_WARNING)
    if risk_level != "normal":
        return 0.0
    if structural_regime_level == "rebound":
        return max(float(GOVERNANCE_CATCHUP_RATE_NORMAL_BULL), 0.45)
    if structural_regime_level == "bull":
        return float(GOVERNANCE_CATCHUP_RATE_NORMAL_BULL)
    if structural_regime_level == "neutral":
        return float(GOVERNANCE_CATCHUP_RATE_NORMAL_NEUTRAL)
    if structural_regime_level == "weak":
        return float(GOVERNANCE_CATCHUP_RATE_NORMAL_WEAK)
    return float(GOVERNANCE_CATCHUP_RATE_NORMAL_BEAR)


def _extra_turnover_budget(risk_level: str) -> float:
    if risk_level == "normal":
        return float(GOVERNANCE_CATCHUP_EXTRA_BUDGET_NORMAL)
    if risk_level == "warning":
        return float(GOVERNANCE_CATCHUP_EXTRA_BUDGET_WARNING)
    return 0.0


def _catchup_tier(qualified_entry_count: int) -> tuple[str, float]:
    count = int(qualified_entry_count)
    if count >= 10:
        return "strong", 1.20
    if count >= 6:
        return "medium", 0.90
    if count >= 3:
        return "small", 0.60
    if count >= 2:
        return "starter", 0.35
    # Keep the configured legacy threshold meaningful for stricter configs.
    if count >= int(GOVERNANCE_CATCHUP_MIN_ENTRY_COUNT):
        return "medium", 0.65
    return "none", 0.0


def _accuracy_multiplier(trailing_buy_accuracy_5d: float | None) -> float:
    if trailing_buy_accuracy_5d is None:
        return 0.90
    accuracy = float(trailing_buy_accuracy_5d)
    if accuracy >= 0.52:
        return 1.10
    if accuracy >= 0.48:
        return 0.95
    if accuracy >= 0.44:
        return 0.70
    if accuracy >= 0.40:
        return 0.55
    return 0.35
