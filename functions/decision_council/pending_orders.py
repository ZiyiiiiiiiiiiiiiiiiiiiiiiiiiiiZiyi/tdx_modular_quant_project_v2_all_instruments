"""Persistent pending-order state machine with one liquidation intent per symbol."""
from __future__ import annotations

from uuid import uuid4

import pandas as pd

from config import GOVERNANCE_LOCK_ALERT_DAYS, GOVERNANCE_LOCK_HAIRCUT_DAYS


PENDING_ORDER_COLUMNS = [
    "order_id",
    "registration_key",
    "order_schema_version",
    "decision_id",
    "symbol",
    "side",
    "reason",
    "origin_reason",
    "latest_reason",
    "highest_priority_reason",
    "reason_history",
    "reason_schema_version",
    "priority",
    "created_date",
    "last_retry_date",
    "target_shares",
    "executed_shares",
    "processed_fill_ids",
    "remaining_shares",
    "retry_count",
    "lock_days",
    "status",
    "block_reason",
    "expired_reason",
    "cancellation_reason",
    "superseded_by_order_id",
    "position_state",
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
    "action_plan_id",
    "action_proposal_id",
    "action_plan_selected",
    "action_plan_contract",
    "scap_v31_authority_tier",
    "scap_v31_authority_contract",
    "cash_reservation_id",
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
    "monthly_lgbm_model_month",
    "monthly_lgbm_trained_as_of",
    "monthly_lgbm_runtime_model",
    "hybrid_rule_rank_percentile",
    "hybrid_ml_rank_percentile",
    "hybrid_ml_weight",
    "hybrid_rule_weight",
    "hybrid_final_score",
    "hybrid_fusion_status",
    "hybrid_fusion_formula_version",
    "hybrid_score_authority",
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
    "replacement_pair_id",
    "replacement_paired_symbol",
    "replacement_pair_leg",
    "replacement_horizon_days",
    "replacement_expected_net_edge",
    "replacement_lcb_net_edge",
    "replacement_cost_rate",
    "replacement_contract",
    "replacement_pair_status",
]

SELL_RETRY_REASONS = {"safety_deleveraging", "qualification_exit", "alpha_collapse_consensus"}
FATAL_REPLACEMENT_BUY_REASONS = {
    "replacement_signal_invalid",
    "replacement_horizon_expired",
    "replacement_candidate_no_longer_superior",
}


class PendingOrderBook:
    """Maintain active orders without duplicating locked sell intents."""

    def __init__(self, orders: pd.DataFrame | None = None):
        self.orders = _ensure_columns(orders)

    def add_order(self, payload: dict) -> str:
        order = {column: pd.NA for column in PENDING_ORDER_COLUMNS}
        order.update(payload)
        registration_key = str(
            _value_or(
                order.get("registration_key"),
                "|".join(
                    [
                        str(order.get("decision_id", "")),
                        str(order.get("symbol", "")),
                        str(order.get("side", "")).lower(),
                        str(order.get("replacement_pair_id", "")),
                        str(order.get("replacement_pair_leg", "")).lower(),
                    ]
                ),
            )
        )
        if registration_key and not self.orders.empty:
            existing = self.orders[
                self.orders["registration_key"].fillna("").astype(str).eq(
                    registration_key
                )
            ]
            if not existing.empty:
                return str(existing.iloc[0]["order_id"])
        order["registration_key"] = registration_key
        order["order_schema_version"] = str(
            _value_or(order.get("order_schema_version"), "pending_order_v2")
        )
        order["order_id"] = str(order.get("order_id") if pd.notna(order.get("order_id")) else uuid4())
        order["side"] = str(order["side"]).lower()
        reason = str(_value_or(order.get("reason"), ""))
        order["origin_reason"] = str(_value_or(order.get("origin_reason"), reason))
        order["latest_reason"] = str(_value_or(order.get("latest_reason"), reason))
        order["highest_priority_reason"] = str(
            _value_or(order.get("highest_priority_reason"), reason)
        )
        order["reason_history"] = str(
            _value_or(order.get("reason_history"), reason)
        )
        order["reason_schema_version"] = str(
            _value_or(
                order.get("reason_schema_version"),
                "scap_exit_reason_contract_v1",
            )
        )
        order["created_date"] = pd.Timestamp(order["created_date"])
        order["last_retry_date"] = pd.Timestamp(_value_or(order.get("last_retry_date"), order["created_date"]))
        order["target_shares"] = float(_value_or(order.get("target_shares"), 0.0))
        order["executed_shares"] = float(_value_or(order.get("executed_shares"), 0.0))
        order["processed_fill_ids"] = str(
            _value_or(order.get("processed_fill_ids"), "")
        )
        order["remaining_shares"] = float(_value_or(order.get("remaining_shares"), order["target_shares"]))
        order["retry_count"] = int(_value_or(order.get("retry_count"), 0))
        order["lock_days"] = int(_value_or(order.get("lock_days"), 0))
        order["status"] = str(_value_or(order.get("status"), "pending"))
        if order["side"] == "buy" and not self.orders.empty:
            active_sell = self.orders[
                self.orders["symbol"].astype(str).eq(str(order["symbol"]))
                & self.orders["side"].astype(str).eq("sell")
                & self.orders["status"].isin(["pending", "pending_locked"])
            ]
            if not active_sell.empty:
                order["status"] = "expired"
                order["expired_reason"] = "active_sell_precedence"
                order["block_reason"] = "same_symbol_buy_sell_conflict"
        new_row = pd.DataFrame([order], columns=PENDING_ORDER_COLUMNS)
        if self.orders.empty or self.orders.dropna(how="all").empty:
            self.orders = new_row
        else:
            # Row assignment to a heterogeneous frame triggers a pandas dtype
            # deprecation warning and repeatedly reallocates its backing blocks.
            self.orders = pd.concat([self.orders, new_row], ignore_index=True)
        return order["order_id"]

    def add_orders_atomic(self, payloads: list[dict]) -> tuple[str, ...]:
        """Register a complete replacement pair or commit nothing.

        Ordinary batches are accepted too, but any payload carrying a pair id
        must form exactly one sell leg and one buy leg for that same pair.
        """
        items = [dict(payload) for payload in payloads]
        if not items:
            return ()
        pair_ids = {
            str(item.get("replacement_pair_id", "") or "")
            for item in items
            if str(item.get("replacement_pair_id", "") or "")
        }
        if pair_ids:
            if len(pair_ids) != 1 or len(items) != 2:
                raise ValueError("atomic replacement registration requires exactly two legs")
            pair_id = next(iter(pair_ids))
            legs = {
                str(item.get("replacement_pair_leg", "") or "").lower()
                for item in items
            }
            sides = {str(item.get("side", "") or "").lower() for item in items}
            if legs != {"sell", "buy"} or sides != {"sell", "buy"}:
                raise ValueError(
                    f"replacement pair {pair_id} requires one sell and one buy leg"
                )
            existing = self.orders[
                self.orders["replacement_pair_id"].fillna("").astype(str).eq(pair_id)
            ]
            if not existing.empty:
                existing_legs = set(
                    existing["replacement_pair_leg"]
                    .fillna("")
                    .astype(str)
                    .str.lower()
                )
                if existing_legs == {"sell", "buy"}:
                    return tuple(existing["order_id"].astype(str))
                raise RuntimeError(
                    f"replacement pair {pair_id} already exists incompletely"
                )
        staged = PendingOrderBook(self.orders.copy(deep=True))
        order_ids = []
        for item in items:
            if str(item.get("side", "")).lower() == "sell":
                order_ids.append(staged.upsert_sell_intent(item))
            else:
                order_ids.append(staged.add_order(item))
        if pair_ids:
            pair_id = next(iter(pair_ids))
            registered = staged.orders[
                staged.orders["replacement_pair_id"].fillna("").astype(str).eq(
                    pair_id
                )
                & staged.orders["status"].isin(["pending", "pending_locked"])
            ]
            if set(
                registered["replacement_pair_leg"]
                .fillna("")
                .astype(str)
                .str.lower()
            ) != {"sell", "buy"}:
                raise RuntimeError(
                    f"replacement pair {pair_id} failed atomic staging"
                )
        self.orders = staged.orders
        return tuple(order_ids)

    def upsert_sell_intent(self, payload: dict) -> str:
        symbol = str(payload["symbol"])
        active_buy_mask = (
            self.orders["symbol"].astype(str).eq(symbol)
            & self.orders["side"].astype(str).eq("buy")
            & self.orders["status"].isin(["pending", "pending_locked"])
        )
        if bool(active_buy_mask.any()):
            self.orders.loc[active_buy_mask, "status"] = "expired"
            self.orders.loc[
                active_buy_mask, "expired_reason"
            ] = "superseded_by_sell_intent"
            self.orders.loc[
                active_buy_mask, "block_reason"
            ] = "same_symbol_buy_sell_conflict"
        active = self.orders[
            (self.orders["symbol"].astype(str) == symbol)
            & (self.orders["side"].astype(str) == "sell")
            & (self.orders["status"].isin(["pending", "pending_locked"]))
        ]
        if active.empty:
            return self.add_order({**payload, "side": "sell"})
        index = active.index[0]
        incoming_reason = str(payload.get("reason", "") or "")
        self.orders.at[index, "latest_reason"] = incoming_reason
        history = [
            item
            for item in str(self.orders.at[index, "reason_history"] or "").split("|")
            if item
        ]
        if incoming_reason and (not history or history[-1] != incoming_reason):
            history.append(incoming_reason)
        self.orders.at[index, "reason_history"] = "|".join(history)
        self.orders.at[index, "target_shares"] = max(
            float(self.orders.at[index, "target_shares"]),
            float(payload.get("target_shares", 0.0)),
        )
        self.orders.at[index, "remaining_shares"] = max(
            float(self.orders.at[index, "remaining_shares"]),
            float(payload.get("target_shares", 0.0)),
        )
        if int(payload.get("priority", 999)) <= int(self.orders.at[index, "priority"]):
            self.orders.at[index, "priority"] = int(payload["priority"])
            self.orders.at[index, "reason"] = incoming_reason
            self.orders.at[index, "highest_priority_reason"] = incoming_reason
            self.orders.at[index, "decision_id"] = payload["decision_id"]
        if bool(payload.get("liquidation_intent", False)):
            self.orders.at[index, "liquidation_intent"] = True
        # Pair identity is execution authority, not descriptive metadata.  A
        # later replacement intent must not be swallowed by an older normal
        # sell intent for the same symbol.
        for column in (
            "replacement_pair_id", "replacement_paired_symbol", "replacement_pair_leg",
            "replacement_horizon_days", "replacement_expected_net_edge",
            "replacement_lcb_net_edge", "replacement_cost_rate", "replacement_contract",
            "replacement_pair_status",
        ):
            value = payload.get(column, pd.NA)
            if value is not None and not pd.isna(value) and str(value) != "":
                self.orders.at[index, column] = value
        return str(self.orders.at[index, "order_id"])

    def settle_day(
        self,
        trade_date,
        fills: dict[str, float] | None = None,
        blocked_symbols=(),
        blocked_reasons: dict[str, str] | None = None,
    ) -> pd.DataFrame:
        trade_date = pd.Timestamp(trade_date)
        before = self.orders.copy(deep=True).set_index("order_id", drop=False)
        fills = fills or {}
        blocked = {str(symbol) for symbol in blocked_symbols}
        reason_by_symbol = {str(symbol): str(reason) for symbol, reason in (blocked_reasons or {}).items()}
        for index, order in self.orders.iterrows():
            if order["status"] not in {"pending", "pending_locked"}:
                continue
            symbol = str(order["symbol"])
            if symbol in blocked:
                block_reason = reason_by_symbol.get(symbol, "liquidity_locked")
                if str(order["side"]) == "buy":
                    if str(order.get("replacement_pair_leg", "")).lower() == "buy":
                        next_retry = int(order["retry_count"]) + 1
                        horizon = pd.to_numeric(
                            pd.Series([order.get("replacement_horizon_days")]), errors="coerce"
                        ).iloc[0]
                        expired = (
                            block_reason in FATAL_REPLACEMENT_BUY_REASONS
                            or (pd.notna(horizon) and next_retry > max(int(horizon), 1))
                        )
                        if expired:
                            self.orders.at[index, "status"] = "expired"
                            self.orders.at[index, "expired_reason"] = (
                                block_reason if block_reason in FATAL_REPLACEMENT_BUY_REASONS
                                else "replacement_horizon_expired"
                            )
                            self.orders.at[index, "block_reason"] = block_reason
                            self.orders.at[index, "replacement_pair_status"] = "expired"
                            continue
                        self.orders.at[index, "status"] = "pending"
                        self.orders.at[index, "last_retry_date"] = trade_date
                        self.orders.at[index, "retry_count"] = next_retry
                        self.orders.at[index, "block_reason"] = block_reason
                        self.orders.at[index, "replacement_pair_status"] = (
                            "sell_pending" if block_reason == "paired_sell_not_filled" else "buy_pending"
                        )
                        continue
                    self.orders.at[index, "status"] = "expired"
                    self.orders.at[index, "expired_reason"] = (
                        block_reason if block_reason != "liquidity_locked" else "daily_expiry"
                    )
                    self.orders.at[index, "block_reason"] = block_reason
                    continue
                lock_days = int(order["lock_days"]) + 1
                self.orders.at[index, "lock_days"] = lock_days
                self.orders.at[index, "block_reason"] = block_reason
                if str(order["side"]) == "sell" and lock_days > GOVERNANCE_LOCK_HAIRCUT_DAYS:
                    self.orders.at[index, "status"] = "pending_locked"
                continue
            if order["status"] == "pending_locked":
                self.orders.at[index, "status"] = "pending"
                self.orders.at[index, "last_retry_date"] = trade_date
                continue
            fill_value = fills.get(str(order["order_id"]), fills.get(symbol, 0.0))
            if isinstance(fill_value, dict):
                fill_id = str(fill_value.get("fill_id", "") or "")
                known_fill_ids = {
                    value
                    for value in str(order.get("processed_fill_ids", "") or "").split("|")
                    if value
                }
                if fill_id and fill_id in known_fill_ids:
                    continue
                requested_fill = float(fill_value.get("shares", 0.0) or 0.0)
            else:
                fill_id = ""
                requested_fill = float(fill_value or 0.0)
            executed = min(
                requested_fill,
                float(order["remaining_shares"]),
            )
            self.orders.at[index, "executed_shares"] = float(order["executed_shares"]) + executed
            self.orders.at[index, "remaining_shares"] = float(order["remaining_shares"]) - executed
            self.orders.at[index, "last_retry_date"] = trade_date
            self.orders.at[index, "retry_count"] = int(order["retry_count"]) + 1
            if fill_id and executed > 0.0:
                prior_ids = [
                    value
                    for value in str(order.get("processed_fill_ids", "") or "").split("|")
                    if value
                ]
                prior_ids.append(fill_id)
                self.orders.at[index, "processed_fill_ids"] = "|".join(
                    dict.fromkeys(prior_ids)
                )
            if float(self.orders.at[index, "remaining_shares"]) <= 1e-12:
                self.orders.at[index, "status"] = "filled"
                pair_leg = str(order.get("replacement_pair_leg", "")).lower()
                if pair_leg in {"sell", "buy"}:
                    self.orders.at[index, "replacement_pair_status"] = f"{pair_leg}_filled"
            elif str(order["side"]) == "buy" and str(order.get("replacement_pair_leg", "")).lower() != "buy":
                self.orders.at[index, "status"] = "expired"
                self.orders.at[index, "expired_reason"] = "daily_expiry"
        changed = []
        for _, order in self.orders.iterrows():
            order_id = str(order["order_id"])
            if order_id not in before.index or not order.equals(before.loc[order_id]):
                payload = order.to_dict()
                payload["snapshot_date"] = trade_date
                payload["event_type"] = "order_state_change"
                changed.append(payload)
        return pd.DataFrame(changed)

    def locked_symbols(self) -> frozenset[str]:
        locked = self.orders[self.orders["status"] == "pending_locked"]["symbol"].astype(str)
        return frozenset(locked)

    def lock_alerts(self) -> pd.DataFrame:
        return self.orders[
            (self.orders["status"] == "pending_locked")
            & (pd.to_numeric(self.orders["lock_days"], errors="coerce") > GOVERNANCE_LOCK_ALERT_DAYS)
        ].copy()

    def apply_stock_distribution(
        self,
        *,
        symbol: str,
        share_ratio: float,
        event_id: str,
    ) -> int:
        """Adjust active order quantities once across a stock distribution."""
        ratio = float(share_ratio or 0.0)
        if ratio == 0.0:
            return 0
        marker = f"corporate_action:{event_id}"
        mask = (
            self.orders["symbol"].astype(str).eq(str(symbol))
            & self.orders["status"].isin(["pending", "pending_locked"])
            & ~self.orders["processed_fill_ids"].fillna("").astype(str).str.contains(
                marker, regex=False
            )
        )
        for index in self.orders.index[mask]:
            multiplier = 1.0 + ratio
            self.orders.at[index, "target_shares"] = float(
                self.orders.at[index, "target_shares"]
            ) * multiplier
            self.orders.at[index, "remaining_shares"] = float(
                self.orders.at[index, "remaining_shares"]
            ) * multiplier
            prior = str(self.orders.at[index, "processed_fill_ids"] or "")
            self.orders.at[index, "processed_fill_ids"] = "|".join(
                value for value in (prior, marker) if value
            )
        return int(mask.sum())


def _ensure_columns(orders: pd.DataFrame | None) -> pd.DataFrame:
    if orders is None or orders.empty:
        return pd.DataFrame(columns=PENDING_ORDER_COLUMNS)
    data = orders.copy()
    for column in PENDING_ORDER_COLUMNS:
        if column not in data.columns:
            data[column] = pd.NA
    return data[PENDING_ORDER_COLUMNS].copy()


def _value_or(value, default):
    return default if value is None or pd.isna(value) else value
