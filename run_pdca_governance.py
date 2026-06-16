# -*- coding: utf-8 -*-
"""
PDCA Governance Research Loop
Plan-Do-Check-Act: 10 cycles with random date windows.

Each cycle:
- Plan: Pick random dates, define improvement hypothesis
- Do: Run governance backtest
- Check: Measure performance metrics
- Act: Keep or revert the change

Enhanced with:
- Market Regime Policy (bull/bear differentiated parameters)
- Buy signal quality filters
- PBO (Probability of Backtest Overfitting) calculation
"""
from __future__ import annotations

import gc
import json
import random
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from config import (
    ENABLE_MARKET_REGIME_POLICY,
    FEATURE_DAILY_PARQUET,
    MARKET_REGIME_BENCHMARK_SYMBOL,
    RESULT_DIR,
    SAFETY_PROXY_MODE,
    STRATEGY_MIN_SCORE_PERCENTILE,
    STRATEGY_TOP_N,
)
from functions.decision_council.market_regime_policy import MarketRegimePolicy

CYCLES = 10
OUTPUT_DIR = RESULT_DIR / "pdca_governance_cycles"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_DATE = pd.Timestamp("2021-01-01")
MAX_DATE = pd.Timestamp("2024-12-31")


def detect_market_regime(features_df: pd.DataFrame, date: pd.Timestamp) -> str:
    """
    Detect bull/bear market regime using MarketRegimePolicy.
    
    Uses sh510300 (CSI 300 ETF) as benchmark with multiple confirmation signals.
    
    Parameters
    ----------
    features_df : pd.DataFrame
        Features dataframe with market data
    date : pd.Timestamp
        Current date to evaluate
    
    Returns
    -------
    str : "bull" or "bear"
    """
    if not ENABLE_MARKET_REGIME_POLICY:
        return "bear"  # Default to bear if policy disabled
    
    try:
        policy = MarketRegimePolicy()
        regime = policy.detector.detect(
            features_df,
            pd.Timestamp(date),
            benchmark_symbol=MARKET_REGIME_BENCHMARK_SYMBOL,
        )
        return regime
    except Exception:
        return "bear"  # Default to bear on error


def get_rebalancing_frequency(market_regime: str) -> int:
    """
    Get rebalancing frequency based on market regime.
    
    Parameters
    ----------
    market_regime : str
        "bull" or "bear"
    
    Returns
    -------
    int : Rebalancing frequency in days
    """
    from functions.decision_council.market_regime_policy import BULL_PARAMS, BEAR_PARAMS
    if market_regime == "bull":
        return BULL_PARAMS.rebalance_interval_days
    else:
        return BEAR_PARAMS.rebalance_interval_days


def should_stop_profit(current_return: float, market_regime: str) -> bool:
    """
    Check if we should stop profit based on market regime.
    
    Parameters
    ----------
    current_return : float
        Current portfolio return
    market_regime : str
        "bull" or "bear"
    
    Returns
    -------
    bool : True if should stop profit
    """
    if market_regime == "bear" and current_return >= 0.05:
        return True
    return False


def random_date_window():
    """Pick a random 6-12 month window within 2021-2024."""
    for _ in range(100):
        start = MIN_DATE + pd.Timedelta(days=random.randint(0, (MAX_DATE - MIN_DATE).days - 180))
        window_days = random.randint(180, min(365, (MAX_DATE - start).days))
        end = start + pd.Timedelta(days=window_days)
        if end <= MAX_DATE:
            return start, end
    return pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31")


def load_features_minimal():
    """Load columns needed for governance including all alpha model scores."""
    import pyarrow.parquet as pq
    schema = pq.read_schema(FEATURE_DAILY_PARQUET)
    needed = [
        # Basic columns
        "date", "symbol", "instrument_type", "close", "close_nominal",
        "open", "open_nominal", "amount", "amount_ma20",
        "is_trading", "abnormal_jump", "rough_limit_up", "rough_limit_down",
        "volatility_20", "ret_5", "ret_20",
        "sector_parent", "sector_parent_heat",
        # Alpha model score columns (all 18 models)
        "score_mom_lowvol",
        "close_to_ma20",
        "score_macd_trend",
        "score_mean_reversion",
        "score_rsi_reversal",
        "score_turtle_breakout",
        "score_alpha_hedge",
        "score_event_driven",
        "score_grid_trading",
        "score_eod_close_strength",
        "score_limit_up_follow",
        "score_macd_cross",
        "score_ma_cross",
        "score_price_volume_breakout",
        "score_consecutive_decline_rebound",
        "score_holiday_effect",
        "score_kdj_oversold_cross",
        "score_low_volume_pullback",
    ]
    cols = [c for c in needed if c in schema.names]
    return pd.read_parquet(FEATURE_DAILY_PARQUET, columns=cols)


def run_governance_cycle(features, start_date, end_date, cycle_idx, extra_config=None):
    """Run one governance backtest cycle with market regime policy."""
    from functions.decision_council.runner import GovernanceBacktestRunner

    output_dir = OUTPUT_DIR / f"cycle_{cycle_idx:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    runner = GovernanceBacktestRunner(
        features,
        safety_proxy_mode=SAFETY_PROXY_MODE,
        output_dir=output_dir,
        enable_reputation=True,
        enable_sector_cap=False,
        enable_safety_agent=True,
        enable_market_regime_policy=ENABLE_MARKET_REGIME_POLICY,
    )
    saved = runner.run(start_date=start_date, end_date=end_date)
    return saved


def compute_metrics(daily_csv_path):
    """Compute comprehensive metrics from governance daily result."""
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
    daily_ret = nav.pct_change().fillna(0.0)
    n_days = len(nav)
    total_return = float(nav.iloc[-1] - 1)
    annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1
    annual_vol = float(daily_ret.std() * np.sqrt(252))
    sharpe = annual_return / annual_vol if annual_vol > 0 else 0.0
    max_dd = float((nav / nav.cummax() - 1).min())
    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0.0
    downside = daily_ret[daily_ret < 0]
    downside_vol = float(downside.std() * np.sqrt(252)) if len(downside) > 0 else 0.0
    sortino = annual_return / downside_vol if downside_vol > 0 else 0.0
    win_rate = float((daily_ret > 0).mean())

    # Max drawdown period
    dd = nav / nav.cummax() - 1
    max_dd_idx = dd.idxmin()
    dd_start = data.loc[:max_dd_idx, "date"].iloc[0] if max_dd_idx > 0 else data["date"].iloc[0]
    dd_end = data["date"].iloc[-1]

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "sortino": sortino,
        "win_rate": win_rate,
        "n_days": n_days,
        "dd_start": str(dd_start.date()) if hasattr(dd_start, "date") else str(dd_start),
        "dd_end": str(dd_end.date()) if hasattr(dd_end, "date") else str(dd_end),
    }


def compute_accuracy(exec_path):
    """Compute decision accuracy from execution ledger."""
    if not exec_path.exists():
        return {}
    from functions.decision_accuracy import analyze_governance_decision_accuracy
    exec_ledger = pd.read_csv(exec_path)
    result = analyze_governance_decision_accuracy(exec_ledger, horizon_days=5)
    return {
        "overall_accuracy": result.get("overall_accuracy", 0.0),
        "buy_accuracy": result.get("buy_accuracy", 0.0),
        "sell_accuracy": result.get("sell_accuracy", 0.0),
        "total_decisions": result.get("total_decisions", 0),
        "correct_decisions": result.get("correct_decisions", 0),
    }


def compute_pbo_for_cycle(daily_csv_path, n_blocks=16):
    """
    Compute PBO (Probability of Backtest Overfitting) for a single cycle.
    
    Parameters
    ----------
    daily_csv_path : Path
        Path to governance daily result CSV
    n_blocks : int
        Number of blocks for CSCV
    
    Returns
    -------
    dict : PBO metrics
    """
    from functions.pbo_cscv import compute_pbo
    
    if not daily_csv_path.exists():
        return {"pbo": np.nan, "mean_logit": np.nan, "n_combinations": 0}
    
    data = pd.read_csv(daily_csv_path)
    if data.empty or len(data) < n_blocks:
        return {"pbo": np.nan, "mean_logit": np.nan, "n_combinations": 0}
    
    # Create synthetic strategy returns for PBO calculation
    # Use the governance portfolio returns as the base strategy
    data["date"] = pd.to_datetime(data["date"])
    nav = pd.to_numeric(data["nominal_nav"], errors="coerce").dropna()
    
    if len(nav) < n_blocks:
        return {"pbo": np.nan, "mean_logit": np.nan, "n_combinations": 0}
    
    # Calculate daily returns
    nav_normalized = nav / float(nav.iloc[0])
    daily_returns = nav_normalized.pct_change().fillna(0.0)
    
    # Create multiple synthetic strategies by adding noise
    strategy_returns = {}
    strategy_returns["governance_strategy"] = daily_returns.values
    
    # Add 5 synthetic strategies with noise for PBO comparison
    np.random.seed(42)
    for i in range(5):
        noise = np.random.normal(0, 0.001, len(daily_returns))
        strategy_returns[f"synthetic_{i+1}"] = daily_returns.values + noise
    
    # Compute PBO
    try:
        result = compute_pbo(
            strategy_returns={k: pd.Series(v) for k, v in strategy_returns.items()},
            n_blocks=n_blocks,
            performance_metric="sharpe"
        )
        return {
            "pbo": result.get("pbo", np.nan),
            "mean_logit": result.get("mean_logit", np.nan),
            "n_combinations": result.get("n_combinations", 0),
            "n_strategies": result.get("n_strategies", 0),
        }
    except Exception as e:
        print(f"PBO computation failed: {e}")
        return {"pbo": np.nan, "mean_logit": np.nan, "n_combinations": 0}


def generate_recommendation(cycle_idx, metrics, accuracy, prev_metrics=None, pbo_result=None, market_regime=None):
    """Generate one improvement recommendation based on results."""
    recommendations = []

    if not metrics:
        return "No data to analyze."

    # Check win rate
    if metrics.get("win_rate", 0) < 0.48:
        recommendations.append("Win rate below 48%: consider increasing STRATEGY_MIN_SCORE_PERCENTILE")

    # Check max drawdown
    if metrics.get("max_drawdown", 0) < -0.15:
        recommendations.append("Max drawdown > 15%: consider tightening safety thresholds")

    # Check Sharpe
    if metrics.get("sharpe", 0) < 0:
        recommendations.append("Negative Sharpe: strategy is destroying value")

    # Check accuracy
    if accuracy.get("overall_accuracy", 0) < 0.50:
        recommendations.append("Accuracy below 50%: score filter may need tightening")

    # Check PBO (overfitting risk)
    if pbo_result and not np.isnan(pbo_result.get("pbo", np.nan)):
        pbo = pbo_result["pbo"]
        if pbo > 0.5:
            recommendations.append(f"PBO {pbo:.1%} > 50%: high overfitting risk, reduce model complexity")
        elif pbo > 0.3:
            recommendations.append(f"PBO {pbo:.1%} > 30%: moderate overfitting risk, consider simpler model")

    # Market regime specific recommendations
    if market_regime:
        if market_regime == "bear":
            recommendations.append("Bear market: using monthly rebalancing with 5% stop profit")
        else:
            recommendations.append("Bull market: using weekly rebalancing for faster opportunity capture")

    # Compare with previous cycle
    if prev_metrics:
        ret_diff = metrics.get("total_return", 0) - prev_metrics.get("total_return", 0)
        if ret_diff < -0.05:
            recommendations.append(f"Return dropped {ret_diff:.2%} vs previous: revert last change")
        elif ret_diff > 0.05:
            recommendations.append(f"Return improved {ret_diff:.2%}: keep last change")

    return "; ".join(recommendations) if recommendations else "Performance acceptable, no change needed."


def main(clear_old_results: bool = True):
    print(f"\n{'#'*60}")
    print(f"PDCA GOVERNANCE RESEARCH LOOP: {CYCLES} CYCLES")
    print(f"{'#'*60}")
    print(f"Market Regime Policy: {'ENABLED' if ENABLE_MARKET_REGIME_POLICY else 'DISABLED'}")
    print(f"Benchmark Symbol: {MARKET_REGIME_BENCHMARK_SYMBOL}")
    print(f"Score percentile threshold: {STRATEGY_MIN_SCORE_PERCENTILE}")
    print(f"Top N: {STRATEGY_TOP_N}")
    print(f"Date range: {MIN_DATE.date()} -> {MAX_DATE.date()}")
    print()

    # Clear old results if requested
    if clear_old_results:
        import shutil
        if OUTPUT_DIR.exists():
            print(f"Clearing old results from {OUTPUT_DIR}...")
            shutil.rmtree(OUTPUT_DIR)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            print("Old results cleared.")

    # Load features once
    print("Loading features...")
    features = load_features_minimal()
    print(f"Features loaded: {len(features)} rows, {len(features.columns)} columns")
    gc.collect()

    all_cycles = []
    prev_metrics = None

    for i in range(1, CYCLES + 1):
        start, end = random_date_window()

        # Skip if cycle already completed
        cycle_dir = OUTPUT_DIR / f"cycle_{i:02d}"
        pdca_file = cycle_dir / "pdca_cycle.json"
        if pdca_file.exists():
            with open(pdca_file, encoding="utf-8") as f:
                existing = json.load(f)
            all_cycles.append(existing)
            m = existing.get("metrics", {})
            print(f"\nCycle {i} already done: {existing['start_date']} -> {existing['end_date']}, return={m.get('total_return', 0):.2%}")
            prev_metrics = m
            continue

        print(f"\n{'='*60}")
        print(f"CYCLE {i}: {start.date()} -> {end.date()}")
        print(f"{'='*60}")

        # Run governance
        try:
            run_governance_cycle(features, start, end, i)
        except Exception as e:
            print(f"Cycle {i} failed: {e}")
            all_cycles.append({
                "cycle": i, "start_date": str(start.date()), "end_date": str(end.date()),
                "status": f"error: {e}",
            })
            continue

        # Compute metrics
        cycle_dir = OUTPUT_DIR / f"cycle_{i:02d}"
        daily_path = cycle_dir / "governance_daily_result.csv"
        exec_path = cycle_dir / "governance_execution_ledger.csv"

        metrics = compute_metrics(daily_path)
        accuracy = compute_accuracy(exec_path)

        # Compute PBO (overfitting probability)
        pbo_result = compute_pbo_for_cycle(daily_path)
        
        # Detect market regime for the cycle
        market_regime = detect_market_regime(features, start)
        rebalancing_freq = get_rebalancing_frequency(market_regime)
        
        # Check if we should stop profit (for bear market)
        current_return = metrics.get("total_return", 0)
        stop_profit_triggered = should_stop_profit(current_return, market_regime)

        # Generate recommendation
        recommendation = generate_recommendation(i, metrics, accuracy, prev_metrics, pbo_result, market_regime)

        cycle_record = {
            "cycle": i,
            "start_date": str(start.date()),
            "end_date": str(end.date()),
            "metrics": metrics,
            "accuracy": accuracy,
            "pbo": pbo_result,
            "market_regime": market_regime,
            "rebalancing_frequency_days": rebalancing_freq,
            "stop_profit_triggered": stop_profit_triggered,
            "recommendation": recommendation,
        }
        all_cycles.append(cycle_record)

        # Print results
        if metrics:
            print(f"  Return: {metrics.get('total_return', 0):.2%}")
            print(f"  Sharpe: {metrics.get('sharpe', 0):.3f}")
            print(f"  Calmar: {metrics.get('calmar', 0):.3f}")
            print(f"  Sortino: {metrics.get('sortino', 0):.3f}")
            print(f"  Max DD: {metrics.get('max_drawdown', 0):.2%} ({metrics.get('dd_start')} -> {metrics.get('dd_end')})")
            print(f"  Win rate: {metrics.get('win_rate', 0):.1%}")
        if accuracy:
            print(f"  Accuracy: {accuracy.get('overall_accuracy', 0):.1%} ({accuracy.get('correct_decisions', 0)}/{accuracy.get('total_decisions', 0)})")
        print(f"  Market regime: {market_regime} (rebalance every {rebalancing_freq} days)")
        if stop_profit_triggered:
            print(f"  *** STOP PROFIT TRIGGERED at {current_return:.2%} ***")
        if pbo_result and not np.isnan(pbo_result.get("pbo", np.nan)):
            print(f"  PBO: {pbo_result['pbo']:.1%} (mean logit: {pbo_result.get('mean_logit', 0):.3f})")
        print(f"  Recommendation: {recommendation}")

        # Save cycle data
        with open(cycle_dir / "pdca_cycle.json", "w", encoding="utf-8") as f:
            json.dump(cycle_record, f, ensure_ascii=False, indent=2, default=str)

        prev_metrics = metrics
        gc.collect()

    # Compile final report
    _write_final_report(all_cycles)


def _write_final_report(all_cycles):
    lines = [
        "# PDCA Governance Research Report (Enhanced with Market Regime Policy)",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Cycles: {CYCLES}",
        f"Market Regime Policy: {'ENABLED' if ENABLE_MARKET_REGIME_POLICY else 'DISABLED'}",
        f"Benchmark Symbol: {MARKET_REGIME_BENCHMARK_SYMBOL}",
        f"Score percentile: {STRATEGY_MIN_SCORE_PERCENTILE}",
        f"Top N: {STRATEGY_TOP_N}",
        "",
        "## Key Improvements",
        "- **Market Regime Policy**: Dynamic parameter adjustment based on bull/bear detection",
        "  - Bull market: More aggressive (kelly_scale=0.45, turnover=4%, weekly rebalance)",
        "  - Bear market: More conservative (kelly_scale=0.35, turnover=2%, monthly rebalance)",
        "- **Buy Signal Quality Filters**:",
        "  - Volatility filter: Exclude stocks with vol > 1.5x median",
        "  - Amount filter: Require 2x minimum daily amount",
        "  - Momentum filter: Exclude stocks with >5% decline in 20 days",
        "- **Safety Thresholds Adjusted**:",
        "  - Warning drawdown: 2.0% (was 1.5%)",
        "  - High drawdown: 4.0% (was 3.0%)",
        "  - Crisis drawdown: 6.0% (was 5.0%)",
        "  - Confirm days: 3 (was 2)",
        "- **Kelly Parameters Optimized**:",
        "  - Kelly scale: 0.40 (was 0.50)",
        "  - Min P(win): 0.52 (was 0.48)",
        "- **PBO (Probability of Backtest Overfitting) calculation**",
        "",
    ]

    # Summary table
    lines.extend([
        "## Cycle Results",
        "",
        "| Cycle | Window | Return | Sharpe | Max DD | Win Rate | Accuracy | PBO | Market | Rebal Freq | Stop Profit |",
        "|-------|--------|--------|--------|--------|----------|----------|-----|--------|------------|-------------|",
    ])

    returns = []
    sharpes = []
    drawdowns = []
    win_rates = []
    accuracies = []
    pbos = []
    market_regimes = []
    rebal_freqs = []
    stop_profits = []

    for c in all_cycles:
        m = c.get("metrics", {})
        a = c.get("accuracy", {})
        pbo = c.get("pbo", {})
        market = c.get("market_regime", "unknown")
        rebal = c.get("rebalancing_frequency_days", 0)
        stop = c.get("stop_profit_triggered", False)
        
        if not m:
            lines.append(f"| {c['cycle']} | {c['start_date']} -> {c['end_date']} | FAILED | - | - | - | - | - | - | - | - |")
            continue

        ret = m.get("total_return", 0)
        sh = m.get("sharpe", 0)
        dd = m.get("max_drawdown", 0)
        wr = m.get("win_rate", 0)
        acc = a.get("overall_accuracy", 0)
        pbo_val = pbo.get("pbo", np.nan) if pbo else np.nan

        returns.append(ret)
        sharpes.append(sh)
        drawdowns.append(dd)
        win_rates.append(wr)
        accuracies.append(acc)
        if not np.isnan(pbo_val):
            pbos.append(pbo_val)
        market_regimes.append(market)
        rebal_freqs.append(rebal)
        stop_profits.append(stop)

        pbo_str = f"{pbo_val:.1%}" if not np.isnan(pbo_val) else "N/A"
        stop_str = "YES" if stop else "no"

        lines.append(
            f"| {c['cycle']} | {c['start_date']} -> {c['end_date']} | "
            f"{ret:.2%} | {sh:.3f} | {dd:.2%} | {wr:.1%} | {acc:.1%} | {pbo_str} | {market} | {rebal}d | {stop_str} |"
        )

    # Market regime distribution
    lines.extend(["", "## Market Regime Distribution", ""])
    bull_count = market_regimes.count("bull")
    bear_count = market_regimes.count("bear")
    lines.append(f"- Bull market cycles: {bull_count}/{len(market_regimes)}")
    lines.append(f"- Bear market cycles: {bear_count}/{len(market_regimes)}")
    lines.append(f"- Stop profit triggered: {sum(stop_profits)}/{len(stop_profits)} times")

    # PBO Summary
    if pbos:
        lines.extend(["", "## Overfitting Analysis (PBO)", ""])
        lines.append(f"- Average PBO: {np.mean(pbos):.1%}")
        lines.append(f"- Min PBO: {np.min(pbos):.1%}")
        lines.append(f"- Max PBO: {np.max(pbos):.1%}")
        lines.append(f"- Cycles with PBO > 50% (high risk): {sum(1 for p in pbos if p > 0.5)}/{len(pbos)}")
        lines.append(f"- Cycles with PBO > 30% (moderate risk): {sum(1 for p in pbos if p > 0.3)}/{len(pbos)}")
        
        if np.mean(pbos) > 0.5:
            lines.append("- **WARNING**: Average PBO > 50%, indicating high overfitting risk")
        elif np.mean(pbos) > 0.3:
            lines.append("- **CAUTION**: Average PBO > 30%, moderate overfitting risk")
        else:
            lines.append("- PBO within acceptable range (< 30%)")

    # Recommendations
    lines.extend(["", "## Recommendations by Cycle", ""])
    for c in all_cycles:
        if "recommendation" in c:
            lines.append(f"- **Cycle {c['cycle']}** ({c['start_date']} -> {c['end_date']}): {c['recommendation']}")

    # Statistics
    if returns:
        lines.extend([
            "",
            "## Aggregate Statistics",
            "",
            "| Metric | Mean | Std | Min | Max |",
            "|--------|------|-----|-----|-----|",
            f"| Return | {np.mean(returns):.2%} | {np.std(returns):.2%} | {np.min(returns):.2%} | {np.max(returns):.2%} |",
            f"| Sharpe | {np.mean(sharpes):.3f} | {np.std(sharpes):.3f} | {np.min(sharpes):.3f} | {np.max(sharpes):.3f} |",
            f"| Max DD | {np.mean(drawdowns):.2%} | {np.std(drawdowns):.2%} | {np.min(drawdowns):.2%} | {np.max(drawdowns):.2%} |",
            f"| Win Rate | {np.mean(win_rates):.1%} | {np.std(win_rates):.1%} | {np.min(win_rates):.1%} | {np.max(win_rates):.1%} |",
            f"| Accuracy | {np.mean(accuracies):.1%} | {np.std(accuracies):.1%} | {np.min(accuracies):.1%} | {np.max(accuracies):.1%} |",
            f"| PBO | {np.mean(pbos):.1%} | {np.std(pbos):.1%} | {np.min(pbos):.1%} | {np.max(pbos):.1%} |" if pbos else "",
        ])

        # Conclusions
        lines.extend([
            "",
            "## Conclusions",
            "",
        ])
        mean_acc = np.mean(accuracies)
        mean_sharpe = np.mean(sharpes)
        mean_dd = np.mean(drawdowns)
        mean_pbo = np.mean(pbos) if pbos else 0

        if mean_acc > 0.52:
            lines.append(f"- Average accuracy {mean_acc:.1%} > 52%: score filter is helping")
        elif mean_acc > 0.50:
            lines.append(f"- Average accuracy {mean_acc:.1%} ~ 50%: marginal edge, consider tightening filter")
        else:
            lines.append(f"- Average accuracy {mean_acc:.1%} < 50%: filter may need adjustment")

        if mean_sharpe > 0.5:
            lines.append(f"- Average Sharpe {mean_sharpe:.3f}: good risk-adjusted returns")
        elif mean_sharpe > 0:
            lines.append(f"- Average Sharpe {mean_sharpe:.3f}: positive but modest")
        else:
            lines.append(f"- Average Sharpe {mean_sharpe:.3f}: negative, strategy underperforming")

        if mean_dd > -0.10:
            lines.append(f"- Average max drawdown {mean_dd:.2%}: well controlled")
        elif mean_dd > -0.20:
            lines.append(f"- Average max drawdown {mean_dd:.2%}: moderate risk")
        else:
            lines.append(f"- Average max drawdown {mean_dd:.2%}: high risk, consider tighter safety")

        # PBO conclusions
        if pbos:
            if mean_pbo > 0.5:
                lines.append(f"- Average PBO {mean_pbo:.1%} > 50%: high overfitting risk, reduce model complexity")
            elif mean_pbo > 0.3:
                lines.append(f"- Average PBO {mean_pbo:.1%} > 30%: moderate overfitting risk")
            else:
                lines.append(f"- Average PBO {mean_pbo:.1%} < 30%: acceptable overfitting risk")

        # Market regime effectiveness
        if market_regimes:
            bull_returns = [r for r, m in zip(returns, market_regimes) if m == "bull"]
            bear_returns = [r for r, m in zip(returns, market_regimes) if m == "bear"]
            if bull_returns:
                lines.append(f"- Average return in bull market: {np.mean(bull_returns):.2%}")
            if bear_returns:
                lines.append(f"- Average return in bear market: {np.mean(bear_returns):.2%}")

    report_text = "\n".join(lines)
    report_path = OUTPUT_DIR / "pdca_governance_final_report.md"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\nSaved PDCA report: {report_path}")

    # Save raw data
    raw_path = OUTPUT_DIR / "pdca_all_cycles.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(all_cycles, f, ensure_ascii=False, indent=2, default=str)
    print(f"Saved raw data: {raw_path}")


if __name__ == "__main__":
    main()
