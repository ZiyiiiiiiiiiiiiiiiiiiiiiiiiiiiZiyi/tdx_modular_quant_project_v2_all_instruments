# AGENTS

## Project

A-share quantitative research pipeline: TDX `.day` files → clean → features → multi-strategy selection → backtest → report. 33 strategies across 4 categories (rule, technical/research, governance, ML).

## Python Environment

**Do NOT use `python` or `py` — they are not on PATH.** Always use the conda env absolute path:

```powershell
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" <script>.py
```

Syntax check (fast, no imports):
```powershell
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" -m py_compile <file>.py
```

## Running the Pipeline

```powershell
# Full pipeline (6 steps, ~1-2 hours for all instruments)
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" main.py

# Low-memory mode: one strategy at a time
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" main.py --low-memory --skip-data-steps --mode all

# Single strategy
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" main.py --low-memory --skip-data-steps --mode all --only momentum

# Governance backtest (separate pipeline)
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" main.py --governance --governance-max-days 5
```

Pipeline steps are toggled in `pipeline_steps.py`, parameters in `config.py`.

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | All parameters: paths, dates, markets, thresholds, strategy params, governance settings |
| `pipeline_steps.py` | Step on/off switches (STEP 1-6) |
| `main.py` | Entry point. CLI args, step orchestration, summary/report building |
| `functions/feature_engineering.py` | Feature generation, strategy selection, metadata attachment |
| `functions/backtest_engine.py` | Backtest execution, order simulation, metrics |
| `functions/report_builder.py` | 5-layer diagnostic report (Summary→Total→Category→Diagnostics→Resources) |
| `functions/strategy_registry.py` | Strategy definitions (name, score_col, source, ascending) |
| `functions/factors/factor_ml.py` | ML baselines (elasticnet, xgboost, lightgbm) with proxy/real model distinction |
| `functions/decision_council/runner.py` | Governance backtest runner |
| `functions/governance.py` | Research status, formal eligibility, fallback disclosures |

## Verification Scripts

All `verify_*.py` scripts are standalone — no pytest, no test framework. Run directly:

```powershell
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" verify_mainline_outputs.py
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" verify_decision_council_phase_one.py
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" verify_feature_pipeline_integration.py
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" verify_execution_rules.py
& "C:\Users\Ziyi Wang\.conda\envs\stock_ai\python.exe" verify_experiment_tracking.py
```

Exit code 1 = failure. They print `[PASS]`/`[FAIL]` per check.

## Data Flow

```
F:\tongxinda\vipdoc\{sh,sz,bj}\lday\*.day
  → data/processed/tdx_daily_raw.parquet          (STEP 1: convert)
  → data/processed/tdx_daily_clean.parquet         (STEP 2: clean)
  → data/processed/tdx_daily_features.parquet      (STEP 3: features, ~5.5 GiB)
  → data/processed/{strategy_name}.parquet          (STEP 4: 33 strategy selections)
  → results/backtest_strategy_summary.csv           (STEP 6: backtest summary)
  → results/strategy_diagnostic_report.md           (STEP 6: 5-layer report)
```

Governance outputs go to `results/decision_council/`.

## Architecture Notes

- **Two selection engines**: `feature_engineering.select_instruments_by_score()` (main pipeline) and `strategy_selection.select_instruments_by_score()` (legacy/compat). The main pipeline uses the former.
- **Strategy metadata**: Every selection parquet must contain `strategy_source`, `weighting_mode`, `price_basis`, `neutralization_mode`, `ml_runtime_mode`, `date_window`, `degradation_flags`. Empty selections also get these columns (fixed).
- **Degradation flags**: Pipe-delimited string in `degradation_flags` column. Covers: `price_basis_nominal_fallback`, `neutralization_disabled_or_partial`, `ml_tree_model_proxy_used`, `formal_price_ineligible`, `benchmark_unavailable`.
- **ML proxy models**: xgboost/lightgbm default to linear proxy (`USE_EXTERNAL_TREE_MODELS = False` in `factor_ml.py`). `requested_model` vs `runtime_model` tracks this.
- **Report comparability**: The report builder auto-detects concentration gaps across strategy categories and inserts warnings when `effective_n` relative gap ≥ 0.50 or `top5_weight_sum` gap ≥ 0.20.
- **Governance is separate**: `--governance` runs a completely different pipeline (daily decision council). Its summary feeds into the unified report via `report_builder._load_governance_summary()`.

## Gotchas

1. **`READ_LIMIT = None`** means all instruments. Set to small number (e.g. 20) for fast debugging.
2. **`STRATEGY_START_DATE` / `STRATEGY_END_DATE`** in config.py defaults to 2021-01-01 → 2021-12-31. The full data starts from 2018-01-01.
3. **Feature parquet is ~5.5 GiB** with 147 columns. Low-memory mode loads only needed columns per strategy via `pyarrow.parquet.read_schema()`.
4. **Pipeline cache**: Steps are skipped if inputs unchanged (`pipeline_cache.json`). Delete this file to force re-run.
5. **Experiment tracking**: Each run creates `runs/run_{timestamp}/`. Controlled by `ENABLE_EXPERIMENT_TRACKING`.
6. **Config validation**: `assert_valid_configuration()` runs at startup. Invalid config raises `ValueError`.
7. **File deletion**: Never use `Remove-Item -Recurse`, `rm -rf`, `del /s`, or `rd /s`. Delete one file at a time with explicit path. If batch deletion needed, stop and ask user.

## WBS Change Control

- Before changing strategy logic, formulas, data timing, execution, accounting, reports, or Web controls, inspect `QUANT_SYSTEM_WBS.md` for an existing leaf.
- Every such change must update the corresponding WBS leaf or add a new leaf, append a dated change record, and check the documented upstream/downstream impact chain.
- Verification evidence and run comparability must be recorded in the WBS change entry. Do not compare results from different dates, code states, capital profiles, factor cabinets, cost models, or PIT states as if they were a controlled experiment.

## Config Thresholds (report/resource warnings)

```python
REPORT_EFFECTIVE_N_RELATIVE_GAP_WARN = 0.50   # concentration comparability
REPORT_TOP5_WEIGHT_SUM_GAP_WARN = 0.20        # concentration comparability
FEATURE_PARQUET_GB_WARN = 1.0                  # resource alert
FEATURE_COLUMN_COUNT_WARN = 250                # resource alert
```

These are text-only warnings; they do NOT change execution mode.

## Strategy Categories

| Source | Weighting | Examples |
|--------|-----------|---------|
| `rule` | equal_weight | momentum, reversal, low_vol, ma_break, kline_shape |
| `technical`/`research` | kelly_managed | macd_cross, rsi_reversal, turtle_breakout, mean_reversion |
| `position_management` | kelly_managed | position_managed_kelly |
| `governance` | dynamic_governance | rules_based_president (+ variants) |
| `ml`/`classic_ml` | equal_weight | ml_elasticnet, ml_xgboost, ml_lightgbm, classic_ml_* |
