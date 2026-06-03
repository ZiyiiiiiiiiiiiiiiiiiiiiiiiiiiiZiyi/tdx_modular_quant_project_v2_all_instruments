"""Alpha-proposal aggregation and collapse consensus."""
from __future__ import annotations

import pandas as pd


def combine_alpha_proposals(proposals: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "model_name", "predicted_return_5d", "prediction_std", "reputation_weight"}
    missing = sorted(required - set(proposals.columns))
    if missing:
        raise ValueError(f"Alpha proposals missing columns: {missing}")
    data = proposals.copy()
    data["predicted_return_5d"] = pd.to_numeric(data["predicted_return_5d"], errors="coerce")
    data["prediction_std"] = pd.to_numeric(data["prediction_std"], errors="coerce").fillna(0.0)
    data["reputation_weight"] = pd.to_numeric(data["reputation_weight"], errors="coerce").fillna(1.0)
    median_std = max(float(data["prediction_std"].median()), 1e-12)
    data["confidence"] = (
        1.0 - data["prediction_std"] / (data["predicted_return_5d"].abs() + median_std)
    ).clip(0.0, 1.0)
    data["alpha_percentile_model"] = data.groupby("model_name")["predicted_return_5d"].rank(pct=True)
    data["vote_weight"] = data["confidence"] * data["reputation_weight"]
    data["weighted_rank"] = data["alpha_percentile_model"] * data["vote_weight"]
    data["weighted_confidence"] = data["confidence"] * data["reputation_weight"]
    grouped = data.groupby("symbol", as_index=False).agg(
        weighted_rank=("weighted_rank", "sum"),
        vote_weight=("vote_weight", "sum"),
        aggregate_confidence_numerator=("weighted_confidence", "sum"),
        reputation_sum=("reputation_weight", "sum"),
        model_count=("model_name", "nunique"),
    )
    grouped["alpha_score"] = grouped["weighted_rank"] / grouped["vote_weight"].replace(0, float("nan"))
    grouped["alpha_score"] = grouped["alpha_score"].fillna(0.0)
    grouped["alpha_percentile"] = grouped["alpha_score"].rank(pct=True)
    grouped["aggregate_confidence"] = (
        grouped["aggregate_confidence_numerator"] / grouped["reputation_sum"].replace(0, float("nan"))
    ).fillna(0.0)
    return grouped.drop(columns=["aggregate_confidence_numerator", "reputation_sum"])


def alpha_collapse_symbols(proposals: pd.DataFrame, combined: pd.DataFrame, holding_days: dict[str, int]) -> frozenset[str]:
    data = proposals.copy()
    if "confidence" not in data.columns:
        std = pd.to_numeric(data["prediction_std"], errors="coerce").fillna(0.0)
        predicted = pd.to_numeric(data["predicted_return_5d"], errors="coerce")
        median_std = max(float(std.median()), 1e-12)
        data["confidence"] = (1.0 - std / (predicted.abs() + median_std)).clip(0.0, 1.0)
    data["confidence"] = pd.to_numeric(data["confidence"], errors="coerce").fillna(0.0)
    negative = data[(pd.to_numeric(data["predicted_return_5d"], errors="coerce") < 0) & (data["confidence"] >= 0.60)]
    counts = negative.groupby("symbol")["model_name"].nunique()
    percentile = combined.set_index("symbol")["alpha_percentile"]
    symbols = [
        symbol for symbol, days in holding_days.items()
        if int(days) >= 2 and float(percentile.get(symbol, 1.0)) <= 0.15 and int(counts.get(symbol, 0)) >= 2
    ]
    return frozenset(symbols)
