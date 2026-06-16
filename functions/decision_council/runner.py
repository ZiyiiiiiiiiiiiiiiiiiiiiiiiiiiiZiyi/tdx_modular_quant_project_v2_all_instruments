"""Historical daily runner for the phase-one rules-based governance strategy."""
from __future__ import annotations

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
from functions.decision_council.engine import PhaseOneDecisionCouncilEngine
from functions.decision_council.leakage import validate_governance_split
from functions.decision_council.market_regime_policy import MarketRegimePolicy
from functions.decision_council.proposals import build_daily_candidates
from functions.decision_council.plots import save_governance_diagnostic_plots
from functions.decision_council.monitoring import evaluate_daily_rollback
from functions.decision_council.reputation import ReputationLedger
from functions.execution.cost_model import estimate_trade_costs
from functions.execution.order_simulator import simulate_order_book
from functions.pricing.feature_leakage_audit import audit_feature_columns
from functions.pipeline_cache import file_fingerprint
from functions.report_builder import build_strategy_report, save_strategy_report


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
        data_fingerprints=None,
        policy=None,
        enable_reputation: bool = True,
        corporate_action_processor=None,
        governance_variant: str = "rules_based_president",
        enable_sector_cap: bool = False,
        enable_safety_agent: bool = True,
        enable_market_regime_policy: bool = ENABLE_MARKET_REGIME_POLICY,
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
        self.price_ledger = LastKnownPriceLedger()
        self.corporate_actions = corporate_action_processor or ExploratoryCorporateActionProcessor.from_default_artifact()
        self.account_audit_rows = []
        self._last_position_mark_rows = []
        self.positions: dict[str, Position] = {}
        self.holding_days: dict[str, int] = {}
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
        self.execution_rows = []
        self.exposure_rows = []
        self.reward_rows = []
        self.alpha_rows = []
        self.alpha_collapse_exit_rows = []
        self._pending_alpha_collapse_exits = []
        self._normal_rebalance_dates = frozenset()
        # Market regime policy for dynamic parameter adjustment
        self.market_regime_policy = MarketRegimePolicy() if self.enable_market_regime_policy else None
        self._current_regime = "bear"  # Default to bear
        self._regime_params_cache = None
        self._record_leakage_audit()

    def run(
        self,
        *,
        start_date=None,
        end_date=None,
        max_days: int | None = None,
        show_progress: bool = True,
        show_live_monitor: bool = False,
    ) -> dict[str, Path]:
        dates = pd.Index(self.features["date"].drop_duplicates().sort_values())
        if start_date is not None:
            dates = dates[dates >= pd.Timestamp(start_date)]
        if end_date is not None:
            dates = dates[dates <= pd.Timestamp(end_date)]
        if max_days is not None:
            dates = dates[: int(max_days)]
        
        total_days = len(dates)
        weekly = pd.Series(dates, index=dates).groupby(dates.to_period("W-FRI")).max()
        self._normal_rebalance_dates = frozenset(pd.Timestamp(date) for date in weekly)
        shadows = self._build_shadow_runners() if self.enable_shadow_portfolios else {}
        
        # Initialize progress tracker
        progress = ProgressTracker(total_days, "Governance Backtest") if show_progress else None
        live_monitor = None
        if show_live_monitor and total_days:
            from functions.decision_council.live_monitor import GovernanceLiveMonitor

            live_monitor = GovernanceLiveMonitor(total_days=total_days, initial_nav=self.initial_cash)
        
        try:
            for day_index, date in enumerate(dates):
                shadow_rewards = {}
                for model_name, shadow in shadows.items():
                    reward = shadow.step(date, day_index)
                    if reward is not None:
                        shadow_rewards[model_name] = reward["reward"]
                self.step(date, day_index, reputation_rewards=shadow_rewards)

                exposure = self.exposure_rows[-1] if self.exposure_rows else {}
                if live_monitor is not None:
                    live_monitor.update(date=date, exposure=exposure, day_index=day_index)

                # Update progress
                if progress:
                    date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
                    nav = exposure.get("nominal_nav", 0)
                    holding_count = len(self.positions)
                    progress.update(f"Date: {date_str} | NAV: {nav:,.0f} | Holdings: {holding_count}")
        finally:
            if live_monitor is not None:
                live_monitor.close()
        
        for model_name, shadow in shadows.items():
            shadow_frame = pd.DataFrame(shadow.exposure_rows)
            if not shadow_frame.empty:
                shadow_frame.insert(0, "model_name", model_name)
                self.engine.record_shadow_portfolio(shadow_frame)
        return self._save()

    def step(self, date, day_index: int, *, reputation_rewards: dict[str, float] | None = None):
        daily = self.features[self.features["date"] == pd.Timestamp(date)].copy()
        self.price_ledger.update(daily, as_of=date)
        self.cash, corporate_action_summary = self.corporate_actions.apply(
            as_of=date,
            positions=self.positions,
            cash=self.cash,
        )
        self._execute_pending(date, daily)
        self._mature_alpha_collapse_diagnostics(date)
        exposure = self._record_exposure(date, daily)
        matured_reward = self._mature_reward(date)
        reputation_snapshot = self.reputation.record_rewards(
            reputation_rewards or {},
            as_of=date,
            trading_day_index=day_index,
        )
        self.engine.record_reputation(reputation_snapshot)
        
        # Get regime-adjusted parameters if market regime policy is enabled
        regime_params = self._get_regime_params(date)
        current_turnover_budget = regime_params.default_turnover_budget if regime_params else GOVERNANCE_DEFAULT_TURNOVER_BUDGET
        current_min_score_percentile = regime_params.min_score_percentile if regime_params else None
        
        candidates, proposals = build_daily_candidates(
            daily,
            reputation_weights=(
                self.reputation.weights()
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
        )
        proposals["decision_date"] = date
        audit_symbols = set(candidates.head(GOVERNANCE_ALPHA_CANDIDATE_LIMIT)["symbol"].astype(str)) | set(self.positions)
        self.alpha_rows.append(proposals[proposals["symbol"].astype(str).isin(audit_symbols)].copy())
        allow_normal_rebalance = self._allow_normal_rebalance(date, day_index)
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
        )
        self._register_orders(orders, daily, exposure["nominal_nav"])
        self.exposure_rows[-1].update(
            {
                "target_exposure": diagnostics["target_exposure"],
                "unresolved_safety_exposure": diagnostics["unresolved_safety_exposure"],
                "constraint_cash_reserve": diagnostics["constraint_cash_reserve"],
                "allow_normal_rebalance": allow_normal_rebalance,
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
        self._record_account_audit(date)
        self._advance_holding_days()
        return matured_reward

    def _build_shadow_runners(self):
        return {
            model_name: GovernanceBacktestRunner(
                self.features,
                initial_cash=self.initial_cash,
                safety_proxy_mode=self.engine.safety_agent.proxy_mode,
                output_dir=self.output_dir / "_shadow" / model_name,
                alpha_models=(model_name,),
                enable_shadow_portfolios=False,
                prepared_features=True,
                shared_safety_agent=self.engine.safety_agent,
                shared_safety_signals=self.engine.safety_signals,
                shared_manifest=self.engine.manifest,
                data_fingerprints=self.engine.manifest.get("data_fingerprints", {}),
                policy=self.engine.policy,
                enable_reputation=self.enable_reputation,
                corporate_action_processor=ExploratoryCorporateActionProcessor(self.corporate_actions.ledger),
                universe_name=self._universe_name,
                universe_mode=self._universe_mode,
                alpha_bundle=self._alpha_bundle,
                registry_version=self._registry_version,
                target_index_codes=self._target_index_codes,
                require_constituents=self._require_constituents,
                allow_fallback=self._allow_fallback,
                allowed_instrument_types=self._allowed_instrument_types,
                enable_quality_filters=self._enable_quality_filters,
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

    def _record_exposure(self, date, daily):
        rows = []
        locked_symbols = self.engine.pending_orders.locked_symbols()
        for symbol, position in self.positions.items():
            mark = self.price_ledger.mark(symbol, as_of=date)
            price = float(mark.price) if mark is not None else 0.0
            rows.append(
                {
                    "symbol": symbol,
                    "shares": position.shares,
                    "price": price,
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
        total_nav = float(snapshot["nominal_nav"])
        weights = (
            nominal_values / total_nav
            if total_nav > 0 and not nominal_values.empty
            else pd.Series(dtype=float)
        )
        sorted_weights = weights.sort_values(ascending=False).reset_index(drop=True)
        snapshot["top1_weight"] = float(sorted_weights.iloc[0]) if len(sorted_weights) else 0.0
        snapshot["top5_weight_sum"] = float(sorted_weights.head(5).sum()) if len(sorted_weights) else 0.0
        weight_square_sum = float(sorted_weights.pow(2).sum()) if len(sorted_weights) else 0.0
        snapshot["effective_n"] = float(1.0 / weight_square_sum) if weight_square_sum > 0 else 0.0
        snapshot["holding_count"] = int(len(sorted_weights))
        snapshot.update({"date": pd.Timestamp(date), "decision_id": f"gov_{pd.Timestamp(date).strftime('%Y%m%d')}", "safety_sell_flow_impact_estimate": 0.0})
        snapshot["stale_price_position_count"] = sum(int(row["valuation_source"] == "last_known_close") for row in rows)
        snapshot["missing_price_position_count"] = sum(int(row["valuation_source"] == "missing_mark") for row in rows)
        self._last_position_mark_rows = rows
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
        try:
            params_dict = self.market_regime_policy.get_params_dict(
                self.features,
                pd.Timestamp(date),
                benchmark_symbol=MARKET_REGIME_BENCHMARK_SYMBOL,
            )
            self._current_regime = params_dict.get("regime", "bear")
            from functions.decision_council.market_regime_policy import RegimeParams
            return RegimeParams(
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
            )
        except Exception:
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
        latest_types = (
            self.features[["symbol", "instrument_type"]]
            .dropna()
            .drop_duplicates("symbol", keep="last")
            .set_index("symbol")["instrument_type"]
            .astype(str)
        )
        return frozenset(
            symbol
            for symbol in self.positions
            if symbol in latest_types.index
            and latest_types.at[symbol] not in GOVERNANCE_ALLOWED_INSTRUMENT_TYPES
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

    def _save(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        saved = self.engine.save(self.output_dir)
        extra = {
            "governance_daily_result": pd.DataFrame(self.exposure_rows),
            "governance_execution_ledger": pd.DataFrame(self.execution_rows),
            "governance_reward_ledger": pd.DataFrame(self.reward_rows),
            "governance_alpha_proposals": pd.concat(self.alpha_rows, ignore_index=True) if self.alpha_rows else pd.DataFrame(),
            "governance_alpha_collapse_exit_diagnostics": pd.DataFrame(self.alpha_collapse_exit_rows),
            "governance_account_audit_ledger": pd.DataFrame(self.account_audit_rows),
            "governance_corporate_action_ledger": self.corporate_actions.audit_frame(),
        }
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
        saved.update(
            save_governance_diagnostic_plots(
                daily_result=extra["governance_daily_result"],
                reputation_ledger=self.engine.ledgers.frame("reputation_ledger"),
                safety_ledger=self.engine.ledgers.frame("safety_decision_ledger"),
                execution_ledger=extra["governance_execution_ledger"],
                feature_data=self.features,
                output_dir=self.output_dir,
            )
        )
        return saved

    def _build_governance_summary(self, *, daily_result, execution_ledger, safety_ledger, constraint_ledger):
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
                    "top1_weight": float(pd.to_numeric(data.get("top1_weight", pd.Series(dtype=float)), errors="coerce").mean()),
                    "top5_weight_sum": float(pd.to_numeric(data.get("top5_weight_sum", pd.Series(dtype=float)), errors="coerce").mean()),
                    "effective_n": float(pd.to_numeric(data.get("effective_n", pd.Series(dtype=float)), errors="coerce").mean()),
                    "degradation_flags": "|".join(degradation_flags),
                    "degradation_count": len(degradation_flags),
                    "price_basis": "nominal_unadjusted",
                    "neutralization_mode": "not_applicable",
                    "ml_runtime_mode": "not_applicable",
                    "requested_model": "",
                    "runtime_model": "",
                    "benchmark_status": "blocked: governance benchmark proxy is safety-only, not an investable excess-return benchmark",
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
    registry_version: str | None = None,
    target_index_codes: tuple[str, ...] = (),
    require_constituents: bool = True,
    allow_fallback: bool = False,
    allowed_instrument_types: tuple[str, ...] = GOVERNANCE_ALLOWED_INSTRUMENT_TYPES,
    enable_quality_filters: bool = True,
    show_live_monitor: bool = False,
) -> dict[str, Path]:
    from functions.decision_council.policy import RulesBasedPresidentPolicy

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
        ),
        prepared_features=True,
        enable_reputation=enable_reputation,
        governance_variant=governance_variant,
        enable_sector_cap=enable_sector_cap,
        enable_safety_agent=enable_safety_agent,
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
        "ret_20",
        "score_mom_lowvol",
        "close_to_ma20",
        "volatility_20",
        "index_pool_codes",
        "in_target_index_pool",
    ]
    columns.extend(GOVERNANCE_ALPHA_MODEL_FEATURES.values())
    return list(dict.fromkeys(columns))


