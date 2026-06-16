# -*- coding: utf-8 -*-
"""
PBO (Probability of Backtest Overfitting) via CSCV
(Combinatorial Symmetric Cross-Validation).

Reference: Bailey, Borwein, López de Prado, Zhu (2017)
"The Probability of Backtest Overfitting".

Core idea:
- Split backtest return series into S equal-sized blocks.
- For each C(S, S/2) combination, use half blocks as IS (in-sample)
  and the other half as OOS (out-of-sample).
- Rank strategies by IS performance, check if the IS-best strategy
  underperforms OOS (i.e., logit of OOS rank > 0 means overfitting).
- PBO = fraction of combinations where IS-best strategy has OOS
  performance below median.
"""
from __future__ import annotations

import itertools
from math import comb, log

import numpy as np
import pandas as pd


def split_return_series_into_blocks(daily_returns: pd.Series, n_blocks: int) -> list[pd.Series]:
    """Split a daily return series into n_blocks equal-length blocks."""
    n = len(daily_returns)
    if n < n_blocks:
        raise ValueError(f"Series length {n} < n_blocks {n_blocks}")
    block_size = n // n_blocks
    blocks = []
    for i in range(n_blocks):
        start = i * block_size
        end = start + block_size if i < n_blocks - 1 else n
        blocks.append(daily_returns.iloc[start:end])
    return blocks


def compute_block_sharpe(block_returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Annualized Sharpe ratio for one block."""
    if len(block_returns) < 2:
        return 0.0
    excess = block_returns - risk_free_rate / 252
    std = excess.std(ddof=1)
    if std == 0 or np.isnan(std):
        return 0.0
    return float(excess.mean() / std * np.sqrt(252))


def cscv_combinations(n_blocks: int) -> list[tuple[list[int], list[int]]]:
    """Generate all C(n_blocks, n_blocks//2) IS/OOS index splits."""
    half = n_blocks // 2
    all_indices = list(range(n_blocks))
    combinations = []
    for is_indices in itertools.combinations(all_indices, half):
        is_set = set(is_indices)
        oos_indices = [i for i in all_indices if i not in is_set]
        combinations.append((list(is_indices), oos_indices))
    return combinations


def compute_pbo(
    strategy_returns: dict[str, pd.Series],
    n_blocks: int = 16,
    risk_free_rate: float = 0.0,
    performance_metric: str = "sharpe",
) -> dict:
    """
    Compute Probability of Backtest Overfitting for a set of strategies.

    Parameters
    ----------
    strategy_returns : dict[str, pd.Series]
        Mapping of strategy name -> daily return series (aligned on same dates).
    n_blocks : int
        Number of blocks to split into (must be even). Default 16.
    risk_free_rate : float
        Annualized risk-free rate.
    performance_metric : str
        'sharpe' or 'total_return'.

    Returns
    -------
    dict with keys:
        pbo: float - probability of backtest overfitting (0-1)
        logits: list[float] - logit values for each combination
        mean_logit: float - mean logit (>0 suggests overfitting)
        n_combinations: int
        n_strategies: int
        is_best_oos_rank_matrix: DataFrame - IS-best strategy's OOS rank per combo
    """
    names = sorted(strategy_returns.keys())
    if len(names) < 2:
        return {
            "pbo": 0.0,
            "logits": [],
            "mean_logit": 0.0,
            "n_combinations": 0,
            "n_strategies": len(names),
            "is_best_oos_rank_matrix": pd.DataFrame(),
        }

    # Align all return series
    aligned = pd.DataFrame({name: strategy_returns[name] for name in names}).dropna()
    if len(aligned) < n_blocks:
        return {
            "pbo": np.nan,
            "logits": [],
            "mean_logit": np.nan,
            "n_combinations": 0,
            "n_strategies": len(names),
            "is_best_oos_rank_matrix": pd.DataFrame(),
        }

    blocks_per_strategy = {}
    for name in names:
        blocks_per_strategy[name] = split_return_series_into_blocks(aligned[name], n_blocks)

    def metric_fn(block_returns: pd.Series) -> float:
        if performance_metric == "sharpe":
            return compute_block_sharpe(block_returns, risk_free_rate)
        elif performance_metric == "total_return":
            return float((1 + block_returns).prod() - 1)
        else:
            raise ValueError(f"Unknown metric: {performance_metric}")

    combinations = cscv_combinations(n_blocks)
    n_strategies = len(names)
    n_combos = len(combinations)
    logits = []
    overfit_count = 0
    rank_records = []

    for combo_idx, (is_idx, oos_idx) in enumerate(combinations):
        # Compute IS and OOS performance for each strategy
        is_perf = {}
        oos_perf = {}
        for name in names:
            is_blocks = [blocks_per_strategy[name][i] for i in is_idx]
            oos_blocks = [blocks_per_strategy[name][i] for i in oos_idx]
            is_perf[name] = np.mean([metric_fn(b) for b in is_blocks])
            oos_perf[name] = np.mean([metric_fn(b) for b in oos_blocks])

        # Find IS-best strategy
        is_best = max(is_perf, key=is_perf.get)

        # Rank all strategies by OOS performance (1 = best)
        oos_ranked = sorted(oos_perf, key=oos_perf.get, reverse=True)
        oos_rank = {name: rank + 1 for rank, name in enumerate(oos_ranked)}

        is_best_oos_rank = oos_rank[is_best]
        # Logit: log(rank / (n+1-rank)) -- higher means worse OOS relative rank
        if is_best_oos_rank >= n_strategies:
            logit_val = float("inf")
        elif is_best_oos_rank <= 1:
            logit_val = float("-inf")
        else:
            logit_val = log(is_best_oos_rank / (n_strategies + 1 - is_best_oos_rank))

        logits.append(logit_val)

        # Check if IS-best is below median OOS
        median_rank = (n_strategies + 1) / 2
        if is_best_oos_rank > median_rank:
            overfit_count += 1

        rank_records.append({
            "combination": combo_idx,
            "is_best_strategy": is_best,
            "is_best_is_perf": is_perf[is_best],
            "is_best_oos_rank": is_best_oos_rank,
            "is_best_oos_perf": oos_perf[is_best],
            "logit": logit_val,
        })

    pbo = overfit_count / n_combos if n_combos > 0 else np.nan
    finite_logits = [x for x in logits if np.isfinite(x)]
    mean_logit = float(np.mean(finite_logits)) if finite_logits else np.nan

    return {
        "pbo": float(pbo),
        "logits": logits,
        "mean_logit": mean_logit,
        "n_combinations": n_combos,
        "n_strategies": n_strategies,
        "rank_matrix": pd.DataFrame(rank_records),
    }


def pbo_summary_report(result: dict) -> str:
    """Generate a human-readable PBO report."""
    lines = [
        "# PBO (Probability of Backtest Overfitting) Report",
        "",
        f"- Strategies evaluated: {result['n_strategies']}",
        f"- CSCV combinations: {result['n_combinations']}",
        f"- PBO: {result['pbo']:.2%}",
        f"- Mean logit: {result['mean_logit']:.4f}",
        "",
    ]
    if result["pbo"] > 0.5:
        lines.append("**WARNING**: PBO > 50% suggests high overfitting risk.")
    elif result["pbo"] > 0.3:
        lines.append("**CAUTION**: PBO > 30% suggests moderate overfitting risk.")
    else:
        lines.append("PBO is within acceptable range (< 30%).")

    if not result["rank_matrix"].empty:
        rm = result["rank_matrix"]
        lines.append("")
        lines.append("## IS-Best Strategy OOS Performance")
        for _, row in rm.iterrows():
            lines.append(
                f"- Combo {int(row['combination'])}: IS-best={row['is_best_strategy']}, "
                f"OOS rank={int(row['is_best_oos_rank'])}, "
                f"logit={row['logit']:.3f}"
            )

    return "\n".join(lines)
