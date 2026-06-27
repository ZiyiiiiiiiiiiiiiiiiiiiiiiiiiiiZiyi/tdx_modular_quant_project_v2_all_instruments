"""Historical daily runner for the phase-one rules-based governance strategy."""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pandas as pd

from config import (
    ENABLE_MARKET_REGIME_POLICY,
    FEATURE_DAILY_PARQUET,
    GOVERNANCE_ALPHA_CANDIDATE_LIMIT,
    GOVERNANCE_ALPHA_MODEL_FEATURES,
    GOVERNANCE_ALPHA_MODELS,
    GOVERNANCE_ALLOWED_INSTRUMENT_TYPES,
    GOVERNANCE_DEFAULT_TOP_N,
    GOVERNANCE_DEFAULT_TURNOVER_BUDGET,
    GOVERNANCE_HIGH_EXPOSURE_MAX_TOP1_RISK_CONTRIBUTION,
    GOVERNANCE_HIGH_EXPOSURE_MIN_ACTUAL_TARGET_RATIO,
    GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_TRADES,
    GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_WIN_RATE,
    GOVERNANCE_HIGH_EXPOSURE_MIN_PAYOFF_RATIO,
    GOVERNANCE_HIGH_EXPOSURE_MIN_PROFIT_FACTOR,
    GOVERNANCE_HIGH_EXPOSURE_MIN_REALIZED_PNL,
    GOVERNANCE_INITIAL_TRANSITION_DAYS,
    GOVERNANCE_INITIAL_CASH,
    GOVERNANCE_END_DATE,
    GOVERNANCE_OUTPUT_DIR,
    GOVERNANCE_PRELOAD_CALENDAR_DAYS,
    GOVERNANCE_REPUTATION_WARMUP_DAYS,
    GOVERNANCE_REPORT_MD,
    GOVERNANCE_START_DATE,
    GOVERNANCE_SUMMARY_CSV,
    MIN_LOT_SIZE,
    MARKET_REGIME_BENCHMARK_SYMBOL,
    SAFETY_PROXY_MODE,
)
from functions.decision_council.accounting import build_exposure_snapshot, calculate_five_day_reward
from functions.decision_council.account_state import (
    ExploratoryCorporateActionProcessor,
    LastKnownPriceLedger,
)
from functions.decision_council.analytics import (
    build_bucket_attribution,
    build_governance_attribution,
    build_top_strength_benchmark_series,
    factor_module,
)
from functions.decision_council.engine import PhaseOneDecisionCouncilEngine
from functions.decision_council.entry_calibration import RollingEntryCalibrator
from functions.decision_council.entry_confirmation import apply_entry_confirmation
from functions.decision_council.exposure_catchup import decide_exposure_catchup
from functions.decision_council.fast_shadow import FastShadowPortfolioRunner
from functions.decision_council.leakage import validate_governance_split
from functions.decision_council.market_regime_policy import MarketRegimePolicy
from functions.decision_council.proposals import build_daily_candidates
from functions.decision_council.plots import save_governance_diagnostic_plots
from functions.decision_council.quality_reports import build_governance_quality_reports
from functions.decision_council.monitoring import evaluate_daily_rollback
from functions.decision_council.reputation import ReputationLedger
from functions.execution.cost_model import estimate_trade_costs
from functions.execution.order_simulator import simulate_order_book
from functions.execution.trade_pairing import build_trade_pairing_ledgers
from functions.pricing.feature_leakage_audit import audit_feature_columns
from functions.pipeline_cache import file_fingerprint
from functions.report_builder import build_strategy_report, save_strategy_report


def archive_existing_governance_output(output_dir: Path) -> Path | None:
    """Archive the previous run before fixed-name outputs are overwritten."""
    output_dir = Path(output_dir)
    if not output_dir.exists() or not any(output_dir.iterdir()):
        return None

    archive_root = output_dir.parent / "_archive" / output_dir.name
    archive_root.mkdir(parents=True, exist_ok=True)
    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = archive_root / timestamp
    suffix = 1
    while archive_dir.exists():
        suffix += 1
        archive_dir = archive_root / f"{timestamp}_{suffix:02d}"
    shutil.copytree(output_dir, archive_dir)
    _clear_governance_output_files(output_dir)
    return archive_dir


def _clear_governance_output_files(output_dir: Path) -> None:
    """Remove stale fixed-name output files after archiving without recursive deletion."""
    for child in Path(output_dir).iterdir():
        if child.is_file() or child.is_symlink():
            child.unlink()
            continue
        raise RuntimeError(
            "Governance output cleanup refuses to remove directories automatically. "
            f"Please clear this directory manually before rerunning: {child}"
        )


class ProgressTracker:
    """Track progress and estimate remaining time for long-running operations."""
    
    def __init__(self, total_steps, desc="Processing"):
        self.total_steps = total_steps
        self.current_step = 0
        self.desc = desc
        self.start_time = time.time()
    
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
        # Print progress
        elapsed_str = str(timedelta(seconds=int(elapsed)))
        print(f"\r{self.desc}: [{bar}] {progress_pct:.1f}% ({self.current_step}/{self.total_steps}) | "
              f"Elapsed: {elapsed_str} | Remaining: {remaining_str} | {step_info}", end="", flush=True)
        
        if self.current_step >= self.total_steps:
            print()  # New line when complete


@dataclass
class Position:
    shares: float
    acquired_date: pd.Timestamp


class GovernanceBacktestRunner:
    """Run daily close decisions and next-day open executions with audit ledgers."""

    def __init__(
        self,
        feature_df: pd.DataFrame,
        *,
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
        probability_bucket_mode: str = "default",
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
    ):
        self.features = feature_df if prepared_features else _prepare_features(feature_df)
        self.features["date"] = pd.to_datetime(self.features["date"], errors="coerce")
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
        self.probability_bucket_mode = str(probability_bucket_mode or "default")
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
        self.alpha_rows = []
        self.entry_confirmation_rows = []
        self.factor_weight_rows = []
        self.alpha_collapse_exit_rows = []
        self._pending_alpha_collapse_exits = []
        self._normal_rebalance_dates = frozenset()
        # Market regime policy for dynamic parameter adjustment
        self.market_regime_policy = MarketRegimePolicy() if self.enable_market_regime_policy else None
        self._current_regime = "bear"  # Default to bear
        self._regime_params_cache: dict[pd.Timestamp, object | None] = {}
        if self.market_regime_policy is not None:
            try:
                self.market_regime_policy.detector.prepare_history(
                    self.features,
                    benchmark_symbol=MARKET_REGIME_BENCHMARK_SYMBOL,
                )
            except Exception:
                pass
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
    ) -> dict[str, Path]:
        dates = pd.Index(self.features["date"].drop_duplicates().sort_values())
        if start_date is not None:
            dates = dates[dates >= pd.Timestamp(start_date)]
        if end_date is not None:
            dates = dates[dates <= pd.Timestamp(end_date)]
        if max_days is not None:
            dates = dates[: int(max_days)]
        
        total_days = len(dates)
        self._run_benchmark_base_nav = self._raw_benchmark_nav_asof(dates[0]) if total_days else 1.0
        weekly = pd.Series(dates, index=dates).groupby(dates.to_period("W-FRI")).max()
        self._normal_rebalance_dates = frozenset(pd.Timestamp(date) for date in weekly)
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
            )
        
        try:
            for day_index, date in enumerate(dates):
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
                    date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
                    nav = exposure.get("nominal_nav", 0)
                    holding_count = int(exposure.get("holding_count", len(self.positions)) or 0)
                    progress.update(f"Date: {date_str} | NAV: {nav:,.0f} | Holdings: {holding_count}")
        finally:
            if live_monitor is not None:
                live_monitor.finish("回测完成。窗口会保持打开，关闭浏览器标签即可。")
        
        for model_name, shadow in shadows.items():
            shadow_frame = pd.DataFrame(shadow.exposure_rows)
            if not shadow_frame.empty:
                shadow_frame.insert(0, "model_name", model_name)
                self.engine.record_shadow_portfolio(shadow_frame)
        return self._save()

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
        self._execute_pending(date, daily)
        self._prune_empty_positions()
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
        
        # Get regime-adjusted parameters if market regime policy is enabled
        regime_params = self._get_regime_params(date)
        current_turnover_budget = regime_params.default_turnover_budget if regime_params else GOVERNANCE_DEFAULT_TURNOVER_BUDGET
        current_min_score_percentile = regime_params.min_score_percentile if regime_params else None
        
        candidates, proposals = build_daily_candidates(
            daily,
            reputation_weights=(
                self._proposal_reputation_weights()
                if self.enable_reputation
                else {model_name: 1.0 for model_name in self.alpha_models}
            ),
            holding_days=self.holding_days,
            candidate_limit=GOVERNANCE_ALPHA_CANDIDATE_LIMIT,
            model_names=self.alpha_models,
            min_score_percentile=current_min_score_percentile,
            allowed_instrument_types=self._allowed_instrument_types,
            target_index_codes=self._target_index_codes,
            universe_mode=self._universe_mode,
            require_constituents=self._require_constituents,
            allow_fallback=self._allow_fallback,
            enable_quality_filters=self._enable_quality_filters,
            selection_weight_mode=self.selection_weight_mode,
        )
        safety_row = self.engine.safety_signals.loc[pd.Timestamp(date)]
        if isinstance(safety_row, pd.DataFrame):
            safety_row = safety_row.iloc[-1]
        risk_level = str(safety_row.get("risk_level", "normal"))
        structural_regime_level = str(safety_row.get("structural_regime_level", "bull"))
        candidates = apply_entry_confirmation(
            candidates,
            risk_level=risk_level,
            structural_regime_level=structural_regime_level,
            entry_calibrator=self.entry_calibrator,
            confirmation_mode=self.entry_confirmation_mode,
            probability_bucket_mode=self.probability_bucket_mode,
        )
        candidates = self._attach_position_lifecycle_signals(candidates, date=date)
        self.entry_calibrator.schedule_candidates(
            candidates,
            day_index=day_index,
            horizon_days=5,
            regime_name=structural_regime_level,
        )
        self.entry_calibrator.schedule_candidates(
            candidates,
            day_index=day_index,
            horizon_days=10,
            regime_name=structural_regime_level,
        )
        if not self.shadow_fast_mode:
            self._record_entry_confirmation(date, candidates)
        proposals["decision_date"] = date
        if not self.shadow_fast_mode:
            audit_symbols = set(candidates.head(GOVERNANCE_ALPHA_CANDIDATE_LIMIT)["symbol"].astype(str)) | set(self.positions)
            self.alpha_rows.append(proposals[proposals["symbol"].astype(str).isin(audit_symbols)].copy())
        allow_normal_rebalance = self._allow_normal_rebalance(date, day_index)
        actual_exposure = float(exposure.get("invested_value", 0.0)) / max(float(exposure.get("nominal_nav", 0.0)), 1e-12)
        safety_exposure_cap = float(pd.to_numeric(pd.Series([safety_row.get("exposure_cap", 1.0)]), errors="coerce").fillna(1.0).iloc[0])
        regime_name = getattr(regime_params, "regime_name", structural_regime_level) if regime_params is not None else structural_regime_level
        liquidity_stress = float(pd.to_numeric(pd.Series([safety_row.get("market_liquidity_stress_ratio", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
        qualified_entry_count = int(candidates.get("entry_confirmed", pd.Series(dtype=bool)).fillna(False).astype(bool).sum())
        trailing_buy_accuracy_5d = self._trailing_trade_accuracy(date, side="buy", horizon_days=5, lookback_trades=60)
        exposure_authorization = _authorize_exposure_by_regime(
            regime_name=regime_name,
            risk_level=risk_level,
            safety_exposure_cap=safety_exposure_cap,
            candidates=candidates,
            qualified_entry_count=qualified_entry_count,
            trailing_buy_accuracy_5d=trailing_buy_accuracy_5d,
            liquidity_stress=liquidity_stress,
            regime_overlay_mode=self.regime_overlay_mode,
        )
        target_exposure_proxy = exposure_authorization["authorized_exposure_max"]
        high_exposure_gate = self._high_exposure_research_gate(date)
        catchup_decision = decide_exposure_catchup(
            actual_exposure=actual_exposure,
            target_exposure=target_exposure_proxy,
            risk_level=risk_level,
            structural_regime_level=structural_regime_level,
            market_liquidity_stress_ratio=liquidity_stress,
            qualified_entry_count=qualified_entry_count,
            transition_only=day_index < GOVERNANCE_INITIAL_TRANSITION_DAYS,
            trailing_buy_accuracy_5d=trailing_buy_accuracy_5d,
            risk_contribution_gate_pass=high_exposure_gate["gate_pass"],
            top5_risk_contribution_sum=high_exposure_gate["latest_top5_risk_contribution_sum"],
            risk_symbol_count=high_exposure_gate["latest_risk_symbol_count"],
            hard_risk_gate_enabled=True,
        )
        high_exposure_gate_diagnostics = {
            "high_exposure_research_gate_pass": high_exposure_gate["gate_pass"],
            "high_exposure_research_gate_reason": high_exposure_gate["gate_reason"],
            "closed_trade_count_for_gate": high_exposure_gate["closed_trade_count"],
            "closed_trade_win_rate_for_gate": high_exposure_gate["closed_trade_win_rate"],
            "profit_factor_for_gate": high_exposure_gate["profit_factor"],
            "payoff_ratio_for_gate": high_exposure_gate["payoff_ratio"],
            "realized_pnl_for_gate": high_exposure_gate["realized_pnl"],
            "actual_target_ratio_for_gate": high_exposure_gate["actual_target_ratio"],
            "latest_top1_risk_contribution_for_gate": high_exposure_gate["latest_top1_risk_contribution"],
        }
        _, orders, diagnostics = self.engine.decide_day(
            decision_id=f"gov_{pd.Timestamp(date).strftime('%Y%m%d')}",
            decision_date=date,
            candidates=candidates,
            current_weights=self._current_weights(daily, exposure["nominal_nav"]),
            holding_days=self.holding_days,
            turnover_budget=current_turnover_budget,
            top_n=regime_params.max_positions if regime_params else GOVERNANCE_DEFAULT_TOP_N,
            allow_normal_rebalance=allow_normal_rebalance,
            transition_only=day_index < GOVERNANCE_INITIAL_TRANSITION_DAYS,
            hard_qualification_symbols=self._hard_qualification_symbols(),
            catchup_buy_budget=catchup_decision.catchup_buy_budget,
            catchup_allowed=catchup_decision.catchup_allowed,
            target_exposure_cap=target_exposure_proxy,
            covariance_matrix=self._rolling_candidate_covariance(date, candidates),
        )
        diagnostics.update(catchup_decision.__dict__)
        diagnostics.update(high_exposure_gate_diagnostics)
        if (
            not bool(high_exposure_gate["gate_pass"])
            and str(diagnostics.get("catchup_block_reason", "")) == "risk_contribution_gate_blocks_catchup"
        ):
            diagnostics["catchup_block_reason"] = f"high_exposure_gate:{high_exposure_gate['gate_reason']}"
        diagnostics["regime_name"] = str(regime_name)
        diagnostics["base_exposure_by_regime"] = _base_exposure_by_regime(regime_name)
        diagnostics.update(exposure_authorization)
        diagnostics["trailing_buy_accuracy_5d"] = trailing_buy_accuracy_5d
        self._register_orders(orders, daily, exposure["nominal_nav"])
        self.exposure_rows[-1].update(
            {
                "target_exposure": diagnostics["target_exposure"],
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
                "regime_name": diagnostics.get("regime_name", ""),
                "base_exposure_by_regime": diagnostics.get("base_exposure_by_regime", 0.0),
                "raw_safety_exposure_cap": diagnostics.get("raw_safety_exposure_cap", safety_exposure_cap),
                "effective_target_exposure_cap": diagnostics.get("effective_target_exposure_cap", target_exposure_proxy),
                "authorized_exposure_max": diagnostics.get("authorized_exposure_max", target_exposure_proxy),
                "exposure_authorization_tier": diagnostics.get("exposure_authorization_tier", ""),
                "exposure_authorization_block_reasons": diagnostics.get("exposure_authorization_block_reasons", ""),
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
                "risk_new_buy_block": diagnostics.get("risk_new_buy_block", False),
                "risk_catchup_block": diagnostics.get("risk_catchup_block", False),
                "risk_new_buy_block_applied": diagnostics.get("risk_new_buy_block_applied", False),
                "risk_catchup_block_applied": diagnostics.get("risk_catchup_block_applied", False),
                "risk_blocked_new_buy_weight": diagnostics.get("risk_blocked_new_buy_weight", 0.0),
                "avg_pairwise_correlation": diagnostics.get("avg_pairwise_correlation", 0.0),
                "covariance_condition_number": diagnostics.get("covariance_condition_number", 0.0),
                "corporate_action_cash_delta": corporate_action_summary["cash_delta"],
                "corporate_action_stock_dividend_shares": corporate_action_summary["stock_dividend_shares"],
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
                "entry_block_reason",
                "breakout_probability_bucket_pass",
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
            order_cols = [column for column in ["symbol", "side", "delta_weight", "reason", "priority"] if column in orders.columns]
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
            pending_cols = [column for column in ["symbol", "side", "remaining_shares", "status", "reason", "lock_days"] if column in active.columns]
            for _, row in active.loc[:, pending_cols].head(10).iterrows():
                pending_preview.append({key: row.get(key) for key in pending_cols})

        factor_weights = self._factor_weight_preview(date=date, proposals=proposals)
        module_weights = _aggregate_factor_modules(factor_weights)
        holding_price_paths = self._holding_price_paths(date=date)
        lifecycle_preview = self._holding_lifecycle_preview()
        benchmark_nav = self._benchmark_nav_asof(date)
        nav_amount = float(exposure.get("liquidatable_nav", exposure.get("nominal_nav", self.initial_cash)) or self.initial_cash)
        account_net_value = nav_amount / max(float(self.initial_cash), 1e-12)
        excess_net_value = account_net_value / max(float(benchmark_nav), 1e-12)
        trailing_sell_accuracy_5d = self._trailing_trade_accuracy(date, side="sell", horizon_days=5, lookback_trades=60)
        lifecycle_alert_count = int(
            sum(
                bool(row.get("profit_giveback_flag", False)) or bool(row.get("post_entry_failure_flag", False))
                for row in lifecycle_preview
            )
        )

        return {
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
            "account_net_value": float(account_net_value),
            "excess_net_value": float(excess_net_value),
            "structural_regime_level": str(safety_row.get("structural_regime_level", "bull")),
            "regime_exposure_budget": float(pd.to_numeric(pd.Series([safety_row.get("regime_exposure_budget", 1.0)]), errors="coerce").fillna(1.0).iloc[0]),
            "safety_exposure_cap": float(pd.to_numeric(pd.Series([safety_row.get("safety_exposure_cap", 1.0)]), errors="coerce").fillna(1.0).iloc[0]),
            "hard_freeze_active": bool(safety_row.get("hard_freeze_active", False)),
            "unresolved_safety_exposure": float(diagnostics.get("unresolved_safety_exposure", 0.0)),
            "target_exposure": float(diagnostics.get("target_exposure", 0.0)),
            "actual_exposure": float(diagnostics.get("actual_exposure", 0.0)),
            "base_exposure_by_regime": float(diagnostics.get("base_exposure_by_regime", 0.0)),
            "raw_safety_exposure_cap": float(diagnostics.get("raw_safety_exposure_cap", 0.0)),
            "effective_target_exposure_cap": float(diagnostics.get("effective_target_exposure_cap", 0.0)),
            "exposure_authorization_tier": str(diagnostics.get("exposure_authorization_tier", "")),
            "exposure_authorization_block_reasons": str(diagnostics.get("exposure_authorization_block_reasons", "")),
            "regime_overlay_mode": str(diagnostics.get("regime_overlay_mode", self.regime_overlay_mode)),
            "regime_overlay_capped": bool(diagnostics.get("regime_overlay_capped", False)),
            "authorization_expected_edge_10d_mean": _safe_float(diagnostics.get("authorization_expected_edge_10d_mean"), default=0.0),
            "authorization_p_win_10d_mean": _safe_float(diagnostics.get("authorization_p_win_10d_mean"), default=0.0),
            "constraint_cash_reserve": float(diagnostics.get("constraint_cash_reserve", 0.0)),
            "planned_safety_sell_weight": float(diagnostics.get("planned_safety_sell_weight", 0.0)),
            "normal_turnover_weight": float(diagnostics.get("normal_turnover_weight", 0.0)),
            "total_target_drift": float(diagnostics.get("total_target_drift", 0.0)),
            "candidate_count": int(len(candidates)),
            "entry_confirmed_count": int(diagnostics.get("qualified_entry_count", 0)),
            "entry_block_summary": entry_block_summary,
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
            "breakout_probability_bucket_pass_count": int(candidates.get("breakout_probability_bucket_pass", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
            "exposure_gap": float(diagnostics.get("exposure_gap", 0.0)),
            "catchup_allowed": bool(diagnostics.get("catchup_allowed", False)),
            "catchup_buy_budget": float(diagnostics.get("catchup_buy_budget", 0.0)),
            "catchup_block_reason": str(diagnostics.get("catchup_block_reason", "")),
            "catchup_tier": str(diagnostics.get("catchup_tier", "none")),
            "accuracy_multiplier": _safe_float(diagnostics.get("accuracy_multiplier"), default=0.0),
            "trailing_buy_accuracy_5d": _safe_float(diagnostics.get("trailing_buy_accuracy_5d"), default=float("nan")),
            "trailing_sell_accuracy_5d": _safe_float(trailing_sell_accuracy_5d, default=float("nan")),
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
            "top_n": getattr(regime_params, "max_positions", GOVERNANCE_DEFAULT_TOP_N) if regime_params is not None else GOVERNANCE_DEFAULT_TOP_N,
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
        total_weight = max(sum(float(value) for value in weights.values()), 1e-12)
        for model_name in self.alpha_models:
            weight = float(weights.get(model_name, 1.0))
            previous = float(self._last_factor_weights.get(model_name, weight))
            stats = contribution.loc[model_name] if model_name in contribution.index else {}
            rep = reputation_state.loc[model_name] if not reputation_state.empty and model_name in reputation_state.index else {}
            module = factor_module(model_name)
            avg_exposure_ema = float(rep.get("avg_exposure_ema", 0.0)) if len(reputation_state) else 0.0
            activity_ema = float(rep.get("activity_ema", 0.0)) if len(reputation_state) else 0.0
            zero_trade_warning = bool(weight > 1.0 and avg_exposure_ema < 0.01)
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "model_name": str(model_name),
                    "factor_module": module,
                    "factor_role": _factor_primary_role(model_name, module),
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
        if str(self.selection_weight_mode).lower() in {"role_balanced", "reputation_auxiliary", "no_reputation_selection"}:
            return {model_name: 1.0 for model_name in self.alpha_models}
        return self.reputation.weights()

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
        start_date = end_date - pd.Timedelta(days=120)
        close_col = "close_nominal" if "close_nominal" in self.features.columns else "close"
        prices = self.features[
            self.features["symbol"].astype(str).isin(symbols)
            & self.features["date"].between(start_date, end_date)
        ].copy()
        if prices.empty:
            return []
        prices[close_col] = pd.to_numeric(prices[close_col], errors="coerce")
        prices = prices.dropna(subset=["date", "symbol", close_col]).sort_values(["symbol", "date"])
        paths = []
        for symbol, group in prices.groupby("symbol", sort=False):
            group = group.tail(90)
            close = pd.to_numeric(group[close_col], errors="coerce").dropna()
            initial = float(close.iloc[0]) if not close.empty and float(close.iloc[0]) > 0 else 0.0
            if initial <= 0:
                continue
            points = [
                {
                    "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                    "value": float(row[close_col]) / initial,
                }
                for _, row in group.iterrows()
                if pd.notna(row[close_col])
            ]
            if len(points) >= 2:
                paths.append({"symbol": str(symbol), "points": points})
        return paths

    def _holding_lifecycle_preview(self) -> list[dict]:
        rows = []
        for row in getattr(self, "_last_position_mark_rows", []) or []:
            rows.append(
                {
                    "symbol": str(row.get("symbol", "")),
                    "market_value": _safe_float(row.get("market_value"), default=0.0),
                    "entry_date": str(row.get("entry_date", ""))[:10],
                    "entry_price": _safe_float(row.get("entry_price"), default=0.0),
                    "unrealized_return": _safe_float(row.get("unrealized_return"), default=0.0),
                    "mfe": _safe_float(row.get("mfe"), default=0.0),
                    "mae": _safe_float(row.get("mae"), default=0.0),
                    "giveback_from_peak": _safe_float(row.get("giveback_from_peak"), default=0.0),
                    "profit_giveback_flag": bool(row.get("profit_giveback_flag", False)),
                    "post_entry_failure_flag": bool(row.get("post_entry_failure_flag", False)),
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
        top_strength = build_top_strength_benchmark_series(self.features)
        if not top_strength.empty:
            data = top_strength.copy()
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

    def _update_lifecycle_on_buy(self, symbol: str, *, date, price: float, shares: float, current) -> None:
        symbol = str(symbol)
        price = float(price)
        shares = float(shares)
        if price <= 0.0 or shares <= 0.0:
            return
        existing = self.position_lifecycle.get(symbol)
        previous_shares = float(current.shares) if current is not None else 0.0
        if existing and previous_shares > 0.0:
            old_entry = float(existing.get("entry_price", price) or price)
            entry_price = (old_entry * previous_shares + price * shares) / max(previous_shares + shares, 1e-12)
            entry_date = existing.get("entry_date", pd.Timestamp(date))
        else:
            entry_price = price
            entry_date = pd.Timestamp(date)
        self.position_lifecycle[symbol] = {
            "entry_date": pd.Timestamp(entry_date),
            "entry_price": float(entry_price),
            "peak_price": max(float(existing.get("peak_price", price)) if existing else price, price),
            "trough_price": min(float(existing.get("trough_price", price)) if existing else price, price),
        }

    def _mark_lifecycle(self, symbol: str, *, date, price: float) -> dict:
        symbol = str(symbol)
        price = float(price)
        state = self.position_lifecycle.get(symbol)
        if state is None or price <= 0.0:
            return {
                "entry_date": pd.NaT,
                "entry_price": pd.NA,
                "unrealized_return": pd.NA,
                "mfe": pd.NA,
                "mae": pd.NA,
                "giveback_from_peak": pd.NA,
                "profit_giveback_flag": False,
                "post_entry_failure_flag": False,
            }
        state["peak_price"] = max(float(state.get("peak_price", price)), price)
        state["trough_price"] = min(float(state.get("trough_price", price)), price)
        entry_price = float(state.get("entry_price", price) or price)
        entry_date = pd.Timestamp(state.get("entry_date", date))
        unrealized = price / entry_price - 1.0 if entry_price > 0.0 else 0.0
        mfe = float(state["peak_price"]) / entry_price - 1.0 if entry_price > 0.0 else 0.0
        mae = float(state["trough_price"]) / entry_price - 1.0 if entry_price > 0.0 else 0.0
        giveback = (mfe - unrealized) / max(mfe, 1e-12) if mfe > 0.0 else 0.0
        holding_days = int(self.holding_days.get(symbol, 0))
        return {
            "entry_date": entry_date,
            "entry_price": entry_price,
            "unrealized_return": float(unrealized),
            "mfe": float(mfe),
            "mae": float(mae),
            "giveback_from_peak": float(giveback),
            "profit_giveback_flag": bool(mfe >= 0.08 and giveback >= 0.45 and holding_days >= 3),
            "post_entry_failure_flag": bool(holding_days >= 6 and mfe < 0.02 and unrealized < -0.02),
        }

    def _attach_position_lifecycle_signals(self, candidates: pd.DataFrame, *, date) -> pd.DataFrame:
        if candidates is None or candidates.empty:
            return candidates
        data = candidates.copy()
        flags = {}
        for row in getattr(self, "_last_position_mark_rows", []) or []:
            symbol = str(row.get("symbol", ""))
            flags[symbol] = {
                "profit_giveback_exit": bool(row.get("profit_giveback_flag", False)),
                "post_entry_failure_watch": bool(row.get("post_entry_failure_flag", False)),
                "position_unrealized_return": row.get("unrealized_return", pd.NA),
                "position_mfe": row.get("mfe", pd.NA),
                "position_mae": row.get("mae", pd.NA),
                "position_giveback_from_peak": row.get("giveback_from_peak", pd.NA),
            }
        for column, default in (
            ("profit_giveback_exit", False),
            ("post_entry_failure_watch", False),
            ("position_unrealized_return", pd.NA),
            ("position_mfe", pd.NA),
            ("position_mae", pd.NA),
            ("position_giveback_from_peak", pd.NA),
        ):
            data[column] = data["symbol"].astype(str).map(lambda symbol: flags.get(symbol, {}).get(column, default))
        data["post_entry_failure_exit"] = _confirm_post_entry_failure(data)
        return data

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
            "breakout_probability_bucket_pass_count": int(candidates.get("breakout_probability_bucket_pass", pd.Series(False, index=candidates.index)).fillna(False).astype(bool).sum()),
        }
        for reason, count in reason_counts.head(8).items():
            row[f"entry_reason_count_{reason}"] = int(count)
        self.entry_confirmation_rows.append(row)

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
            )
            for model_name in self.alpha_models
        }

    def _execute_pending(self, date, daily):
        active = self.engine.pending_orders.orders
        active = active[
            active["status"].isin(["pending", "pending_locked"])
            & (pd.to_datetime(active["created_date"], errors="coerce") < pd.Timestamp(date))
        ].copy()
        if active.empty:
            return
        market = daily.set_index("symbol", drop=False)
        rows = []
        blocked_symbols = set()
        fill_map = {}
        for _, order in active.sort_values(["priority", "created_date"]).iterrows():
            symbol = str(order["symbol"])
            if symbol not in market.index:
                blocked_symbols.add(symbol)
                continue
            quote = market.loc[symbol]
            price = float(quote["open_nominal"])
            requested = float(order["remaining_shares"])
            if str(order["side"]) == "sell":
                position = self.positions.get(symbol)
                requested = min(requested, position.shares if position else 0.0)
            row = {
                "symbol": symbol,
                "trade_date": date,
                "side": order["side"],
                "target_shares": requested,
                "price": price,
                "market_amount": float(pd.to_numeric(pd.Series([quote.get("amount", 0.0)]), errors="coerce").fillna(0.0).iloc[0]),
                "same_day_sell_blocked": bool(
                    str(order["side"]) == "sell"
                    and symbol in self.positions
                    and self.positions[symbol].acquired_date >= pd.Timestamp(date)
                ),
                "price_limit_blocked_flag": bool(
                    quote["rough_limit_up"] if str(order["side"]) == "buy" else quote["rough_limit_down"]
                ),
                "suspension_blocked_flag": not bool(quote["is_trading"]),
                "order_id": order["order_id"],
                "decision_id": order["decision_id"],
                "reason": order["reason"],
            }
            rows.append(row)
        if not rows:
            self.engine.settle_pending_orders(date, blocked_symbols=blocked_symbols)
            return
        simulated = simulate_order_book(pd.DataFrame(rows))
        for _, fill in simulated.iterrows():
            symbol = str(fill["symbol"])
            order_id = str(fill["order_id"])
            if fill["execution_status"] != "filled":
                blocked_symbols.add(symbol)
                continue
            shares = float(fill["executed_shares"])
            notional = float(fill["trade_notional"])
            cost = float(fill["total_cost"])
            if str(fill["side"]) == "buy":
                affordable = max(self.cash - cost, 0.0)
                shares = min(shares, float(int(affordable // float(fill["price"]) // MIN_LOT_SIZE) * MIN_LOT_SIZE))
                if shares <= 0:
                    continue
                recalculated = estimate_trade_costs(pd.DataFrame([{**fill.to_dict(), "target_shares": shares}]))
                notional = float(recalculated.iloc[0]["trade_notional"])
                cost = float(recalculated.iloc[0]["total_cost"])
                self.cash -= notional + cost
                current = self.positions.get(symbol)
                self.positions[symbol] = Position(
                    shares=(current.shares if current else 0.0) + shares,
                    acquired_date=pd.Timestamp(date),
                )
                self.holding_days.setdefault(symbol, 0)
                self._update_lifecycle_on_buy(symbol, date=date, price=float(fill["price"]), shares=shares, current=current)
            else:
                current = self.positions.get(symbol)
                shares = min(shares, current.shares if current else 0.0)
                if shares <= 0:
                    continue
                self.cash += notional - cost
                remaining = current.shares - shares
                if remaining <= 1e-12:
                    self.positions.pop(symbol, None)
                    self.holding_days.pop(symbol, None)
                    self.position_lifecycle.pop(symbol, None)
                else:
                    self.positions[symbol] = Position(remaining, current.acquired_date)
            fill_map[order_id] = shares
            record = fill.to_dict()
            record.update({"executed_shares": shares, "trade_notional": notional, "total_cost": cost, "order_id": order_id})
            self.execution_rows.append(record)
            if str(fill["side"]) == "sell" and str(fill.get("reason")) == "alpha_collapse_consensus":
                self._pending_alpha_collapse_exits.append(
                    {
                        "decision_id": fill.get("decision_id"),
                        "symbol": symbol,
                        "exit_date": pd.Timestamp(date),
                        "exit_price": float(fill["price"]),
                    }
                )
        self.engine.settle_pending_orders(date, fills=fill_map, blocked_symbols=blocked_symbols)

    def _prune_empty_positions(self, *, min_shares: float = 1e-9) -> None:
        empty_symbols = [
            symbol
            for symbol, position in self.positions.items()
            if position is None or float(position.shares) <= float(min_shares)
        ]
        for symbol in empty_symbols:
            self.positions.pop(symbol, None)
            self.holding_days.pop(symbol, None)

    def _record_exposure(self, date, daily):
        rows = []
        locked_symbols = self.engine.pending_orders.locked_symbols()
        total_position_value = 0.0
        for symbol, position in self.positions.items():
            mark = self.price_ledger.mark(symbol, as_of=date)
            price = float(mark.price) if mark is not None else 0.0
            market_value = float(position.shares) * price
            total_position_value += market_value
            lifecycle = self._mark_lifecycle(symbol, date=date, price=price)
            rows.append(
                {
                    "symbol": symbol,
                    "shares": position.shares,
                    "price": price,
                    "market_value": market_value,
                    **lifecycle,
                    "lock_days": self._symbol_lock_days(symbol) if symbol in locked_symbols else 0,
                    "stale_days": mark.stale_days if mark is not None else pd.NA,
                    "valuation_source": mark.valuation_source if mark is not None else "missing_mark",
                    "stale_haircut_ratio": mark.stale_haircut_ratio if mark is not None else 1.0,
                }
            )
        snapshot = build_exposure_snapshot(
            pd.DataFrame(rows, columns=["symbol", "shares", "price", "lock_days"]),
            cash=self.cash,
            target_exposure=0.0,
        )
        nominal_values = pd.Series(
            [float(row["shares"]) * float(row["price"]) for row in rows],
            dtype=float,
        )
        invested_value = float(total_position_value)
        sleeve_weights = (
            nominal_values / invested_value
            if invested_value > 0 and not nominal_values.empty
            else pd.Series(dtype=float)
        )
        nominal_nav = float(snapshot.get("nominal_nav", 0.0) or 0.0)
        account_weights = (
            nominal_values / nominal_nav
            if nominal_nav > 0 and not nominal_values.empty
            else pd.Series(dtype=float)
        )
        sorted_sleeve_weights = sleeve_weights.sort_values(ascending=False).reset_index(drop=True)
        sorted_account_weights = account_weights.sort_values(ascending=False).reset_index(drop=True)
        snapshot["top1_sleeve_weight"] = float(sorted_sleeve_weights.iloc[0]) if len(sorted_sleeve_weights) else 0.0
        snapshot["top5_sleeve_weight_sum"] = float(sorted_sleeve_weights.head(5).sum()) if len(sorted_sleeve_weights) else 0.0
        sleeve_weight_square_sum = float(sorted_sleeve_weights.pow(2).sum()) if len(sorted_sleeve_weights) else 0.0
        snapshot["sleeve_effective_n"] = float(1.0 / sleeve_weight_square_sum) if sleeve_weight_square_sum > 0 else 0.0
        snapshot["top1_account_weight"] = float(sorted_account_weights.iloc[0]) if len(sorted_account_weights) else 0.0
        snapshot["top5_account_weight_sum"] = float(sorted_account_weights.head(5).sum()) if len(sorted_account_weights) else 0.0
        account_weight_square_sum = float(sorted_account_weights.pow(2).sum()) if len(sorted_account_weights) else 0.0
        snapshot["account_effective_n"] = float(1.0 / account_weight_square_sum) if account_weight_square_sum > 0 else 0.0
        snapshot["top1_weight"] = snapshot["top1_sleeve_weight"]
        snapshot["top5_weight_sum"] = snapshot["top5_sleeve_weight_sum"]
        snapshot["effective_n"] = snapshot["sleeve_effective_n"]
        snapshot["weight_basis"] = "sleeve_weight_legacy"
        snapshot["holding_count"] = int(len(sorted_sleeve_weights))
        snapshot.update({"date": pd.Timestamp(date), "decision_id": f"gov_{pd.Timestamp(date).strftime('%Y%m%d')}", "safety_sell_flow_impact_estimate": 0.0})
        snapshot["stale_price_position_count"] = sum(int(row["valuation_source"] == "last_known_close") for row in rows)
        snapshot["missing_price_position_count"] = sum(int(row["valuation_source"] == "missing_mark") for row in rows)
        snapshot["cash"] = float(self.cash)
        snapshot["invested_value"] = float(total_position_value)
        self._last_position_mark_rows = rows
        if rows and not self.shadow_fast_mode:
            invested_nav = max(float(total_position_value), 1e-12)
            account_nav = max(nominal_nav, 1e-12)
            for row in rows:
                sleeve_weight = float(row["market_value"]) / invested_nav if invested_nav > 0 else 0.0
                account_weight = float(row["market_value"]) / account_nav if account_nav > 0 else 0.0
                self.holdings_rows.append(
                    {
                        "date": pd.Timestamp(date),
                        "decision_id": snapshot["decision_id"],
                        "symbol": row["symbol"],
                        "shares": float(row["shares"]),
                        "price": float(row["price"]),
                        "market_value": float(row["market_value"]),
                        "account_weight": account_weight,
                        "sleeve_weight": sleeve_weight,
                        "portfolio_exposure": float(total_position_value) / account_nav if account_nav > 0 else 0.0,
                        "weight": sleeve_weight,
                        "weight_basis": "sleeve_weight_legacy",
                        "entry_date": row.get("entry_date", pd.NaT),
                        "entry_price": row.get("entry_price", pd.NA),
                        "unrealized_return": row.get("unrealized_return", pd.NA),
                        "mfe": row.get("mfe", pd.NA),
                        "mae": row.get("mae", pd.NA),
                        "giveback_from_peak": row.get("giveback_from_peak", pd.NA),
                        "profit_giveback_flag": row.get("profit_giveback_flag", False),
                        "post_entry_failure_flag": row.get("post_entry_failure_flag", False),
                        "lock_days": int(row["lock_days"]),
                        "stale_days": row["stale_days"],
                        "valuation_source": row["valuation_source"],
                        "stale_haircut_ratio": row["stale_haircut_ratio"],
                    }
                )
        self.exposure_rows.append(snapshot)
        return snapshot

    def _register_orders(self, orders, daily, nominal_nav):
        if orders.empty:
            return
        prices = daily.set_index("symbol")["close_nominal"]
        for _, order in orders.iterrows():
            symbol = str(order["symbol"])
            mark = self.price_ledger.mark(symbol, as_of=order["execution_date"] - pd.offsets.BDay(1))
            if symbol in prices.index:
                order_price = float(prices.at[symbol])
            elif mark is not None:
                order_price = float(mark.price)
            else:
                continue
            shares = abs(float(order["delta_weight"])) * float(nominal_nav) / order_price
            shares = float(int(shares // MIN_LOT_SIZE) * MIN_LOT_SIZE)
            if shares <= 0:
                continue
            payload = {
                "decision_id": order["decision_id"],
                "symbol": symbol,
                "side": order["side"],
                "reason": order["reason"],
                "priority": int(order["priority"]),
                "created_date": order["execution_date"] - pd.offsets.BDay(1),
                "target_shares": shares,
            }
            if order["side"] == "sell":
                self.engine.pending_orders.upsert_sell_intent(payload)
            else:
                self.engine.pending_orders.add_order(payload)

    def _current_weights(self, daily, nominal_nav):
        if nominal_nav <= 0:
            return {}
        weights = {}
        for symbol, position in self.positions.items():
            mark = self.price_ledger.mark(symbol, as_of=daily["date"].iloc[0])
            if mark is not None:
                weights[symbol] = position.shares * float(mark.price) / nominal_nav
        return weights

    def _get_regime_params(self, date):
        """Get regime-adjusted parameters for the current date."""
        if not self.enable_market_regime_policy or self.market_regime_policy is None:
            return None
        date_key = pd.Timestamp(date)
        if date_key in self._regime_params_cache:
            return self._regime_params_cache[date_key]
        try:
            params_dict = self.market_regime_policy.get_params_dict(
                self.features,
                date_key,
                benchmark_symbol=MARKET_REGIME_BENCHMARK_SYMBOL,
            )
            self._current_regime = params_dict.get("regime", "bear")
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
                regime_name=params_dict.get("regime", "bear"),
            )
            self._regime_params_cache[date_key] = params
            return params
        except Exception:
            self._regime_params_cache[date_key] = None
            return None

    def _allow_normal_rebalance(self, date, day_index):
        if self._normal_rebalance_dates:
            return pd.Timestamp(date) in self._normal_rebalance_dates
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
        exposure = self.exposure_rows[-1]
        marked_position_value = sum(
            float(row["shares"]) * float(row["price"])
            for row in self._last_position_mark_rows
        )
        independently_rebuilt_nav = float(self.cash) + marked_position_value
        reconciliation_error = float(exposure["nominal_nav"]) - independently_rebuilt_nav
        self.account_audit_rows.append(
            {
                "date": pd.Timestamp(date),
                "decision_id": exposure["decision_id"],
                "cash": float(self.cash),
                "marked_position_value": marked_position_value,
                "nominal_nav": float(exposure["nominal_nav"]),
                "independently_rebuilt_nav": independently_rebuilt_nav,
                "liquidatable_nav": float(exposure["liquidatable_nav"]),
                "reconciliation_error": reconciliation_error,
                "reconciliation_passed": abs(reconciliation_error) <= 1e-8,
                "stale_price_position_count": exposure["stale_price_position_count"],
                "missing_price_position_count": exposure["missing_price_position_count"],
            }
        )

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
        returns = returns.dropna(axis=1, thresh=max(int(lookback_days * 0.50), 10)).dropna(how="all")
        if returns.shape[1] < 2:
            return pd.DataFrame()
        return returns.cov()

    def _latest_price_frame_for_trade_pairing(self, execution_ledger: pd.DataFrame) -> pd.DataFrame:
        if execution_ledger is None or execution_ledger.empty or "symbol" not in execution_ledger.columns:
            return pd.DataFrame(columns=["date", "symbol", "trade_close"])
        price_col = "trade_close" if "trade_close" in self.features.columns else "close"
        required = {"date", "symbol", price_col}
        if not required.issubset(set(self.features.columns)):
            return pd.DataFrame(columns=["date", "symbol", "trade_close"])
        symbols = set(execution_ledger["symbol"].astype(str).dropna().unique())
        if not symbols:
            return pd.DataFrame(columns=["date", "symbol", "trade_close"])
        data = self.features.loc[
            self.features["symbol"].astype(str).isin(symbols),
            ["date", "symbol", price_col],
        ].copy()
        if price_col != "trade_close":
            data = data.rename(columns={price_col: "trade_close"})
        data["date"] = pd.to_datetime(data["date"], errors="coerce")
        data["trade_close"] = pd.to_numeric(data["trade_close"], errors="coerce")
        return data.dropna(subset=["date", "symbol", "trade_close"])

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
        latest_risk_symbol_count = int(_safe_float(latest.get("risk_symbol_count"), default=0.0))
        actual_target_ratio = _recent_actual_target_ratio(self.exposure_rows)

        reasons = []
        if closed_trade_count < int(GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_TRADES):
            reasons.append("insufficient_closed_trades")
        if not (pd.notna(profit_factor) and profit_factor >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_PROFIT_FACTOR)):
            reasons.append("profit_factor_below_threshold")
        if realized_pnl <= float(GOVERNANCE_HIGH_EXPOSURE_MIN_REALIZED_PNL):
            reasons.append("realized_pnl_not_positive")
        payoff_or_win_ok = (
            (pd.notna(payoff_ratio) and payoff_ratio >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_PAYOFF_RATIO))
            or (pd.notna(closed_trade_win_rate) and closed_trade_win_rate >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_WIN_RATE))
        )
        if not payoff_or_win_ok:
            reasons.append("payoff_and_win_rate_below_threshold")
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
            capital_profile=self.governance_variant,
        )
        return summary

    def _save(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        saved = self.engine.save(self.output_dir)
        extra = {
            "governance_daily_result": pd.DataFrame(self.exposure_rows),
            "governance_holdings_ledger": pd.DataFrame(self.holdings_rows),
            "governance_execution_ledger": pd.DataFrame(self.execution_rows),
            "governance_reward_ledger": pd.DataFrame(self.reward_rows),
            "governance_entry_confirmation_ledger": pd.DataFrame(self.entry_confirmation_rows),
            "governance_factor_weight_ledger": pd.DataFrame(self.factor_weight_rows),
            "governance_alpha_proposals": pd.concat(self.alpha_rows, ignore_index=True) if self.alpha_rows else pd.DataFrame(),
            "governance_alpha_collapse_exit_diagnostics": pd.DataFrame(self.alpha_collapse_exit_rows),
            "governance_account_audit_ledger": pd.DataFrame(self.account_audit_rows),
            "governance_corporate_action_ledger": self.corporate_actions.audit_frame(),
        }
        trade_pairs, open_positions, trade_summary = build_trade_pairing_ledgers(
            extra["governance_execution_ledger"],
            latest_prices=self._latest_price_frame_for_trade_pairing(extra["governance_execution_ledger"]),
            capital_profile=self.governance_variant,
        )
        extra["governance_trade_pairs"] = trade_pairs
        extra["governance_open_positions"] = open_positions
        extra["governance_trade_pair_summary"] = pd.DataFrame([trade_summary])
        extra["governance_pnl_by_sell_reason"] = _pnl_by_sell_reason(trade_pairs)
        extra["governance_attribution_ledger"] = build_governance_attribution(
            daily_result=extra["governance_daily_result"],
            feature_data=self.features,
            benchmark_symbol=self.engine.safety_agent.proxy_symbol,
            factor_weight_ledger=extra["governance_factor_weight_ledger"],
        )
        extra["governance_bucket_attribution"] = build_bucket_attribution(extra["governance_attribution_ledger"])
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
        for name, frame in extra.items():
            path = self.output_dir / f"{name}.csv"
            frame.to_csv(path, index=False, encoding="utf-8-sig")
            saved[name] = path
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
        )
        summary_path = (
            GOVERNANCE_SUMMARY_CSV
            if self.output_dir.resolve() == Path(GOVERNANCE_OUTPUT_DIR).resolve()
            else self.output_dir / "governance_strategy_summary.csv"
        )
        governance_summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
        saved["governance_strategy_summary"] = summary_path
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
        shadow_diagnostics = build_shadow_factor_diagnostics(
            self.engine.ledgers.frame("shadow_portfolio_ledger"),
            reputation_ledger=self.engine.ledgers.frame("reputation_ledger"),
        )
        if not shadow_diagnostics.empty:
            shadow_csv_path = self.output_dir / "governance_shadow_factor_diagnostics.csv"
            shadow_md_path = self.output_dir / "governance_shadow_factor_diagnostics.md"
            shadow_diagnostics.to_csv(shadow_csv_path, index=False, encoding="utf-8-sig")
            shadow_md_path.write_text(
                render_shadow_factor_diagnostics_markdown(shadow_diagnostics),
                encoding="utf-8",
            )
            saved["governance_shadow_factor_diagnostics"] = shadow_csv_path
            saved["governance_shadow_factor_diagnostics_report"] = shadow_md_path
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
                feature_data=self.features,
                output_dir=self.output_dir,
            )
        )
        return saved

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
    ):
        if daily_result.empty:
            return pd.DataFrame(
                [
                    {
                        "strategy": self.governance_variant,
                        "strategy_source": "governance",
                        "weighting_mode": "dynamic_governance",
                    }
                ]
            )
        data = daily_result.copy()
        safety = safety_ledger.copy()
        execution = execution_ledger.copy()
        constraint = constraint_ledger.copy()
        exposure_cap = pd.to_numeric(safety.get("exposure_cap", pd.Series(dtype=float)), errors="coerce")
        freeze_mask = exposure_cap.fillna(1.0) <= 0.0
        deleverage_mask = exposure_cap.fillna(1.0) < 1.0
        confirmed_crisis_mask = safety.get("risk_level", pd.Series(dtype=object)).astype(str).eq("crisis")
        confirmed_high_mask = safety.get("risk_level", pd.Series(dtype=object)).astype(str).eq("high")
        actual_forced_sell_days = int(
            execution.loc[
                execution.get("reason", pd.Series(dtype=object)).astype(str).eq("safety_deleveraging"),
                "trade_date" if "trade_date" in execution.columns else "execution_date",
            ].nunique()
        ) if not execution.empty and "reason" in execution.columns else 0
        participation_rate = pd.to_numeric(execution.get("participation_rate", pd.Series(dtype=float)), errors="coerce")
        capacity_passed = pd.to_numeric(execution.get("capacity_passed", pd.Series(dtype=float)), errors="coerce")
        turnover_budget = pd.to_numeric(constraint.get("normal_turnover_weight", pd.Series(dtype=float)), errors="coerce")
        target_exposure = pd.to_numeric(data.get("target_exposure", pd.Series(dtype=float)), errors="coerce")
        degradation_flags = []
        if bool(pd.to_numeric(safety.get("degraded", pd.Series(dtype=float)), errors="coerce").fillna(0.0).astype(bool).any()):
            degradation_flags.append("benchmark_unavailable")
        nominal_nav_series = pd.to_numeric(data["nominal_nav"], errors="coerce").dropna()
        liquidatable_nav_series = pd.to_numeric(data["liquidatable_nav"], errors="coerce").dropna()
        initial_nav = float(nominal_nav_series.iloc[0])
        final_liquidatable_nav = float(liquidatable_nav_series.iloc[-1])
        daily_returns = liquidatable_nav_series.pct_change(fill_method=None).dropna()
        trading_days = int(len(liquidatable_nav_series))
        total_return = final_liquidatable_nav / initial_nav - 1.0 if initial_nav > 0 else pd.NA
        annual_return = (
            float((1.0 + total_return) ** (252.0 / max(trading_days - 1, 1)) - 1.0)
            if trading_days > 1 and pd.notna(total_return)
            else pd.NA
        )
        annual_volatility = (
            float(daily_returns.std(ddof=0) * (252.0 ** 0.5))
            if not daily_returns.empty
            else pd.NA
        )
        sharpe = (
            float(daily_returns.mean() / daily_returns.std(ddof=0) * (252.0 ** 0.5))
            if len(daily_returns) >= 2 and float(daily_returns.std(ddof=0)) > 1e-12
            else pd.NA
        )
        running_peak = liquidatable_nav_series.cummax()
        drawdown = liquidatable_nav_series / running_peak - 1.0
        max_drawdown = float(drawdown.min()) if not drawdown.empty else pd.NA
        win_rate = float((daily_returns > 0).mean()) if not daily_returns.empty else pd.NA
        freeze_period_lengths = _contiguous_true_lengths(freeze_mask)
        deleverage_period_lengths = _contiguous_true_lengths(deleverage_mask)
        freeze_exposure_caps = exposure_cap[freeze_mask].dropna().tolist()
        freeze_target_exposures = target_exposure[freeze_mask].dropna().tolist()
        deleverage_exposure_caps = exposure_cap[deleverage_mask].dropna().tolist()
        deleverage_target_exposures = target_exposure[deleverage_mask].dropna().tolist()
        reputation_history = self.reputation.history_frame()
        latest_reputation = (
            reputation_history.sort_values(["date", "model_name"]).groupby("model_name", as_index=False).tail(1)
            if not reputation_history.empty
            else pd.DataFrame()
        )
        latest_trading_day_index = int(
            pd.to_numeric(latest_reputation.get("trading_day_index"), errors="coerce").dropna().max()
        ) if not latest_reputation.empty else -1
        reputation_window_observed_days = max(latest_trading_day_index + 1, 0)
        reputation_window_ready = bool(reputation_window_observed_days >= int(GOVERNANCE_REPUTATION_WARMUP_DAYS))
        ml_weight_distinction = float(
            pd.to_numeric(latest_reputation.get("model_weight_distinction"), errors="coerce").dropna().max()
        ) if not latest_reputation.empty else 0.0
        if not self.enable_reputation:
            ml_weight_state = "equal_weight_reputation_disabled"
        elif not reputation_window_ready:
            ml_weight_state = "warmup_equal_weight_pending"
        elif ml_weight_distinction > 1e-9:
            ml_weight_state = "reputation_weighted_active"
        else:
            ml_weight_state = "reputation_ready_flat_weights"
        attribution = attribution_ledger.copy() if attribution_ledger is not None else pd.DataFrame()
        if not attribution.empty:
            avg_actual_exposure = _safe_numeric_mean(attribution.get("actual_exposure"))
            final_account_net_value = _safe_last(attribution.get("account_net_value"), default=1.0)
            final_invested_net_value = _safe_last(attribution.get("invested_capital_net_value"), default=1.0)
            final_valid_invested_net_value = _safe_last(attribution.get("valid_invested_capital_net_value"), default=1.0)
            final_holding_portfolio_net_value = _safe_last(attribution.get("holding_portfolio_net_value"), default=1.0)
            final_benchmark_net_value = _safe_last(attribution.get("benchmark_net_value"), default=1.0)
            final_excess_net_value = _safe_last(attribution.get("excess_net_value"), default=1.0)
            final_invested_excess_net_value = _safe_last(attribution.get("invested_excess_net_value"), default=1.0)
            final_valid_invested_excess_net_value = _safe_last(attribution.get("valid_invested_excess_net_value"), default=1.0)
            final_holding_excess_net_value = _safe_last(attribution.get("holding_portfolio_excess_net_value"), default=1.0)
            invested_capital_return = final_invested_net_value - 1.0
            valid_invested_capital_return = final_valid_invested_net_value - 1.0
            holding_portfolio_return = final_holding_portfolio_net_value - 1.0
            benchmark_total_return = final_benchmark_net_value - 1.0
            benchmark_excess_return = final_excess_net_value - 1.0
            invested_excess_return = final_invested_excess_net_value - 1.0
            valid_invested_excess_return = final_valid_invested_excess_net_value - 1.0
            holding_portfolio_excess_return = final_holding_excess_net_value - 1.0
            invested_capital_max_drawdown = float(pd.to_numeric(attribution.get("invested_capital_drawdown"), errors="coerce").dropna().min()) if not pd.to_numeric(attribution.get("invested_capital_drawdown"), errors="coerce").dropna().empty else pd.NA
            valid_invested_capital_max_drawdown = float(pd.to_numeric(attribution.get("valid_invested_capital_drawdown"), errors="coerce").dropna().min()) if not pd.to_numeric(attribution.get("valid_invested_capital_drawdown"), errors="coerce").dropna().empty else pd.NA
            account_return_per_exposure = float(total_return) / max(avg_actual_exposure, 1e-12) if pd.notna(total_return) else pd.NA
            avg_factor_entropy = _safe_numeric_mean(attribution.get("factor_entropy"))
            avg_factor_top1_share = _safe_numeric_mean(attribution.get("factor_top1_share"))
            benchmark_beta = _safe_last(attribution.get("benchmark_beta_full_period"), default=0.0)
            upside_capture = _safe_last(attribution.get("upside_capture_full_period"), default=0.0)
            downside_capture = _safe_last(attribution.get("downside_capture_full_period"), default=0.0)
            valid_invested_observed_days = int(pd.Series(attribution.get("valid_invested_capital_observed", [])).fillna(False).astype(bool).sum())
        else:
            avg_actual_exposure = pd.NA
            invested_capital_return = pd.NA
            valid_invested_capital_return = pd.NA
            holding_portfolio_return = pd.NA
            benchmark_total_return = pd.NA
            benchmark_excess_return = pd.NA
            invested_excess_return = pd.NA
            valid_invested_excess_return = pd.NA
            holding_portfolio_excess_return = pd.NA
            invested_capital_max_drawdown = pd.NA
            valid_invested_capital_max_drawdown = pd.NA
            account_return_per_exposure = pd.NA
            avg_factor_entropy = pd.NA
            avg_factor_top1_share = pd.NA
            benchmark_beta = pd.NA
            upside_capture = pd.NA
            downside_capture = pd.NA
            valid_invested_observed_days = 0
        bucket = bucket_attribution.copy() if bucket_attribution is not None else pd.DataFrame()
        best_holding_bucket = _best_bucket(bucket, "holding_count_bucket", "valid_invested_excess_total_return")
        best_factor_entropy_bucket = _best_bucket(bucket, "factor_entropy_bucket", "valid_invested_excess_total_return")
        quality_reports = quality_reports or {}
        calibration = quality_reports.get("governance_entry_calibration_report", pd.DataFrame())
        payoff = quality_reports.get("governance_entry_payoff_report", pd.DataFrame())
        risk_contribution = quality_reports.get("governance_risk_contribution_ledger", pd.DataFrame())
        capacity = quality_reports.get("governance_capacity_stress_report", pd.DataFrame())
        lifecycle = quality_reports.get("governance_position_lifecycle_report", pd.DataFrame())
        factor_roles = quality_reports.get("governance_factor_role_report", pd.DataFrame())
        rolling_beat = quality_reports.get("governance_rolling_beat_report", pd.DataFrame())
        validation = quality_reports.get("governance_strategy_validation_matrix", pd.DataFrame())
        rebound_diagnostics = quality_reports.get("governance_rebound_entry_diagnostics", pd.DataFrame())
        trade_summary = trade_pair_summary.copy() if trade_pair_summary is not None else pd.DataFrame()
        trade_row = trade_summary.iloc[0].to_dict() if not trade_summary.empty else {}
        closed_trade_count = int(_safe_float(trade_row.get("realized_trade_count"), default=0.0))
        closed_trade_win_rate = _safe_float(trade_row.get("closed_trade_win_rate"), default=float("nan"))
        realized_pnl = _safe_float(trade_row.get("realized_pnl"), default=0.0)
        gross_profit = _safe_float(trade_row.get("gross_profit"), default=0.0)
        gross_loss = _safe_float(trade_row.get("gross_loss"), default=0.0)
        avg_win = _safe_float(trade_row.get("avg_win"), default=float("nan"))
        avg_loss = _safe_float(trade_row.get("avg_loss"), default=float("nan"))
        payoff_ratio = _safe_float(trade_row.get("payoff_ratio"), default=float("nan"))
        profit_factor = _safe_float(trade_row.get("profit_factor"), default=float("nan"))
        open_position_count = int(_safe_float(trade_row.get("open_position_count"), default=0.0))
        pnl_by_sell_reason_text = _format_pnl_by_sell_reason(pnl_by_sell_reason)
        pwin10_ece = _calibration_ece(calibration, horizon_days=10)
        pwin10_wilson_lower = _calibration_best_wilson(calibration, horizon_days=10)
        buy_expectancy_10d = _payoff_metric(payoff, horizon_days=10, side="buy", metric="expectancy")
        buy_hit_rate_10d = _payoff_metric(payoff, horizon_days=10, side="buy", metric="hit_rate")
        sell_expectancy_10d = _payoff_metric(payoff, horizon_days=10, side="sell", metric="expectancy")
        normal_sell_expectancy_10d = _payoff_reason_metric(payoff, horizon_days=10, side="sell", reason="normal_sell", metric="expectancy")
        rebound_buy_expectancy_10d = _rebound_metric(rebound_diagnostics, diagnostic="rebound_buy_10d", metric="expectancy")
        rebound_buy_excess_10d = _rebound_metric(rebound_diagnostics, diagnostic="rebound_buy_10d", metric="avg_directional_excess_return")
        rebound_day_count = _rebound_metric(rebound_diagnostics, diagnostic="rebound_day_share", metric="sample_count")
        profit_giveback_lifecycle_flags = _safe_count_true(lifecycle.get("paper_profit_giveback_flag"))
        post_entry_failure_lifecycle_flags = _safe_count_true(lifecycle.get("post_entry_failure_flag"))
        sell_trigger_factor_count = _safe_count_true(factor_roles.get("sell_trigger_allowed"))
        risk_override_factor_count = _safe_count_true(factor_roles.get("risk_override_allowed"))
        rolling_beat_20d = _rolling_beat_metric(rolling_beat, window_days=20)
        rolling_beat_60d = _rolling_beat_metric(rolling_beat, window_days=60)
        rolling_beat_120d = _rolling_beat_metric(rolling_beat, window_days=120)
        rolling_beat_252d = _rolling_beat_metric(rolling_beat, window_days=252)
        rolling_beat_60d_2024 = _rolling_beat_metric(rolling_beat, window_days=60, segment="year_2024")
        max_risk_contribution_observed = _risk_gate_max_contribution(risk_contribution)
        capacity_10x_passed = _capacity_passed(capacity, multiplier=10)
        validation_gate_pass_ratio = _validation_pass_ratio(validation)
        validation_gate_fail_count = _validation_fail_count(validation)
        return pd.DataFrame(
            [
                {
                    "strategy": self.governance_variant,
                    "strategy_source": "governance",
                    "weighting_mode": "dynamic_governance",
                    "trading_days": trading_days,
                    "final_net_value": final_liquidatable_nav / initial_nav if initial_nav > 0 else pd.NA,
                    "total_return": total_return,
                    "annual_return": annual_return,
                    "annual_volatility": annual_volatility,
                    "sharpe": sharpe,
                    "max_drawdown": max_drawdown,
                    "win_rate": win_rate,
                    "avg_actual_exposure": avg_actual_exposure,
                    "invested_capital_return": invested_capital_return,
                    "valid_invested_capital_return": valid_invested_capital_return,
                    "holding_portfolio_return": holding_portfolio_return,
                    "benchmark_total_return": benchmark_total_return,
                    "benchmark_excess_return": benchmark_excess_return,
                    "invested_excess_return": invested_excess_return,
                    "valid_invested_excess_return": valid_invested_excess_return,
                    "holding_portfolio_excess_return": holding_portfolio_excess_return,
                    "invested_capital_max_drawdown": invested_capital_max_drawdown,
                    "valid_invested_capital_max_drawdown": valid_invested_capital_max_drawdown,
                    "account_return_per_exposure": account_return_per_exposure,
                    "benchmark_beta": benchmark_beta,
                    "upside_capture": upside_capture,
                    "downside_capture": downside_capture,
                    "valid_invested_observed_days": valid_invested_observed_days,
                    "avg_factor_entropy": avg_factor_entropy,
                    "avg_factor_top1_share": avg_factor_top1_share,
                    "best_holding_count_bucket_by_invested_excess": best_holding_bucket,
                    "best_factor_entropy_bucket_by_invested_excess": best_factor_entropy_bucket,
                    "p_win_10d_ece": pwin10_ece,
                    "p_win_10d_best_bucket_wilson_lower": pwin10_wilson_lower,
                    "buy_expectancy_10d": buy_expectancy_10d,
                    "buy_hit_rate_10d": buy_hit_rate_10d,
                    "sell_expectancy_10d": sell_expectancy_10d,
                    "normal_sell_expectancy_10d": normal_sell_expectancy_10d,
                    "closed_trade_count": closed_trade_count,
                    "closed_trade_win_rate": closed_trade_win_rate,
                    "realized_pnl": realized_pnl,
                    "gross_profit": gross_profit,
                    "gross_loss": gross_loss,
                    "avg_win": avg_win,
                    "avg_loss": avg_loss,
                    "payoff_ratio": payoff_ratio,
                    "profit_factor": profit_factor,
                    "open_position_count": open_position_count,
                    "pnl_by_sell_reason": pnl_by_sell_reason_text,
                    "rebound_buy_expectancy_10d": rebound_buy_expectancy_10d,
                    "rebound_buy_excess_10d": rebound_buy_excess_10d,
                    "rebound_day_count": rebound_day_count,
                    "profit_giveback_lifecycle_flags": profit_giveback_lifecycle_flags,
                    "post_entry_failure_lifecycle_flags": post_entry_failure_lifecycle_flags,
                    "sell_trigger_factor_count": sell_trigger_factor_count,
                    "risk_override_factor_count": risk_override_factor_count,
                    "rolling_beat_ratio_20d": rolling_beat_20d,
                    "rolling_beat_ratio_60d": rolling_beat_60d,
                    "rolling_beat_ratio_120d": rolling_beat_120d,
                    "rolling_beat_ratio_252d": rolling_beat_252d,
                    "rolling_beat_ratio_60d_2024": rolling_beat_60d_2024,
                    "max_risk_contribution_observed": max_risk_contribution_observed,
                    "capacity_10x_passed": capacity_10x_passed,
                    "validation_gate_pass_ratio": validation_gate_pass_ratio,
                    "validation_gate_fail_count": validation_gate_fail_count,
                    "high_exposure_research_gate": bool(
                        closed_trade_count >= int(GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_TRADES)
                        and pd.notna(profit_factor)
                        and float(profit_factor) >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_PROFIT_FACTOR)
                        and float(realized_pnl) > float(GOVERNANCE_HIGH_EXPOSURE_MIN_REALIZED_PNL)
                        and (
                            (pd.notna(payoff_ratio) and float(payoff_ratio) >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_PAYOFF_RATIO))
                            or (
                                pd.notna(closed_trade_win_rate)
                                and float(closed_trade_win_rate) >= float(GOVERNANCE_HIGH_EXPOSURE_MIN_CLOSED_WIN_RATE)
                            )
                        )
                        and float(max_risk_contribution_observed or 0.0) <= float(GOVERNANCE_HIGH_EXPOSURE_MAX_TOP1_RISK_CONTRIBUTION)
                        and float(validation_gate_pass_ratio or 0.0) >= 0.60
                    ),
                    "account_total_exposure": float(pd.to_numeric(data.get("actual_exposure", pd.Series(dtype=float)), errors="coerce").mean()),
                    "top1_account_weight": float(pd.to_numeric(data.get("top1_account_weight", pd.Series(dtype=float)), errors="coerce").mean()),
                    "top5_account_weight_sum": float(pd.to_numeric(data.get("top5_account_weight_sum", pd.Series(dtype=float)), errors="coerce").mean()),
                    "account_effective_n": float(pd.to_numeric(data.get("account_effective_n", pd.Series(dtype=float)), errors="coerce").mean()),
                    "top1_sleeve_weight": float(pd.to_numeric(data.get("top1_sleeve_weight", data.get("top1_weight", pd.Series(dtype=float))), errors="coerce").mean()),
                    "top5_sleeve_weight_sum": float(pd.to_numeric(data.get("top5_sleeve_weight_sum", data.get("top5_weight_sum", pd.Series(dtype=float))), errors="coerce").mean()),
                    "sleeve_effective_n": float(pd.to_numeric(data.get("sleeve_effective_n", data.get("effective_n", pd.Series(dtype=float))), errors="coerce").mean()),
                    "top1_weight": float(pd.to_numeric(data.get("top1_weight", pd.Series(dtype=float)), errors="coerce").mean()),
                    "top5_weight_sum": float(pd.to_numeric(data.get("top5_weight_sum", pd.Series(dtype=float)), errors="coerce").mean()),
                    "effective_n": float(pd.to_numeric(data.get("effective_n", pd.Series(dtype=float)), errors="coerce").mean()),
                    "weight_basis": "top*_weight/effective_n are legacy sleeve-weight fields; use account_* and sleeve_* fields",
                    "degradation_flags": "|".join(degradation_flags),
                    "degradation_count": len(degradation_flags),
                    "price_basis": "nominal_unadjusted",
                    "neutralization_mode": "not_applicable",
                    "ml_runtime_mode": "not_applicable",
                    "requested_model": "",
                    "runtime_model": "",
                    "benchmark_status": "exploratory: top_strength_30pct_equal_weight synthetic benchmark, PIT prior-day strength, not directly investable",
                    "governance_variant": self.governance_variant,
                    "safety_proxy_mode": self.engine.safety_agent.proxy_mode,
                    "exposure_cap_mode": "rule_based_safety_agent" if self.enable_safety_agent else "disabled",
                    "safety_agent_enabled": self.enable_safety_agent,
                    "reputation_enabled": self.enable_reputation,
                    "reputation_window_ready": reputation_window_ready,
                    "reputation_window_observed_days": reputation_window_observed_days,
                    "reputation_window_required_days": int(GOVERNANCE_REPUTATION_WARMUP_DAYS),
                    "ml_weight_state": ml_weight_state,
                    "ml_weight_distinction": ml_weight_distinction,
                    "sector_cap_enabled": self.enable_sector_cap,
                    "portfolio_exposure_cap": float(exposure_cap.mean()) if not exposure_cap.dropna().empty else pd.NA,
                    "turnover_budget": float(turnover_budget.mean()) if not turnover_budget.dropna().empty else pd.NA,
                    "participation_rate": float(participation_rate.mean()) if not participation_rate.dropna().empty else pd.NA,
                    "capacity_passed_ratio": float(capacity_passed.mean()) if not capacity_passed.dropna().empty else pd.NA,
                    "trading_freeze_trigger_count": int(len(freeze_period_lengths)),
                    "trading_freeze_total_rebalance_periods": int(freeze_mask.sum()),
                    "trading_freeze_period_lengths": ",".join(str(length) for length in freeze_period_lengths) if freeze_period_lengths else "",
                    "trading_freeze_min_exposure_cap": min(freeze_exposure_caps) if freeze_exposure_caps else pd.NA,
                    "trading_freeze_min_target_exposure": min(freeze_target_exposures) if freeze_target_exposures else pd.NA,
                    "risk_confirmed_crisis_days": int(confirmed_crisis_mask.sum()),
                    "risk_confirmed_high_days": int(confirmed_high_mask.sum()),
                    "exposure_cap_below_full_days": int(deleverage_mask.sum()),
                    "actual_emergency_sell_days": actual_forced_sell_days,
                    "emergency_deleveraging_trigger_count": int(len(deleverage_period_lengths)),
                    "emergency_deleveraging_total_rebalance_periods": int(deleverage_mask.sum()),
                    "emergency_deleveraging_period_lengths": ",".join(str(length) for length in deleverage_period_lengths) if deleverage_period_lengths else "",
                    "emergency_deleveraging_min_exposure_cap": min(deleverage_exposure_caps) if deleverage_exposure_caps else pd.NA,
                    "emergency_deleveraging_min_target_exposure": min(deleverage_target_exposures) if deleverage_target_exposures else pd.NA,
                    "date_window": f"{pd.to_datetime(data['date']).min().date()} -> {pd.to_datetime(data['date']).max().date()}",
                    "composite_score": pd.NA,
                    # Registry framework metadata
                    "universe_name": self._universe_name or "unknown",
                    "universe_mode": self._universe_mode,
                    "alpha_bundle": self._alpha_bundle or "unknown",
                    "registry_version": self._registry_version or "unknown",
                }
            ]
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
    probability_bucket_mode: str = "default",
    registry_version: str | None = None,
    target_index_codes: tuple[str, ...] = (),
    require_constituents: bool = True,
    allow_fallback: bool = False,
    allowed_instrument_types: tuple[str, ...] = GOVERNANCE_ALLOWED_INSTRUMENT_TYPES,
    enable_quality_filters: bool = True,
    enable_shadow_portfolios: bool = True,
    show_live_monitor: bool = False,
) -> dict[str, Path]:
    from functions.decision_council.policy import RulesBasedPresidentPolicy

    output_dir = Path(output_dir)
    archived_path = archive_existing_governance_output(output_dir)
    if archived_path is not None:
        print(f"Archived previous governance outputs to: {archived_path}")

    effective_start = pd.Timestamp(start_date or GOVERNANCE_START_DATE) if (start_date or GOVERNANCE_START_DATE) else None
    effective_end = pd.Timestamp(end_date or GOVERNANCE_END_DATE) if (end_date or GOVERNANCE_END_DATE) else None
    filters = []
    if effective_start is not None:
        filters.append(("date", ">=", effective_start - pd.Timedelta(days=GOVERNANCE_PRELOAD_CALENDAR_DAYS)))
    if effective_end is not None:
        filters.append(("date", "<=", effective_end))
    if allowed_instrument_types:
        load_instrument_types = tuple(dict.fromkeys((*allowed_instrument_types, "etf_fund")))
        filters.append(("instrument_type", "in", list(load_instrument_types)))
    try:
        import pyarrow.parquet as pq

        available_columns = set(pq.read_schema(feature_path).names)
    except Exception:
        available_columns = set(_governance_feature_columns())
    features = pd.read_parquet(
        feature_path,
        columns=[column for column in _governance_feature_columns() if column in available_columns],
        filters=filters or None,
    )
    features = _prepare_features(features, copy=False)
    runner = GovernanceBacktestRunner(
        features,
        output_dir=output_dir,
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
        entry_confirmation_mode=entry_confirmation_mode,
        selection_weight_mode=selection_weight_mode,
        regime_overlay_mode=regime_overlay_mode,
        risk_hard_gate_enabled=risk_hard_gate_enabled,
        probability_bucket_mode=probability_bucket_mode,
        universe_name=universe_name,
        universe_mode=universe_mode,
        alpha_bundle=alpha_bundle,
        registry_version=registry_version,
        target_index_codes=target_index_codes,
        require_constituents=require_constituents,
        allow_fallback=allow_fallback,
        allowed_instrument_types=allowed_instrument_types,
        enable_quality_filters=enable_quality_filters,
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


def _safe_float(value, default=0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").dropna()
    if numeric.empty:
        return float(default)
    return float(numeric.iloc[0])


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


def _factor_primary_role(model_name: str, module: str) -> str:
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
    watch = candidates.get("post_entry_failure_watch", pd.Series(False, index=candidates.index)).fillna(False).astype(bool)
    unrealized = pd.to_numeric(candidates.get("position_unrealized_return", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    p_lower = pd.to_numeric(candidates.get("p_win_10d_wilson_lower", pd.Series(0.5, index=candidates.index)), errors="coerce").fillna(0.5)
    conservative_edge = pd.to_numeric(candidates.get("conservative_expected_edge_10d", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    alpha = pd.to_numeric(candidates.get("alpha_percentile", pd.Series(0.5, index=candidates.index)), errors="coerce").fillna(0.5)
    ret5 = pd.to_numeric(candidates.get("ret_5", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    ret20 = pd.to_numeric(candidates.get("ret_20", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    close_to_ma20 = pd.to_numeric(candidates.get("close_to_ma20", pd.Series(0.0, index=candidates.index)), errors="coerce").fillna(0.0)
    flow_count = pd.to_numeric(candidates.get("entry_orderflow_confirm_count", pd.Series(0, index=candidates.index)), errors="coerce").fillna(0)
    alpha_weak = (p_lower < 0.42) | (conservative_edge < -0.003) | (alpha < 0.45)
    trend_weak = (ret5 < -0.02) | (ret20 < -0.04) | (close_to_ma20 < -0.03)
    flow_weak = flow_count <= 1
    severe_loss = unrealized < -0.055
    return watch & (severe_loss | (alpha_weak & trend_weak) | (trend_weak & flow_weak))


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
    trailing_accuracy = _safe_float(trailing_buy_accuracy_5d, default=0.52) if trailing_buy_accuracy_5d is not None else 0.52
    block_reasons = []
    tier = "defensive"
    multiplier = 0.55

    if risk in {"crisis", "high"}:
        block_reasons.append(f"risk_level_{risk}")
        tier = "risk_capped"
        multiplier = 0.50 if risk == "high" else 0.35
    elif regime == "bull" and int(qualified_entry_count) >= 3 and float(liquidity_stress) < 0.25:
        if trailing_accuracy >= 0.44 or conservative_edge_mean >= -0.002 or pwin_lower_mean >= 0.42:
            tier = "full"
            if pwin_lower_mean >= 0.50 and conservative_edge_mean > 0.0 and calibration_trust_mean >= 0.35:
                multiplier = 1.0
            else:
                multiplier = 0.90
        else:
            block_reasons.append("weak_bull_entry_evidence")
            multiplier = 0.75
    elif regime == "rebound" and int(qualified_entry_count) >= 3 and float(liquidity_stress) < 0.22:
        tier = "rebound_confirmed"
        if pwin_lower_mean >= 0.48 and conservative_edge_mean > 0.0 and calibration_trust_mean >= 0.35:
            multiplier = 0.90
        elif pwin_lower_mean >= 0.45 and conservative_edge_mean >= -0.001:
            multiplier = 0.72
            block_reasons.append("rebound_partial_evidence")
        else:
            multiplier = 0.55
            block_reasons.append("weak_rebound_entry_evidence")
    elif regime == "neutral" and int(qualified_entry_count) >= 3 and float(liquidity_stress) < 0.25:
        tier = "normal_high"
        multiplier = 0.90 if trailing_accuracy >= 0.44 or conservative_edge_mean >= -0.002 else 0.75
    elif int(qualified_entry_count) < 2:
        block_reasons.append("too_few_confirmed_entries")
        multiplier = 0.55
    elif float(liquidity_stress) >= 0.25:
        block_reasons.append("liquidity_stress")
        multiplier = 0.65
    elif conservative_edge_mean <= -0.004 and trailing_accuracy < 0.40:
        block_reasons.append("negative_edge_and_weak_accuracy")
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
    data = feature_df.copy() if copy else feature_df
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    for target, fallback in (("open_nominal", "open"), ("close_nominal", "close")):
        if target not in data.columns:
            data[target] = data[fallback]
    for column in ("rough_limit_up", "rough_limit_down", "abnormal_jump"):
        if column not in data.columns:
            data[column] = False
    if "is_trading" not in data.columns:
        data["is_trading"] = True
    data.sort_values(["date", "symbol"], inplace=True)
    data.reset_index(drop=True, inplace=True)
    return data


def _governance_feature_columns():
    columns = [
        "date",
        "symbol",
        "instrument_type",
        "open",
        "close",
        "open_nominal",
        "close_nominal",
        "amount",
        "amount_ma20",
        "is_trading",
        "rough_limit_up",
        "rough_limit_down",
        "abnormal_jump",
        "ret_5",
        "ret_20",
        "score_mom_lowvol",
        "close_to_ma20",
        "volatility_20",
        "index_pool_codes",
        "in_target_index_pool",
        "score_orderflow_amount_shock",
        "score_orderflow_close_drive",
        "score_orderflow_accumulation",
        "score_orderflow_efficiency",
        "score_eod_close_strength",
    ]
    columns.extend(GOVERNANCE_ALPHA_MODEL_FEATURES.values())
    return list(dict.fromkeys(columns))
