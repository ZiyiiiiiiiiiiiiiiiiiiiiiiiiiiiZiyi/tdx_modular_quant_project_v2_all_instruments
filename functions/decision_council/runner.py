"""Historical daily runner for the phase-one rules-based governance strategy."""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pandas as pd

from config import (
    COMMISSION_RATE,
    GOVERNANCE_AUDIT_CANDIDATE_LIMIT,
    GOVERNANCE_AUDIT_ENTRY_FORMULA_LIMIT,
    GOVERNANCE_AUDIT_PRICE_HISTORY_CACHE_SYMBOL_LIMIT,
    ENABLE_MARKET_REGIME_POLICY,
    FEATURE_DAILY_PARQUET,
    GOVERNANCE_ALPHA_CANDIDATE_LIMIT,
    GOVERNANCE_ALPHA_MODEL_FEATURES,
    GOVERNANCE_ALPHA_MODELS,
    GOVERNANCE_ALLOWED_INSTRUMENT_TYPES,
    GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS,
    GOVERNANCE_DEFAULT_TOP_N,
    GOVERNANCE_DEFAULT_TURNOVER_BUDGET,
    GOVERNANCE_HIGH_EXPOSURE_MAX_TOP1_RISK_CONTRIBUTION,
    GOVERNANCE_HIGH_EXPOSURE_MIN_ACTUAL_TARGET_RATIO,
    GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_TRADES,
    GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_WIN_RATE,
    GOVERNANCE_HIGH_EXPOSURE_MIN_PAYOFF_RATIO,
    GOVERNANCE_HIGH_EXPOSURE_MIN_PROFIT_FACTOR,
    GOVERNANCE_HIGH_EXPOSURE_MIN_REALIZED_PNL,
    GOVERNANCE_ENTRY_MATRIX_EXIT_DECAY_THRESHOLD,
    GOVERNANCE_ENTRY_MATRIX_EXTREME_THRESHOLD,
    GOVERNANCE_ENTRY_MATRIX_WATCH_THRESHOLD,
    GOVERNANCE_ENTRY_MATRIX_STARTER_2,
    GOVERNANCE_ENTRY_MATRIX_STRONG_STARTER,
    GOVERNANCE_ENTRY_SUCCESS_PROB_NORMAL,
    GOVERNANCE_CONTROL_AVOIDED_LOSS_HORIZON_DAYS,
    GOVERNANCE_BUY_SELL_CONFLICT_COOLDOWN_DAYS,
    GOVERNANCE_CAPITAL_USAGE_MODE_DEFAULT,
    GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY,
    GOVERNANCE_DEFENSIVE_SLEEVE_ASSETS,
    GOVERNANCE_DIVERSIFY_ENTRY_MATRIX_MIN,
    GOVERNANCE_DOWNTREND_DECAY_ADD_BLOCK,
    GOVERNANCE_DOWNTREND_DECAY_EXIT,
    GOVERNANCE_EXHAUSTION_ADD_MAX,
    GOVERNANCE_EXHAUSTION_BUY_MAX,
    GOVERNANCE_FOLLOW_THROUGH_STARTER_2,
    GOVERNANCE_FOLLOW_THROUGH_STRONG,
    GOVERNANCE_FORCE_DEPLOY_MIN_HOLDINGS_20K,
    GOVERNANCE_FORCE_DEPLOY_TARGET_EXPOSURE_HIGH,
    GOVERNANCE_FORCE_DEPLOY_TARGET_EXPOSURE_NORMAL,
    GOVERNANCE_FORCE_DEPLOY_TARGET_EXPOSURE_WEAK,
    GOVERNANCE_HARD_STOP_COOLDOWN_DAYS,
    GOVERNANCE_HARD_STOP_LOSS,
    GOVERNANCE_IMPACT_MAX_RATE,
    GOVERNANCE_IMPACT_SQRT_COEFFICIENT,
    GOVERNANCE_LAYER_ADD_GAPS,
    GOVERNANCE_LAYER_WEIGHTS,
    GOVERNANCE_ADD_MIN_FACTOR_CONVICTION,
    GOVERNANCE_ADD_MIN_SIGNAL_RETENTION,
    GOVERNANCE_MAX_ADD_LAYERS_LARGE,
    GOVERNANCE_MAX_ADD_LAYERS_RETAIL_20K,
    GOVERNANCE_MAX_POSITION_WEIGHT,
    GOVERNANCE_PROFIT_GIVEBACK_1,
    GOVERNANCE_PROFIT_GIVEBACK_2,
    GOVERNANCE_PROFIT_GIVEBACK_3,
    GOVERNANCE_PROFIT_HARD_STOP_ARM_TRIGGER,
    GOVERNANCE_PROFIT_HARD_STOP_MIN_NET_PROFIT,
    GOVERNANCE_PROFIT_HARD_STOP_TRAIL_GIVEBACK,
    GOVERNANCE_PROFIT_PROTECT_TRIGGER_1,
    GOVERNANCE_PROFIT_PROTECT_TRIGGER_2,
    GOVERNANCE_PROFIT_PROTECT_TRIGGER_3,
    GOVERNANCE_PROTECTING_PROFIT_MIN_HOLD_DAYS,
    GOVERNANCE_PROFIT_TAKE_COOLDOWN_DAYS,
    GOVERNANCE_POST_ENTRY_FAILURE_EARLY_DAYS,
    GOVERNANCE_POST_ENTRY_FAILURE_EARLY_EXIT_SCORE,
    GOVERNANCE_POST_ENTRY_FAILURE_EARLY_EXIT_THRESHOLDS,
    GOVERNANCE_POST_ENTRY_FAILURE_EXIT_SCORE,
    GOVERNANCE_RISK_CONTRIBUTION_SCORE_PENALTY,
    GOVERNANCE_SIGNAL_FAILURE_COOLDOWN_DAYS,
    GOVERNANCE_STALE_EXIT_MAX_MFE,
    GOVERNANCE_STALE_EXIT_DAYS,
    GOVERNANCE_STALE_EXIT_MIN_ALPHA_DROP,
    GOVERNANCE_STALE_EXIT_MIN_LIQUIDITY_DECAY,
    GOVERNANCE_STALE_REDUCE_DAYS,
    GOVERNANCE_STALE_WATCH_DAYS,
    GOVERNANCE_INITIAL_TRANSITION_DAYS,
    GOVERNANCE_INITIAL_CASH,
    GOVERNANCE_END_DATE,
    GOVERNANCE_OUTPUT_DIR,
    GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
    GOVERNANCE_PERFORMANCE_BENCHMARK_TOP_N,
    GOVERNANCE_PRELOAD_CALENDAR_DAYS,
    GOVERNANCE_REPUTATION_WARMUP_DAYS,
    GOVERNANCE_RETAIL_STARTER_2_LOTS,
    GOVERNANCE_RETAIL_STRONG_STARTER_LOTS,
    GOVERNANCE_REPORT_MD,
    GOVERNANCE_START_DATE,
    GOVERNANCE_SUMMARY_CSV,
    SLIPPAGE_RATE,
    STAMP_DUTY_RATE,
    MIN_LOT_SIZE,
    MARKET_REGIME_BENCHMARK_SYMBOL,
    SAFETY_PROXY_MODE,
    TRANSFER_FEE_RATE,
)
from functions.decision_council.accounting import build_exposure_snapshot, calculate_five_day_reward
from functions.execution.security_trading_rules import trading_rule_for
from functions.decision_council.account_state import (
    ExploratoryCorporateActionProcessor,
    LastKnownPriceLedger,
)
from functions.decision_council.analytics import (
    build_bucket_attribution,
    build_governance_attribution,
    build_top_pool_benchmark_series,
    build_top_pool_benchmark_sensitivity,
    factor_module,
)
from functions.decision_council.engine import PhaseOneDecisionCouncilEngine
from functions.decision_council.entry_calibration import RollingEntryCalibrator
from functions.decision_council.entry_confirmation import apply_entry_confirmation
from functions.decision_council.scap_v31_authority import (
    attach_scap_v31_authority,
)
from functions.decision_council.execution_runtime import (
    execute_pending as execute_pending_runtime,
    prune_empty_positions as prune_empty_positions_runtime,
    register_orders as register_orders_runtime,
)
from functions.decision_council.runtime_identity import build_runtime_identity
from functions.decision_council.exposure_catchup import decide_exposure_catchup
from functions.decision_council.exposure_contract import (
    build_exposure_semantics,
    build_holding_semantics,
    resolve_policy_band,
    resolve_strategic_exposure_band,
)
from functions.decision_council.capital_scaling import (
    resolve_position_capacity,
    scaled_position_weight_caps,
)
from functions.decision_council.exposure_runtime import (
    current_weights as current_weights_runtime,
    latest_price_frame_for_trade_pairing as latest_price_frame_for_trade_pairing_runtime,
    record_account_audit as record_account_audit_runtime,
    record_exposure as record_exposure_runtime,
    trade_pairing_capital_profile as trade_pairing_capital_profile_runtime,
)
from functions.decision_council.fast_shadow import FastShadowPortfolioRunner
from functions.decision_council.leakage import validate_governance_split
from functions.decision_council.market_regime_policy import MarketRegimePolicy
from functions.decision_council.market_state_semantics import (
    build_market_state_authority_disclosure,
)
from functions.decision_council.mainline_v2 import (
    MAINLINE_V2,
    MAINLINE_V3,
    MAINLINE_V3_MONTHLY_LGBM_HYBRID,
    apply_mainline_v2_entry_policy,
    calibration_runtime_state,
    is_mainline_v3_version,
    normalize_strategy_logic_version,
)
from functions.decision_council.reliability_weighted_scoring import (
    MAINLINE_V31_RELIABILITY,
    RollingRoleReliabilityController,
    attach_reliability_weighted_score,
)
from functions.decision_council.mainline_v3 import apply_mainline_v3_entry_policy
from functions.decision_council.small_capital_aggressive import (
    build_scap_exposure_targets,
    scap_control_enabled,
)
from functions.decision_council.multi_horizon_value import attach_multi_horizon_value_contract
from functions.decision_council.action_counterfactual_reward import (
    build_action_decisions,
    mature_action_rewards,
    summarize_exit_counterfactual_rewards,
)
from functions.decision_council.flow_state_features import attach_flow_state_features
from functions.decision_council.monthly_lgbm_hybrid import (
    FusionCalibration,
    OnlineMonthlyLGBMController,
    apply_continuous_rank_fusion,
    predict_daily_rank,
)
from functions.decision_council.dual_horizon_lgbm import DualHorizonMonthlyLGBMController
from functions.decision_council.runtime_maturity import (
    combined_runtime_maturity,
    covariance_runtime_state,
    reputation_runtime_state,
    trade_accuracy_runtime_state,
)
from functions.decision_council.proposals import build_daily_candidates
from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LEGACY,
    LEGACY_GOVERNANCE_ALPHA_BUNDLE,
    FactorSourceSpec,
    install_factor_source_model_map,
    resolve_factor_source,
)
from functions.decision_council.factor_runtime_audit import (
    build_factor_runtime_audit,
    print_factor_runtime_audit,
    save_factor_runtime_audit,
)
from functions.decision_council.factor_semantic_contract import (
    build_factor_semantic_contracts,
    semantic_contract_rows,
    validate_factor_semantic_contracts,
)
from functions.decision_council.candidate_factor_cache import attach_pre_screen_candidate_factor_cache
from functions.decision_council.candidate_funnel_audit import (
    build_candidate_rejection_detail,
    build_control_opportunity_cost,
    build_control_trigger_summary_from_csv_parts,
    build_entry_gate_summary,
    build_exposure_reconciliation,
    reconcile_funnel_daily,
    summarize_funnel,
)
from functions.decision_council.factor_cabinet_feature_cache import attach_factor_cabinet_feature_cache
from functions.decision_council.factor_cabinet_module_taxonomy import (
    build_cabinet_experiment_contracts,
    build_cabinet_module_mapping,
)
from functions.decision_council.plots import save_governance_diagnostic_plots
from functions.decision_council.position_lifecycle import (
    apply_candidate_risk_penalty as apply_candidate_risk_penalty_runtime,
    apply_position_state_constraints as apply_position_state_constraints_runtime,
    attach_position_lifecycle_signals as attach_position_lifecycle_signals_runtime,
    expire_position_cooldowns as expire_position_cooldowns_runtime,
    lifecycle_market_shape as lifecycle_market_shape_runtime,
    mark_lifecycle as mark_lifecycle_runtime,
    max_add_layers as max_add_layers_runtime,
    register_position_cooldown as register_position_cooldown_runtime,
    update_lifecycle_on_buy as update_lifecycle_on_buy_runtime,
)
from functions.decision_council.policy import ORDER_COLUMNS, ORDER_PRIORITIES
from functions.decision_council.quality_reports import build_governance_quality_reports
from functions.decision_council.outputs import write_governance_csv, write_governance_text
from functions.decision_council.monitoring import evaluate_daily_rollback
from functions.decision_council.reputation import ReputationLedger
from functions.decision_council.runner_data import (
    governance_feature_columns as governance_feature_columns_runtime,
    prepare_features as prepare_features_runtime,
)
from functions.decision_council.retail_execution import (
    adapt_retail_buy_order as adapt_retail_buy_order_runtime,
    record_retail_execution_diagnostic as record_retail_execution_diagnostic_runtime,
    retail_cash_required as retail_cash_required_runtime,
    sort_retail_orders as sort_retail_orders_runtime,
)
from functions.decision_council.runner_summary import build_governance_summary as build_governance_summary_frame
from functions.decision_council.runtime_integrity_audit import build_runtime_integrity_audit
from functions.execution.cost_model import estimate_trade_costs
from functions.execution.order_simulator import simulate_order_book
from functions.execution.trade_pairing import build_trade_pairing_ledgers
from functions.output_naming import dated_run_dir
from functions.pricing.feature_leakage_audit import audit_feature_columns
from functions.pipeline_cache import file_fingerprint
from functions.report_builder import build_strategy_report, save_strategy_report


EXECUTION_LEDGER_COLUMNS = [
    "symbol",
    "signal_date",
    "decision_timestamp",
    "scheduled_execution_date",
    "next_trading_day",
    "trade_date",
    "execution_price_basis",
    "side",
    "target_shares",
    "executed_shares",
    "remaining_shares",
    "price",
    "trade_notional",
    "total_cost",
    "market_amount",
    "execution_status",
    "same_day_sell_blocked",
    "price_limit_blocked_flag",
    "suspension_blocked_flag",
    "order_id",
    "decision_id",
    "reason",
    "origin_reason",
    "latest_reason",
    "highest_priority_reason",
    "reason_history",
    "reason_schema_version",
    "position_state",
    "orderflow_candidate_score",
    "reversal_entry_score",
    "breakout_gate_score",
    "trend_hold_score",
    "position_exit_reason",
    "liquidation_intent",
    "add_layer",
    "add_allowed",
    "add_block_reason",
    "add_decision_type",
    "unified_action_selected",
    "unified_action_proposals",
    "unified_action_vetoed",
    "unified_action_conflict_count",
    "unified_action_contract",
    "entry_matrix_score",
    "entry_alpha_score",
    "entry_timing_score",
    "entry_liquidity_score",
    "alpha_quality_score",
    "surge_capture_score",
    "follow_through_score",
    "exhaustion_score",
    "entry_success_probability",
    "entry_size_tier",
    "planned_entry_lots",
    "empirical_distribution_score",
    "final_entry_score",
    "tail_risk_proxy",
    "trend_direction_score",
    "peak_decay_score",
    "profit_protection_pressure",
    "dynamic_giveback_limit",
    "future_loss_risk_score",
    "entry_alpha_quality_at_buy",
    "alpha_quality_drop_from_entry",
    "downtrend_decay_score",
    "post_entry_failure_score",
    "strategy_logic_version",
    "cabinet_native_final_score",
    "mainline_v3_score_authority",
    "mainline_v3_score_authority_version",
    "mainline_v3_selection_evaluated",
    "v31_reliability_score",
    "v31_reliability_score_coverage",
    "v31_reliability_contract",
    "v31_calibration_window",
    "v31_score_formula",
    "v31_score_authority",
    "v31_strict_entry_paper_only",
    "monthly_lgbm_raw_score",
    "monthly_lgbm_rank_percentile",
    "hybrid_final_score",
    "hybrid_ml_weight",
    "hybrid_fusion_status",
    "cabinet_base_entry_score",
    "cabinet_strict_entry_score",
    "cabinet_proxy_entry_score",
    "cabinet_timing_score",
    "cabinet_liquidity_health_score",
    "cabinet_risk_safety_score",
    "cabinet_hold_support_score",
    "cabinet_entry_thesis",
    "cabinet_entry_thesis_support",
    "mainline_v3_one_lot_cash_required",
    "mainline_v3_one_lot_weight",
    "mainline_v3_lot_feasible",
    "comparable_value_horizon_days",
    "comparable_expected_alpha",
    "comparable_alpha_lcb",
    "comparable_value_contract",
    "scap_expected_return_point",
    "scap_expected_return_lcb",
    "scap_decision_expected_return",
    "scap_decision_return_basis",
    "scap_estimated_total_cost_amount",
    "scap_risk_penalty_amount",
    "scap_candidate_utility",
    "scap_candidate_utility_version",
    "replacement_pair_id",
    "replacement_paired_symbol",
    "replacement_pair_leg",
    "replacement_horizon_days",
    "replacement_expected_net_edge",
    "replacement_lcb_net_edge",
    "replacement_cost_rate",
    "replacement_contract",
]

HOLDINGS_LEDGER_COLUMNS = [
    "date",
    "decision_id",
    "symbol",
    "shares",
    "price",
    "market_value",
    "account_weight",
    "sleeve_weight",
    "portfolio_exposure",
    "weight",
    "weight_basis",
    "entry_date",
    "entry_price",
    "unrealized_return",
    "mfe",
    "mae",
    "giveback_from_peak",
    "trend_direction_score",
    "peak_decay_score",
    "profit_protection_pressure",
    "dynamic_giveback_limit",
    "future_loss_risk_score",
    "profit_giveback_flag",
    "post_entry_failure_flag",
    "lock_days",
    "stale_days",
    "valuation_source",
    "stale_haircut_ratio",
]

POSITION_STATE_LEDGER_COLUMNS = [
    "date",
    "symbol",
    "position_state",
    "exit_state",
    "position_exit_reason",
    "paper_exit_reason",
    "paper_exit_state",
    "cooldown_active",
    "paper_cooldown_active",
    "cooldown_until",
    "cooldown_reason",
    "cooldown_override",
    "protecting_profit",
    "profit_protection_triggered",
    "buy_sell_conflict_cooldown_days",
    "add_allowed",
    "add_block_reason",
    "add_layer",
    "add_budget",
    "add_decision_type",
    "unified_action_selected",
    "unified_action_proposals",
    "unified_action_vetoed",
    "unified_action_conflict_count",
    "unified_action_contract",
    "hard_stop_exit",
    "profit_hard_stop_exit",
    "paper_hard_stop_exit",
    "paper_profit_hard_stop_exit",
    "loss_containment_exit",
    "paper_loss_containment_exit",
    "hard_stop_net_mfe",
    "hard_stop_net_unrealized",
    "hard_stop_giveback_from_net_peak",
    "profit_giveback_exit",
    "paper_profit_giveback_exit",
    "post_entry_failure_exit",
    "paper_post_entry_failure_exit",
    "alpha_collapse_exit",
    "paper_alpha_collapse_exit",
    "signal_failure_exit",
    "paper_signal_failure_exit",
    "signal_failure_confirmation_count",
    "signal_failure_confirmation_required",
    "signal_failure_confirmed",
    "exit_arbitration_contract",
    "exit_triggered_reasons",
    "exit_authorized_reasons",
    "exit_vetoed_reasons",
    "exit_conflict_count",
    "entry_thesis",
    "entry_logic_version",
    "entry_module_support",
    "current_module_support",
    "support_decay",
    "thesis_failure_exit",
    "paper_thesis_failure_exit",
    "stale_time_reduce",
    "paper_stale_time_reduce",
    "stale_time_exit",
    "paper_stale_time_exit",
    "alpha_quality_score",
    "surge_capture_score",
    "follow_through_score",
    "exhaustion_score",
    "entry_success_probability",
    "entry_size_tier",
    "planned_entry_lots",
    "empirical_distribution_score",
    "final_entry_score",
    "tail_risk_proxy",
    "trend_direction_score",
    "peak_decay_score",
    "profit_protection_pressure",
    "dynamic_giveback_limit",
    "future_loss_risk_score",
    "downtrend_decay_score",
    "post_entry_failure_score",
    "early_post_entry_failure_exit",
    "factor_conviction_score",
    "signal_retention_score",
    "alpha_quality_drop_from_entry",
    "liquidity_decay_score",
    "risk_contribution_penalty",
    "risk_adjusted_primary_score",
    "cabinet_native_final_score",
    "cabinet_strict_entry_score",
    "cabinet_proxy_entry_score",
    "cabinet_timing_score",
    "cabinet_liquidity_health_score",
    "cabinet_risk_safety_score",
    "cabinet_hold_support_score",
    "comparable_value_horizon_days",
    "comparable_expected_alpha",
    "comparable_alpha_lcb",
    "comparable_value_contract",
    "state_observation_status",
    "state_source_date",
    "valuation_source",
    "stale_days",
]


def _frame_with_columns(rows, columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    ordered_columns = list(dict.fromkeys([*columns, *frame.columns.tolist()]))
    # Add all missing audit fields in one operation. Repeated scalar-column
    # insertion fragments wide empty ledgers and emits thousands of warnings.
    return frame.reindex(columns=ordered_columns)


def scap_winner_add_trading_authorized(capital_profile) -> bool:
    profile = dict(capital_profile or {})
    return bool(profile.get("scap_winner_pyramiding_enabled", False)) and bool(
        profile.get("scap_winner_pyramiding_trading_authorized", True)
    )


def archive_existing_governance_output(output_dir: Path) -> Path | None:
    """Deprecated compatibility hook.

    Governance outputs now use run-stamped directories, so old artifacts should
    not be copied, moved, or cleared automatically.
    """
    return None


def _clear_governance_output_files(output_dir: Path) -> None:
    """Deprecated. Automatic governance output cleanup is intentionally disabled."""
    raise RuntimeError("Automatic governance output cleanup is disabled; use a new run-stamped output directory.")


class ProgressTracker:
    """Track progress and estimate remaining time for long-running operations."""
    
    def __init__(self, total_steps, desc="Processing"):
        self.total_steps = total_steps
        self.current_step = 0
        self.desc = desc
        self.start_time = time.time()
        self._last_line_width = 0
    
    def update(self, step_info=""):
        self.current_step += 1
        elapsed = time.time() - self.start_time
        
        # Calculate progress
        progress = self.current_step / self.total_steps
        progress_pct = progress * 100
        
        # Estimate remaining time
        if self.current_step > 0:
            avg_time_per_step = elapsed / self.current_step
            remaining_steps = self.total_steps - self.current_step
            estimated_remaining = avg_time_per_step * remaining_steps
            remaining_str = str(timedelta(seconds=int(estimated_remaining)))
        else:
            remaining_str = "calculating..."
        
        # Use ASCII-only progress characters so GBK consoles do not crash.
        bar_length = 30
        filled_length = int(bar_length * progress)
        bar = "#" * filled_length + "-" * (bar_length - filled_length)
        elapsed_str = str(timedelta(seconds=int(elapsed)))
        line = (
            f"{self.desc}: [{bar}] {progress_pct:.1f}% ({self.current_step}/{self.total_steps}) | "
            f"Elapsed: {elapsed_str} | Remaining: {remaining_str} | {step_info}"
        )
        trailing_spaces = " " * max(self._last_line_width - len(line), 0)
        print(f"\r{line}{trailing_spaces}", end="", flush=True)
        self._last_line_width = len(line)
        
        if self.current_step >= self.total_steps:
            print()  # New line when complete


@dataclass
class Position:
    shares: float
    acquired_date: pd.Timestamp


def build_portfolio_rebalance_dates(dates, frequency: str) -> frozenset[pd.Timestamp]:
    """Return actual decision sessions for the portfolio, not its benchmark."""
    normalized = pd.DatetimeIndex(pd.to_datetime(list(dates), errors="coerce")).dropna()
    mode = str(frequency or "monthly").strip().lower()
    if mode not in {"daily", "weekly", "monthly"}:
        raise ValueError("portfolio normal rebalance frequency must be daily, weekly, or monthly")
    if len(normalized) == 0:
        return frozenset()
    if mode == "daily":
        selected = normalized
    else:
        period = "W-FRI" if mode == "weekly" else "M"
        selected = pd.Series(normalized, index=normalized).groupby(
            normalized.to_period(period)
        ).max()
    return frozenset(pd.Timestamp(date) for date in selected)


class GovernanceBacktestRunner:
    """Run daily close decisions and next-day open executions with audit ledgers."""

    def __init__(
        self,
        feature_df: pd.DataFrame,
        *,
        audit_price_df: pd.DataFrame | None = None,
        initial_cash: float = GOVERNANCE_INITIAL_CASH,
        safety_proxy_mode: str = SAFETY_PROXY_MODE,
        output_dir=GOVERNANCE_OUTPUT_DIR,
        alpha_models=GOVERNANCE_ALPHA_MODELS,
        enable_shadow_portfolios: bool = True,
        prepared_features: bool = False,
        shared_safety_agent=None,
        shared_safety_signals=None,
        shared_manifest=None,
        shared_return_pivot=None,
        shared_daily_feature_indices=None,
        shared_instrument_type_by_symbol=None,
        data_fingerprints=None,
        policy=None,
        enable_reputation: bool = True,
        corporate_action_processor=None,
        governance_variant: str = "rules_based_president",
        enable_sector_cap: bool = False,
        enable_safety_agent: bool = True,
        enable_market_regime_policy: bool = ENABLE_MARKET_REGIME_POLICY,
        entry_confirmation_mode: str = "full",
        selection_weight_mode: str = "reputation_weighted",
        regime_overlay_mode: str = "full",
        risk_hard_gate_enabled: bool = False,
        governance_control_mode: str = "normal",
        alpha_collapse_exit_enabled: bool = True,
        shadow_fast_mode: bool = False,
        universe_name: str | None = None,
        universe_mode: str = "index_pool_strict",
        alpha_bundle: str | None = None,
        registry_version: str | None = None,
        target_index_codes: tuple[str, ...] = (),
        require_constituents: bool = True,
        allow_fallback: bool = False,
        allowed_instrument_types: tuple[str, ...] = GOVERNANCE_ALLOWED_INSTRUMENT_TYPES,
        enable_quality_filters: bool = True,
        max_positions: int | None = None,
        capital_profile: dict | None = None,
        factor_source_spec: FactorSourceSpec | None = None,
        strategy_logic_version: str = "production_v1",
        pit_runtime_state: str = "degraded",
        pit_level2_runtime_state: str = "degraded",
        factor_temporal_isolation_pass: bool = False,
        monthly_lgbm_artifact=None,
        monthly_lgbm_fusion_calibration: FusionCalibration | None = None,
        monthly_lgbm_maximum_weight: float | None = None,
        monthly_lgbm_controller: OnlineMonthlyLGBMController | None = None,
        performance_benchmark_top_n: int = GOVERNANCE_PERFORMANCE_BENCHMARK_TOP_N,
        performance_benchmark_rebalance: str = GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
        decision_start=None,
        decision_end=None,
        portfolio_calendar_dates=None,
    ):
        self.features = feature_df if prepared_features else _prepare_features(feature_df)
        self.features["date"] = pd.to_datetime(self.features["date"], errors="coerce")
        supplied_portfolio_calendar = pd.to_datetime(
            pd.Series(portfolio_calendar_dates, dtype=object), errors="coerce"
        ).dropna()
        self._portfolio_calendar_dates = pd.DatetimeIndex(
            supplied_portfolio_calendar.drop_duplicates().sort_values()
        ).normalize()
        audit_source = audit_price_df if audit_price_df is not None else self.features
        audit_close = "close_nominal" if "close_nominal" in audit_source.columns else "close"
        if {"date", "symbol", audit_close}.issubset(audit_source.columns):
            audit_columns = ["date", "symbol", audit_close]
            audit_columns.extend(
                column for column in ("open_nominal", "open", "amount", "volatility_20")
                if column in audit_source.columns and column not in audit_columns
            )
            self.audit_prices = audit_source[audit_columns].copy()
            if audit_close != "close":
                self.audit_prices = self.audit_prices.rename(columns={audit_close: "close"})
            self.audit_prices["date"] = pd.to_datetime(self.audit_prices["date"], errors="coerce")
            self.audit_prices["symbol"] = self.audit_prices["symbol"].astype(str)
            self.audit_prices["close"] = pd.to_numeric(self.audit_prices["close"], errors="coerce")
            self.audit_prices = self.audit_prices.dropna(subset=["date", "symbol", "close"]).drop_duplicates(["date", "symbol"], keep="last")
        else:
            self.audit_prices = pd.DataFrame(columns=["date", "symbol", "close"])
        self.output_dir = Path(output_dir)
        self.cash = float(initial_cash)
        self.initial_cash = float(initial_cash)
        self.alpha_models = tuple(alpha_models)
        self.enable_shadow_portfolios = bool(enable_shadow_portfolios)
        self.enable_reputation = bool(enable_reputation)
        self.governance_variant = str(governance_variant)
        self.enable_sector_cap = bool(enable_sector_cap)
        self.enable_safety_agent = bool(enable_safety_agent)
        self.enable_market_regime_policy = bool(enable_market_regime_policy)
        self.entry_confirmation_mode = str(entry_confirmation_mode or "full")
        self.selection_weight_mode = str(selection_weight_mode or "reputation_weighted")
        self.regime_overlay_mode = str(regime_overlay_mode or "full")
        self.risk_hard_gate_enabled = bool(risk_hard_gate_enabled)
        self.governance_control_mode = _normalize_governance_control_mode(governance_control_mode)
        self.alpha_collapse_exit_enabled = bool(alpha_collapse_exit_enabled)
        self.shadow_fast_mode = bool(shadow_fast_mode)
        # Registry framework metadata
        self._universe_name = universe_name
        self._universe_mode = str(universe_mode)
        self._alpha_bundle = alpha_bundle
        self._registry_version = registry_version
        self._target_index_codes = tuple(str(code).zfill(6) for code in target_index_codes if str(code).strip())
        self._require_constituents = bool(require_constituents)
        self._allow_fallback = bool(allow_fallback)
        self._allowed_instrument_types = tuple(allowed_instrument_types)
        self._enable_quality_filters = bool(enable_quality_filters)
        self._max_positions_override = int(max_positions) if max_positions not in (None, "", 0) else None
        self.capital_profile = dict(capital_profile or {})
        self._scap_recovery_episode_id = ""
        self._scap_recovery_episode_day = 0
        self._user_hard_position_cap = (
            int(self.capital_profile.get("user_hard_position_cap"))
            if self.capital_profile.get("user_hard_position_cap") not in (None, "", 0, "0")
            else self._max_positions_override
        )
        self.factor_source_spec = factor_source_spec or FactorSourceSpec(
            factor_source=FACTOR_SOURCE_LEGACY,
            alpha_bundle=LEGACY_GOVERNANCE_ALPHA_BUNDLE,
        )
        self.strategy_logic_version = normalize_strategy_logic_version(strategy_logic_version)
        if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}:
            if not is_mainline_v3_version(self.strategy_logic_version):
                raise ValueError("SCAP control modes require a mainline_v3 strategy logic version")
            if not bool(self.capital_profile.get("retail_lot_adapter", False)):
                raise ValueError("SCAP control modes require a retail lot-aware capital profile")
        self.monthly_lgbm_artifact = monthly_lgbm_artifact
        self.monthly_lgbm_fusion_calibration = monthly_lgbm_fusion_calibration
        self.monthly_lgbm_fusion_rows: list[dict] = []
        self.monthly_lgbm_controller = monthly_lgbm_controller
        self.role_reliability_controller: RollingRoleReliabilityController | None = None
        self.performance_benchmark_top_n = int(performance_benchmark_top_n)
        self.performance_benchmark_rebalance = str(performance_benchmark_rebalance or "monthly").strip().lower()
        self.portfolio_normal_rebalance_frequency = str(
            self.capital_profile.get("portfolio_normal_rebalance_frequency", "monthly")
            or "monthly"
        ).strip().lower()
        if self.performance_benchmark_top_n <= 0:
            raise ValueError("performance benchmark top_n must be positive")
        if self.performance_benchmark_rebalance not in {"daily", "weekly", "monthly"}:
            raise ValueError("performance benchmark rebalance must be daily, weekly, or monthly")
        if self.portfolio_normal_rebalance_frequency not in {"daily", "weekly", "monthly"}:
            raise ValueError("portfolio normal rebalance frequency must be daily, weekly, or monthly")
        if (
            self.strategy_logic_version == MAINLINE_V3_MONTHLY_LGBM_HYBRID
            and self.monthly_lgbm_controller is None
            and self.monthly_lgbm_artifact is None
            and monthly_lgbm_maximum_weight is not None
        ):
            self.monthly_lgbm_controller = DualHorizonMonthlyLGBMController(
                maximum_ml_weight=float(monthly_lgbm_maximum_weight),
                benchmark_symbol=MARKET_REGIME_BENCHMARK_SYMBOL,
                round_trip_cost_rate=(
                    2.0 * (float(COMMISSION_RATE) + float(SLIPPAGE_RATE) + float(TRANSFER_FEE_RATE))
                    + float(STAMP_DUTY_RATE)
                ),
                allow_pit_restricted_features=str(pit_level2_runtime_state).strip().lower() in {
                    "formal", "formal_ready", "production", "production_ready", "ready"
                },
                treatment_top_k=int(
                    self._max_positions_override
                    or self.capital_profile.get("soft_target_positions")
                    or GOVERNANCE_DEFAULT_TOP_N
                ),
            )
        if self.strategy_logic_version == MAINLINE_V31_RELIABILITY:
            self.role_reliability_controller = RollingRoleReliabilityController(
                benchmark_symbol=MARKET_REGIME_BENCHMARK_SYMBOL,
                horizon_days=10,
                minimum_dates=60,
                rolling_dates=252,
                round_trip_cost_rate=(
                    2.0 * (float(COMMISSION_RATE) + float(SLIPPAGE_RATE) + float(TRANSFER_FEE_RATE))
                    + float(STAMP_DUTY_RATE)
                ),
            )
        self.pit_runtime_state = str(pit_runtime_state or "degraded")
        self.pit_level2_runtime_state = str(pit_level2_runtime_state or "degraded")
        self.factor_temporal_isolation_pass = bool(factor_temporal_isolation_pass)
        self.factor_runtime_context = self.factor_source_spec.runtime_context()
        self.factor_semantic_contracts = {}
        self.factor_semantic_contract_audit = {}
        if is_mainline_v3_version(self.strategy_logic_version):
            if not self.factor_source_spec.uses_factor_cabinet:
                raise ValueError("mainline_v3_cabinet_native requires a resolved factor_cabinet source")
            self.factor_semantic_contracts = build_factor_semantic_contracts(self.factor_runtime_context)
            self.factor_semantic_contract_audit = validate_factor_semantic_contracts(
                self.factor_semantic_contracts,
                expected_models=self.alpha_models,
            )
        self.factor_runtime_audit = build_factor_runtime_audit(
            self.factor_source_spec,
            available_columns=self.features.columns,
            feature_frame=self.features,
            decision_start=decision_start,
            decision_end=decision_end,
        )
        if self.factor_source_spec.uses_factor_cabinet and self.factor_runtime_audit.fallback_detected:
            raise RuntimeError(f"factor_cabinet runtime contract failed: {self.factor_runtime_audit.fallback_reason}")
        self.capital_profile.setdefault("name", "custom")
        self.capital_usage_mode = _normalize_capital_usage_mode(
            self.capital_profile.get("capital_usage_mode", GOVERNANCE_CAPITAL_USAGE_MODE_DEFAULT)
        )
        self._retail_lot_adapter_enabled = bool(self.capital_profile.get("retail_lot_adapter", False))
        self._daily_feature_indices = (
            shared_daily_feature_indices
            if shared_daily_feature_indices is not None
            else {
                pd.Timestamp(date): indexer
                for date, indexer in self.features.groupby("date", sort=False).indices.items()
            }
        )
        self._instrument_type_by_symbol = (
            shared_instrument_type_by_symbol
            if shared_instrument_type_by_symbol is not None
            else (
                self.features[["symbol", "instrument_type"]]
                .dropna()
                .drop_duplicates("symbol", keep="last")
                .set_index("symbol")["instrument_type"]
                .astype(str)
                .to_dict()
            )
        )
        self._return_pivot = shared_return_pivot if shared_return_pivot is not None else self._build_return_pivot()
        self._benchmark_nav_by_date = self._build_benchmark_nav_lookup()
        self._run_benchmark_base_nav = 1.0
        self.price_ledger = LastKnownPriceLedger()
        self.corporate_actions = corporate_action_processor or ExploratoryCorporateActionProcessor.from_default_artifact()
        self.account_audit_rows = []
        self._last_position_mark_rows = []
        self._latest_monitor_state = {}
        self._last_factor_weights: dict[str, float] = {}
        self.positions: dict[str, Position] = {}
        self.holding_days: dict[str, int] = {}
        self.position_lifecycle: dict[str, dict] = {}
        self.position_cooldowns: dict[str, dict] = {}
        self.position_exit_confirmations: dict[str, dict] = {}
        self.position_state_rows = []
        self.retail_execution_rows = []
        self.entry_formula_audit_rows = []
        self.candidate_gate_rows = []
        # Keep this internal path short: deep experiment paths can exceed the
        # legacy Windows MAX_PATH limit before monthly CSV names are appended.
        self._candidate_gate_spool_dir = self.output_dir / "_audit" / "cg"
        self.candidate_funnel_rows = []
        self.retail_executable_rank_rows = []
        self.defensive_sleeve_rows = []
        self._scap_v31_all_d_streak = 0
        self._scap_v31_normal_cash_zero_proposal_streak = 0
        # Entry-price diagnostics are post-trade audit data.  Do not materialize
        # a copied DataFrame for every symbol in the full feature universe.
        self._feature_indices_by_symbol: dict[str, object] | None = None
        self._close_history_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self._audit_price_indices_by_symbol: dict[str, object] | None = None
        self._audit_close_history_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self.engine = PhaseOneDecisionCouncilEngine(
            self.features,
            safety_proxy_mode=safety_proxy_mode,
            safety_agent=shared_safety_agent,
            safety_signals=shared_safety_signals,
            manifest=shared_manifest,
            copy_features=not prepared_features,
            data_fingerprints=data_fingerprints,
            policy=policy,
        )
        self.reputation = ReputationLedger(self.alpha_models)
        self.entry_calibrator = RollingEntryCalibrator()
        self.execution_rows = []
        self.exposure_rows = []
        self.holdings_rows = []
        self.reward_rows = []
        self.action_decision_rows = []
        self.action_proposal_rows = []
        self.action_plan_rows = []
        self.alpha_rows = []
        self.entry_confirmation_rows = []
        self.factor_weight_rows = []
        self.alpha_collapse_exit_rows = []
        self._pending_alpha_collapse_exits = []
        self._normal_rebalance_dates = frozenset()
        # Market regime policy for dynamic parameter adjustment
        # Diagnostics are prepared independently from trading authority.  The
        # layer-validation variant intentionally keeps adaptive regime control
        # disabled, but it must still observe the real benchmark and PIT market
        # breadth so a future authorization decision has factual evidence.
        self.market_regime_policy = (
            MarketRegimePolicy()
            if self.enable_market_regime_policy or self._control_enabled("regime")
            else None
        )
        self._current_regime = "unknown"
        self._regime_params_cache: dict[pd.Timestamp, object | None] = {}
        self._regime_diagnostics_cache: dict[pd.Timestamp, dict] = {}
        if self.market_regime_policy is not None:
            self.market_regime_policy.detector.prepare_history(
                self.features,
                benchmark_symbol=MARKET_REGIME_BENCHMARK_SYMBOL,
            )
        self._record_leakage_audit()

    def run(
        self,
        *,
        start_date=None,
        end_date=None,
        max_days: int | None = None,
        show_progress: bool = True,
        show_live_monitor: bool = False,
        live_monitor=None,
        progress_callback=None,
    ) -> dict[str, Path]:
        dates = pd.Index(self.features["date"].drop_duplicates().sort_values())
        full_feature_calendar_dates = (
            self._portfolio_calendar_dates
            if len(self._portfolio_calendar_dates)
            else pd.DatetimeIndex(dates)
        )
        if start_date is not None:
            dates = dates[dates >= pd.Timestamp(start_date)]
        if end_date is not None:
            dates = dates[dates <= pd.Timestamp(end_date)]
        if max_days is not None:
            dates = dates[: int(max_days)]
        if len(dates) and self.governance_control_mode == "aggressive_lean":
            warmup_manifest = self.entry_calibrator.warmup_from_feature_history(
                self.features,
                trade_start=dates[0],
                horizon_days=int(
                    self.capital_profile.get("scap_forecast_horizon_days", 10) or 10
                ),
                lookback_sessions=int(
                    self.capital_profile.get("scap_warmup_sessions", 252) or 252
                ),
                score_columns=tuple(
                    dict.fromkeys(
                        str(column)
                        for column in (
                            self.factor_source_spec.model_feature_map or {}
                        ).values()
                        if str(column)
                    )
                ),
            )
            self.engine.manifest["scap_v3_lean_warmup"] = warmup_manifest
            if warmup_manifest.get("status") != "ready":
                raise RuntimeError(
                    "SCAP-V3 Lean warm-up is not ready: "
                    f"{warmup_manifest}"
                )
        
        total_days = len(dates)
        if total_days and self.factor_source_spec.uses_factor_cabinet:
            # Constructor bounds can be absent when the Web supplies dates to
            # run().  Rebuild the audit against the actual decision window so
            # a schema-only pass can never masquerade as daily data coverage.
            self.factor_runtime_audit = build_factor_runtime_audit(
                self.factor_source_spec,
                available_columns=self.features.columns,
                feature_frame=self.features,
                decision_start=dates[0],
                decision_end=dates[-1],
            )
            if self.factor_runtime_audit.fallback_detected:
                raise RuntimeError(
                    "factor_cabinet decision-window coverage failed: "
                    f"{self.factor_runtime_audit.fallback_reason}; "
                    f"failures={self.factor_runtime_audit.coverage_failures}"
                )
        self.runtime_identity = build_runtime_identity(
            self,
            dates=dates,
            output_dir=self.output_dir,
        )
        self.engine.manifest["runtime_identity"] = self.runtime_identity
        self.engine.manifest["effective_config_hash"] = self.runtime_identity[
            "runtime_identity_hash"
        ]
        from functions.decision_council.runtime_checkpoint import (
            write_daily_atomic_snapshot,
            write_run_checkpoint,
        )
        write_run_checkpoint(
            self.output_dir,
            status="running",
            current_day=0,
            total_days=total_days,
            runtime_identity_hash=self.runtime_identity["runtime_identity_hash"],
            stage="initialized",
        )
        self._run_decision_start = pd.Timestamp(dates[0]).normalize() if total_days else None
        self._run_decision_end = pd.Timestamp(dates[-1]).normalize() if total_days else None
        self._run_benchmark_base_nav = self._raw_benchmark_nav_asof(dates[0]) if total_days else 1.0
        normalized_dates = pd.DatetimeIndex(dates)
        portfolio_calendar_dates = build_portfolio_rebalance_dates(
            full_feature_calendar_dates,
            self.portfolio_normal_rebalance_frequency,
        )
        self._normal_rebalance_dates = frozenset(
            date for date in portfolio_calendar_dates if date in set(normalized_dates)
        )
        self._decision_session_ordinal = {
            pd.Timestamp(date): index for index, date in enumerate(normalized_dates)
        }
        shadows = self._build_shadow_runners() if self.enable_shadow_portfolios else {}
        
        # Initialize progress tracker
        progress = ProgressTracker(total_days, "Governance Backtest") if show_progress else None
        if live_monitor is None and show_live_monitor and total_days:
            from functions.decision_council.live_monitor import GovernanceLiveMonitor

            live_monitor = GovernanceLiveMonitor(total_days=total_days, initial_nav=self.initial_cash)
        if live_monitor is not None and total_days:
            live_monitor.start_session(
                title=f"Governance Backtest | {self._universe_name or 'unknown_universe'}",
                total_days=total_days,
                initial_nav=self.initial_cash,
                output_dir=self.output_dir,
            )
        
        run_outcome = "running"
        try:
            for day_index, date in enumerate(dates):
                date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
                if progress_callback is not None:
                    try:
                        progress_callback(
                            {
                                "percent": 80.0 + (day_index / max(total_days, 1)) * 13.0,
                                "step": "process_date",
                                "message": f"processing governance date {date_str}",
                                "detail": f"day={day_index + 1}/{total_days}",
                            }
                        )
                    except Exception:
                        pass
                if live_monitor is not None:
                    previous_exposure = self.exposure_rows[-1] if self.exposure_rows else {
                        "nominal_nav": self.initial_cash,
                        "liquidatable_nav": self.initial_cash,
                        "cash": self.cash,
                        "holding_count": len(self.positions),
                    }
                    previous_monitor_state = dict(self._latest_monitor_state or {})
                    previous_monitor_state.update(
                        {
                            "phase": "processing_date",
                            "date_status": "started",
                            "processing_date": date_str,
                        }
                    )
                    live_monitor.update(
                        date=date,
                        exposure=previous_exposure,
                        day_index=day_index,
                        holdings=self._last_position_mark_rows,
                        monitor_state=previous_monitor_state,
                    )
                shadow_rewards = {}
                shadow_activity = {}
                for model_name, shadow in shadows.items():
                    reward = shadow.step(date, day_index)
                    if reward is not None:
                        shadow_rewards[model_name] = reward["reward"]
                    if shadow.exposure_rows:
                        latest_shadow = shadow.exposure_rows[-1]
                        shadow_activity[model_name] = {
                            "actual_exposure": latest_shadow.get("actual_exposure", 0.0),
                            "holding_count": latest_shadow.get("holding_count", 0),
                            "nominal_nav": latest_shadow.get("nominal_nav", 0.0),
                        }
                self.step(date, day_index, reputation_rewards=shadow_rewards, reputation_activity=shadow_activity)
                latest_ledger_rows = {}
                for ledger_name in (
                    "ideal_portfolio_plan",
                    "executable_order_plan",
                    "constraint_allocation_ledger",
                    "pending_order_ledger",
                ):
                    parts = self.engine.ledgers.frames.get(ledger_name, [])
                    latest_ledger_rows[ledger_name] = (
                        parts[-1].tail(50).to_dict("records") if parts else []
                    )
                write_daily_atomic_snapshot(
                    self.output_dir,
                    trading_day_index=day_index + 1,
                    trade_date=pd.Timestamp(date).date(),
                    runtime_identity_hash=self.runtime_identity[
                        "runtime_identity_hash"
                    ],
                    payload={
                        "account": {
                            "cash": float(self.cash),
                            "holding_count": len(self.positions),
                            "exposure": (
                                dict(self.exposure_rows[-1])
                                if self.exposure_rows
                                else {}
                            ),
                        },
                        "positions": list(self._last_position_mark_rows or []),
                        "pending_orders": self.engine.pending_orders.orders.to_dict(
                            "records"
                        ),
                        "execution_events_tail": list(self.execution_rows[-100:]),
                        "policy_pool_plan_ledgers": latest_ledger_rows,
                    },
                )
                write_run_checkpoint(
                    self.output_dir,
                    status="running",
                    current_day=day_index + 1,
                    total_days=total_days,
                    last_successful_date=pd.Timestamp(date).date(),
                    runtime_identity_hash=self.runtime_identity[
                        "runtime_identity_hash"
                    ],
                    stage="date_complete",
                )

                exposure = self.exposure_rows[-1] if self.exposure_rows else {}
                if live_monitor is not None:
                    live_monitor.update(
                        date=date,
                        exposure=exposure,
                        day_index=day_index,
                        holdings=self._last_position_mark_rows,
                        monitor_state=self._latest_monitor_state,
                    )

                # Update progress
                if progress:
                    nav = exposure.get("nominal_nav", 0)
                    holding_count = int(exposure.get("holding_count", len(self.positions)) or 0)
                    progress.update(f"Date: {date_str} | NAV: {nav:,.0f} | Holdings: {holding_count}")
                if progress_callback is not None:
                    try:
                        progress_callback(
                            {
                                "percent": 80.0 + ((day_index + 1) / max(total_days, 1)) * 13.0,
                                "step": "date_complete",
                                "message": f"completed governance date {date_str}",
                                "detail": f"day={day_index + 1}/{total_days}",
                            }
                        )
                    except Exception:
                        pass
        except KeyboardInterrupt:
            run_outcome = "interrupted"
            write_run_checkpoint(
                self.output_dir,
                status="interrupted",
                current_day=len(self.exposure_rows),
                total_days=total_days,
                last_successful_date=(
                    pd.Timestamp(self.exposure_rows[-1]["date"]).date()
                    if self.exposure_rows
                    else None
                ),
                runtime_identity_hash=self.runtime_identity[
                    "runtime_identity_hash"
                ],
                stage="keyboard_interrupt",
                error="KeyboardInterrupt: user requested Ctrl+C stop",
            )
            print(
                "Governance backtest interrupted by Ctrl+C; "
                "the last completed trading day is preserved in run_checkpoint.json.",
                flush=True,
            )
            raise
        except Exception as exc:
            run_outcome = "failed"
            write_run_checkpoint(
                self.output_dir,
                status="failed",
                current_day=len(self.exposure_rows),
                total_days=total_days,
                last_successful_date=(
                    pd.Timestamp(self.exposure_rows[-1]["date"]).date()
                    if self.exposure_rows
                    else None
                ),
                runtime_identity_hash=self.runtime_identity[
                    "runtime_identity_hash"
                ],
                stage="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        finally:
            if live_monitor is not None:
                finish_messages = {
                    "running": "??????????????",
                    "interrupted": "???? Ctrl+C ????????????? checkpoint?",
                    "failed": "???????? checkpoint ????????",
                }
                live_monitor.finish(finish_messages.get(run_outcome, "??????"))
        
        for model_name, shadow in shadows.items():
            shadow_frame = pd.DataFrame(shadow.exposure_rows)
            if not shadow_frame.empty:
                shadow_frame.insert(0, "model_name", model_name)
                self.engine.record_shadow_portfolio(shadow_frame)
        write_run_checkpoint(
            self.output_dir,
            status="saving",
            current_day=total_days,
            total_days=total_days,
            last_successful_date=(
                pd.Timestamp(dates[-1]).date() if total_days else None
            ),
            runtime_identity_hash=self.runtime_identity[
                "runtime_identity_hash"
            ],
            stage="saving_outputs",
        )
        try:
            saved = self._save()
        except Exception as exc:
            from functions.decision_council.artifact_manifest import (
                update_artifact_manifest,
            )

            update_artifact_manifest(
                self.output_dir,
                stage="save_failed",
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            write_run_checkpoint(
                self.output_dir,
                status="failed",
                current_day=total_days,
                total_days=total_days,
                last_successful_date=(
                    pd.Timestamp(dates[-1]).date() if total_days else None
                ),
                runtime_identity_hash=self.runtime_identity[
                    "runtime_identity_hash"
                ],
                stage="save_failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        completion_path = self.output_dir / "COMPLETE.json"
        write_governance_text(
            __import__("json").dumps(
                {
                    "status": "complete",
                    "schema_version": "governance_completion_v1",
                    "runtime_identity_hash": self.runtime_identity[
                        "runtime_identity_hash"
                    ],
                    "trading_days": total_days,
                    "last_successful_date": (
                        str(pd.Timestamp(dates[-1]).date())
                        if total_days
                        else None
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            completion_path,
        )
        saved["completion_marker"] = completion_path
        write_run_checkpoint(
            self.output_dir,
            status="complete",
            current_day=total_days,
            total_days=total_days,
            last_successful_date=(
                pd.Timestamp(dates[-1]).date() if total_days else None
            ),
            runtime_identity_hash=self.runtime_identity[
                "runtime_identity_hash"
            ],
            stage="complete",
        )
        return saved

    def step(
        self,
        date,
        day_index: int,
        *,
        reputation_rewards: dict[str, float] | None = None,
        reputation_activity: dict[str, dict] | None = None,
    ):
        date_key = pd.Timestamp(date)
        daily_indexer = self._daily_feature_indices.get(date_key)
        if daily_indexer is None:
            daily = self.features.iloc[0:0].copy()
        else:
            daily = self.features.iloc[daily_indexer].copy()
        self.price_ledger.update(daily, as_of=date)
        self.cash, corporate_action_summary = self.corporate_actions.apply(
            as_of=date,
            positions=self.positions,
            cash=self.cash,
        )
        self._prune_empty_positions()
        self.entry_calibrator.mature(day_index=day_index, price_frame=daily)
        calibration_state = calibration_runtime_state(
            matured_sample_count=len(self.entry_calibrator.history_rows),
            day_index=day_index,
        )
        from functions.data.trading_calendar import TradingCalendar

        self.trading_calendar = TradingCalendar(self._daily_feature_indices.keys())
        self._execute_pending(date, daily)
        self._prune_empty_positions()
        if self._user_hard_position_cap is not None and len(self.positions) > self._user_hard_position_cap:
            raise RuntimeError(
                "governance position limit invariant failed at start of decision: "
                f"positions={len(self.positions)}, user_hard_position_cap={self._user_hard_position_cap}"
            )
        self._mature_alpha_collapse_diagnostics(date)
        exposure = self._record_exposure(date, daily)
        matured_reward = self._mature_reward(date)
        reputation_snapshot = self.reputation.record_rewards(
            reputation_rewards or {},
            as_of=date,
            trading_day_index=day_index,
            model_activity=reputation_activity or {},
        )
        self.engine.record_reputation(reputation_snapshot)
        reputation_state = reputation_runtime_state(day_index=day_index, snapshot=reputation_snapshot)
        closed_trade_count = sum(
            str(row.get("side", "")).lower() == "sell"
            and str(row.get("execution_status", "")).lower() == "filled"
            for row in self.execution_rows
        )
        trade_accuracy_state = trade_accuracy_runtime_state(closed_trade_count=closed_trade_count)
        
        # Get regime-adjusted parameters if market regime policy is enabled
        regime_params = self._get_regime_params(date)
        if not self._control_enabled("regime"):
            regime_params = None
        current_turnover_budget = regime_params.default_turnover_budget if regime_params else GOVERNANCE_DEFAULT_TURNOVER_BUDGET
        current_min_score_percentile = regime_params.min_score_percentile if regime_params else None
        if self.strategy_logic_version == MAINLINE_V2 or is_mainline_v3_version(self.strategy_logic_version):
            # V2 keeps regime as an account-level exposure/risk overlay. It must
            # not also alter candidate admission or portfolio operating cadence.
            current_turnover_budget = GOVERNANCE_DEFAULT_TURNOVER_BUDGET
            current_min_score_percentile = 0.80
        if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}:
            current_min_score_percentile = 0.0
        
        candidates, proposals = build_daily_candidates(
            daily,
            # Reputation remains recorded for diagnostics, but does not directly
            # change candidate admission. This keeps the live path factor-matrix led.
            reputation_weights={model_name: 1.0 for model_name in self.alpha_models},
            holding_days=self.holding_days,
            candidate_limit=GOVERNANCE_ALPHA_CANDIDATE_LIMIT,
            model_names=self.alpha_models,
            min_score_percentile=current_min_score_percentile,
            allowed_instrument_types=self._allowed_instrument_types,
            target_index_codes=self._target_index_codes,
            universe_mode=self._universe_mode,
            require_constituents=self._require_constituents,
            allow_fallback=self._allow_fallback,
            enable_quality_filters=(
                False if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"} else self._enable_quality_filters
            ),
            selection_weight_mode=(
                "cabinet_native" if is_mainline_v3_version(self.strategy_logic_version)
                else self.selection_weight_mode
            ),
            runtime_context=self.factor_runtime_context,
        )
        candidates = attach_flow_state_features(candidates)
        candidate_build_counts = dict(candidates.attrs.get("candidate_funnel_counts", {}))
        safety_row = self.engine.safety_signals.loc[pd.Timestamp(date)]
        if isinstance(safety_row, pd.DataFrame):
            safety_row = safety_row.iloc[-1]
        risk_level = str(safety_row.get("risk_level", "normal"))
        structural_regime_level = str(safety_row.get("structural_regime_level", "bull"))
        preliminary_risk_cap = float(
            pd.to_numeric(
                pd.Series([safety_row.get("exposure_cap", 1.0)]),
                errors="coerce",
            ).fillna(1.0).iloc[0]
        )
        position_capacity = resolve_position_capacity(
            capital_profile=self.capital_profile,
            nav_amount=float(exposure.get("nominal_nav", self.initial_cash)),
            cash_amount=float(self.cash),
            risk_exposure_ceiling=preliminary_risk_cap,
            candidates=candidates,
            current_symbols=self.positions,
            current_exposure=(
                float(exposure.get("invested_value", 0.0) or 0.0)
                / max(float(exposure.get("nominal_nav", self.initial_cash) or self.initial_cash), 1e-12)
            ),
        )
        if position_capacity.mode == "auto":
            dynamic_soft_cap, dynamic_hard_cap = scaled_position_weight_caps(
                target_exposure=preliminary_risk_cap,
                effective_position_cap=position_capacity.sizing_reference_positions,
                absolute_soft_cap=float(
                    self.capital_profile.get(
                        "scap_single_position_soft_cap",
                        0.25,
                    )
                    or 0.25
                ),
                absolute_hard_cap=float(
                    self.capital_profile.get(
                        "retail_single_position_cap",
                        GOVERNANCE_MAX_POSITION_WEIGHT,
                    )
                    or GOVERNANCE_MAX_POSITION_WEIGHT
                ),
            )
        else:
            dynamic_soft_cap = float(
                self.capital_profile.get("scap_single_position_soft_cap", 0.25)
                or 0.25
            )
            dynamic_hard_cap = float(
                self.capital_profile.get(
                    "retail_single_position_cap",
                    GOVERNANCE_MAX_POSITION_WEIGHT,
                )
                or GOVERNANCE_MAX_POSITION_WEIGHT
            )
        if self.governance_control_mode == "aggressive_lean":
            diversified_hard_cap = float(
                self.capital_profile.get(
                    "scap_diversified_single_position_hard_cap", 0.20
                )
                or 0.20
            )
            dynamic_hard_cap = min(dynamic_hard_cap, diversified_hard_cap)
            dynamic_soft_cap = min(dynamic_soft_cap, dynamic_hard_cap)
        self._current_dynamic_single_position_hard_cap = float(dynamic_hard_cap)
        confirmation_mode = self.entry_confirmation_mode
        if self.governance_control_mode in {"factor_only", "safe_factor_only", "aggressive_profit", "aggressive_lean"}:
            if str(confirmation_mode or "").strip().lower() in {"", "full", "fixed_percentile_only"}:
                confirmation_mode = "factor_only"
        candidates = apply_entry_confirmation(
            candidates,
            risk_level=risk_level,
            structural_regime_level=structural_regime_level if self._control_enabled("regime") else "neutral",
            entry_calibrator=self.entry_calibrator,
            confirmation_mode=confirmation_mode,
            capital_usage_mode=self.capital_usage_mode,
        )
        v3_ranking_score_column = "cabinet_native_final_score"
        v3_ranking_coverage_column = "cabinet_strict_entry_score_coverage"
        if is_mainline_v3_version(self.strategy_logic_version):
            if self.strategy_logic_version == MAINLINE_V31_RELIABILITY:
                candidates = self.role_reliability_controller.process_day(
                    candidates, as_of_date=date, price_history=self.audit_prices
                ) if self.role_reliability_controller is not None else attach_reliability_weighted_score(
                    candidates, as_of_date=date
                )
                v3_ranking_score_column = "v31_reliability_score"
                v3_ranking_coverage_column = "v31_reliability_score_coverage"
            if self.strategy_logic_version == MAINLINE_V3_MONTHLY_LGBM_HYBRID:
                if self.monthly_lgbm_controller is not None:
                    candidates, audit_row = self.monthly_lgbm_controller.process_day(
                        candidates,
                        as_of_date=date,
                        price_history=self.audit_prices,
                    )
                    self.monthly_lgbm_fusion_rows.append(audit_row)
                else:
                    calibration = self.monthly_lgbm_fusion_calibration
                    if self.monthly_lgbm_artifact is not None and calibration is not None:
                        candidates = predict_daily_rank(self.monthly_lgbm_artifact, candidates)
                    else:
                        calibration = FusionCalibration(
                            ml_weight=0.0,
                            unconstrained_weight=float("nan"),
                            reliability=0.0,
                            maximum_ml_weight=(
                                float(calibration.maximum_ml_weight)
                                if calibration is not None
                                else 0.0
                            ),
                            validation_rank_ic_mean=float("nan"),
                            validation_rank_ic_standard_error=float("nan"),
                            status="fallback_monthly_model_unavailable",
                        )
                    candidates = apply_continuous_rank_fusion(candidates, calibration)
                    audit_row = {"date": pd.Timestamp(date), **calibration.audit_dict()}
                    audit_row["model_available"] = self.monthly_lgbm_artifact is not None
                    if self.monthly_lgbm_artifact is not None:
                        audit_row.update(self.monthly_lgbm_artifact.audit_dict())
                    self.monthly_lgbm_fusion_rows.append(audit_row)
                v3_ranking_score_column = "hybrid_final_score"
            candidates = self._apply_candidate_risk_penalty(
                candidates,
                exposure=exposure,
                score_column=v3_ranking_score_column,
            )
            v3_ranking_score_column = "risk_adjusted_primary_score"
            # SCAP utility consumes same-horizon expected return and its
            # conservative bound. Attach that contract before either V3 policy
            # pass; attaching it after selection makes every row
            # ``insufficient`` and deterministically blocks all new entries.
            candidates = attach_multi_horizon_value_contract(candidates)
            if self.governance_control_mode == "aggressive_lean":
                candidates = attach_scap_v31_authority(
                    candidates,
                    horizon_days=int(
                        self.capital_profile.get(
                            "scap_forecast_horizon_days", 10
                        )
                        or 10
                    ),
                    position_cap_mode=position_capacity.mode,
                    target_position_cash=(
                        preliminary_risk_cap
                        * float(exposure.get("nominal_nav", self.initial_cash))
                        / max(position_capacity.sizing_reference_positions, 1)
                    ),
                    authority_snapshot_id=(
                        f"{pd.Timestamp(date).date().isoformat()}|"
                        f"{self.strategy_logic_version}|authority"
                    ),
                )
            # Attach the one authoritative final score before lifecycle. This
            # pass deliberately cannot select; the optimizer runs once only
            # after lifecycle/state constraints have been evaluated.
            candidates = apply_mainline_v3_entry_policy(
                candidates,
                max_new_candidates=position_capacity.effective_position_cap,
                available_cash=self.cash,
                nominal_nav=exposure.get("nominal_nav"),
                min_cash_buffer=float(self.capital_profile.get("min_cash_buffer", 0.0) or 0.0),
                max_single_position_weight=dynamic_hard_cap,
                held_symbols=self.positions,
                lot_size=MIN_LOT_SIZE,
                strategy_logic_version=self.strategy_logic_version,
                ranking_score_column=v3_ranking_score_column,
                use_scap_candidate_utility=self.governance_control_mode in {"aggressive_profit", "aggressive_lean"},
                scap_single_position_soft_cap=dynamic_soft_cap,
                scap_candidate_minimum_commission=float(
                    self.capital_profile.get("scap_candidate_minimum_commission", 5.0) or 5.0
                ),
                scap_candidate_reward_basis=str(
                    self.capital_profile.get("scap_candidate_reward_basis", "lcb") or "lcb"
                ),
                ranking_coverage_column=v3_ranking_coverage_column,
                decision_date=date,
                selection_enabled=False,
                scap_candidate_pool_limit=int(
                    self.capital_profile.get("scap_candidate_pool_limit", 32) or 32
                ),
                scap_candidate_pool_per_thesis=int(
                    self.capital_profile.get("scap_candidate_pool_per_thesis", 2) or 2
                ),
            )
        candidates = self._attach_position_lifecycle_signals(candidates, date=date)
        candidates = self._apply_position_state_constraints(candidates, date=date, exposure=exposure)
        candidates = self._apply_optional_exit_controls(candidates)
        candidates["calibration_runtime_state"] = calibration_state
        candidates["reputation_runtime_state"] = reputation_state
        candidates["trade_accuracy_runtime_state"] = trade_accuracy_state
        candidates["pit_runtime_state"] = self.pit_runtime_state
        if self.strategy_logic_version == MAINLINE_V2:
            candidates = apply_mainline_v2_entry_policy(
                candidates,
                risk_level=risk_level,
                max_new_candidates=(
                    self._max_positions_override
                    or (
                        regime_params.max_positions
                        if regime_params is not None
                        else GOVERNANCE_DEFAULT_TOP_N
                    )
                ),
            )
        elif is_mainline_v3_version(self.strategy_logic_version):
            candidates = apply_mainline_v3_entry_policy(
                candidates,
                max_new_candidates=position_capacity.effective_position_cap,
                available_cash=self.cash,
                nominal_nav=exposure.get("nominal_nav"),
                min_cash_buffer=float(self.capital_profile.get("min_cash_buffer", 0.0) or 0.0),
                max_single_position_weight=dynamic_hard_cap,
                held_symbols=self.positions,
                lot_size=MIN_LOT_SIZE,
                strategy_logic_version=self.strategy_logic_version,
                ranking_score_column=v3_ranking_score_column,
                ranking_coverage_column=v3_ranking_coverage_column,
                decision_date=date,
                use_scap_candidate_utility=self.governance_control_mode in {"aggressive_profit", "aggressive_lean"},
                scap_single_position_soft_cap=dynamic_soft_cap,
                scap_candidate_minimum_commission=float(
                    self.capital_profile.get("scap_candidate_minimum_commission", 5.0) or 5.0
                ),
                scap_candidate_reward_basis=str(
                    self.capital_profile.get("scap_candidate_reward_basis", "lcb") or "lcb"
                ),
                scap_candidate_pool_limit=int(
                    self.capital_profile.get("scap_candidate_pool_limit", 32) or 32
                ),
                scap_candidate_pool_per_thesis=int(
                    self.capital_profile.get("scap_candidate_pool_per_thesis", 2) or 2
                ),
            )
        # Non-V3 strategies still need the same comparable return-unit fields
        # for lifecycle, replacement and reporting consumers.
        if not is_mainline_v3_version(self.strategy_logic_version):
            candidates = attach_multi_horizon_value_contract(candidates)
        elif self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}:
            # Re-resolve K after the comparable return contract is attached.
            # The first pass supplies concentration sizing; this final pass
            # prevents cheap one-lot names from inflating the financial cap
            # unless some integer lot size covers full lifecycle costs.
            position_capacity = resolve_position_capacity(
                capital_profile=self.capital_profile,
                nav_amount=float(exposure.get("nominal_nav", self.initial_cash)),
                cash_amount=float(self.cash),
                risk_exposure_ceiling=preliminary_risk_cap,
                candidates=candidates,
                current_symbols=self.positions,
                current_exposure=(
                    float(exposure.get("invested_value", 0.0) or 0.0)
                    / max(float(exposure.get("nominal_nav", self.initial_cash) or self.initial_cash), 1e-12)
                ),
            )
        # Lifecycle rows are created before the final v3/ML ranking pass.  Bind
        # the final comparable value and role scores back to the same daily
        # held-position snapshot so monitoring and integrity audits evaluate
        # the score that actually governed replacement decisions.
        if self.position_state_rows and not candidates.empty:
            final_by_symbol = candidates.drop_duplicates("symbol", keep="first").set_index("symbol", drop=False)
            score_fields = (
                "cabinet_native_final_score", "cabinet_strict_entry_score",
                "cabinet_proxy_entry_score", "cabinet_timing_score",
                "cabinet_liquidity_health_score", "cabinet_risk_safety_score",
                "cabinet_hold_support_score", "comparable_value_horizon_days",
                "comparable_expected_alpha", "comparable_alpha_lcb",
                "comparable_value_contract",
            )
            for state_row in self.position_state_rows:
                if pd.Timestamp(state_row.get("date")) != pd.Timestamp(date):
                    continue
                symbol = str(state_row.get("symbol", ""))
                if symbol not in final_by_symbol.index:
                    continue
                final = final_by_symbol.loc[symbol]
                for field in score_fields:
                    state_row[field] = final.get(field, pd.NA)
        self._record_candidate_gate_audit(date=date, candidates=candidates)
        entry_confirmed = candidates.get("entry_confirmed", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
        role_pass = candidates.get("state_machine_role_pass", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
        cooldown_clear = ~candidates.get("cooldown_active", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
        candidate_funnel_row = {
            "date": pd.Timestamp(date),
            "decision_id": f"gov_{pd.Timestamp(date).strftime('%Y%m%d')}",
            **candidate_build_counts,
            "entry_confirmation_pass_count": int(entry_confirmed.sum()),
            "state_machine_role_pass_count": int((entry_confirmed & role_pass).sum()),
            "risk_pass_count": int((entry_confirmed & role_pass).sum()),
            "reputation_pass_count": int((entry_confirmed & role_pass).sum()),
            "regime_pass_count": int((entry_confirmed & role_pass).sum()),
            "cooldown_pass_count": int((entry_confirmed & role_pass & cooldown_clear).sum()),
            "capital_pass_count": 0,
            "risk_stage_mode": "score_or_size_only",
            "reputation_stage_mode": "diagnostics_only",
            "regime_stage_mode": "confirmation_or_exposure_overlay",
            "candidate_detail_scope": f"top_{int(GOVERNANCE_AUDIT_ENTRY_FORMULA_LIMIT)}",
            "candidate_detail_count": 0,
            "scap_raw_signal_count": 0,
            "scap_structural_feasible_count": 0,
            "scap_cash_feasible_count": 0,
            "scap_slot_feasible_count": 0,
            "scap_optimizer_selected_count": 0,
            "scap_registered_buy_count": 0,
            "scap_registered_add_buy_count": 0,
            "scap_registered_replacement_buy_count": 0,
        }
        defensive_candidates = self._record_defensive_sleeve_diagnostics(
            date=date,
            daily=daily,
            risk_level=risk_level,
            structural_regime_level=structural_regime_level,
            stock_candidate_count=int(_state_machine_entry_mask(candidates).sum()),
        )
        self._record_entry_formula_and_retail_rank(date=date, candidates=candidates, daily=daily, exposure=exposure)
        self.entry_calibrator.schedule_candidates(
            candidates,
            day_index=day_index,
            horizon_days=5,
            regime_name=structural_regime_level,
            score_column=(
                "cabinet_native_final_score"
                if "cabinet_native_final_score" in candidates.columns
                else "primary_score"
            ),
        )
        self.entry_calibrator.schedule_candidates(
            candidates,
            day_index=day_index,
            horizon_days=10,
            regime_name=structural_regime_level,
            score_column=(
                "cabinet_native_final_score"
                if "cabinet_native_final_score" in candidates.columns
                else "primary_score"
            ),
        )
        if not self.shadow_fast_mode:
            self._record_entry_confirmation(date, candidates)
        proposals["decision_date"] = date
        if not self.shadow_fast_mode:
            audit_symbols = set(candidates.head(GOVERNANCE_AUDIT_CANDIDATE_LIMIT)["symbol"].astype(str)) | set(self.positions)
            self.alpha_rows.append(proposals[proposals["symbol"].astype(str).isin(audit_symbols)].copy())
        allow_normal_rebalance = self._allow_normal_rebalance(date, day_index)
        actual_exposure = float(exposure.get("invested_value", 0.0)) / max(float(exposure.get("nominal_nav", 0.0)), 1e-12)
        safety_exposure_cap = float(pd.to_numeric(pd.Series([safety_row.get("exposure_cap", 1.0)]), errors="coerce").fillna(1.0).iloc[0])
        regime_name = getattr(regime_params, "regime_name", structural_regime_level) if regime_params is not None else structural_regime_level
        liquidity_stress = float(pd.to_numeric(pd.Series([safety_row.get("market_liquidity_stress_ratio", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        entry_stage_counts = _scap_entry_stage_counts(candidates)
        qualified_entry_count = int(entry_stage_counts["optimizer_selected_entry_count"])
        exposure_signal_count = (
            int(entry_stage_counts["raw_signal_count"])
            if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}
            else qualified_entry_count
        )
        trailing_buy_accuracy_5d = self._trailing_trade_accuracy(date, side="buy", horizon_days=5, lookback_trades=60)
        exposure_authorization = _authorize_exposure_by_regime(
            regime_name=regime_name,
            risk_level=risk_level,
            safety_exposure_cap=safety_exposure_cap,
            candidates=candidates,
            qualified_entry_count=exposure_signal_count,
            trailing_buy_accuracy_5d=trailing_buy_accuracy_5d,
            liquidity_stress=liquidity_stress,
            regime_overlay_mode=self.regime_overlay_mode if self._control_enabled("regime_overlay") else "off",
        )
        target_exposure_proxy = exposure_authorization["authorized_exposure_max"]
        desired_exposure_target = float(target_exposure_proxy)
        risk_exposure_ceiling = float(target_exposure_proxy)
        lot_feasible_target_exposure = float(target_exposure_proxy)
        strategic_policy = (
            resolve_policy_band(
                risk_level=str(risk_level),
                structural_regime_level=str(structural_regime_level),
                policy_bands=self.capital_profile.get("scap_policy_bands"),
            )
            if self.governance_control_mode == "aggressive_lean"
            else None
        )
        strategic_band = (
            resolve_strategic_exposure_band(
                risk_level=str(risk_level),
                structural_regime_level=str(structural_regime_level),
                safety_exposure_cap=safety_exposure_cap,
                policy_bands=self.capital_profile.get("scap_policy_bands"),
            )
            if strategic_policy is not None
            else None
        )
        if (
            is_mainline_v3_version(self.strategy_logic_version)
            and self.capital_usage_mode == GOVERNANCE_CAPITAL_USAGE_MODE_DEFAULT
        ):
            selected_or_add = (
                candidates.get("entry_confirmed", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
                | candidates.get("add_allowed", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
            )
            feasible_increment = float(
                pd.to_numeric(
                    candidates.get("mainline_v3_one_lot_weight", pd.Series(0.0, index=candidates.index)),
                    errors="coerce",
                ).fillna(0.0).where(selected_or_add, 0.0).clip(lower=0.0).sum()
            )
            if self.governance_control_mode == "aggressive_profit":
                scap_targets = build_scap_exposure_targets(
                    actual_exposure=actual_exposure,
                    authorized_risk_ceiling=target_exposure_proxy,
                    feasible_increment=feasible_increment,
                    qualified_entry_count=exposure_signal_count,
                )
                risk_exposure_ceiling = scap_targets.risk_exposure_ceiling
                desired_exposure_target = scap_targets.desired_exposure_target
                lot_feasible_target_exposure = scap_targets.executable_exposure_target
                target_exposure_proxy = scap_targets.executable_exposure_target
            elif self.governance_control_mode == "aggressive_lean":
                target_exposure_proxy = float(strategic_band.hard_ceiling)
                risk_exposure_ceiling = float(strategic_band.hard_ceiling)
                desired_exposure_target = float(strategic_band.target)
                lot_feasible_target_exposure = min(
                    float(strategic_band.hard_ceiling),
                    max(float(actual_exposure), float(strategic_band.target)),
                )
            else:
                lot_feasible_target_exposure = min(
                    float(target_exposure_proxy),
                    float(actual_exposure) + feasible_increment,
                )
                target_exposure_proxy = max(float(actual_exposure), lot_feasible_target_exposure)
        force_deploy_target = self._force_deploy_target_exposure(
            risk_level=risk_level,
            structural_regime_level=structural_regime_level,
            safety_exposure_cap=safety_exposure_cap,
            liquidity_stress=liquidity_stress,
        )
        if (
            force_deploy_target is not None
            and self.governance_control_mode != "aggressive_lean"
        ):
            target_exposure_proxy = max(float(target_exposure_proxy), float(force_deploy_target))
            target_exposure_proxy = min(float(target_exposure_proxy), float(safety_exposure_cap))
        high_exposure_gate = self._high_exposure_research_gate(date)
        high_exposure_cap_applied = False
        if (
            self.governance_control_mode == "aggressive_profit"
            and not bool(high_exposure_gate["gate_pass"])
            and float(target_exposure_proxy) > 0.60
        ):
            # The same authorization is consumed by new entries, both add
            # paths, and replacements through DecisionContext/ActionPlan.
            target_exposure_proxy = 0.60
            desired_exposure_target = min(float(desired_exposure_target), 0.60)
            risk_exposure_ceiling = min(float(risk_exposure_ceiling), 0.60)
            lot_feasible_target_exposure = min(
                float(lot_feasible_target_exposure), 0.60
            )
            high_exposure_cap_applied = True
        catchup_decision = decide_exposure_catchup(
            actual_exposure=actual_exposure,
            target_exposure=(
                desired_exposure_target
                if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}
                else target_exposure_proxy
            ),
            risk_level=risk_level,
            structural_regime_level=structural_regime_level,
            market_liquidity_stress_ratio=liquidity_stress,
            qualified_entry_count=exposure_signal_count,
            transition_only=day_index < GOVERNANCE_INITIAL_TRANSITION_DAYS,
            trailing_buy_accuracy_5d=trailing_buy_accuracy_5d,
            risk_contribution_gate_pass=high_exposure_gate["gate_pass"],
            top5_risk_contribution_sum=high_exposure_gate["latest_top5_risk_contribution_sum"],
            top20pct_risk_contribution_sum=high_exposure_gate[
                "latest_top20pct_risk_contribution_sum"
            ],
            risk_effective_n_ratio=high_exposure_gate[
                "latest_risk_effective_n_ratio"
            ],
            risk_symbol_count=high_exposure_gate["latest_risk_symbol_count"],
            hard_risk_gate_enabled=True,
            representative_one_lot_weight=(
                float(position_capacity.median_one_lot_amount)
                / max(float(exposure.get("nominal_nav", self.initial_cash)), 1e-12)
            ),
            strategic_lower_bound=(
                float(strategic_band.lower_bound)
                if self.governance_control_mode == "aggressive_lean"
                else None
            ),
            recovery_daily_exposure_cap=float(
                self.capital_profile.get("scap_recovery_daily_exposure_cap", 0.15)
                or 0.15
            ),
            recovery_max_new_names=int(
                self.capital_profile.get("scap_recovery_max_new_names_per_day", 1)
                or 1
            ),
            recovery_window_sessions=int(
                self.capital_profile.get("scap_recovery_window_sessions", 5)
                or 5
            ),
        )
        high_exposure_gate_diagnostics = {
            "high_exposure_research_gate_pass": high_exposure_gate["gate_pass"],
            "high_exposure_research_gate_reason": high_exposure_gate["gate_reason"],
            "high_exposure_unified_cap_applied": high_exposure_cap_applied,
            "closed_trade_count_for_gate": high_exposure_gate["closed_trade_count"],
            "closed_trade_win_rate_for_gate": high_exposure_gate["closed_trade_win_rate"],
            "profit_factor_for_gate": high_exposure_gate["profit_factor"],
            "payoff_ratio_for_gate": high_exposure_gate["payoff_ratio"],
            "realized_pnl_for_gate": high_exposure_gate["realized_pnl"],
            "actual_target_ratio_for_gate": high_exposure_gate["actual_target_ratio"],
            "latest_top1_risk_contribution_for_gate": high_exposure_gate["latest_top1_risk_contribution"],
        }
        scenario_started = time.perf_counter()
        portfolio_search_active = bool(
            allow_normal_rebalance or catchup_decision.catchup_allowed
        )
        covariance_matrix = (
            self._rolling_candidate_covariance(date, candidates)
            if portfolio_search_active
            else None
        )
        scenario_return_matrix = (
            self._rolling_candidate_return_scenarios(
                date,
                candidates,
                current_symbols=self.positions,
                horizon_days=int(
                    self.capital_profile.get("scap_forecast_horizon_days", 10) or 10
                ),
            )
            if portfolio_search_active
            else pd.DataFrame()
        )
        scenario_build_elapsed_seconds = time.perf_counter() - scenario_started
        if self.governance_variant == "governance_layer_validation" and self.governance_control_mode == "factor_only":
            covariance_matrix = None
        covariance_state = covariance_runtime_state(day_index=day_index, covariance_matrix=covariance_matrix)
        covariance_for_decision = (
            covariance_matrix
            if covariance_state == "calibrated"
            else None
        )
        runtime_maturity_state = combined_runtime_maturity(
            probability_state=calibration_state,
            reputation_state=reputation_state,
            covariance_state=covariance_state,
            trade_accuracy_state=trade_accuracy_state,
            pit_state=self.pit_runtime_state,
        )
        regime_es_multiplier = self._scap_regime_es_budget_multiplier(date)
        ideal_plan, orders, diagnostics = self.engine.decide_day(
            decision_id=f"gov_{pd.Timestamp(date).strftime('%Y%m%d')}",
            decision_date=date,
            candidates=candidates,
            current_weights=self._current_weights(daily, exposure["nominal_nav"]),
            holding_days=self.holding_days,
            turnover_budget=current_turnover_budget,
            top_n=(
                position_capacity.effective_position_cap
                if is_mainline_v3_version(self.strategy_logic_version)
                else (
                    self._max_positions_override
                    or (
                        GOVERNANCE_DEFAULT_TOP_N
                        if self.strategy_logic_version == MAINLINE_V2
                        else (
                            regime_params.max_positions
                            if regime_params
                            else GOVERNANCE_DEFAULT_TOP_N
                        )
                    )
                )
            ),
            allow_normal_rebalance=allow_normal_rebalance,
            transition_only=day_index < GOVERNANCE_INITIAL_TRANSITION_DAYS,
            hard_qualification_symbols=self._hard_qualification_symbols(),
            catchup_buy_budget=catchup_decision.catchup_buy_budget,
            catchup_allowed=catchup_decision.catchup_allowed,
            active_replacement_enabled=bool(
                self.capital_profile.get("active_replacement_enabled", True)
            ),
            active_replacement_max_pairs_per_day=int(
                self.capital_profile.get(
                    "scap_active_replacement_max_pairs_per_day", 1
                )
                or 0
            ),
            target_exposure_cap=target_exposure_proxy,
            covariance_matrix=covariance_for_decision,
            scenario_return_matrix=scenario_return_matrix,
            nav_amount=float(exposure["nominal_nav"]),
            cash_amount=float(self.cash),
            cash_buffer_amount=float(
                self.capital_profile.get("min_cash_buffer", 0.0) or 0.0
            ),
            per_name_structural_cap=dynamic_hard_cap,
            portfolio_stress_budget_amount=float(exposure["nominal_nav"])
            * float(
                self.capital_profile.get("scap_portfolio_es_budget_ratio", 0.08)
                or 0.08
            )
            * regime_es_multiplier,
            control_mode=self.governance_control_mode,
            winner_add_enabled=scap_winner_add_trading_authorized(
                self.capital_profile
            ),
            loser_add_enabled=bool(
                self.capital_profile.get("scap_loser_averaging_enabled", False)
            ),
            soft_exit_enabled=bool(
                self.capital_profile.get("scap_soft_exit_enabled", True)
            ),
            forecast_horizon_sessions=int(
                self.capital_profile.get("scap_forecast_horizon_days", 10) or 10
            ),
            forecast_kappa=float(
                self.capital_profile.get("scap_forecast_kappa", 0.50) or 0.50
            ),
            soft_target_positions=position_capacity.soft_target_positions,
            execution_cost_profile=self.capital_profile,
            desired_exposure_target=float(desired_exposure_target),
            hard_exposure_ceiling=float(
                min(
                    float(safety_exposure_cap),
                    float(risk_exposure_ceiling),
                )
                if (
                    str(getattr(risk_level, "value", risk_level))
                    .strip()
                    .lower()
                    in {"high", "critical"}
                    or bool(safety_row.get("hard_freeze_active", False))
                    or int(safety_row.get("trigger_streak_days", 0) or 0)
                    >= max(
                        int(
                            self.capital_profile.get(
                                "scap_safety_confirmation_days",
                                1,
                            )
                            or 1
                        ),
                        1,
                    )
                )
                else float(safety_exposure_cap)
            ),
            confirmed_derisk_target=(
                float(risk_exposure_ceiling)
                if (
                    str(getattr(risk_level, "value", risk_level))
                    .strip()
                    .lower()
                    in {"high", "critical"}
                    or bool(safety_row.get("hard_freeze_active", False))
                    or int(safety_row.get("trigger_streak_days", 0) or 0)
                    >= max(
                        int(
                            self.capital_profile.get(
                                "scap_safety_confirmation_days",
                                1,
                            )
                            or 1
                        ),
                        1,
                    )
                )
                else None
            ),
            current_lots_by_symbol={
                str(symbol): max(
                    int(
                        (
                            float(position.shares)
                            + float(
                                trading_rule_for(
                                    symbol,
                                    trade_date=date,
                                ).minimum_buy_quantity
                            )
                            - 1.0
                        )
                        // float(
                            trading_rule_for(
                                symbol,
                                trade_date=date,
                            ).minimum_buy_quantity
                        )
                    ),
                    1,
                )
                for symbol, position in self.positions.items()
                if float(position.shares) > 0.0
            },
            policy_band=strategic_policy,
            recovery_episode_id=self._scap_recovery_episode_id,
            recovery_episode_day=self._scap_recovery_episode_day,
        )
        action_proposal_rows = diagnostics.pop("_action_proposal_rows", [])
        action_plan_rows = diagnostics.pop("_action_plan_rows", [])
        diagnostics["regime_es_budget_multiplier"] = float(regime_es_multiplier)
        diagnostics["portfolio_search_active"] = portfolio_search_active
        diagnostics["scenario_build_elapsed_seconds"] = float(
            scenario_build_elapsed_seconds
        )
        if bool(diagnostics.get("post_mandatory_recovery_authorized", False)):
            self._scap_recovery_episode_id = str(
                diagnostics.get("post_mandatory_recovery_episode_id", "")
            )
            self._scap_recovery_episode_day = int(
                diagnostics.get("post_mandatory_recovery_episode_day", 0) or 0
            )
        else:
            self._scap_recovery_episode_id = ""
            self._scap_recovery_episode_day = 0
        diagnostics["regime_control_authority"] = str(
            self.capital_profile.get(
                "scap_market_regime_control_mode", "legacy_discrete"
            )
        )
        self.action_proposal_rows.extend(action_proposal_rows)
        self.action_plan_rows.extend(action_plan_rows)
        if self.governance_control_mode == "aggressive_lean":
            selected_entry_symbols = {
                str(row.get("symbol", ""))
                for row in action_proposal_rows
                if bool(row.get("selected_by_plan", False))
                and str(row.get("action_type", "")) == "new_entry"
            }
            candidates["scap_optimizer_selected"] = (
                candidates["symbol"].astype(str).isin(selected_entry_symbols)
            )
            today = pd.Timestamp(date).normalize()
            for row in self.entry_formula_audit_rows:
                if pd.Timestamp(row.get("date")).normalize() == today:
                    row["scap_optimizer_selected"] = (
                        str(row.get("symbol", ""))
                        in selected_entry_symbols
                    )
        if self.governance_control_mode != "aggressive_lean":
            orders = self._augment_force_deploy_diversify_orders(
                orders=orders,
                candidates=candidates,
                defensive_candidates=defensive_candidates,
                decision_id=f"gov_{pd.Timestamp(date).strftime('%Y%m%d')}",
                decision_date=date,
                current_weights=self._current_weights(daily, exposure["nominal_nav"]),
                nominal_nav=exposure["nominal_nav"],
                daily=daily,
                target_exposure=target_exposure_proxy,
            )
        else:
            diagnostics["post_action_plan_order_augmentation"] = "disabled_unique_action_plan"
        self.action_decision_rows.extend(build_action_decisions(
            date=date,
            candidates=candidates,
            held_symbols=self.positions,
            orders=orders,
            daily=daily,
            regime_name=regime_name,
        ))
        diagnostics.update(catchup_decision.__dict__)
        diagnostics.update(
            {
                f"position_capacity_{key}": value
                for key, value in position_capacity.as_dict().items()
            }
        )
        for column in (
            "cabinet_raw_factor_count",
            "cabinet_empirical_cluster_count",
            "cabinet_empirical_compression_ratio",
        ):
            if column in candidates.columns and not candidates.empty:
                diagnostics[column] = candidates.iloc[0].get(column, pd.NA)
        diagnostics["dynamic_single_position_soft_cap"] = float(dynamic_soft_cap)
        diagnostics["dynamic_single_position_hard_cap"] = float(dynamic_hard_cap)
        diagnostics["policy_target_exposure_before_lot_cap"] = float(exposure_authorization["authorized_exposure_max"])
        diagnostics["qualified_entry_count"] = int(qualified_entry_count)
        diagnostics["pre_slot_qualified_entry_count"] = int(
            entry_stage_counts["pre_slot_qualified_entry_count"]
        )
        diagnostics["raw_signal_count"] = int(entry_stage_counts["raw_signal_count"])
        diagnostics["structural_feasible_count"] = int(
            entry_stage_counts["structural_feasible_count"]
        )
        diagnostics["cash_feasible_count"] = int(
            entry_stage_counts["cash_feasible_count"]
        )
        diagnostics["slot_feasible_count"] = int(
            entry_stage_counts["slot_feasible_count"]
        )
        diagnostics["optimizer_selected_entry_count"] = int(
            diagnostics.get("lean_optimizer_selected_entry_count", 0)
            if self.governance_control_mode == "aggressive_lean"
            else entry_stage_counts["optimizer_selected_entry_count"]
        )
        diagnostics["exposure_signal_count"] = int(exposure_signal_count)
        diagnostics["lot_feasible_target_exposure"] = float(lot_feasible_target_exposure)
        diagnostics["risk_exposure_ceiling"] = float(risk_exposure_ceiling)
        diagnostics["desired_exposure_target"] = float(desired_exposure_target)
        diagnostics["executable_exposure_target"] = float(lot_feasible_target_exposure)
        if self.governance_control_mode == "aggressive_profit":
            diagnostics.update(scap_targets.as_dict())
            diagnostics["target_exposure"] = float(desired_exposure_target)
            diagnostics["effective_target_exposure_cap"] = float(lot_feasible_target_exposure)
        elif self.governance_control_mode == "aggressive_lean":
            diagnostics["strategic_exposure_budget"] = float(
                desired_exposure_target
            )
            diagnostics["actual_exposure"] = float(actual_exposure)
            diagnostics["execution_drag"] = max(
                float(diagnostics.get("planned_exposure", actual_exposure))
                - float(actual_exposure),
                0.0,
            )
            diagnostics["optimizer_planned_exposure"] = float(
                diagnostics.get("planned_exposure", actual_exposure)
            )
            # Compatibility target now means the strategic desired exposure.
            # The optimizer plan has its own explicit field and must not be
            # mixed with the gap to the strategic budget.
            diagnostics["target_exposure"] = float(desired_exposure_target)
            diagnostics["effective_target_exposure_cap"] = float(
                risk_exposure_ceiling
            )
        diagnostics.update(high_exposure_gate_diagnostics)
        if (
            not bool(high_exposure_gate["gate_pass"])
            and str(diagnostics.get("catchup_block_reason", "")) == "risk_contribution_gate_blocks_catchup"
        ):
            diagnostics["catchup_block_reason"] = f"high_exposure_gate:{high_exposure_gate['gate_reason']}"
        diagnostics["regime_name"] = str(regime_name)
        diagnostics.update(self._regime_diagnostics_cache.get(pd.Timestamp(date), {}))
        diagnostics["regime_diagnostics_enabled"] = self.market_regime_policy is not None
        diagnostics["regime_control_authorized"] = bool(
            self.enable_market_regime_policy and self._control_enabled("regime")
        )
        diagnostics.update(
            build_market_state_authority_disclosure(
                safety_structural_state=structural_regime_level,
                safety_agent_enabled=self.enable_safety_agent,
                optional_overlay_enabled=self.enable_market_regime_policy,
                optional_overlay_authorized=diagnostics["regime_control_authorized"],
                optional_input_valid=bool(diagnostics.get("regime_input_valid", False)),
                optional_confirmed_label=str(diagnostics.get("regime_confirmed_label", "unknown")),
            )
        )
        diagnostics["performance_benchmark_role"] = "performance_attribution"
        diagnostics["performance_benchmark_distinct_from_regime_proxy"] = True
        diagnostics["base_exposure_by_regime"] = _base_exposure_by_regime(regime_name)
        diagnostics.update(exposure_authorization)
        diagnostics["trailing_buy_accuracy_5d"] = trailing_buy_accuracy_5d
        retail_diagnostics = self._register_orders(orders, daily, exposure["nominal_nav"])
        diagnostics.update(retail_diagnostics)
        today_entry_audit = [
            row for row in self.entry_formula_audit_rows
            if pd.Timestamp(row.get("date")).normalize() == pd.Timestamp(date).normalize()
        ]
        candidate_funnel_row["capital_pass_count"] = int(
            sum(bool(row.get("retail_executable", False)) for row in today_entry_audit)
        )
        candidate_funnel_row["candidate_detail_count"] = int(len(today_entry_audit))
        candidate_funnel_row["ideal_portfolio_count"] = int(len(ideal_plan))
        candidate_funnel_row["order_count"] = int(len(orders))
        if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}:
            from functions.decision_council.candidate_funnel_audit import (
                classify_scap_registered_buys,
            )

            registered_buy_counts = classify_scap_registered_buys(orders)
            if self.governance_control_mode == "aggressive_lean":
                funnel_stage_counts = {
                    "raw_signal_count": int(
                        diagnostics.get("lean_raw_entry_signal_count", 0)
                    ),
                    "structural_feasible_count": int(
                        diagnostics.get("lean_structural_feasible_entry_count", 0)
                    ),
                    "cash_feasible_count": int(
                        diagnostics.get("lean_cash_feasible_entry_count", 0)
                    ),
                    "slot_feasible_count": int(
                        diagnostics.get("lean_slot_feasible_entry_count", 0)
                    ),
                    "optimizer_selected_entry_count": int(
                        diagnostics.get("lean_optimizer_selected_entry_count", 0)
                    ),
                }
            else:
                funnel_stage_counts = entry_stage_counts
            candidate_funnel_row.update(
                {
                    "scap_raw_signal_count": int(funnel_stage_counts["raw_signal_count"]),
                    "scap_structural_feasible_count": int(
                        funnel_stage_counts["structural_feasible_count"]
                    ),
                    "scap_cash_feasible_count": int(
                        funnel_stage_counts["cash_feasible_count"]
                    ),
                    "scap_slot_feasible_count": int(
                        funnel_stage_counts["slot_feasible_count"]
                    ),
                    "scap_optimizer_selected_count": int(
                        funnel_stage_counts["optimizer_selected_entry_count"]
                    ),
                    # Only first-entry buys belong to the candidate subset
                    # chain. Adds and paired replacement buys have different
                    # denominators and are audited separately.
                    "scap_registered_buy_count": registered_buy_counts[
                        "entry_buy_count"
                    ],
                    "scap_registered_add_buy_count": registered_buy_counts[
                        "add_buy_count"
                    ],
                    "scap_registered_replacement_buy_count": registered_buy_counts[
                        "replacement_buy_count"
                    ],
                }
            )
            from functions.decision_council.candidate_funnel_audit import (
                assert_scap_funnel_monotonic,
            )

            assert_scap_funnel_monotonic(candidate_funnel_row)
        authority_tiers = candidates.get(
            "scap_v31_authority_tier",
            pd.Series(dtype=str),
        ).fillna("D").astype(str).str.upper()
        positive_c_fallback_count = int(authority_tiers.eq("C").sum())
        all_d_today = bool(
            self.governance_control_mode == "aggressive_lean"
            and len(authority_tiers) > 0
            and authority_tiers.eq("D").all()
        )
        self._scap_v31_all_d_streak = (
            self._scap_v31_all_d_streak + 1 if all_d_today else 0
        )
        current_idle_cash_ratio = float(
            exposure.get("cash", self.cash) or 0.0
        ) / max(
            float(
                exposure.get("nominal_nav", self.initial_cash)
                or self.initial_cash
            ),
            1e-12,
        )
        normal_cash_zero_proposal = bool(
            self.governance_control_mode == "aggressive_lean"
            and str(getattr(risk_level, "value", risk_level)).strip().upper()
            == "NORMAL"
            and current_idle_cash_ratio >= 0.30
            and int(candidate_funnel_row.get("scap_raw_signal_count", 0)) == 0
        )
        self._scap_v31_normal_cash_zero_proposal_streak = (
            self._scap_v31_normal_cash_zero_proposal_streak + 1
            if normal_cash_zero_proposal
            else 0
        )
        liveness_streak = max(
            self._scap_v31_all_d_streak,
            self._scap_v31_normal_cash_zero_proposal_streak,
        )
        liveness_alert = (
            "red"
            if liveness_streak >= 10
            else ("yellow" if liveness_streak >= 5 else "none")
        )
        candidate_funnel_row.update(
            {
                "scap_v31_positive_c_fallback_count": positive_c_fallback_count,
                "scap_v31_all_d_streak": self._scap_v31_all_d_streak,
                "scap_v31_normal_cash_zero_proposal_streak": (
                    self._scap_v31_normal_cash_zero_proposal_streak
                ),
                "scap_v31_position_recovery_alert": liveness_alert,
            }
        )
        self.candidate_funnel_rows.append(candidate_funnel_row)
        holding_targets = _holding_target_contract(
            self.capital_profile,
            actual_holding_count=int(exposure.get("holding_count", 0) or 0),
            max_positions_override=position_capacity.effective_position_cap,
        )
        if strategic_band is not None:
            maximum_positions = holding_targets["maximum_allowed_holding_count"]
            conditional_minimum = min(
                int(
                    diagnostics.get(
                        "conditional_holding_floor",
                        strategic_band.conditional_min_holdings,
                    )
                ),
                maximum_positions,
            )
            soft_positions = min(
                max(
                    int(
                        diagnostics.get(
                            "policy_holding_target",
                            strategic_band.soft_target_holdings,
                        )
                    ),
                    conditional_minimum,
                ),
                maximum_positions,
            )
            holding_targets.update(
                {
                    "minimum_required_holding_count": conditional_minimum,
                    "soft_target_holding_count": soft_positions,
                    "soft_holding_shortfall_count": max(
                        soft_positions - int(exposure.get("holding_count", 0) or 0),
                        0,
                    ),
                }
            )
        action_plan_target_holding_count = int(
            diagnostics.get(
                "action_plan_target_holding_count",
                holding_targets["soft_target_holding_count"],
            )
            or 0
        )
        actual_holding_count = int(exposure.get("holding_count", 0) or 0)
        holding_semantics = build_holding_semantics(
            minimum_required=holding_targets["minimum_required_holding_count"],
            soft_target=holding_targets["soft_target_holding_count"],
            maximum_allowed=holding_targets["maximum_allowed_holding_count"],
            optimizer_planned=action_plan_target_holding_count,
            actual=actual_holding_count,
        )
        strategic_lower_bound = float(
            strategic_band.lower_bound
            if strategic_band is not None
            else min(float(desired_exposure_target), 0.60)
        )
        strategic_upper_bound = float(
            strategic_band.upper_bound
            if strategic_band is not None
            else max(
                float(desired_exposure_target),
                min(float(risk_exposure_ceiling), float(safety_exposure_cap)),
            )
        )
        hard_risk_ceiling = float(
            strategic_band.hard_ceiling
            if strategic_band is not None
            else max(
                strategic_upper_bound,
                min(float(risk_exposure_ceiling), float(safety_exposure_cap)),
            )
        )
        attainable_ceiling = min(
            max(float(lot_feasible_target_exposure), float(actual_exposure)),
            1.0,
        )
        optimizer_planned_exposure = min(
            max(float(diagnostics.get("planned_exposure", actual_exposure)), 0.0),
            1.0,
        )
        exposure_semantics = build_exposure_semantics(
            strategic_target=float(desired_exposure_target),
            strategic_lower_bound=strategic_lower_bound,
            strategic_upper_bound=strategic_upper_bound,
            hard_risk_ceiling=hard_risk_ceiling,
            attainable_ceiling=attainable_ceiling,
            optimizer_planned=optimizer_planned_exposure,
            actual=float(actual_exposure),
        )
        self.exposure_rows[-1].update(
            {
                "target_exposure": diagnostics["target_exposure"],
                "strategy_logic_version": self.strategy_logic_version,
                "policy_band_state": diagnostics.get("policy_band_state", ""),
                "policy_holding_floor": int(diagnostics.get("policy_holding_floor", 0) or 0),
                "policy_holding_target": int(diagnostics.get("policy_holding_target", 0) or 0),
                "policy_exposure_lower": float(diagnostics.get("policy_exposure_lower", 0.0) or 0.0),
                "policy_exposure_target": float(diagnostics.get("policy_exposure_target", 0.0) or 0.0),
                "policy_exposure_upper": float(diagnostics.get("policy_exposure_upper", 0.0) or 0.0),
                "policy_disaster_exposure_ceiling": float(diagnostics.get("policy_disaster_exposure_ceiling", 0.0) or 0.0),
                "post_mandatory_holding_count": int(diagnostics.get("post_mandatory_holding_count", 0) or 0),
                "post_mandatory_exposure": float(diagnostics.get("post_mandatory_exposure", 0.0) or 0.0),
                "post_mandatory_cash": float(diagnostics.get("post_mandatory_cash", 0.0) or 0.0),
                "conditional_holding_floor": int(diagnostics.get("conditional_holding_floor", 0) or 0),
                "conditional_exposure_floor": float(diagnostics.get("conditional_exposure_floor", 0.0) or 0.0),
                "daily_effective_holding_ceiling": int(diagnostics.get("daily_effective_holding_ceiling", position_capacity.effective_position_cap) or 0),
                "daily_effective_exposure_ceiling": float(diagnostics.get("daily_effective_exposure_ceiling", risk_exposure_ceiling) or 0.0),
                "positive_feasible_new_name_count": int(diagnostics.get("positive_feasible_new_name_count", 0) or 0),
                "post_mandatory_recovery_authorized": bool(diagnostics.get("post_mandatory_recovery_authorized", False)),
                "post_mandatory_recovery_reason": str(diagnostics.get("post_mandatory_recovery_reason", "")),
                "post_mandatory_recovery_episode_id": str(diagnostics.get("post_mandatory_recovery_episode_id", "")),
                "post_mandatory_recovery_episode_day": int(diagnostics.get("post_mandatory_recovery_episode_day", 0) or 0),
                "post_mandatory_recovery_holding_deficit": int(diagnostics.get("post_mandatory_recovery_holding_deficit", 0) or 0),
                "post_mandatory_recovery_exposure_deficit": float(diagnostics.get("post_mandatory_recovery_exposure_deficit", 0.0) or 0.0),
                "post_mandatory_recovery_max_new_names_today": int(diagnostics.get("post_mandatory_recovery_max_new_names_today", 0) or 0),
                "post_mandatory_recovery_max_buy_exposure_today": float(diagnostics.get("post_mandatory_recovery_max_buy_exposure_today", 0.0) or 0.0),
                "post_mandatory_recovery_deadline_sessions": int(diagnostics.get("post_mandatory_recovery_deadline_sessions", 0) or 0),
                "wealth_materiality_epsilon_amount": float(diagnostics.get("wealth_materiality_epsilon_amount", 0.0) or 0.0),
                "planned_holding_count": int(diagnostics.get("planned_holding_count", 0) or 0),
                "holding_floor_violation_count": int(diagnostics.get("holding_floor_violation_count", 0) or 0),
                "exposure_floor_violation": float(diagnostics.get("exposure_floor_violation", 0.0) or 0.0),
                "policy_holding_ceiling": int(diagnostics.get("policy_holding_ceiling", 0) or 0),
                "policy_minimum_active_pool_size": int(diagnostics.get("policy_minimum_active_pool_size", 0) or 0),
                "policy_minimum_effective_n_ratio": float(diagnostics.get("policy_minimum_effective_n_ratio", 0.0) or 0.0),
                "policy_minimum_pool_count": int(diagnostics.get("policy_minimum_pool_count", 0) or 0),
                "policy_maximum_names_per_pool": int(diagnostics.get("policy_maximum_names_per_pool", 0) or 0),
                "policy_holding_floor_violation_count": int(diagnostics.get("policy_holding_floor_violation_count", 0) or 0),
                "policy_floor_feasible_pre_optimizer": bool(diagnostics.get("policy_floor_feasible_pre_optimizer", False)),
                "atomic_pool_violation_count": int(diagnostics.get("atomic_pool_violation_count", 0) or 0),
                "planned_effective_n": float(diagnostics.get("planned_effective_n", 0.0) or 0.0),
                "effective_n_violation": float(diagnostics.get("effective_n_violation", 0.0) or 0.0),
                "planned_pool_count": int(diagnostics.get("planned_pool_count", 0) or 0),
                "pool_count_violation": int(diagnostics.get("pool_count_violation", 0) or 0),
                "orphan_pool_recovery_active": bool(diagnostics.get("orphan_pool_recovery_active", False)),
                "orphan_pool_breach": bool(diagnostics.get("orphan_pool_breach", False)),
                "orphan_pool_recovery_deadline_breached": bool(diagnostics.get("orphan_pool_recovery_deadline_breached", False)),
                "calibration_runtime_state": calibration_state,
                "reputation_runtime_state": reputation_state,
                "covariance_runtime_state": covariance_state,
                "covariance_candidate_coverage_ratio": float(
                    getattr(covariance_matrix, "attrs", {}).get(
                        "candidate_coverage_ratio",
                        0.0,
                    )
                ) if covariance_matrix is not None else 0.0,
                "covariance_estimator": str(
                    getattr(covariance_matrix, "attrs", {}).get(
                        "estimator",
                        "fallback",
                    )
                ) if covariance_matrix is not None else "fallback",
                "trade_accuracy_runtime_state": trade_accuracy_state,
                "runtime_maturity_state": runtime_maturity_state,
                "pit_runtime_state": self.pit_runtime_state,
                "pit_level2_runtime_state": self.pit_level2_runtime_state,
                "factor_temporal_isolation_status": (
                    "PASS" if self.factor_temporal_isolation_pass else "FAIL_OR_NOT_EVALUATED"
                ),
                "capital_usage_mode": self.capital_usage_mode,
                "force_deploy_enabled": self.capital_usage_mode == GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY,
                # Keep the account configuration distinct from the minimum/target
                # holding count.  Reports must not infer a hard position limit
                # from the profile's diversification target.
                "configured_max_positions": (
                    int(position_capacity.user_hard_cap)
                    if position_capacity.user_hard_cap is not None
                    else pd.NA
                ),
                "user_hard_position_cap": (
                    int(position_capacity.user_hard_cap)
                    if position_capacity.user_hard_cap is not None
                    else pd.NA
                ),
                "economic_position_cap": int(position_capacity.economic_position_cap),
                "lot_cash_position_cap": int(position_capacity.lot_cash_position_cap),
                "cost_feasible_position_cap": int(
                    position_capacity.cost_feasible_position_cap
                ),
                "risk_feasible_position_cap": int(
                    position_capacity.risk_feasible_position_cap
                ),
                "search_position_cap": int(position_capacity.search_cap),
                "effective_position_cap": int(position_capacity.effective_position_cap),
                "sizing_reference_positions": int(
                    position_capacity.sizing_reference_positions
                ),
                "capacity_spendable_cash": float(position_capacity.spendable_cash),
                "capacity_risk_room_amount": float(position_capacity.capacity_risk_room_amount),
                "capacity_minimum_economic_order_amount": float(position_capacity.minimum_economic_order_amount),
                "capacity_median_one_lot_amount": float(position_capacity.median_one_lot_amount),
                "grandfathered_excess_names": int(
                    position_capacity.grandfathered_excess_names
                ),
                "position_capacity_mode": position_capacity.mode,
                "position_capacity_reason": position_capacity.reason,
                "selected_position_count": diagnostics.get(
                    "selected_position_count", 0
                ),
                "profit_coverage_ratio": diagnostics.get(
                    "profit_coverage_ratio", 0.0
                ),
                "profit_coverage_probability_lower": diagnostics.get(
                    "profit_coverage_probability_lower", 0.0
                ),
                "coverage_evidence_name_count": diagnostics.get(
                    "coverage_evidence_name_count", 0
                ),
                "coverage_state": diagnostics.get(
                    "coverage_state", "not_applicable"
                ),
                "coverage_mode": diagnostics.get(
                    "coverage_mode", "diagnostic_shadow"
                ),
                "coverage_penalty_amount": diagnostics.get(
                    "coverage_penalty_amount", 0.0
                ),
                "hold_baseline_objective_amount": diagnostics.get(
                    "hold_baseline_objective_amount", 0.0
                ),
                "incremental_expected_wealth_amount": diagnostics.get(
                    "incremental_expected_wealth_amount", 0.0
                ),
                "incremental_cvar_amount": diagnostics.get(
                    "incremental_cvar_amount", 0.0
                ),
                "model_uncertainty_amount": diagnostics.get(
                    "model_uncertainty_amount", 0.0
                ),
                "scenario_risk_penalty_amount": diagnostics.get(
                    "scenario_risk_penalty_amount", 0.0
                ),
                "scenario_evidence_state": diagnostics.get(
                    "scenario_evidence_state", "not_applicable"
                ),
                "scenario_contract_id": diagnostics.get(
                    "scenario_contract_id", ""
                ),
                "scenario_risk_measure": diagnostics.get(
                    "scenario_risk_measure", "correlated_tail_loss_proxy"
                ),
                "joint_scenario_count": diagnostics.get(
                    "joint_scenario_count", 0
                ),
                "regime_es_budget_multiplier": diagnostics.get(
                    "regime_es_budget_multiplier", 1.0
                ),
                "best_rejected_proposal_ids": diagnostics.get(
                    "best_rejected_proposal_ids", ()
                ),
                "best_rejected_objective_amount": diagnostics.get(
                    "best_rejected_objective_amount", 0.0
                ),
                "best_rejected_expected_wealth_amount": diagnostics.get(
                    "best_rejected_expected_wealth_amount", 0.0
                ),
                "best_rejected_cvar_amount": diagnostics.get(
                    "best_rejected_cvar_amount", 0.0
                ),
                "best_rejected_model_uncertainty_amount": diagnostics.get(
                    "best_rejected_model_uncertainty_amount", 0.0
                ),
                "expected_positive_pnl_amount": diagnostics.get(
                    "expected_positive_pnl_amount", 0.0
                ),
                "expected_loss_pnl_amount": diagnostics.get(
                    "expected_loss_pnl_amount", 0.0
                ),
                "lifecycle_cost_amount": diagnostics.get(
                    "lifecycle_cost_amount", 0.0
                ),
                "expected_log_growth": diagnostics.get(
                    "expected_log_growth", 0.0
                ),
                "minimum_selected_marginal_utility_amount": diagnostics.get(
                    "minimum_selected_marginal_utility_amount", 0.0
                ),
                "maximum_rejected_marginal_utility_amount": diagnostics.get(
                    "maximum_rejected_marginal_utility_amount", 0.0
                ),
                "cabinet_raw_factor_count": diagnostics.get(
                    "cabinet_raw_factor_count", pd.NA
                ),
                "cabinet_empirical_cluster_count": diagnostics.get(
                    "cabinet_empirical_cluster_count", pd.NA
                ),
                "cabinet_empirical_compression_ratio": diagnostics.get(
                    "cabinet_empirical_compression_ratio", pd.NA
                ),
                "minimum_required_holding_count": holding_semantics.minimum_required_holding_count,
                "soft_target_holding_count": holding_semantics.soft_target_holding_count,
                "maximum_allowed_holding_count": holding_semantics.maximum_allowed_holding_count,
                # Compatibility field is permanently strategic.  It must not
                # shrink when the optimizer selects no buy.
                "target_holding_count": holding_semantics.soft_target_holding_count,
                "action_plan_target_holding_count": action_plan_target_holding_count,
                "optimizer_planned_holding_count": holding_semantics.optimizer_planned_holding_count,
                "strategic_holding_shortfall_count": holding_semantics.strategic_holding_shortfall_count,
                "execution_holding_shortfall_count": holding_semantics.execution_holding_shortfall_count,
                "optimizer_planned_excess_holding_count": holding_semantics.optimizer_planned_excess_holding_count,
                "actual_excess_holding_count": holding_semantics.actual_excess_holding_count,
                "holding_shortfall_count": holding_semantics.strategic_holding_shortfall_count,
                "exposure_semantics_contract_version": exposure_semantics.contract_version,
                "strategic_exposure_band_state": (
                    strategic_band.state if strategic_band is not None else "legacy"
                ),
                **{
                    key: value
                    for key, value in exposure_semantics.as_dict().items()
                    if key != "contract_version"
                },
                "idle_cash": float(exposure.get("cash", self.cash) or 0.0),
                "idle_cash_ratio": float(exposure.get("cash", self.cash) or 0.0) / max(float(exposure.get("nominal_nav", self.initial_cash) or self.initial_cash), 1e-12),
                "scap_v31_positive_c_fallback_count": positive_c_fallback_count,
                "scap_v31_all_d_streak": self._scap_v31_all_d_streak,
                "scap_v31_normal_cash_zero_proposal_streak": (
                    self._scap_v31_normal_cash_zero_proposal_streak
                ),
                "scap_v31_position_recovery_alert": liveness_alert,
                "defensive_candidate_count": int(len(defensive_candidates)) if defensive_candidates is not None else 0,
                "defensive_eligible_count": (
                    int(defensive_candidates.get("defensive_state", pd.Series(dtype=str)).astype(str).eq("eligible_defensive").sum())
                    if defensive_candidates is not None and not defensive_candidates.empty
                    else 0
                ),
                "unresolved_safety_exposure": diagnostics["unresolved_safety_exposure"],
                "constraint_cash_reserve": diagnostics["constraint_cash_reserve"],
                "allow_normal_rebalance": allow_normal_rebalance,
                "actual_exposure": diagnostics.get("actual_exposure", actual_exposure),
                "exposure_gap": diagnostics.get("exposure_gap", 0.0),
                "catchup_allowed": diagnostics.get("catchup_allowed", False),
                "catchup_buy_budget": diagnostics.get("catchup_buy_budget", 0.0),
                "catchup_block_reason": diagnostics.get("catchup_block_reason", ""),
                "catchup_tier": diagnostics.get("catchup_tier", "none"),
                "accuracy_multiplier": diagnostics.get("accuracy_multiplier", 0.0),
                "high_exposure_research_gate_pass": diagnostics.get("high_exposure_research_gate_pass", False),
                "high_exposure_research_gate_reason": diagnostics.get("high_exposure_research_gate_reason", ""),
                "closed_trade_count_for_gate": diagnostics.get("closed_trade_count_for_gate", 0),
                "closed_trade_win_rate_for_gate": diagnostics.get("closed_trade_win_rate_for_gate", pd.NA),
                "profit_factor_for_gate": diagnostics.get("profit_factor_for_gate", pd.NA),
                "payoff_ratio_for_gate": diagnostics.get("payoff_ratio_for_gate", pd.NA),
                "realized_pnl_for_gate": diagnostics.get("realized_pnl_for_gate", 0.0),
                "actual_target_ratio_for_gate": diagnostics.get("actual_target_ratio_for_gate", pd.NA),
                "latest_top1_risk_contribution_for_gate": diagnostics.get("latest_top1_risk_contribution_for_gate", pd.NA),
                "qualified_entry_count": diagnostics.get("qualified_entry_count", 0),
                "pre_slot_qualified_entry_count": diagnostics.get("pre_slot_qualified_entry_count", 0),
                "raw_signal_count": diagnostics.get("raw_signal_count", 0),
                "structural_feasible_count": diagnostics.get("structural_feasible_count", 0),
                "cash_feasible_count": diagnostics.get("cash_feasible_count", 0),
                "slot_feasible_count": diagnostics.get("slot_feasible_count", 0),
                "optimizer_selected_entry_count": diagnostics.get("optimizer_selected_entry_count", 0),
                "exposure_signal_count": diagnostics.get("exposure_signal_count", 0),
                "regime_name": diagnostics.get("regime_name", ""),
                "regime_input_valid": diagnostics.get("regime_input_valid", False),
                "regime_input_status": diagnostics.get("regime_input_status", "unknown"),
                "regime_benchmark_symbol": diagnostics.get("regime_benchmark_symbol", str(MARKET_REGIME_BENCHMARK_SYMBOL)),
                "regime_benchmark_role": diagnostics.get("regime_benchmark_role", "safety_control_proxy"),
                "regime_benchmark_observed": diagnostics.get("regime_benchmark_observed", False),
                "regime_benchmark_lag_days": diagnostics.get("regime_benchmark_lag_days", pd.NA),
                "regime_breadth_score": diagnostics.get("regime_breadth_score", pd.NA),
                "regime_breadth_coverage": diagnostics.get("regime_breadth_coverage", 0.0),
                "regime_raw_label": diagnostics.get("regime_raw_label", "unknown"),
                "regime_confirmed_label": diagnostics.get("regime_confirmed_label", diagnostics.get("regime_name", "unknown")),
                "regime_as_of_date": diagnostics.get("regime_as_of_date", pd.Timestamp(date)),
                "regime_diagnostics_enabled": diagnostics.get("regime_diagnostics_enabled", False),
                "regime_control_authorized": diagnostics.get("regime_control_authorized", False),
                "market_state_semantics_contract_version": diagnostics.get("market_state_semantics_contract_version", ""),
                "safety_market_state_active": diagnostics.get("safety_market_state_active", False),
                "safety_structural_state": diagnostics.get("safety_structural_state", "unknown"),
                "safety_market_state_authority": diagnostics.get("safety_market_state_authority", "disabled"),
                "optional_regime_overlay_enabled": diagnostics.get("optional_regime_overlay_enabled", False),
                "optional_regime_overlay_authorized": diagnostics.get("optional_regime_overlay_authorized", False),
                "optional_regime_overlay_state": diagnostics.get("optional_regime_overlay_state", "unknown"),
                "optional_regime_overlay_authority": diagnostics.get("optional_regime_overlay_authority", "diagnostics_only_no_trade_authority"),
                "performance_benchmark_authority": diagnostics.get("performance_benchmark_authority", "attribution_only_no_trade_authority"),
                "safety_benchmark_authority": diagnostics.get("safety_benchmark_authority", "safety_market_state_input"),
                "performance_benchmark_role": diagnostics.get("performance_benchmark_role", "performance_attribution"),
                "performance_benchmark_distinct_from_regime_proxy": diagnostics.get("performance_benchmark_distinct_from_regime_proxy", True),
                "base_exposure_by_regime": diagnostics.get("base_exposure_by_regime", 0.0),
                "raw_safety_exposure_cap": diagnostics.get("raw_safety_exposure_cap", safety_exposure_cap),
                "effective_target_exposure_cap": diagnostics.get("effective_target_exposure_cap", target_exposure_proxy),
                "policy_target_exposure_before_lot_cap": diagnostics.get("policy_target_exposure_before_lot_cap", target_exposure_proxy),
                "lot_feasible_target_exposure": diagnostics.get("lot_feasible_target_exposure", target_exposure_proxy),
                "risk_exposure_ceiling": diagnostics.get("risk_exposure_ceiling", target_exposure_proxy),
                "hard_exposure_ceiling": diagnostics.get(
                    "hard_exposure_ceiling",
                    diagnostics.get(
                        "risk_exposure_ceiling",
                        target_exposure_proxy,
                    ),
                ),
                "desired_exposure_target": diagnostics.get("desired_exposure_target", target_exposure_proxy),
                "executable_exposure_target": diagnostics.get("executable_exposure_target", target_exposure_proxy),
                "optimizer_planned_exposure": diagnostics.get(
                    "optimizer_planned_exposure",
                    diagnostics.get("planned_exposure", actual_exposure),
                ),
                "signal_cash_drag": diagnostics.get("signal_cash_drag", 0.0),
                "lot_feasibility_drag": diagnostics.get("lot_feasibility_drag", 0.0),
                "risk_ceiling_drag": diagnostics.get("risk_ceiling_drag", 0.0),
                "authorized_exposure_max": diagnostics.get("authorized_exposure_max", target_exposure_proxy),
                "exposure_authorization_tier": diagnostics.get("exposure_authorization_tier", ""),
                "exposure_authorization_block_reasons": diagnostics.get("exposure_authorization_block_reasons", ""),
                "governance_control_mode": self.governance_control_mode,
                "reputation_control_enabled": self._control_enabled("reputation"),
                "regime_control_enabled": bool(
                    self.enable_market_regime_policy and self._control_enabled("regime")
                ),
                "cooldown_control_enabled": self._control_enabled("cooldown"),
                "hard_stop_control_enabled": self._control_enabled("hard_stop_exit"),
                "alpha_collapse_exit_enabled": self.alpha_collapse_exit_enabled,
                "regime_overlay_mode": diagnostics.get("regime_overlay_mode", self.regime_overlay_mode),
                "regime_overlay_capped": diagnostics.get("regime_overlay_capped", False),
                "authorization_expected_edge_10d_mean": diagnostics.get("authorization_expected_edge_10d_mean", 0.0),
                "authorization_p_win_10d_mean": diagnostics.get("authorization_p_win_10d_mean", 0.0),
                "trailing_buy_accuracy_5d": trailing_buy_accuracy_5d,
                "best_replacement_edge_10d": diagnostics.get("best_replacement_edge_10d", 0.0),
                "replacement_opportunity_sell_count": diagnostics.get("replacement_opportunity_sell_count", 0),
                "profit_giveback_observation_count": diagnostics.get("profit_giveback_observation_count", 0),
                "post_entry_failure_exit_count": diagnostics.get("post_entry_failure_exit_count", 0),
                "trend_break_observation_count": diagnostics.get("trend_break_observation_count", 0),
                "volume_distribution_observation_count": diagnostics.get("volume_distribution_observation_count", 0),
                "covariance_risk_model_used": diagnostics.get("covariance_risk_model_used", False),
                "portfolio_covariance_volatility": diagnostics.get("portfolio_covariance_volatility", 0.0),
                "max_risk_contribution": diagnostics.get("max_risk_contribution", 0.0),
                "risk_contribution_gate_pass": diagnostics.get("risk_contribution_gate_pass", True),
                "risk_contribution_exposure_scale": diagnostics.get("risk_contribution_exposure_scale", 1.0),
                "risk_symbol_count": diagnostics.get("risk_symbol_count", 0),
                "risk_contribution_block_reason": diagnostics.get("risk_contribution_block_reason", ""),
                "top5_risk_contribution_sum": diagnostics.get("top5_risk_contribution_sum", 0.0),
                "top20pct_risk_contribution_sum": diagnostics.get("top20pct_risk_contribution_sum", 0.0),
                "risk_effective_n": diagnostics.get("risk_effective_n", 0.0),
                "risk_effective_n_ratio": diagnostics.get("risk_effective_n_ratio", 0.0),
                "risk_contribution_hhi": diagnostics.get("risk_contribution_hhi", 0.0),
                "risk_new_buy_block": diagnostics.get("risk_new_buy_block", False),
                "risk_catchup_block": diagnostics.get("risk_catchup_block", False),
                "risk_new_buy_block_applied": diagnostics.get("risk_new_buy_block_applied", False),
                "risk_catchup_block_applied": diagnostics.get("risk_catchup_block_applied", False),
                "risk_blocked_new_buy_weight": diagnostics.get("risk_blocked_new_buy_weight", 0.0),
                "avg_pairwise_correlation": diagnostics.get("avg_pairwise_correlation", 0.0),
                "covariance_condition_number": diagnostics.get("covariance_condition_number", 0.0),
                "corporate_action_cash_delta": corporate_action_summary["cash_delta"],
                "corporate_action_stock_dividend_shares": corporate_action_summary["stock_dividend_shares"],
                "retail_order_count": retail_diagnostics.get("retail_order_count", 0),
                "retail_upgraded_to_one_lot_count": retail_diagnostics.get("retail_upgraded_to_one_lot_count", 0),
                "retail_blocked_count": retail_diagnostics.get("retail_blocked_count", 0),
                "retail_lot_cash_insufficient_count": retail_diagnostics.get("retail_lot_cash_insufficient_count", 0),
                "retail_state_block_count": retail_diagnostics.get("retail_state_block_count", 0),
                "zero_lot_order_count": retail_diagnostics.get("zero_lot_order_count", 0),
                "zero_lot_buy_order_count": retail_diagnostics.get("zero_lot_buy_order_count", 0),
                "zero_lot_sell_order_count": retail_diagnostics.get("zero_lot_sell_order_count", 0),
            }
        )
        market_total_amount = float(pd.to_numeric(daily["amount"], errors="coerce").fillna(0.0).sum())
        impact = self.engine.safety_agent.safety_sell_flow_impact(
            diagnostics["planned_safety_sell_weight"] * exposure["nominal_nav"],
            market_total_amount,
        )
        self.exposure_rows[-1]["safety_sell_flow_impact_estimate"] = impact
        self.exposure_rows[-1]["safety_sell_flow_impact_alert"] = bool(impact > 0.02)
        self.exposure_rows[-1]["locked_position_alert_count"] = len(self.engine.pending_orders.lock_alerts())
        self.engine.record_exposure(self.exposure_rows[-1])
        if not self.shadow_fast_mode:
            self._record_account_audit(date)
            self._latest_monitor_state = self._build_live_monitor_state(
                date=date,
                candidates=candidates,
                proposals=proposals,
                orders=orders,
                diagnostics=diagnostics,
                regime_params=regime_params,
                turnover_budget=current_turnover_budget,
                exposure=exposure,
            )
        self._advance_holding_days()
        return matured_reward

    def _build_live_monitor_state(self, *, date, candidates, proposals, orders, diagnostics, regime_params, turnover_budget, exposure):
        safety_row = self.engine.safety_signals.loc[pd.Timestamp(date)]
        if isinstance(safety_row, pd.DataFrame):
            safety_row = safety_row.iloc[-1]
        factual_exposure_row = (
            dict(self.exposure_rows[-1]) if self.exposure_rows else {}
        )

        candidate_preview = []
        candidate_cols = [
            column
            for column in [
                "symbol",
                "primary_score",
                "alpha_percentile",
                "expected_return_5d",
                "aggregate_confidence",
                "p_win_10d_calibrated",
                "expected_edge_10d",
                "edge_to_risk_10d",
                "entry_edge_rank_pct",
                "orderflow_candidate_score",
                "reversal_entry_score",
                "breakout_gate_score",
                "trend_hold_score",
                "module_candidate_score",
                "module_entry_score",
                "module_hold_score",
                "entry_matrix_score",
                "entry_alpha_score",
                "entry_timing_score",
                "entry_liquidity_score",
                "alpha_quality_score",
                "surge_capture_score",
                "follow_through_score",
                "exhaustion_score",
                "entry_success_probability",
                "entry_size_tier",
                "planned_entry_lots",
                "trend_direction_score",
                "peak_decay_score",
                "profit_protection_pressure",
                "dynamic_giveback_limit",
                "future_loss_risk_score",
                "downtrend_decay_score",
                "post_entry_failure_score",
                "entry_quality_tier",
                "surge_buy_flag",
                "position_state",
                "add_allowed",
                "add_block_reason",
                "position_exit_reason",
                "cooldown_active",
                "entry_block_reason",
                "cabinet_base_entry_score",
                "cabinet_strict_entry_score",
                "cabinet_proxy_entry_score",
                "cabinet_timing_score",
                "cabinet_liquidity_health_score",
                "cabinet_risk_safety_score",
                "cabinet_hold_support_score",
                "cabinet_entry_thesis",
                "cabinet_entry_thesis_support",
                "scap_v31_authority_tier",
                "scap_v31_authority_reason",
                "scap_v31_decision_expected_return",
                "scap_candidate_utility",
                "scap_optimizer_selected",
            ]
            if column in candidates.columns
        ]
        if candidate_cols:
            preview = candidates.loc[:, candidate_cols].head(8).copy()
            for _, row in preview.iterrows():
                candidate_preview.append({key: row.get(key) for key in candidate_cols})
        confirmed_preview = []
        if candidate_cols and "entry_confirmed" in candidates.columns:
            confirmed = candidates[candidates["entry_confirmed"].fillna(False).astype(bool)]
            for _, row in confirmed.loc[:, candidate_cols].head(8).iterrows():
                confirmed_preview.append({key: row.get(key) for key in candidate_cols})
        entry_block_summary = _top_value_counts(
            candidates.get("entry_block_reason", pd.Series(dtype=object)),
            limit=8,
        )

        order_preview = []
        if orders is not None and not orders.empty:
            order_cols = [
                column
                for column in [
                    "symbol",
                    "side",
                    "delta_weight",
                    "reason",
                    "priority",
                    "position_state",
                    "add_layer",
                    "entry_matrix_score",
                ]
                if column in orders.columns
            ]
            for _, row in orders.loc[:, order_cols].head(10).iterrows():
                order_preview.append({key: row.get(key) for key in order_cols})
        order_reason_summary = _top_value_counts(
            orders.get("reason", pd.Series(dtype=object)) if orders is not None and not orders.empty else pd.Series(dtype=object),
            limit=8,
        )

        pending_preview = []
        pending = self.engine.pending_orders.orders
        if pending is not None and not pending.empty:
            active = pending[pending["status"].isin(["pending", "pending_locked"])].copy()
            pending_cols = [
                column
                for column in [
                    "symbol", "side", "remaining_shares", "status", "reason",
                    "origin_reason", "latest_reason", "highest_priority_reason",
                    "reason_history", "lock_days",
                    "order_execution_policy", "maximum_age_sessions", "signal_age_sessions",
                ]
                if column in active.columns
            ]
            for _, row in active.loc[:, pending_cols].head(10).iterrows():
                pending_preview.append({key: row.get(key) for key in pending_cols})

        factor_weights = self._factor_weight_preview(date=date, proposals=proposals)
        module_weights = _aggregate_factor_modules(factor_weights)
        holding_price_paths = self._holding_price_paths(date=date)
        lifecycle_preview = self._holding_lifecycle_preview()
        benchmark_nav = self._benchmark_nav_asof(date)
        benchmark_audit = {}
        benchmark_frame = getattr(self, "_performance_benchmark_frame", pd.DataFrame())
        if benchmark_frame is not None and not benchmark_frame.empty:
            benchmark_dates = pd.to_datetime(benchmark_frame.get("date"), errors="coerce").dt.normalize()
            matching = benchmark_frame.loc[benchmark_dates.eq(pd.Timestamp(date).normalize())]
            if not matching.empty:
                benchmark_audit = matching.iloc[-1].to_dict()
        nav_amount = float(exposure.get("liquidatable_nav", exposure.get("nominal_nav", self.initial_cash)) or self.initial_cash)
        account_net_value = nav_amount / max(float(self.initial_cash), 1e-12)
        excess_net_value = account_net_value / max(float(benchmark_nav), 1e-12)
        trailing_sell_accuracy_5d = self._trailing_trade_accuracy(date, side="sell", horizon_days=5, lookback_trades=60)
        trade_summary = self._rolling_trade_pair_summary(date)
        lifecycle_alert_count = int(
            sum(
                bool(row.get("profit_giveback_flag", False)) or bool(row.get("post_entry_failure_flag", False))
                for row in lifecycle_preview
            )
        )

        return {
            "runtime_identity_hash": str(
                getattr(self, "runtime_identity", {}).get("runtime_identity_hash", "")
            ),
            "scap_exit_stage": str(
                self.capital_profile.get("scap_exit_stage", "E0") or "E0"
            ).upper(),
            "scap_loss_stop": float(
                self.capital_profile.get("scap_loss_stop", -0.12)
            ),
            "risk_level": str(safety_row.get("risk_level", "normal")),
            "raw_risk_level": str(safety_row.get("raw_risk_level", "normal")),
            "trigger_streak_days": int(pd.to_numeric(pd.Series([safety_row.get("trigger_streak_days", 0)]), errors="coerce").fillna(0).iloc[0]),
            "exposure_cap": float(pd.to_numeric(pd.Series([safety_row.get("exposure_cap", 1.0)]), errors="coerce").fillna(1.0).iloc[0]),
            "benchmark_drawdown_5d": pd.to_numeric(pd.Series([safety_row.get("benchmark_drawdown_5d")]), errors="coerce").iloc[0],
            "benchmark_drawdown_20d": pd.to_numeric(pd.Series([safety_row.get("benchmark_drawdown_20d")]), errors="coerce").iloc[0],
            "benchmark_return_5d": pd.to_numeric(pd.Series([safety_row.get("benchmark_return_5d")]), errors="coerce").iloc[0],
            "benchmark_return_20d": pd.to_numeric(pd.Series([safety_row.get("benchmark_return_20d")]), errors="coerce").iloc[0],
            "benchmark_underwater_from_peak": pd.to_numeric(pd.Series([safety_row.get("benchmark_underwater_from_peak")]), errors="coerce").iloc[0],
            "market_liquidity_stress_ratio": float(pd.to_numeric(pd.Series([safety_row.get("market_liquidity_stress_ratio", 0.0)]), errors="coerce").fillna(0.0).iloc[0]),
            "trigger_source": str(safety_row.get("trigger_source", "normal")),
            "benchmark_nav": float(benchmark_nav),
            "performance_benchmark_id": str(
                benchmark_audit.get(
                    "benchmark_id",
                    f"top_liquidity_{self.performance_benchmark_top_n}_equal_weight_{self.performance_benchmark_rebalance}",
                )
            ),
            "performance_benchmark_member_count": int(
                pd.to_numeric(pd.Series([benchmark_audit.get("benchmark_member_count", 0)]), errors="coerce").fillna(0).iloc[0]
            ),
            "performance_benchmark_return_coverage": float(
                pd.to_numeric(pd.Series([benchmark_audit.get("benchmark_return_coverage", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
            ),
            "performance_benchmark_rebalanced": bool(benchmark_audit.get("benchmark_rebalanced", False)),
            "performance_benchmark_turnover": float(
                pd.to_numeric(pd.Series([benchmark_audit.get("benchmark_turnover", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
            ),
            "safety_benchmark_id": str(MARKET_REGIME_BENCHMARK_SYMBOL or ""),
            "regime_input_valid": bool(diagnostics.get("regime_input_valid", False)),
            "regime_input_status": str(diagnostics.get("regime_input_status", "unknown")),
            "regime_benchmark_symbol": str(diagnostics.get("regime_benchmark_symbol", MARKET_REGIME_BENCHMARK_SYMBOL or "")),
            "regime_benchmark_role": str(diagnostics.get("regime_benchmark_role", "safety_control_proxy")),
            "regime_benchmark_observed": bool(diagnostics.get("regime_benchmark_observed", False)),
            "regime_benchmark_lag_days": diagnostics.get("regime_benchmark_lag_days", pd.NA),
            "regime_breadth_score": diagnostics.get("regime_breadth_score", pd.NA),
            "regime_breadth_coverage": float(diagnostics.get("regime_breadth_coverage", 0.0) or 0.0),
            "regime_raw_label": str(diagnostics.get("regime_raw_label", "unknown")),
            "regime_confirmed_label": str(diagnostics.get("regime_confirmed_label", diagnostics.get("regime_name", "unknown"))),
            "regime_as_of_date": diagnostics.get("regime_as_of_date", pd.Timestamp(date)),
            "market_state_semantics_contract_version": str(diagnostics.get("market_state_semantics_contract_version", "")),
            "safety_market_state_active": bool(diagnostics.get("safety_market_state_active", False)),
            "safety_structural_state": str(diagnostics.get("safety_structural_state", safety_row.get("structural_regime_level", "unknown"))),
            "safety_market_state_authority": str(diagnostics.get("safety_market_state_authority", "disabled")),
            "optional_regime_overlay_enabled": bool(diagnostics.get("optional_regime_overlay_enabled", False)),
            "optional_regime_overlay_authorized": bool(diagnostics.get("optional_regime_overlay_authorized", False)),
            "optional_regime_overlay_state": str(diagnostics.get("optional_regime_overlay_state", "unknown")),
            "optional_regime_overlay_authority": str(diagnostics.get("optional_regime_overlay_authority", "diagnostics_only_no_trade_authority")),
            "performance_benchmark_authority": str(diagnostics.get("performance_benchmark_authority", "attribution_only_no_trade_authority")),
            "safety_benchmark_authority": str(diagnostics.get("safety_benchmark_authority", "safety_market_state_input")),
            "performance_benchmark_role": str(diagnostics.get("performance_benchmark_role", "performance_attribution")),
            "performance_benchmark_distinct_from_regime_proxy": bool(diagnostics.get("performance_benchmark_distinct_from_regime_proxy", True)),
            "account_net_value": float(account_net_value),
            "excess_net_value": float(excess_net_value),
            "structural_regime_level": str(safety_row.get("structural_regime_level", "bull")),
            "regime_exposure_budget": float(pd.to_numeric(pd.Series([safety_row.get("regime_exposure_budget", 1.0)]), errors="coerce").fillna(1.0).iloc[0]),
            "safety_exposure_cap": float(pd.to_numeric(pd.Series([safety_row.get("safety_exposure_cap", 1.0)]), errors="coerce").fillna(1.0).iloc[0]),
            "hard_freeze_active": bool(safety_row.get("hard_freeze_active", False)),
            "unresolved_safety_exposure": float(diagnostics.get("unresolved_safety_exposure", 0.0)),
            "target_exposure": float(
                factual_exposure_row.get(
                    "target_exposure",
                    diagnostics.get("target_exposure", 0.0),
                )
            ),
            "policy_exposure_target": float(factual_exposure_row.get("policy_exposure_target", diagnostics.get("policy_exposure_target", 0.0)) or 0.0),
            "policy_exposure_lower": float(factual_exposure_row.get("policy_exposure_lower", diagnostics.get("policy_exposure_lower", 0.0)) or 0.0),
            "pretrade_policy_lower_shortfall": max(
                float(factual_exposure_row.get("policy_exposure_lower", diagnostics.get("policy_exposure_lower", 0.0)) or 0.0)
                - float(factual_exposure_row.get("actual_exposure", diagnostics.get("actual_exposure", 0.0)) or 0.0),
                0.0,
            ),
            "post_mandatory_exposure": float(factual_exposure_row.get("post_mandatory_exposure", diagnostics.get("post_mandatory_exposure", 0.0)) or 0.0),
            "conditional_exposure_floor": float(factual_exposure_row.get("conditional_exposure_floor", diagnostics.get("conditional_exposure_floor", 0.0)) or 0.0),
            "actual_exposure": float(
                factual_exposure_row.get(
                    "actual_exposure",
                    diagnostics.get("actual_exposure", 0.0),
                )
            ),
            "base_exposure_by_regime": float(diagnostics.get("base_exposure_by_regime", 0.0)),
            "raw_safety_exposure_cap": float(diagnostics.get("raw_safety_exposure_cap", 0.0)),
            "effective_target_exposure_cap": float(diagnostics.get("effective_target_exposure_cap", 0.0)),
            "risk_exposure_ceiling": float(diagnostics.get("risk_exposure_ceiling", 0.0)),
            "desired_exposure_target": float(diagnostics.get("desired_exposure_target", 0.0)),
            "executable_exposure_target": float(diagnostics.get("executable_exposure_target", 0.0)),
            "optimizer_planned_exposure": float(
                factual_exposure_row.get(
                    "optimizer_planned_exposure",
                    diagnostics.get(
                        "optimizer_planned_exposure",
                        diagnostics.get("planned_exposure", 0.0),
                    ),
                )
            ),
            "signal_cash_drag": float(diagnostics.get("signal_cash_drag", 0.0)),
            "lot_feasibility_drag": float(diagnostics.get("lot_feasibility_drag", 0.0)),
            "risk_ceiling_drag": float(diagnostics.get("risk_ceiling_drag", 0.0)),
            "exposure_authorization_tier": str(diagnostics.get("exposure_authorization_tier", "")),
            "exposure_authorization_block_reasons": str(diagnostics.get("exposure_authorization_block_reasons", "")),
            "governance_control_mode": self.governance_control_mode,
            "reputation_control_enabled": bool(self._control_enabled("reputation")),
            "regime_control_enabled": bool(
                self.enable_market_regime_policy and self._control_enabled("regime")
            ),
            "cooldown_control_enabled": bool(self._control_enabled("cooldown")),
            "hard_stop_control_enabled": bool(self._control_enabled("hard_stop_exit")),
            "alpha_collapse_exit_enabled": bool(self.alpha_collapse_exit_enabled),
            "regime_overlay_mode": str(diagnostics.get("regime_overlay_mode", self.regime_overlay_mode)),
            "regime_overlay_capped": bool(diagnostics.get("regime_overlay_capped", False)),
            "authorization_expected_edge_10d_mean": _safe_float(diagnostics.get("authorization_expected_edge_10d_mean"), default=0.0),
            "authorization_p_win_10d_mean": _safe_float(diagnostics.get("authorization_p_win_10d_mean"), default=0.0),
            "constraint_cash_reserve": float(diagnostics.get("constraint_cash_reserve", 0.0)),
            "minimum_required_holding_count": int(
                factual_exposure_row.get("minimum_required_holding_count", 0)
            ),
            "soft_target_holding_count": int(
                factual_exposure_row.get("soft_target_holding_count", 0)
            ),
            "maximum_allowed_holding_count": int(
                factual_exposure_row.get("maximum_allowed_holding_count", 0)
            ),
            "user_hard_position_cap": factual_exposure_row.get("user_hard_position_cap", pd.NA),
            "economic_position_cap": int(factual_exposure_row.get("economic_position_cap", 0) or 0),
            "lot_cash_position_cap": int(factual_exposure_row.get("lot_cash_position_cap", 0) or 0),
            "cost_feasible_position_cap": int(factual_exposure_row.get("cost_feasible_position_cap", 0) or 0),
            "risk_feasible_position_cap": int(factual_exposure_row.get("risk_feasible_position_cap", 0) or 0),
            "grandfathered_excess_names": int(factual_exposure_row.get("grandfathered_excess_names", 0) or 0),
            "search_position_cap": int(factual_exposure_row.get("search_position_cap", 0) or 0),
            "effective_position_cap": int(factual_exposure_row.get("effective_position_cap", 0) or 0),
            "portfolio_normal_rebalance_frequency": str(self.portfolio_normal_rebalance_frequency),
            "portfolio_normal_rebalance_anchor": str(
                self.capital_profile.get("portfolio_normal_rebalance_anchor", "") or ""
            ),
            "monthly_plan_execution_window_sessions": int(
                self.capital_profile.get("scap_monthly_plan_execution_window_sessions", 0) or 0
            ),
            "max_daily_new_names": int(
                self.capital_profile.get("scap_max_daily_new_names", 0) or 0
            ),
            "max_daily_new_exposure_ratio": float(
                self.capital_profile.get("scap_max_daily_new_exposure_ratio", 0.0) or 0.0
            ),
            "sizing_reference_positions": int(factual_exposure_row.get("sizing_reference_positions", 0) or 0),
            "selected_position_count": int(factual_exposure_row.get("selected_position_count", 0) or 0),
            "optimizer_planned_holding_count": int(factual_exposure_row.get("optimizer_planned_holding_count", factual_exposure_row.get("planned_holding_count", 0)) or 0),
            "planned_holding_count": int(factual_exposure_row.get("planned_holding_count", 0) or 0),
            "conditional_holding_floor": int(factual_exposure_row.get("conditional_holding_floor", 0) or 0),
            "post_mandatory_holding_count": int(factual_exposure_row.get("post_mandatory_holding_count", 0) or 0),
            "profit_coverage_ratio": float(factual_exposure_row.get("profit_coverage_ratio", 0.0) or 0.0),
            "profit_coverage_probability_lower": float(factual_exposure_row.get("profit_coverage_probability_lower", 0.0) or 0.0),
            "coverage_evidence_name_count": int(factual_exposure_row.get("coverage_evidence_name_count", 0) or 0),
            "coverage_state": str(factual_exposure_row.get("coverage_state", "not_applicable") or "not_applicable"),
            "coverage_mode": str(factual_exposure_row.get("coverage_mode", "diagnostic_shadow") or "diagnostic_shadow"),
            "coverage_penalty_amount": float(factual_exposure_row.get("coverage_penalty_amount", 0.0) or 0.0),
            "hold_baseline_objective_amount": float(factual_exposure_row.get("hold_baseline_objective_amount", 0.0) or 0.0),
            "incremental_expected_wealth_amount": float(factual_exposure_row.get("incremental_expected_wealth_amount", 0.0) or 0.0),
            "incremental_cvar_amount": float(factual_exposure_row.get("incremental_cvar_amount", 0.0) or 0.0),
            "model_uncertainty_amount": float(factual_exposure_row.get("model_uncertainty_amount", 0.0) or 0.0),
            "scenario_risk_penalty_amount": float(factual_exposure_row.get("scenario_risk_penalty_amount", 0.0) or 0.0),
            "scenario_evidence_state": str(factual_exposure_row.get("scenario_evidence_state", "not_applicable") or "not_applicable"),
            "scenario_contract_id": str(factual_exposure_row.get("scenario_contract_id", "") or ""),
            "scenario_risk_measure": str(factual_exposure_row.get("scenario_risk_measure", "correlated_tail_loss_proxy") or "correlated_tail_loss_proxy"),
            "joint_scenario_count": int(factual_exposure_row.get("joint_scenario_count", 0) or 0),
            "regime_es_budget_multiplier": float(factual_exposure_row.get("regime_es_budget_multiplier", 1.0) or 1.0),
            "best_rejected_proposal_ids": factual_exposure_row.get("best_rejected_proposal_ids", ()),
            "best_rejected_objective_amount": float(factual_exposure_row.get("best_rejected_objective_amount", 0.0) or 0.0),
            "best_rejected_expected_wealth_amount": float(factual_exposure_row.get("best_rejected_expected_wealth_amount", 0.0) or 0.0),
            "best_rejected_cvar_amount": float(factual_exposure_row.get("best_rejected_cvar_amount", 0.0) or 0.0),
            "best_rejected_model_uncertainty_amount": float(factual_exposure_row.get("best_rejected_model_uncertainty_amount", 0.0) or 0.0),
            "expected_positive_pnl_amount": float(factual_exposure_row.get("expected_positive_pnl_amount", 0.0) or 0.0),
            "expected_loss_pnl_amount": float(factual_exposure_row.get("expected_loss_pnl_amount", 0.0) or 0.0),
            "lifecycle_cost_amount": float(factual_exposure_row.get("lifecycle_cost_amount", 0.0) or 0.0),
            "expected_log_growth": float(factual_exposure_row.get("expected_log_growth", 0.0) or 0.0),
            "minimum_selected_marginal_utility_amount": float(factual_exposure_row.get("minimum_selected_marginal_utility_amount", 0.0) or 0.0),
            "maximum_rejected_marginal_utility_amount": float(factual_exposure_row.get("maximum_rejected_marginal_utility_amount", 0.0) or 0.0),
            "capacity_spendable_cash": float(factual_exposure_row.get("capacity_spendable_cash", 0.0) or 0.0),
            "capacity_risk_room_amount": float(factual_exposure_row.get("capacity_risk_room_amount", 0.0) or 0.0),
            "capacity_minimum_economic_order_amount": float(factual_exposure_row.get("capacity_minimum_economic_order_amount", 0.0) or 0.0),
            "capacity_median_one_lot_amount": float(factual_exposure_row.get("capacity_median_one_lot_amount", 0.0) or 0.0),
            "target_holding_count": int(
                factual_exposure_row.get("target_holding_count", 0)
            ),
            "holding_shortfall_count": int(
                factual_exposure_row.get("holding_shortfall_count", 0)
            ),
            "idle_cash": float(
                factual_exposure_row.get("idle_cash", exposure.get("cash", 0.0))
            ),
            "idle_cash_ratio": float(
                factual_exposure_row.get(
                    "idle_cash_ratio",
                    float(exposure.get("cash", 0.0))
                    / max(float(exposure.get("nominal_nav", self.initial_cash)), 1e-12),
                )
            ),
            "defensive_eligible_count": int(
                factual_exposure_row.get("defensive_eligible_count", 0)
            ),
            "scap_v31_positive_c_fallback_count": int(
                factual_exposure_row.get(
                    "scap_v31_positive_c_fallback_count", 0
                )
            ),
            "scap_v31_all_d_streak": int(
                factual_exposure_row.get("scap_v31_all_d_streak", 0)
            ),
            "scap_v31_normal_cash_zero_proposal_streak": int(
                factual_exposure_row.get(
                    "scap_v31_normal_cash_zero_proposal_streak", 0
                )
            ),
            "scap_v31_position_recovery_alert": str(
                factual_exposure_row.get(
                    "scap_v31_position_recovery_alert", "none"
                )
            ),
            "planned_safety_sell_weight": float(diagnostics.get("planned_safety_sell_weight", 0.0)),
            "normal_turnover_weight": float(diagnostics.get("normal_turnover_weight", 0.0)),
            "total_target_drift": float(diagnostics.get("total_target_drift", 0.0)),
            "candidate_count": int(len(candidates)),
            "strategy_logic_version": self.strategy_logic_version,
            "entry_confirmed_count": int(diagnostics.get("qualified_entry_count", 0)),
            "entry_block_summary": entry_block_summary,
            "orderflow_candidate_score_mean": _safe_numeric_mean(candidates.get("orderflow_candidate_score")),
            "reversal_entry_score_mean": _safe_numeric_mean(candidates.get("reversal_entry_score")),
            "breakout_gate_score_mean": _safe_numeric_mean(candidates.get("breakout_gate_score")),
            "trend_hold_score_mean": _safe_numeric_mean(candidates.get("trend_hold_score")),
            "module_candidate_score_mean": _safe_numeric_mean(candidates.get("module_candidate_score")),
            "module_entry_score_mean": _safe_numeric_mean(candidates.get("module_entry_score")),
            "module_hold_score_mean": _safe_numeric_mean(candidates.get("module_hold_score")),
            "entry_alpha_score_mean": _safe_numeric_mean(candidates.get("entry_alpha_score")),
            "entry_timing_score_mean": _safe_numeric_mean(candidates.get("entry_timing_score")),
            "entry_liquidity_score_mean": _safe_numeric_mean(candidates.get("entry_liquidity_score")),
            "entry_matrix_score_mean": _safe_numeric_mean(candidates.get("entry_matrix_score")),
            "cabinet_strict_entry_score_mean": _safe_numeric_mean(candidates.get("cabinet_strict_entry_score")),
            "cabinet_proxy_entry_score_mean": _safe_numeric_mean(candidates.get("cabinet_proxy_entry_score")),
            "cabinet_timing_score_mean": _safe_numeric_mean(candidates.get("cabinet_timing_score")),
            "cabinet_liquidity_health_score_mean": _safe_numeric_mean(candidates.get("cabinet_liquidity_health_score")),
            "cabinet_risk_safety_score_mean": _safe_numeric_mean(candidates.get("cabinet_risk_safety_score")),
            "cabinet_hold_support_score_mean": _safe_numeric_mean(candidates.get("cabinet_hold_support_score")),
            "alpha_quality_score_mean": _safe_numeric_mean(candidates.get("alpha_quality_score")),
            "surge_capture_score_mean": _safe_numeric_mean(candidates.get("surge_capture_score")),
            "follow_through_score_mean": _safe_numeric_mean(candidates.get("follow_through_score")),
            "exhaustion_score_mean": _safe_numeric_mean(candidates.get("exhaustion_score")),
            "entry_success_probability_mean": _safe_numeric_mean(candidates.get("entry_success_probability")),
            "empirical_distribution_score_mean": _safe_numeric_mean(candidates.get("empirical_distribution_score")),
            "final_entry_score_mean": _safe_numeric_mean(candidates.get("final_entry_score")),
            "tail_risk_proxy_mean": _safe_numeric_mean(candidates.get("tail_risk_proxy")),
            "trend_direction_score_mean": _safe_numeric_mean(candidates.get("trend_direction_score")),
            "peak_decay_score_mean": _safe_numeric_mean(candidates.get("peak_decay_score")),
            "profit_protection_pressure_mean": _safe_numeric_mean(candidates.get("profit_protection_pressure")),
            "future_loss_risk_score_mean": _safe_numeric_mean(candidates.get("future_loss_risk_score")),
            "downtrend_decay_score_mean": _safe_numeric_mean(candidates.get("downtrend_decay_score")),
            "post_entry_failure_score_mean": _safe_numeric_mean(candidates.get("post_entry_failure_score")),
            "orderflow_candidate_pass_count": int(candidates.get("orderflow_candidate_pass", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "reversal_confirm_pass_count": int(candidates.get("reversal_confirm_pass", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "breakout_gate_pass_count": int(candidates.get("breakout_gate_pass", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "surge_candidate_count": int(candidates.get("surge_buy_flag", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "strong_starter_count": int(candidates.get("entry_size_tier", pd.Series("", index=candidates.index)).astype(str).eq("starter_strong").sum()),
            "starter_2_lot_count": int(candidates.get("entry_size_tier", pd.Series("", index=candidates.index)).astype(str).eq("starter_2_lot").sum()),
            "diversify_1_lot_count": int(candidates.get("entry_size_tier", pd.Series("", index=candidates.index)).astype(str).eq("diversify_1_lot").sum()),
            "exhaustion_block_count": int(pd.to_numeric(candidates.get("exhaustion_score", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0).ge(float(GOVERNANCE_EXHAUSTION_BUY_MAX)).sum()),
            "downtrend_decay_count": int(pd.to_numeric(candidates.get("downtrend_decay_score", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0).ge(float(GOVERNANCE_DOWNTREND_DECAY_ADD_BLOCK)).sum()),
            "protecting_profit_count": int(candidates.get("position_state", pd.Series("", index=candidates.index)).astype(str).str.lower().eq("protecting_profit").sum()),
            "buy_sell_conflict_cooldown_days": int(GOVERNANCE_BUY_SELL_CONFLICT_COOLDOWN_DAYS),
            "exposure_gap": float(diagnostics.get("exposure_gap", 0.0)),
            "catchup_allowed": bool(diagnostics.get("catchup_allowed", False)),
            "catchup_buy_budget": float(diagnostics.get("catchup_buy_budget", 0.0)),
            "catchup_block_reason": str(diagnostics.get("catchup_block_reason", "")),
            "catchup_tier": str(diagnostics.get("catchup_tier", "none")),
            "accuracy_multiplier": _safe_float(diagnostics.get("accuracy_multiplier"), default=0.0),
            "trailing_buy_accuracy_5d": _safe_float(diagnostics.get("trailing_buy_accuracy_5d"), default=float("nan")),
            "trailing_sell_accuracy_5d": _safe_float(trailing_sell_accuracy_5d, default=float("nan")),
            "closed_trade_count": int(trade_summary.get("realized_trade_count", 0) or 0),
            "closed_trade_win_rate": _safe_float(trade_summary.get("closed_trade_win_rate"), default=float("nan")),
            "realized_pnl": _safe_float(trade_summary.get("realized_pnl"), default=0.0),
            "gross_profit": _safe_float(trade_summary.get("gross_profit"), default=0.0),
            "gross_loss": _safe_float(trade_summary.get("gross_loss"), default=0.0),
            "avg_win": _safe_float(trade_summary.get("avg_win"), default=float("nan")),
            "avg_loss": _safe_float(trade_summary.get("avg_loss"), default=float("nan")),
            "payoff_ratio": _safe_float(trade_summary.get("payoff_ratio"), default=float("nan")),
            "profit_factor": _safe_float(trade_summary.get("profit_factor"), default=float("nan")),
            **_control_avoided_loss_summary(
                pd.DataFrame(self.execution_rows),
                self.features,
                as_of=pd.Timestamp(date),
            ),
            "best_replacement_edge_10d": _safe_float(diagnostics.get("best_replacement_edge_10d"), default=0.0),
            "replacement_opportunity_sell_count": int(diagnostics.get("replacement_opportunity_sell_count", 0)),
            "profit_giveback_observation_count": int(diagnostics.get("profit_giveback_observation_count", 0)),
            "post_entry_failure_exit_count": int(diagnostics.get("post_entry_failure_exit_count", 0)),
            "trend_break_observation_count": int(diagnostics.get("trend_break_observation_count", 0)),
            "volume_distribution_observation_count": int(diagnostics.get("volume_distribution_observation_count", 0)),
            "covariance_risk_model_used": bool(diagnostics.get("covariance_risk_model_used", False)),
            "portfolio_covariance_volatility": _safe_float(diagnostics.get("portfolio_covariance_volatility"), default=0.0),
            "max_risk_contribution": _safe_float(diagnostics.get("max_risk_contribution"), default=0.0),
            "risk_contribution_gate_pass": bool(diagnostics.get("risk_contribution_gate_pass", True)),
            "risk_contribution_exposure_scale": _safe_float(diagnostics.get("risk_contribution_exposure_scale"), default=1.0),
            "risk_symbol_count": int(diagnostics.get("risk_symbol_count", 0)),
            "risk_contribution_block_reason": str(diagnostics.get("risk_contribution_block_reason", "")),
            "top5_risk_contribution_sum": _safe_float(diagnostics.get("top5_risk_contribution_sum"), default=0.0),
            "top20pct_risk_contribution_sum": _safe_float(diagnostics.get("top20pct_risk_contribution_sum"), default=0.0),
            "risk_effective_n": _safe_float(diagnostics.get("risk_effective_n"), default=0.0),
            "risk_effective_n_ratio": _safe_float(diagnostics.get("risk_effective_n_ratio"), default=0.0),
            "risk_contribution_hhi": _safe_float(diagnostics.get("risk_contribution_hhi"), default=0.0),
            "risk_new_buy_block": bool(diagnostics.get("risk_new_buy_block", False)),
            "risk_catchup_block": bool(diagnostics.get("risk_catchup_block", False)),
            "risk_new_buy_block_applied": bool(diagnostics.get("risk_new_buy_block_applied", False)),
            "risk_catchup_block_applied": bool(diagnostics.get("risk_catchup_block_applied", False)),
            "risk_blocked_new_buy_weight": _safe_float(diagnostics.get("risk_blocked_new_buy_weight"), default=0.0),
            "avg_pairwise_correlation": _safe_float(diagnostics.get("avg_pairwise_correlation"), default=0.0),
            "covariance_condition_number": _safe_float(diagnostics.get("covariance_condition_number"), default=0.0),
            "order_count": int(len(orders)) if orders is not None else 0,
            "order_reason_summary": order_reason_summary,
            "pending_order_count": int(len(pending_preview)),
            "retail_order_count": int(diagnostics.get("retail_order_count", 0)),
            "retail_upgraded_to_one_lot_count": int(diagnostics.get("retail_upgraded_to_one_lot_count", 0)),
            "retail_blocked_count": int(diagnostics.get("retail_blocked_count", 0)),
            "retail_lot_cash_insufficient_count": int(diagnostics.get("retail_lot_cash_insufficient_count", 0)),
            "retail_state_block_count": int(diagnostics.get("retail_state_block_count", 0)),
            "zero_lot_order_count": int(diagnostics.get("zero_lot_order_count", 0)),
            "zero_lot_buy_order_count": int(diagnostics.get("zero_lot_buy_order_count", 0)),
            "zero_lot_sell_order_count": int(diagnostics.get("zero_lot_sell_order_count", 0)),
            "candidate_preview": candidate_preview,
            "confirmed_preview": confirmed_preview,
            "order_preview": order_preview,
            "pending_preview": pending_preview,
            "factor_weights": factor_weights,
            "module_weights": module_weights,
            "holding_price_paths": holding_price_paths,
            "holding_lifecycle_preview": lifecycle_preview,
            "lifecycle_alert_count": lifecycle_alert_count,
            "regime": getattr(regime_params, "regime_name", "default") if regime_params is not None else "default",
            "top_n": int(
                factual_exposure_row.get(
                    "effective_position_cap",
                    self._user_hard_position_cap
                    or (
                        getattr(regime_params, "max_positions", GOVERNANCE_DEFAULT_TOP_N)
                        if regime_params is not None
                        else GOVERNANCE_DEFAULT_TOP_N
                    ),
                )
            ),
            "turnover_budget": float(turnover_budget),
        }

    def _factor_weight_preview(self, *, date, proposals: pd.DataFrame) -> list[dict]:
        weights = (
            self.reputation.weights()
            if self.enable_reputation
            else {model_name: 1.0 for model_name in self.alpha_models}
        )
        reputation_state = self.reputation.state.set_index("model_name", drop=False) if self.enable_reputation else pd.DataFrame()
        if proposals is not None and not proposals.empty and "model_name" in proposals.columns:
            contribution = (
                proposals.assign(
                    predicted_return_5d=pd.to_numeric(proposals.get("predicted_return_5d"), errors="coerce"),
                    prediction_std=pd.to_numeric(proposals.get("prediction_std"), errors="coerce"),
                )
                .groupby("model_name", dropna=False)
                .agg(
                    avg_predicted_return_5d=("predicted_return_5d", "mean"),
                    avg_prediction_std=("prediction_std", "mean"),
                    proposal_count=("model_name", "size"),
                )
            )
        else:
            contribution = pd.DataFrame()

        rows = []
        if str(self.selection_weight_mode).lower() == "factor_judged":
            weights = {
                model_name: float(GOVERNANCE_FACTOR_JUDGED_ALPHA_WEIGHTS.get(model_name, 0.0))
                for model_name in self.alpha_models
            }
        total_weight = max(sum(float(value) for value in weights.values()), 1e-12)
        for model_name in self.alpha_models:
            weight = float(weights.get(model_name, 1.0))
            previous = float(self._last_factor_weights.get(model_name, weight))
            stats = contribution.loc[model_name] if model_name in contribution.index else {}
            rep = reputation_state.loc[model_name] if not reputation_state.empty and model_name in reputation_state.index else {}
            module = self.factor_runtime_context.module_map.get(model_name, factor_module(model_name))
            avg_exposure_ema = float(rep.get("avg_exposure_ema", 0.0)) if len(reputation_state) else 0.0
            activity_ema = float(rep.get("activity_ema", 0.0)) if len(reputation_state) else 0.0
            zero_trade_warning = bool(weight > 1.0 and avg_exposure_ema < 0.01)
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "model_name": str(model_name),
                    "factor_module": module,
                    "factor_role": _factor_primary_role(
                        model_name,
                        module,
                        configured_roles=self.factor_runtime_context.role_map.get(model_name, ()),
                    ),
                    "weight": weight,
                    "weight_share": weight / total_weight,
                    "weight_delta": weight - previous,
                    "avg_predicted_return_5d": float(stats.get("avg_predicted_return_5d", 0.0)) if len(contribution) else 0.0,
                    "avg_prediction_std": float(stats.get("avg_prediction_std", 0.0)) if len(contribution) else 0.0,
                    "proposal_count": int(stats.get("proposal_count", 0)) if len(contribution) else 0,
                    "activity_ema": activity_ema,
                    "coverage_ema": float(rep.get("coverage_ema", 0.0)) if len(reputation_state) else 0.0,
                    "avg_exposure_ema": avg_exposure_ema,
                    "zero_exposure_penalty": float(rep.get("zero_exposure_penalty", 1.0)) if len(reputation_state) else 1.0,
                    "coverage_penalty": float(rep.get("coverage_penalty", 1.0)) if len(reputation_state) else 1.0,
                    "zero_trade_factor_warning": zero_trade_warning,
                    "weight_explanation": _factor_weight_explanation(
                        activity_ema=activity_ema,
                        avg_exposure_ema=avg_exposure_ema,
                        zero_trade_warning=zero_trade_warning,
                    ),
                }
            )
        self._last_factor_weights = {row["model_name"]: float(row["weight"]) for row in rows}
        self.factor_weight_rows.extend(rows)
        rows.sort(key=lambda item: (abs(float(item["weight_delta"])), float(item["weight"])), reverse=True)
        return rows

    def _proposal_reputation_weights(self) -> dict[str, float]:
        if not self._control_enabled("reputation"):
            return {model_name: 1.0 for model_name in self.alpha_models}
        if str(self.selection_weight_mode).lower() in {"role_balanced", "reputation_auxiliary", "no_reputation_selection"}:
            return {model_name: 1.0 for model_name in self.alpha_models}
        return self.reputation.weights()

    def _apply_optional_exit_controls(self, candidates: pd.DataFrame) -> pd.DataFrame:
        if candidates is None or candidates.empty:
            return candidates
        data = candidates.copy()
        alpha_exit = data.get("alpha_collapse_exit", pd.Series(False, index=data.index)).fillna(False).astype(bool)
        data["paper_alpha_collapse_exit"] = alpha_exit
        if not self.alpha_collapse_exit_enabled:
            data["alpha_collapse_exit"] = False
        return data

    def _control_enabled(self, control_name: str) -> bool:
        mode = str(self.governance_control_mode or "normal").lower()
        control = str(control_name or "").lower()
        if mode == "normal":
            return True
        if mode == "factor_only":
            return control not in {
                "reputation",
                "regime",
                "regime_overlay",
                "cooldown",
                "profit_giveback_exit",
                "signal_failure_exit",
                "stale_exit",
                "post_entry_failure_exit",
                "hard_stop_exit",
            }
        if mode == "safe_factor_only":
            return control not in {
                "reputation",
                "regime",
                "regime_overlay",
                "cooldown",
                "profit_giveback_exit",
                "signal_failure_exit",
                "stale_exit",
                "post_entry_failure_exit",
            }
        if mode == "paper_controls":
            return control not in {
                "reputation",
                "regime",
                "regime_overlay",
                "cooldown",
                "profit_giveback_exit",
                "signal_failure_exit",
                "stale_exit",
                "post_entry_failure_exit",
                "hard_stop_exit",
            }
        if mode in {"aggressive_profit", "aggressive_lean"}:
            exit_stage = str(self.capital_profile.get("scap_exit_stage", "E0") or "E0").strip().upper()
            return scap_control_enabled(exit_stage=exit_stage, control_name=control)
        return True

    def _holding_price_paths(self, *, date) -> list[dict]:
        if not getattr(self, "_last_position_mark_rows", None):
            return []
        ranked = sorted(
            self._last_position_mark_rows,
            key=lambda row: float(row.get("market_value", 0.0) or 0.0),
            reverse=True,
        )
        symbols = [str(row.get("symbol")) for row in ranked[:6] if str(row.get("symbol", "")).strip()]
        if not symbols:
            return []
        end_date = pd.Timestamp(date)
        start_date = end_date - pd.Timedelta(days=270)
        paths = []
        lifecycle_by_symbol = {
            str(row.get("symbol", "")): row
            for row in getattr(self, "_last_position_mark_rows", []) or []
        }
        for symbol in symbols:
            history = self._close_history(symbol)
            if history.empty:
                continue
            group = history[history["date"].between(start_date, end_date)].tail(180).copy()
            close = pd.to_numeric(group["close"], errors="coerce").dropna()
            if close.empty:
                continue
            lifecycle = lifecycle_by_symbol.get(str(symbol), {})
            entry_date = pd.to_datetime(lifecycle.get("entry_date"), errors="coerce")
            entry_price = _safe_float(lifecycle.get("entry_price"), default=0.0)
            if entry_price <= 0.0:
                entry_price = _safe_float(lifecycle.get("price"), default=0.0)
            normalization_price = entry_price if entry_price > 0.0 else float(close.iloc[0])
            if normalization_price <= 0.0:
                continue
            latest_price = _safe_float(lifecycle.get("price"), default=0.0)
            entry_index = None
            points = [
                {
                    "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                    "value": float(row["close"]) / normalization_price,
                    "entry_value": float(row["close"]) / entry_price if entry_price > 0.0 else None,
                }
                for _, row in group.iterrows()
                if pd.notna(row["close"])
            ]
            if pd.notna(entry_date):
                entry_date_ts = pd.Timestamp(entry_date)
                first_visible_date = pd.Timestamp(points[0]["date"]) if points else pd.NaT
                if pd.notna(first_visible_date) and entry_date_ts >= first_visible_date:
                    for idx, point in enumerate(points):
                        if pd.Timestamp(point["date"]) >= entry_date_ts:
                            entry_index = idx
                            break
            if len(points) >= 2:
                paths.append(
                    {
                        "symbol": str(symbol),
                        "entry_date": entry_date.strftime("%Y-%m-%d") if pd.notna(entry_date) else "",
                        "entry_price": float(entry_price) if entry_price > 0.0 else None,
                        "latest_price": float(latest_price) if latest_price > 0.0 else None,
                        "unrealized_return": _safe_float(lifecycle.get("unrealized_return"), default=float("nan")),
                        "entry_index": entry_index,
                        "entry_visible": entry_index is not None,
                        "points": points,
                    }
                )
        return paths

    def _holding_lifecycle_preview(self) -> list[dict]:
        rows = []
        latest_state_by_symbol = {}
        latest_date = ""
        if self.position_state_rows:
            latest_date = max(pd.Timestamp(row.get("date")) for row in self.position_state_rows if row.get("date") is not None)
            latest_state_by_symbol = {
                str(row.get("symbol", "")): row
                for row in self.position_state_rows
                if pd.Timestamp(row.get("date")) == latest_date
            }
        for row in getattr(self, "_last_position_mark_rows", []) or []:
            state = latest_state_by_symbol.get(str(row.get("symbol", "")), {})
            rows.append(
                {
                    "symbol": str(row.get("symbol", "")),
                    "snapshot_date": str(row.get("date", latest_date))[:10],
                    "market_value": _safe_float(row.get("market_value"), default=0.0),
                    "entry_date": str(row.get("entry_date", ""))[:10],
                    "entry_price": _safe_float(row.get("entry_price"), default=0.0),
                    "unrealized_return": _safe_float(row.get("unrealized_return"), default=0.0),
                    "mfe": _safe_float(row.get("mfe"), default=0.0),
                    "mae": _safe_float(row.get("mae"), default=0.0),
                    "giveback_from_peak": _safe_float(row.get("giveback_from_peak"), default=0.0),
                    "giveback_armed": bool(
                        _safe_float(row.get("mfe"), default=0.0)
                        >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_1)
                    ),
                    "trend_direction_score": _safe_float(row.get("trend_direction_score"), default=0.0),
                    "peak_decay_score": _safe_float(row.get("peak_decay_score"), default=0.0),
                    "profit_protection_pressure": _safe_float(row.get("profit_protection_pressure"), default=0.0),
                    "dynamic_giveback_limit": _safe_float(row.get("dynamic_giveback_limit"), default=0.0),
                    "future_loss_risk_score": _safe_float(row.get("future_loss_risk_score"), default=0.0),
                    "profit_giveback_flag": bool(row.get("profit_giveback_flag", False)),
                    "post_entry_failure_flag": bool(row.get("post_entry_failure_flag", False)),
                    "post_entry_failure_score": _safe_float(
                        state.get("post_entry_failure_score"), default=0.0
                    ),
                    "post_entry_failure_threshold": _safe_float(
                        state.get("post_entry_failure_threshold"),
                        default=GOVERNANCE_POST_ENTRY_FAILURE_EXIT_SCORE,
                    ),
                    "position_state": state.get("position_state", ""),
                    "add_allowed": bool(state.get("add_allowed", False)),
                    "add_block_reason": state.get("add_block_reason", ""),
                    "position_exit_reason": state.get("position_exit_reason", ""),
                    "paper_exit_reason": state.get("paper_exit_reason", ""),
                    "paper_exit_state": bool(state.get("paper_exit_state", False)),
                    "cooldown_until": state.get("cooldown_until", ""),
                }
            )
        return sorted(rows, key=lambda item: float(item.get("market_value", 0.0)), reverse=True)[:12]

    def _benchmark_nav_asof(self, date) -> float:
        raw = self._raw_benchmark_nav_asof(date)
        base = float(getattr(self, "_run_benchmark_base_nav", 1.0) or 1.0)
        return raw / max(base, 1e-12)

    def _raw_benchmark_nav_asof(self, date) -> float:
        lookup = getattr(self, "_benchmark_nav_by_date", {}) or {}
        key = pd.Timestamp(date).normalize()
        return float(lookup.get(key, 1.0))

    def _build_benchmark_nav_lookup(self) -> dict:
        self._performance_benchmark_frame = build_top_pool_benchmark_series(
            self._performance_benchmark_source(),
            top_n=self.performance_benchmark_top_n,
            rebalance=self.performance_benchmark_rebalance,
        )
        if not self._performance_benchmark_frame.empty:
            data = self._performance_benchmark_frame.copy()
            data["date_norm"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
            data["benchmark_nav"] = pd.to_numeric(data["benchmark_net_value"], errors="coerce")
            data = data.dropna(subset=["date_norm", "benchmark_nav"])
            if not data.empty:
                return data.drop_duplicates("date_norm", keep="last").set_index("date_norm")["benchmark_nav"].astype(float).to_dict()

        symbol = str(MARKET_REGIME_BENCHMARK_SYMBOL or "")
        if not symbol:
            return {}
        close_col = "close_nominal" if "close_nominal" in self.features.columns else "close"
        data = self.features.loc[
            self.features["symbol"].astype(str).eq(symbol),
            ["date", close_col],
        ].copy()
        if data.empty:
            return {}
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data[close_col] = pd.to_numeric(data[close_col], errors="coerce")
        data = data.dropna(subset=["date", close_col]).sort_values("date")
        if data.empty:
            return {}
        first = float(data[close_col].iloc[0])
        if first <= 0.0:
            return {}
        data["benchmark_nav"] = data[close_col] / first
        data["date_norm"] = data["date"].dt.normalize()
        return data.drop_duplicates("date_norm", keep="last").set_index("date_norm")["benchmark_nav"].astype(float).to_dict()

    def _performance_benchmark_source(self) -> pd.DataFrame:
        source_frames = []
        for source in (self.features, self.audit_prices):
            if source is None or source.empty:
                continue
            close_col = "close_nominal" if "close_nominal" in source.columns else "close"
            columns = [column for column in (
                "date", "symbol", close_col, "amount", "amount_ma20", "instrument_type", "is_trading"
            ) if column in source.columns]
            if not {"date", "symbol", close_col}.issubset(columns):
                continue
            frame = source.loc[:, columns].copy()
            if close_col != "close_nominal":
                frame = frame.rename(columns={close_col: "close_nominal"})
            if "instrument_type" not in frame.columns:
                frame["instrument_type"] = "stock"
            if "is_trading" not in frame.columns:
                frame["is_trading"] = True
            source_frames.append(frame)
        if not source_frames:
            return pd.DataFrame()
        result = pd.concat(source_frames, ignore_index=True).drop_duplicates(["date", "symbol"], keep="first")
        # The ETF proxy remains a safety/regime input.  It must not become a
        # constituent of the independent stock-pool performance benchmark.
        return result.loc[
            ~result["symbol"].astype(str).eq(str(MARKET_REGIME_BENCHMARK_SYMBOL or ""))
        ].copy()

    def _update_lifecycle_on_buy(self, symbol: str, *, date, price: float, shares: float, current, signal=None) -> None:
        return update_lifecycle_on_buy_runtime(self, symbol, date=date, price=price, shares=shares, current=current, signal=signal)

    def _mark_lifecycle(self, symbol: str, *, date, price: float) -> dict:
        return mark_lifecycle_runtime(self, symbol, date=date, price=price)

    def _lifecycle_market_shape(self, *, symbol: str, date, entry_price: float, peak_price: float) -> dict:
        return lifecycle_market_shape_runtime(self, symbol=symbol, date=date, entry_price=entry_price, peak_price=peak_price)

    def _attach_position_lifecycle_signals(self, candidates: pd.DataFrame, *, date) -> pd.DataFrame:
        return attach_position_lifecycle_signals_runtime(self, candidates, date=date)

    def _apply_position_state_constraints(self, candidates: pd.DataFrame, *, date, exposure: dict) -> pd.DataFrame:
        return apply_position_state_constraints_runtime(self, candidates, date=date, exposure=exposure)

    def _apply_candidate_risk_penalty(
        self,
        candidates: pd.DataFrame,
        *,
        exposure: dict,
        score_column: str = "primary_score",
    ) -> pd.DataFrame:
        return apply_candidate_risk_penalty_runtime(
            self,
            candidates,
            exposure=exposure,
            score_column=score_column,
        )

    def _expire_position_cooldowns(self, date) -> None:
        return expire_position_cooldowns_runtime(self, date)

    def _max_add_layers(self) -> int:
        return max_add_layers_runtime(self)

    def _force_deploy_target_exposure(
        self,
        *,
        risk_level: str,
        structural_regime_level: str,
        safety_exposure_cap: float,
        liquidity_stress: float,
    ) -> float | None:
        if self.capital_usage_mode != GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY:
            return None
        if float(liquidity_stress) >= 0.35:
            return min(float(safety_exposure_cap), float(GOVERNANCE_FORCE_DEPLOY_TARGET_EXPOSURE_HIGH))
        risk = str(risk_level or "").lower()
        regime = str(structural_regime_level or "").lower()
        if risk in {"crisis", "high"}:
            target = float(GOVERNANCE_FORCE_DEPLOY_TARGET_EXPOSURE_HIGH)
        elif regime in {"weak", "bear"}:
            target = float(GOVERNANCE_FORCE_DEPLOY_TARGET_EXPOSURE_WEAK)
        else:
            target = float(self.capital_profile.get("force_deploy_target_exposure_normal", GOVERNANCE_FORCE_DEPLOY_TARGET_EXPOSURE_NORMAL) or GOVERNANCE_FORCE_DEPLOY_TARGET_EXPOSURE_NORMAL)
        return min(max(target, 0.0), float(safety_exposure_cap))

    def _augment_force_deploy_diversify_orders(
        self,
        *,
        orders: pd.DataFrame,
        candidates: pd.DataFrame,
        defensive_candidates: pd.DataFrame | None,
        decision_id: str,
        decision_date,
        current_weights: dict[str, float],
        nominal_nav: float,
        daily: pd.DataFrame,
        target_exposure: float,
    ) -> pd.DataFrame:
        if self.capital_usage_mode != GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY:
            return orders
        if candidates is None or candidates.empty or float(nominal_nav or 0.0) <= 0.0:
            return orders
        min_holdings = int(
            self.capital_profile.get("min_holdings", GOVERNANCE_FORCE_DEPLOY_MIN_HOLDINGS_20K)
            or GOVERNANCE_FORCE_DEPLOY_MIN_HOLDINGS_20K
        )
        max_positions = int(
            self._max_positions_override
            or self.capital_profile.get("max_positions", min_holdings)
            or min_holdings
        )
        existing_symbols = {str(symbol) for symbol, weight in current_weights.items() if float(weight) > 1e-12}
        buy_symbols: set[str] = set()
        sell_symbols: set[str] = set()
        if orders is not None and not orders.empty:
            sides = orders.get("side", pd.Series(dtype=object)).astype(str)
            buy_symbols = set(orders.loc[sides.eq("buy"), "symbol"].astype(str))
            sell_symbols = set(orders.loc[sides.eq("sell"), "symbol"].astype(str))
        planned_holding_count = len(existing_symbols | buy_symbols)
        shortfall = max(min(min_holdings, max_positions) - planned_holding_count, 0)
        if shortfall <= 0:
            return orders

        price_map = daily.set_index("symbol")["close_nominal"] if "symbol" in daily.columns else pd.Series(dtype=float)
        min_buffer = float(self.capital_profile.get("min_cash_buffer", 0.0) or 0.0)
        single_cap = float(self.capital_profile.get("retail_single_position_cap", 0.40) or 0.40)
        exposure_tolerance = float(self.capital_profile.get("retail_target_exposure_tolerance", 0.10) or 0.10)
        available_cash = max(float(self.cash) - min_buffer, 0.0)
        current_exposure = sum(float(value) for value in current_weights.values())
        planned_buy_weight = 0.0
        if orders is not None and not orders.empty:
            planned_buy_weight = float(
                pd.to_numeric(
                    orders.loc[orders.get("side", pd.Series(dtype=object)).astype(str).eq("buy"), "delta_weight"],
                    errors="coerce",
                )
                .fillna(0.0)
                .clip(lower=0.0)
                .sum()
            )
        exposure_room = max(float(target_exposure) + exposure_tolerance - current_exposure - planned_buy_weight, 0.0)
        if available_cash <= 0.0 or exposure_room <= 1e-12:
            return orders

        data = candidates.copy()
        data["symbol"] = data["symbol"].astype(str)
        confirmed = _state_machine_entry_mask(data)
        tier = data.get("entry_size_tier", pd.Series("", index=data.index)).astype(str).str.lower()
        state = data.get("position_state", pd.Series("", index=data.index)).astype(str).str.lower()
        locked_symbols = {str(symbol) for symbol in self.engine.pending_orders.locked_symbols()}
        data = data[
            confirmed
            & tier.isin(["basket_1_lot", "diversify_1_lot", "starter_1_lot", "starter_2_lot", "starter_strong"])
            & state.isin(["building", "strong_building", "holding", "watching"])
            & ~data["symbol"].isin(existing_symbols | buy_symbols | sell_symbols | locked_symbols)
        ].copy()
        supplemental = []
        used_cash = 0.0
        used_weight = 0.0
        stock_candidates = self._force_deploy_order_candidates(
            data,
            price_map=price_map,
            nominal_nav=nominal_nav,
            available_cash=available_cash,
            single_cap=single_cap,
            exposure_room=exposure_room,
        )
        for _, row in stock_candidates.iterrows():
            if len(supplemental) >= shortfall:
                break
            payload, one_lot_cash, one_lot_weight = self._force_deploy_order_payload(
                row=row,
                decision_id=decision_id,
                decision_date=decision_date,
                current_weights=current_weights,
                reason="force_deploy_diversify_buy",
                priority=ORDER_PRIORITIES.get("force_deploy_diversify_buy", ORDER_PRIORITIES.get("normal_buy", 5)),
            )
            if used_cash + one_lot_cash > available_cash + 1e-12 or used_weight + one_lot_weight > exposure_room + 1e-12:
                continue
            supplemental.append(payload)
            used_cash += one_lot_cash
            used_weight += one_lot_weight

        if len(supplemental) < shortfall:
            blocked_symbols = existing_symbols | buy_symbols | sell_symbols | locked_symbols | {str(row["symbol"]) for row in supplemental}
            defensive_order_candidates = self._force_deploy_defensive_order_candidates(
                defensive_candidates,
                price_map=price_map,
                nominal_nav=nominal_nav,
                available_cash=max(available_cash - used_cash, 0.0),
                single_cap=single_cap,
                exposure_room=max(exposure_room - used_weight, 0.0),
                blocked_symbols=blocked_symbols,
            )
            for _, row in defensive_order_candidates.iterrows():
                if len(supplemental) >= shortfall:
                    break
                payload, one_lot_cash, one_lot_weight = self._force_deploy_order_payload(
                    row=row,
                    decision_id=decision_id,
                    decision_date=decision_date,
                    current_weights=current_weights,
                    reason="force_deploy_defensive_buy",
                    priority=ORDER_PRIORITIES.get("force_deploy_defensive_buy", ORDER_PRIORITIES.get("normal_buy", 6)),
                )
                if used_cash + one_lot_cash > available_cash + 1e-12 or used_weight + one_lot_weight > exposure_room + 1e-12:
                    continue
                supplemental.append(payload)
                used_cash += one_lot_cash
                used_weight += one_lot_weight

        if not supplemental:
            return orders
        supplement_frame = pd.DataFrame(supplemental, columns=ORDER_COLUMNS)
        self.engine.ledgers.append("executable_order_plan", supplement_frame)
        if orders is None or orders.empty:
            return supplement_frame
        return pd.concat([orders, supplement_frame], ignore_index=True)

    def _force_deploy_order_candidates(
        self,
        data: pd.DataFrame,
        *,
        price_map: pd.Series,
        nominal_nav: float,
        available_cash: float,
        single_cap: float,
        exposure_room: float,
    ) -> pd.DataFrame:
        if data is None or data.empty:
            return pd.DataFrame()
        out = data.copy()
        out["_final_entry_score"] = pd.to_numeric(
            out.get("final_entry_score", out.get("entry_matrix_score", 0.0)),
            errors="coerce",
        ).fillna(0.0)
        out["_entry_matrix_score"] = pd.to_numeric(out.get("entry_matrix_score", 0.0), errors="coerce").fillna(0.0)
        out["_exhaustion_score"] = pd.to_numeric(out.get("exhaustion_score", 1.0), errors="coerce").fillna(1.0)
        out["_downtrend_decay_score"] = pd.to_numeric(out.get("downtrend_decay_score", 1.0), errors="coerce").fillna(1.0)
        out = self._attach_one_lot_order_costs(out, price_map=price_map, nominal_nav=nominal_nav)
        out = out[
            (out["_one_lot_cash_required"] > 0.0)
            & (out["_one_lot_cash_required"] <= available_cash)
            & (out["_one_lot_account_weight"] <= single_cap + 1e-12)
            & (out["_one_lot_account_weight"] <= exposure_room + 1e-12)
            & (out["_exhaustion_score"] < float(GOVERNANCE_EXHAUSTION_BUY_MAX))
            & (out["_downtrend_decay_score"] < float(GOVERNANCE_DOWNTREND_DECAY_ADD_BLOCK))
        ].copy()
        if out.empty:
            return out
        return out.sort_values(
            ["_final_entry_score", "_entry_matrix_score", "_one_lot_account_weight", "symbol"],
            ascending=[False, False, True, True],
        )

    def _force_deploy_defensive_order_candidates(
        self,
        defensive_candidates: pd.DataFrame | None,
        *,
        price_map: pd.Series,
        nominal_nav: float,
        available_cash: float,
        single_cap: float,
        exposure_room: float,
        blocked_symbols: set[str],
    ) -> pd.DataFrame:
        if defensive_candidates is None or defensive_candidates.empty:
            return pd.DataFrame()
        out = defensive_candidates.copy()
        out["symbol"] = out["symbol"].astype(str)
        out = out[~out["symbol"].isin(blocked_symbols)].copy()
        out["_final_entry_score"] = pd.to_numeric(out.get("defensive_score", 0.0), errors="coerce").fillna(0.0)
        out["_entry_matrix_score"] = out["_final_entry_score"]
        out = out[out["_final_entry_score"] >= 0.55].copy()
        if out.empty:
            return out
        out["position_state"] = out.get("defensive_state", "defensive_holding")
        out["entry_size_tier"] = "defensive_1_lot"
        out["planned_entry_lots"] = 1
        out["entry_matrix_score"] = out["_entry_matrix_score"]
        out["final_entry_score"] = out["_final_entry_score"]
        out["alpha_quality_score"] = out.get("defensive_trend_score", pd.NA)
        out["entry_timing_score"] = out.get("defensive_drawdown_resilience", pd.NA)
        out["entry_liquidity_score"] = out.get("defensive_liquidity_score", pd.NA)
        out["follow_through_score"] = out.get("defensive_low_vol_score", pd.NA)
        out["exhaustion_score"] = 0.0
        out["downtrend_decay_score"] = 0.0
        out["tail_risk_proxy"] = 1.0 - out["_final_entry_score"].clip(lower=0.0, upper=1.0)
        out = self._attach_one_lot_order_costs(out, price_map=price_map, nominal_nav=nominal_nav)
        out = out[
            (out["_one_lot_cash_required"] > 0.0)
            & (out["_one_lot_cash_required"] <= available_cash)
            & (out["_one_lot_account_weight"] <= single_cap + 1e-12)
            & (out["_one_lot_account_weight"] <= exposure_room + 1e-12)
        ].copy()
        if out.empty:
            return out
        return out.sort_values(
            ["_final_entry_score", "_one_lot_account_weight", "symbol"],
            ascending=[False, True, True],
        )

    def _attach_one_lot_order_costs(self, data: pd.DataFrame, *, price_map: pd.Series, nominal_nav: float) -> pd.DataFrame:
        out = data.copy()
        out["_one_lot_cash_required"] = out["symbol"].astype(str).map(
            lambda symbol: self._retail_cash_required(
                side="buy",
                price=float(price_map.at[symbol]) if symbol in price_map.index and pd.notna(price_map.at[symbol]) else 0.0,
                shares=float(trading_rule_for(symbol).minimum_buy_quantity),
            )
        )
        out["_one_lot_account_weight"] = out["_one_lot_cash_required"] / max(float(nominal_nav), 1e-12)
        return out

    def _force_deploy_order_payload(
        self,
        *,
        row: pd.Series,
        decision_id: str,
        decision_date,
        current_weights: dict[str, float],
        reason: str,
        priority: int,
    ) -> tuple[dict, float, float]:
        one_lot_cash = float(row["_one_lot_cash_required"])
        one_lot_weight = float(row["_one_lot_account_weight"])
        old_weight = float(current_weights.get(str(row["symbol"]), 0.0))
        payload = {column: pd.NA for column in ORDER_COLUMNS}
        payload.update(
            {
                "decision_id": str(decision_id),
                "decision_date": pd.Timestamp(decision_date),
                "execution_date": self.trading_calendar.next_session(decision_date),
                "symbol": str(row["symbol"]),
                "side": "buy",
                "current_weight": old_weight,
                "target_weight": old_weight + one_lot_weight,
                "delta_weight": one_lot_weight,
                "reason": str(reason),
                "priority": int(priority),
                "pending_policy": "daily_expiry",
                "position_state": row.get("position_state", ""),
                "position_exit_reason": row.get("position_exit_reason", ""),
                "add_layer": row.get("add_layer", pd.NA),
                "add_allowed": bool(row.get("add_allowed", False)),
                "add_block_reason": row.get("add_block_reason", ""),
                "entry_matrix_score": row.get("entry_matrix_score", pd.NA),
                "entry_alpha_score": row.get("entry_alpha_score", pd.NA),
                "entry_timing_score": row.get("entry_timing_score", pd.NA),
                "entry_liquidity_score": row.get("entry_liquidity_score", pd.NA),
                "alpha_quality_score": row.get("alpha_quality_score", pd.NA),
                "surge_capture_score": row.get("surge_capture_score", pd.NA),
                "follow_through_score": row.get("follow_through_score", pd.NA),
                "exhaustion_score": row.get("exhaustion_score", pd.NA),
                "entry_success_probability": row.get("entry_success_probability", pd.NA),
                "entry_size_tier": row.get("entry_size_tier", ""),
                "planned_entry_lots": row.get("planned_entry_lots", 1),
                "empirical_distribution_score": row.get("empirical_distribution_score", pd.NA),
                "final_entry_score": row.get("final_entry_score", pd.NA),
                "tail_risk_proxy": row.get("tail_risk_proxy", pd.NA),
                "trend_direction_score": row.get("trend_direction_score", pd.NA),
                "peak_decay_score": row.get("peak_decay_score", pd.NA),
                "profit_protection_pressure": row.get("profit_protection_pressure", pd.NA),
                "dynamic_giveback_limit": row.get("dynamic_giveback_limit", pd.NA),
                "future_loss_risk_score": row.get("future_loss_risk_score", pd.NA),
                "downtrend_decay_score": row.get("downtrend_decay_score", pd.NA),
                "post_entry_failure_score": row.get("post_entry_failure_score", pd.NA),
                "orderflow_candidate_score": row.get("orderflow_candidate_score", pd.NA),
                "reversal_entry_score": row.get("reversal_entry_score", pd.NA),
                "breakout_gate_score": row.get("breakout_gate_score", pd.NA),
                "trend_hold_score": row.get("trend_hold_score", pd.NA),
            }
        )
        return payload, one_lot_cash, one_lot_weight

    def _register_position_cooldown(self, symbol: str, *, date, reason: str) -> None:
        return register_position_cooldown_runtime(self, symbol, date=date, reason=reason)

    def _record_entry_confirmation(self, date, candidates: pd.DataFrame) -> None:
        if candidates is None or candidates.empty:
            self.entry_confirmation_rows.append(
                {
                    "date": pd.Timestamp(date),
                    "candidate_count": 0,
                    "entry_confirmed_count": 0,
                    "entry_confirmed_ratio": 0.0,
                    "top_block_reason": "no_candidates",
                }
            )
            return
        confirmed = candidates.get("entry_confirmed", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
        reasons = candidates.get("entry_block_reason", pd.Series("unknown", index=candidates.index)).fillna("unknown")
        reason_counts = reasons.value_counts(dropna=False)
        row = {
            "date": pd.Timestamp(date),
            "candidate_count": int(len(candidates)),
            "entry_confirmed_count": int(confirmed.sum()),
            "entry_confirmed_ratio": float(confirmed.mean()) if len(confirmed) else 0.0,
            "top_block_reason": str(reason_counts.index[0]) if not reason_counts.empty else "unknown",
            "top_block_reason_count": int(reason_counts.iloc[0]) if not reason_counts.empty else 0,
            "entry_quality_score_mean": _safe_numeric_mean(candidates.get("entry_quality_score")),
            "entry_matrix_score_mean": _safe_numeric_mean(candidates.get("entry_matrix_score")),
            "entry_alpha_score_mean": _safe_numeric_mean(candidates.get("entry_alpha_score")),
            "entry_timing_score_mean": _safe_numeric_mean(candidates.get("entry_timing_score")),
            "entry_liquidity_score_mean": _safe_numeric_mean(candidates.get("entry_liquidity_score")),
            "alpha_quality_score_mean": _safe_numeric_mean(candidates.get("alpha_quality_score")),
            "surge_capture_score_mean": _safe_numeric_mean(candidates.get("surge_capture_score")),
            "follow_through_score_mean": _safe_numeric_mean(candidates.get("follow_through_score")),
            "exhaustion_score_mean": _safe_numeric_mean(candidates.get("exhaustion_score")),
            "entry_success_probability_mean": _safe_numeric_mean(candidates.get("entry_success_probability")),
            "empirical_distribution_score_mean": _safe_numeric_mean(candidates.get("empirical_distribution_score")),
            "final_entry_score_mean": _safe_numeric_mean(candidates.get("final_entry_score")),
            "tail_risk_proxy_mean": _safe_numeric_mean(candidates.get("tail_risk_proxy")),
            "downtrend_decay_score_mean": _safe_numeric_mean(candidates.get("downtrend_decay_score")),
            "post_entry_failure_score_mean": _safe_numeric_mean(candidates.get("post_entry_failure_score")),
            "surge_buy_flag_count": int(candidates.get("surge_buy_flag", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "strong_starter_count": int(candidates.get("entry_size_tier", pd.Series("", index=candidates.index)).astype(str).eq("starter_strong").sum()),
            "starter_2_lot_count": int(candidates.get("entry_size_tier", pd.Series("", index=candidates.index)).astype(str).eq("starter_2_lot").sum()),
            "diversify_1_lot_count": int(candidates.get("entry_size_tier", pd.Series("", index=candidates.index)).astype(str).eq("diversify_1_lot").sum()),
            "exhaustion_block_count": int(pd.to_numeric(candidates.get("exhaustion_score", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0).ge(float(GOVERNANCE_EXHAUSTION_BUY_MAX)).sum()),
            "protecting_profit_count": int(candidates.get("position_state", pd.Series("", index=candidates.index)).astype(str).str.lower().eq("protecting_profit").sum()),
            "direct_buy_flag_count": int(candidates.get("direct_buy_flag", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "watchlist_flag_count": int(candidates.get("watchlist_flag", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "cooldown_active_count": int(candidates.get("cooldown_active", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "exit_state_count": int(candidates.get("exit_state", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "add_allowed_count": int(candidates.get("add_allowed", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "entry_alpha_threshold_mean": _safe_numeric_mean(candidates.get("entry_alpha_threshold")),
            "entry_orderflow_confirm_mean": _safe_numeric_mean(candidates.get("entry_orderflow_confirm_count")),
            "alpha_confirm_ratio": _safe_numeric_mean(candidates.get("alpha_confirm")),
            "market_confirm_ratio": _safe_numeric_mean(candidates.get("market_confirm")),
            "flow_confirm_ratio": _safe_numeric_mean(candidates.get("flow_confirm")),
            "calibrated_win_prob_5d_mean": _safe_numeric_mean(candidates.get("calibrated_win_prob_5d")),
            "p_win_10d_calibrated_mean": _safe_numeric_mean(candidates.get("p_win_10d_calibrated")),
            "p_win_10d_wilson_lower_mean": _safe_numeric_mean(candidates.get("p_win_10d_wilson_lower")),
            "entry_calibration_trust_10d_mean": _safe_numeric_mean(candidates.get("entry_calibration_trust_10d")),
            "expected_edge_5d_mean": _safe_numeric_mean(candidates.get("expected_edge_5d")),
            "expected_edge_10d_mean": _safe_numeric_mean(candidates.get("expected_edge_10d")),
            "conservative_expected_edge_10d_mean": _safe_numeric_mean(candidates.get("conservative_expected_edge_10d")),
            "edge_to_risk_10d_mean": _safe_numeric_mean(candidates.get("edge_to_risk_10d")),
            "conservative_edge_to_risk_10d_mean": _safe_numeric_mean(candidates.get("conservative_edge_to_risk_10d")),
            "entry_edge_rank_pct_mean": _safe_numeric_mean(candidates.get("entry_edge_rank_pct")),
            "entry_conservative_edge_rank_pct_mean": _safe_numeric_mean(candidates.get("entry_conservative_edge_rank_pct")),
            "entry_calibration_sample_count_10d_mean": _safe_numeric_mean(candidates.get("entry_calibration_sample_count_10d")),
            "entry_evidence_strong_count": int(candidates.get("entry_evidence_grade", pd.Series("", index=candidates.index)).astype(str).eq("strong").sum()),
            "entry_evidence_usable_count": int(candidates.get("entry_evidence_grade", pd.Series("", index=candidates.index)).astype(str).isin(["strong", "usable"]).sum()),
            "starter_position_allowed_count": int(candidates.get("starter_position_allowed", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "confirmed_add_position_allowed_count": int(candidates.get("confirmed_add_position_allowed", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "orderflow_candidate_score_mean": _safe_numeric_mean(candidates.get("orderflow_candidate_score")),
            "reversal_entry_score_mean": _safe_numeric_mean(candidates.get("reversal_entry_score")),
            "breakout_gate_score_mean": _safe_numeric_mean(candidates.get("breakout_gate_score")),
            "trend_hold_score_mean": _safe_numeric_mean(candidates.get("trend_hold_score")),
            "module_candidate_score_mean": _safe_numeric_mean(candidates.get("module_candidate_score")),
            "module_entry_score_mean": _safe_numeric_mean(candidates.get("module_entry_score")),
            "module_hold_score_mean": _safe_numeric_mean(candidates.get("module_hold_score")),
            "orderflow_candidate_pass_count": int(candidates.get("orderflow_candidate_pass", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "reversal_confirm_pass_count": int(candidates.get("reversal_confirm_pass", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "breakout_gate_pass_count": int(candidates.get("breakout_gate_pass", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
        }
        for reason, count in reason_counts.head(8).items():
            row[f"entry_reason_count_{reason}"] = int(count)
        self.entry_confirmation_rows.append(row)

    def _record_candidate_gate_audit(self, *, date, candidates: pd.DataFrame) -> None:
        """Store one narrow row per ranked candidate; never copy cabinet factor columns."""
        if self.shadow_fast_mode or candidates is None or candidates.empty:
            return
        decision_id = f"gov_{pd.Timestamp(date).strftime('%Y%m%d')}"
        bool_fields = (
            "alpha_confirm", "market_confirm", "flow_confirm",
            "orderflow_candidate_pass", "reversal_confirm_pass", "breakout_gate_pass",
            "state_machine_role_pass", "entry_confirmed", "cooldown_active", "exit_state",
            "entry_confirmed_matrix_counterfactual", "entry_confirmed_without_probability",
            "entry_confirmed_roles_only_counterfactual", "probability_gate_evaluated",
            "probability_gate_changed_decision", "paper_exit_state", "paper_profit_giveback_exit",
            "paper_post_entry_failure_exit", "paper_signal_failure_exit",
            "paper_thesis_failure_exit", "paper_stale_time_exit",
            "paper_loss_containment_exit", "paper_hard_stop_exit",
            "paper_profit_hard_stop_exit",
            "profit_giveback_exit", "post_entry_failure_exit", "signal_failure_exit",
            "thesis_failure_exit", "stale_time_exit", "loss_containment_exit",
            "hard_stop_exit", "profit_hard_stop_exit",
            "signal_failure_confirmed",
            "production_v1_entry_confirmed", "mainline_v2_eligible",
            "mainline_v2_entry_confirmed", "mainline_v2_changed_decision",
            "mainline_v3_eligible", "mainline_v3_entry_confirmed", "mainline_v3_changed_decision",
            "mainline_v3_lot_feasible", "lifecycle_held_row",
            "mainline_v3_selection_evaluated",
            "mainline_v3_raw_signal", "mainline_v3_structural_feasible",
            "mainline_v3_cash_feasible", "mainline_v3_slot_feasible",
            "scap_action_candidate", "scap_candidate_pool_factual_feasible",
            "scap_candidate_pool_positive_feasible",
        )
        score_fields = (
            "primary_score", "alpha_percentile", "entry_alpha_score", "entry_timing_score",
            "entry_liquidity_score", "entry_matrix_score", "final_entry_score",
            "p_win_10d_calibrated", "p_win_10d_wilson_lower",
            "production_v1_target_weight", "target_weight",
            "cabinet_base_entry_score", "cabinet_strict_entry_score", "cabinet_proxy_entry_score",
            "cabinet_timing_score", "cabinet_liquidity_health_score",
            "cabinet_risk_safety_score", "cabinet_hold_support_score",
            "v31_reliability_score", "v31_reliability_score_coverage",
            "monthly_lgbm_raw_score", "monthly_lgbm_rank_percentile",
            "hybrid_rule_rank_percentile", "hybrid_ml_rank_percentile",
            "hybrid_ml_weight", "hybrid_rule_weight", "hybrid_final_score",
            "mainline_v3_one_lot_cash_required", "mainline_v3_one_lot_weight",
            "scap_alpha_percentile", "scap_estimated_round_trip_cost_rate",
            "scap_cost_penalty", "scap_concentration_penalty",
            "scap_cash_fragment_penalty", "scap_soft_quality_penalty",
            "scap_overlap_penalty", "scap_candidate_utility",
            "comparable_value_horizon_days", "comparable_expected_alpha",
            "comparable_alpha_lcb", "scap_expected_return_point",
            "scap_expected_return_lcb", "scap_decision_expected_return",
            "scap_estimated_total_cost_amount", "scap_risk_penalty_amount",
            "scap_optimizer_objective", "scap_optimizer_candidate_pool_size",
            "scap_v31_decision_expected_return", "scap_v31_max_lots",
            "entry_calibration_unique_session_count_10d",
            "signal_failure_confirmation_count",
            "signal_failure_confirmation_required",
            "exit_conflict_count",
        )
        family_score_fields = tuple(
            column for column in candidates.columns
            if (
                column.startswith("cabinet_family_")
                or column.startswith("cabinet_entry_family_")
            ) and column.endswith("_score")
        )
        score_fields = score_fields + family_score_fields
        day_rows = []
        for _, candidate in candidates.iterrows():
            row = {
                "decision_id": decision_id,
                "signal_date": pd.Timestamp(date),
            "strategy_logic_version": self.strategy_logic_version,
            "calibration_runtime_state": str(candidate.get("calibration_runtime_state", "")),
                "symbol": str(candidate.get("symbol", "")),
                "candidate_rank": candidate.get("candidate_rank", pd.NA),
                "entry_block_reason": str(candidate.get("entry_block_reason", "")),
                "state_machine_role_block_reason": str(candidate.get("state_machine_role_block_reason", "")),
                "position_state": str(candidate.get("position_state", "")),
                "cabinet_entry_thesis": str(candidate.get("cabinet_entry_thesis", "")),
                "cabinet_entry_thesis_support": candidate.get("cabinet_entry_thesis_support", pd.NA),
                "hybrid_fusion_status": str(candidate.get("hybrid_fusion_status", "")),
                "hybrid_fusion_formula_version": str(candidate.get("hybrid_fusion_formula_version", "")),
                "hybrid_score_authority": str(candidate.get("hybrid_score_authority", "")),
                "v31_reliability_contract": str(candidate.get("v31_reliability_contract", "")),
                "v31_calibration_window": str(candidate.get("v31_calibration_window", "")),
                "v31_score_formula": str(candidate.get("v31_score_formula", "")),
                "v31_score_authority": str(candidate.get("v31_score_authority", "")),
                "v31_strict_entry_paper_only": candidate.get("v31_strict_entry_paper_only", pd.NA),
                "scap_candidate_utility_version": str(candidate.get("scap_candidate_utility_version", "")),
                "scap_decision_return_basis": str(candidate.get("scap_decision_return_basis", "")),
                "scap_overlap_penalty_state": str(candidate.get("scap_overlap_penalty_state", "")),
                "scap_optimizer_selected": candidate.get("scap_optimizer_selected", pd.NA),
                "scap_optimizer_status": str(candidate.get("scap_optimizer_status", "")),
                "scap_candidate_pool_contract_version": str(
                    candidate.get("scap_candidate_pool_contract_version", "")
                ),
                "scap_v31_authority_tier": str(
                    candidate.get("scap_v31_authority_tier", "")
                ),
                "scap_v31_authority_reason": str(
                    candidate.get("scap_v31_authority_reason", "")
                ),
                "scap_v31_authority_contract": str(
                    candidate.get("scap_v31_authority_contract", "")
                ),
                "exit_arbitration_contract": str(
                    candidate.get("exit_arbitration_contract", "")
                ),
                "exit_triggered_reasons": str(
                    candidate.get("exit_triggered_reasons", "")
                ),
                "exit_authorized_reasons": str(
                    candidate.get("exit_authorized_reasons", "")
                ),
                "exit_vetoed_reasons": str(
                    candidate.get("exit_vetoed_reasons", "")
                ),
                "mainline_v3_score_authority": str(
                    candidate.get("mainline_v3_score_authority", "")
                ),
                "mainline_v3_score_authority_version": str(
                    candidate.get("mainline_v3_score_authority_version", "")
                ),
            }
            for field in bool_fields:
                value = candidate.get(field, pd.NA)
                row[field] = bool(value) if pd.notna(value) else pd.NA
            for source, target in (
                ("alpha_confirm", "alpha_confirm_pass"),
                ("market_confirm", "market_confirm_pass"),
                ("flow_confirm", "flow_confirm_pass"),
            ):
                row[target] = row.get(source, pd.NA)
            for field in score_fields:
                row[field] = candidate.get(field, pd.NA)
            day_rows.append(row)
        if day_rows:
            self._candidate_gate_spool_dir.mkdir(parents=True, exist_ok=True)
            month_path = self._candidate_gate_spool_dir / f"cg_{pd.Timestamp(date):%Y%m}.csv"
            pd.DataFrame(day_rows).to_csv(
                month_path,
                mode="a",
                header=not month_path.exists(),
                index=False,
                encoding="utf-8-sig",
            )

    def _candidate_gate_part_paths(self) -> list[Path]:
        if not self._candidate_gate_spool_dir.exists():
            return []
        return sorted(self._candidate_gate_spool_dir.glob("cg_*.csv"))

    def _candidate_gate_partition_index(self) -> pd.DataFrame:
        rows = []
        for path in self._candidate_gate_part_paths():
            try:
                row_count = sum(
                    len(chunk)
                    for chunk in pd.read_csv(path, usecols=["signal_date"], chunksize=5000)
                )
            except (OSError, pd.errors.EmptyDataError, ValueError):
                row_count = 0
            rows.append({"path": str(path), "row_count": int(row_count), "size_bytes": int(path.stat().st_size)})
        return pd.DataFrame(rows)

    def _load_candidate_gate_audit(self, *, max_rows: int = 20000) -> pd.DataFrame:
        parts = []
        remaining = max(int(max_rows), 0)
        for path in self._candidate_gate_part_paths():
            if remaining <= 0:
                break
            try:
                part = pd.read_csv(path, nrows=remaining, low_memory=False)
            except (OSError, pd.errors.EmptyDataError):
                continue
            if not part.empty:
                parts.append(part)
                remaining -= len(part)
        if self.candidate_gate_rows:
            parts.append(pd.DataFrame(self.candidate_gate_rows))
        result = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        if not result.empty:
            result["audit_detail_scope"] = "bounded_sample; full_detail_in_runtime_audit_spool"
        return result

    def _record_defensive_sleeve_diagnostics(
        self,
        *,
        date,
        daily: pd.DataFrame,
        risk_level: str,
        structural_regime_level: str,
        stock_candidate_count: int,
    ) -> pd.DataFrame:
        rows = []
        if daily is None or daily.empty:
            return pd.DataFrame()
        universe = {}
        for asset_class, symbols in dict(GOVERNANCE_DEFENSIVE_SLEEVE_ASSETS).items():
            for symbol in symbols:
                universe[str(symbol).lower()] = str(asset_class)
        if not universe:
            return pd.DataFrame()
        data = daily.copy()
        data["symbol_key"] = data["symbol"].astype(str).str.lower()
        data = data[data["symbol_key"].isin(universe)].copy()
        if data.empty:
            return pd.DataFrame()
        amount = pd.to_numeric(data.get("amount", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
        amount_ma20 = pd.to_numeric(data.get("amount_ma20", pd.Series(amount, index=data.index)), errors="coerce").replace(0.0, pd.NA)
        ret20 = pd.to_numeric(data.get("ret_20", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
        ret5 = pd.to_numeric(data.get("ret_5", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
        vol = pd.to_numeric(data.get("volatility_20", pd.Series(0.02, index=data.index)), errors="coerce").fillna(0.02)
        close_to_ma20 = pd.to_numeric(data.get("close_to_ma20", pd.Series(0.0, index=data.index)), errors="coerce").fillna(0.0)
        liquidity_score = (amount / amount_ma20).fillna(1.0).clip(0.0, 2.0) / 2.0
        low_vol_score = (1.0 - (vol / max(float(vol.median()), 1e-9)).clip(0.0, 2.0) / 2.0).clip(0.0, 1.0)
        trend_score = (0.65 * ret20.rank(pct=True).fillna(0.0) + 0.35 * ret5.rank(pct=True).fillna(0.0)).clip(0.0, 1.0)
        drawdown_resilience = (1.0 - close_to_ma20.abs().clip(0.0, 0.20) / 0.20).clip(0.0, 1.0)
        defensive_score = (
            0.30 * trend_score
            + 0.25 * low_vol_score
            + 0.25 * liquidity_score
            + 0.20 * drawdown_resilience
        ).clip(0.0, 1.0)
        force_deploy = self.capital_usage_mode == GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY
        risk = str(risk_level or "").lower()
        for idx, row in data.iterrows():
            score = _safe_float(defensive_score.loc[idx], default=0.0)
            state = "inactive"
            if force_deploy and int(stock_candidate_count) < int(self.capital_profile.get("min_holdings", GOVERNANCE_FORCE_DEPLOY_MIN_HOLDINGS_20K) or GOVERNANCE_FORCE_DEPLOY_MIN_HOLDINGS_20K):
                state = "eligible_defensive" if score >= 0.55 and risk not in {"crisis"} else "paper_defensive"
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "symbol": str(row.get("symbol", "")),
                    "asset_class": universe.get(str(row.get("symbol_key", "")), "unknown"),
                    "risk_level": str(risk_level),
                    "structural_regime_level": str(structural_regime_level),
                    "stock_candidate_count": int(stock_candidate_count),
                    "capital_usage_mode": self.capital_usage_mode,
                    "defensive_score": score,
                    "defensive_trend_score": _safe_float(trend_score.loc[idx], default=0.0),
                    "defensive_low_vol_score": _safe_float(low_vol_score.loc[idx], default=0.0),
                    "defensive_liquidity_score": _safe_float(liquidity_score.loc[idx], default=0.0),
                    "defensive_drawdown_resilience": _safe_float(drawdown_resilience.loc[idx], default=0.0),
                    "defensive_state": state,
                }
            )
        self.defensive_sleeve_rows.extend(rows)
        return pd.DataFrame(rows)

    def _record_entry_formula_and_retail_rank(self, *, date, candidates: pd.DataFrame, daily: pd.DataFrame, exposure: dict) -> None:
        if self.shadow_fast_mode or candidates is None or candidates.empty:
            return
        data = candidates.copy()
        data["symbol"] = data["symbol"].astype(str)
        price_map = (
            daily.assign(symbol=daily["symbol"].astype(str)).set_index("symbol")["close_nominal"].to_dict()
            if daily is not None and not daily.empty and "close_nominal" in daily.columns
            else {}
        )
        nominal_nav = max(float(exposure.get("nominal_nav", 0.0) or 0.0), 1e-12)
        available_cash = max(float(self.cash), 0.0)
        min_buffer = float(self.capital_profile.get("min_cash_buffer", 0.0) or 0.0)
        single_cap = float(self.capital_profile.get("retail_single_position_cap", 0.40) or 0.40)
        one_lot_cap = float(self.capital_profile.get("retail_one_lot_position_cap", single_cap) or single_cap)
        min_entry_score = float(self.capital_profile.get("retail_min_entry_matrix_score", 0.0) or 0.0)
        current_weights = {
            str(row.get("symbol", "")): float(row.get("market_value", 0.0) or 0.0) / nominal_nav
            for row in getattr(self, "_last_position_mark_rows", []) or []
        }
        rank_rows = []
        if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"} and "scap_candidate_utility" in data.columns:
            ordered = data.sort_values(
                ["scap_optimizer_selected", "scap_candidate_utility", "primary_score", "symbol"],
                ascending=[False, False, False, True],
            ).head(GOVERNANCE_AUDIT_ENTRY_FORMULA_LIMIT)
        else:
            ordered = data.sort_values(
                ["entry_matrix_score", "primary_score", "symbol"],
                ascending=[False, False, True],
            ).head(GOVERNANCE_AUDIT_ENTRY_FORMULA_LIMIT)
        for _, row in ordered.iterrows():
            symbol = str(row.get("symbol", ""))
            price = _safe_float(price_map.get(symbol), default=float("nan"))
            one_lot_cash_required = (
                self._retail_cash_required(
                    side="buy",
                    price=price,
                    shares=float(trading_rule_for(symbol).minimum_buy_quantity),
                )
                if pd.notna(price) and price > 0.0
                else float("nan")
            )
            one_lot_weight = one_lot_cash_required / nominal_nav if pd.notna(one_lot_cash_required) else float("nan")
            current_weight = float(current_weights.get(symbol, 0.0) or 0.0)
            state = str(row.get("position_state", "") or "").strip().lower()
            cash_ok = pd.notna(one_lot_cash_required) and one_lot_cash_required <= max(available_cash - min_buffer, 0.0)
            cap_ok = pd.notna(one_lot_weight) and current_weight + one_lot_weight <= one_lot_cap + 1e-12
            state_ok = state not in {"blocked", "cooldown", "exiting", "protecting_profit"} and not bool(row.get("exit_state", False))
            score_ok = _retail_entry_score_gate_pass(
                row,
                strategy_logic_version=self.strategy_logic_version,
                minimum_score=min_entry_score,
            )
            block_reasons = []
            if not pd.notna(price) or price <= 0.0:
                block_reasons.append("missing_price")
            if not cash_ok:
                block_reasons.append("lot_size_cash_insufficient")
            if not cap_ok:
                block_reasons.append("one_lot_position_cap")
            if not state_ok:
                block_reasons.append("position_state")
            if not score_ok:
                block_reasons.append("entry_matrix_score")
            alpha_score = _safe_float(row.get("entry_alpha_score"), default=0.0)
            timing_score = _safe_float(row.get("entry_timing_score"), default=0.0)
            liquidity_score = _safe_float(row.get("entry_liquidity_score"), default=0.0)
            matrix_score = _safe_float(row.get("entry_matrix_score"), default=0.0)
            alpha_quality_score = _safe_float(row.get("alpha_quality_score"), default=0.0)
            surge_score = _safe_float(row.get("surge_capture_score"), default=0.0)
            follow_through_score = _safe_float(row.get("follow_through_score"), default=0.0)
            exhaustion_score = _safe_float(row.get("exhaustion_score"), default=0.0)
            entry_success_probability = _safe_float(row.get("entry_success_probability"), default=0.0)
            downtrend_score = _safe_float(row.get("downtrend_decay_score"), default=0.0)
            post_failure_score = _safe_float(row.get("post_entry_failure_score"), default=0.0)
            one_lot_penalty = min(max(one_lot_weight if pd.notna(one_lot_weight) else 1.0, 0.0), 1.0)
            retail_score = (
                0.45 * matrix_score
                + 0.25 * timing_score
                + 0.15 * liquidity_score
                + 0.10 * alpha_score
                + 0.05 * (1.0 - one_lot_penalty)
            )
            if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}:
                retail_score = _safe_float(row.get("scap_candidate_utility"), default=retail_score)
            payload = {
                "decision_id": f"gov_{pd.Timestamp(date).strftime('%Y%m%d')}",
                "date": pd.Timestamp(date),
                "symbol": symbol,
                "primary_score": row.get("primary_score", pd.NA),
                "alpha_percentile": row.get("alpha_percentile", pd.NA),
                "expected_return_5d": row.get("expected_return_5d", pd.NA),
                "entry_alpha_score": alpha_score,
                "entry_timing_score": timing_score,
                "entry_liquidity_score": liquidity_score,
                "entry_matrix_score": matrix_score,
                "alpha_quality_score": alpha_quality_score,
                "surge_capture_score": surge_score,
                "follow_through_score": follow_through_score,
                "exhaustion_score": exhaustion_score,
                "entry_success_probability": entry_success_probability,
                "entry_size_tier": row.get("entry_size_tier", ""),
                "planned_entry_lots": row.get("planned_entry_lots", pd.NA),
                "downtrend_decay_score": downtrend_score,
                "post_entry_failure_score": post_failure_score,
                "surge_buy_flag": bool(row.get("surge_buy_flag", False)),
                "entry_confirmed": bool(row.get("entry_confirmed", False)),
                "entry_quality_tier": row.get("entry_quality_tier", ""),
                "position_state": row.get("position_state", ""),
                "entry_block_reason": row.get("entry_block_reason", ""),
                "state_machine_role_pass": row.get("state_machine_role_pass", pd.NA),
                "state_machine_role_block_reason": row.get("state_machine_role_block_reason", ""),
                "cooldown_active": row.get("cooldown_active", False),
                "retail_executable": not block_reasons,
                "retail_block_reason": "|".join(block_reasons),
                "retail_executable_score": float(retail_score),
                "price": price,
                "one_lot_cash_required": one_lot_cash_required,
                "one_lot_account_weight": one_lot_weight,
                "retail_one_lot_position_cap": one_lot_cap,
                "available_cash": available_cash,
                "cash_buffer_required": min_buffer,
                "scap_alpha_percentile": row.get("scap_alpha_percentile", pd.NA),
                "scap_estimated_round_trip_cost_rate": row.get(
                    "scap_estimated_round_trip_cost_rate", pd.NA
                ),
                "scap_cost_penalty": row.get("scap_cost_penalty", pd.NA),
                "scap_concentration_penalty": row.get("scap_concentration_penalty", pd.NA),
                "scap_cash_fragment_penalty": row.get("scap_cash_fragment_penalty", pd.NA),
                "scap_soft_quality_penalty": row.get("scap_soft_quality_penalty", pd.NA),
                "scap_overlap_penalty": row.get("scap_overlap_penalty", pd.NA),
                "scap_overlap_penalty_state": row.get("scap_overlap_penalty_state", ""),
                "scap_candidate_utility": row.get("scap_candidate_utility", pd.NA),
                "scap_candidate_utility_version": row.get("scap_candidate_utility_version", ""),
                "scap_optimizer_selected": row.get("scap_optimizer_selected", pd.NA),
                "scap_optimizer_objective": row.get("scap_optimizer_objective", pd.NA),
                "scap_optimizer_candidate_pool_size": row.get(
                    "scap_optimizer_candidate_pool_size", pd.NA
                ),
                "scap_optimizer_status": row.get("scap_optimizer_status", ""),
                "mainline_v3_raw_signal": row.get("mainline_v3_raw_signal", pd.NA),
                "mainline_v3_structural_feasible": row.get(
                    "mainline_v3_structural_feasible", pd.NA
                ),
                "mainline_v3_cash_feasible": row.get(
                    "mainline_v3_cash_feasible", pd.NA
                ),
                "mainline_v3_slot_feasible": row.get(
                    "mainline_v3_slot_feasible", pd.NA
                ),
                "forward_return_1d": self._forward_return(symbol, date, 1),
                "forward_return_3d": self._forward_return(symbol, date, 3),
                "forward_return_5d": self._forward_return(symbol, date, 5),
                "forward_return_10d": self._forward_return(symbol, date, 10),
                "forward_return_20d": self._forward_return(symbol, date, 20),
            }
            payload.update(self._post_entry_price_diagnostics(symbol, date, price))
            self.entry_formula_audit_rows.append(payload)
            if payload["retail_executable"] or payload["entry_confirmed"]:
                rank_rows.append(payload)
        rank_rows = sorted(
            rank_rows,
            key=lambda item: (
                -int(bool(item.get("retail_executable", False))),
                -float(item.get("retail_executable_score", 0.0) or 0.0),
                str(item.get("symbol", "")),
            ),
        )[:40]
        for rank, row in enumerate(rank_rows, start=1):
            payload = dict(row)
            payload["retail_executable_rank"] = rank
            self.retail_executable_rank_rows.append(payload)

    def _forward_return(self, symbol: str, date, horizon_days: int):
        try:
            horizon = int(horizon_days)
            if horizon <= 0:
                return pd.NA
            history = self._audit_close_history(symbol)
            if history.empty:
                return pd.NA
            dates = pd.to_datetime(history["date"], errors="coerce")
            closes = pd.to_numeric(history["close"], errors="coerce")
            current = closes[dates.le(pd.Timestamp(date))].dropna()
            future = closes[dates.gt(pd.Timestamp(date))].dropna().head(horizon)
            if current.empty or len(future) < horizon or float(current.iloc[-1]) <= 0.0:
                return pd.NA
            return float(future.iloc[-1] / float(current.iloc[-1]) - 1.0)
        except Exception:
            return pd.NA

    def _close_history(self, symbol: str) -> pd.DataFrame:
        symbol_key = str(symbol)
        cached = self._close_history_cache.pop(symbol_key, None)
        if cached is not None:
            self._close_history_cache[symbol_key] = cached
            return cached

        close_col = "close_nominal" if "close_nominal" in self.features.columns else "close"
        if close_col not in self.features.columns:
            return pd.DataFrame(columns=["date", "close"])
        if self._feature_indices_by_symbol is None:
            # Integer index arrays are compact references into self.features;
            # unlike a group-by DataFrame dictionary they do not duplicate the
            # full 5M+ row feature table.
            self._feature_indices_by_symbol = {
                str(key): value
                for key, value in self.features.groupby("symbol", sort=False).indices.items()
            }
        indices = self._feature_indices_by_symbol.get(symbol_key)
        if indices is None:
            return pd.DataFrame(columns=["date", "close"])
        history = self.features.iloc[indices][["date", close_col]].copy()
        history["date"] = pd.to_datetime(history["date"], errors="coerce")
        if close_col != "close":
            history = history.rename(columns={close_col: "close"})
        history["close"] = pd.to_numeric(history["close"], errors="coerce")
        history = history.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        self._close_history_cache[symbol_key] = history
        while len(self._close_history_cache) > int(GOVERNANCE_AUDIT_PRICE_HISTORY_CACHE_SYMBOL_LIMIT):
            self._close_history_cache.popitem(last=False)
        return history

    def _audit_close_history(self, symbol: str) -> pd.DataFrame:
        """Return post-run outcome prices, never strategy-decision features."""
        symbol_key = str(symbol)
        cached = self._audit_close_history_cache.pop(symbol_key, None)
        if cached is not None:
            self._audit_close_history_cache[symbol_key] = cached
            return cached
        if self.audit_prices.empty:
            return pd.DataFrame(columns=["date", "close"])
        if self._audit_price_indices_by_symbol is None:
            self._audit_price_indices_by_symbol = {
                str(key): value
                for key, value in self.audit_prices.groupby("symbol", sort=False).indices.items()
            }
        indices = self._audit_price_indices_by_symbol.get(symbol_key)
        if indices is None:
            return pd.DataFrame(columns=["date", "close"])
        history = (
            self.audit_prices.iloc[indices][["date", "close"]]
            .dropna()
            .sort_values("date")
            .reset_index(drop=True)
        )
        self._audit_close_history_cache[symbol_key] = history
        while len(self._audit_close_history_cache) > int(GOVERNANCE_AUDIT_PRICE_HISTORY_CACHE_SYMBOL_LIMIT):
            self._audit_close_history_cache.popitem(last=False)
        return history

    def _post_entry_price_diagnostics(self, symbol: str, date, entry_price) -> dict:
        result = {
            "best_buy_after_entry_date": pd.NaT,
            "best_buy_after_entry_gap": pd.NA,
            "worst_drawdown_after_entry": pd.NA,
        }
        price = _safe_float(entry_price, default=0.0)
        if price <= 0.0:
            return result
        history = self._close_history(symbol)
        if history.empty:
            return result
        dates = pd.to_datetime(history["date"], errors="coerce")
        loc = dates.searchsorted(pd.Timestamp(date), side="right")
        window = history.iloc[loc : loc + 10].copy()
        if window.empty:
            return result
        closes = pd.to_numeric(window["close"], errors="coerce").dropna()
        if closes.empty:
            return result
        best_idx = closes.idxmin()
        best_price = float(closes.loc[best_idx])
        result["best_buy_after_entry_date"] = pd.Timestamp(window.loc[best_idx, "date"])
        result["best_buy_after_entry_gap"] = float(best_price / price - 1.0)
        result["worst_drawdown_after_entry"] = float(closes.min() / price - 1.0)
        return result

    def _build_shadow_runners(self):
        return {
            model_name: FastShadowPortfolioRunner(
                self.features,
                model_name=model_name,
                safety_signals=self.engine.safety_signals,
                daily_feature_indices=self._daily_feature_indices,
                initial_cash=self.initial_cash,
                universe_mode=self._universe_mode,
                target_index_codes=self._target_index_codes,
                require_constituents=self._require_constituents,
                allow_fallback=self._allow_fallback,
                allowed_instrument_types=self._allowed_instrument_types,
                enable_quality_filters=self._enable_quality_filters,
                top_n=GOVERNANCE_DEFAULT_TOP_N,
                runtime_context=self.factor_runtime_context,
            )
            for model_name in self.alpha_models
        }

    def _execute_pending(self, date, daily):
        return execute_pending_runtime(self, date, daily)

    def _prune_empty_positions(self, *, min_shares: float = 1e-9) -> None:
        return prune_empty_positions_runtime(self, min_shares=min_shares)

    def _record_exposure(self, date, daily):
        return record_exposure_runtime(self, date, daily)

    def _register_orders(self, orders, daily, nominal_nav):
        return register_orders_runtime(self, orders, daily, nominal_nav)

    def _sort_retail_orders(self, orders: pd.DataFrame) -> pd.DataFrame:
        return sort_retail_orders_runtime(self, orders)

    def _adapt_retail_buy_order(
        self,
        *,
        order,
        strategy_target_notional: float,
        order_price: float,
        nominal_nav: float,
        reserved_cash: float,
        initial_shares: float,
        one_lot_cash_required: float | None = None,
    ) -> tuple[float, str, str]:
        return adapt_retail_buy_order_runtime(
            self,
            order=order,
            strategy_target_notional=strategy_target_notional,
            order_price=order_price,
            nominal_nav=nominal_nav,
            reserved_cash=reserved_cash,
            initial_shares=initial_shares,
            one_lot_cash_required=one_lot_cash_required,
        )

    def _retail_cash_required(self, *, side: str, price: float, shares: float) -> float:
        return retail_cash_required_runtime(self, side=side, price=price, shares=shares)

    def _record_retail_execution_diagnostic(
        self,
        *,
        order,
        nominal_nav: float,
        price,
        one_lot_cost,
        strategy_target_notional: float,
        adjusted_target_notional: float,
        target_shares: float,
        available_cash: float,
        retail_action: str,
        retail_block_reason: str,
        one_lot_cash_required=None,
    ) -> None:
        return record_retail_execution_diagnostic_runtime(
            self,
            order=order,
            nominal_nav=nominal_nav,
            price=price,
            one_lot_cost=one_lot_cost,
            strategy_target_notional=strategy_target_notional,
            adjusted_target_notional=adjusted_target_notional,
            target_shares=target_shares,
            available_cash=available_cash,
            retail_action=retail_action,
            retail_block_reason=retail_block_reason,
            one_lot_cash_required=one_lot_cash_required,
        )

    def _current_weights(self, daily, nominal_nav):
        return current_weights_runtime(self, daily, nominal_nav)

    def _get_regime_params(self, date):
        """Get regime-adjusted parameters for the current date."""
        if self.market_regime_policy is None:
            return None
        date_key = pd.Timestamp(date)
        if date_key in self._regime_params_cache:
            return self._regime_params_cache[date_key]
        params_dict = self.market_regime_policy.get_params_dict(
            self.features,
            date_key,
            benchmark_symbol=MARKET_REGIME_BENCHMARK_SYMBOL,
        )
        self._current_regime = params_dict.get("regime", "unknown")
        self._regime_diagnostics_cache[date_key] = {
            key: value
            for key, value in params_dict.items()
            if key.startswith("regime_")
        }
        if not self.enable_market_regime_policy:
            # Observation-only path: preserve the repaired state diagnostics
            # without allowing the regime parameters to change orders/exits.
            self._regime_params_cache[date_key] = None
            return None
        if (
            self.governance_control_mode == "aggressive_lean"
            and str(
                self.capital_profile.get(
                    "scap_market_regime_control_mode", "bounded_continuous_es_only"
                )
            ).strip().lower()
            == "bounded_continuous_es_only"
        ):
            # SCAP observes the repaired regime data but does not consume the
            # categorical Kelly, entry, position-count or rebalance switches.
            # Only the bounded continuous ES multiplier below has authority.
            self._regime_params_cache[date_key] = None
            return None
        from functions.decision_council.market_regime_policy import RegimeParams
        params = RegimeParams(
                safety_warning_drawdown=params_dict["safety_warning_drawdown"],
                safety_high_drawdown=params_dict["safety_high_drawdown"],
                safety_crisis_drawdown=params_dict["safety_crisis_drawdown"],
                safety_warning_confirm_days=params_dict["safety_warning_confirm_days"],
                safety_high_confirm_days=params_dict["safety_high_confirm_days"],
                safety_crisis_confirm_days=params_dict["safety_crisis_confirm_days"],
                min_score_percentile=params_dict["min_score_percentile"],
                kelly_scale=params_dict["kelly_scale"],
                min_p_win=params_dict["min_p_win"],
                severe_exit_kelly_score=params_dict["severe_exit_kelly_score"],
                default_turnover_budget=params_dict["default_turnover_budget"],
                max_positions=params_dict["max_positions"],
                max_position_weight=params_dict["max_position_weight"],
                max_sector_weight=params_dict["max_sector_weight"],
                rebalance_interval_days=params_dict["rebalance_interval_days"],
                regime_name=params_dict.get("regime", "unknown"),
        )
        self._regime_params_cache[date_key] = params
        return params

    def _scap_regime_es_budget_multiplier(self, date) -> float:
        if self.governance_control_mode != "aggressive_lean":
            return 1.0
        mode = str(
            self.capital_profile.get(
                "scap_market_regime_control_mode", "bounded_continuous_es_only"
            )
        ).strip().lower()
        if mode != "bounded_continuous_es_only":
            return 1.0
        diagnostics = self._regime_diagnostics_cache.get(pd.Timestamp(date), {})
        valid = bool(diagnostics.get("regime_input_valid", False))
        diagnostics_enabled = getattr(self, "market_regime_policy", None) is not None
        es_authorized = bool(
            getattr(self, "enable_market_regime_policy", False)
            and diagnostics_enabled
        )
        if not diagnostics_enabled or not valid or not es_authorized:
            neutral = float(
                self.capital_profile.get("scap_invalid_regime_es_multiplier", 1.0)
                or 1.0
            )
            if abs(neutral - 1.0) > 1e-12:
                raise ValueError("invalid market-regime evidence must fail neutral at 1.0")
            return 1.0
        raw = {
            "bull": 1.05,
            "rebound": 1.05,
            "neutral": 1.00,
            "weak": 0.85,
            "bear": 0.75,
            "crisis": 0.70,
        }.get(str(self._current_regime).strip().lower(), 1.0)
        lower = float(self.capital_profile.get("scap_regime_es_multiplier_min", 0.70) or 0.70)
        upper = float(self.capital_profile.get("scap_regime_es_multiplier_max", 1.10) or 1.10)
        if lower <= 0.0 or upper < lower:
            raise ValueError("invalid bounded regime ES multiplier interval")
        return min(max(float(raw), lower), upper)

    def _allow_normal_rebalance(self, date, day_index):
        if self._normal_rebalance_dates:
            return pd.Timestamp(date) in self._normal_rebalance_dates
        if self.strategy_logic_version == MAINLINE_V2 or is_mainline_v3_version(self.strategy_logic_version):
            return int(day_index) % 5 == 0
        # Use regime-adjusted rebalancing interval
        regime_params = self._get_regime_params(date)
        if regime_params:
            interval = regime_params.rebalance_interval_days
        else:
            interval = 5  # Default weekly
        return int(day_index) % interval == 0

    def _hard_qualification_symbols(self):
        if not self.positions:
            return frozenset()
        return frozenset(
            symbol
            for symbol in self.positions
            if symbol in self._instrument_type_by_symbol
            and self._instrument_type_by_symbol[symbol] not in GOVERNANCE_ALLOWED_INSTRUMENT_TYPES
        )

    def _record_account_audit(self, date):
        return record_account_audit_runtime(self, date)

    def _symbol_lock_days(self, symbol):
        rows = self.engine.pending_orders.orders
        rows = rows[(rows["symbol"].astype(str) == symbol) & (rows["status"] == "pending_locked")]
        return int(pd.to_numeric(rows["lock_days"], errors="coerce").max()) if not rows.empty else 0

    def _advance_holding_days(self):
        for symbol in list(self.holding_days):
            self.holding_days[symbol] += 1

    def _mature_reward(self, date):
        if len(self.exposure_rows) < 6:
            return None
        window = pd.DataFrame(self.exposure_rows[-6:])
        recent_dates = set(pd.to_datetime(window["date"]))
        turnover = sum(
            float(row.get("trade_notional", 0.0)) for row in self.execution_rows
            if pd.Timestamp(row["trade_date"]) in recent_dates
        ) / max(float(window.iloc[0]["nominal_nav"]), 1e-12)
        reward = calculate_five_day_reward(window["liquidatable_nav"], executed_turnover_5d=turnover)
        nominal_return = float(window.iloc[-1]["nominal_nav"] / window.iloc[0]["nominal_nav"] - 1.0)
        reward.update(
            {
                "maturity_date": pd.Timestamp(date),
                "decision_id": window.iloc[0]["decision_id"],
                "liquidity_lock_loss_5d": nominal_return - reward["liquidatable_nav_return_5d"],
            }
        )
        self.reward_rows.append(reward)
        return reward

    def _mature_alpha_collapse_diagnostics(self, date):
        pending = []
        for event in self._pending_alpha_collapse_exits:
            symbol_path = self.features[
                (self.features["symbol"].astype(str) == str(event["symbol"]))
                & (self.features["date"] > event["exit_date"])
                & (self.features["date"] <= pd.Timestamp(date))
            ].sort_values("date")
            if len(symbol_path) < 5:
                pending.append(event)
                continue
            future = symbol_path.iloc[4]
            symbol_return = float(future["close_nominal"]) / float(event["exit_price"]) - 1.0
            benchmark_return, benchmark_volatility = self._benchmark_path_metrics(event["exit_date"], future["date"])
            excess_return = symbol_return - benchmark_return
            threshold = max(0.03, 1.5 * benchmark_volatility)
            self.alpha_collapse_exit_rows.append(
                {
                    **event,
                    "maturity_date": pd.Timestamp(future["date"]),
                    "post_exit_return_5d": symbol_return,
                    "benchmark_return_5d": benchmark_return,
                    "benchmark_volatility_5d": benchmark_volatility,
                    "post_exit_excess_return_5d": excess_return,
                    "false_exit_threshold": threshold,
                    "false_exit": bool(excess_return > threshold),
                }
            )
        self._pending_alpha_collapse_exits = pending

    def _trailing_trade_accuracy(self, date, *, side: str, horizon_days: int = 5, lookback_trades: int = 60) -> float | None:
        if not self.execution_rows:
            return None
        trades = pd.DataFrame(self.execution_rows)
        required = {"trade_date", "symbol", "side", "price", "execution_status"}
        if not required.issubset(trades.columns):
            return None
        trades["trade_date"] = pd.to_datetime(trades["trade_date"], errors="coerce")
        trades = trades[
            trades["execution_status"].astype(str).eq("filled")
            & trades["side"].astype(str).eq(str(side))
            & (trades["trade_date"] <= pd.Timestamp(date) - pd.offsets.BDay(horizon_days))
        ].copy()
        if trades.empty:
            return None
        trades = trades.sort_values("trade_date").tail(int(lookback_trades))
        outcomes = []
        close_col = "close_nominal" if "close_nominal" in self.features.columns else "close"
        for _, trade in trades.iterrows():
            path = self.features[
                (self.features["symbol"].astype(str) == str(trade["symbol"]))
                & (self.features["date"] > pd.Timestamp(trade["trade_date"]))
                & (self.features["date"] <= pd.Timestamp(date))
            ].sort_values("date").head(horizon_days)
            if len(path) < horizon_days:
                continue
            future_close = pd.to_numeric(path[close_col], errors="coerce").dropna()
            price = float(pd.to_numeric(pd.Series([trade["price"]]), errors="coerce").fillna(0.0).iloc[0])
            if future_close.empty or price <= 0:
                continue
            fwd_return = float(future_close.iloc[-1]) / price - 1.0
            outcomes.append(fwd_return > 0.0 if str(side) == "buy" else fwd_return < 0.0)
        if not outcomes:
            return None
        return float(pd.Series(outcomes, dtype=bool).mean())

    def _benchmark_path_metrics(self, exit_date, maturity_date):
        proxy = self.engine.safety_agent.proxy_symbol
        if proxy is None:
            return 0.0, 0.0
        path = self.features[
            (self.features["symbol"].astype(str) == str(proxy))
            & (self.features["date"] >= pd.Timestamp(exit_date))
            & (self.features["date"] <= pd.Timestamp(maturity_date))
        ].sort_values("date")
        close = pd.to_numeric(path["close_nominal"], errors="coerce").dropna()
        if len(close) < 2 or float(close.iloc[0]) <= 0:
            return 0.0, 0.0
        returns = close.pct_change(fill_method=None).dropna()
        return float(close.iloc[-1] / close.iloc[0] - 1.0), float(returns.std(ddof=0))

    def _build_return_pivot(self) -> pd.DataFrame:
        """Precompute close-return matrix once so daily covariance avoids full-table scans."""
        close_col = "close_nominal" if "close_nominal" in self.features.columns else "close"
        if close_col not in self.features.columns:
            return pd.DataFrame()
        source = self.features[["date", "symbol", close_col]].copy()
        source["date"] = pd.to_datetime(source["date"], errors="coerce")
        source["symbol"] = source["symbol"].astype(str)
        source[close_col] = pd.to_numeric(source[close_col], errors="coerce")
        source = source.dropna(subset=["date", "symbol", close_col])
        if source.empty:
            return pd.DataFrame()
        close_pivot = source.pivot_table(index="date", columns="symbol", values=close_col, aggfunc="last").sort_index()
        return close_pivot.pct_change(fill_method=None).dropna(how="all")

    def _rolling_candidate_covariance(self, date, candidates: pd.DataFrame, *, lookback_days: int = 60) -> pd.DataFrame:
        if candidates is None or candidates.empty or "symbol" not in candidates.columns:
            return pd.DataFrame()
        symbols = candidates["symbol"].astype(str).drop_duplicates().head(80).tolist()
        if len(symbols) < 2:
            return pd.DataFrame()
        if self._return_pivot.empty:
            return pd.DataFrame()
        available_symbols = [symbol for symbol in symbols if symbol in self._return_pivot.columns]
        if len(available_symbols) < 2:
            return pd.DataFrame()
        returns = self._return_pivot.loc[
            self._return_pivot.index < pd.Timestamp(date),
            available_symbols,
        ].tail(int(lookback_days))
        if returns.empty:
            return pd.DataFrame()
        minimum_observations = max(int(min(int(lookback_days), len(returns)) * 0.80), 10)
        returns = returns.dropna(axis=1, thresh=minimum_observations).dropna(how="all")
        if returns.shape[1] < 2:
            return pd.DataFrame()
        # Mean imputation occurs at the return-observation layer after an 80%
        # coverage gate. Unknown covariance pairs are never converted to zero.
        complete_returns = returns.apply(
            lambda series: series.fillna(series.mean()),
            axis=0,
        ).dropna(axis=1, how="any")
        if complete_returns.shape[1] < 2 or len(complete_returns) < 10:
            return pd.DataFrame()
        covariance = complete_returns.cov(ddof=1)
        if covariance.empty:
            return covariance
        if covariance.isna().any().any():
            return pd.DataFrame()
        # Dimension/sample adaptive diagonal shrinkage stabilizes the estimate
        # without claiming unknown pairs have zero covariance.
        dimension = int(covariance.shape[0])
        observations = int(len(complete_returns))
        shrinkage = min(max(dimension / max(observations - 1, 1), 0.10), 0.90)
        diagonal = pd.DataFrame(
            0.0,
            index=covariance.index,
            columns=covariance.columns,
        )
        for symbol in covariance.index.intersection(covariance.columns):
            diagonal.at[symbol, symbol] = covariance.at[symbol, symbol]
        shrunk = (
            (1.0 - shrinkage) * covariance
            + shrinkage * diagonal
        )
        shrunk = (shrunk + shrunk.T) / 2.0
        shrunk.attrs.update(
            {
                "estimator": "adaptive_diagonal_shrinkage",
                "shrinkage_intensity": float(shrinkage),
                "lookback_observations": observations,
                "candidate_symbol_count": len(symbols),
                "covered_symbol_count": dimension,
                "candidate_coverage_ratio": dimension / max(len(symbols), 1),
                "pair_coverage_ratio": 1.0,
            }
        )
        return shrunk

    def _rolling_candidate_return_scenarios(
        self,
        date,
        candidates: pd.DataFrame,
        *,
        current_symbols=(),
        lookback_days: int = 252,
        horizon_days: int = 10,
    ) -> pd.DataFrame:
        """Build synchronized, pre-decision multi-name return scenarios.

        Rolling horizons intentionally preserve same-date cross-sectional
        dependence. Missing values remain missing so the portfolio evaluator
        can fail over to an explicitly named conservative proxy instead of
        manufacturing zero correlation or zero loss.
        """
        if self._return_pivot.empty:
            return pd.DataFrame()
        candidate_symbols = (
            candidates["symbol"].astype(str).drop_duplicates().head(80).tolist()
            if candidates is not None and not candidates.empty and "symbol" in candidates.columns
            else []
        )
        symbols = list(dict.fromkeys([*map(str, current_symbols), *candidate_symbols]))
        available = [symbol for symbol in symbols if symbol in self._return_pivot.columns]
        horizon = max(int(horizon_days), 1)
        if not available:
            return pd.DataFrame()
        daily = self._return_pivot.loc[
            self._return_pivot.index < pd.Timestamp(date), available
        ].tail(max(int(lookback_days) + horizon - 1, horizon))
        if len(daily) < horizon:
            return pd.DataFrame()
        scenarios = (1.0 + daily).rolling(horizon, min_periods=horizon).apply(
            lambda values: float(values.prod()), raw=True
        ) - 1.0
        scenarios = scenarios.tail(int(lookback_days)).dropna(how="all")
        scenarios.attrs.update(
            {
                "scenario_method": "overlapping_synchronized_horizon_returns",
                "horizon_sessions": horizon,
                "decision_cutoff_exclusive": pd.Timestamp(date).strftime("%Y-%m-%d"),
            }
        )
        return scenarios

    def _latest_price_frame_for_trade_pairing(self, execution_ledger: pd.DataFrame) -> pd.DataFrame:
        return latest_price_frame_for_trade_pairing_runtime(self, execution_ledger)

    def _high_exposure_research_gate(self, date) -> dict:
        trade_summary = self._rolling_trade_pair_summary(date)
        closed_trade_count = int(trade_summary.get("realized_trade_count", 0) or 0)
        closed_trade_win_rate = _safe_float(trade_summary.get("closed_trade_win_rate"), default=float("nan"))
        profit_factor = _safe_float(trade_summary.get("profit_factor"), default=float("nan"))
        payoff_ratio = _safe_float(trade_summary.get("payoff_ratio"), default=float("nan"))
        realized_pnl = _safe_float(trade_summary.get("realized_pnl"), default=0.0)

        latest = self.exposure_rows[-1] if self.exposure_rows else {}
        latest_top1_risk = _safe_float(latest.get("max_risk_contribution"), default=0.0)
        latest_top5_risk = _safe_float(latest.get("top5_risk_contribution_sum"), default=0.0)
        latest_top20pct_risk = _safe_float(
            latest.get("top20pct_risk_contribution_sum"), default=0.0
        )
        latest_risk_effective_n_ratio = _safe_float(
            latest.get("risk_effective_n_ratio"), default=1.0
        )
        latest_risk_symbol_count = int(_safe_float(latest.get("risk_symbol_count"), default=0.0))
        actual_target_ratio = _recent_actual_target_ratio(self.exposure_rows)

        reasons = []
        if closed_trade_count < int(GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_TRADES):
            reasons.append("insufficient_closed_trades")
        if not (pd.notna(profit_factor) and profit_factor >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_PROFIT_FACTOR)):
            reasons.append("profit_factor_below_threshold")
        if realized_pnl <= float(GOVERNANCE_HIGH_EXPOSURE_MIN_REALIZED_PNL):
            reasons.append("realized_pnl_not_positive")
        # Win rate and payoff ratio are diagnostics only for the small-capital
        # branch. They must not jointly or alternatively veto profitable
        # deployment after the profit-factor and realized-PnL health gates.
        if latest_top1_risk > float(GOVERNANCE_HIGH_EXPOSURE_MAX_TOP1_RISK_CONTRIBUTION):
            reasons.append("top1_risk_contribution_above_threshold")

        tracking_ok = pd.notna(actual_target_ratio) and actual_target_ratio >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_ACTUAL_TARGET_RATIO)
        if not tracking_ok:
            reasons.append("actual_target_tracking_low_ramp_only")

        hard_reasons = [reason for reason in reasons if reason != "actual_target_tracking_low_ramp_only"]
        gate_pass = not hard_reasons
        return {
            "gate_pass": bool(gate_pass),
            "gate_reason": "passed" if not reasons else "|".join(reasons),
            "closed_trade_count": closed_trade_count,
            "closed_trade_win_rate": closed_trade_win_rate,
            "profit_factor": profit_factor,
            "payoff_ratio": payoff_ratio,
            "realized_pnl": realized_pnl,
            "actual_target_ratio": actual_target_ratio,
            "latest_top1_risk_contribution": latest_top1_risk,
            "latest_top5_risk_contribution_sum": latest_top5_risk,
            "latest_top20pct_risk_contribution_sum": latest_top20pct_risk,
            "latest_risk_effective_n_ratio": latest_risk_effective_n_ratio,
            "latest_risk_symbol_count": latest_risk_symbol_count,
        }

    def _rolling_trade_pair_summary(self, date) -> dict:
        if not self.execution_rows:
            return {}
        ledger = pd.DataFrame(self.execution_rows)
        if ledger.empty or "trade_date" not in ledger.columns:
            return {}
        ledger["trade_date"] = pd.to_datetime(ledger["trade_date"], errors="coerce")
        cutoff = pd.Timestamp(date)
        ledger = ledger[ledger["trade_date"].notna() & (ledger["trade_date"] < cutoff)].copy()
        if ledger.empty:
            return {}
        _, _, summary = build_trade_pairing_ledgers(
            ledger,
            latest_prices=None,
            capital_profile=self._trade_pairing_capital_profile(),
        )
        return summary

    def _log_save_stage(self, stage: str, **details) -> None:
        detail_text = ", ".join(f"{key}={value}" for key, value in details.items())
        suffix = f" | {detail_text}" if detail_text else ""
        # A console can disappear while a long Windows backtest continues
        # (for example when an orchestration wait times out).  Progress output
        # is not part of the financial state and may never abort persistence.
        try:
            print(f"[governance] save_stage: {stage}{suffix}", flush=True)
        except (BrokenPipeError, OSError, ValueError):
            pass
        from functions.decision_council.artifact_manifest import (
            update_artifact_manifest,
        )

        update_artifact_manifest(
            self.output_dir,
            stage=str(stage),
            status=("complete" if str(stage) == "complete" else "saving"),
            core_complete=(True if str(stage) == "complete" else None),
            audit_complete=(True if str(stage) == "complete" else None),
            web_complete=(True if str(stage) == "complete" else None),
        )

    def _save(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._log_save_stage("engine_ledgers")
        if self.exposure_rows and not bool(
            getattr(self, "_terminal_pending_snapshot_recorded", False)
        ):
            self.engine.record_terminal_pending_order_snapshot(
                self.exposure_rows[-1]["date"]
            )
            self._terminal_pending_snapshot_recorded = True
        saved = self.engine.save(self.output_dir)
        from functions.decision_council.artifact_manifest import (
            update_artifact_manifest,
        )
        update_artifact_manifest(
            self.output_dir,
            stage="core_ledgers_saved",
            status="saving",
            core_complete=True,
        )
        self._log_save_stage("build_extra_frames")
        daily_result = pd.DataFrame(self.exposure_rows)
        reward_prices = self.audit_prices.copy()
        performance_benchmark_symbol = "__TOP_POOL_PERFORMANCE_BENCHMARK__"
        if not getattr(self, "_performance_benchmark_frame", pd.DataFrame()).empty:
            benchmark_columns = ["date", "benchmark_net_value"]
            if "benchmark_return_valid" in self._performance_benchmark_frame.columns:
                benchmark_columns.append("benchmark_return_valid")
            benchmark_prices = self._performance_benchmark_frame[benchmark_columns].rename(
                columns={"benchmark_net_value": "close"}
            )
            benchmark_prices["symbol"] = performance_benchmark_symbol
            benchmark_prices["counterfactual_price_valid"] = benchmark_prices.get(
                "benchmark_return_valid",
                pd.Series(True, index=benchmark_prices.index),
            ).fillna(False).astype(bool)
            reward_prices["counterfactual_price_valid"] = True
            reward_prices = pd.concat(
                [reward_prices, benchmark_prices[["date", "symbol", "close", "counterfactual_price_valid"]]],
                ignore_index=True,
            )
        performance_benchmark_output = getattr(self, "_performance_benchmark_frame", pd.DataFrame()).copy()
        if not performance_benchmark_output.empty:
            benchmark_dates = pd.to_datetime(performance_benchmark_output["date"], errors="coerce").dt.normalize()
            performance_benchmark_output["benchmark_scope"] = "decision"
            if self._run_decision_start is not None:
                performance_benchmark_output.loc[benchmark_dates < self._run_decision_start, "benchmark_scope"] = "preload"
            if self._run_decision_end is not None:
                performance_benchmark_output.loc[benchmark_dates > self._run_decision_end, "benchmark_scope"] = "forward_audit"
        action_counterfactual = mature_action_rewards(
            pd.DataFrame(self.action_decision_rows),
            reward_prices,
            benchmark_symbol=performance_benchmark_symbol,
            executions=pd.DataFrame(self.execution_rows),
        )
        extra = {
            "governance_daily_result": daily_result,
            "governance_holdings_ledger": _frame_with_columns(self.holdings_rows, HOLDINGS_LEDGER_COLUMNS),
            "governance_execution_ledger": _frame_with_columns(self.execution_rows, EXECUTION_LEDGER_COLUMNS),
            "governance_reward_ledger": _frame_with_columns(
                self.reward_rows,
                ["date", "symbol", "side", "trade_date", "reward_5d", "reward_source"],
            ),
            "governance_action_decision_ledger": pd.DataFrame(self.action_decision_rows),
            "governance_action_proposal_ledger": pd.DataFrame(
                self.action_proposal_rows
            ),
            "governance_action_plan_ledger": pd.DataFrame(
                self.action_plan_rows
            ),
            "governance_action_counterfactual_reward": action_counterfactual,
            "governance_exit_counterfactual_summary": summarize_exit_counterfactual_rewards(
                action_counterfactual
            ),
            "governance_performance_benchmark": performance_benchmark_output,
            "governance_performance_benchmark_sensitivity": build_top_pool_benchmark_sensitivity(
                self._performance_benchmark_source(),
                top_n_values=(50, 100, 300),
                rebalance=self.performance_benchmark_rebalance,
                evaluation_start=self._run_decision_start,
                evaluation_end=self._run_decision_end,
            ),
            "governance_entry_confirmation_ledger": pd.DataFrame(self.entry_confirmation_rows),
            "governance_position_state_ledger": _frame_with_columns(
                self.position_state_rows,
                POSITION_STATE_LEDGER_COLUMNS,
            ),
            "governance_retail_execution_diagnostics": pd.DataFrame(
                self.retail_execution_rows,
                columns=[
                    "decision_id",
                    "execution_date",
                    "symbol",
                    "side",
                    "strategy_target_weight",
                    "strategy_target_notional",
                    "adjusted_target_notional",
                    "price",
                    "one_lot_cost",
                    "one_lot_cash_required",
                    "target_shares",
                    "available_cash",
                    "cash_buffer_required",
                    "single_position_weight_after",
                    "lot_upgrade_ratio",
                    "retail_one_lot_position_cap",
                    "retail_min_entry_matrix_score",
                    "position_state",
                    "entry_matrix_score",
                    "entry_alpha_score",
                    "entry_timing_score",
                    "entry_liquidity_score",
                    "alpha_quality_score",
                    "surge_capture_score",
                    "follow_through_score",
                    "exhaustion_score",
                    "entry_success_probability",
                    "entry_size_tier",
                    "planned_entry_lots",
                    "empirical_distribution_score",
                    "final_entry_score",
                    "tail_risk_proxy",
                    "trend_direction_score",
                    "peak_decay_score",
                    "profit_protection_pressure",
                    "dynamic_giveback_limit",
                    "future_loss_risk_score",
                    "downtrend_decay_score",
                    "post_entry_failure_score",
                    "strategy_logic_version",
                    "cabinet_native_final_score",
                    "v31_reliability_score",
                    "v31_reliability_score_coverage",
                    "v31_reliability_contract",
                    "v31_calibration_window",
                    "v31_score_formula",
                    "v31_score_authority",
                    "v31_strict_entry_paper_only",
                    "monthly_lgbm_raw_score",
                    "monthly_lgbm_rank_percentile",
                    "hybrid_final_score",
                    "hybrid_ml_weight",
                    "hybrid_fusion_status",
                    "cabinet_base_entry_score",
                    "cabinet_strict_entry_score",
                    "cabinet_proxy_entry_score",
                    "cabinet_timing_score",
                    "cabinet_liquidity_health_score",
                    "cabinet_risk_safety_score",
                    "cabinet_hold_support_score",
                    "cabinet_entry_thesis",
                    "cabinet_entry_thesis_support",
                    "mainline_v3_one_lot_cash_required",
                    "mainline_v3_one_lot_weight",
                    "mainline_v3_lot_feasible",
                    "retail_action",
                    "retail_block_reason",
                    "capital_profile",
                ],
            ),
            "governance_entry_formula_audit": pd.DataFrame(self.entry_formula_audit_rows),
            "governance_candidate_gate_audit": self._load_candidate_gate_audit(),
            "governance_candidate_gate_partition_index": self._candidate_gate_partition_index(),
            "governance_retail_executable_rank": pd.DataFrame(self.retail_executable_rank_rows),
            "governance_defensive_sleeve_diagnostics": pd.DataFrame(self.defensive_sleeve_rows),
            "governance_factor_weight_ledger": pd.DataFrame(self.factor_weight_rows),
            "governance_factor_source_report": pd.DataFrame([self.factor_source_spec.summary_dict()]),
            "governance_monthly_lgbm_fusion_audit": pd.DataFrame(self.monthly_lgbm_fusion_rows),
            "governance_monthly_lgbm_training_audit": (
                self.monthly_lgbm_controller.training_attempt_frame()
                if self.monthly_lgbm_controller is not None else pd.DataFrame()
            ),
            "governance_monthly_lgbm_feature_diagnostics": (
                self.monthly_lgbm_controller.feature_diagnostic_frame()
                if self.monthly_lgbm_controller is not None else pd.DataFrame()
            ),
            "governance_monthly_lgbm_iteration_metrics": (
                self.monthly_lgbm_controller.iteration_metric_frame()
                if self.monthly_lgbm_controller is not None else pd.DataFrame()
            ),
            "governance_monthly_lgbm_nested_candidates": (
                self.monthly_lgbm_controller.nested_candidate_frame()
                if self.monthly_lgbm_controller is not None else pd.DataFrame()
            ),
            "governance_monthly_lgbm_treatment_candidates": (
                self.monthly_lgbm_controller.treatment_candidate_frame()
                if self.monthly_lgbm_controller is not None else pd.DataFrame()
            ),
            "governance_monthly_lgbm_treatment_daily": (
                self.monthly_lgbm_controller.treatment_daily_frame()
                if self.monthly_lgbm_controller is not None else pd.DataFrame()
            ),
            "governance_monthly_lgbm_treatment_effect": (
                self.monthly_lgbm_controller.treatment_effect_frame(self.features)
                if self.monthly_lgbm_controller is not None else pd.DataFrame()
            ),
            "governance_v31_rolling_reliability_audit": (
                self.role_reliability_controller.audit_frame()
                if self.role_reliability_controller is not None else pd.DataFrame()
            ),
            "governance_factor_semantic_contract": pd.DataFrame(
                semantic_contract_rows(self.factor_semantic_contracts)
            ),
            "governance_alpha_proposals": pd.concat(self.alpha_rows, ignore_index=True) if self.alpha_rows else pd.DataFrame(),
            "governance_alpha_collapse_exit_diagnostics": pd.DataFrame(self.alpha_collapse_exit_rows),
            "governance_account_audit_ledger": pd.DataFrame(self.account_audit_rows),
            "governance_corporate_action_ledger": self.corporate_actions.audit_frame(),
        }
        if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}:
            from functions.decision_council.small_capital_aggressive import (
                build_scap_exit_stage_contract,
            )

            extra["scap_exit_stage_contract"] = build_scap_exit_stage_contract(
                self.capital_profile.get("scap_exit_stage", "E0"),
                active_replacement_enabled=bool(
                    self.capital_profile.get("active_replacement_enabled", False)
                ),
                loser_averaging_enabled=bool(
                    self.capital_profile.get(
                        "scap_loser_averaging_enabled", False
                    )
                ),
                winner_pyramiding_enabled=bool(
                    self.capital_profile.get(
                        "scap_winner_pyramiding_enabled", False
                    )
                ),
            )
        maturity_columns = [
            column
            for column in (
                "date",
                "strategy_logic_version",
                "calibration_runtime_state",
                "reputation_runtime_state",
                "covariance_runtime_state",
                "trade_accuracy_runtime_state",
                "pit_runtime_state",
                "runtime_maturity_state",
            )
            if column in daily_result.columns
        ]
        extra["governance_runtime_maturity"] = daily_result.loc[:, maturity_columns].copy()
        cabinet_mapping = build_cabinet_module_mapping(self.factor_source_spec)
        extra["governance_factor_cabinet_module_mapping"] = cabinet_mapping
        extra["governance_factor_cabinet_experiment_contracts"] = build_cabinet_experiment_contracts(cabinet_mapping)
        self._log_save_stage("trade_pairing")
        trade_pairs, open_positions, trade_summary = build_trade_pairing_ledgers(
            extra["governance_execution_ledger"],
            latest_prices=self._latest_price_frame_for_trade_pairing(extra["governance_execution_ledger"]),
            capital_profile=self._trade_pairing_capital_profile(),
            corporate_action_ledger=extra["governance_corporate_action_ledger"],
        )
        extra["governance_trade_pairs"] = trade_pairs
        extra["governance_open_positions"] = open_positions
        extra["governance_trade_pair_summary"] = pd.DataFrame([trade_summary])
        extra["governance_ideal_vs_executed"] = _ideal_vs_executed(
            extra["governance_entry_formula_audit"],
            extra["governance_execution_ledger"],
        )
        extra["governance_entry_timing_diagnostics"] = _entry_timing_diagnostics(
            extra["governance_entry_formula_audit"],
            extra["governance_execution_ledger"],
        )
        from functions.decision_council.scap_profit_objective import (
            build_scap_profit_objective_audit,
            summarize_scap_profit_objective,
        )

        profit_objective_audit = build_scap_profit_objective_audit(
            extra["governance_entry_formula_audit"]
        )
        # Keep filenames short enough for legacy Windows MAX_PATH consumers.
        extra["scap_profit_audit"] = profit_objective_audit
        extra["scap_profit_summary"] = (
            summarize_scap_profit_objective(profit_objective_audit)
        )
        extra["governance_pnl_by_sell_reason"] = _pnl_by_sell_reason(trade_pairs)
        rejection_detail = build_candidate_rejection_detail(extra["governance_entry_formula_audit"])
        funnel_daily = reconcile_funnel_daily(
            pd.DataFrame(self.candidate_funnel_rows),
            ideal_plan=self.engine.ledgers.frame("ideal_portfolio_plan"),
            order_plan=self.engine.ledgers.frame("executable_order_plan"),
            execution_ledger=extra["governance_execution_ledger"],
        )
        extra["governance_candidate_rejection_detail"] = rejection_detail
        extra["governance_candidate_funnel_daily"] = funnel_daily
        extra["governance_candidate_funnel_summary"] = summarize_funnel(funnel_daily)
        extra["governance_control_opportunity_cost"] = build_control_opportunity_cost(rejection_detail)
        from functions.decision_council.candidate_funnel_audit import build_entry_gate_summary_from_csv_parts
        extra["governance_entry_gate_summary"] = build_entry_gate_summary_from_csv_parts(
            self._candidate_gate_part_paths()
        )
        extra["governance_control_trigger_summary"] = build_control_trigger_summary_from_csv_parts(
            self._candidate_gate_part_paths(),
            order_plan=self.engine.ledgers.frame("executable_order_plan"),
            execution_ledger=extra["governance_execution_ledger"],
        )
        extra["governance_exposure_reconciliation"] = build_exposure_reconciliation(
            extra["governance_daily_result"]
        )
        extra["governance_runtime_integrity_audit"] = build_runtime_integrity_audit(
            execution_ledger=extra["governance_execution_ledger"],
            account_audit=extra["governance_account_audit_ledger"],
            daily_result=extra["governance_daily_result"],
            holdings_ledger=extra["governance_holdings_ledger"],
            position_state_ledger=extra["governance_position_state_ledger"],
            max_positions=self._user_hard_position_cap,
            action_proposal_ledger=extra[
                "governance_action_proposal_ledger"
            ],
            action_plan_ledger=extra["governance_action_plan_ledger"],
            order_plan_ledger=self.engine.ledgers.frame(
                "executable_order_plan"
            ),
        )
        if self.governance_variant == "governance_layer_validation":
            self._log_save_stage("layer_validation_audit")
            from functions.decision_council.layer_validation_audit import build_layer_validation_reports

            extra.update(
                build_layer_validation_reports(
                    self._candidate_gate_part_paths(),
                    close_history_getter=self._audit_close_history,
                    execution_ledger=extra["governance_execution_ledger"],
                    trade_pairs=trade_pairs,
                )
            )
            from functions.decision_council.failure_lab import (
                ROLE_SCORE_COLUMNS,
                build_failure_lab_overview,
                build_negative_control_permutation_report,
                build_paired_layer_increment_reports,
                build_role_marginal_regression_reports,
            )

            layer_failure_reports = build_paired_layer_increment_reports(
                extra["governance_layer_validation_daily"]
            )
            role_failure_reports = build_role_marginal_regression_reports(
                extra["governance_layer_validation_candidate_detail"]
            )
            negative_control_reports = build_negative_control_permutation_report(
                extra["governance_layer_validation_candidate_detail"]
            )
            extra.update(layer_failure_reports)
            extra.update(role_failure_reports)
            extra.update(negative_control_reports)
            from functions.decision_council.survival_audit import build_candidate_competing_risk_reports
            survival_reports = build_candidate_competing_risk_reports(
                extra["governance_layer_validation_candidate_detail"],
                close_history_getter=self._audit_close_history,
                feature_columns=ROLE_SCORE_COLUMNS,
                entry_mask_column="l1_current_role_confirmation",
                horizon_days=20,
                profit_barrier=GOVERNANCE_PROFIT_PROTECT_TRIGGER_1,
                loss_barrier=GOVERNANCE_HARD_STOP_LOSS,
                bootstrap_samples=500,
            )
            extra.update(survival_reports)
            from functions.decision_council.drift_audit import build_adversarial_drift_reports
            candidate_detail = extra["governance_layer_validation_candidate_detail"]
            candidate_dates = pd.Index(sorted(pd.to_datetime(candidate_detail["signal_date"], errors="coerce").dropna().unique()))
            split = max(1, int(len(candidate_dates) * .70))
            early_dates, late_dates = set(candidate_dates[:split]), set(candidate_dates[split:])
            early = candidate_detail[pd.to_datetime(candidate_detail["signal_date"], errors="coerce").isin(early_dates)]
            late = candidate_detail[pd.to_datetime(candidate_detail["signal_date"], errors="coerce").isin(late_dates)]
            drift_reports = build_adversarial_drift_reports(
                early, late, feature_columns=ROLE_SCORE_COLUMNS,
                group_column="symbol", permutation_samples=300, minimum_domain_rows=100,
            )
            extra.update(drift_reports)
            extra["governance_failure_lab_overview"] = build_failure_lab_overview(
                layer_increment=layer_failure_reports["governance_failure_lab_layer_increment"],
                role_marginal_summary=role_failure_reports["governance_failure_lab_role_marginal_summary"],
                negative_control_audit=negative_control_reports["governance_failure_lab_negative_control_audit"],
            )
        from functions.decision_council.cost_capacity_audit import build_cost_capacity_stress_reports
        extra.update(build_cost_capacity_stress_reports(
            trade_pairs,
            extra["governance_execution_ledger"],
            impact_sqrt_coefficient=GOVERNANCE_IMPACT_SQRT_COEFFICIENT,
            impact_max_rate=GOVERNANCE_IMPACT_MAX_RATE,
        ))
        if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}:
            from functions.decision_council.scap_cost_stress import build_scap_cost_stress_report
            extra["governance_scap_cost_stress_report"] = build_scap_cost_stress_report(
                trade_pairs,
                extra["governance_execution_ledger"],
                initial_cash=self.initial_cash,
            )
        requires_monthly_ml = self.strategy_logic_version == MAINLINE_V3_MONTHLY_LGBM_HYBRID
        if self.monthly_lgbm_controller is not None:
            from functions.decision_council.ml_stability_audit import build_monthly_lgbm_stability_reports
            extra.update(build_monthly_lgbm_stability_reports(
                extra["governance_monthly_lgbm_training_audit"],
                extra["governance_monthly_lgbm_feature_diagnostics"],
            ))
        elif requires_monthly_ml:
            from functions.decision_council.ml_stability_audit import build_insufficient_ml_stability_reports
            extra.update(build_insufficient_ml_stability_reports(
                "externally supplied artifact has no cross-month online training history"
            ))
        from functions.decision_council.overfit_audit import build_insufficient_overfit_reports
        extra.update(build_insufficient_overfit_reports(
            "matched v1/v2/v3 daily return matrix must be supplied by the fixed comparison runner"
        ))
        from functions.decision_council.research_gate import build_unified_research_gate
        gate_detail, gate_summary = build_unified_research_gate(
            extra,
            pit_runtime_state=self.pit_runtime_state,
            requires_monthly_ml=requires_monthly_ml,
            pit_level2_runtime_state=self.pit_level2_runtime_state,
            temporal_isolation_pass=self.factor_temporal_isolation_pass,
        )
        extra["governance_unified_research_gate"] = gate_detail
        extra["governance_unified_research_gate_summary"] = gate_summary
        self._log_save_stage("future_loss_duration_audit", trades=len(trade_pairs))
        extra["governance_future_loss_duration_audit"] = _future_loss_duration_audit(
            trade_pairs,
            self.features,
            horizon_days=40,
        )
        self._log_save_stage("control_avoided_loss")
        extra["governance_control_avoided_loss_ledger"] = _control_avoided_loss_ledger(
            extra["governance_execution_ledger"],
            self.features,
        )
        extra["governance_control_avoided_loss_summary"] = _control_avoided_loss_summary_frame(
            extra["governance_control_avoided_loss_ledger"]
        )
        if is_mainline_v3_version(self.strategy_logic_version):
            from functions.decision_council.cabinet_thesis_audit import build_cabinet_thesis_counterfactual
            from functions.decision_council.factor_ic_transfer_audit import build_factor_ic_transfer_audit

            extra["governance_cabinet_thesis_counterfactual"] = build_cabinet_thesis_counterfactual(
                extra["governance_position_state_ledger"],
                self.audit_prices,
            )
            extra["governance_factor_ic_transfer_audit"] = build_factor_ic_transfer_audit(
                extra["governance_alpha_proposals"],
                self.audit_prices,
                factor_source_spec=self.factor_source_spec,
                candidate_universe=extra.get("governance_layer_validation_candidate_detail"),
            )
        self._log_save_stage("attribution")
        extra["governance_attribution_ledger"] = build_governance_attribution(
            daily_result=extra["governance_daily_result"],
            feature_data=self.features,
            benchmark_symbol=self.engine.safety_agent.proxy_symbol,
            factor_weight_ledger=extra["governance_factor_weight_ledger"],
            benchmark_top_n=self.performance_benchmark_top_n,
            benchmark_rebalance=self.performance_benchmark_rebalance,
        )
        extra["governance_bucket_attribution"] = build_bucket_attribution(extra["governance_attribution_ledger"])
        self._log_save_stage("quality_reports")
        quality_reports = build_governance_quality_reports(
            ideal_portfolio_plan=self.engine.ledgers.frame("ideal_portfolio_plan"),
            executable_order_plan=self.engine.ledgers.frame("executable_order_plan"),
            execution_ledger=extra["governance_execution_ledger"],
            alpha_proposals=extra["governance_alpha_proposals"],
            feature_data=self.features,
            benchmark_symbol=self.engine.safety_agent.proxy_symbol,
            daily_result=extra["governance_daily_result"],
            attribution_ledger=extra["governance_attribution_ledger"],
            return_pivot=self._return_pivot,
            runtime_context=self.factor_runtime_context,
            benchmark_top_n=self.performance_benchmark_top_n,
            benchmark_rebalance=self.performance_benchmark_rebalance,
        )
        extra.update(quality_reports)
        monitoring_input = extra["governance_daily_result"].merge(
            extra["governance_account_audit_ledger"][["date", "reconciliation_error"]],
            on="date",
            how="left",
        )
        extra["governance_rollback_recommendation_ledger"] = evaluate_daily_rollback(
            monitoring_input,
            safety_ledger=self.engine.ledgers.frame("safety_decision_ledger"),
        )
        self._log_save_stage("write_extra_csv", frames=len(extra))
        for name, frame in extra.items():
            path = self.output_dir / f"{name}.csv"
            saved[name] = write_governance_csv(frame, path)
        update_artifact_manifest(
            self.output_dir,
            stage="audit_csv_saved",
            status="saving",
            audit_complete=True,
        )
        self._log_save_stage("summary_report")
        governance_summary = self._build_governance_summary(
            daily_result=extra["governance_daily_result"],
            execution_ledger=extra["governance_execution_ledger"],
            safety_ledger=self.engine.ledgers.frame("safety_decision_ledger"),
            constraint_ledger=self.engine.ledgers.frame("constraint_allocation_ledger"),
            attribution_ledger=extra["governance_attribution_ledger"],
            bucket_attribution=extra["governance_bucket_attribution"],
            quality_reports=quality_reports,
            trade_pair_summary=extra["governance_trade_pair_summary"],
            pnl_by_sell_reason=extra["governance_pnl_by_sell_reason"],
            control_avoided_loss_summary=extra["governance_control_avoided_loss_summary"],
        )
        summary_path = (
            GOVERNANCE_SUMMARY_CSV
            if self.output_dir.resolve() == Path(GOVERNANCE_OUTPUT_DIR).resolve()
            else self.output_dir / "governance_strategy_summary.csv"
        )
        saved["governance_strategy_summary"] = write_governance_csv(governance_summary, summary_path)
        if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}:
            from functions.decision_council.scap_admission import build_scap_admission_report
            scap_admission = build_scap_admission_report(
                governance_summary=governance_summary,
                cost_stress=extra["governance_scap_cost_stress_report"],
                daily_result=extra["governance_daily_result"],
                holdings_ledger=extra["governance_holdings_ledger"],
                initial_cash=self.initial_cash,
                profit_factor_threshold=float(
                    self.capital_profile.get("scap_profit_factor_admission", 1.15) or 1.15
                ),
                structural_single_position_cap=float(
                    self.capital_profile.get("retail_single_position_cap", 0.40) or 0.40
                ),
            )
            saved["governance_scap_admission_report"] = write_governance_csv(
                scap_admission,
                self.output_dir / "governance_scap_admission_report.csv",
            )
        report_path = (
            GOVERNANCE_REPORT_MD
            if self.output_dir.resolve() == Path(GOVERNANCE_OUTPUT_DIR).resolve()
            else self.output_dir / "governance_strategy_report.md"
        )
        report_text = build_strategy_report(
            pd.DataFrame(),
            governance_summary_df=governance_summary,
            report_title="Governance Strategy Report",
            universe_name=self._universe_name,
            variant_name=self.governance_variant,
            alpha_bundle=self._alpha_bundle,
        )
        saved["governance_strategy_report"] = save_strategy_report(report_text, report_path)
        saved["factor_runtime_audit"] = save_factor_runtime_audit(self.factor_runtime_audit, self.output_dir)
        if self.factor_semantic_contracts:
            semantic_path = self.output_dir / "factor_semantic_contract_audit.json"
            saved["factor_semantic_contract_audit"] = write_governance_text(
                json.dumps(
                    {
                        **self.factor_semantic_contract_audit,
                        "strategy_logic_version": self.strategy_logic_version,
                        "factor_cabinet_run_id": self.factor_source_spec.factor_cabinet_run_id,
                        "factor_cabinet_hash": self.factor_source_spec.cabinet_manifest_hash,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                semantic_path,
                encoding="utf-8",
            )
        self._log_save_stage("shadow_diagnostics")
        shadow_diagnostics = build_shadow_factor_diagnostics(
            self.engine.ledgers.frame("shadow_portfolio_ledger"),
            reputation_ledger=self.engine.ledgers.frame("reputation_ledger"),
        )
        if not shadow_diagnostics.empty:
            shadow_csv_path = self.output_dir / "governance_shadow_factor_diagnostics.csv"
            shadow_md_path = self.output_dir / "governance_shadow_factor_diagnostics.md"
            write_governance_csv(shadow_diagnostics, shadow_csv_path)
            write_governance_text(
                render_shadow_factor_diagnostics_markdown(shadow_diagnostics),
                shadow_md_path,
                encoding="utf-8",
            )
            saved["governance_shadow_factor_diagnostics"] = shadow_csv_path
            saved["governance_shadow_factor_diagnostics_report"] = shadow_md_path
        self._log_save_stage("diagnostic_plots")
        saved.update(
            save_governance_diagnostic_plots(
                daily_result=extra["governance_daily_result"],
                holdings_ledger=extra["governance_holdings_ledger"],
                reputation_ledger=self.engine.ledgers.frame("reputation_ledger"),
                safety_ledger=self.engine.ledgers.frame("safety_decision_ledger"),
                execution_ledger=extra["governance_execution_ledger"],
                attribution_ledger=extra["governance_attribution_ledger"],
                bucket_attribution=extra["governance_bucket_attribution"],
                factor_weight_ledger=extra["governance_factor_weight_ledger"],
                ml_iteration_metrics=extra["governance_monthly_lgbm_iteration_metrics"],
                ml_treatment_effect=extra["governance_monthly_lgbm_treatment_effect"],
                role_reliability_audit=extra["governance_v31_rolling_reliability_audit"],
                feature_data=self.features,
                output_dir=self.output_dir,
            )
        )
        if self.governance_control_mode in {"aggressive_profit", "aggressive_lean"}:
            self._log_save_stage("holding_factor_products")
            from functions.decision_council.holding_factor_products import (
                FACTOR_PRODUCT_DIRNAME,
                FACTOR_WORKBOOK_NAME,
                build_integrated_products,
            )

            factor_product = build_integrated_products(
                self.output_dir,
                build_workbook=True,
                strict=True,
            )
            factor_product_dir = self.output_dir / FACTOR_PRODUCT_DIRNAME
            saved["holding_factor_product_status"] = (
                factor_product_dir / "product_status.json"
            )
            saved["holding_factor_scores_long"] = (
                factor_product_dir / "holding_factor_scores_long.csv"
            )
            if factor_product.get("workbook_status") == "ok":
                saved["holding_factor_workbook"] = (
                    factor_product_dir / FACTOR_WORKBOOK_NAME
                )
            update_artifact_manifest(
                self.output_dir,
                stage="holding_factor_products",
                status="saving",
                web_complete=bool(factor_product.get("workbook_status") == "ok"),
                artifact_name="holding_factor_products",
                artifact_status=str(factor_product.get("workbook_status", "unknown")),
            )
        self._log_save_stage("complete")
        return saved

    def _trade_pairing_capital_profile(self) -> str:
        return trade_pairing_capital_profile_runtime(self)

    def _build_governance_summary(
        self,
        *,
        daily_result,
        execution_ledger,
        safety_ledger,
        constraint_ledger,
        attribution_ledger=None,
        bucket_attribution=None,
        quality_reports=None,
        trade_pair_summary=None,
        pnl_by_sell_reason=None,
        control_avoided_loss_summary=None,
    ):
        return build_governance_summary_frame(
            self,
            daily_result=daily_result,
            execution_ledger=execution_ledger,
            safety_ledger=safety_ledger,
            constraint_ledger=constraint_ledger,
            attribution_ledger=attribution_ledger,
            bucket_attribution=bucket_attribution,
            quality_reports=quality_reports,
            trade_pair_summary=trade_pair_summary,
            pnl_by_sell_reason=pnl_by_sell_reason,
            control_avoided_loss_summary=control_avoided_loss_summary,
        )

    def _record_leakage_audit(self):
        feature_audit = audit_feature_columns(
            ["ret_20", "score_mom_lowvol", "close_to_ma20", "volatility_20"]
        )
        split_failures = validate_governance_split(20, 5)
        rows = [
            {
                "check": "phase_one_rule_alpha_feature_columns",
                "status": "passed" if feature_audit["is_clean"] else "failed",
                "detail": str(feature_audit),
            },
            {
                "check": "governance_training_split_minimum",
                "status": "passed" if not split_failures else "failed",
                "detail": "; ".join(split_failures),
            },
            {
                "check": "daily_decision_timestamp_rule",
                "status": "manual_review_required",
                "detail": "TDX daily features are consumed at t_close and orders execute no earlier than t_plus_1_open.",
            },
        ]
        self.engine.record_leakage_audit(pd.DataFrame(rows))


def run_governance_backtest(
    feature_path=FEATURE_DAILY_PARQUET,
    *,
    output_dir=GOVERNANCE_OUTPUT_DIR,
    safety_proxy_mode=SAFETY_PROXY_MODE,
    start_date=None,
    end_date=None,
    max_days=None,
    enable_sector_cap: bool = False,
    enable_safety_agent: bool = True,
    enable_market_regime_policy: bool = ENABLE_MARKET_REGIME_POLICY,
    enable_reputation: bool = True,
    governance_variant: str = "rules_based_president",
    universe_name: str | None = None,
    universe_mode: str = "index_pool_strict",
    alpha_bundle: str | None = None,
    entry_confirmation_mode: str = "full",
    policy_exit_mode: str = "full",
    selection_weight_mode: str = "reputation_weighted",
    regime_overlay_mode: str = "full",
    risk_hard_gate_enabled: bool = False,
    probability_bucket_mode: str | None = None,
    registry_version: str | None = None,
    target_index_codes: tuple[str, ...] = (),
    require_constituents: bool = True,
    allow_fallback: bool = False,
    allowed_instrument_types: tuple[str, ...] = GOVERNANCE_ALLOWED_INSTRUMENT_TYPES,
    enable_quality_filters: bool = True,
    enable_shadow_portfolios: bool = True,
    show_live_monitor: bool = False,
    initial_cash: float = GOVERNANCE_INITIAL_CASH,
    max_positions: int | None = None,
    capital_profile: dict | None = None,
    governance_control_mode: str = "normal",
    alpha_collapse_exit_enabled: bool = True,
    factor_source: str = FACTOR_SOURCE_LEGACY,
    factor_cabinet_run_id: str = "",
    factor_cabinet_path: str = "",
    strategy_logic_version: str = "production_v1",
    monthly_lgbm_maximum_weight: float | None = None,
    pit_mode: str = "research",
    performance_benchmark_top_n: int = GOVERNANCE_PERFORMANCE_BENCHMARK_TOP_N,
    performance_benchmark_rebalance: str = GOVERNANCE_PERFORMANCE_BENCHMARK_REBALANCE,
) -> dict[str, Path]:
    from functions.decision_council.policy import RulesBasedPresidentPolicy
    from functions.alpha_bundles import ALPHA_BUNDLE_REGISTRY

    # Deprecated compatibility only. Probability-bucket logic was removed from
    # the strategy path, but older interactive launchers/notebook state may still
    # pass this keyword after module reloads.
    _ = probability_bucket_mode
    if strategy_logic_version == MAINLINE_V3_MONTHLY_LGBM_HYBRID and monthly_lgbm_maximum_weight is None:
        raise ValueError(
            "mainline_v3_monthly_lgbm_hybrid requires a pre-registered monthly_lgbm_maximum_weight"
        )

    output_dir = Path(output_dir)
    if not output_dir.name.startswith("run"):
        output_dir = dated_run_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    from functions.data.pit_level1_store import run_pit_preflight

    pit_preflight = run_pit_preflight(
        mode=pit_mode,
        output_path=output_dir / "pit_runtime_audit.json",
    )
    from functions.data.pit_level2_store import run_pit_level2_preflight
    pit_level2_preflight = run_pit_level2_preflight(
        mode=pit_mode,
        output_path=output_dir / "pit_level2_runtime_audit.json",
    )

    effective_start = pd.Timestamp(start_date or GOVERNANCE_START_DATE) if (start_date or GOVERNANCE_START_DATE) else None
    effective_end = pd.Timestamp(end_date or GOVERNANCE_END_DATE) if (end_date or GOVERNANCE_END_DATE) else None
    portfolio_calendar_dates = pd.DatetimeIndex([])
    if effective_start is not None and effective_end is not None:
        from functions.data.trading_calendar import (
            bounded_observed_feature_end,
            first_observed_feature_session,
            observed_feature_sessions,
        )

        requested_effective_end = pd.Timestamp(effective_end)
        portfolio_calendar_dates = observed_feature_sessions(
            feature_path, effective_start, requested_effective_end
        )
        effective_end = bounded_observed_feature_end(
            feature_path,
            effective_start,
            requested_effective_end,
            max_days,
        )
        if require_constituents and not allow_fallback:
            from functions.investable_universe import validate_pit_membership_manifest_coverage

            membership_coverage = validate_pit_membership_manifest_coverage(
                start_date=first_observed_feature_session(feature_path, effective_start, effective_end),
                end_date=effective_end,
            )
            if membership_coverage["status"] != "pass":
                raise ValueError(
                    "PIT index membership does not cover the effective governance window: "
                    f"{membership_coverage}"
                )
    filters = []
    preload_calendar_days = governance_preload_calendar_days(governance_control_mode)
    if effective_start is not None:
        filters.append(
            ("date", ">=", effective_start - pd.Timedelta(days=preload_calendar_days))
        )
    if effective_end is not None:
        filters.append(("date", "<=", effective_end))
    if allowed_instrument_types:
        load_instrument_types = tuple(dict.fromkeys((*allowed_instrument_types, "etf_fund")))
        filters.append(("instrument_type", "in", list(load_instrument_types)))
    factor_spec = resolve_factor_source(
        factor_source=factor_source,
        factor_cabinet_run_id=factor_cabinet_run_id,
        factor_cabinet_path=factor_cabinet_path,
        alpha_bundle=alpha_bundle or LEGACY_GOVERNANCE_ALPHA_BUNDLE,
    )
    factor_runtime_audit = build_factor_runtime_audit(factor_spec, requested_factor_source=factor_source)
    print_factor_runtime_audit(factor_runtime_audit)
    if factor_spec.uses_factor_cabinet:
        alpha_models = factor_spec.alpha_models
        alpha_bundle = f"factor_cabinet_{factor_spec.factor_cabinet_run_id}"
    else:
        alpha_bundle = LEGACY_GOVERNANCE_ALPHA_BUNDLE
        alpha_models = tuple(ALPHA_BUNDLE_REGISTRY.get_alpha_model_names(alpha_bundle))
    temporal_pass = False
    if factor_spec.uses_factor_cabinet and effective_start is not None:
        from functions.research.temporal_contract import audit_artifact_lineage, write_temporal_audit
        temporal_evidence, temporal_summary = audit_artifact_lineage(
            factor_spec.factor_cabinet_path, oos_start=effective_start
        )
        write_temporal_audit(output_dir, temporal_evidence, temporal_summary)
        temporal_pass = bool(temporal_summary["temporal_isolation_pass"])
    try:
        import pyarrow.parquet as pq

        available_columns = set(pq.read_schema(feature_path).names)
    except Exception:
        available_columns = set(_governance_feature_columns())
    feature_map = dict(factor_spec.model_feature_map or {}) if factor_spec.uses_factor_cabinet else GOVERNANCE_ALPHA_MODEL_FEATURES
    generated_candidate_columns = {
        feature_map[name]
        for name in alpha_models
        if name in feature_map
        and feature_map[name].startswith("cand_")
        and feature_map[name] not in available_columns
    }
    load_columns = list(_governance_feature_columns()) + [
        feature_map[name] for name in alpha_models
        if name in feature_map and feature_map[name] not in generated_candidate_columns
    ]
    features = pd.read_parquet(
        feature_path,
        columns=[column for column in dict.fromkeys(load_columns) if column in available_columns],
        filters=filters or None,
    )
    if generated_candidate_columns:
        cache_start = (
            effective_start - pd.Timedelta(days=preload_calendar_days)
            if effective_start is not None
            else features["date"].min()
        )
        cache_end = effective_end if effective_end is not None else features["date"].max()
        if factor_spec.uses_factor_cabinet:
            cabinet_cache_start = (
                cache_start
                if _normalize_governance_control_mode(governance_control_mode)
                == "aggressive_lean"
                else (
                    effective_start
                    if effective_start is not None
                    else cache_start
                )
            )
            features = attach_factor_cabinet_feature_cache(
                features,
                spec=factor_spec,
                start_date=cabinet_cache_start,
                end_date=cache_end,
                feature_path=Path(feature_path),
            )
        else:
            features = attach_pre_screen_candidate_factor_cache(
                features,
                start_date=cache_start,
                end_date=cache_end,
                alpha_models=alpha_models,
                feature_path=Path(feature_path),
            )
        still_missing = sorted(generated_candidate_columns - set(features.columns))
        if still_missing:
            raise ValueError(f"Candidate factor cache did not provide required columns: {still_missing}")
    features = _prepare_features(features, copy=False)
    audit_prices = pd.DataFrame(columns=["date", "symbol", "close"])
    if effective_start is not None and effective_end is not None:
        from functions.decision_council.audit_price_history import load_audit_price_history

        audit_prices = load_audit_price_history(
            feature_path,
            decision_start=effective_start,
            decision_end=effective_end,
            horizon_days=20,
            allowed_instrument_types=allowed_instrument_types,
        )
    runner = GovernanceBacktestRunner(
        features,
        audit_price_df=audit_prices,
        initial_cash=float(initial_cash),
        output_dir=output_dir,
        alpha_models=alpha_models,
        safety_proxy_mode=safety_proxy_mode,
        data_fingerprints={"feature_daily_parquet": file_fingerprint(feature_path)},
        policy=RulesBasedPresidentPolicy(
            enable_sector_cap=enable_sector_cap,
            enable_safety_agent=enable_safety_agent,
            exit_mode=policy_exit_mode,
            risk_hard_gate_enabled=risk_hard_gate_enabled,
        ),
        prepared_features=True,
        enable_shadow_portfolios=enable_shadow_portfolios,
        enable_reputation=enable_reputation,
        governance_variant=governance_variant,
        enable_sector_cap=enable_sector_cap,
        enable_safety_agent=enable_safety_agent,
        enable_market_regime_policy=enable_market_regime_policy,
        entry_confirmation_mode=entry_confirmation_mode,
        selection_weight_mode=selection_weight_mode,
        regime_overlay_mode=regime_overlay_mode,
        risk_hard_gate_enabled=risk_hard_gate_enabled,
        governance_control_mode=governance_control_mode,
        alpha_collapse_exit_enabled=alpha_collapse_exit_enabled,
        universe_name=universe_name,
        universe_mode=universe_mode,
        alpha_bundle=alpha_bundle,
        registry_version=registry_version,
        target_index_codes=target_index_codes,
        require_constituents=require_constituents,
        allow_fallback=allow_fallback,
        allowed_instrument_types=allowed_instrument_types,
        enable_quality_filters=enable_quality_filters,
        max_positions=max_positions,
        capital_profile=capital_profile,
        factor_source_spec=factor_spec,
        strategy_logic_version=strategy_logic_version,
        monthly_lgbm_maximum_weight=monthly_lgbm_maximum_weight,
        pit_runtime_state=pit_preflight["pit_runtime_state"],
        pit_level2_runtime_state=pit_level2_preflight["pit_runtime_state"],
        factor_temporal_isolation_pass=temporal_pass,
        performance_benchmark_top_n=performance_benchmark_top_n,
        performance_benchmark_rebalance=performance_benchmark_rebalance,
        decision_start=effective_start,
        decision_end=effective_end,
        portfolio_calendar_dates=portfolio_calendar_dates,
    )
    return runner.run(
        start_date=effective_start,
        end_date=effective_end,
        max_days=max_days,
        show_live_monitor=show_live_monitor,
    )


def _contiguous_true_lengths(mask: pd.Series) -> list[int]:
    lengths: list[int] = []
    current = 0
    for value in mask.fillna(False).astype(bool).tolist():
        if value:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return lengths


def _safe_numeric_mean(values, default=0.0) -> float:
    series = pd.to_numeric(values if values is not None else pd.Series(dtype=float), errors="coerce").dropna()
    if series.empty:
        return float(default)
    return float(series.mean())


def _safe_last(values, default=0.0) -> float:
    series = pd.to_numeric(values if values is not None else pd.Series(dtype=float), errors="coerce").dropna()
    if series.empty:
        return float(default)
    return float(series.iloc[-1])


def _safe_numeric_max(values, default=0.0) -> float:
    series = pd.to_numeric(values if values is not None else pd.Series(dtype=float), errors="coerce").dropna()
    if series.empty:
        return float(default)
    return float(series.max())


def _risk_gate_max_contribution(risk_contribution: pd.DataFrame) -> float:
    if risk_contribution is None or risk_contribution.empty:
        return 0.0
    data = risk_contribution.copy()
    if "risk_gate_eligible" in data.columns:
        eligible = data["risk_gate_eligible"].fillna(False).astype(bool)
        if eligible.any():
            data = data[eligible].copy()
    metric_col = (
        "positive_risk_contribution_share"
        if "positive_risk_contribution_share" in data.columns
        else "risk_contribution_share"
    )
    return _safe_numeric_max(data.get(metric_col), default=0.0)


def _recent_actual_target_ratio(exposure_rows: list[dict], *, window: int = 20) -> float:
    if not exposure_rows:
        return pd.NA
    data = pd.DataFrame(exposure_rows).tail(int(window)).copy()
    if not {"actual_exposure", "target_exposure"}.issubset(data.columns):
        return pd.NA
    actual = pd.to_numeric(data["actual_exposure"], errors="coerce")
    target = pd.to_numeric(data["target_exposure"], errors="coerce")
    ratio = (actual / target.replace(0.0, pd.NA)).dropna()
    if ratio.empty:
        return pd.NA
    return float(ratio.median())


def _ideal_vs_executed(entry_audit: pd.DataFrame, execution_ledger: pd.DataFrame) -> pd.DataFrame:
    if entry_audit is None or entry_audit.empty:
        return pd.DataFrame()
    data = entry_audit.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    data["symbol"] = data.get("symbol", pd.Series("", index=data.index)).astype(str)
    buys = pd.DataFrame()
    if execution_ledger is not None and not execution_ledger.empty:
        buys = execution_ledger.copy()
        buys["trade_date"] = pd.to_datetime(buys.get("trade_date"), errors="coerce")
        buys["symbol"] = buys.get("symbol", pd.Series("", index=buys.index)).astype(str)
        buys = buys[
            buys.get("side", pd.Series("", index=buys.index)).astype(str).str.lower().eq("buy")
            & pd.to_numeric(buys.get("executed_shares", pd.Series(0.0, index=buys.index)), errors="coerce").fillna(0.0).gt(0.0)
        ].copy()
        if not buys.empty:
            buys = buys.groupby(["trade_date", "symbol"], as_index=False).agg(
                executed_buy=("executed_shares", "sum"),
                executed_notional=("trade_notional", "sum"),
                execution_status=("execution_status", "last"),
                buy_reason=("reason", "last"),
            )
    if buys.empty:
        data["executed_buy"] = 0.0
        data["executed_notional"] = 0.0
        data["execution_status"] = ""
        data["buy_reason"] = ""
    else:
        data = data.merge(
            buys,
            left_on=["date", "symbol"],
            right_on=["trade_date", "symbol"],
            how="left",
        )
        data["executed_buy"] = pd.to_numeric(data.get("executed_buy"), errors="coerce").fillna(0.0)
        data["executed_notional"] = pd.to_numeric(data.get("executed_notional"), errors="coerce").fillna(0.0)
        data["execution_status"] = data.get("execution_status", pd.Series("", index=data.index)).fillna("")
        data["buy_reason"] = data.get("buy_reason", pd.Series("", index=data.index)).fillna("")
        if "trade_date" in data.columns:
            data = data.drop(columns=["trade_date"])
    data["executed_flag"] = pd.to_numeric(data["executed_buy"], errors="coerce").fillna(0.0).gt(0.0)
    preferred = [
        "date",
        "symbol",
        "executed_flag",
        "executed_buy",
        "executed_notional",
        "execution_status",
        "buy_reason",
        "retail_executable",
        "retail_block_reason",
        "retail_executable_score",
        "entry_confirmed",
        "entry_alpha_score",
        "entry_timing_score",
        "entry_liquidity_score",
        "entry_matrix_score",
        "alpha_quality_score",
        "surge_capture_score",
        "follow_through_score",
        "exhaustion_score",
        "entry_success_probability",
        "entry_size_tier",
        "planned_entry_lots",
        "downtrend_decay_score",
        "post_entry_failure_score",
        "primary_score",
        "alpha_percentile",
        "expected_return_5d",
        "one_lot_cash_required",
        "one_lot_account_weight",
        "retail_one_lot_position_cap",
        "forward_return_5d",
        "forward_return_10d",
        "forward_return_20d",
    ]
    columns = [column for column in preferred if column in data.columns]
    extras = [column for column in data.columns if column not in columns]
    return data[columns + extras].sort_values(
        ["date", "executed_flag", "retail_executable_score", "symbol"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)


def _entry_timing_diagnostics(entry_audit: pd.DataFrame, execution_ledger: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "date",
        "symbol",
        "entry_matrix_score",
        "alpha_quality_score",
        "entry_timing_score",
        "surge_capture_score",
        "follow_through_score",
        "exhaustion_score",
        "downtrend_decay_score",
        "post_entry_failure_score",
        "entry_size_tier",
        "planned_lots",
        "executed_lots",
        "empirical_distribution_score",
        "final_entry_score",
        "tail_risk_proxy",
        "trend_direction_score",
        "peak_decay_score",
        "profit_protection_pressure",
        "dynamic_giveback_limit",
        "future_loss_risk_score",
        "forward_return_1d",
        "forward_return_3d",
        "forward_return_5d",
        "forward_return_10d",
        "best_buy_after_entry_date",
        "best_buy_after_entry_gap",
        "worst_drawdown_after_entry",
        "entry_confirmed",
        "entry_block_reason",
        "position_state",
        "retail_executable",
        "retail_block_reason",
    ]
    if entry_audit is None or entry_audit.empty:
        return pd.DataFrame(columns=columns)
    data = entry_audit.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    data["symbol"] = data.get("symbol", pd.Series("", index=data.index)).astype(str)
    data["planned_lots"] = pd.to_numeric(data.get("planned_entry_lots"), errors="coerce").fillna(0.0)
    if execution_ledger is None or execution_ledger.empty:
        data["executed_lots"] = 0.0
    else:
        executions = execution_ledger.copy()
        executions["trade_date"] = pd.to_datetime(executions.get("trade_date"), errors="coerce")
        executions["symbol"] = executions.get("symbol", pd.Series("", index=executions.index)).astype(str)
        side = executions.get("side", pd.Series("", index=executions.index)).astype(str).str.lower()
        executions = executions[side.eq("buy")].copy()
        if executions.empty:
            data["executed_lots"] = 0.0
        else:
            buys = (
                executions.groupby(["trade_date", "symbol"], as_index=False)
                .agg(executed_shares=("executed_shares", "sum"))
            )
            buys["executed_lots"] = pd.to_numeric(buys["executed_shares"], errors="coerce").fillna(0.0) / float(MIN_LOT_SIZE)
            data = data.merge(
                buys[["trade_date", "symbol", "executed_lots"]],
                left_on=["date", "symbol"],
                right_on=["trade_date", "symbol"],
                how="left",
            )
            data["executed_lots"] = pd.to_numeric(data.get("executed_lots"), errors="coerce").fillna(0.0)
            if "trade_date" in data.columns:
                data = data.drop(columns=["trade_date"])
    for column in columns:
        if column not in data.columns:
            data[column] = pd.NA
    return data[columns].sort_values(
        ["date", "executed_lots", "entry_matrix_score", "symbol"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)


def _pnl_by_sell_reason(trade_pairs: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "sell_reason",
        "closed_trade_count",
        "closed_trade_win_rate",
        "realized_pnl",
        "gross_profit",
        "gross_loss",
        "avg_win",
        "avg_loss",
        "payoff_ratio",
        "profit_factor",
    ]
    if trade_pairs is None or trade_pairs.empty:
        return pd.DataFrame(columns=columns)
    data = trade_pairs.copy()
    data["realized_pnl_amount"] = pd.to_numeric(data.get("realized_pnl_amount"), errors="coerce")
    reason_source = data.get("sell_reason", data.get("close_reason", pd.Series("", index=data.index)))
    data["sell_reason"] = reason_source.fillna("").astype(str).replace("", "unknown")
    data = data[data["realized_pnl_amount"].notna()].copy()
    if data.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for reason, group in data.groupby("sell_reason", dropna=False):
        pnl = pd.to_numeric(group["realized_pnl_amount"], errors="coerce").dropna()
        wins = pnl[pnl > 0.0]
        losses = pnl[pnl < 0.0]
        gross_profit = float(wins.sum()) if len(wins) else 0.0
        gross_loss = float(losses.sum()) if len(losses) else 0.0
        avg_win = float(wins.mean()) if len(wins) else pd.NA
        avg_loss = float(losses.mean()) if len(losses) else pd.NA
        rows.append(
            {
                "sell_reason": str(reason),
                "closed_trade_count": int(len(pnl)),
                "closed_trade_win_rate": float((pnl > 0.0).mean()) if len(pnl) else pd.NA,
                "realized_pnl": float(pnl.sum()) if len(pnl) else 0.0,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "payoff_ratio": (
                    float(avg_win / abs(avg_loss))
                    if pd.notna(avg_win) and pd.notna(avg_loss) and abs(float(avg_loss)) > 1e-12
                    else pd.NA
                ),
                "profit_factor": (
                    float(gross_profit / abs(gross_loss))
                    if abs(gross_loss) > 1e-12
                    else pd.NA
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("realized_pnl", ascending=False)


def _future_loss_duration_audit(trade_pairs: pd.DataFrame, features: pd.DataFrame, *, horizon_days: int = 40) -> pd.DataFrame:
    columns = [
        "symbol",
        "entry_date",
        "exit_date",
        "sell_reason",
        "exit_price",
        "exit_net_price",
        "exit_shares",
        "realized_pnl_amount",
        "realized_pnl_pct",
        "future_5d_return_if_hold",
        "future_10d_return_if_hold",
        "future_20d_return_if_hold",
        "future_40d_return_if_hold",
        "future_low_after_exit",
        "future_low_date",
        "days_to_future_low",
        "loss_days_after_exit",
        "observed_future_days",
        "avoided_loss_to_future_low",
        "continued_loss_flag",
    ]
    if trade_pairs is None or trade_pairs.empty or features is None or features.empty:
        return pd.DataFrame(columns=columns)
    required = {"symbol", "entry_date", "exit_date", "sell_reason", "exit_price", "exit_shares"}
    if not required.issubset(trade_pairs.columns):
        return pd.DataFrame(columns=columns)
    price_col = "close_nominal" if "close_nominal" in features.columns else "close"
    if not {"date", "symbol", price_col}.issubset(features.columns):
        return pd.DataFrame(columns=columns)
    trade_symbols = set(trade_pairs["symbol"].dropna().astype(str).unique())
    if not trade_symbols:
        return pd.DataFrame(columns=columns)
    source_prices = features.loc[features["symbol"].astype(str).isin(trade_symbols), ["date", "symbol", price_col]]
    prices = source_prices.copy()
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")
    prices["symbol"] = prices["symbol"].astype(str)
    prices[price_col] = pd.to_numeric(prices[price_col], errors="coerce")
    prices = prices.dropna(subset=["date", "symbol", price_col]).sort_values(["symbol", "date"])
    prices_by_symbol = {
        symbol: group.reset_index(drop=True)
        for symbol, group in prices.groupby("symbol", sort=False)
    }
    rows = []
    for _, trade in trade_pairs.iterrows():
        symbol = str(trade.get("symbol", ""))
        exit_date = pd.to_datetime(trade.get("exit_date"), errors="coerce")
        if not symbol or pd.isna(exit_date):
            continue
        exit_price = _safe_float(trade.get("exit_net_price"), default=_safe_float(trade.get("exit_price"), default=0.0))
        shares = _safe_float(trade.get("exit_shares"), default=0.0)
        if exit_price <= 0.0 or shares <= 0.0:
            continue
        symbol_prices = prices_by_symbol.get(symbol)
        if symbol_prices is None or symbol_prices.empty:
            continue
        start_pos = int(symbol_prices["date"].searchsorted(pd.Timestamp(exit_date), side="right"))
        path = symbol_prices.iloc[start_pos : start_pos + int(horizon_days)].copy()
        if path.empty:
            continue
        close = path[price_col].astype(float).reset_index(drop=True)
        dates = path["date"].reset_index(drop=True)
        returns = {}
        for horizon in (5, 10, 20, 40):
            if len(close) >= horizon:
                returns[horizon] = float(close.iloc[horizon - 1] / exit_price - 1.0)
            else:
                returns[horizon] = pd.NA
        low_idx = int(close.idxmin())
        low_price = float(close.iloc[low_idx])
        low_date = pd.Timestamp(dates.iloc[low_idx])
        loss_days = int((close < exit_price).sum())
        rows.append(
            {
                "symbol": symbol,
                "entry_date": trade.get("entry_date", pd.NaT),
                "exit_date": exit_date,
                "sell_reason": str(trade.get("sell_reason", "")),
                "exit_price": _safe_float(trade.get("exit_price"), default=exit_price),
                "exit_net_price": exit_price,
                "exit_shares": shares,
                "realized_pnl_amount": _safe_float(trade.get("realized_pnl_amount"), default=0.0),
                "realized_pnl_pct": _safe_float(trade.get("realized_pnl_pct"), default=0.0),
                "future_5d_return_if_hold": returns[5],
                "future_10d_return_if_hold": returns[10],
                "future_20d_return_if_hold": returns[20],
                "future_40d_return_if_hold": returns[40],
                "future_low_after_exit": low_price,
                "future_low_date": low_date,
                "days_to_future_low": int(low_idx + 1),
                "loss_days_after_exit": loss_days,
                "observed_future_days": int(len(close)),
                "avoided_loss_to_future_low": max((exit_price - low_price) * shares, 0.0),
                "continued_loss_flag": bool(loss_days >= min(10, len(close)) or low_price < exit_price * 0.95),
            }
        )
    return pd.DataFrame(rows, columns=columns)


CONTROL_AVOIDED_LOSS_REASONS = ("profit_hard_stop_exit", "hard_stop_exit", "alpha_collapse_consensus", "safety_deleveraging")


def _control_avoided_loss_ledger(execution_ledger: pd.DataFrame, features: pd.DataFrame, *, as_of=None) -> pd.DataFrame:
    columns = [
        "trade_date",
        "symbol",
        "sell_reason",
        "exit_price",
        "exit_net_price",
        "executed_shares",
        "horizon_days",
        "maturity_date",
        "window_low_date",
        "window_low_price",
        "window_end_date",
        "window_end_price",
        "avoided_loss_to_window_low",
        "avoided_loss_to_window_end",
        "signed_exit_benefit_to_window_low",
        "signed_exit_benefit_to_window_end",
        "counterfactual_window_observed_days",
        "counterfactual_note",
    ]
    if execution_ledger is None or execution_ledger.empty or features is None or features.empty:
        return pd.DataFrame(columns=columns)
    required = {"trade_date", "symbol", "side", "reason", "price", "executed_shares"}
    if not required.issubset(execution_ledger.columns):
        return pd.DataFrame(columns=columns)
    price_col = "trade_close" if "trade_close" in features.columns else "close_nominal" if "close_nominal" in features.columns else "close"
    if not {"date", "symbol", price_col}.issubset(features.columns):
        return pd.DataFrame(columns=columns)
    as_of_ts = pd.Timestamp(as_of) if as_of is not None else None
    sells = execution_ledger.copy()
    sells["trade_date"] = pd.to_datetime(sells["trade_date"], errors="coerce")
    sells["side"] = sells["side"].astype(str).str.lower()
    sells["reason"] = sells["reason"].astype(str)
    sells["executed_shares"] = pd.to_numeric(sells["executed_shares"], errors="coerce").fillna(0.0)
    sells["price"] = pd.to_numeric(sells["price"], errors="coerce")
    sells["total_cost"] = pd.to_numeric(sells.get("total_cost", pd.Series(0.0, index=sells.index)), errors="coerce").fillna(0.0)
    sells = sells[
        sells["trade_date"].notna()
        & sells["side"].eq("sell")
        & sells["reason"].isin(CONTROL_AVOIDED_LOSS_REASONS)
        & sells["executed_shares"].gt(0.0)
        & sells["price"].gt(0.0)
    ].copy()
    if sells.empty:
        return pd.DataFrame(columns=columns)
    sell_symbols = set(sells["symbol"].dropna().astype(str).unique())
    if not sell_symbols:
        return pd.DataFrame(columns=columns)
    source_prices = features.loc[features["symbol"].astype(str).isin(sell_symbols), ["date", "symbol", price_col]]
    feature_prices = source_prices.copy()
    feature_prices["date"] = pd.to_datetime(feature_prices["date"], errors="coerce")
    feature_prices["symbol"] = feature_prices["symbol"].astype(str)
    feature_prices[price_col] = pd.to_numeric(feature_prices[price_col], errors="coerce")
    feature_prices = feature_prices.dropna(subset=["date", "symbol", price_col])
    feature_prices = feature_prices.sort_values(["symbol", "date"])
    prices_by_symbol = {
        symbol: group.reset_index(drop=True)
        for symbol, group in feature_prices.groupby("symbol", sort=False)
    }
    rows = []
    horizon_days = int(GOVERNANCE_CONTROL_AVOIDED_LOSS_HORIZON_DAYS)
    for _, sell in sells.iterrows():
        symbol = str(sell["symbol"])
        trade_date = pd.Timestamp(sell["trade_date"])
        symbol_prices = prices_by_symbol.get(symbol)
        if symbol_prices is None or symbol_prices.empty:
            continue
        start_pos = int(symbol_prices["date"].searchsorted(trade_date, side="right"))
        path = symbol_prices.iloc[start_pos:].copy()
        if as_of_ts is not None:
            path = path[path["date"] <= as_of_ts]
        path = path.head(horizon_days)
        if path.empty:
            continue
        low_idx = path[price_col].idxmin()
        low_row = path.loc[low_idx]
        end_row = path.iloc[-1]
        shares = float(sell["executed_shares"])
        exit_net_price = float(sell["price"]) - float(sell.get("total_cost", 0.0)) / max(shares, 1e-12)
        window_low_price = float(low_row[price_col])
        window_end_price = float(end_row[price_col])
        rows.append(
            {
                "trade_date": trade_date,
                "symbol": symbol,
                "sell_reason": str(sell["reason"]),
                "exit_price": float(sell["price"]),
                "exit_net_price": exit_net_price,
                "executed_shares": shares,
                "horizon_days": horizon_days,
                "maturity_date": pd.Timestamp(end_row["date"]),
                "window_low_date": pd.Timestamp(low_row["date"]),
                "window_low_price": window_low_price,
                "window_end_date": pd.Timestamp(end_row["date"]),
                "window_end_price": window_end_price,
                "avoided_loss_to_window_low": max((exit_net_price - window_low_price) * shares, 0.0),
                "avoided_loss_to_window_end": max((exit_net_price - window_end_price) * shares, 0.0),
                "signed_exit_benefit_to_window_low": (exit_net_price - window_low_price) * shares,
                "signed_exit_benefit_to_window_end": (exit_net_price - window_end_price) * shares,
                "counterfactual_window_observed_days": int(len(path)),
                "counterfactual_note": "If the control sell had not happened, this is the extra mark-to-low/end loss avoided in the post-exit window.",
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _control_avoided_loss_summary_frame(ledger: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "sell_reason",
        "control_exit_count",
        "avoided_loss_to_window_low",
        "avoided_loss_to_window_end",
        "avg_avoided_loss_to_window_low",
        "signed_exit_benefit_to_window_low",
        "signed_exit_benefit_to_window_end",
        "avg_observed_days",
    ]
    if ledger is None or ledger.empty:
        return pd.DataFrame(columns=columns)
    data = ledger.copy()
    data["avoided_loss_to_window_low"] = pd.to_numeric(data.get("avoided_loss_to_window_low"), errors="coerce").fillna(0.0)
    data["avoided_loss_to_window_end"] = pd.to_numeric(data.get("avoided_loss_to_window_end"), errors="coerce").fillna(0.0)
    data["counterfactual_window_observed_days"] = pd.to_numeric(
        data.get("counterfactual_window_observed_days"), errors="coerce"
    ).fillna(0.0)
    data["signed_exit_benefit_to_window_low"] = pd.to_numeric(
        data.get("signed_exit_benefit_to_window_low"), errors="coerce"
    ).fillna(0.0)
    data["signed_exit_benefit_to_window_end"] = pd.to_numeric(
        data.get("signed_exit_benefit_to_window_end"), errors="coerce"
    ).fillna(0.0)
    rows = []
    for reason, group in data.groupby("sell_reason", dropna=False):
        count = int(len(group))
        low_sum = float(group["avoided_loss_to_window_low"].sum())
        rows.append(
            {
                "sell_reason": str(reason),
                "control_exit_count": count,
                "avoided_loss_to_window_low": low_sum,
                "avoided_loss_to_window_end": float(group["avoided_loss_to_window_end"].sum()),
                "avg_avoided_loss_to_window_low": low_sum / max(count, 1),
                "signed_exit_benefit_to_window_low": float(
                    group["signed_exit_benefit_to_window_low"].sum()
                ),
                "signed_exit_benefit_to_window_end": float(
                    group["signed_exit_benefit_to_window_end"].sum()
                ),
                "avg_observed_days": float(group["counterfactual_window_observed_days"].mean()) if count else pd.NA,
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("avoided_loss_to_window_low", ascending=False)


def _control_avoided_loss_summary(execution_ledger: pd.DataFrame, features: pd.DataFrame, *, as_of=None) -> dict:
    return _control_avoided_loss_summary_from_frame(
        _control_avoided_loss_summary_frame(
            _control_avoided_loss_ledger(execution_ledger, features, as_of=as_of)
        )
    )


def _control_avoided_loss_summary_from_frame(summary: pd.DataFrame | None) -> dict:
    result = {
        "control_exit_count": 0,
        "avoided_loss_to_window_low": 0.0,
        "avoided_loss_to_window_end": 0.0,
        "profit_hard_stop_avoided_loss_to_window_low": 0.0,
        "hard_stop_avoided_loss_to_window_low": 0.0,
        "alpha_collapse_avoided_loss_to_window_low": 0.0,
        "safety_deleveraging_avoided_loss_to_window_low": 0.0,
    }
    if summary is None or summary.empty:
        return result
    data = summary.copy()
    data["sell_reason"] = data.get("sell_reason", pd.Series("", index=data.index)).astype(str)
    data["control_exit_count"] = pd.to_numeric(data.get("control_exit_count"), errors="coerce").fillna(0.0)
    data["avoided_loss_to_window_low"] = pd.to_numeric(data.get("avoided_loss_to_window_low"), errors="coerce").fillna(0.0)
    data["avoided_loss_to_window_end"] = pd.to_numeric(data.get("avoided_loss_to_window_end"), errors="coerce").fillna(0.0)
    result["control_exit_count"] = int(data["control_exit_count"].sum())
    result["avoided_loss_to_window_low"] = float(data["avoided_loss_to_window_low"].sum())
    result["avoided_loss_to_window_end"] = float(data["avoided_loss_to_window_end"].sum())
    for reason, key in (
        ("profit_hard_stop_exit", "profit_hard_stop_avoided_loss_to_window_low"),
        ("hard_stop_exit", "hard_stop_avoided_loss_to_window_low"),
        ("alpha_collapse_consensus", "alpha_collapse_avoided_loss_to_window_low"),
        ("safety_deleveraging", "safety_deleveraging_avoided_loss_to_window_low"),
    ):
        rows = data[data["sell_reason"].eq(reason)]
        result[key] = float(rows["avoided_loss_to_window_low"].sum()) if not rows.empty else 0.0
    result["hard_stop_avoided_loss_to_window_low"] += result["profit_hard_stop_avoided_loss_to_window_low"]
    return result


def _format_pnl_by_sell_reason(pnl_by_sell_reason: pd.DataFrame) -> str:
    if pnl_by_sell_reason is None or pnl_by_sell_reason.empty:
        return ""
    parts = []
    data = pnl_by_sell_reason.copy()
    data["realized_pnl"] = pd.to_numeric(data.get("realized_pnl"), errors="coerce")
    for _, row in data.sort_values("realized_pnl", ascending=False).head(8).iterrows():
        parts.append(f"{row.get('sell_reason')}:{float(row.get('realized_pnl', 0.0)):.2f}")
    return "|".join(parts)


def _validation_pass_ratio(validation: pd.DataFrame) -> float:
    if validation is None or validation.empty or "passed" not in validation.columns:
        return 0.0
    values = validation["passed"].fillna(False).astype(bool)
    return float(values.mean()) if len(values) else 0.0


def _validation_fail_count(validation: pd.DataFrame) -> int:
    if validation is None or validation.empty or "passed" not in validation.columns:
        return 0
    values = validation["passed"].fillna(False).astype(bool)
    return int((~values).sum())


def _research_gate_status(research_gate: pd.DataFrame) -> str:
    if research_gate is None or research_gate.empty or "overall_status" not in research_gate.columns:
        return "unknown"
    values = research_gate["overall_status"].dropna().astype(str)
    return values.iloc[-1] if not values.empty else "unknown"


def _research_gate_fail_count(research_gate: pd.DataFrame) -> int:
    if research_gate is None or research_gate.empty or "pass_flag" not in research_gate.columns:
        return 0
    passed = research_gate["pass_flag"].fillna(False).astype(bool)
    return int((~passed).sum())


def _latest_bool(values) -> bool:
    if values is None:
        return False
    series = pd.Series(values).dropna()
    if series.empty:
        return False
    return bool(series.iloc[-1])


def _safe_float(value, default=0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").dropna()
    if numeric.empty:
        return float(default)
    return float(numeric.iloc[0])


def _retail_entry_score_gate_pass(row, *, strategy_logic_version: str, minimum_score: float) -> bool:
    """Keep the legacy retail score gate out of every v3 execution audit.

    V3 admission has already been decided by its cabinet/state-machine score.
    Reapplying the legacy matrix threshold here would only create a false audit
    rejection (and the raw Native score is not on the same scale as the ML
    percentile score).
    """
    if is_mainline_v3_version(strategy_logic_version):
        return True
    value = row.get("entry_matrix_score", 0.0) if hasattr(row, "get") else 0.0
    return _safe_float(value, default=0.0) >= float(minimum_score)


def _clip01(value) -> float:
    return min(max(_safe_float(value, default=0.0), 0.0), 1.0)


def _dynamic_giveback_limit(
    *,
    mfe: float,
    trend_direction_score: float,
    peak_decay_score: float,
    orderflow_decay_score: float,
) -> float:
    mfe = max(_safe_float(mfe, default=0.0), 0.0)
    if mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_3):
        base = float(GOVERNANCE_PROFIT_GIVEBACK_3)
    elif mfe >= float(GOVERNANCE_PROFIT_PROTECT_TRIGGER_2):
        base = float(GOVERNANCE_PROFIT_GIVEBACK_2)
    else:
        base = float(GOVERNANCE_PROFIT_GIVEBACK_1) + 0.05
    trend_decay_penalty = max(0.55 - _safe_float(trend_direction_score, default=0.50), 0.0) * 0.30
    peak_decay_penalty = _clip01(peak_decay_score) * 0.12
    orderflow_penalty = _clip01(orderflow_decay_score) * 0.08
    return min(max(base - trend_decay_penalty - peak_decay_penalty - orderflow_penalty, 0.18), 0.55)


def _governance_round_trip_cost_rate() -> float:
    return (
        2.0 * float(COMMISSION_RATE)
        + 2.0 * float(SLIPPAGE_RATE)
        + float(STAMP_DUTY_RATE)
        + 2.0 * float(TRANSFER_FEE_RATE)
    )


def _normalize_governance_control_mode(value) -> str:
    mode = str(value or "normal").strip().lower()
    aliases = {
        "default": "normal",
        "full": "normal",
        "factor": "factor_only",
        "factor_only_stop": "factor_only",
        "stop": "factor_only",
        "stop_mode": "factor_only",
        "paper": "paper_controls",
        "paper_control": "paper_controls",
        "safe_factor": "safe_factor_only",
        "safe_stop": "safe_factor_only",
        "scap": "aggressive_profit",
        "profit": "aggressive_profit",
        "lean": "aggressive_lean",
        "scap_v3": "aggressive_lean",
    }
    mode = aliases.get(mode, mode)
    allowed = {"normal", "factor_only", "paper_controls", "safe_factor_only", "aggressive_profit", "aggressive_lean"}
    if mode not in allowed:
        raise ValueError(f"Unknown governance_control_mode '{value}'. Available: {sorted(allowed)}")
    return mode


def _holding_target_contract(
    capital_profile,
    *,
    actual_holding_count: int,
    max_positions_override=None,
) -> dict:
    """Resolve minimum, soft target and hard maximum without treating zero as missing."""
    profile = dict(capital_profile or {})
    minimum_raw = profile.get("min_holdings")
    minimum = (
        int(GOVERNANCE_FORCE_DEPLOY_MIN_HOLDINGS_20K)
        if minimum_raw is None
        else max(int(minimum_raw), 0)
    )
    maximum_raw = (
        max_positions_override
        if max_positions_override not in (None, "")
        else profile.get("max_positions")
    )
    maximum = (
        int(GOVERNANCE_DEFAULT_TOP_N)
        if maximum_raw in (None, "")
        else max(int(maximum_raw), 1)
    )
    soft_raw = profile.get("soft_target_positions")
    soft = minimum if soft_raw is None else max(int(soft_raw), 0)
    soft = min(max(soft, minimum), maximum)
    actual = max(int(actual_holding_count), 0)
    return {
        "minimum_required_holding_count": minimum,
        "soft_target_holding_count": soft,
        "maximum_allowed_holding_count": maximum,
        "soft_holding_shortfall_count": max(soft - actual, 0),
    }


def governance_preload_calendar_days(control_mode, configured_days=None) -> int:
    """Return the single feature-history preload contract for every entry point."""
    base_days = (
        int(GOVERNANCE_PRELOAD_CALENDAR_DAYS)
        if configured_days is None
        else int(configured_days)
    )
    if base_days < 0:
        raise ValueError("governance preload calendar days must be non-negative")
    if _normalize_governance_control_mode(control_mode) == "aggressive_lean":
        return max(base_days, 420)
    return base_days


def _normalize_capital_usage_mode(value) -> str:
    mode = str(value or GOVERNANCE_CAPITAL_USAGE_MODE_DEFAULT).strip().lower()
    aliases = {
        "cash": "allow_cash",
        "allow": "allow_cash",
        "idle_cash": "allow_cash",
        "force": GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY,
        "forced": GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY,
        "full": GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY,
        "deploy": GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY,
    }
    mode = aliases.get(mode, mode)
    if mode not in {"allow_cash", GOVERNANCE_CAPITAL_USAGE_MODE_FORCE_DEPLOY}:
        return GOVERNANCE_CAPITAL_USAGE_MODE_DEFAULT
    return mode


def _state_machine_entry_mask(candidates: pd.DataFrame) -> pd.Series:
    """Confirmed entry mask that also honors the alpha role-diversity gate."""
    if candidates is None or candidates.empty:
        return pd.Series(dtype=bool)
    confirmed = candidates.get("entry_confirmed", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
    if "state_machine_role_pass" not in candidates.columns:
        return confirmed
    role_pass = candidates["state_machine_role_pass"].fillna(False).astype(bool)
    return confirmed & role_pass


def _scap_entry_stage_counts(candidates: pd.DataFrame) -> dict[str, int]:
    """Keep signal qualification distinct from optimizer slot allocation."""
    if candidates is None or candidates.empty:
        return {
            "raw_signal_count": 0,
            "structural_feasible_count": 0,
            "cash_feasible_count": 0,
            "slot_feasible_count": 0,
            "pre_slot_qualified_entry_count": 0,
            "optimizer_selected_entry_count": 0,
        }
    selected = _state_machine_entry_mask(candidates)
    role_pass = candidates.get(
        "state_machine_role_pass",
        pd.Series(True, index=candidates.index),
    ).fillna(False).astype(bool)
    pre_slot = candidates.get(
        "mainline_v3_pre_slot_qualified",
        selected,
    ).fillna(False).astype(bool) & role_pass
    raw_signal = candidates.get(
        "mainline_v3_raw_signal", pre_slot
    ).fillna(False).astype(bool) & role_pass
    structural = candidates.get(
        "mainline_v3_structural_feasible", pre_slot
    ).fillna(False).astype(bool) & role_pass
    cash = candidates.get(
        "mainline_v3_cash_feasible", structural
    ).fillna(False).astype(bool) & role_pass
    slot = candidates.get(
        "mainline_v3_slot_feasible", cash
    ).fillna(False).astype(bool) & role_pass
    return {
        "raw_signal_count": int(raw_signal.sum()),
        "structural_feasible_count": int(structural.sum()),
        "cash_feasible_count": int(cash.sum()),
        "slot_feasible_count": int(slot.sum()),
        "pre_slot_qualified_entry_count": int(pre_slot.sum()),
        "optimizer_selected_entry_count": int(selected.sum()),
    }


def _best_bucket(bucket_frame: pd.DataFrame, dimension: str, metric: str) -> str:
    if bucket_frame is None or bucket_frame.empty:
        return ""
    if not {"dimension", "bucket", metric}.issubset(bucket_frame.columns):
        return ""
    data = bucket_frame[bucket_frame["dimension"].astype(str).eq(dimension)].copy()
    data[metric] = pd.to_numeric(data[metric], errors="coerce")
    data = data.dropna(subset=[metric])
    if data.empty:
        return ""
    best = data.sort_values(metric, ascending=False).iloc[0]
    return f"{best['bucket']} ({float(best[metric]):.2%})"


def _calibration_ece(calibration: pd.DataFrame, *, horizon_days: int) -> float:
    if calibration is None or calibration.empty:
        return pd.NA
    required = {"horizon_days", "sample_count", "realized_win_rate", "predicted_p_mean"}
    if not required.issubset(calibration.columns):
        return pd.NA
    data = calibration[pd.to_numeric(calibration["horizon_days"], errors="coerce").eq(int(horizon_days))].copy()
    if data.empty:
        return pd.NA
    n = pd.to_numeric(data["sample_count"], errors="coerce").fillna(0.0)
    if float(n.sum()) <= 0:
        return pd.NA
    gap = (
        pd.to_numeric(data["realized_win_rate"], errors="coerce")
        - pd.to_numeric(data["predicted_p_mean"], errors="coerce")
    ).abs()
    return float((gap * n).sum() / n.sum())


def _calibration_best_wilson(calibration: pd.DataFrame, *, horizon_days: int) -> float:
    if calibration is None or calibration.empty:
        return pd.NA
    required = {"horizon_days", "sample_count", "wilson_lower_95"}
    if not required.issubset(calibration.columns):
        return pd.NA
    data = calibration[pd.to_numeric(calibration["horizon_days"], errors="coerce").eq(int(horizon_days))].copy()
    data["sample_count"] = pd.to_numeric(data["sample_count"], errors="coerce").fillna(0.0)
    data["wilson_lower_95"] = pd.to_numeric(data["wilson_lower_95"], errors="coerce")
    data = data[(data["sample_count"] >= 50) & data["wilson_lower_95"].notna()]
    if data.empty:
        return pd.NA
    return float(data["wilson_lower_95"].max())


def _payoff_metric(payoff: pd.DataFrame, *, horizon_days: int, side: str, metric: str) -> float:
    if payoff is None or payoff.empty or metric not in payoff.columns:
        return pd.NA
    data = payoff[
        pd.to_numeric(payoff.get("horizon_days"), errors="coerce").eq(int(horizon_days))
        & payoff.get("side", pd.Series(dtype=object)).astype(str).eq(str(side))
    ].copy()
    values = pd.to_numeric(data.get(metric), errors="coerce").dropna()
    if values.empty:
        return pd.NA
    weights = pd.to_numeric(data.loc[values.index, "sample_count"], errors="coerce").fillna(1.0)
    return float((values * weights).sum() / max(float(weights.sum()), 1e-12))


def _payoff_reason_metric(payoff: pd.DataFrame, *, horizon_days: int, side: str, reason: str, metric: str) -> float:
    if payoff is None or payoff.empty or metric not in payoff.columns:
        return pd.NA
    data = payoff[
        pd.to_numeric(payoff.get("horizon_days"), errors="coerce").eq(int(horizon_days))
        & payoff.get("side", pd.Series(dtype=object)).astype(str).eq(str(side))
        & payoff.get("reason", pd.Series(dtype=object)).astype(str).eq(str(reason))
    ].copy()
    values = pd.to_numeric(data.get(metric), errors="coerce").dropna()
    if values.empty:
        return pd.NA
    weights = pd.to_numeric(data.loc[values.index, "sample_count"], errors="coerce").fillna(1.0)
    return float((values * weights).sum() / max(float(weights.sum()), 1e-12))


def _rebound_metric(report: pd.DataFrame, *, diagnostic: str, metric: str) -> float:
    if report is None or report.empty or metric not in report.columns:
        return pd.NA
    data = report[report.get("diagnostic", pd.Series(dtype=object)).astype(str).eq(str(diagnostic))]
    if data.empty:
        return pd.NA
    values = pd.to_numeric(data.get(metric), errors="coerce").dropna()
    if values.empty:
        return pd.NA
    return float(values.iloc[-1])


def _safe_count_true(values) -> int:
    if values is None:
        return 0
    try:
        return int(pd.Series(values).fillna(False).astype(bool).sum())
    except Exception:
        return 0


def _rolling_beat_metric(report: pd.DataFrame, *, window_days: int, segment: str = "full") -> float:
    if report is None or report.empty or "account_beat_ratio" not in report.columns:
        return pd.NA
    data = report[
        pd.to_numeric(report.get("window_days"), errors="coerce").eq(int(window_days))
        & report.get("segment", pd.Series("full", index=report.index)).fillna("full").astype(str).eq(str(segment))
    ].copy()
    values = pd.to_numeric(data.get("account_beat_ratio"), errors="coerce").dropna()
    if values.empty:
        return pd.NA
    return float(values.iloc[-1])


def _capacity_passed(capacity: pd.DataFrame, *, multiplier: float) -> bool:
    if capacity is None or capacity.empty or "capacity_passed" not in capacity.columns:
        return False
    data = capacity[pd.to_numeric(capacity.get("capital_multiplier"), errors="coerce").eq(float(multiplier))]
    if data.empty:
        return False
    return bool(data["capacity_passed"].astype(bool).iloc[-1])


def _factor_weight_explanation(*, activity_ema: float, avg_exposure_ema: float, zero_trade_warning: bool) -> str:
    if zero_trade_warning:
        return "warning: high weight with near-zero shadow exposure"
    if activity_ema < 0.20:
        return "penalized: low active shadow coverage"
    if avg_exposure_ema < 0.05:
        return "capped: low average shadow exposure"
    return "active shadow contribution"


def _factor_primary_role(model_name: str, module: str, *, configured_roles=()) -> str:
    if configured_roles:
        return str(tuple(configured_roles)[0])
    name = str(model_name).lower()
    module = str(module).lower()
    if module == "defensive" or "lowvol" in name:
        return "risk_sizer"
    if module in {"event_limit"} or "limit" in name or "event" in name:
        return "event_risk_watch"
    if module in {"trend", "flow_close"}:
        return "entry_hold_sell_watch"
    if module in {"reversal_pullback", "range_grid"}:
        return "entry_only"
    return "entry_alpha"


def _top_value_counts(values, *, limit: int = 8) -> list[dict]:
    if values is None:
        return []
    series = pd.Series(values).fillna("unknown").astype(str)
    if series.empty:
        return []
    counts = series.value_counts(dropna=False).head(int(limit))
    total = max(float(len(series)), 1.0)
    return [
        {"name": str(name), "count": int(count), "share": float(count) / total}
        for name, count in counts.items()
    ]


def _aggregate_factor_modules(factor_weights: list[dict]) -> list[dict]:
    modules: dict[str, dict] = {}
    for row in factor_weights or []:
        module = str(row.get("factor_module", "unknown"))
        if module not in modules:
            modules[module] = {
                "factor_module": module,
                "weight": 0.0,
                "weight_share": 0.0,
                "factor_count": 0,
                "avg_predicted_return_5d": 0.0,
            }
        modules[module]["weight"] += float(row.get("weight", 0.0) or 0.0)
        modules[module]["weight_share"] += float(row.get("weight_share", 0.0) or 0.0)
        modules[module]["avg_predicted_return_5d"] += float(row.get("avg_predicted_return_5d", 0.0) or 0.0)
        modules[module]["factor_count"] += 1
    for row in modules.values():
        count = max(int(row["factor_count"]), 1)
        row["avg_predicted_return_5d"] = float(row["avg_predicted_return_5d"]) / count
    return sorted(modules.values(), key=lambda item: float(item.get("weight_share", 0.0)), reverse=True)


def _confirm_post_entry_failure(candidates: pd.DataFrame) -> pd.Series:
    if candidates is None or candidates.empty:
        return pd.Series(dtype=bool)
    return _post_entry_failure_score(candidates).ge(float(GOVERNANCE_POST_ENTRY_FAILURE_EXIT_SCORE))


def _post_entry_failure_score(candidates: pd.DataFrame) -> pd.Series:
    if candidates is None or candidates.empty:
        return pd.Series(dtype=float)
    watch = candidates.get("post_entry_failure_watch", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
    unrealized = pd.to_numeric(candidates.get("position_unrealized_return", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    alpha = pd.to_numeric(candidates.get("alpha_percentile", pd.Series(0.5, index=candidates.index)), errors="coerce").fillna(0.5)
    alpha_quality = pd.to_numeric(candidates.get("alpha_quality_score", pd.Series(0.5, index=candidates.index)), errors="coerce").fillna(0.5)
    entry_alpha_quality = pd.to_numeric(
        candidates.get("position_entry_alpha_quality_score", pd.Series(alpha_quality, index=candidates.index)),
        errors="coerce",
    ).fillna(alpha_quality)
    alpha_quality_drop = (entry_alpha_quality - alpha_quality).clip(lower=0.0, upper=1.0)
    ret5 = pd.to_numeric(candidates.get("ret_5", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    ret20 = pd.to_numeric(candidates.get("ret_20", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    close_to_ma20 = pd.to_numeric(candidates.get("close_to_ma20", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    mfe = pd.to_numeric(candidates.get("position_mfe", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    mae = pd.to_numeric(candidates.get("position_mae", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    downtrend_decay = pd.to_numeric(candidates.get("downtrend_decay_score", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    flow_raw = pd.to_numeric(candidates.get("entry_orderflow_confirm_count", pd.Series(float("nan"), index=candidates.index)), errors="coerce")
    flow_count = flow_raw.fillna(0.0)
    holding_days = pd.to_numeric(candidates.get("position_holding_days", pd.Series(0, index=candidates.index)), errors="coerce").fillna(0)
    alpha_collapse = (
        alpha.lt(0.45).astype(float) * 0.35
        + alpha_quality.lt(0.55).astype(float) * 0.25
        + (alpha_quality_drop / 0.12).clip(0.0, 1.0) * 0.40
    ).clip(0.0, 1.0)
    trend_weak = (
        ret5.lt(-0.02).astype(float) * 0.35
        + ret20.lt(-0.04).astype(float) * 0.35
        + close_to_ma20.lt(-0.03).astype(float) * 0.30
    ).clip(0.0, 1.0)
    orderflow_bad = flow_count.le(1).astype(float).where(flow_raw.notna(), 0.5)
    loss_bad = ((-unrealized - 0.015) / 0.055).clip(0.0, 1.0)
    poor_excursion = (
        mfe.lt(0.02).astype(float) * 0.45
        + ((-mae - 0.02) / 0.08).clip(0.0, 1.0) * 0.35
        + downtrend_decay.clip(0.0, 1.0) * 0.20
    ).clip(0.0, 1.0)
    stale_bad = ((holding_days - 6.0) / 14.0).clip(0.0, 1.0)
    score = (
        0.25 * loss_bad
        + 0.25 * alpha_collapse
        + 0.20 * poor_excursion
        + 0.15 * orderflow_bad
        + 0.15 * trend_weak
        + 0.05 * stale_bad
    ) / 1.05
    score = score.clip(0.0, 1.0)
    return score.where(watch | holding_days.ge(3), 0.0)


def build_shadow_factor_diagnostics(
    shadow_ledger: pd.DataFrame,
    *,
    reputation_ledger: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Rank per-alpha shadow portfolios when the expensive shadow mode is enabled."""
    if shadow_ledger is None or shadow_ledger.empty:
        return pd.DataFrame()
    required = {"model_name", "date", "nominal_nav", "actual_exposure"}
    if not required.issubset(shadow_ledger.columns):
        return pd.DataFrame()

    data = shadow_ledger.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["nominal_nav"] = pd.to_numeric(data["nominal_nav"], errors="coerce")
    data["actual_exposure"] = pd.to_numeric(data["actual_exposure"], errors="coerce").fillna(0.0)
    if "holding_count" in data.columns:
        data["holding_count"] = pd.to_numeric(data["holding_count"], errors="coerce").fillna(0.0)
    else:
        data["holding_count"] = 0.0
    data = data.dropna(subset=["date", "nominal_nav"])
    if data.empty:
        return pd.DataFrame()

    latest_reputation = pd.DataFrame()
    if reputation_ledger is not None and not reputation_ledger.empty and "model_name" in reputation_ledger.columns:
        reputation = reputation_ledger.copy()
        reputation["date"] = pd.to_datetime(reputation.get("date"), errors="coerce")
        latest_reputation = reputation.sort_values("date").groupby("model_name", as_index=False).tail(1)

    rows: list[dict] = []
    for model_name, group in data.sort_values("date").groupby("model_name"):
        nav = pd.to_numeric(group["nominal_nav"], errors="coerce").dropna()
        if nav.empty:
            continue
        initial_nav = float(nav.iloc[0])
        final_nav = float(nav.iloc[-1])
        if initial_nav <= 0:
            total_return = 0.0
        else:
            total_return = final_nav / initial_nav - 1.0
        peak = nav.cummax()
        drawdown = nav / peak.where(peak != 0.0) - 1.0
        max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
        trading_days = int(group["date"].nunique())
        active_mask = pd.to_numeric(group["actual_exposure"], errors="coerce").fillna(0.0) > 0.01
        active_days = int(active_mask.sum())
        avg_exposure = float(pd.to_numeric(group["actual_exposure"], errors="coerce").fillna(0.0).mean())
        avg_holding_count = float(pd.to_numeric(group["holding_count"], errors="coerce").fillna(0.0).mean())
        latest = (
            latest_reputation[latest_reputation["model_name"].astype(str).eq(str(model_name))].iloc[-1]
            if not latest_reputation.empty
            and latest_reputation["model_name"].astype(str).eq(str(model_name)).any()
            else pd.Series(dtype=object)
        )
        latest_active_weight = _safe_float(latest.get("active_reputation_weight", 1.0), 1.0)
        latest_candidate_weight = _safe_float(latest.get("candidate_weight", 1.0), 1.0)
        latest_score_ema = _safe_float(latest.get("score_ema", 0.0), 0.0)
        latest_activity_ema = _safe_float(latest.get("activity_ema", 0.0), 0.0)
        latest_coverage_ema = _safe_float(latest.get("coverage_ema", 0.0), 0.0)
        latest_avg_exposure_ema = _safe_float(latest.get("avg_exposure_ema", 0.0), 0.0)
        active_day_ratio = active_days / max(trading_days, 1)
        zero_trade_reward_flag = bool(
            active_days == 0
            and abs(total_return) <= 1e-10
            and latest_active_weight > 1.05
        )
        low_activity_high_weight_flag = bool(active_day_ratio < 0.05 and latest_active_weight > 1.20)
        rows.append(
            {
                "model_name": model_name,
                "trading_days": trading_days,
                "first_date": group["date"].min().strftime("%Y-%m-%d"),
                "last_date": group["date"].max().strftime("%Y-%m-%d"),
                "initial_nav": initial_nav,
                "final_nav": final_nav,
                "total_return": total_return,
                "max_drawdown": max_drawdown,
                "avg_actual_exposure": avg_exposure,
                "active_days": active_days,
                "active_day_ratio": active_day_ratio,
                "avg_holding_count": avg_holding_count,
                "latest_active_reputation_weight": latest_active_weight,
                "latest_candidate_weight": latest_candidate_weight,
                "latest_score_ema": latest_score_ema,
                "latest_activity_ema": latest_activity_ema,
                "latest_coverage_ema": latest_coverage_ema,
                "latest_avg_exposure_ema": latest_avg_exposure_ema,
                "zero_trade_reward_flag": zero_trade_reward_flag,
                "low_activity_high_weight_flag": low_activity_high_weight_flag,
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["return_rank"] = result["total_return"].rank(ascending=False, method="min").astype(int)
    result["drawdown_rank"] = result["max_drawdown"].rank(ascending=False, method="min").astype(int)
    result["activity_rank"] = result["active_day_ratio"].rank(ascending=False, method="min").astype(int)
    return result.sort_values(
        ["zero_trade_reward_flag", "total_return", "active_day_ratio"],
        ascending=[True, False, False],
    ).reset_index(drop=True)


def render_shadow_factor_diagnostics_markdown(diagnostics: pd.DataFrame) -> str:
    if diagnostics is None or diagnostics.empty:
        return "# Governance Shadow Factor Diagnostics\n\nNo shadow portfolio rows were available.\n"
    display = diagnostics.copy()
    percent_columns = [
        "total_return",
        "max_drawdown",
        "avg_actual_exposure",
        "active_day_ratio",
        "latest_avg_exposure_ema",
    ]
    for column in percent_columns:
        if column in display.columns:
            display[column] = pd.to_numeric(display[column], errors="coerce").map(lambda value: f"{value:.2%}")
    for column in (
        "latest_active_reputation_weight",
        "latest_candidate_weight",
        "latest_score_ema",
        "latest_activity_ema",
        "latest_coverage_ema",
        "avg_holding_count",
    ):
        if column in display.columns:
            display[column] = pd.to_numeric(display[column], errors="coerce").map(lambda value: f"{value:.4f}")
    columns = [
        "return_rank",
        "model_name",
        "total_return",
        "max_drawdown",
        "avg_actual_exposure",
        "active_days",
        "active_day_ratio",
        "latest_active_reputation_weight",
        "zero_trade_reward_flag",
        "low_activity_high_weight_flag",
    ]
    columns = [column for column in columns if column in display.columns]
    zero_warnings = int(diagnostics.get("zero_trade_reward_flag", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    low_activity_warnings = int(diagnostics.get("low_activity_high_weight_flag", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
    table_rows = [columns, ["---"] * len(columns)]
    for _, row in display[columns].iterrows():
        table_rows.append([str(row.get(column, "")) for column in columns])
    table_text = "\n".join("| " + " | ".join(row) + " |" for row in table_rows)
    lines = [
        "# Governance Shadow Factor Diagnostics",
        "",
        "This report is generated only when per-alpha shadow portfolios are enabled.",
        "",
        f"- Factors: {len(diagnostics)}",
        f"- Zero-trade high-weight warnings: {zero_warnings}",
        f"- Low-activity high-weight warnings: {low_activity_warnings}",
        "",
        table_text,
        "",
    ]
    return "\n".join(lines)


def _base_exposure_by_regime(regime_name: str) -> float:
    regime = str(regime_name).lower()
    mapping = {
        "crisis": 0.20,
        "bear": 0.40,
        "weak": 0.50,
        "neutral": 0.75,
        "rebound": 0.90,
        "bull": 1.00,
    }
    return float(mapping.get(regime, 0.40))


def _authorize_exposure_by_regime(
    *,
    regime_name: str,
    risk_level: str,
    safety_exposure_cap: float,
    candidates: pd.DataFrame,
    qualified_entry_count: int,
    trailing_buy_accuracy_5d,
    liquidity_stress: float,
    regime_overlay_mode: str = "full",
) -> dict:
    base = _base_exposure_by_regime(regime_name)
    overlay_mode = str(regime_overlay_mode or "full").strip().lower()
    overlay_capped = False
    if overlay_mode in {"off", "disabled", "none"}:
        return {
            "authorized_exposure_max": float(safety_exposure_cap),
            "exposure_authorization_tier": "control_mode_off",
            "exposure_authorization_block_reasons": "",
            "authorization_expected_edge_10d_mean": 0.0,
            "authorization_conservative_expected_edge_10d_mean": 0.0,
            "authorization_p_win_10d_mean": 0.0,
            "authorization_p_win_10d_wilson_lower_mean": 0.0,
            "authorization_calibration_trust_10d_mean": 0.0,
            "authorization_trailing_buy_accuracy_5d": _safe_float(trailing_buy_accuracy_5d, default=0.52),
            "authorization_liquidity_stress": float(liquidity_stress),
            "regime_overlay_mode": overlay_mode,
            "regime_overlay_capped": False,
        }
    if overlay_mode in {"conservative", "no_active_boost", "risk_only"}:
        capped_base = min(float(base), 0.60)
        overlay_capped = bool(capped_base < float(base))
        base = capped_base
    risk = str(risk_level).lower()
    regime = str(regime_name).lower()
    data = candidates.copy() if candidates is not None else pd.DataFrame()
    confirmed = (
        data[data.get("entry_confirmed", pd.Series(False, index=data.index)).fillna(False).astype(bool)].copy()
        if not data.empty
        else pd.DataFrame()
    )
    edge_mean = _safe_numeric_mean(confirmed.get("expected_edge_10d"), default=0.0)
    conservative_edge_mean = _safe_numeric_mean(confirmed.get("conservative_expected_edge_10d"), default=edge_mean)
    pwin_mean = _safe_numeric_mean(confirmed.get("p_win_10d_calibrated"), default=0.0)
    pwin_lower_mean = _safe_numeric_mean(confirmed.get("p_win_10d_wilson_lower"), default=max(pwin_mean - 0.08, 0.0))
    calibration_trust_mean = _safe_numeric_mean(confirmed.get("entry_calibration_trust_10d"), default=0.0)
    matrix_mean = _safe_numeric_mean(confirmed.get("entry_matrix_score"), default=0.0)
    alpha_quality_mean = _safe_numeric_mean(confirmed.get("alpha_quality_score"), default=0.0)
    follow_through_mean = _safe_numeric_mean(confirmed.get("follow_through_score"), default=0.0)
    exhaustion_mean = _safe_numeric_mean(confirmed.get("exhaustion_score"), default=0.0)
    trailing_accuracy = _safe_float(trailing_buy_accuracy_5d, default=0.52) if trailing_buy_accuracy_5d is not None else 0.52
    block_reasons = []
    tier = "defensive"
    multiplier = 0.55
    quality_ok = bool(matrix_mean >= 0.68 and alpha_quality_mean >= 0.64 and follow_through_mean >= 0.50 and exhaustion_mean < 0.60)

    if risk in {"crisis", "high"}:
        block_reasons.append(f"risk_level_{risk}")
        tier = "risk_capped"
        multiplier = 0.50 if risk == "high" else 0.35
    elif regime == "bull" and int(qualified_entry_count) >= 3 and float(liquidity_stress) < 0.25:
        if quality_ok or trailing_accuracy >= 0.44:
            tier = "full"
            multiplier = 0.90
        else:
            block_reasons.append("weak_bull_entry_evidence")
            multiplier = 0.75
    elif regime == "rebound" and int(qualified_entry_count) >= 3 and float(liquidity_stress) < 0.22:
        tier = "rebound_confirmed"
        if quality_ok:
            multiplier = 0.72
        else:
            multiplier = 0.55
            block_reasons.append("weak_rebound_entry_evidence")
    elif regime == "neutral" and int(qualified_entry_count) >= 3 and float(liquidity_stress) < 0.25:
        tier = "normal_high"
        multiplier = 0.85 if quality_ok or trailing_accuracy >= 0.44 else 0.70
    elif int(qualified_entry_count) < 2:
        block_reasons.append("too_few_confirmed_entries")
        multiplier = 0.55
    elif float(liquidity_stress) >= 0.25:
        block_reasons.append("liquidity_stress")
        multiplier = 0.65
    elif matrix_mean < 0.62 and trailing_accuracy < 0.40:
        block_reasons.append("weak_matrix_and_accuracy")
        multiplier = 0.60
    elif regime == "weak":
        tier = "weak_participation"
        multiplier = 0.70
    elif regime == "bear":
        tier = "bear_participation"
        multiplier = 0.55
    else:
        tier = "defensive_participation"
        multiplier = 0.65

    authorized = min(float(safety_exposure_cap), max(base * multiplier, 0.0))
    return {
        "authorized_exposure_max": float(authorized),
        "exposure_authorization_tier": tier,
        "exposure_authorization_block_reasons": "|".join(block_reasons),
        "authorization_expected_edge_10d_mean": float(edge_mean),
        "authorization_conservative_expected_edge_10d_mean": float(conservative_edge_mean),
        "authorization_p_win_10d_mean": float(pwin_mean),
        "authorization_p_win_10d_wilson_lower_mean": float(pwin_lower_mean),
        "authorization_calibration_trust_10d_mean": float(calibration_trust_mean),
        "authorization_trailing_buy_accuracy_5d": trailing_accuracy,
        "authorization_liquidity_stress": float(liquidity_stress),
        "regime_overlay_mode": overlay_mode,
        "regime_overlay_capped": overlay_capped,
    }


def _prepare_features(feature_df, *, copy: bool = True):
    return prepare_features_runtime(feature_df, copy=copy)


def _governance_feature_columns():
    return governance_feature_columns_runtime()
