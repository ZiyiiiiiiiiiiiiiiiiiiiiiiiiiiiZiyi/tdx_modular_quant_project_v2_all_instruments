"""Fixed-horizon candidate diagnostics for the factor-only validation line."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd


HORIZONS = (5, 10, 20)
SCORE_COLUMNS = (
    "primary_score",
    "entry_alpha_score",
    "entry_timing_score",
    "entry_liquidity_score",
    "entry_matrix_score",
    "final_entry_score",
    "p_win_10d_calibrated",
)
SOURCE_COLUMNS = (
    "decision_id",
    "signal_date",
    "symbol",
    "candidate_rank",
    "primary_score",
    "alpha_percentile",
    "entry_alpha_score",
    "entry_timing_score",
    "entry_liquidity_score",
    "entry_matrix_score",
    "final_entry_score",
    "p_win_10d_calibrated",
    "entry_confirmed",
    "mainline_v2_entry_confirmed",
    "mainline_v3_entry_confirmed",
    "state_machine_role_pass",
    "cooldown_active",
    "lifecycle_held_row",
    "position_state",
    "entry_block_reason",
    "cabinet_strict_entry_score",
    "cabinet_proxy_entry_score",
    "cabinet_timing_score",
    "cabinet_risk_safety_score",
    "cabinet_liquidity_health_score",
    "cabinet_hold_support_score",
    "cabinet_sell_safety_score",
)


def build_layer_validation_reports(
    candidate_part_paths: Iterable[Path],
    *,
    close_history_getter: Callable[[str], pd.DataFrame],
    execution_ledger: pd.DataFrame | None = None,
    trade_pairs: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Build L0/L1/L2 signal reports and the observed L3 execution marker."""
    candidates = _load_candidate_parts(candidate_part_paths)
    if candidates.empty:
        return {
            "governance_layer_validation_candidate_detail": pd.DataFrame(columns=_candidate_detail_columns()),
            "governance_layer_validation_variant_report": pd.DataFrame(columns=_variant_report_columns()),
            "governance_layer_validation_score_report": pd.DataFrame(columns=_score_report_columns()),
            "governance_layer_validation_daily": pd.DataFrame(columns=_daily_report_columns()),
            "governance_layer_validation_trade_review": _empty_trade_review(),
            "governance_layer_validation_execution_gap": _empty_execution_gap(),
            "governance_layer_validation_contract": _contract_frame(),
        }

    candidates["signal_date"] = pd.to_datetime(candidates["signal_date"], errors="coerce")
    candidates["symbol"] = candidates["symbol"].astype(str)
    candidates = candidates.dropna(subset=["signal_date", "symbol"]).reset_index(drop=True)
    for column in SCORE_COLUMNS:
        candidates[column] = pd.to_numeric(candidates.get(column), errors="coerce")
    for column in (
        "entry_confirmed",
        "mainline_v2_entry_confirmed",
        "mainline_v3_entry_confirmed",
        "state_machine_role_pass",
        "cooldown_active",
        "lifecycle_held_row",
    ):
        candidates[column] = _as_bool(candidates.get(column, pd.Series(False, index=candidates.index)))
    # Held rows exist here only for lifecycle evaluation. They are not fresh
    # entry opportunities and must not enter entry-effect statistics.
    candidates = candidates[~candidates["lifecycle_held_row"]].reset_index(drop=True)

    candidates = _attach_forward_returns(candidates, close_history_getter=close_history_getter)
    candidates["l0_primary_rank"] = candidates.groupby("signal_date")["primary_score"].rank(
        method="first", ascending=False
    )
    candidates["l0_primary_top3"] = candidates["l0_primary_rank"].le(3)
    current_confirmed = candidates["mainline_v2_entry_confirmed"]
    if candidates["mainline_v3_entry_confirmed"].any():
        current_confirmed = candidates["mainline_v3_entry_confirmed"]
    if not current_confirmed.any() and candidates["entry_confirmed"].any():
        current_confirmed = candidates["entry_confirmed"]
    candidates["l1_current_role_confirmation"] = current_confirmed & candidates["state_machine_role_pass"]
    candidates["l2_primary_top3"] = candidates["l0_primary_top3"]
    alpha_median = candidates.groupby("signal_date")["entry_alpha_score"].transform("median")
    alpha_eligible = candidates["entry_alpha_score"].ge(alpha_median) & candidates["entry_alpha_score"].notna()
    alpha_rank = candidates["primary_score"].where(alpha_eligible).groupby(candidates["signal_date"]).rank(
        method="first", ascending=False
    )
    candidates["l2_primary_entry_alpha_top3"] = alpha_eligible & alpha_rank.le(3)
    candidates["l3_executed_buy"] = _executed_buy_mask(candidates, execution_ledger)

    variants = {
        "L0_all_percentile_candidates": pd.Series(True, index=candidates.index),
        "L1_current_role_confirmation": candidates["l1_current_role_confirmation"],
        "L2_primary_top3": candidates["l2_primary_top3"],
        "L2_primary_entry_alpha_top3": candidates["l2_primary_entry_alpha_top3"],
        "L3_executed_buy": candidates["l3_executed_buy"],
    }
    trade_review = _trade_review(candidates, execution_ledger, trade_pairs)
    return {
        "governance_layer_validation_candidate_detail": candidates[_candidate_detail_columns()].copy(),
        "governance_layer_validation_variant_report": _variant_report(candidates, variants),
        "governance_layer_validation_score_report": _score_report(candidates),
        "governance_layer_validation_daily": _daily_report(candidates, variants),
        "governance_layer_validation_trade_review": trade_review,
        "governance_layer_validation_execution_gap": _execution_gap_report(trade_review),
        "governance_layer_validation_contract": _contract_frame(),
    }


def _load_candidate_parts(paths: Iterable[Path]) -> pd.DataFrame:
    parts = []
    wanted = set(SOURCE_COLUMNS)
    for path in (Path(item) for item in paths):
        try:
            part = pd.read_csv(path, usecols=lambda column: column in wanted)
        except (OSError, pd.errors.EmptyDataError, ValueError):
            continue
        if not part.empty:
            parts.append(part)
    if not parts:
        return pd.DataFrame(columns=SOURCE_COLUMNS)
    data = pd.concat(parts, ignore_index=True)
    for column in SOURCE_COLUMNS:
        if column not in data.columns:
            data[column] = pd.NA
    return data[list(SOURCE_COLUMNS)]


def _attach_forward_returns(
    candidates: pd.DataFrame,
    *,
    close_history_getter: Callable[[str], pd.DataFrame],
) -> pd.DataFrame:
    result = candidates.copy()
    for horizon in HORIZONS:
        result[f"forward_return_{horizon}d"] = np.nan
    for symbol, indices in result.groupby("symbol", sort=False).groups.items():
        history = close_history_getter(str(symbol))
        if history is None or history.empty or not {"date", "close"}.issubset(history.columns):
            continue
        history = history[["date", "close"]].copy()
        history["date"] = pd.to_datetime(history["date"], errors="coerce")
        history["close"] = pd.to_numeric(history["close"], errors="coerce")
        history = history.dropna().drop_duplicates("date", keep="last").sort_values("date")
        if history.empty:
            continue
        close = history.set_index("date")["close"]
        signal_dates = result.loc[indices, "signal_date"]
        for horizon in HORIZONS:
            outcomes = close.shift(-horizon).div(close).sub(1.0)
            result.loc[indices, f"forward_return_{horizon}d"] = signal_dates.map(outcomes).to_numpy()
    return result


def _variant_report(candidates: pd.DataFrame, variants: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    signatures: dict[str, str] = {}
    all_daily = candidates.groupby("signal_date")
    all_means = {
        horizon: all_daily[f"forward_return_{horizon}d"].mean()
        for horizon in HORIZONS
    }
    for name, mask in variants.items():
        selected = candidates[mask.fillna(False).astype(bool)].copy()
        selection_hash = _selection_hash(selected)
        identical_to = next(
            (prior_name for prior_name, prior_hash in signatures.items() if prior_hash == selection_hash),
            "",
        )
        signatures[name] = selection_hash
        for horizon in HORIZONS:
            column = f"forward_return_{horizon}d"
            values = pd.to_numeric(selected[column], errors="coerce").dropna()
            daily = selected.groupby("signal_date")[column].mean().dropna()
            comparable = pd.concat([daily.rename("selected"), all_means[horizon].rename("all")], axis=1).dropna()
            rows.append({
                "variant": name,
                "selection_hash": selection_hash,
                "identical_to": identical_to,
                "distinct_selection": not bool(identical_to),
                "horizon_days": horizon,
                "selected_count": int(len(selected)),
                "observed_count": int(len(values)),
                "selected_days": int(selected["signal_date"].nunique()),
                "avg_selected_per_day": float(len(selected) / max(selected["signal_date"].nunique(), 1)),
                "mean_forward_return": float(values.mean()) if not values.empty else np.nan,
                "median_forward_return": float(values.median()) if not values.empty else np.nan,
                "positive_rate": float(values.gt(0.0).mean()) if not values.empty else np.nan,
                "mean_daily_return": float(daily.mean()) if not daily.empty else np.nan,
                "mean_daily_spread_vs_all": (
                    float((comparable["selected"] - comparable["all"]).mean())
                    if not comparable.empty else np.nan
                ),
            })
    return pd.DataFrame(rows, columns=_variant_report_columns())


def _score_report(candidates: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for score in SCORE_COLUMNS:
        for horizon in HORIZONS:
            outcome = f"forward_return_{horizon}d"
            daily_ics = []
            for _, group in candidates[["signal_date", score, outcome]].dropna().groupby("signal_date"):
                if len(group) >= 3 and group[score].nunique() > 1:
                    daily_ics.append(group[score].corr(group[outcome], method="spearman"))
            rows.append({
                "score": score,
                "horizon_days": horizon,
                "observed_days": int(len(daily_ics)),
                "mean_daily_rank_ic": float(np.nanmean(daily_ics)) if daily_ics else np.nan,
                "median_daily_rank_ic": float(np.nanmedian(daily_ics)) if daily_ics else np.nan,
                "positive_ic_day_ratio": float(pd.Series(daily_ics).gt(0.0).mean()) if daily_ics else np.nan,
            })
    return pd.DataFrame(rows, columns=_score_report_columns())


def _daily_report(candidates: pd.DataFrame, variants: dict[str, pd.Series]) -> pd.DataFrame:
    frames = []
    for name, mask in variants.items():
        selected = candidates[mask.fillna(False).astype(bool)]
        if selected.empty:
            continue
        grouped = selected.groupby("signal_date")
        frame = grouped.size().rename("selected_count").to_frame()
        for horizon in HORIZONS:
            frame[f"mean_forward_return_{horizon}d"] = grouped[f"forward_return_{horizon}d"].mean()
        frame.insert(0, "variant", name)
        frames.append(frame.reset_index())
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_daily_report_columns())


def _executed_buy_mask(candidates: pd.DataFrame, execution_ledger: pd.DataFrame | None) -> pd.Series:
    if execution_ledger is None or execution_ledger.empty:
        return pd.Series(False, index=candidates.index)
    trades = execution_ledger.copy()
    side = trades.get("side", pd.Series("", index=trades.index)).astype(str).str.lower()
    status = trades.get("execution_status", pd.Series("", index=trades.index)).astype(str).str.lower()
    trades = trades[side.eq("buy") & status.eq("filled")].copy()
    if trades.empty:
        return pd.Series(False, index=candidates.index)
    trades["signal_date"] = pd.to_datetime(trades.get("signal_date"), errors="coerce")
    keys = set(zip(trades["signal_date"], trades["symbol"].astype(str)))
    return pd.Series(
        [(date, symbol) in keys for date, symbol in zip(candidates["signal_date"], candidates["symbol"])],
        index=candidates.index,
    )


def _trade_review(
    candidates: pd.DataFrame,
    execution_ledger: pd.DataFrame | None,
    trade_pairs: pd.DataFrame | None,
) -> pd.DataFrame:
    if execution_ledger is None or execution_ledger.empty:
        return _empty_trade_review()
    executions = execution_ledger.copy()
    status = executions.get("execution_status", pd.Series("", index=executions.index)).astype(str).str.lower()
    side = executions.get("side", pd.Series("", index=executions.index)).astype(str).str.lower()
    executions = executions[status.eq("filled") & side.isin({"buy", "sell"})].copy()
    if executions.empty:
        return _empty_trade_review()
    executions["signal_date"] = pd.to_datetime(executions.get("signal_date"), errors="coerce")
    executions["trade_date"] = pd.to_datetime(executions.get("trade_date"), errors="coerce")
    executions["symbol"] = executions.get("symbol", pd.Series("", index=executions.index)).astype(str)

    candidate_lookup = candidates.drop_duplicates(["signal_date", "symbol"], keep="last").set_index(
        ["signal_date", "symbol"], drop=False
    )
    candidate_groups = {date: group for date, group in candidates.groupby("signal_date", sort=False)}
    symbol_groups = {symbol: group.sort_values("signal_date") for symbol, group in candidates.groupby("symbol", sort=False)}
    pair_by_sell_order = {}
    if trade_pairs is not None and not trade_pairs.empty and "sell_order_id" in trade_pairs.columns:
        pair_by_sell_order = {
            str(row["sell_order_id"]): row
            for _, row in trade_pairs.dropna(subset=["sell_order_id"]).iterrows()
        }

    rows = []
    for _, execution in executions.sort_values(["trade_date", "symbol", "side"]).iterrows():
        signal_date = pd.Timestamp(execution["signal_date"]) if pd.notna(execution["signal_date"]) else pd.NaT
        symbol = str(execution["symbol"])
        candidate = None
        if pd.notna(signal_date) and (signal_date, symbol) in candidate_lookup.index:
            candidate = candidate_lookup.loc[(signal_date, symbol)]
            if isinstance(candidate, pd.DataFrame):
                candidate = candidate.iloc[-1]
        daily = candidate_groups.get(signal_date, pd.DataFrame()) if pd.notna(signal_date) else pd.DataFrame()
        row = {
            "order_id": str(execution.get("order_id", "")),
            "decision_id": str(execution.get("decision_id", "")),
            "signal_date": signal_date,
            "trade_date": execution.get("trade_date", pd.NaT),
            "symbol": symbol,
            "side": str(execution.get("side", "")).lower(),
            "reason": str(execution.get("reason", "")),
            "price": pd.to_numeric(pd.Series([execution.get("price")]), errors="coerce").iloc[0],
            "executed_shares": pd.to_numeric(pd.Series([execution.get("executed_shares")]), errors="coerce").iloc[0],
            "candidate_found": candidate is not None,
            "candidate_count_on_signal_date": int(len(daily)),
            "candidate_rank": candidate.get("candidate_rank", pd.NA) if candidate is not None else pd.NA,
            "primary_rank": candidate.get("l0_primary_rank", pd.NA) if candidate is not None else pd.NA,
            "primary_score": candidate.get("primary_score", pd.NA) if candidate is not None else pd.NA,
            "entry_alpha_score": candidate.get("entry_alpha_score", pd.NA) if candidate is not None else pd.NA,
            "entry_timing_score": candidate.get("entry_timing_score", pd.NA) if candidate is not None else pd.NA,
            "entry_matrix_score": candidate.get("entry_matrix_score", pd.NA) if candidate is not None else pd.NA,
            "final_entry_score": candidate.get("final_entry_score", pd.NA) if candidate is not None else pd.NA,
        }
        for horizon in HORIZONS:
            outcome = f"forward_return_{horizon}d"
            selected_return = candidate.get(outcome, pd.NA) if candidate is not None else pd.NA
            daily_values = pd.to_numeric(daily.get(outcome, pd.Series(dtype=float)), errors="coerce").dropna()
            row[outcome] = selected_return
            row[f"best_candidate_return_{horizon}d"] = daily_values.max() if not daily_values.empty else pd.NA
            row[f"outcome_rank_{horizon}d"] = _outcome_rank(daily, symbol, outcome)
            row[f"gap_to_best_{horizon}d"] = (
                float(selected_return) - float(daily_values.max())
                if pd.notna(selected_return) and not daily_values.empty else pd.NA
            )
            nearby = symbol_groups.get(symbol, pd.DataFrame())
            if not nearby.empty and pd.notna(signal_date):
                nearby = nearby[nearby["signal_date"].between(signal_date - pd.Timedelta(days=10), signal_date + pd.Timedelta(days=10))]
            nearby_values = pd.to_numeric(nearby.get(outcome, pd.Series(dtype=float)), errors="coerce")
            if not nearby.empty and nearby_values.notna().any():
                best_index = nearby_values.idxmax()
                row[f"best_nearby_signal_date_{horizon}d"] = nearby.loc[best_index, "signal_date"]
                row[f"best_nearby_return_{horizon}d"] = nearby_values.loc[best_index]
                row[f"gap_to_nearby_best_{horizon}d"] = (
                    float(selected_return) - float(nearby_values.loc[best_index])
                    if pd.notna(selected_return) else pd.NA
                )
            else:
                row[f"best_nearby_signal_date_{horizon}d"] = pd.NaT
                row[f"best_nearby_return_{horizon}d"] = pd.NA
                row[f"gap_to_nearby_best_{horizon}d"] = pd.NA
        pair = pair_by_sell_order.get(str(execution.get("order_id", "")))
        row["realized_pnl_amount"] = pair.get("realized_pnl_amount", pd.NA) if pair is not None else pd.NA
        row["realized_pnl_pct"] = pair.get("realized_pnl_pct", pd.NA) if pair is not None else pd.NA
        row["holding_days"] = pair.get("holding_days", pd.NA) if pair is not None else pd.NA
        rows.append(row)
    return pd.DataFrame(rows, columns=_trade_review_columns())


def _execution_gap_report(trade_review: pd.DataFrame) -> pd.DataFrame:
    if trade_review is None or trade_review.empty:
        return _empty_execution_gap()
    buys = trade_review[trade_review["side"].eq("buy")].copy()
    if buys.empty:
        return _empty_execution_gap()
    rows = []
    for signal_date, group in buys.groupby("signal_date", dropna=False):
        row = {
            "signal_date": signal_date,
            "executed_buy_count": int(len(group)),
            "candidate_match_count": int(group["candidate_found"].fillna(False).sum()),
            "mean_primary_rank": pd.to_numeric(group["primary_rank"], errors="coerce").mean(),
        }
        for horizon in HORIZONS:
            row[f"mean_forward_return_{horizon}d"] = pd.to_numeric(group[f"forward_return_{horizon}d"], errors="coerce").mean()
            row[f"mean_gap_to_best_{horizon}d"] = pd.to_numeric(group[f"gap_to_best_{horizon}d"], errors="coerce").mean()
            row[f"mean_gap_to_nearby_best_{horizon}d"] = pd.to_numeric(
                group[f"gap_to_nearby_best_{horizon}d"], errors="coerce"
            ).mean()
        rows.append(row)
    return pd.DataFrame(rows, columns=_execution_gap_columns())


def _outcome_rank(daily: pd.DataFrame, symbol: str, outcome: str):
    if daily.empty or outcome not in daily.columns:
        return pd.NA
    values = pd.to_numeric(daily[outcome], errors="coerce")
    ranks = values.rank(method="min", ascending=False)
    matched = daily["symbol"].astype(str).eq(str(symbol))
    return ranks[matched].iloc[-1] if matched.any() else pd.NA


def _trade_review_columns() -> list[str]:
    base = [
        "order_id", "decision_id", "signal_date", "trade_date", "symbol", "side", "reason",
        "price", "executed_shares", "candidate_found", "candidate_count_on_signal_date",
        "candidate_rank", "primary_rank", "primary_score", "entry_alpha_score",
        "entry_timing_score", "entry_matrix_score", "final_entry_score",
    ]
    horizon_columns = []
    for horizon in HORIZONS:
        horizon_columns.extend([
            f"forward_return_{horizon}d", f"best_candidate_return_{horizon}d",
            f"outcome_rank_{horizon}d", f"gap_to_best_{horizon}d",
            f"best_nearby_signal_date_{horizon}d", f"best_nearby_return_{horizon}d",
            f"gap_to_nearby_best_{horizon}d",
        ])
    return [*base, *horizon_columns, "realized_pnl_amount", "realized_pnl_pct", "holding_days"]


def _execution_gap_columns() -> list[str]:
    columns = ["signal_date", "executed_buy_count", "candidate_match_count", "mean_primary_rank"]
    for horizon in HORIZONS:
        columns.extend([
            f"mean_forward_return_{horizon}d", f"mean_gap_to_best_{horizon}d",
            f"mean_gap_to_nearby_best_{horizon}d",
        ])
    return columns


def _candidate_detail_columns() -> list[str]:
    return [
        "decision_id", "signal_date", "symbol", "candidate_rank", *SCORE_COLUMNS,
        "entry_confirmed", "state_machine_role_pass", "position_state", "entry_block_reason",
        "cabinet_strict_entry_score", "cabinet_proxy_entry_score", "cabinet_timing_score",
        "cabinet_risk_safety_score", "cabinet_liquidity_health_score",
        "cabinet_hold_support_score", "cabinet_sell_safety_score",
        "l0_primary_rank", "l0_primary_top3", "l1_current_role_confirmation",
        "l2_primary_top3", "l2_primary_entry_alpha_top3", "l3_executed_buy",
        *(f"forward_return_{horizon}d" for horizon in HORIZONS),
    ]


def _variant_report_columns() -> list[str]:
    return [
        "variant", "selection_hash", "identical_to", "distinct_selection", "horizon_days",
        "selected_count", "observed_count", "selected_days", "avg_selected_per_day",
        "mean_forward_return", "median_forward_return", "positive_rate", "mean_daily_return",
        "mean_daily_spread_vs_all",
    ]


def _score_report_columns() -> list[str]:
    return [
        "score", "horizon_days", "observed_days", "mean_daily_rank_ic",
        "median_daily_rank_ic", "positive_ic_day_ratio",
    ]


def _daily_report_columns() -> list[str]:
    return [
        "signal_date", "variant", "selected_count",
        *(f"mean_forward_return_{horizon}d" for horizon in HORIZONS),
    ]


def _empty_trade_review() -> pd.DataFrame:
    return pd.DataFrame(columns=_trade_review_columns())


def _empty_execution_gap() -> pd.DataFrame:
    return pd.DataFrame(columns=_execution_gap_columns())


def _contract_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"variant": "L0_all_percentile_candidates", "purpose": "fixed-horizon cabinet signal baseline", "changes_trading": False},
        {"variant": "L1_current_role_confirmation", "purpose": "current role-gate incremental value", "changes_trading": False},
        {"variant": "L2_primary_top3", "purpose": "simple primary-score counterfactual", "changes_trading": False},
        {"variant": "L2_primary_entry_alpha_top3", "purpose": "primary plus above-median entry-alpha counterfactual", "changes_trading": False},
        {"variant": "L3_executed_buy", "purpose": "observed small-capital execution", "changes_trading": False},
    ])


def _as_bool(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False).astype(bool)
    normalized = values.astype("string").fillna("").str.strip().str.lower()
    return normalized.isin({"true", "1", "yes"})


def _selection_hash(selected: pd.DataFrame) -> str:
    if selected.empty:
        payload = "<empty>"
    else:
        keys = selected[["signal_date", "symbol"]].copy()
        keys["signal_date"] = pd.to_datetime(keys["signal_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        payload = "\n".join(
            f"{date}|{symbol}"
            for date, symbol in keys.sort_values(["signal_date", "symbol"]).itertuples(index=False, name=None)
        )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
