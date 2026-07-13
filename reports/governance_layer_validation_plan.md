# Governance Layer Validation Plan

This diagnostic line exists to answer one question before adding more complexity:

Does the compact base signal have positive expectancy after costs and risk controls?

## New Validation Line

- Variant: `governance_layer_validation`
- Alpha bundle: `validation_core_bundle`
- Universe default: `hs300_csi500_a500_strict`
- Reputation: disabled
- Shadow portfolios: disabled
- Market-regime overlay: disabled
- Safety agent: enabled
- Factor weighting: equal weight

The line intentionally removes adaptive reputation, shadow feedback, and regime-specific overlays. If this line does not show positive buy expectancy, the full mainline should not be made more aggressive by raising exposure.

## Factor Set

`validation_core_bundle` contains 8 factors:

- `momentum`
- `mom_lowvol`
- `orderflow_amount_shock`
- `orderflow_efficiency`
- `price_volume_breakout`
- `turtle_breakout`
- `mean_reversion`
- `kdj_oversold_cross`

This covers five interpretable modules: momentum, low volatility, order flow, breakout, and reversal. It avoids the 23-factor mainline blend so factor attribution is easier to audit.

## Primary Acceptance Metrics

Use the generated `governance_strategy_summary.csv` and quality reports.

- `buy_expectancy_10d` should be positive.
- `buy_hit_rate_10d` is useful, but payoff ratio matters more than raw accuracy.
- `p_win_10d_ece` should trend below 0.06 before probability-driven sizing is trusted.
- `p_win_10d_best_bucket_wilson_lower` should approach or exceed 0.50 before high exposure is allowed.
- `holding_portfolio_excess_return` should be positive versus the Top30 strength benchmark.
- `max_risk_contribution_observed` should stay below 0.35 for research and below 0.25 for production-style gating.
- `validation_gate_pass_ratio` should exceed 0.60 before the line is used to justify higher exposure.

## Interpretation Rules

- If account NAV is stable but holding portfolio return is weak, the result is mostly cash/risk defense, not alpha.
- If benchmark excess is positive but total return is negative, the line is defensive but not yet profitable.
- If buy expectancy is negative, do not increase exposure. Fix entry signal first.
- If sell expectancy is positive but buy expectancy is negative, the strategy is better at avoiding losers than finding winners.
- If risk contribution is concentrated, increasing exposure will amplify hidden common-factor risk.
- If probability calibration fails, do not use Kelly or probability-weighted sizing.

## Recommended Experiment Matrix

Run the same window with these lines:

- Mainline: `rules_based_president + president_core_bundle`
- Validation core: `governance_layer_validation + validation_core_bundle`
- Same universe, same date window, same benchmark.

Compare only after normalizing the window:

- Account NAV
- Holding portfolio NAV
- Top30 benchmark NAV
- Excess NAV
- Buy 5/10/20 day payoff
- Sell 5/10/20 day payoff
- Risk contribution
- Rolling beat ratio
- Calibration ECE and Wilson lower bound

## Web Usage

In `main.py` browser launcher:

- Choose `Layer validation line` for the clean diagnostic test.
- Choose `Layer ablation suite` to run all major complexity-layer tests in one click.
- Use `Fast lane` for short checks.
- Use `Full lane` for serious comparisons.
- Leave `Enable per-alpha shadow portfolios` off for this validation line.

## One-Click Layer Ablation Suite

The web launcher task `Layer ablation suite` runs these lines with the same universe and date window:

- `01_core_base`: compact factors, fixed-percentile entry, simple exits, no regime overlay.
- `02_core_plus_regime`: adds market-regime parameter overlay.
- `03_core_plus_probability`: adds probability calibration and expected-edge entry.
- `04_core_plus_complex_exit`: adds lifecycle, replacement, trend, and volume exits.
- `05_full_mainline_control`: current mainline settings with the full 23-factor president bundle and reputation path, but written under a separate diagnostic variant so the suite does not overwrite the formal mainline folder.

The suite writes the combined table to:

`results/governance/layer_ablation_suite_comparison_suite_YYYYMMDD_HHMMSS.csv`

Each component run is also written into a timestamped subdirectory:

`results/governance/{universe}/{variant}/{bundle}/suite_YYYYMMDD_HHMMSS/`

Read this table by layer, not by isolated return. If a later layer improves total return but worsens buy expectancy, calibration, or risk contribution, that layer is not robust enough to justify higher exposure.

Use the web button `Run layer suite only` when you want the ablation matrix. It ignores other checked task boxes and avoids accidentally running the full data pipeline or mainline review. The suite opens one shared live monitor page and reuses it across all component runs.
