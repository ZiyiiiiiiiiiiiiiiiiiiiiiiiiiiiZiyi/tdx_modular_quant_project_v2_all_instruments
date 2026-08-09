"""Typed policy, projection, feasibility, and recovery contracts for SCAP.

The contracts deliberately keep six layers separate: pre-trade facts, policy,
mandatory-action projection, feasible bounds, optimizer plan, and execution.
No field in this module is allowed to silently replace a policy value with a
daily feasible value.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable, Mapping


def _finite(value, *, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _ratio(value, *, name: str) -> float:
    result = _finite(value, name=name)
    if result < 0.0 or result > 1.0:
        raise ValueError(f"{name} must be within [0, 1]")
    return result


@dataclass(frozen=True)
class PolicyBand:
    state: str
    holding_floor: int
    holding_target: int
    exposure_lower: float
    exposure_target: float
    exposure_upper: float
    disaster_ceiling: float
    holding_ceiling: int = 32
    minimum_active_pool_size: int = 0
    minimum_effective_n_ratio: float = 0.0
    minimum_pool_count: int = 0
    maximum_names_per_pool: int = 32
    policy_version: str = "scap_policy_band_v1"

    def __post_init__(self) -> None:
        if not self.state:
            raise ValueError("policy state is required")
        floor = max(int(self.holding_floor), 0)
        target = max(int(self.holding_target), 0)
        ceiling = max(int(self.holding_ceiling), 0)
        active_floor = max(int(self.minimum_active_pool_size), 0)
        if not floor <= target <= ceiling:
            raise ValueError("holding policy must satisfy floor <= target <= ceiling")
        if active_floor > ceiling:
            raise ValueError("minimum active pool size cannot exceed holding ceiling")
        ratio = _ratio(
            self.minimum_effective_n_ratio,
            name="minimum_effective_n_ratio",
        )
        if int(self.minimum_pool_count) < 0 or int(self.maximum_names_per_pool) <= 0:
            raise ValueError("pool-count constraints must be non-negative/positive")
        if ratio > 1.0:
            raise ValueError("minimum effective-N ratio cannot exceed one")
        lower = _ratio(self.exposure_lower, name="exposure_lower")
        desired = _ratio(self.exposure_target, name="exposure_target")
        upper = _ratio(self.exposure_upper, name="exposure_upper")
        disaster = _ratio(self.disaster_ceiling, name="disaster_ceiling")
        if not lower <= desired <= upper <= disaster:
            raise ValueError(
                "exposure policy must satisfy lower <= target <= upper <= disaster ceiling"
            )

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MandatoryProjection:
    post_mandatory_lots: Mapping[str, int]
    post_mandatory_weights: Mapping[str, float]
    post_mandatory_cash: float
    post_mandatory_holding_count: int
    post_mandatory_exposure: float
    mandatory_proposal_ids: tuple[str, ...]
    unexecutable_mandatory_ids: tuple[str, ...] = ()
    projection_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if int(self.post_mandatory_holding_count) < 0:
            raise ValueError("post_mandatory_holding_count must be non-negative")
        _ratio(self.post_mandatory_exposure, name="post_mandatory_exposure")
        if _finite(self.post_mandatory_cash, name="post_mandatory_cash") < 0.0:
            raise ValueError("post_mandatory_cash must be non-negative")

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DeploymentBounds:
    policy_holding_floor: int
    policy_holding_target: int
    conditional_holding_floor: int
    hard_holding_ceiling: int
    policy_exposure_lower: float
    policy_exposure_target: float
    conditional_exposure_floor: float
    hard_exposure_ceiling: float
    positive_feasible_new_name_count: int
    positive_feasible_exposure_ceiling: float
    holding_floor_shortfall_reason: str = ""
    exposure_floor_shortfall_reason: str = ""
    policy_holding_ceiling: int = 32
    policy_floor_feasible: bool = False
    authority_attainable_holding_count: int = 0
    authority_attainable_exposure: float = 0.0
    integer_attainable_holding_count: int = 0
    integer_attainable_exposure: float = 0.0
    policy_floor_feasible_before_authority: bool = False
    policy_floor_feasible_after_authority: bool = False
    structural_shortfall_reasons: tuple[str, ...] = ()
    contract_version: str = "scap_deployment_bounds_v3_authority_attainable"

    def __post_init__(self) -> None:
        values = (
            int(self.policy_holding_floor),
            int(self.policy_holding_target),
            int(self.conditional_holding_floor),
            int(self.hard_holding_ceiling),
            int(self.positive_feasible_new_name_count),
            int(self.authority_attainable_holding_count),
            int(self.integer_attainable_holding_count),
        )
        if any(value < 0 for value in values):
            raise ValueError("holding bounds and feasible counts must be non-negative")
        if self.policy_holding_floor > self.policy_holding_target:
            raise ValueError("policy holding floor cannot exceed target")
        if self.conditional_holding_floor > self.hard_holding_ceiling:
            raise ValueError("conditional holding floor cannot exceed hard ceiling")
        policy_lower = _ratio(self.policy_exposure_lower, name="policy_exposure_lower")
        policy_target = _ratio(self.policy_exposure_target, name="policy_exposure_target")
        conditional = _ratio(
            self.conditional_exposure_floor,
            name="conditional_exposure_floor",
        )
        hard = _ratio(self.hard_exposure_ceiling, name="hard_exposure_ceiling")
        feasible = _ratio(
            self.positive_feasible_exposure_ceiling,
            name="positive_feasible_exposure_ceiling",
        )
        _ratio(
            self.authority_attainable_exposure,
            name="authority_attainable_exposure",
        )
        _ratio(
            self.integer_attainable_exposure,
            name="integer_attainable_exposure",
        )
        if policy_lower > policy_target:
            raise ValueError("policy exposure lower cannot exceed target")
        if conditional > hard:
            raise ValueError("execution exposure floor cannot exceed its hard ceiling")

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryAuthorization:
    authorized: bool
    episode_id: str
    episode_day: int
    holding_deficit: int
    exposure_deficit: float
    max_new_names_today: int
    max_buy_exposure_today: float
    deadline_sessions: int
    block_reason: str
    contract_version: str = "scap_recovery_authorization_v1"

    def __post_init__(self) -> None:
        if int(self.episode_day) < 0 or int(self.holding_deficit) < 0:
            raise ValueError("recovery day and deficits must be non-negative")
        if int(self.max_new_names_today) < 0 or int(self.deadline_sessions) < 0:
            raise ValueError("recovery limits must be non-negative")
        _ratio(self.exposure_deficit, name="exposure_deficit")
        _ratio(self.max_buy_exposure_today, name="max_buy_exposure_today")

    def as_dict(self) -> dict:
        return asdict(self)


def project_mandatory_actions(
    *,
    current_lots: Mapping[str, int],
    current_weights: Mapping[str, float],
    current_cash: float,
    proposals: Iterable[object],
) -> MandatoryProjection:
    """Project only executable mandatory exits; optional actions are ignored."""
    lots = {str(symbol): max(int(value), 0) for symbol, value in current_lots.items()}
    weights = {
        str(symbol): max(_finite(value, name=f"weight[{symbol}]"), 0.0)
        for symbol, value in current_weights.items()
    }
    cash = max(_finite(current_cash, name="current_cash"), 0.0)
    mandatory_ids: list[str] = []
    unexecutable_ids: list[str] = []
    reasons: list[str] = []
    for proposal in proposals:
        action_type = str(getattr(proposal, "action_type", ""))
        mandatory = bool(getattr(proposal, "must_execute", False)) or action_type in {
            "hard_exit",
            "safety_exit",
        }
        if not mandatory:
            continue
        proposal_id = str(getattr(proposal, "proposal_id", ""))
        if not bool(getattr(proposal, "executable", False)):
            unexecutable_ids.append(proposal_id)
            reasons.append("mandatory_action_not_executable")
            continue
        symbol = str(getattr(proposal, "symbol", ""))
        mandatory_ids.append(proposal_id)
        lots.pop(symbol, None)
        weights.pop(symbol, None)
        cash += max(
            _finite(
                getattr(proposal, "sell_cash_released_amount", 0.0),
                name="sell_cash_released_amount",
            ),
            0.0,
        )
    exposure = min(max(sum(weights.values()), 0.0), 1.0)
    active_lots = {symbol: value for symbol, value in lots.items() if value > 0}
    return MandatoryProjection(
        post_mandatory_lots=active_lots,
        post_mandatory_weights=weights,
        post_mandatory_cash=cash,
        post_mandatory_holding_count=len(active_lots),
        post_mandatory_exposure=exposure,
        mandatory_proposal_ids=tuple(mandatory_ids),
        unexecutable_mandatory_ids=tuple(unexecutable_ids),
        projection_reasons=tuple(sorted(set(reasons))),
    )


def resolve_conditional_deployment_bounds(
    *,
    policy_band: PolicyBand,
    mandatory_projection: MandatoryProjection,
    hard_holding_ceiling: int,
    hard_exposure_ceiling: float,
    positive_feasible_proposals: Iterable[object],
    wealth_epsilon_amount: float = 0.0,
) -> DeploymentBounds:
    """Resolve executable lower bounds without rewriting the policy contract."""
    ceiling_k = max(int(hard_holding_ceiling), 0)
    ceiling_e = _ratio(hard_exposure_ceiling, name="hard_exposure_ceiling")
    epsilon = max(_finite(wealth_epsilon_amount, name="wealth_epsilon_amount"), 0.0)
    minimum_by_symbol: dict[str, float] = {}
    maximum_by_symbol: dict[str, float] = {}
    implied_nav_values: list[float] = []
    for proposal in positive_feasible_proposals:
        action_type = str(getattr(proposal, "action_type", ""))
        if action_type not in {"new_entry", "winner_add", "loser_add", "replacement_buy"}:
            continue
        if not bool(getattr(proposal, "executable", False)):
            continue
        robust = _finite(
            getattr(proposal, "robust_net_profit_amount", 0.0),
            name="robust_net_profit_amount",
        ) - max(
            _finite(
                getattr(proposal, "authority_penalty_amount", 0.0),
                name="authority_penalty_amount",
            ),
            0.0,
        )
        if robust <= epsilon:
            continue
        symbol = str(getattr(proposal, "symbol", ""))
        if symbol in mandatory_projection.post_mandatory_lots:
            continue
        exposure_delta = max(
            _finite(getattr(proposal, "exposure_delta", 0.0), name="exposure_delta"),
            0.0,
        )
        previous = minimum_by_symbol.get(symbol)
        if previous is None or exposure_delta < previous:
            # One-lot/minimum feasible increments produce a conservative count
            # and the broadest jointly fundable lower-bound estimate.
            minimum_by_symbol[symbol] = exposure_delta
        maximum_by_symbol[symbol] = max(
            maximum_by_symbol.get(symbol, 0.0), exposure_delta
        )
        market_notional = max(
            _finite(
                getattr(proposal, "market_notional_amount", 0.0),
                name="market_notional_amount",
            ),
            0.0,
        )
        if market_notional > 0.0 and exposure_delta > 1e-12:
            implied_nav_values.append(market_notional / exposure_delta)
    feasible_new_count = len(minimum_by_symbol)
    # Computational compression and today's candidate quality may explain why
    # a policy is infeasible, but they are not allowed to rewrite the policy
    # requirement.  The optimizer records any remaining violation explicitly.
    conditional_k = min(max(int(policy_band.holding_floor), 0), ceiling_k)
    authority_exposure = mandatory_projection.post_mandatory_exposure + sum(
        maximum_by_symbol.values()
    )
    if implied_nav_values:
        implied_nav_values.sort()
        implied_nav = implied_nav_values[len(implied_nav_values) // 2]
        cash_exposure_ceiling = (
            mandatory_projection.post_mandatory_exposure
            + mandatory_projection.post_mandatory_cash / max(implied_nav, 1e-12)
        )
    else:
        cash_exposure_ceiling = mandatory_projection.post_mandatory_exposure
    feasible_exposure = min(
        ceiling_e,
        max(
            min(authority_exposure, cash_exposure_ceiling),
            mandatory_projection.post_mandatory_exposure,
        ),
    )
    conditional_e = min(policy_band.exposure_lower, ceiling_e)
    holding_reason = ""
    policy_k_feasible = bool(
        mandatory_projection.post_mandatory_holding_count + feasible_new_count
        >= conditional_k
    )
    policy_e_feasible = bool(feasible_exposure + 1e-12 >= conditional_e)
    if not policy_k_feasible:
        holding_reason = (
            "positive_feasible_candidate_shortfall"
            if conditional_k <= ceiling_k
            else "hard_holding_ceiling_binds"
        )
    exposure_reason = ""
    if not policy_e_feasible:
        exposure_reason = (
            "positive_feasible_exposure_shortfall"
            if conditional_e <= ceiling_e
            else "hard_exposure_ceiling_binds"
        )
    shortfall_reasons = tuple(
        reason
        for reason in (holding_reason, exposure_reason)
        if reason
    )
    attainable_k = min(
        mandatory_projection.post_mandatory_holding_count + feasible_new_count,
        ceiling_k,
    )
    return DeploymentBounds(
        policy_holding_floor=policy_band.holding_floor,
        policy_holding_target=policy_band.holding_target,
        conditional_holding_floor=conditional_k,
        hard_holding_ceiling=ceiling_k,
        policy_exposure_lower=policy_band.exposure_lower,
        policy_exposure_target=policy_band.exposure_target,
        conditional_exposure_floor=conditional_e,
        hard_exposure_ceiling=ceiling_e,
        positive_feasible_new_name_count=feasible_new_count,
        positive_feasible_exposure_ceiling=feasible_exposure,
        holding_floor_shortfall_reason=holding_reason,
        exposure_floor_shortfall_reason=exposure_reason,
        policy_holding_ceiling=int(policy_band.holding_ceiling),
        policy_floor_feasible=bool(policy_k_feasible and policy_e_feasible),
        authority_attainable_holding_count=attainable_k,
        authority_attainable_exposure=feasible_exposure,
        integer_attainable_holding_count=attainable_k,
        integer_attainable_exposure=feasible_exposure,
        policy_floor_feasible_before_authority=bool(
            int(policy_band.holding_floor) <= ceiling_k
            and float(policy_band.exposure_lower) <= ceiling_e + 1e-12
        ),
        policy_floor_feasible_after_authority=bool(
            policy_k_feasible and policy_e_feasible
        ),
        structural_shortfall_reasons=shortfall_reasons,
    )


def authorize_recovery(
    *,
    decision_id: str,
    mandatory_projection: MandatoryProjection,
    bounds: DeploymentBounds,
    configured_max_new_names: int,
    configured_daily_exposure_cap: float,
    deadline_sessions: int,
    safety_blocked: bool,
    prior_episode_id: str = "",
    prior_episode_day: int = 0,
) -> RecoveryAuthorization:
    """Authorize recovery from post-mandatory facts, not pre-trade exposure."""
    holding_deficit = max(
        bounds.conditional_holding_floor
        - mandatory_projection.post_mandatory_holding_count,
        0,
    )
    exposure_deficit = max(
        bounds.conditional_exposure_floor
        - mandatory_projection.post_mandatory_exposure,
        0.0,
    )
    needs_recovery = holding_deficit > 0 or exposure_deficit > 1e-12
    authorized = bool(needs_recovery and not safety_blocked)
    if safety_blocked:
        reason = "safety_state_blocks_recovery"
    elif not needs_recovery:
        reason = "post_mandatory_floor_satisfied"
    elif bounds.positive_feasible_new_name_count <= 0:
        reason = "no_positive_feasible_candidate"
        authorized = False
    else:
        reason = "post_mandatory_floor_recovery"
    max_names = (
        min(
            max(max(int(configured_max_new_names), 0), holding_deficit),
            bounds.positive_feasible_new_name_count,
        )
        if authorized
        else 0
    )
    configured_cap = _ratio(
        configured_daily_exposure_cap,
        name="configured_daily_exposure_cap",
    )
    # A discrete minimum pool may overshoot the continuous lower exposure by
    # one or more whole lots.  When name recovery is required, authorize up to
    # the policy target (never beyond the hard ceiling) so integer granularity
    # cannot deadlock an otherwise feasible five-name batch at the 60% floor.
    recovery_exposure_need = max(
        exposure_deficit,
        (
            bounds.policy_exposure_target
            - mandatory_projection.post_mandatory_exposure
            if holding_deficit > 0
            else 0.0
        ),
    )
    max_exposure = (
        min(
            max(configured_cap, recovery_exposure_need),
            max(
                bounds.hard_exposure_ceiling
                - mandatory_projection.post_mandatory_exposure,
                0.0,
            ),
        )
        if authorized
        else 0.0
    )
    episode_id = (
        str(prior_episode_id)
        if authorized and str(prior_episode_id)
        else f"{decision_id}|post_mandatory_recovery"
        if authorized
        else ""
    )
    episode_day = (
        max(int(prior_episode_day), 0) + 1 if authorized else 0
    )
    if authorized and int(deadline_sessions) > 0 and episode_day > int(deadline_sessions):
        reason = "post_mandatory_recovery_deadline_breached"
    return RecoveryAuthorization(
        authorized=authorized,
        episode_id=episode_id,
        episode_day=episode_day,
        holding_deficit=holding_deficit,
        exposure_deficit=exposure_deficit,
        max_new_names_today=max_names,
        max_buy_exposure_today=max_exposure,
        deadline_sessions=max(int(deadline_sessions), 0) if authorized else 0,
        block_reason=reason,
    )
