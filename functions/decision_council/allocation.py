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

    def __init__(self, *, enable_sector_cap: bool = False):
        self.enable_sector_cap = bool(enable_sector_cap)

    def construct(self, candidates: pd.DataFrame, *, exposure_cap: float, covariance_matrix: pd.DataFrame | None = None):
        return allocate_constrained_inverse_vol(
            candidates,
            exposure_cap=float(exposure_cap),
            max_sector_weight=GOVERNANCE_MAX_PROTOTYPE_SECTOR_WEIGHT if self.enable_sector_cap else 1.0,
            covariance_matrix=covariance_matrix,
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
    covariance_matrix: pd.DataFrame | None = None,
    covariance_shrinkage: float = 0.35,
    max_risk_contribution: float = 0.25,
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
    if "target_weight" in data.columns and pd.to_numeric(
        data["target_weight"], errors="coerce"
    ).fillna(0.0).gt(0.0).any():
        requested = pd.to_numeric(data["target_weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
        raw = requested / requested.sum()
        max_position_weight = min(
            float(max_position_weight),
            float(requested.max()),
        )
        exposure_cap = min(float(exposure_cap), float(requested.sum()))
    else:
        edge = pd.to_numeric(
            data.get("edge_to_risk_10d", pd.Series(0.0, index=data.index)),
            errors="coerce",
        ).fillna(0.0).clip(lower=0.0)
        if edge.gt(0.0).any():
            raw = (1.0 / data["volatility_20"]) * (1.0 + edge.clip(upper=2.0))
        else:
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
    covariance_diagnostics = _apply_covariance_risk_budget(
        data,
        covariance_matrix=covariance_matrix,
        shrinkage=covariance_shrinkage,
        max_risk_contribution=max_risk_contribution,
    )
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
        **covariance_diagnostics,
    }
    return data, diagnostics


def _diagonal_portfolio_volatility(weights: pd.Series, volatilities: pd.Series) -> float:
    return float(np.sqrt(np.square(weights.to_numpy(dtype=float) * volatilities.to_numpy(dtype=float)).sum()))


def _apply_covariance_risk_budget(
    data: pd.DataFrame,
    *,
    covariance_matrix: pd.DataFrame | None,
    shrinkage: float,
    max_risk_contribution: float,
) -> dict:
    if covariance_matrix is None or covariance_matrix.empty or data.empty:
        return {
            "covariance_risk_model_used": False,
            "portfolio_covariance_volatility": 0.0,
            "max_risk_contribution": 0.0,
            "avg_pairwise_correlation": 0.0,
            "covariance_condition_number": 0.0,
        }
    symbols = data["symbol"].astype(str).tolist()
    cov = covariance_matrix.copy()
    cov.index = cov.index.astype(str)
    cov.columns = cov.columns.astype(str)
    available = [symbol for symbol in symbols if symbol in cov.index and symbol in cov.columns]
    if len(available) < 2:
        return {
            "covariance_risk_model_used": False,
            "portfolio_covariance_volatility": 0.0,
            "max_risk_contribution": 0.0,
            "avg_pairwise_correlation": 0.0,
            "covariance_condition_number": 0.0,
        }
    cov = cov.loc[available, available].astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    raw_sigma = cov.to_numpy(dtype=float)
    diagonal = np.diag(np.diag(raw_sigma))
    raw_condition = _condition_number(_nearest_positive_semidefinite(raw_sigma))
    lam = min(max(float(shrinkage), 0.0), 1.0)
    if raw_condition > 5000:
        lam = max(lam, 0.80)
    elif raw_condition > 1000:
        lam = max(lam, 0.65)
    elif raw_condition > 300:
        lam = max(lam, 0.50)
    sigma = lam * diagonal + (1.0 - lam) * raw_sigma
    sigma = _nearest_positive_semidefinite(sigma)
    indexer = data["symbol"].astype(str).isin(available)
    weights = data.loc[indexer, "target_weight"].to_numpy(dtype=float)
    if weights.sum() <= 0:
        return {
            "covariance_risk_model_used": True,
            "portfolio_covariance_volatility": 0.0,
            "max_risk_contribution": 0.0,
            "avg_pairwise_correlation": _avg_pairwise_correlation(sigma),
            "covariance_condition_number": _condition_number(sigma),
        }
    for _ in range(80):
        rc = _risk_contribution(weights, sigma)
        if rc.size == 0 or float(np.nanmax(rc)) <= float(max_risk_contribution):
            break
        offender = int(np.nanargmax(rc))
        scale = min(0.85 * float(max_risk_contribution) / max(float(rc[offender]), 1e-12), 0.75)
        scale = max(scale, 0.05)
        weights[offender] *= scale
    data.loc[indexer, "target_weight"] = weights
    variance = float(weights @ sigma @ weights)
    return {
        "covariance_risk_model_used": True,
        "portfolio_covariance_volatility": float(np.sqrt(max(variance, 0.0))),
        "max_risk_contribution": float(np.nanmax(_risk_contribution(weights, sigma))) if weights.sum() > 0 else 0.0,
        "avg_pairwise_correlation": _avg_pairwise_correlation(sigma),
        "covariance_condition_number": _condition_number(sigma),
        "covariance_shrinkage_used": float(lam),
        "raw_covariance_condition_number": float(raw_condition),
    }


def _risk_contribution(weights: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    variance = float(weights @ sigma @ weights)
    if variance <= 1e-18:
        return np.zeros_like(weights)
    marginal = sigma @ weights
    return (weights * marginal) / variance


def _nearest_positive_semidefinite(sigma: np.ndarray) -> np.ndarray:
    sigma = np.asarray(sigma, dtype=float)
    sigma = 0.5 * (sigma + sigma.T)
    min_diag = max(float(np.nanmedian(np.diag(sigma))) * 0.01, 1e-8)
    diag = np.diag(sigma).copy()
    diag[diag <= 0.0] = min_diag
    np.fill_diagonal(sigma, diag)
    try:
        values, vectors = np.linalg.eigh(sigma)
        floor = max(float(np.nanmedian(values[values > 0])) * 0.001 if np.any(values > 0) else 1e-8, 1e-10)
        values = np.clip(values, floor, None)
        stabilized = (vectors * values) @ vectors.T
        return 0.5 * (stabilized + stabilized.T)
    except Exception:
        return sigma


def _avg_pairwise_correlation(sigma: np.ndarray) -> float:
    diag = np.sqrt(np.clip(np.diag(sigma), 1e-12, None))
    corr = sigma / np.outer(diag, diag)
    if corr.shape[0] < 2:
        return 0.0
    mask = ~np.eye(corr.shape[0], dtype=bool)
    return float(np.nanmean(corr[mask]))


def _condition_number(sigma: np.ndarray) -> float:
    try:
        return float(np.linalg.cond(sigma))
    except Exception:
        return 0.0


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
        "covariance_risk_model_used": False,
        "portfolio_covariance_volatility": 0.0,
        "max_risk_contribution": 0.0,
        "avg_pairwise_correlation": 0.0,
        "covariance_condition_number": 0.0,
    }
