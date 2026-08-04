"""Immutable exposure and holding-count semantics for SCAP decisions.

The contract deliberately separates policy intent, factual feasibility, the
optimizer plan and post-execution facts.  Downstream reports may display these
values but must never use a later layer to rewrite an earlier one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math


EXPOSURE_CONTRACT_VERSION = "scap_exposure_semantics_v1"
DECISION_RECORD_CONTRACT_VERSION = "scap_append_only_decision_record_v1"


def _ratio(value, *, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < -1e-12 or parsed > 1.0 + 1e-12:
        raise ValueError(f"{name} must be a finite ratio in [0, 1]")
    return min(max(parsed, 0.0), 1.0)


@dataclass(frozen=True)
class ExposureSemantics:
    strategic_exposure_target: float
    strategic_exposure_lower_bound: float
    strategic_exposure_upper_bound: float
    hard_risk_exposure_ceiling: float
    attainable_exposure_ceiling: float
    optimizer_planned_exposure: float
    actual_exposure: float
    strategic_exposure_gap: float
    attainable_exposure_gap: float
    execution_exposure_gap: float
    planned_hard_risk_excess: float
    actual_hard_risk_excess: float
    contract_version: str = EXPOSURE_CONTRACT_VERSION

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HoldingSemantics:
    minimum_required_holding_count: int
    soft_target_holding_count: int
    maximum_allowed_holding_count: int
    optimizer_planned_holding_count: int
    actual_holding_count: int
    strategic_holding_shortfall_count: int
    execution_holding_shortfall_count: int
    optimizer_planned_excess_holding_count: int
    actual_excess_holding_count: int
    contract_version: str = EXPOSURE_CONTRACT_VERSION

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StrategicExposureBand:
    state: str
    target: float
    lower_bound: float
    upper_bound: float
    hard_ceiling: float
    conditional_min_holdings: int
    soft_target_holdings: int


def resolve_strategic_exposure_band(
    *,
    risk_level: str,
    structural_regime_level: str,
    safety_exposure_cap: float,
    policy_bands: dict | None = None,
) -> StrategicExposureBand:
    """Compatibility wrapper over the single policy-band resolver.

    The returned hard ceiling is safety-clipped for legacy consumers.  The
    policy object itself remains immutable and unmodified in
    :func:`resolve_policy_band`.
    """
    policy = resolve_policy_band(
        risk_level=risk_level,
        structural_regime_level=structural_regime_level,
        policy_bands=policy_bands,
    )
    safety = _ratio(safety_exposure_cap, name="safety_exposure_cap")
    hard = min(policy.disaster_ceiling, safety)
    upper = min(policy.exposure_upper, hard)
    target = min(policy.exposure_target, upper)
    lower = min(policy.exposure_lower, target)
    return StrategicExposureBand(
        state=policy.state,
        target=target,
        lower_bound=lower,
        upper_bound=upper,
        hard_ceiling=hard,
        conditional_min_holdings=policy.holding_floor,
        soft_target_holdings=policy.holding_target,
    )


def resolve_policy_band(
    *,
    risk_level: str,
    structural_regime_level: str,
    policy_bands: dict | None = None,
) -> PolicyBand:
    """Return the unmodified product policy for the verified state."""
    risk = str(risk_level or "normal").strip().lower()
    regime = str(structural_regime_level or "unknown").strip().lower()
    if risk == "critical" or regime == "crisis":
        state = "crisis"
    elif risk == "high":
        state = "high_risk"
    elif risk in {"warning", "elevated"} or regime in {"weak", "bear", "risk_off"}:
        state = "weak"
    else:
        # Missing/invalid regime evidence fails neutral instead of bearish.
        state = "normal_neutral"
    defaults = {
        "crisis": (0, 0, 0, 0, 0.0, 0, 0, 0.0, 0.0, 0.0, 0.0),
        "high_risk": (0, 0, 4, 3, 0.75, 2, 2, 0.0, 0.0, 0.35, 0.35),
        "weak": (3, 4, 5, 3, 0.75, 2, 3, 0.40, 0.55, 0.65, 0.70),
        "normal_neutral": (5, 6, 7, 5, 0.75, 3, 4, 0.60, 0.75, 0.85, 0.90),
    }
    configured = dict((policy_bands or {}).get(state, {}) or {})
    (
        floor,
        target_count,
        ceiling_count,
        active_pool_minimum,
        effective_n_ratio,
        minimum_pool_count,
        maximum_names_per_pool,
        lower,
        target,
        upper,
        disaster,
    ) = defaults[state]
    return PolicyBand(
        state=state,
        holding_floor=int(configured.get("holding_floor", floor)),
        holding_target=int(configured.get("holding_target", target_count)),
        holding_ceiling=int(configured.get("holding_ceiling", ceiling_count)),
        minimum_active_pool_size=int(
            configured.get("minimum_active_pool_size", active_pool_minimum)
        ),
        minimum_effective_n_ratio=float(
            configured.get("minimum_effective_n_ratio", effective_n_ratio)
        ),
        minimum_pool_count=int(
            configured.get("minimum_pool_count", minimum_pool_count)
        ),
        maximum_names_per_pool=int(
            configured.get("maximum_names_per_pool", maximum_names_per_pool)
        ),
        exposure_lower=float(configured.get("exposure_lower", lower)),
        exposure_target=float(configured.get("exposure_target", target)),
        exposure_upper=float(configured.get("exposure_upper", upper)),
        disaster_ceiling=float(configured.get("disaster_ceiling", disaster)),
        policy_version=str(
            configured.get("policy_version", "scap_policy_band_v1")
        ),
    )


def build_record_lineage(
    *,
    decision_id: str,
    record_stage: str,
    record_id: str,
    immutable_payload: dict,
    formula_version: str,
    supersedes_event_id: str = "",
) -> dict:
    """Return deterministic lineage fields for an append-only decision row."""
    canonical = json.dumps(
        immutable_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    input_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    event_key = "|".join(
        (
            str(decision_id),
            str(record_stage),
            str(record_id),
            str(formula_version),
            input_hash,
        )
    )
    return {
        "event_id": hashlib.sha256(event_key.encode("utf-8")).hexdigest(),
        "record_stage": str(record_stage),
        "record_id": str(record_id),
        "input_hash": input_hash,
        "formula_version": str(formula_version),
        "supersedes_event_id": str(supersedes_event_id or ""),
        "record_status": "correction" if supersedes_event_id else "original",
        "decision_record_contract_version": DECISION_RECORD_CONTRACT_VERSION,
    }


def build_exposure_semantics(
    *,
    strategic_target: float,
    strategic_lower_bound: float,
    strategic_upper_bound: float,
    hard_risk_ceiling: float,
    attainable_ceiling: float,
    optimizer_planned: float,
    actual: float,
) -> ExposureSemantics:
    """Build monotone exposure facts without allowing downstream overwrite.

    The attainable ceiling is descriptive, not a replacement policy target.
    Consequently, an empty candidate set can reduce the attainable gap but can
    never erase the strategic gap.
    """
    target = _ratio(strategic_target, name="strategic_target")
    lower = _ratio(strategic_lower_bound, name="strategic_lower_bound")
    upper = _ratio(strategic_upper_bound, name="strategic_upper_bound")
    hard = _ratio(hard_risk_ceiling, name="hard_risk_ceiling")
    attainable = _ratio(attainable_ceiling, name="attainable_ceiling")
    planned = _ratio(optimizer_planned, name="optimizer_planned")
    factual = _ratio(actual, name="actual")
    if lower > target + 1e-12 or target > upper + 1e-12:
        raise ValueError("strategic exposure must satisfy lower <= target <= upper")
    if upper > hard + 1e-12:
        raise ValueError("strategic upper bound cannot exceed hard risk ceiling")
    attainable_target = min(target, attainable)
    return ExposureSemantics(
        strategic_exposure_target=target,
        strategic_exposure_lower_bound=lower,
        strategic_exposure_upper_bound=upper,
        hard_risk_exposure_ceiling=hard,
        attainable_exposure_ceiling=attainable,
        optimizer_planned_exposure=planned,
        actual_exposure=factual,
        strategic_exposure_gap=max(target - factual, 0.0),
        attainable_exposure_gap=max(attainable_target - factual, 0.0),
        execution_exposure_gap=max(planned - factual, 0.0),
        planned_hard_risk_excess=max(planned - hard, 0.0),
        actual_hard_risk_excess=max(factual - hard, 0.0),
    )


def build_holding_semantics(
    *,
    minimum_required: int,
    soft_target: int,
    maximum_allowed: int,
    optimizer_planned: int,
    actual: int,
) -> HoldingSemantics:
    minimum = max(int(minimum_required), 0)
    soft = max(int(soft_target), 0)
    maximum = max(int(maximum_allowed), 0)
    planned = max(int(optimizer_planned), 0)
    factual = max(int(actual), 0)
    if not minimum <= soft <= maximum:
        raise ValueError("holding counts must satisfy minimum <= soft target <= maximum")
    return HoldingSemantics(
        minimum_required_holding_count=minimum,
        soft_target_holding_count=soft,
        maximum_allowed_holding_count=maximum,
        optimizer_planned_holding_count=planned,
        actual_holding_count=factual,
        strategic_holding_shortfall_count=max(soft - factual, 0),
        execution_holding_shortfall_count=max(planned - factual, 0),
        optimizer_planned_excess_holding_count=max(planned - maximum, 0),
        actual_excess_holding_count=max(factual - maximum, 0),
    )
from functions.decision_council.portfolio_constraint_contract import PolicyBand
