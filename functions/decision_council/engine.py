"""Lightweight orchestration for phase-one daily governance decisions."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pandas as pd

from config import (
    GOVERNANCE_ENTRY_RANK_LIMIT,
    GOVERNANCE_HOLD_RANK_LIMIT,
    GOVERNANCE_OUTPUT_DIR,
    GOVERNANCE_PARTIAL_ADJUSTMENT_RATE,
    SAFETY_PROXY_MODE,
)
from functions.decision_council.contracts import DecisionContext
from functions.decision_council.outputs import GovernanceLedgerBundle
from functions.decision_council.pending_orders import PendingOrderBook
from functions.decision_council.policy import RulesBasedPresidentPolicy
from functions.decision_council.preflight import (
    build_environment_manifest,
    save_environment_manifest,
    validate_safety_proxy,
)
from functions.decision_council.safety import RuleBasedSafetyAgent


class PhaseOneDecisionCouncilEngine:
    """Coordinate auditable daily plans without inventing alpha predictions."""

    def __init__(
        self,
        feature_df: pd.DataFrame,
        *,
        safety_proxy_mode: str = SAFETY_PROXY_MODE,
        policy: RulesBasedPresidentPolicy | None = None,
        pending_orders: PendingOrderBook | None = None,
        ledgers: GovernanceLedgerBundle | None = None,
        safety_agent: RuleBasedSafetyAgent | None = None,
        safety_signals: pd.DataFrame | None = None,
        manifest: dict | None = None,
        copy_features: bool = True,
        data_fingerprints: dict | None = None,
    ):
        self.feature_df = feature_df.copy() if copy_features else feature_df
        self.feature_df["date"] = pd.to_datetime(self.feature_df["date"], errors="coerce")
        if safety_agent is None:
            proxy = validate_safety_proxy(self.feature_df, mode=safety_proxy_mode)
            safety_agent = RuleBasedSafetyAgent(proxy["proxy_symbol"], proxy_mode=safety_proxy_mode)
        self.safety_agent = safety_agent
        self.safety_signals = (
            safety_signals
            if safety_signals is not None
            else self.safety_agent.build_daily_signals(self.feature_df).set_index("date")
        )
        self.policy = policy or RulesBasedPresidentPolicy()
        self.pending_orders = pending_orders or PendingOrderBook()
        self.ledgers = ledgers or GovernanceLedgerBundle()
        self.manifest = manifest or build_environment_manifest(
            self.feature_df,
            safety_proxy_mode=safety_proxy_mode,
            config_values={"safety_proxy_mode": safety_proxy_mode},
            data_fingerprints=data_fingerprints,
        )

    def decide_day(
        self,
        *,
        decision_id: str,
        decision_date,
        candidates: pd.DataFrame,
        current_weights: dict[str, float],
        holding_days: dict[str, int],
        turnover_budget: float = 0.20,
        minimum_holding_days: int = 5,
        top_n: int = 20,
        allow_normal_rebalance: bool = True,
        transition_only: bool = False,
        hard_qualification_symbols=(),
        catchup_buy_budget: float = 0.0,
        catchup_allowed: bool = False,
        active_replacement_enabled: bool = True,
        active_replacement_max_pairs_per_day: int = 1,
        target_exposure_cap: float | None = None,
        covariance_matrix: pd.DataFrame | None = None,
        nav_amount: float = 1.0,
        cash_amount: float = 0.0,
        cash_buffer_amount: float = 0.0,
        per_name_structural_cap: float = 1.0,
        portfolio_stress_budget_amount: float = 1.0e18,
        control_mode: str = "normal",
        winner_add_enabled: bool = False,
        loser_add_enabled: bool = False,
        soft_exit_enabled: bool = True,
        forecast_horizon_sessions: int = 10,
        forecast_kappa: float = 0.50,
        soft_target_positions: int = 4,
        execution_cost_profile: dict | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        decision_date = pd.Timestamp(decision_date)
        if decision_date not in self.safety_signals.index:
            raise ValueError(f"No safety signal is available for {decision_date.date()}")
        safety_row = self.safety_signals.loc[decision_date]
        if isinstance(safety_row, pd.DataFrame):
            safety_row = safety_row.iloc[-1]
        safety = self.safety_agent.decide({"date": decision_date, **safety_row.to_dict()})
        raw_safety_exposure_cap = float(safety.exposure_cap)
        if target_exposure_cap is not None:
            effective_cap = min(raw_safety_exposure_cap, max(float(target_exposure_cap), 0.0))
            safety = replace(safety, exposure_cap=effective_cap)
        context = DecisionContext(
            decision_id=str(decision_id),
            decision_date=decision_date,
            candidates=candidates,
            current_weights=current_weights,
            holding_days=holding_days,
            pending_locked_symbols=self.pending_orders.locked_symbols(),
            safety=safety,
            turnover_budget=float(turnover_budget),
            minimum_holding_days=int(minimum_holding_days),
            top_n=int(top_n),
            entry_rank_limit=GOVERNANCE_ENTRY_RANK_LIMIT,
            hold_rank_limit=GOVERNANCE_HOLD_RANK_LIMIT,
            allow_normal_rebalance=bool(allow_normal_rebalance),
            partial_adjustment_rate=GOVERNANCE_PARTIAL_ADJUSTMENT_RATE,
            catchup_buy_budget=float(catchup_buy_budget),
            catchup_allowed=bool(catchup_allowed),
            transition_only=bool(transition_only),
            active_replacement_enabled=bool(active_replacement_enabled),
            active_replacement_max_pairs_per_day=max(
                int(active_replacement_max_pairs_per_day), 0
            ),
            hard_qualification_symbols=frozenset(str(symbol) for symbol in hard_qualification_symbols),
            covariance_matrix=covariance_matrix,
            nav_amount=max(float(nav_amount), 1e-12),
            cash_amount=max(float(cash_amount), 0.0),
            cash_buffer_amount=max(float(cash_buffer_amount), 0.0),
            per_name_structural_cap=min(
                max(float(per_name_structural_cap), 0.0), 1.0
            ),
            portfolio_stress_budget_amount=max(
                float(portfolio_stress_budget_amount), 0.0
            ),
            control_mode=str(control_mode or "normal").strip().lower(),
            winner_add_enabled=bool(winner_add_enabled),
            loser_add_enabled=bool(loser_add_enabled),
            soft_exit_enabled=bool(soft_exit_enabled),
            forecast_horizon_sessions=max(int(forecast_horizon_sessions), 1),
            forecast_kappa=max(float(forecast_kappa), 0.0),
            soft_target_positions=max(int(soft_target_positions), 0),
            execution_cost_profile=dict(execution_cost_profile or {}),
        )
        ideal, orders, diagnostics = self.policy.decide(context)
        diagnostics["raw_safety_exposure_cap"] = raw_safety_exposure_cap
        diagnostics["effective_target_exposure_cap"] = float(safety.exposure_cap)
        self.ledgers.append("ideal_portfolio_plan", ideal)
        self.ledgers.append("executable_order_plan", orders)
        self.ledgers.append("safety_decision_ledger", {**safety.__dict__, **diagnostics})
        self.ledgers.append("constraint_allocation_ledger", {"decision_id": decision_id, "date": decision_date, **diagnostics})
        return ideal, orders, diagnostics

    def save(self, output_dir=GOVERNANCE_OUTPUT_DIR) -> dict[str, Path]:
        output = Path(output_dir)
        saved = self.ledgers.save(output)
        saved["environment_manifest"] = save_environment_manifest(
            self.manifest,
            output / "environment_manifest.json",
        )
        return saved

    def settle_pending_orders(
        self,
        trade_date,
        *,
        fills=None,
        blocked_symbols=(),
        blocked_reasons=None,
    ) -> pd.DataFrame:
        ledger = self.pending_orders.settle_day(
            trade_date,
            fills=fills,
            blocked_symbols=blocked_symbols,
            blocked_reasons=blocked_reasons,
        )
        self.ledgers.append("pending_order_ledger", ledger)
        return ledger

    def record_exposure(self, payload: dict):
        self.ledgers.append("actual_exposure_ledger", payload)

    def record_reputation(self, frame: pd.DataFrame):
        self.ledgers.append("reputation_ledger", frame)

    def record_shadow_portfolio(self, frame: pd.DataFrame):
        self.ledgers.append("shadow_portfolio_ledger", frame)

    def record_leakage_audit(self, frame: pd.DataFrame):
        self.ledgers.append("leakage_audit_report", frame)
