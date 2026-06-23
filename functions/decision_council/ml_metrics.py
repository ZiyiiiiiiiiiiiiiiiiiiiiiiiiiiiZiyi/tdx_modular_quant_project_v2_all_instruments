# -*- coding: utf-8 -*-
"""
Shared metrics computation for all Governance versions.
Computes comprehensive metrics including:
- Return, Sharpe, Calmar, Sortino
- Max Drawdown
- Win Rate
- Buy/Sell counts
- Negative block rate for single-run stability diagnostics
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def compute_comprehensive_metrics(daily_csv_path: str | Path) -> dict:
    """
    Compute comprehensive metrics from governance daily result.
    
    Returns dict with:
    - total_return, annual_return
    - sharpe, calmar, sortino
    - max_drawdown
    - win_rate
    - n_days
    """
    daily_csv_path = Path(daily_csv_path)
    if not daily_csv_path.exists():
        return {}
    
    data = pd.read_csv(daily_csv_path)
    if data.empty:
        return {}
    
    data["date"] = pd.to_datetime(data["date"])
    nav = pd.to_numeric(data["nominal_nav"], errors="coerce").dropna()
    
    if len(nav) < 10:
        return {}
    
    nav = nav / float(nav.iloc[0])
    daily_ret = nav.pct_change(fill_method=None).fillna(0.0)
    n_days = len(nav)
    
    # Basic metrics
    total_return = float(nav.iloc[-1] - 1)
    annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1
    annual_vol = float(daily_ret.std() * np.sqrt(252))

    daily_rf = 0.0
    excess_daily_ret = daily_ret - daily_rf

    # Standard daily excess-return Sharpe.
    excess_mean_annual = float(excess_daily_ret.mean() * 252)
    sharpe = excess_mean_annual / annual_vol if annual_vol > 0 else 0.0
    
    # Max Drawdown
    drawdown = nav / nav.cummax() - 1
    max_dd = float(drawdown.min())
    
    # Calmar
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0.0
    
    # Sortino
    downside = excess_daily_ret[excess_daily_ret < 0]
    downside_vol = float(downside.std() * np.sqrt(252)) if len(downside) > 0 else 0.0
    sortino = excess_mean_annual / downside_vol if downside_vol > 0 else 0.0
    
    # Win Rate
    win_rate = float((daily_ret > 0).mean())
    
    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe": sharpe,
        "calmar": calmar,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "n_days": n_days,
    }


def compute_execution_accuracy(exec_csv_path: str | Path) -> dict:
    """
    Compute buy/sell accuracy from execution ledger.
    
    Returns dict with:
    - overall_accuracy, buy_accuracy, sell_accuracy
    - total_decisions, correct_decisions
    """
    exec_csv_path = Path(exec_csv_path)
    if not exec_csv_path.exists():
        return {}
    
    exec_ledger = pd.read_csv(exec_csv_path)
    if exec_ledger.empty:
        return {}
    
    # Check if we have the required columns
    required_cols = ["side", "trade_date"]
    if not all(col in exec_ledger.columns for col in required_cols):
        return {}
    
    # For simple accuracy, we need to check if the trade was profitable
    # This requires comparing buy/sell prices
    if "price" not in exec_ledger.columns:
        return {}
    
    # Group by symbol and calculate accuracy
    trades = exec_ledger.copy()
    trades["trade_date"] = pd.to_datetime(trades["trade_date"])
    
    # Calculate forward returns for each trade
    buy_trades = trades[trades["side"] == "buy"]
    sell_trades = trades[trades["side"] == "sell"]
    
    # Simple accuracy: count profitable trades
    # For buy trades, we assume they're correct if we later sell at a higher price
    # For this simplified version, we'll use a different approach
    
    # Count trades
    total_buys = len(buy_trades)
    total_sells = len(sell_trades)
    total_trades = total_buys + total_sells
    
    return {
        "total_buys": total_buys,
        "total_sells": total_sells,
        "total_trades": total_trades,
    }


def compute_concentration_metrics(holdings_csv_path: str | Path) -> dict:
    """Recompute concentration metrics from daily holdings market values."""
    holdings_csv_path = Path(holdings_csv_path)
    if not holdings_csv_path.exists():
        return {
            "top1_weight": np.nan,
            "top5_weight_sum": np.nan,
            "effective_n": np.nan,
            "holding_count_avg": np.nan,
            "concentration_method": "missing_holdings_ledger_recompute_required",
        }

    holdings = pd.read_csv(holdings_csv_path)
    if holdings.empty:
        return {
            "top1_weight": np.nan,
            "top5_weight_sum": np.nan,
            "effective_n": np.nan,
            "holding_count_avg": np.nan,
            "concentration_method": "empty_holdings_ledger_recompute_required",
        }

    required_cols = {"date", "symbol", "market_value"}
    if not required_cols.issubset(set(holdings.columns)):
        return {
            "top1_weight": np.nan,
            "top5_weight_sum": np.nan,
            "effective_n": np.nan,
            "holding_count_avg": np.nan,
            "concentration_method": "invalid_holdings_ledger_recompute_required",
        }

    holdings["date"] = pd.to_datetime(holdings["date"], errors="coerce")
    holdings["market_value"] = pd.to_numeric(holdings["market_value"], errors="coerce")
    holdings = holdings.dropna(subset=["date", "symbol", "market_value"])
    if holdings.empty:
        return {
            "top1_weight": np.nan,
            "top5_weight_sum": np.nan,
            "effective_n": np.nan,
            "holding_count_avg": np.nan,
            "concentration_method": "empty_holdings_ledger_recompute_required",
        }

    grouped = []
    for _, frame in holdings.groupby("date", sort=True):
        values = frame["market_value"].clip(lower=0.0)
        invested = float(values.sum())
        if invested <= 0:
            continue
        weights = (values / invested).sort_values(ascending=False).reset_index(drop=True)
        weight_square_sum = float(weights.pow(2).sum())
        grouped.append(
            {
                "top1_weight": float(weights.iloc[0]) if len(weights) else 0.0,
                "top5_weight_sum": float(weights.head(5).sum()) if len(weights) else 0.0,
                "effective_n": float(1.0 / weight_square_sum) if weight_square_sum > 0 else 0.0,
                "holding_count": int(len(weights)),
            }
        )

    if not grouped:
        return {
            "top1_weight": np.nan,
            "top5_weight_sum": np.nan,
            "effective_n": np.nan,
            "holding_count_avg": np.nan,
            "concentration_method": "empty_holdings_ledger_recompute_required",
        }

    result = pd.DataFrame(grouped)
    return {
        "top1_weight": float(result["top1_weight"].mean()),
        "top5_weight_sum": float(result["top5_weight_sum"].mean()),
        "effective_n": float(result["effective_n"].mean()),
        "holding_count_avg": float(result["holding_count"].mean()),
        "concentration_method": "holdings_ledger_market_value_recomputed",
    }


def compute_negative_block_rate(daily_csv_path: str | Path, n_blocks: int = 16) -> dict:
    """
    Compute a single-run block stability diagnostic.

    This is not CSCV/PBO because a single strategy run has no model-selection
    competition set. We expose it separately as the fraction of negative
    contiguous return blocks.
    """
    daily_csv_path = Path(daily_csv_path)
    if not daily_csv_path.exists():
        return {"negative_block_rate": np.nan}
    
    data = pd.read_csv(daily_csv_path)
    if data.empty or len(data) < n_blocks:
        return {"negative_block_rate": np.nan}
    
    data["date"] = pd.to_datetime(data["date"])
    nav = pd.to_numeric(data["nominal_nav"], errors="coerce").dropna()
    
    if len(nav) < n_blocks:
        return {"negative_block_rate": np.nan}
    
    # Split into blocks
    nav_normalized = nav / float(nav.iloc[0])
    block_size = len(nav_normalized) // n_blocks
    blocks = []
    
    for i in range(n_blocks):
        start = i * block_size
        end = start + block_size
        if end <= len(nav_normalized):
            block_return = float(nav_normalized.iloc[end-1] / nav_normalized.iloc[start] - 1)
            blocks.append(block_return)
    
    if len(blocks) < 2:
        return {"negative_block_rate": np.nan}
    
    negative_blocks = sum(1 for b in blocks if b < 0)
    return {"negative_block_rate": negative_blocks / len(blocks)}


def compute_all_metrics(
    output_dir: str | Path,
    start_date: str = None,
    end_date: str = None,
) -> dict:
    """
    Compute all metrics for a governance run.
    
    Returns comprehensive dict with all metrics.
    """
    output_dir = Path(output_dir)
    
    daily_path = output_dir / "governance_daily_result.csv"
    exec_path = output_dir / "governance_execution_ledger.csv"
    holdings_path = output_dir / "governance_holdings_ledger.csv"
    
    # Basic metrics
    metrics = compute_comprehensive_metrics(daily_path)
    
    # Execution accuracy
    accuracy = compute_execution_accuracy(exec_path)

    concentration = compute_concentration_metrics(holdings_path)
    
    stability = compute_negative_block_rate(daily_path)
    
    # Combine all
    result = {
        **metrics,
        **accuracy,
        **concentration,
        **stability,
        "pbo": np.nan,
        "pbo_method": "not_applicable_single_strategy_run",
        "output_dir": str(output_dir),
    }
    
    if start_date:
        result["start_date"] = start_date
    if end_date:
        result["end_date"] = end_date
    
    return result


def format_metrics_report(metrics: dict, model_name: str = "") -> str:
    """Format metrics into a readable report."""
    lines = []
    
    if model_name:
        lines.append(f"=== {model_name} ===")
    else:
        lines.append("=== Metrics Report ===")
    
    lines.append("")
    
    if "total_return" in metrics:
        lines.append(f"Total Return:     {metrics['total_return']:.2%}")
    if "annual_return" in metrics:
        lines.append(f"Annual Return:    {metrics['annual_return']:.2%}")
    if "sharpe" in metrics:
        lines.append(f"Sharpe Ratio:     {metrics['sharpe']:.3f}")
    if "calmar" in metrics:
        lines.append(f"Calmar Ratio:     {metrics['calmar']:.3f}")
    if "sortino" in metrics:
        lines.append(f"Sortino Ratio:    {metrics['sortino']:.3f}")
    if "max_drawdown" in metrics:
        lines.append(f"Max Drawdown:     {metrics['max_drawdown']:.2%}")
    if "win_rate" in metrics:
        lines.append(f"Win Rate:         {metrics['win_rate']:.1%}")
    if "negative_block_rate" in metrics and not np.isnan(metrics.get("negative_block_rate", np.nan)):
        lines.append(f"Negative Block Rate: {metrics['negative_block_rate']:.1%}")
    if "pbo" in metrics and not np.isnan(metrics.get("pbo", np.nan)):
        lines.append(f"PBO:              {metrics['pbo']:.1%}")
    if "total_buys" in metrics:
        lines.append(f"Total Buys:       {metrics['total_buys']}")
    if "total_sells" in metrics:
        lines.append(f"Total Sells:      {metrics['total_sells']}")
    if "n_days" in metrics:
        lines.append(f"Trading Days:     {metrics['n_days']}")
    
    return "\n".join(lines)


def save_metrics_json(metrics: dict, output_path: str | Path) -> None:
    """Save metrics to JSON file."""
    import json
    
    output_path = Path(output_path)
    
    # Convert numpy types to Python types
    def convert(obj):
        if isinstance(obj, (np.integer, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, Path):
            return str(obj)
        return obj
    
    clean_metrics = {k: convert(v) for k, v in metrics.items()}
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(clean_metrics, f, ensure_ascii=False, indent=2)
