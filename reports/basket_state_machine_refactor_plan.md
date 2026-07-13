# Basket State Machine Refactor Plan

## Objective

The governance path should move from single-name entry gating to basket-level
entry and replacement. Single stocks still receive scores, but trading intent is
created only after a diversified 3-8 name basket passes quality, liquidity, and
risk checks.

## Five-Layer Data Separation

1. Raw market layer
   - TDX `.day`, index constituents, adjustment factors, fundamentals, money flow.
   - Responsibility: ingestion, point-in-time checks, coverage diagnostics.

2. Feature layer
   - Momentum, reversal, volatility, liquidity, MACD, RSI, turtle breakout,
     price-volume, fundamentals, event proxies, alternative-data proxies.
   - Responsibility: deterministic feature generation only. No buy/sell logic.

3. Factor judge layer
   - IC, rank IC, quantile spread, turnover cost, redundancy, coverage.
   - Responsibility: produce the fixed promote/watchlist pool and factor contract.

4. Alpha matrix layer
   - Select non-near-relative factors from the judged pool by role, module,
     family, and correlation cluster.
   - Responsibility: create the state-machine factor matrix.

5. Trading governance layer
   - Basket state machine, basket scoring, entry, replacement, stop/profit logic,
     turnover budget, cash and lot-size execution.

## Basket Structure

- Stable core: 50% of basket risk budget.
  - Low volatility, liquidity, trend quality, value/quality style.
  - Goal: reduce drawdown and keep the basket investable.

- Aggressive satellite: 30% of basket risk budget.
  - Momentum, breakout, MACD, order-flow, price-volume acceleration.
  - Goal: capture upside when timing confirms.

- Reserve replacement: 20% of basket risk budget.
  - Watchlist names with better liquidity or lower near-relative overlap.
  - Goal: replace deteriorating holdings without rebuilding the whole basket.

## Entry Logic

1. Score each stock with the selected factor matrix.
2. Build a 3-8 name basket.
3. Reject near relatives:
   - Same factor family should normally appear once.
   - Same module can appear at most twice.
   - Same sector can appear at most twice for small baskets.
4. Allow one-lot starter buys when the basket passes, even if each stock is not
   individually a strong buy.
5. Keep cash and lot-size rules active for 20k accounts.

## Replacement Logic

- Minimum hold days: 5 trading days by default.
- Replace only when one of these is true:
  - unrealized loss breaches the early loss threshold;
  - factor quality decays materially;
  - signal collapses while a reserve name has a materially better score.
- Turnover budget caps replacement weight per rebalance.
- Replacement must not increase near-relative, module, family, or sector
  concentration.

## State-Machine Roles

- entry_alpha: stock ranking and initial edge.
- timing_filter: MACD, RSI, reversal, breakout, turtle confirmation.
- risk_override: volatility, downside volatility, drawdown, beta, low-noise.
- liquidity_filter: amount, turnover, Amihud, close-volume ratio.
- hold_validation: trend quality and signal persistence.
- sell_trigger: alpha collapse, downtrend decay, post-entry failure.

## Robustness Rules

- Missing fundamental/event/alternative fields are allowed, but their coverage
  must appear in factor judge reports and cannot silently pass.
- Fast smoke tests should validate factor count, role coverage, basket diversity,
  entry decision, and output files without running the full governance mainline.
- Full governance runs remain required before production conclusions.
