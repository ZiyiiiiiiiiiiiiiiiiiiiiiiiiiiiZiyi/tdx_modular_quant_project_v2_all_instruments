"""Phase-one rule alpha proposals derived from the real feature table."""
from __future__ import annotations

import pandas as pd

from config import (
    GOVERNANCE_ALLOWED_INSTRUMENT_TYPES,
    GOVERNANCE_ALPHA_MODELS,
    GOVERNANCE_MIN_DAILY_AMOUNT,
)
from functions.decision_council.alpha import alpha_collapse_symbols, combine_alpha_proposals


MODEL_FEATURES = {
    "momentum_20": "ret_20",
    "mom_lowvol": "score_mom_lowvol",
    "ma_break": "close_to_ma20",
}


def build_rule_alpha_proposals(
    daily_features: pd.DataFrame,
    *,
    reputation_weights: dict[str, float] | None = None,
    model_names=GOVERNANCE_ALPHA_MODELS,
) -> pd.DataFrame:
    """Build deterministic proposal rows without pretending they are trained ML outputs."""
    reputation_weights = reputation_weights or {}
    data = daily_features.copy()
    rows = []
    for model_name in model_names:
        feature_col = MODEL_FEATURES[model_name]
        if feature_col not in data.columns:
            raise ValueError(f"Rule alpha feature is missing: {feature_col}")
        score = pd.to_numeric(data[feature_col], errors="coerce")
        volatility = pd.to_numeric(data.get("volatility_20"), errors="coerce").fillna(0.0)
        scale = score.abs().median()
        scale = float(scale) if pd.notna(scale) and scale > 1e-12 else 1.0
        predicted = (score / scale).clip(-5.0, 5.0) * 0.01
        part = pd.DataFrame(
            {
                "symbol": data["symbol"].astype(str),
                "model_name": model_name,
                "predicted_return_5d": predicted,
                "prediction_std": volatility.clip(lower=0.001),
                "reputation_weight": float(reputation_weights.get(model_name, 1.0)),
            }
        )
        rows.append(part)
    return pd.concat(rows, ignore_index=True)


def build_daily_candidates(
    daily_features: pd.DataFrame,
    *,
    reputation_weights: dict[str, float] | None = None,
    holding_days: dict[str, int] | None = None,
    candidate_limit: int | None = None,
    model_names=GOVERNANCE_ALPHA_MODELS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Combine rule proposals with tradable feature rows for president-policy input."""
    proposals = build_rule_alpha_proposals(
        daily_features,
        reputation_weights=reputation_weights,
        model_names=model_names,
    )
    combined = combine_alpha_proposals(proposals)
    collapses = alpha_collapse_symbols(proposals, combined, holding_days or {})
    source = daily_features.copy()
    keep = [
        "symbol",
        "instrument_type",
        "volatility_20",
        "close",
        "close_nominal",
        "amount",
        "amount_ma20",
        "is_trading",
        "abnormal_jump",
    ]
    source = source[[column for column in keep if column in source.columns]].copy()
    candidates = source.merge(combined, on="symbol", how="inner")
    candidates["expected_return_5d"] = (
        proposals.groupby("symbol")["predicted_return_5d"].mean().reindex(candidates["symbol"]).to_numpy()
    )
    candidates["alpha_collapse_exit"] = candidates["symbol"].isin(collapses)
    candidates = candidates[
        candidates["instrument_type"].astype(str).isin(GOVERNANCE_ALLOWED_INSTRUMENT_TYPES)
    ]
    if "is_trading" in candidates.columns:
        candidates = candidates[candidates["is_trading"].fillna(False)]
    if "abnormal_jump" in candidates.columns:
        candidates = candidates[~candidates["abnormal_jump"].fillna(True)]
    amount = pd.to_numeric(candidates.get("amount"), errors="coerce").fillna(0.0)
    rolling_amount = pd.to_numeric(candidates.get("amount_ma20", amount), errors="coerce").fillna(amount)
    candidates["liquidity_eligible"] = (
        (amount >= float(GOVERNANCE_MIN_DAILY_AMOUNT))
        & (rolling_amount >= float(GOVERNANCE_MIN_DAILY_AMOUNT))
    )
    candidates = candidates[candidates["liquidity_eligible"]]
    candidates = candidates.dropna(subset=["symbol", "volatility_20", "alpha_score"])
    candidates = candidates.sort_values(["alpha_score", "symbol"], ascending=[False, True])
    candidates["candidate_rank"] = range(1, len(candidates) + 1)
    if candidate_limit is not None:
        held = set((holding_days or {}).keys())
        candidates = candidates[
            (candidates["candidate_rank"] <= int(candidate_limit))
            | candidates["symbol"].astype(str).isin(held)
        ]
    return candidates.reset_index(drop=True), proposals
