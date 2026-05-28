# Module Progress

## 2026-05-26

### Completed in this phase
- Added `functions/strategy_registry.py` to centralize strategy metadata.
- Switched `main.py` to read strategy names and descriptions from the registry.
- Switched `functions/feature_engineering.py` to iterate over the registry instead of hand-written per-strategy branches.
- Added config switches:
  - `ENABLE_HOT_THEME_BIAS`
  - `ENABLE_LEARNING_STRATEGIES`
  - `LEARNING_STRATEGY_WHITELIST`
- Added `verify_mainline_outputs.py` for focused mainline artifact verification.

### Verification completed
- `& "E:\ForANACONDA\python.exe" -m py_compile main.py functions\feature_engineering.py functions\strategy_registry.py verify_mainline_outputs.py`
- `& "E:\ForANACONDA\python.exe" verify_mainline_outputs.py`

### Current scope status
- Current module is treated as complete:
  - strategy registry extraction
  - config-driven registry filtering
  - mainline artifact verification

### Next module entry point
- Start Module 1 proper:
  - experiment/config skeleton
  - run metadata tracking
  - stable `run_id` output structure

## 2026-05-26 Module 1 update

### Added in this phase
- Added `functions/evaluation/experiment_tracker.py`
- Added `functions/evaluation/model_lifecycle.py`
- Added `functions/evaluation/__init__.py`
- Added `verify_experiment_tracking.py`
- Added run tracking config:
  - `RUNS_DIR`
  - `ENABLE_EXPERIMENT_TRACKING`
  - `RUN_ID_PREFIX`
  - `RUN_METADATA_FILENAME`
- Wired `main.py` to create per-run metadata and mark runs completed or failed.

### Scope note
- This phase implements the minimum experiment skeleton only.
- It does not yet enforce `idea_id`, validation attempt limits, or test locking.

### Verification completed
- `& "E:\ForANACONDA\python.exe" -m py_compile main.py functions\evaluation\experiment_tracker.py functions\evaluation\model_lifecycle.py`
- smoke test for `start_experiment_run()` and `mark_run_completed()`
- `& "E:\ForANACONDA\python.exe" verify_mainline_outputs.py`

### Current scope status
- Module 1 minimum skeleton is complete:
  - run directory creation
  - metadata writeback
  - completion / failure status support
  - dedicated verification script for latest run metadata

### Next module entry point
- Start Module 2:
  - external code mapping skeleton
  - corporate actions source interface

## 2026-05-26 Module 2 update

### Added in this phase
- Added `functions/data_sources/__init__.py`
- Added `functions/data_sources/code_mapping.py`
- Added `functions/data_sources/corporate_actions.py`
- Added data source config:
  - `RAW_EXTERNAL_DIR`
  - `DEFAULT_CORPORATE_ACTIONS_SOURCE`
  - `CODE_MAPPING_CSV`
  - `CORPORATE_ACTIONS_PARQUET`
  - `CORPORATE_ACTIONS_QUALITY_CSV`

### Scope note
- This phase only builds the interface skeleton and normalized output schema.
- It does not yet integrate a real external provider or adjustment factor generation.

### Verification completed
- `& "E:\ForANACONDA\python.exe" -m py_compile functions\data_sources\code_mapping.py functions\data_sources\corporate_actions.py`
- synthetic smoke test for:
  - code mapping frame build
  - corporate actions normalization
  - quality report generation
  - parquet/csv output save

### Current scope status
- Module 2 minimum skeleton is complete:
  - standardized code mapping output
  - standardized corporate actions output
  - quality report builder
  - dedicated verification script

### Next module entry point
- Start Module 3:
  - adjustment factor skeleton
  - coverage window fields
  - factor quality report interface

## 2026-05-26 Module 3 update

### Added in this phase
- Added `functions/data_sources/adjustment_factors.py`
- Added adjustment factor config:
  - `ADJUSTMENT_FACTORS_PARQUET`
  - `ADJUSTMENT_FACTORS_QUALITY_CSV`
- Added `verify_adjustment_factors.py`

### Scope note
- This phase only builds the normalized adjustment factor schema and coverage window fields.
- It does not yet calculate production-grade forward/backward factors from a real provider.

### Verification completed
- `& "E:\ForANACONDA\python.exe" -m py_compile functions\data_sources\adjustment_factors.py verify_adjustment_factors.py`
- synthetic smoke test for:
  - adjustment factor frame build
  - coverage window fields
  - quality report generation
  - parquet/csv output save

### Current scope status
- Module 3 minimum skeleton is complete:
  - normalized adjustment factor output
  - forward/backward factor placeholder fields
  - coverage window fields
  - dedicated verification script

### Next module entry point
- Start Module 4:
  - dual price view skeleton
  - adjusted/nominal field naming contract
  - feature-side price source split

## 2026-05-26 Module 4 update

### Added in this phase
- Added `functions/pricing/__init__.py`
- Added `functions/pricing/price_views.py`
- Added `functions/pricing/price_transform.py`
- Added `verify_dual_price_views.py`

### Scope note
- This phase only defines the naming contract and minimal transformation helpers.
- It does not yet integrate adjusted/nominal field selection into feature generation or backtest logic.

### Verification completed
- `& "E:\ForANACONDA\python.exe" -m py_compile functions\pricing\price_views.py functions\pricing\price_transform.py verify_dual_price_views.py`
- synthetic smoke test for:
  - dual price field generation
  - original price field preservation
  - nominal/adjusted field distinction
  - price transform round-trip

### Current scope status
- Module 4 minimum skeleton is complete:
  - dual price naming contract
  - nominal price view fields
  - forward-adjusted price view fields
  - dedicated verification script

### Next module entry point
- Start Module 5:
  - feature leakage audit skeleton
  - future-column reference checks
  - label path-dependence guardrails

## 2026-05-26 Module 5 update

### Added in this phase
- Added `functions/pricing/feature_leakage_audit.py`
- Added `verify_feature_leakage_audit.py`

### Scope note
- This phase only adds column-name and label-metadata rule checks.
- It does not yet inspect live function bodies or integrate with the feature pipeline.

### Verification completed
- `& "E:\ForANACONDA\python.exe" -m py_compile functions\pricing\feature_leakage_audit.py verify_feature_leakage_audit.py`
- synthetic smoke test for:
  - future-like feature column detection
  - forbidden feature column detection
  - path-dependent label metadata checks
  - clean/risky audit result split

### Current scope status
- Module 5 minimum skeleton is complete:
  - future column naming rule checks
  - forbidden feature column checks
  - label path-dependence metadata checks
  - dedicated verification script

### Next module entry point
- Start Module 6:
  - execution rules skeleton
  - transaction cost model contract
  - A-share constraint placeholders

## 2026-05-26 Module 6 update

### Added in this phase
- Added `functions/execution/__init__.py`
- Added `functions/execution/execution_rules.py`
- Added `functions/execution/cost_model.py`
- Added `verify_execution_rules.py`
- Added execution config:
  - `COMMISSION_RATE`
  - `STAMP_DUTY_RATE`
  - `SLIPPAGE_RATE`
  - `MIN_LOT_SIZE`
  - `ENABLE_T_PLUS_ONE`
  - `ENABLE_PRICE_LIMIT_CHECK`
  - `ENABLE_SUSPENSION_CHECK`

### Scope note
- This phase only defines order normalization, constraint flags, and cost columns.
- It does not yet integrate execution logic into the backtest engine.

### Verification completed
- `& "E:\ForANACONDA\python.exe" -m py_compile functions\execution\execution_rules.py functions\execution\cost_model.py verify_execution_rules.py`
- synthetic smoke test for:
  - order normalization
  - A-share constraint flags
  - blocked-order detection
  - transaction cost columns
  - buy/sell stamp duty behavior

### Current scope status
- Module 6 minimum skeleton is complete:
  - execution rule contract
  - cost model contract
  - A-share constraint placeholders
  - dedicated verification script

### Next module entry point
- Start Module 7:
  - order simulator skeleton
  - delayed execution placeholders
  - liquidity lock event report contract

## 2026-05-26 Module 7 update

### Added in this phase
- Added `functions/execution/order_simulator.py`
- Added `functions/execution/liquidity_lock_handler.py`
- Added `verify_order_simulator.py`
- Added execution report config:
  - `MAX_LIQUIDITY_LOCK_DAYS`
  - `LIQUIDITY_LOCK_REPORT_CSV`

### Scope note
- This phase only defines order status, delayed queue, and liquidity lock report structures.
- It does not yet integrate order simulation into the backtest engine timeline.

### Verification completed
- `& "E:\ForANACONDA\python.exe" -m py_compile functions\execution\order_simulator.py functions\execution\liquidity_lock_handler.py verify_order_simulator.py`
- synthetic smoke test for:
  - simulated order status fields
  - delayed order queue generation
  - liquidity lock report generation
  - forced-exit placeholder logic
  - report file save

### Current scope status
- Module 7 minimum skeleton is complete:
  - order simulator contract
  - delayed execution placeholders
  - liquidity lock event report contract
  - dedicated verification script

### Next module entry point
- Start Module 8:
  - baseline rebuild helper skeleton
  - old/new result comparison contract
  - strategy rerun summary output placeholders

## 2026-05-26 Module 8 update

### Added in this phase
- Added `rebuild_all_baselines.py`
- Added `compare_old_new_rankings.py`
- Added `verify_baseline_rebuild_contract.py`
- Added rebuild/report config:
  - `BACKTEST_SUMMARY_V2_CSV`
  - `STRATEGY_RANK_SHIFT_REPORT_CSV`

### Scope note
- This phase only builds helper contracts and placeholder outputs.
- It does not yet trigger full pipeline reruns or replace the existing mainline summary.

### Verification completed
- `& "E:\ForANACONDA\python.exe" -m py_compile rebuild_all_baselines.py compare_old_new_rankings.py verify_baseline_rebuild_contract.py`
- synthetic smoke test for:
  - rebuild plan generation
  - placeholder summary output
  - old/new summary comparison
  - rank shift report save

### Current scope status
- Module 8 minimum skeleton is complete:
  - baseline rebuild helper contract
  - old/new ranking comparison contract
  - rerun summary placeholder output
  - dedicated verification script

### Next module entry point
- Start Module 9:
  - evaluation protocol skeleton
  - walk-forward split contract
  - idea/attempt lifecycle placeholders

## 2026-05-26 Module 9 update

### Added in this phase
- Added `functions/evaluation/evaluation_protocol.py`
- Added `functions/evaluation/walk_forward.py`
- Expanded `functions/evaluation/model_lifecycle.py`
- Updated `functions/evaluation/__init__.py`
- Added `verify_evaluation_protocol.py`
- Added evaluation config:
  - `WALK_FORWARD_TRAIN_PERIODS`
  - `WALK_FORWARD_VALIDATION_PERIODS`
  - `WALK_FORWARD_TEST_PERIODS`
  - `WALK_FORWARD_STEP_PERIODS`
  - `WALK_FORWARD_PURGE_PERIODS`
  - `WALK_FORWARD_EMBARGO_PERIODS`
  - `VALIDATION_MAX_ATTEMPTS`
  - `TEST_LOCK_ENABLED`

### Scope note
- This phase only builds the protocol contract, split generator, and lifecycle placeholders.
- It does not yet wire walk-forward splits into the strategy or backtest pipeline.

### Verification completed
- `& "E:\\ForANACONDA\\python.exe" -m py_compile functions\\evaluation\\evaluation_protocol.py functions\\evaluation\\walk_forward.py functions\\evaluation\\model_lifecycle.py verify_evaluation_protocol.py`
- synthetic smoke test for:
  - protocol snapshot generation
  - protocol validation rules
  - walk-forward split generation
  - purge / embargo gap checks
  - idea / attempt lifecycle transitions

### Current scope status
- Module 9 minimum skeleton is complete:
  - evaluation protocol contract
  - walk-forward split contract
  - idea / attempt lifecycle placeholders
  - dedicated verification script

### Next module entry point
- Start Module 10:
  - market cap data skeleton
  - market cap jump marker fields
  - stabilized market cap placeholder output

## 2026-05-26 Module 10 update

### Added in this phase
- Added `functions/data_sources/market_cap_data.py`
- Added `verify_market_cap_data.py`
- Added market cap config:
  - `MARKET_CAP_PARQUET`
  - `MARKET_CAP_QUALITY_CSV`

### Scope note
- This phase only builds the normalized market cap schema, jump flag placeholders, and stabilized field output.
- It does not yet integrate a real provider or wire size-neutralization into the feature pipeline.

### Verification completed
- `& "E:\\ForANACONDA\\python.exe" -m py_compile functions\\data_sources\\market_cap_data.py verify_market_cap_data.py`
- synthetic smoke test for:
  - market cap history normalization
  - jump flag detection
  - stabilized market cap fill
  - quality report generation
  - parquet/csv output save

### Current scope status
- Module 10 minimum skeleton is complete:
  - normalized market cap history contract
  - market cap jump marker fields
  - stabilized market cap placeholder output
  - dedicated verification script

### Next module entry point
- Start Module 11:
  - label system skeleton
  - label metadata / formula contract
  - future-path aggregation guardrails

## 2026-05-26 Module 11 update

### Added in this phase
- Added `functions/labels.py`
- Added `verify_labels.py`
- Added label config:
  - `LABEL_DEFAULT_HORIZONS`
  - `LABEL_DEFAULT_TARGET_RETURN`

### Scope note
- This phase only builds the label registry, metadata/formula contract, and guardrails against future-path aggregation.
- It does not yet replace inline target generation inside `factor_ml.py` or `factor_learning.py`.

### Verification completed
- `& "E:\\ForANACONDA\\python.exe" -m py_compile functions\\labels.py verify_labels.py`
- synthetic smoke test for:
  - label spec generation
  - label formula table generation
  - default label column generation
  - label metadata leakage audit

### Current scope status
- Module 11 minimum skeleton is complete:
  - label system contract
  - label metadata / formula contract
  - future-path aggregation guardrails
  - dedicated verification script

### Next module entry point
- Start Module 12:
  - feature normalization skeleton
  - winsorize / scaling helpers
  - industry / size neutralization placeholders

## 2026-05-26 Module 12 update

### Added in this phase
- Added `functions/feature_normalization.py`
- Added `functions/feature_diagnostics.py`
- Added `verify_feature_normalization.py`
- Added normalization config:
  - `FEATURE_WINSORIZE_LOWER`
  - `FEATURE_WINSORIZE_UPPER`
  - `FEATURE_ROBUST_SCALE_EPSILON`

### Scope note
- This phase only builds winsorize, zscore, robust scaling, and neutralization placeholders plus diagnostic report builders.
- It does not yet wire normalized features into `feature_engineering.py` or the ML pipeline.

### Verification completed
- `& "E:\\ForANACONDA\\python.exe" -m py_compile functions\\feature_normalization.py functions\\feature_diagnostics.py verify_feature_normalization.py`
- synthetic smoke test for:
  - cross-sectional winsorize
  - zscore normalization
  - robust scaling
  - industry / size neutralized columns
  - coverage / distribution / correlation / stability reports

### Current scope status
- Module 12 minimum skeleton is complete:
  - feature normalization contract
  - winsorize / scaling helpers
  - industry / size neutralization placeholders
  - diagnostic report builders
  - dedicated verification script

### Next module entry point
- Start Module 13:
  - factor registry skeleton
  - factor metadata contract
  - factor test / status placeholders

## 2026-05-26 Module 13-19 consolidated update

### Added in this phase
- Added `functions/factor_registry.py`
- Added `functions/factor_tests.py`
- Added `verify_factor_registry.py`
- Expanded `functions/factors/factor_ml.py` with ML baseline contract helpers
- Expanded `functions/factors/factor_learning.py` with learning baseline contract helpers
- Added `verify_ml_baselines.py`
- Added `functions/report_builder.py`
- Added `functions/market_regime.py`
- Added `verify_report_builder.py`
- Added `functions/factors/advanced_price_volume.py`
- Added `verify_advanced_price_volume.py`
- Added `functions/portfolio_optimizer.py`
- Added `functions/strategy_ensemble.py`
- Added `verify_portfolio_ensemble.py`
- Added `functions/data_sources/event_data.py`
- Added `verify_event_data.py`
- Added `functions/qml_experiments/__init__.py`
- Added `functions/qml_experiments/qml_contract.py`
- Added `verify_qml_contract.py`
- Added config:
  - `FACTOR_MIN_COVERAGE_RATIO`
  - `FACTOR_REGISTRY_STATUS_DEFAULT`
  - `REPORT_OUTPUT_MD`
  - `EVENT_DATA_PARQUET`
  - `EVENT_DATA_QUALITY_CSV`
  - `QML_MIN_TEST_WINDOWS`
  - `QML_WILCOXON_P_THRESHOLD`
  - `QML_MAX_DRAWDOWN_MULTIPLIER`

### Scope note
- These phases complete the remaining module contracts only.
- They do not yet fully wire factor registry, reporting, portfolio optimization, event data, or QML evaluation into the live pipeline.

### Verification completed
- `& "E:\\ForANACONDA\\python.exe" -m py_compile functions\\factor_registry.py functions\\factor_tests.py functions\\report_builder.py functions\\market_regime.py functions\\factors\\advanced_price_volume.py functions\\portfolio_optimizer.py functions\\strategy_ensemble.py functions\\data_sources\\event_data.py functions\\qml_experiments\\qml_contract.py functions\\factors\\factor_ml.py functions\\factors\\factor_learning.py verify_factor_registry.py verify_ml_baselines.py verify_report_builder.py verify_advanced_price_volume.py verify_portfolio_ensemble.py verify_event_data.py verify_qml_contract.py`
- `& "E:\\ForANACONDA\\python.exe" verify_factor_registry.py`
- `& "E:\\ForANACONDA\\python.exe" verify_ml_baselines.py`
- `& "E:\\ForANACONDA\\python.exe" verify_report_builder.py`
- `& "E:\\ForANACONDA\\python.exe" verify_advanced_price_volume.py`
- `& "E:\\ForANACONDA\\python.exe" verify_portfolio_ensemble.py`
- `& "E:\\ForANACONDA\\python.exe" verify_event_data.py`
- `& "E:\\ForANACONDA\\python.exe" verify_qml_contract.py`
- full regression sweep:
  - `verify_mainline_outputs.py`
  - `verify_experiment_tracking.py`
  - `verify_corporate_actions.py`
  - `verify_adjustment_factors.py`
  - `verify_dual_price_views.py`
  - `verify_feature_leakage_audit.py`
  - `verify_execution_rules.py`
  - `verify_order_simulator.py`
  - `verify_baseline_rebuild_contract.py`
  - `verify_evaluation_protocol.py`
  - `verify_market_cap_data.py`
  - `verify_labels.py`
  - `verify_feature_normalization.py`
- `main.py` startup regression observed:
  - run tracking initialized successfully
  - main pipeline entered Step 1 full-market conversion with `READ_LIMIT=None`

### Current scope status
- Modules 13-19 minimum skeletons are implemented:
  - factor registry and factor tests
  - ML baseline contracts
  - reporting and market regime helpers
  - advanced price-volume factor placeholders
  - portfolio optimizer and ensemble helpers
  - event data interface
  - QML exit criteria contract

### Next module entry point
- Next phase should focus on live integration:
  - wire labels and normalization into `feature_engineering.py`
  - wire evaluation protocol into ML selection
  - wire execution rules into `backtest_engine.py`
  - wire reporting into post-backtest summary

## 2026-05-26 Live integration audit and fixes

### Verified before changes
- All existing `verify_*.py` scripts passed, confirming the scaffold contracts were internally consistent.
- The roadmap is not complete by its stated completion criteria: most modules are interfaces or synthetic verifications, and no production corporate-action/adjustment feed has been attached.

### Implemented in this phase
- Fixed execution-cost accounting so pending/blocked orders have zero executed notional and zero transaction cost.
- Passed `is_trading` and rough price-limit states from feature data into rebalance order checks.
- Made the backtest execution ledger prefer `close_nominal` whenever a nominal price view is available.
- Moved default backtest initial capital to config and set it to a value compatible with A-share lot-size execution.
- Fixed `max_weight` enforcement: clipping no longer gets undone by normalization; residual allocation remains cash.
- Wired the nominal price view into cleaned and feature frames.
- Made adjusted feature/label computation opt-in to an actual `forward_factor` column.
- Removed silent identity fallback for missing adjustment factors and exposed `adj_factor_available`.
- Added `feature_price_source` and `feature_timestamp` columns for price-view auditability.

### Added regression coverage
- Pending orders are not charged turnover or transaction costs.
- Filled orders continue to incur costs.
- Backtest execution uses nominal prices and records a price-limit blocked order.
- Hard `max_weight` is retained for undersized selections.
- Missing adjustment factors remain unavailable instead of silently using nominal prices.
- Feature frames explicitly identify nominal-unadjusted versus adjusted-forward calculation.

### Not complete
- P0-0: adjustment factor generation remains a schema/synthetic implementation; no verified external corporate-action data chain exists.
- P0-1: the pipeline can use factor-bearing input, but no production factor attachment job is wired from external data into daily prices.
- P0-2: costs and basic constraint flags are integrated, but blocked orders do not yet drive a complete cash/position state machine or multi-day re-execution flow.
- P0-3 onward: a trusted all-strategy rebuild and locked research evaluation cannot be claimed until the preceding P0 dependencies are real.
