"""Deterministic phase-one president policy."""
from __future__ import annotations

import pandas as pd

from config import GOVERNANCE_SINGLE_WEIGHT_DRIFT, GOVERNANCE_TOTAL_WEIGHT_DRIFT
from functions.decision_council.allocation import PortfolioConstructionCommittee
from functions.decision_council.contracts import DecisionContext


ORDER_PRIORITIES = {
    "safety_deleveraging": 0,
    "qualification_exit": 1,
    "alpha_collapse_consensus": 2,
    "expired_holding_exit": 3,
    "normal_sell": 4,
    "normal_buy": 5,
}
ORDER_COLUMNS = [
    "decision_id",
    "execution_date",
    "symbol",
    "side",
    "current_weight",
    "target_weight",
    "delta_weight",
    "reason",
    "priority",
    "pending_policy",
]


class RulesBasedPresidentPolicy:
    """Convert ranked candidates and hard constraints into one daily plan."""

    def __init__(self, *, enable_sector_cap: bool = False, enable_safety_agent: bool = True):
        self.enable_sector_cap = bool(enable_sector_cap)
        self.enable_safety_agent = bool(enable_safety_agent)
        self.portfolio_constructor = PortfolioConstructionCommittee(enable_sector_cap=enable_sector_cap)

    def decide(self, context: DecisionContext) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
        candidates = _prepare_candidates(context.candidates)
        candidate_index = candidates.set_index("symbol", drop=False)
        locked_weights = {
            symbol: float(weight)
            for symbol, weight in context.current_weights.items()
            if symbol in context.pending_locked_symbols
        }
        safety_cap = float(context.safety.exposure_cap) if self.enable_safety_agent else 1.0
        eligible = candidates[~candidates["symbol"].isin(context.pending_locked_symbols)].copy()
        preserved_unranked = {
            symbol: float(weight)
            for symbol, weight in context.current_weights.items()
            if symbol not in context.pending_locked_symbols
            and symbol not in set(eligible["symbol"])
            and symbol not in context.hard_qualification_symbols
        }
        allocatable_cap = max(
            safety_cap - sum(locked_weights.values()) - sum(preserved_unranked.values()),
            0.0,
        )
        held_symbols = []
        for symbol, days in context.holding_days.items():
            if symbol not in candidate_index.index or symbol in context.pending_locked_symbols:
                continue
            row = candidate_index.loc[symbol]
            if bool(row["alpha_collapse_exit"]):
                continue
            if int(days) < int(context.minimum_holding_days) or int(row["candidate_rank"]) <= int(context.hold_rank_limit):
                held_symbols.append(symbol)
        ranked_symbols = eligible.loc[
            eligible["candidate_rank"] <= int(context.entry_rank_limit)
        ].sort_values(["primary_score", "symbol"], ascending=[False, True])["symbol"].tolist()
        selected_symbols = list(dict.fromkeys(held_symbols))
        for symbol in ranked_symbols:
            if symbol not in selected_symbols and len(selected_symbols) < int(context.top_n):
                selected_symbols.append(symbol)
        selected = eligible[eligible["symbol"].isin(selected_symbols)].copy()
        selected = selected.sort_values(["primary_score", "symbol"], ascending=[False, True])
        allocated, allocation_diagnostics = self.portfolio_constructor.construct(
            selected,
            exposure_cap=allocatable_cap,
        )
        target_weights = dict(zip(allocated["symbol"], allocated["target_weight"]))
        target_weights.update(locked_weights)
        target_weights.update(preserved_unranked)
        protected_weights = {**locked_weights, **preserved_unranked}
        ideal = self._ideal_plan(context, allocated, protected_weights, allocation_diagnostics)
        orders, order_diagnostics = self._build_orders(context, target_weights, eligible, safety_cap)
        diagnostics = {
            **allocation_diagnostics,
            **order_diagnostics,
            "locked_nominal_weight": sum(locked_weights.values()),
            "preserved_unranked_nominal_weight": sum(preserved_unranked.values()),
            "target_exposure": sum(target_weights.values()),
            "sector_cap_enabled": self.enable_sector_cap,
            "safety_agent_enabled": self.enable_safety_agent,
        }
        return ideal, orders, diagnostics

    def _ideal_plan(self, context, allocated, locked_weights, diagnostics):
        columns = [
            "decision_id",
            "decision_date",
            "horizon_days",
            "symbol",
            "ideal_weight",
            "alpha_percentile",
            "expected_return_5d",
            "aggregate_confidence",
            "hold_until_date",
            "proposal_sources",
            "prototype_sector",
            "constraint_cash_reserve",
        ]
        plan = allocated.copy()
        if not plan.empty:
            plan["ideal_weight"] = plan["target_weight"]
            plan["decision_id"] = context.decision_id
            plan["decision_date"] = context.decision_date
            plan["horizon_days"] = 5
            plan["hold_until_date"] = pd.Timestamp(context.decision_date) + pd.offsets.BDay(context.minimum_holding_days)
            plan["proposal_sources"] = plan.get("proposal_sources", "alpha_ensemble")
            plan["constraint_cash_reserve"] = diagnostics["constraint_cash_reserve"]
        for column in columns:
            if column not in plan.columns:
                plan[column] = pd.NA
        plan = plan[columns].copy()
        locked_rows = []
        for symbol, weight in locked_weights.items():
            locked_rows.append(
                {
                    "decision_id": context.decision_id,
                    "decision_date": context.decision_date,
                    "horizon_days": 5,
                    "symbol": symbol,
                    "ideal_weight": weight,
                    "alpha_percentile": pd.NA,
                    "expected_return_5d": pd.NA,
                    "aggregate_confidence": pd.NA,
                    "hold_until_date": pd.NA,
                    "proposal_sources": "pending_locked",
                    "prototype_sector": pd.NA,
                    "constraint_cash_reserve": diagnostics["constraint_cash_reserve"],
                }
            )
        if locked_rows and plan.empty:
            keep = pd.DataFrame(locked_rows)
        elif locked_rows:
            locked = pd.DataFrame(locked_rows)
            keep = pd.concat(
                [plan.dropna(axis=1, how="all"), locked.dropna(axis=1, how="all")],
                ignore_index=True,
            )
        else:
            keep = plan
        for column in columns:
            if column not in keep.columns:
                keep[column] = pd.NA
        return keep[columns].copy()

    def _build_orders(self, context, target_weights, eligible, safety_cap):
        current = {str(symbol): float(weight) for symbol, weight in context.current_weights.items()}
        symbols = sorted(set(current) | set(target_weights))
        safety_shortfall = max(sum(current.values()) - float(safety_cap), 0.0)
        rows = []
        normal_turnover = 0.0
        total_drift = sum(abs(target_weights.get(symbol, 0.0) - current.get(symbol, 0.0)) for symbol in symbols)
        candidate_index = eligible.set_index("symbol", drop=False)
        safety_sold_symbols = set()
        remaining_safety_shortfall = safety_shortfall
        safety_ranked = sorted(
            (
                (
                    float(candidate_index.at[symbol, "primary_score"]) if symbol in candidate_index.index else float("-inf"),
                    symbol,
                    weight,
                )
                for symbol, weight in current.items()
                if symbol not in context.pending_locked_symbols and float(weight) > 0.0
            ),
            key=lambda item: (item[0], item[1]),
        )
        for _, symbol, old in safety_ranked:
            if remaining_safety_shortfall <= 1e-12:
                break
            sell_weight = min(float(old), remaining_safety_shortfall)
            rows.append(self._order_row(context, symbol, old, old - sell_weight, "safety_deleveraging"))
            safety_sold_symbols.add(symbol)
            remaining_safety_shortfall -= sell_weight
        for symbol in symbols:
            if symbol in context.pending_locked_symbols or symbol in safety_sold_symbols:
                continue
            old = current.get(symbol, 0.0)
            new = target_weights.get(symbol, 0.0)
            delta = new - old
            if abs(delta) <= 1e-12:
                continue
            row = candidate_index.loc[symbol] if symbol in candidate_index.index else None
            reason = _order_reason(symbol, delta, row, context)
            is_forced_sell = delta < 0 and reason in {
                "qualification_exit",
                "alpha_collapse_consensus",
            }
            if not is_forced_sell:
                if not context.allow_normal_rebalance:
                    continue
                if delta > 0 and safety_shortfall > 1e-12:
                    continue
                if delta > 0 and context.transition_only:
                    continue
                if delta < 0 and int(context.holding_days.get(symbol, 0)) < int(context.minimum_holding_days):
                    continue
                if abs(delta) < GOVERNANCE_SINGLE_WEIGHT_DRIFT and total_drift < GOVERNANCE_TOTAL_WEIGHT_DRIFT:
                    continue
                delta *= float(context.partial_adjustment_rate)
                new = old + delta
                allowed = max(float(context.turnover_budget) - normal_turnover, 0.0)
                if allowed <= 1e-12:
                    continue
                if abs(delta) > allowed:
                    delta = allowed if delta > 0 else -allowed
                    new = old + delta
                normal_turnover += abs(delta)
            rows.append(self._order_row(context, symbol, old, new, reason))
        orders = pd.DataFrame(rows, columns=ORDER_COLUMNS)
        planned_safety_sell_weight = float(
            -orders.loc[orders.get("reason", pd.Series(dtype=object)) == "safety_deleveraging", "delta_weight"].sum()
        ) if not orders.empty else 0.0
        return orders, {
            "total_target_drift": total_drift,
            "normal_turnover_weight": normal_turnover,
            "planned_safety_sell_weight": planned_safety_sell_weight,
            "unresolved_safety_exposure": max(remaining_safety_shortfall, 0.0),
        }

    @staticmethod
    def _order_row(context, symbol, old, new, reason):
        delta = float(new) - float(old)
        return {
            "decision_id": context.decision_id,
            "execution_date": pd.Timestamp(context.decision_date) + pd.offsets.BDay(1),
            "symbol": symbol,
            "side": "buy" if delta > 0 else "sell",
            "current_weight": float(old),
            "target_weight": float(new),
            "delta_weight": delta,
            "reason": reason,
            "priority": ORDER_PRIORITIES[reason],
            "pending_policy": "daily_expiry" if delta > 0 else "persistent_sell_intent",
        }


def _prepare_candidates(candidates):
    data = candidates.copy()
    required = {"symbol", "alpha_score", "alpha_percentile", "volatility_20"}
    missing = sorted(required - set(data.columns))
    if missing:
        raise ValueError(f"President candidates missing columns: {missing}")
    data["alpha_collapse_exit"] = data.get("alpha_collapse_exit", False)
    data["expected_return_5d"] = data.get("expected_return_5d", pd.NA)
    data["aggregate_confidence"] = data.get("aggregate_confidence", pd.NA)
    data["primary_score"] = data.get("primary_score", data["alpha_score"])
    data["score_authority"] = data.get("score_authority", "exploratory_alpha_fallback")
    if "candidate_rank" not in data.columns:
        ordered = data.sort_values(["primary_score", "symbol"], ascending=[False, True]).index
        data.loc[ordered, "candidate_rank"] = range(1, len(data) + 1)
    return data


def _order_reason(symbol, delta, candidate_row, context):
    if delta < 0 and symbol in context.hard_qualification_symbols:
        return "qualification_exit"
    if delta < 0 and candidate_row is not None and bool(candidate_row.get("alpha_collapse_exit", False)):
        return "alpha_collapse_consensus"
    if delta < 0 and int(context.holding_days.get(symbol, 0)) >= int(context.minimum_holding_days):
        return "expired_holding_exit"
    return "normal_buy" if delta > 0 else "normal_sell"
