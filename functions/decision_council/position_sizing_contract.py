"""Single-source portfolio and entry sizing contracts for SCAP.

Trade capacity is a ceiling.  It must never become the denominator used to
split a policy target.  This module resolves the one executable sizing intent
and applies authority/risk/cash limits to integer entry lots.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math

import pandas as pd

from functions.decision_council.portfolio_constraint_contract import PolicyBand


SIZING_CONTRACT_VERSION = "scap_portfolio_sizing_v2"
AUTHORITY_FRACTIONS = {"A": 1.00, "B": 0.60, "C": 0.35, "D": 0.0}


def _finite(value, *, name: str) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{name} must be finite")
    return numeric


def _ratio(value, *, name: str) -> float:
    numeric = _finite(value, name=name)
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{name} must be within [0, 1]")
    return numeric


@dataclass(frozen=True)
class PortfolioSizingIntent:
    decision_id: str
    nav_amount: float
    policy_holding_floor: int
    policy_holding_target: int
    policy_exposure_lower: float
    policy_exposure_target: float
    hard_holding_ceiling: int
    hard_exposure_ceiling: float
    executable_target_holding_count: int
    executable_target_exposure: float
    target_gross_amount: float
    current_gross_amount: float
    incremental_target_amount: float
    target_new_name_count: int
    base_new_name_target_amount: float
    legacy_sizing_reference_positions: int
    sizing_mode: str
    feasibility_state: str
    binding_reasons: tuple[str, ...]
    contract_version: str = SIZING_CONTRACT_VERSION
    sizing_contract_id: str = ""

    def __post_init__(self) -> None:
        if not str(self.decision_id):
            raise ValueError("decision_id is required")
        integer_fields = (
            self.policy_holding_floor,
            self.policy_holding_target,
            self.hard_holding_ceiling,
            self.executable_target_holding_count,
            self.target_new_name_count,
            self.legacy_sizing_reference_positions,
        )
        if any(int(value) < 0 for value in integer_fields):
            raise ValueError("sizing position counts must be non-negative")
        if self.executable_target_holding_count > self.hard_holding_ceiling:
            raise ValueError("executable target cannot exceed hard holding ceiling")
        _ratio(self.policy_exposure_lower, name="policy_exposure_lower")
        _ratio(self.policy_exposure_target, name="policy_exposure_target")
        _ratio(self.hard_exposure_ceiling, name="hard_exposure_ceiling")
        _ratio(self.executable_target_exposure, name="executable_target_exposure")
        for name in (
            "nav_amount",
            "target_gross_amount",
            "current_gross_amount",
            "incremental_target_amount",
            "base_new_name_target_amount",
        ):
            if _finite(getattr(self, name), name=name) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if not self.sizing_contract_id:
            payload = {
                key: value
                for key, value in asdict(self).items()
                if key != "sizing_contract_id"
            }
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
            ).hexdigest()[:20]
            object.__setattr__(
                self,
                "sizing_contract_id",
                f"{self.decision_id}|{self.contract_version}|{digest}",
            )

    def as_dict(self) -> dict:
        return asdict(self)


def resolve_portfolio_sizing_intent(
    *,
    decision_id: str,
    nav_amount: float,
    current_exposure: float,
    current_holding_count: int,
    policy_band: PolicyBand,
    hard_holding_ceiling: int,
    hard_exposure_ceiling: float,
    legacy_sizing_reference_positions: int = 0,
    sizing_mode: str = "policy_executable_target",
) -> PortfolioSizingIntent:
    """Resolve the only financial denominator used for new-name sizing."""
    nav = _finite(nav_amount, name="nav_amount")
    if nav <= 0.0:
        raise ValueError("nav_amount must be positive")
    current_e = _ratio(current_exposure, name="current_exposure")
    current_k = max(int(current_holding_count), 0)
    hard_k = max(
        min(int(hard_holding_ceiling), int(policy_band.holding_ceiling)),
        current_k,
    )
    hard_e = min(
        _ratio(hard_exposure_ceiling, name="hard_exposure_ceiling"),
        float(policy_band.exposure_upper),
        float(policy_band.disaster_ceiling),
    )
    target_k = min(int(policy_band.holding_target), hard_k)
    target_e = min(float(policy_band.exposure_target), hard_e)
    target_amount = target_e * nav
    current_amount = current_e * nav
    incremental_amount = max(target_amount - current_amount, 0.0)
    new_name_count = max(target_k - current_k, 0)
    base_amount = (
        incremental_amount / new_name_count
        if new_name_count > 0 and incremental_amount > 0.0
        else 0.0
    )
    reasons: list[str] = []
    if target_k < int(policy_band.holding_target):
        reasons.append("hard_holding_ceiling_binds")
    if target_e + 1e-12 < float(policy_band.exposure_target):
        reasons.append("hard_exposure_ceiling_binds")
    if new_name_count == 0:
        reasons.append("no_new_name_target")
    if incremental_amount <= 1e-12:
        reasons.append("exposure_target_already_met")
    return PortfolioSizingIntent(
        decision_id=str(decision_id),
        nav_amount=nav,
        policy_holding_floor=int(policy_band.holding_floor),
        policy_holding_target=int(policy_band.holding_target),
        policy_exposure_lower=float(policy_band.exposure_lower),
        policy_exposure_target=float(policy_band.exposure_target),
        hard_holding_ceiling=hard_k,
        hard_exposure_ceiling=hard_e,
        executable_target_holding_count=target_k,
        executable_target_exposure=target_e,
        target_gross_amount=target_amount,
        current_gross_amount=current_amount,
        incremental_target_amount=incremental_amount,
        target_new_name_count=new_name_count,
        base_new_name_target_amount=base_amount,
        legacy_sizing_reference_positions=max(
            int(legacy_sizing_reference_positions), 0
        ),
        sizing_mode=str(sizing_mode),
        feasibility_state="bounded_target_resolved",
        binding_reasons=tuple(reasons),
    )


def attach_entry_sizing_envelopes(
    candidates: pd.DataFrame,
    *,
    intent: PortfolioSizingIntent,
    spendable_cash_amount: float,
    per_name_hard_cap: float,
    add_authorized: bool,
) -> pd.DataFrame:
    """Attach the final integer entry domain consumed by proposal generation."""
    data = candidates.copy()
    if data.empty:
        return data
    spendable = max(_finite(spendable_cash_amount, name="spendable_cash_amount"), 0.0)
    per_name_cap = _ratio(per_name_hard_cap, name="per_name_hard_cap")
    tier = data.get(
        "scap_v31_authority_tier", pd.Series("D", index=data.index)
    ).astype(str)
    fraction = tier.map(AUTHORITY_FRACTIONS).fillna(0.0)
    lot_cash = _lot_cash(data)
    valid_lot = lot_cash.gt(0.0) & lot_cash.notna()
    base_amount = float(intent.base_new_name_target_amount)
    authority_amount = fraction * base_amount
    base_lots = pd.Series(0, index=data.index, dtype=int)
    authority_lots = pd.Series(0, index=data.index, dtype=int)
    cash_lots = pd.Series(0, index=data.index, dtype=int)
    single_name_lots = pd.Series(0, index=data.index, dtype=int)
    if valid_lot.any():
        base_lots.loc[valid_lot] = (
            base_amount / lot_cash.loc[valid_lot]
        ).apply(math.floor).clip(lower=0).astype(int)
        authority_lots.loc[valid_lot] = (
            authority_amount.loc[valid_lot] / lot_cash.loc[valid_lot]
        ).apply(math.floor).clip(lower=0).astype(int)
        positive = tier.isin({"A", "B", "C"}) & base_lots.ge(1) & valid_lot
        authority_lots.loc[positive] = authority_lots.loc[positive].clip(lower=1)
        cash_lots.loc[valid_lot] = (
            spendable / lot_cash.loc[valid_lot]
        ).apply(math.floor).clip(lower=0).astype(int)
        single_name_lots.loc[valid_lot] = (
            (float(intent.nav_amount) * per_name_cap)
            / lot_cash.loc[valid_lot]
        ).apply(math.floor).clip(lower=0).astype(int)
    final_lots = pd.concat(
        [authority_lots, cash_lots, single_name_lots], axis=1
    ).min(axis=1).fillna(0).astype(int)
    final_lots.loc[tier.eq("D") | ~valid_lot] = 0
    binding = []
    for idx in data.index:
        if not bool(valid_lot.loc[idx]):
            binding.append("invalid_one_lot_amount")
        elif tier.loc[idx] == "D":
            binding.append("authority_tier_block")
        elif int(authority_lots.loc[idx]) <= int(cash_lots.loc[idx]) and int(
            authority_lots.loc[idx]
        ) <= int(single_name_lots.loc[idx]):
            binding.append("authority_size_cap")
        elif int(cash_lots.loc[idx]) <= int(single_name_lots.loc[idx]):
            binding.append("cash_capacity")
        else:
            binding.append("single_name_hard_cap")
    data["scap_v31_max_lots"] = final_lots
    data["scap_authority_fraction"] = fraction.astype(float)
    data["scap_sizing_base_target_amount"] = base_amount
    data["scap_sizing_authority_target_amount"] = authority_amount.astype(float)
    data["scap_sizing_base_lots"] = base_lots
    data["scap_sizing_cash_max_lots"] = cash_lots
    data["scap_sizing_single_name_max_lots"] = single_name_lots
    data["scap_sizing_authority_max_lots"] = authority_lots
    data["scap_sizing_final_max_lots"] = final_lots
    data["scap_sizing_binding_constraint"] = binding
    data["scap_sizing_contract_id"] = str(intent.sizing_contract_id)
    data["scap_sizing_contract_version"] = str(intent.contract_version)
    data["scap_v32_authority_size_mode"] = "policy_executable_target"
    data["scap_v32_authority_role"] = (
        "starter_size_with_authorized_add_path"
        if bool(add_authorized)
        else "final_authorized_size_add_unavailable"
    )
    return data


def _lot_cash(data: pd.DataFrame) -> pd.Series:
    for column in (
        "mainline_v3_one_lot_cash_required",
        "one_lot_cash_required",
        "lot_cash_required",
    ):
        if column in data.columns:
            values = pd.to_numeric(data[column], errors="coerce")
            if values.gt(0.0).any():
                return values
    for column in ("close_nominal", "close", "open_nominal", "open"):
        if column in data.columns:
            return pd.to_numeric(data[column], errors="coerce") * 100.0
    return pd.Series(float("nan"), index=data.index)
