"""Single-source arbitration for lifecycle exits and action conflicts."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from functions.decision_council.exit_reason_contract import (
    EXIT_REASON_PRIORITY,
    canonical_exit_reason,
    control_for_exit_reason,
)


_EXIT_TIE_BREAK = {
    "profit_hard_stop_exit": 0,
    "loss_containment_exit": 1,
    "qualification_exit": 2,
    "alpha_collapse_consensus": 3,
    "post_entry_failure_exit": 4,
    "thesis_failure_exit": 5,
    "signal_failure_exit": 6,
    "stale_time_exit": 7,
    "profit_giveback_exit": 8,
    "stale_time_reduce": 9,
    "replacement_opportunity_exit": 10,
}


@dataclass(frozen=True)
class ExitArbitration:
    paper_reason: str
    active_reason: str
    triggered_reasons: tuple[str, ...]
    authorized_reasons: tuple[str, ...]
    vetoed_reasons: tuple[str, ...]
    conflict_count: int
    contract: str = "single_exit_authority_v2"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PositionActionArbitration:
    selected_action: str
    proposed_actions: tuple[str, ...]
    vetoed_actions: tuple[str, ...]
    conflict_count: int
    contract: str = "unified_position_action_v1"

    def as_dict(self) -> dict:
        return asdict(self)


_POSITION_ACTION_PRIORITY = {
    "exit": 0,
    "active_replacement": 1,
    "loser_averaging": 2,
    "winner_pyramiding": 3,
    "new_entry": 4,
    "normal_rebalance": 5,
    "hold": 6,
}


def arbitrate_position_actions(proposals: dict[str, bool]) -> PositionActionArbitration:
    """Choose one auditable position action from competing module proposals."""
    proposed = tuple(
        sorted(
            {
                str(action).strip().lower()
                for action, enabled in proposals.items()
                if bool(enabled) and str(action).strip()
            },
            key=lambda action: (_POSITION_ACTION_PRIORITY.get(action, 999), action),
        )
    )
    selected = proposed[0] if proposed else "hold"
    return PositionActionArbitration(
        selected_action=selected,
        proposed_actions=proposed or ("hold",),
        vetoed_actions=tuple(action for action in proposed if action != selected),
        conflict_count=max(len(proposed) - 1, 0),
    )


def arbitrate_exit_signals(
    triggers: dict[str, bool],
    *,
    control_enabled=None,
) -> ExitArbitration:
    """Authorize every trigger once, then select one canonical exit reason."""
    triggered = {
        canonical_exit_reason(reason)
        for reason, is_triggered in triggers.items()
        if bool(is_triggered)
    }
    ordered = tuple(
        sorted(
            triggered,
            key=lambda reason: (
                int(EXIT_REASON_PRIORITY.get(reason, 999)),
                int(_EXIT_TIE_BREAK.get(reason, 999)),
                reason,
            ),
        )
    )
    authorized = []
    vetoed = []
    for reason in ordered:
        control = control_for_exit_reason(reason)
        allowed = (
            True
            if control_enabled is None or not control
            else bool(control_enabled(control))
        )
        (authorized if allowed else vetoed).append(reason)
    return ExitArbitration(
        paper_reason=ordered[0] if ordered else "",
        active_reason=authorized[0] if authorized else "",
        triggered_reasons=ordered,
        authorized_reasons=tuple(authorized),
        vetoed_reasons=tuple(vetoed),
        conflict_count=max(len(ordered) - 1, 0),
    )


def update_consecutive_confirmation(
    store: dict[str, dict],
    *,
    symbol: str,
    signal_name: str,
    date,
    triggered: bool,
    required_days: int,
) -> tuple[int, bool]:
    """Track consecutive observed decision days for one symbol/signal."""
    key = f"{symbol}|{signal_name}"
    required = max(int(required_days), 1)
    if not bool(triggered):
        store.pop(key, None)
        return 0, False
    prior = store.get(key, {})
    prior_date = pd.to_datetime(prior.get("last_date"), errors="coerce")
    current_date = pd.Timestamp(date)
    count = int(prior.get("count", 0) or 0)
    if pd.isna(prior_date) or current_date > pd.Timestamp(prior_date):
        count += 1
    store[key] = {"count": count, "last_date": current_date}
    return count, count >= required


def reconcile_same_symbol_orders(orders: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Enforce one action direction per symbol and decision.

    Sell wins over buy for the same symbol. Exact duplicate rows keep the
    highest-priority order.  Every dropped row is returned as audit evidence.
    """
    if orders is None or orders.empty:
        return orders, pd.DataFrame(
            columns=[
                "decision_id",
                "symbol",
                "dropped_side",
                "dropped_reason",
                "kept_side",
                "arbitration_reason",
            ]
        )
    data = orders.copy()
    data["_row_order"] = range(len(data))
    kept_indices: list[int] = []
    audit_rows: list[dict] = []
    group_columns = [
        column for column in ("decision_id", "decision_date", "symbol")
        if column in data.columns
    ]
    if "symbol" not in group_columns:
        group_columns.append("symbol")
    for _, group in data.groupby(group_columns, dropna=False, sort=False):
        sides = set(group.get("side", pd.Series("", index=group.index)).astype(str))
        if "sell" in sides:
            preferred = group[group["side"].astype(str).eq("sell")]
            kept_side = "sell"
        else:
            preferred = group
            kept_side = str(preferred.iloc[0].get("side", ""))
        priority = pd.to_numeric(
            preferred.get("priority", pd.Series(999, index=preferred.index)),
            errors="coerce",
        ).fillna(999)
        keep_idx = int(
            preferred.assign(_priority=priority)
            .sort_values(["_priority", "_row_order"], kind="stable")
            .index[0]
        )
        kept_indices.append(keep_idx)
        for idx, row in group.iterrows():
            if int(idx) == keep_idx:
                continue
            audit_rows.append(
                {
                    "decision_id": row.get("decision_id", ""),
                    "symbol": row.get("symbol", ""),
                    "dropped_side": row.get("side", ""),
                    "dropped_reason": row.get("reason", ""),
                    "kept_side": kept_side,
                    "arbitration_reason": (
                        "same_symbol_sell_precedence"
                        if "sell" in sides and "buy" in sides
                        else "duplicate_order_deduplicated"
                    ),
                }
            )
    kept = (
        data.loc[sorted(kept_indices, key=lambda idx: int(data.at[idx, "_row_order"]))]
        .drop(columns=["_row_order"])
        .reset_index(drop=True)
    )
    return kept, pd.DataFrame(audit_rows)
