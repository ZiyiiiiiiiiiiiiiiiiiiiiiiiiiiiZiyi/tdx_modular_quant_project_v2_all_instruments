"""Small, dependency-light experiment hygiene helpers."""
from __future__ import annotations

import numpy as np
import pandas as pd


def block_bootstrap_mean_interval(
    values,
    *,
    block_length: int,
    samples: int = 1000,
    confidence: float = 0.95,
    random_seed: int = 42,
) -> dict:
    series = pd.to_numeric(pd.Series(values), errors="coerce").dropna().to_numpy()
    if len(series) < max(int(block_length) * 2, 4):
        return {
            "state": "insufficient",
            "nominal_sample_count": int(len(series)),
            "effective_sample_count": 0,
            "mean": np.nan,
            "lower": np.nan,
            "upper": np.nan,
        }
    block = max(int(block_length), 1)
    rng = np.random.default_rng(int(random_seed))
    starts = np.arange(0, len(series) - block + 1)
    means = []
    blocks_needed = int(np.ceil(len(series) / block))
    for _ in range(max(int(samples), 100)):
        sampled_starts = rng.choice(starts, size=blocks_needed, replace=True)
        sample = np.concatenate(
            [series[start : start + block] for start in sampled_starts]
        )[: len(series)]
        means.append(float(sample.mean()))
    alpha = (1.0 - float(confidence)) / 2.0
    return {
        "state": "ok",
        "nominal_sample_count": int(len(series)),
        "effective_sample_count": max(int(len(series) // block), 1),
        "mean": float(series.mean()),
        "lower": float(np.quantile(means, alpha)),
        "upper": float(np.quantile(means, 1.0 - alpha)),
        "block_length": block,
        "bootstrap_samples": max(int(samples), 100),
    }


def holm_adjust(p_values) -> list[float]:
    values = np.asarray(list(p_values), dtype=float)
    count = len(values)
    if count == 0:
        return []
    order = np.argsort(values)
    adjusted = np.empty(count, dtype=float)
    running = 0.0
    for rank, index in enumerate(order):
        candidate = min((count - rank) * float(values[index]), 1.0)
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted.tolist()
