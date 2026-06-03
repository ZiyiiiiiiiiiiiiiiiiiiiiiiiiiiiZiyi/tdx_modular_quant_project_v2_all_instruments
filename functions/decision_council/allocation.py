"""Deterministic portfolio allocation with auditable caps."""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import (
    GOVERNANCE_MAX_POSITION_WEIGHT,
    GOVERNANCE_MAX_PROTOTYPE_SECTOR_WEIGHT,
    GOVERNANCE_REALLOCATION_ITERATIONS,
    GOVERNANCE_REALLOCATION_MIN_WEIGHT,
    GOVERNANCE_VOLATILITY_CAP_MULTIPLIER,
)


def classify_prototype_sector(symbol: str, instrument_type: str | None = None) -> str:
    symbol = str(symbol).lower()
    code = symbol[2:]
    if instrument_type == "etf_fund":
        return "etf"
    if symbol.startswith("bj"):
        return "beijing_exchange"
    if code.startswith(("300", "301")):
        return "chinext"
    if code.startswith(("688", "689")):
        return "star_market"
    if symbol.startswith("sh"):
        return "shanghai_main"
    if symbol.startswith("sz"):
        return "shenzhen_main"
    return "other"


class PortfolioConstructionCommittee:
    """Translate ranked proposals and risk caps into auditable candidate weights."""

    def __init__(self, *, enable_sector_cap: bool = True):
        self.enable_sector_cap = bool(enable_sector_cap)

    def construct(self, candidates: pd.DataFrame, *, exposure_cap: float):
        return allocate_constrained_inverse_vol(
            candidates,
            exposure_cap=float(exposure_cap),
            max_sector_weight=GOVERNANCE_MAX_PROTOTYPE_SECTOR_WEIGHT if self.enable_sector_cap else 1.0,
        )


def allocate_constrained_inverse_vol(
    candidates: pd.DataFrame,
    *,
    exposure_cap: float = 1.0,
    max_position_weight: float = GOVERNANCE_MAX_POSITION_WEIGHT,
    max_sector_weight: float = GOVERNANCE_MAX_PROTOTYPE_SECTOR_WEIGHT,
    max_iterations: int = GOVERNANCE_REALLOCATION_ITERATIONS,
    min_residual: float = GOVERNANCE_REALLOCATION_MIN_WEIGHT,
    volatility_cap_multiplier: float = GOVERNANCE_VOLATILITY_CAP_MULTIPLIER,
) -> tuple[pd.DataFrame, dict]:
    data = candidates.copy()
    if data.empty or exposure_cap <= 0:
        empty = data.iloc[0:0].copy()
        empty["target_weight"] = pd.Series(dtype=float)
        return empty, _empty_diagnostics(float(exposure_cap))
    data["volatility_20"] = pd.to_numeric(data["volatility_20"], errors="coerce")
    fallback = data["volatility_20"].dropna().median()
    fallback = float(fallback) if pd.notna(fallback) and fallback > 0 else 0.02
    data["volatility_20"] = data["volatility_20"].fillna(fallback).clip(lower=1e-9)
    if "prototype_sector" not in data.columns:
        types = data.get("instrument_type", pd.Series(index=data.index, dtype=object))
        data["prototype_sector"] = [
            classify_prototype_sector(symbol, instrument_type)
            for symbol, instrument_type in zip(data["symbol"], types)
        ]
    raw = 1.0 / data["volatility_20"]
    raw = raw / raw.sum()
    data["raw_inverse_vol_weight"] = raw * float(exposure_cap)
    data["target_weight"] = 0.0
    residual = float(exposure_cap)
    for _ in range(int(max_iterations)):
        if residual < min_residual:
            break
        room_position = max_position_weight - data["target_weight"]
        sector_weight = data.groupby("prototype_sector")["target_weight"].transform("sum")
        room_sector = max_sector_weight - sector_weight
        room = pd.concat([room_position, room_sector], axis=1).min(axis=1).clip(lower=0.0)
        eligible = room > 1e-12
        if not eligible.any():
            break
        preferred = raw.where(eligible, 0.0)
        if preferred.sum() <= 0:
            break
        increment = residual * preferred / preferred.sum()
        increment = increment.clip(upper=room_position.clip(lower=0.0))
        for sector, indexes in data.groupby("prototype_sector").groups.items():
            sector_budget = max(
                float(max_sector_weight) - float(data.loc[indexes, "target_weight"].sum()),
                0.0,
            )
            proposed = float(increment.loc[indexes].sum())
            if proposed > sector_budget and proposed > 0:
                increment.loc[indexes] *= sector_budget / proposed
        distributed = float(increment.sum())
        data["target_weight"] += increment
        residual -= distributed
        if distributed < 1e-12:
            break

    uncapped_vol = _diagonal_portfolio_volatility(data["raw_inverse_vol_weight"], data["volatility_20"])
    constrained_vol = _diagonal_portfolio_volatility(data["target_weight"], data["volatility_20"])
    volatility_cap = volatility_cap_multiplier * uncapped_vol
    scale = min(1.0, volatility_cap / constrained_vol) if constrained_vol > 0 else 1.0
    data["target_weight"] *= scale
    reserve = max(float(exposure_cap) - float(data["target_weight"].sum()), 0.0)
    diagnostics = {
        "exposure_cap": float(exposure_cap),
        "uncapped_ex_ante_volatility": uncapped_vol,
        "constrained_ex_ante_volatility_before_scale": constrained_vol,
        "volatility_cap": volatility_cap,
        "volatility_scale_factor": scale,
        "constraint_cash_reserve": reserve,
        "max_position_weight": float(data["target_weight"].max()),
        "max_prototype_sector_weight": float(data.groupby("prototype_sector")["target_weight"].sum().max()),
    }
    return data, diagnostics


def _diagonal_portfolio_volatility(weights: pd.Series, volatilities: pd.Series) -> float:
    return float(np.sqrt(np.square(weights.to_numpy(dtype=float) * volatilities.to_numpy(dtype=float)).sum()))


def _empty_diagnostics(exposure_cap: float) -> dict:
    return {
        "exposure_cap": exposure_cap,
        "uncapped_ex_ante_volatility": 0.0,
        "constrained_ex_ante_volatility_before_scale": 0.0,
        "volatility_cap": 0.0,
        "volatility_scale_factor": 1.0,
        "constraint_cash_reserve": exposure_cap,
        "max_position_weight": 0.0,
        "max_prototype_sector_weight": 0.0,
    }
