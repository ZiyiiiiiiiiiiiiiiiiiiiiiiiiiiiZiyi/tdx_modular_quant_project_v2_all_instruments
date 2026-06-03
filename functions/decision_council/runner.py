"""Historical daily runner for the phase-one rules-based governance strategy."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config import (
    FEATURE_DAILY_PARQUET,
    GOVERNANCE_ALPHA_CANDIDATE_LIMIT,
    GOVERNANCE_ALPHA_MODELS,
    GOVERNANCE_ALLOWED_INSTRUMENT_TYPES,
    GOVERNANCE_DEFAULT_TOP_N,
    GOVERNANCE_DEFAULT_TURNOVER_BUDGET,
    GOVERNANCE_INITIAL_TRANSITION_DAYS,
    GOVERNANCE_INITIAL_CASH,
    GOVERNANCE_END_DATE,
    GOVERNANCE_OUTPUT_DIR,
    GOVERNANCE_PRELOAD_CALENDAR_DAYS,
    GOVERNANCE_START_DATE,
    MIN_LOT_SIZE,
    SAFETY_PROXY_MODE,
)
from functions.decision_council.accounting import build_exposure_snapshot, calculate_five_day_reward
from functions.decision_council.account_state import (
    ExploratoryCorporateActionProcessor,
    LastKnownPriceLedger,
)
from functions.decision_council.engine import PhaseOneDecisionCouncilEngine
from functions.decision_council.leakage import validate_governance_split
from functions.decision_council.proposals import build_daily_candidates
from functions.decision_council.plots import save_governance_diagnostic_plots
from functions.decision_council.monitoring import evaluate_daily_rollback
from functions.decision_council.reputation import ReputationLedger
from functions.execution.cost_model import estimate_trade_costs
from functions.execution.order_simulator import simulate_order_book
from functions.pricing.feature_leakage_audit import audit_feature_columns
from functions.pipeline_cache import file_fingerprint


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
    ):
        self.features = feature_df if prepared_features else _prepare_features(feature_df)
        self.output_dir = Path(output_dir)
        self.cash = float(initial_cash)
        self.initial_cash = float(initial_cash)
        self.alpha_models = tuple(alpha_models)
        self.enable_shadow_portfolios = bool(enable_shadow_portfolios)
        self.enable_reputation = bool(enable_reputation)
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
        self._record_leakage_audit()

    def run(self, *, start_date=None, end_date=None, max_days: int | None = None) -> dict[str, Path]:
        dates = pd.Index(self.features["date"].drop_duplicates().sort_values())
        if start_date is not None:
            dates = dates[dates >= pd.Timestamp(start_date)]
        if end_date is not None:
            dates = dates[dates <= pd.Timestamp(end_date)]
        if max_days is not None:
            dates = dates[: int(max_days)]
        weekly = pd.Series(dates, index=dates).groupby(dates.to_period("W-FRI")).max()
        self._normal_rebalance_dates = frozenset(pd.Timestamp(date) for date in weekly)
        shadows = self._build_shadow_runners() if self.enable_shadow_portfolios else {}
        for day_index, date in enumerate(dates):
            shadow_rewards = {}
            for model_name, shadow in shadows.items():
                reward = shadow.step(date, day_index)
                if reward is not None:
                    shadow_rewards[model_name] = reward["reward"]
            self.step(date, day_index, reputation_rewards=shadow_rewards)
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
            turnover_budget=GOVERNANCE_DEFAULT_TURNOVER_BUDGET,
            top_n=GOVERNANCE_DEFAULT_TOP_N,
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

    def _allow_normal_rebalance(self, date, day_index):
        if self._normal_rebalance_dates:
            return pd.Timestamp(date) in self._normal_rebalance_dates
        return int(day_index) % 5 == 0

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
        saved.update(
            save_governance_diagnostic_plots(
                daily_result=extra["governance_daily_result"],
                reputation_ledger=self.engine.ledgers.frame("reputation_ledger"),
                safety_ledger=self.engine.ledgers.frame("safety_decision_ledger"),
                output_dir=self.output_dir,
            )
        )
        return saved

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
    enable_sector_cap: bool = True,
    enable_safety_agent: bool = True,
    enable_reputation: bool = True,
) -> dict[str, Path]:
    from functions.decision_council.policy import RulesBasedPresidentPolicy

    effective_start = pd.Timestamp(start_date or GOVERNANCE_START_DATE) if (start_date or GOVERNANCE_START_DATE) else None
    effective_end = pd.Timestamp(end_date or GOVERNANCE_END_DATE) if (end_date or GOVERNANCE_END_DATE) else None
    filters = []
    if effective_start is not None:
        filters.append(("date", ">=", effective_start - pd.Timedelta(days=GOVERNANCE_PRELOAD_CALENDAR_DAYS)))
    if effective_end is not None:
        filters.append(("date", "<=", effective_end))
    features = pd.read_parquet(
        feature_path,
        columns=_governance_feature_columns(),
        filters=filters or None,
    )
    runner = GovernanceBacktestRunner(
        features,
        output_dir=output_dir,
        safety_proxy_mode=safety_proxy_mode,
        data_fingerprints={"feature_daily_parquet": file_fingerprint(feature_path)},
        policy=RulesBasedPresidentPolicy(
            enable_sector_cap=enable_sector_cap,
            enable_safety_agent=enable_safety_agent,
        ),
        enable_reputation=enable_reputation,
    )
    return runner.run(start_date=effective_start, end_date=effective_end, max_days=max_days)


def _prepare_features(feature_df):
    data = feature_df.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    for target, fallback in (("open_nominal", "open"), ("close_nominal", "close")):
        if target not in data.columns:
            data[target] = data[fallback]
    for column in ("rough_limit_up", "rough_limit_down", "abnormal_jump"):
        if column not in data.columns:
            data[column] = False
    if "is_trading" not in data.columns:
        data["is_trading"] = True
    return data.sort_values(["date", "symbol"]).reset_index(drop=True)


def _governance_feature_columns():
    return [
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
    ]
