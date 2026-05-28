# -*- coding: utf-8 -*-
import pandas as pd


def build_equal_strategy_ensemble(score_frames, score_col="score"):
    if not score_frames:
        return pd.DataFrame(columns=["date", "symbol", "ensemble_score", "source_count"])

    prepared = []
    for name, frame in score_frames.items():
        part = frame[["date", "symbol", score_col]].copy()
        part = part.rename(columns={score_col: f"{name}_score"})
        prepared.append(part)

    merged = prepared[0]
    for part in prepared[1:]:
        merged = merged.merge(part, on=["date", "symbol"], how="outer")

    score_columns = [col for col in merged.columns if col.endswith("_score")]
    merged["ensemble_score"] = merged[score_columns].mean(axis=1)
    merged["source_count"] = merged[score_columns].notna().sum(axis=1)
    return merged[["date", "symbol", "ensemble_score", "source_count"]]
