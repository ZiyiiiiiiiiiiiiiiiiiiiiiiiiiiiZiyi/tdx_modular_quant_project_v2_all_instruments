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
    "trend_break_exit": 3,
    "profit_giveback_exit": 3,
    "post_entry_failure_exit": 3,
    "volume_distribution_exit": 4,
    "replacement_opportunity_exit": 4,
    "single_name_risk_trim": 5,
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

    def __init__(self, *, enable_sector_cap: bool = False, enable_safety_agent: bool = True, exit_mode: str = "full"):
        self.enable_sector_cap = bool(enable_sector_cap)
        self.enable_safety_agent = bool(enable_safety_agent)
        self.exit_mode = str(exit_mode or "full").strip().lower()
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
        allocatable_cap = max(
            safety_cap - sum(locked_weights.values()),
            0.0,
        )
        held_symbols = []
        for symbol, days in context.holding_days.items():
            if symbol not in candidate_index.index or symbol in context.pending_locked_symbols:
                continue
            row = candidate_index.loc[symbol]
            if bool(row["alpha_collapse_exit"]):
                continue
            if (
                int(days) < int(context.minimum_holding_days)
                or int(row["candidate_rank"]) <= int(context.hold_rank_limit)
                or _holding_age_review_passed(row)
            ):
                held_symbols.append(symbol)
        ranked_symbols = eligible.loc[
            (eligible["candidate_rank"] <= int(context.entry_rank_limit))
            & eligible.get("entry_confirmed", pd.Series(True, index=eligible.index)).fillna(False).astype(bool)
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
            covariance_matrix=context.covariance_matrix,
        )
        target_weights = dict(zip(allocated["symbol"], allocated["target_weight"]))
        target_weights.update(locked_weights)
        ideal = self._ideal_plan(context, allocated, locked_weights, allocation_diagnostics)
        replacement_edge = _best_replacement_edge(eligible, set(context.current_weights))
        orders, order_diagnostics = self._build_orders(context, target_weights, eligible, safety_cap, replacement_edge)
        diagnostics = {
            **allocation_diagnostics,
            **order_diagnostics,
            "locked_nominal_weight": sum(locked_weights.values()),
            "preserved_unranked_nominal_weight": 0.0,
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
            "p_win_5d_calibrated",
            "p_win_10d_calibrated",
            "p_win_10d_wilson_lower",
            "expected_edge_5d",
            "expected_edge_10d",
            "conservative_expected_edge_10d",
            "edge_to_risk_10d",
            "conservative_edge_to_risk_10d",
            "entry_evidence_grade",
            "entry_confirmed",
            "entry_block_reason",
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
                    "p_win_5d_calibrated": pd.NA,
                    "p_win_10d_calibrated": pd.NA,
                    "p_win_10d_wilson_lower": pd.NA,
                    "expected_edge_5d": pd.NA,
                    "expected_edge_10d": pd.NA,
                    "conservative_expected_edge_10d": pd.NA,
                    "edge_to_risk_10d": pd.NA,
                    "conservative_edge_to_risk_10d": pd.NA,
                    "entry_evidence_grade": pd.NA,
                    "entry_confirmed": pd.NA,
                    "entry_block_reason": "pending_locked",
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

    def _build_orders(self, context, target_weights, eligible, safety_cap, replacement_edge: float):
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
            reason = _order_reason(symbol, delta, row, context, replacement_edge, exit_mode=self.exit_mode)
            is_catchup_buy = (
                delta > 0
                and context.catchup_allowed
                and reason == "normal_buy"
                and old <= 1e-12
            )
            is_forced_sell = delta < 0 and reason in {
                "qualification_exit",
                "alpha_collapse_consensus",
                "profit_giveback_exit",
                "post_entry_failure_exit",
            }
            if not is_forced_sell:
                if not context.allow_normal_rebalance and not is_catchup_buy:
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
                if is_catchup_buy:
                    budget_limit = float(context.turnover_budget) + float(context.catchup_buy_budget)
                else:
                    budget_limit = float(context.turnover_budget)
                allowed = max(budget_limit - normal_turnover, 0.0)
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
            "best_replacement_edge_10d": float(replacement_edge),
            "replacement_opportunity_sell_count": int(
                orders.get("reason", pd.Series(dtype=object)).astype(str).eq("replacement_opportunity_exit").sum()
            ) if not orders.empty else 0,
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


def _order_reason(symbol, delta, candidate_row, context, replacement_edge: float = 0.0, exit_mode: str = "full"):
    if delta < 0 and symbol in context.hard_qualification_symbols:
        return "qualification_exit"
    if delta < 0 and candidate_row is not None and bool(candidate_row.get("alpha_collapse_exit", False)):
        return "alpha_collapse_consensus"
    if delta < 0 and str(exit_mode or "full").lower() in {"simple", "minimal", "no_complex_exit"}:
        return "normal_sell"
    if delta < 0 and candidate_row is not None:
        if bool(candidate_row.get("profit_giveback_exit", False)):
            return "profit_giveback_exit"
        if bool(candidate_row.get("post_entry_failure_exit", False)):
            return "post_entry_failure_exit"
        if _volume_distribution_exit(candidate_row):
            return "volume_distribution_exit"
        if _trend_break_exit(candidate_row):
            return "trend_break_exit"
        if _replacement_opportunity_exit(candidate_row, replacement_edge):
            return "replacement_opportunity_exit"
    return "normal_buy" if delta > 0 else "normal_sell"


def _best_replacement_edge(eligible: pd.DataFrame, held_symbols: set[str]) -> float:
    if eligible is None or eligible.empty or "symbol" not in eligible.columns:
        return 0.0
    data = eligible[~eligible["symbol"].astype(str).isin(held_symbols)].copy()
    if data.empty or "expected_edge_10d" not in data.columns:
        return 0.0
    edge = pd.to_numeric(data["expected_edge_10d"], errors="coerce").dropna()
    if edge.empty:
        return 0.0
    return float(edge.quantile(0.90))


def _replacement_opportunity_exit(candidate_row, replacement_edge: float) -> bool:
    hold_edge = _hold_edge_after_lifecycle_penalty(candidate_row)
    alpha_percentile = pd.to_numeric(
        pd.Series([candidate_row.get("alpha_percentile", 0.5)]),
        errors="coerce",
    ).fillna(0.5).iloc[0]
    edge_gap = float(replacement_edge) - float(hold_edge)
    giveback = _safe_row_float(candidate_row, "position_giveback_from_peak", 0.0)
    mfe = _safe_row_float(candidate_row, "position_mfe", 0.0)
    return bool(
        (edge_gap >= 0.004 and alpha_percentile < 0.55)
        or (edge_gap >= 0.002 and mfe >= 0.06 and giveback >= 0.35)
    )


def _hold_edge_after_lifecycle_penalty(candidate_row) -> float:
    edge = _safe_row_float(candidate_row, "conservative_expected_edge_10d", None)
    if edge is None:
        edge = _safe_row_float(candidate_row, "expected_edge_10d", 0.0)
    giveback = _safe_row_float(candidate_row, "position_giveback_from_peak", 0.0)
    mfe = _safe_row_float(candidate_row, "position_mfe", 0.0)
    mae = abs(_safe_row_float(candidate_row, "position_mae", 0.0))
    unrealized = _safe_row_float(candidate_row, "position_unrealized_return", 0.0)
    lifecycle_penalty = 0.0
    if mfe >= 0.06:
        lifecycle_penalty += max(giveback - 0.25, 0.0) * 0.006
    if mae >= 0.05 and unrealized <= 0.0:
        lifecycle_penalty += 0.003
    if bool(candidate_row.get("post_entry_failure_exit", False)):
        lifecycle_penalty += 0.006
    return float(edge) - float(lifecycle_penalty)


def _holding_age_review_passed(candidate_row) -> bool:
    if candidate_row is None:
        return False
    if bool(candidate_row.get("alpha_collapse_exit", False)):
        return False
    if bool(candidate_row.get("profit_giveback_exit", False)) or bool(candidate_row.get("post_entry_failure_exit", False)):
        return False
    if _trend_break_exit(candidate_row) or _volume_distribution_exit(candidate_row):
        return False
    alpha_percentile = float(pd.to_numeric(pd.Series([candidate_row.get("alpha_percentile", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
    expected_return = float(pd.to_numeric(pd.Series([candidate_row.get("expected_return_5d", 0.0)]), errors="coerce").fillna(0.0).iloc[0])
    return alpha_percentile >= 0.50 or expected_return >= 0.0


def _trend_break_exit(candidate_row) -> bool:
    close_to_ma20 = pd.to_numeric(pd.Series([candidate_row.get("close_to_ma20", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    ret_20 = pd.to_numeric(pd.Series([candidate_row.get("ret_20", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    alpha_percentile = pd.to_numeric(pd.Series([candidate_row.get("alpha_percentile", 0.5)]), errors="coerce").fillna(0.5).iloc[0]
    return bool(close_to_ma20 < -0.08 and ret_20 < -0.08 and alpha_percentile < 0.45)


def _volume_distribution_exit(candidate_row) -> bool:
    amount = pd.to_numeric(pd.Series([candidate_row.get("amount", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    amount_ma20 = pd.to_numeric(pd.Series([candidate_row.get("amount_ma20", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    close_to_ma20 = pd.to_numeric(pd.Series([candidate_row.get("close_to_ma20", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    ret_20 = pd.to_numeric(pd.Series([candidate_row.get("ret_20", 0.0)]), errors="coerce").fillna(0.0).iloc[0]
    return bool(amount_ma20 > 0 and amount > amount_ma20 * 1.8 and close_to_ma20 < -0.03 and ret_20 < 0.0)


def _safe_row_float(candidate_row, column: str, default):
    value = pd.to_numeric(pd.Series([candidate_row.get(column, default)]), errors="coerce").dropna()
    if value.empty:
        return default
    return float(value.iloc[0])
