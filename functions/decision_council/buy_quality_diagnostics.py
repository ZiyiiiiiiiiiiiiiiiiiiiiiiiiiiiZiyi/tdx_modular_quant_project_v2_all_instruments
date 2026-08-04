"""Post-run buy-quality and selection-lineage diagnostics.

The product follows saved facts from candidate gate through proposal, plan,
registered order, fill, and (when available) a closed trade.  Missing later
stages remain missing/false; they are never inferred from an earlier stage.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


FAMILY_PREFIX = "cabinet_family_"
FAMILY_SUFFIX = "_score"


def _truth(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype("string").fillna("").str.strip().str.lower().isin({"1", "true", "yes", "y"})


def _load_candidate_partitions(run_dir: Path) -> pd.DataFrame:
    frames = []
    for path in sorted((run_dir / "_audit" / "cg").glob("cg_*.csv")):
        header = pd.read_csv(path, nrows=0).columns
        wanted = [
            "decision_id", "signal_date", "symbol", "candidate_rank", "cabinet_entry_thesis",
            "cabinet_entry_thesis_support", "mainline_v3_raw_signal", "mainline_v3_structural_feasible",
            "mainline_v3_cash_feasible", "mainline_v3_slot_feasible", "scap_optimizer_selected",
            "scap_candidate_pool_factual_feasible", "scap_candidate_pool_positive_feasible",
            "scap_candidate_utility", "scap_decision_expected_return", "scap_expected_return_lcb",
        ]
        wanted.extend(column for column in header if column.startswith(FAMILY_PREFIX) and column.endswith(FAMILY_SUFFIX))
        frames.append(pd.read_csv(path, usecols=[column for column in wanted if column in header]))
    if not frames:
        return pd.DataFrame()
    data = pd.concat(frames, ignore_index=True)
    data["signal_date"] = pd.to_datetime(data["signal_date"], errors="coerce")
    if data.duplicated(["signal_date", "symbol"]).any():
        raise RuntimeError("candidate-gate partitions contain duplicate signal_date/symbol keys")
    return data


def _aggregate_later_stages(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    proposal = pd.read_csv(
        run_dir / "governance_action_proposal_ledger.csv",
        usecols=["decision_date", "symbol", "action_type", "selected_by_plan", "hard_veto_reasons", "optimizer_rejection_reason"],
    )
    proposal["signal_date"] = pd.to_datetime(proposal["decision_date"], errors="coerce")
    proposal["is_buy_proposal"] = proposal["action_type"].astype(str).isin({"new_entry", "add", "replacement_buy"})
    proposal = proposal[proposal["is_buy_proposal"]].copy()
    proposal["selected_by_plan"] = _truth(proposal["selected_by_plan"])
    proposal_agg = proposal.groupby(["signal_date", "symbol"], as_index=False).agg(
        buy_proposal_count=("action_type", "size"),
        selected_buy_proposal=("selected_by_plan", "max"),
        proposal_action_types=("action_type", lambda x: "|".join(sorted(set(map(str, x))))),
        proposal_hard_veto_reasons=("hard_veto_reasons", lambda x: "|".join(sorted(set(str(v) for v in x if pd.notna(v) and str(v))))),
        optimizer_rejection_reasons=("optimizer_rejection_reason", lambda x: "|".join(sorted(set(str(v) for v in x if pd.notna(v) and str(v))))),
    )

    orders = pd.read_csv(
        run_dir / "executable_order_plan.csv",
        usecols=["decision_date", "symbol", "side", "action_plan_selected", "action_plan_id", "reason"],
    )
    orders = orders[orders["side"].astype(str).eq("buy")].copy()
    orders["signal_date"] = pd.to_datetime(orders["decision_date"], errors="coerce")
    orders["action_plan_selected"] = _truth(orders["action_plan_selected"])
    order_agg = orders.groupby(["signal_date", "symbol"], as_index=False).agg(
        registered_buy_order=("side", "size"),
        action_plan_selected=("action_plan_selected", "max"),
        buy_order_reasons=("reason", lambda x: "|".join(sorted(set(map(str, x))))),
        action_plan_ids=("action_plan_id", lambda x: "|".join(sorted(set(str(v) for v in x if pd.notna(v))))),
    )
    order_agg["registered_buy_order"] = order_agg["registered_buy_order"].gt(0)

    fills = pd.read_csv(
        run_dir / "governance_execution_ledger.csv",
        usecols=["signal_date", "trade_date", "symbol", "side", "executed_shares", "trade_notional", "total_cost", "order_id", "fill_id"],
    )
    fills = fills[fills["side"].astype(str).eq("buy")].copy()
    fills["signal_date"] = pd.to_datetime(fills["signal_date"], errors="coerce")
    fills["executed_shares"] = pd.to_numeric(fills["executed_shares"], errors="coerce").fillna(0.0)
    fills = fills[fills["executed_shares"].gt(0)].copy()
    fill_agg = fills.groupby(["signal_date", "symbol"], as_index=False).agg(
        executed_buy=("executed_shares", lambda x: bool(pd.to_numeric(x, errors="coerce").sum() > 0)),
        executed_buy_shares=("executed_shares", "sum"),
        executed_buy_notional=("trade_notional", "sum"),
        executed_buy_cost=("total_cost", "sum"),
        first_trade_date=("trade_date", "min"),
        buy_order_ids=("order_id", lambda x: "|".join(sorted(set(map(str, x))))),
        fill_ids=("fill_id", lambda x: "|".join(sorted(set(map(str, x))))),
    )
    return proposal_agg, order_agg, fill_agg


def _stage_summary(lineage: pd.DataFrame, grouping: list[str]) -> pd.DataFrame:
    stage_columns = [
        "candidate_gate", "mainline_v3_raw_signal", "mainline_v3_structural_feasible",
        "mainline_v3_cash_feasible", "mainline_v3_slot_feasible", "optimizer_selected",
        "selected_buy_proposal", "registered_buy_order", "executed_buy",
    ]
    rows = []
    for stage in stage_columns:
        selected = lineage[_truth(lineage[stage])]
        for key, group in selected.groupby(grouping, dropna=False, sort=True):
            key = key if isinstance(key, tuple) else (key,)
            row = dict(zip(grouping, key))
            row.update({"stage": stage, "sample_count": int(len(group)), "symbol_count": int(group["symbol"].nunique())})
            for horizon in (5, 10, 20):
                outcome = pd.to_numeric(group[f"forward_return_{horizon}d"], errors="coerce").dropna()
                row[f"outcome_count_{horizon}d"] = int(len(outcome))
                row[f"mean_forward_return_{horizon}d"] = float(outcome.mean()) if not outcome.empty else np.nan
                row[f"hit_rate_{horizon}d"] = float(outcome.gt(0).mean()) if not outcome.empty else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def build_buy_quality_diagnostics(run_dir: str | Path, output_dir: str | Path | None = None) -> dict:
    run_dir = Path(run_dir).resolve()
    output_dir = Path(output_dir).resolve() if output_dir is not None else run_dir / "buy_quality_diagnostics"
    output_dir.mkdir(parents=True, exist_ok=True)
    lineage = _load_candidate_partitions(run_dir)
    lineage["candidate_gate"] = True

    outcomes = pd.read_csv(
        run_dir / "governance_layer_validation_candidate_detail.csv",
        usecols=["signal_date", "symbol", "forward_return_5d", "forward_return_10d", "forward_return_20d"],
    )
    outcomes["signal_date"] = pd.to_datetime(outcomes["signal_date"], errors="coerce")
    outcomes = outcomes.drop_duplicates(["signal_date", "symbol"], keep="last")
    lineage = lineage.merge(outcomes, on=["signal_date", "symbol"], how="left", validate="one_to_one")

    states = pd.read_csv(
        run_dir / "governance_daily_result.csv",
        usecols=["date", "regime_name", "policy_band_state", "nominal_nav"],
    ).rename(columns={"date": "signal_date", "regime_name": "safety_structural_state", "policy_band_state": "safety_policy_band"})
    states["signal_date"] = pd.to_datetime(states["signal_date"], errors="coerce")
    states = states.drop_duplicates("signal_date", keep="last")
    lineage = lineage.merge(states, on="signal_date", how="left", validate="many_to_one")

    proposal, orders, fills = _aggregate_later_stages(run_dir)
    for stage in (proposal, orders, fills):
        lineage = lineage.merge(stage, on=["signal_date", "symbol"], how="left", validate="one_to_one")
    boolean_columns = [
        "mainline_v3_raw_signal", "mainline_v3_structural_feasible", "mainline_v3_cash_feasible",
        "mainline_v3_slot_feasible", "scap_optimizer_selected", "selected_buy_proposal",
        "action_plan_selected", "registered_buy_order", "executed_buy",
    ]
    for column in boolean_columns:
        lineage[column] = _truth(lineage.get(column, pd.Series(False, index=lineage.index)))

    # Candidate partitions are captured before the one authoritative optimizer
    # invocation.  The append-only proposal/plan ledger is the factual source
    # of optimizer selection; retain the earlier field only as a snapshot.
    lineage["candidate_snapshot_optimizer_selected"] = lineage["scap_optimizer_selected"]
    lineage["optimizer_selected"] = lineage["selected_buy_proposal"]

    family_columns = [column for column in lineage if column.startswith(FAMILY_PREFIX) and column.endswith(FAMILY_SUFFIX)]
    family_values = lineage[family_columns].apply(pd.to_numeric, errors="coerce")
    lineage["recomputed_top_family_all_roles"] = family_values.idxmax(axis=1).str.removeprefix(FAMILY_PREFIX).str.removesuffix(FAMILY_SUFFIX)
    semantic = pd.read_csv(run_dir / "governance_factor_semantic_contract.csv")
    eligible_families = sorted(
        semantic.loc[
            semantic["primary_role"].astype(str).isin({"entry_alpha", "entry_alpha_proxy"}),
            "economic_family",
        ].dropna().astype(str).unique()
    )
    eligible_columns = [f"{FAMILY_PREFIX}{name}{FAMILY_SUFFIX}" for name in eligible_families if f"{FAMILY_PREFIX}{name}{FAMILY_SUFFIX}" in family_values]
    eligible_values = family_values[eligible_columns]
    lineage["recomputed_top_entry_family"] = eligible_values.idxmax(axis=1).str.removeprefix(FAMILY_PREFIX).str.removesuffix(FAMILY_SUFFIX)
    lineage["thesis_matches_top_entry_family"] = lineage["cabinet_entry_thesis"].astype(str).eq(lineage["recomputed_top_entry_family"])
    lineage["entry_month"] = lineage["signal_date"].dt.to_period("M").astype(str)

    trades = pd.read_csv(
        run_dir / "governance_trade_pairs.csv",
        usecols=["symbol", "entry_order_id", "realized_pnl_amount", "realized_pnl_pct", "is_win", "holding_days", "close_reason"],
    )
    trade_agg = trades.groupby("entry_order_id", as_index=False).agg(
        closed_trade_count=("symbol", "size"), realized_pnl_amount=("realized_pnl_amount", "sum"),
        realized_pnl_pct=("realized_pnl_pct", "mean"), realized_win=("is_win", "max"),
        closed_holding_days=("holding_days", "mean"), close_reasons=("close_reason", lambda x: "|".join(sorted(set(map(str, x))))),
    )
    executed = lineage[lineage["executed_buy"]].copy()
    executed["primary_buy_order_id"] = executed["buy_order_ids"].fillna("").astype(str).str.split("|").str[0]
    executed = executed.merge(trade_agg, left_on="primary_buy_order_id", right_on="entry_order_id", how="left", validate="many_to_one")

    by_month = _stage_summary(lineage, ["entry_month", "safety_structural_state"])
    by_thesis = _stage_summary(lineage, ["cabinet_entry_thesis", "safety_structural_state"])
    executed_summary = (
        executed.groupby(["entry_month", "cabinet_entry_thesis", "safety_structural_state"], dropna=False)
        .agg(
            executed_buy_count=("symbol", "size"), closed_trade_count=("closed_trade_count", "sum"),
            realized_pnl_amount=("realized_pnl_amount", "sum"), mean_realized_pnl_pct=("realized_pnl_pct", "mean"),
            realized_win_rate=("realized_win", "mean"), mean_holding_days=("closed_holding_days", "mean"),
            mean_forward_return_5d=("forward_return_5d", "mean"), mean_forward_return_10d=("forward_return_10d", "mean"),
            mean_forward_return_20d=("forward_return_20d", "mean"), mean_entry_nav=("nominal_nav", "mean"),
        ).reset_index()
    )

    lineage.to_csv(output_dir / "governance_buy_quality_lineage.csv", index=False, encoding="utf-8-sig")
    by_month.to_csv(output_dir / "governance_buy_quality_by_month.csv", index=False, encoding="utf-8-sig")
    by_thesis.to_csv(output_dir / "governance_buy_quality_by_thesis.csv", index=False, encoding="utf-8-sig")
    executed.to_csv(output_dir / "governance_executed_buy_quality.csv", index=False, encoding="utf-8-sig")
    executed_summary.to_csv(output_dir / "governance_executed_buy_quality_summary.csv", index=False, encoding="utf-8-sig")

    monotone_columns = [
        "candidate_gate", "mainline_v3_raw_signal", "mainline_v3_structural_feasible",
        "mainline_v3_cash_feasible", "mainline_v3_slot_feasible", "optimizer_selected", "executed_buy",
    ]
    counts = {column: int(_truth(lineage[column]).sum()) for column in monotone_columns}
    manifest = {
        "contract": "post_run_read_only_no_decision_authority",
        "source_run": str(run_dir),
        "candidate_rows": int(len(lineage)),
        "candidate_dates": int(lineage["signal_date"].nunique()),
        "stage_counts": counts,
        "executed_buy_rows": int(len(executed)),
        "closed_trade_links": int(executed["closed_trade_count"].notna().sum()),
        "entry_thesis_eligible_families": eligible_families,
        "thesis_collapsed_family_reproduction_ratio": float(lineage["thesis_matches_top_entry_family"].mean()),
        "forward_outcome_coverage": {f"{h}d": float(lineage[f"forward_return_{h}d"].notna().mean()) for h in (5, 10, 20)},
        "caveats": [
            "forward returns are saved post-run diagnostic labels, not decision-time inputs",
            "realized PnL exists only for closed trade pairs; open fills remain missing",
            "candidate-gate lineage is conditional on the saved candidate gate and is not full-universe OOS evidence",
            "candidate snapshot optimizer flag is pre-optimizer; authoritative selection comes from the append-only proposal/plan ledger",
            "historical generic family columns collapse the same family across roles; the thesis reproduction ratio is approximate, and new runs persist cabinet_entry_family_* scores",
        ],
        "research_gate": "blocked",
        "production_gate": "blocked",
    }
    (output_dir / "buy_quality_diagnostics_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
