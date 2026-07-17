"""Runtime-only semantic contracts for factor-cabinet decision roles."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


ROLE_HORIZONS = {
    "entry_alpha": (10, 20),
    "entry_alpha_proxy": (10, 20),
    "timing_filter": (3, 5),
    "risk_override": (1, 5),
    "liquidity_filter": (1, 5),
    "hold_validation": (10, 20),
    "sell_trigger": (1, 5),
}


@dataclass(frozen=True)
class FactorSemanticContract:
    factor_name: str
    primary_role: str
    family: str
    economic_family: str
    module: str
    near_relative_key: str
    direction: str
    horizons: tuple[int, ...]
    hard_veto: bool = False
    missing_policy: str = "unavailable"
    normalization: str = "cross_sectional_rank"
    thesis: str = "composite"

    def as_dict(self) -> dict:
        row = asdict(self)
        row["horizons"] = list(self.horizons)
        return row


def build_factor_semantic_contracts(runtime_context) -> dict[str, FactorSemanticContract]:
    """Build immutable contracts from one resolved cabinet runtime context."""
    if runtime_context is None or getattr(runtime_context, "factor_source", "") == "legacy_bundle":
        return {}
    model_map = dict(getattr(runtime_context, "model_feature_map", {}) or {})
    primary_roles = dict(getattr(runtime_context, "primary_role_map", {}) or {})
    families = dict(getattr(runtime_context, "family_map", {}) or {})
    modules = dict(getattr(runtime_context, "module_map", {}) or {})
    directions = dict(getattr(runtime_context, "direction_map", {}) or {})
    relatives = dict(getattr(runtime_context, "near_relative_map", {}) or {})
    horizons = dict(getattr(runtime_context, "horizon_map", {}) or {})
    contracts: dict[str, FactorSemanticContract] = {}
    for name in model_map:
        role = str(primary_roles.get(name, "")).strip()
        if role not in ROLE_HORIZONS:
            raise ValueError(f"factor semantic contract has invalid primary role for {name}: {role!r}")
        direction = str(directions.get(name, "higher_better") or "higher_better").strip()
        if direction not in {"higher_better", "lower_better"}:
            raise ValueError(f"factor semantic contract has invalid direction for {name}: {direction!r}")
        family = str(families.get(name, "")).strip()
        module = str(modules.get(name, "")).strip()
        if not family or not module:
            raise ValueError(f"factor semantic contract is missing family/module for {name}")
        configured_horizon = int(horizons.get(name, 0) or 0)
        role_horizons = ROLE_HORIZONS[role]
        contract_horizons = (configured_horizon,) if configured_horizon > 0 else role_horizons
        economic_family = canonical_economic_family(name=name, module=module, family=family)
        contracts[name] = FactorSemanticContract(
            factor_name=name,
            primary_role=role,
            family=family,
            economic_family=economic_family,
            module=module,
            near_relative_key=str(relatives.get(name, "") or f"{module}:{family}:{name}"),
            direction=direction,
            horizons=contract_horizons,
            thesis=_thesis_for(economic_family, role),
        )
    return contracts


def validate_factor_semantic_contracts(
    contracts: Mapping[str, FactorSemanticContract],
    *,
    expected_models=(),
) -> dict:
    expected = tuple(str(name) for name in expected_models)
    missing = sorted(set(expected) - set(contracts))
    unexpected = sorted(set(contracts) - set(expected)) if expected else []
    duplicate_relatives: dict[str, int] = {}
    for contract in contracts.values():
        key = f"{contract.primary_role}|{contract.near_relative_key}"
        duplicate_relatives[key] = duplicate_relatives.get(key, 0) + 1
    if missing or unexpected:
        raise ValueError(
            "factor semantic contract/model mismatch: "
            f"missing={missing[:10]}, unexpected={unexpected[:10]}"
        )
    return {
        "contract_count": len(contracts),
        "missing_models": missing,
        "unexpected_models": unexpected,
        "near_relative_group_count": len(duplicate_relatives),
        "largest_near_relative_group": max(duplicate_relatives.values(), default=0),
        "roles": _counts(contract.primary_role for contract in contracts.values()),
        "economic_families": _counts(contract.economic_family for contract in contracts.values()),
    }


def semantic_contract_rows(contracts: Mapping[str, FactorSemanticContract]) -> list[dict]:
    return [contracts[name].as_dict() for name in sorted(contracts)]


def canonical_economic_family(*, name: str, module: str, family: str) -> str:
    text = "|".join((name, module, family)).lower()
    if any(token in text for token in ("orderflow", "flow_close", "accumulation", "close_drive")):
        return "orderflow"
    if "breakout" in text or "turtle" in text:
        return "breakout"
    if "rsi" in text:
        return "rsi"
    if any(token in text for token in ("amihud", "liquidity", "turnover", "amount")):
        return "liquidity"
    if any(token in text for token in ("reversal", "mean_reversion", "rev_", "rev+")):
        return "reversal"
    if any(token in text for token in ("momentum", "ret_", "ret+", "trend")):
        return "momentum"
    if any(token in text for token in ("volatility", "vol_", "vol+", "beta")):
        return "volatility"
    if any(token in text for token in ("size", "barra", "market_cap")):
        return "size_style"
    if any(token in text for token in ("book_to_price", "value", "fcf_yield", "valuation", "pe_", "pb_")):
        return "value"
    if any(token in text for token in ("growth", "revenue", "profit_accel")):
        return "growth"
    if any(token in text for token in ("cashflow", "accrual", "ocf", "cash_")):
        return "cashflow_quality"
    if any(token in text for token in ("quality", "roe", "roa", "margin")):
        return "profitability_quality"
    if any(token in text for token in ("event", "buyback", "announcement", "insider")):
        return "event"
    return family or module or "unknown"


def _thesis_for(economic_family: str, role: str) -> str:
    if role == "hold_validation":
        return f"{economic_family}_persistence"
    if role in {"risk_override", "liquidity_filter", "sell_trigger"}:
        return f"{economic_family}_control"
    return economic_family


def _counts(values) -> dict[str, int]:
    output: dict[str, int] = {}
    for value in values:
        key = str(value)
        output[key] = output.get(key, 0) + 1
    return dict(sorted(output.items()))
