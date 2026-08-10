"""Build auditable held-stock factor-curve products from one governance run.

This is a post-run diagnostic only.  It never feeds future or holding-period
information back into the strategy.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_NODE = Path(
    r"C:\Users\Ziyi Wang\.cache\codex-runtimes\codex-primary-runtime"
    r"\dependencies\node\bin\node.exe"
)
FACTOR_PRODUCT_DIRNAME = "holding_factor_curves"
# This name crosses a Python -> Node subprocess boundary on Windows.  Keep the
# machine path ASCII-stable; localized download labels belong to HTTP headers,
# not the filesystem contract.
FACTOR_WORKBOOK_NAME = "SCAP_holding_factor_curves.xlsx"


def workbook_content_check_failures(summary: dict) -> list[str]:
    failures: list[str] = []
    if int(summary.get("unexpected_holding_factor_coverage_gap_count", 0)) > 0:
        failures.append("holding_symbol_day_factor_coverage")
    if int(summary.get("held_symbol_count", 0)) > 0 and int(
        summary.get("factor_model_count", 0)
    ) <= 0:
        failures.append("held_positions_without_factor_models")
    return failures


def classify_holding_factor_coverage(
    holding_keys: pd.DataFrame,
    observed_counts: pd.DataFrame,
    position_state: pd.DataFrame,
    *,
    expected_factor_count: int,
) -> pd.DataFrame:
    """Classify held-symbol-day factor coverage without inventing stale scores.

    A held position can legitimately have no same-day factor observation when
    the persisted lifecycle ledger proves that the current feature row was
    unavailable and valuation used the last known close.  This is disclosed,
    but it is not repaired by forward filling.  Any observable or ambiguous
    held day with missing/partial factor records remains a strict failure.
    """
    keys = holding_keys[["date", "symbol"]].drop_duplicates().copy()
    keys["date"] = pd.to_datetime(keys["date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    keys["symbol"] = keys["symbol"].astype(str)
    counts = observed_counts[["date", "symbol", "observed_factor_count"]].copy()
    counts["date"] = pd.to_datetime(
        counts["date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    counts["symbol"] = counts["symbol"].astype(str)
    state_columns = [
        column
        for column in (
            "date",
            "symbol",
            "position_state",
            "state_observation_status",
            "state_source_date",
            "valuation_source",
            "stale_days",
        )
        if column in position_state.columns
    ]
    states = position_state[state_columns].copy()
    states["date"] = pd.to_datetime(
        states["date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    states["symbol"] = states["symbol"].astype(str)
    states = states.drop_duplicates(["date", "symbol"], keep="last")

    detail = keys.merge(counts, on=["date", "symbol"], how="left").merge(
        states,
        on=["date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    detail["observed_factor_count"] = pd.to_numeric(
        detail["observed_factor_count"], errors="coerce"
    ).fillna(0).astype(int)
    detail["expected_factor_count"] = max(int(expected_factor_count), 0)
    position_value = detail.get(
        "position_state", pd.Series("", index=detail.index)
    ).fillna("").astype(str)
    observation_value = detail.get(
        "state_observation_status", pd.Series("", index=detail.index)
    ).fillna("").astype(str)
    valuation_value = detail.get(
        "valuation_source", pd.Series("", index=detail.index)
    ).fillna("").astype(str)
    stale_days = pd.to_numeric(
        detail.get("stale_days", pd.Series(float("nan"), index=detail.index)),
        errors="coerce",
    )
    detail["market_observed"] = ~observation_value.eq(
        "carried_forward_missing_current_feature"
    )
    detail["justified_unobserved_holding"] = (
        position_value.eq("held_unobserved")
        & observation_value.eq("carried_forward_missing_current_feature")
        & valuation_value.eq("last_known_close")
        & stale_days.gt(0.0)
    )
    complete = detail["observed_factor_count"].eq(
        detail["expected_factor_count"]
    ) & detail["expected_factor_count"].gt(0)
    partial = detail["observed_factor_count"].between(
        1,
        max(int(expected_factor_count) - 1, 0),
        inclusive="both",
    )
    detail["coverage_status"] = "unexpected_no_factor_record"
    detail.loc[partial, "coverage_status"] = "unexpected_partial_factor_record"
    detail.loc[
        detail["justified_unobserved_holding"]
        & detail["observed_factor_count"].eq(0),
        "coverage_status",
    ] = "justified_unobserved_holding"
    detail.loc[complete, "coverage_status"] = "complete"
    detail.loc[
        detail["justified_unobserved_holding"]
        & detail["observed_factor_count"].gt(0),
        "coverage_status",
    ] = "unexpected_factor_record_for_unobserved_holding"
    detail["coverage_complete"] = complete
    detail["coverage_gate_passed"] = detail["coverage_status"].isin(
        {"complete", "justified_unobserved_holding"}
    )
    detail["coverage_gate_failure"] = ~detail["coverage_gate_passed"]
    detail["coverage_reason"] = detail["coverage_status"]
    return detail.sort_values(["date", "symbol"]).reset_index(drop=True)


HOLDING_COLUMNS = [
    "date",
    "symbol",
    "shares",
    "price",
    "market_value",
    "account_weight",
    "portfolio_exposure",
    "entry_date",
    "entry_price",
    "unrealized_return",
    "mfe",
    "mae",
    "giveback_from_peak",
    "trend_direction_score",
    "peak_decay_score",
    "profit_protection_pressure",
    "future_loss_risk_score",
    "profit_giveback_flag",
    "post_entry_failure_flag",
]

DAILY_COLUMNS = [
    "date",
    "nominal_nav",
    "cash",
    "holding_count",
    "economic_position_cap",
    "lot_cash_position_cap",
    "cost_feasible_position_cap",
    "risk_feasible_position_cap",
    "search_position_cap",
    "effective_position_cap",
    "grandfathered_excess_names",
    "sizing_reference_positions",
    "selected_position_count",
    "actual_exposure",
    "desired_exposure_target",
    "executable_exposure_target",
    "exposure_gap",
    "raw_signal_count",
    "structural_feasible_count",
    "cash_feasible_count",
    "slot_feasible_count",
    "optimizer_selected_entry_count",
    "catchup_allowed",
    "catchup_block_reason",
    "allow_normal_rebalance",
    "coverage_mode",
    "coverage_penalty_amount",
    "profit_coverage_ratio",
    "profit_coverage_probability_lower",
    "coverage_evidence_name_count",
    "incremental_expected_wealth_amount",
    "incremental_cvar_amount",
    "model_uncertainty_amount",
    "scenario_risk_penalty_amount",
    "scenario_evidence_state",
    "scenario_contract_id",
    "scenario_risk_measure",
    "joint_scenario_count",
    "regime_es_budget_multiplier",
    "best_rejected_objective_amount",
]


def _read_columns(path: Path, columns: list[str]) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns
    selected = [column for column in columns if column in header]
    return pd.read_csv(path, usecols=selected, low_memory=False)


def build_dataset(run_dir: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    holdings = _read_columns(
        run_dir / "governance_holdings_ledger.csv",
        HOLDING_COLUMNS,
    )
    holdings["date"] = pd.to_datetime(holdings["date"]).dt.strftime("%Y-%m-%d")
    holding_keys = holdings[["date", "symbol"]].drop_duplicates()
    held_symbols = set(holding_keys["symbol"].astype(str))
    held_dates = set(holding_keys["date"].astype(str))

    proposal_parts = []
    for chunk in pd.read_csv(
        run_dir / "governance_alpha_proposals.csv",
        usecols=[
            "decision_date",
            "symbol",
            "model_name",
            "predicted_return_5d",
            "prediction_std",
            "reputation_weight",
        ],
        chunksize=250_000,
        low_memory=False,
    ):
        chunk["date"] = pd.to_datetime(chunk["decision_date"]).dt.strftime("%Y-%m-%d")
        mask = chunk["symbol"].astype(str).isin(held_symbols) & chunk["date"].isin(held_dates)
        if bool(mask.any()):
            proposal_parts.append(chunk.loc[mask].drop(columns=["decision_date"]))
    proposals = (
        pd.concat(proposal_parts, ignore_index=True)
        if proposal_parts
        else pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "model_name",
                "predicted_return_5d",
                "prediction_std",
                "reputation_weight",
            ]
        )
    )
    factor_long = holding_keys.merge(
        proposals,
        on=["date", "symbol"],
        how="left",
        validate="one_to_many",
    )

    weight_columns = [
        "date",
        "model_name",
        "factor_module",
        "factor_role",
        "weight",
        "weight_share",
    ]
    factor_weights = _read_columns(
        run_dir / "governance_factor_weight_ledger.csv",
        weight_columns,
    )
    factor_weights["date"] = pd.to_datetime(factor_weights["date"]).dt.strftime("%Y-%m-%d")
    factor_weights = factor_weights.drop_duplicates(["date", "model_name"], keep="last")
    factor_long = factor_long.merge(
        factor_weights,
        on=["date", "model_name"],
        how="left",
        validate="many_to_one",
    )
    factor_long["weighted_factor_score"] = (
        pd.to_numeric(factor_long["predicted_return_5d"], errors="coerce")
        * pd.to_numeric(factor_long["reputation_weight"], errors="coerce")
    )
    factor_long = factor_long.sort_values(
        ["symbol", "date", "factor_role", "model_name"],
        kind="stable",
    ).reset_index(drop=True)

    daily = _read_columns(run_dir / "governance_daily_result.csv", DAILY_COLUMNS)
    daily["date"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
    benchmark = _read_columns(
        run_dir / "governance_performance_benchmark.csv",
        ["date", "benchmark_net_value", "benchmark_daily_return"],
    )
    benchmark["date"] = pd.to_datetime(benchmark["date"]).dt.strftime("%Y-%m-%d")
    daily = daily.merge(benchmark, on="date", how="left", validate="one_to_one")

    trades = pd.read_csv(run_dir / "governance_trade_pairs.csv", low_memory=False)
    position_state = pd.read_csv(
        run_dir / "governance_position_state_ledger.csv",
        low_memory=False,
    )
    active_exits = position_state[
        position_state.get(
            "exit_state",
            pd.Series(False, index=position_state.index),
        ).fillna(False).astype(bool)
    ].copy()

    holdings.to_csv(output_dir / "holding_daily.csv", index=False, encoding="utf-8-sig")
    factor_long.to_csv(
        output_dir / "holding_factor_scores_long.csv",
        index=False,
        encoding="utf-8-sig",
    )
    daily.to_csv(output_dir / "daily_constraints.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(output_dir / "closed_trades.csv", index=False, encoding="utf-8-sig")
    active_exits.to_csv(
        output_dir / "active_sell_diagnostics.csv",
        index=False,
        encoding="utf-8-sig",
    )

    factor_runtime_path = run_dir / "factor_runtime_audit.json"
    factor_runtime = (
        json.loads(factor_runtime_path.read_text(encoding="utf-8-sig"))
        if factor_runtime_path.is_file()
        else {}
    )
    runtime_factor_count = int(
        factor_runtime.get(
            "loaded_factor_count",
            factor_runtime.get("runtime_model_count", 0),
        )
        or 0
    )
    observed_factor_model_count = int(factor_long["model_name"].nunique())
    factor_model_count = runtime_factor_count or observed_factor_model_count
    observed_counts = (
        factor_long.loc[factor_long["model_name"].notna()]
        .groupby(["date", "symbol"])["model_name"]
        .nunique()
        .rename("observed_factor_count")
        .reset_index()
    )
    coverage_detail = classify_holding_factor_coverage(
        holding_keys,
        observed_counts,
        position_state,
        expected_factor_count=factor_model_count,
    )
    coverage_detail.to_csv(
        output_dir / "holding_factor_coverage_detail.csv",
        index=False,
        encoding="utf-8-sig",
    )
    coverage_gaps = coverage_detail.loc[
        coverage_detail["coverage_gate_failure"]
    ].copy()
    coverage_gaps.to_csv(
        output_dir / "holding_factor_coverage_gaps.csv",
        index=False,
        encoding="utf-8-sig",
    )
    unobserved_holding_days = coverage_detail.loc[
        coverage_detail["coverage_status"].eq("justified_unobserved_holding")
    ].copy()
    unobserved_holding_days.to_csv(
        output_dir / "holding_factor_unobserved_holding_days.csv",
        index=False,
        encoding="utf-8-sig",
    )
    complete_coverage = int(coverage_detail["coverage_complete"].sum())
    gate_passed_coverage = int(coverage_detail["coverage_gate_passed"].sum())
    observable_holding_days = int(coverage_detail["market_observed"].sum())
    holding_count = pd.to_numeric(daily["holding_count"], errors="coerce").fillna(0.0)
    economic_cap = pd.to_numeric(
        daily.get("economic_position_cap", pd.Series(index=daily.index, dtype=float)),
        errors="coerce",
    )
    valid_capacity = economic_cap.gt(0.0)
    capacity_full = valid_capacity & holding_count.ge(economic_cap)
    capacity_full_gap = capacity_full & pd.to_numeric(
        daily["exposure_gap"], errors="coerce"
    ).gt(0.05)
    capacity_utilization = holding_count.div(economic_cap.where(valid_capacity))
    summary = {
        "source_run": str(run_dir.resolve()),
        "date_start": str(daily["date"].min()),
        "date_end": str(daily["date"].max()),
        "trading_days": int(len(daily)),
        "held_symbol_count": int(holdings["symbol"].nunique()),
        "holding_symbol_days": int(len(holding_keys)),
        "factor_model_count": factor_model_count,
        "observed_factor_model_count": observed_factor_model_count,
        "factor_score_rows": int(len(factor_long)),
        # Compatibility field now means strict-gate-passed held days.  The
        # observable/full distinction below is the authoritative disclosure.
        "covered_holding_symbol_days": int(gate_passed_coverage),
        "observable_holding_symbol_days": observable_holding_days,
        "covered_observable_holding_symbol_days": complete_coverage,
        "justified_unobserved_holding_days": int(len(unobserved_holding_days)),
        "unexpected_holding_factor_coverage_gap_count": int(len(coverage_gaps)),
        "holding_factor_coverage_gap_count": int(len(coverage_gaps)),
        "holding_factor_coverage_gap_preview": coverage_gaps.head(20)[
            [
                "date",
                "symbol",
                "observed_factor_count",
                "expected_factor_count",
                "coverage_reason",
            ]
        ].to_dict("records"),
        "justified_unobserved_holding_preview": unobserved_holding_days.head(20)[
            [
                "date",
                "symbol",
                "position_state",
                "state_observation_status",
                "valuation_source",
                "stale_days",
                "coverage_status",
            ]
        ].to_dict("records"),
        "economic_capacity_observed_days": int(valid_capacity.sum()),
        "economic_capacity_full_days": int(capacity_full.sum()),
        "economic_capacity_full_gap_gt_5pct_days": int(capacity_full_gap.sum()),
        "average_capacity_utilization": float(capacity_utilization.mean())
        if bool(valid_capacity.any())
        else 0.0,
        "closed_trade_count": int(len(trades)),
        "active_exit_rows": int(len(active_exits)),
        # Compatibility key retained for existing workbook payloads.
        "active_signal_failure_rows": int(len(active_exits)),
        "diagnostic_contract": "post_run_read_only_no_decision_authority",
    }
    factor_meta = (
        factor_long[
            ["model_name", "factor_role", "factor_module"]
        ]
        .dropna(subset=["model_name"])
        .drop_duplicates("model_name")
        .sort_values("model_name")
    )
    symbol_payloads = []
    for symbol, symbol_rows in factor_long.groupby("symbol", sort=True):
        held = (
            holdings[holdings["symbol"].astype(str).eq(str(symbol))]
            .sort_values("date")
            .drop_duplicates("date", keep="last")
            .set_index("date")
        )
        matrix = (
            symbol_rows.pivot_table(
                index="date",
                columns="model_name",
                values="predicted_return_5d",
                aggfunc="last",
            )
            .sort_index()
            .reindex(held.index.astype(str))
        )
        top_factors = (
            matrix.std(axis=0)
            .fillna(0.0)
            .sort_values(ascending=False)
            .head(12)
            .index.astype(str)
            .tolist()
        )
        symbol_payloads.append(
            {
                "symbol": str(symbol),
                "dates": matrix.index.astype(str).tolist(),
                "factors": matrix.columns.astype(str).tolist(),
                "values": [
                    [None if pd.isna(value) else float(value) for value in row]
                    for row in matrix.to_numpy()
                ],
                "top_factors": top_factors,
                "price": [
                    (
                        None
                        if date not in held.index or pd.isna(held.at[date, "price"])
                        else float(held.at[date, "price"])
                    )
                    for date in matrix.index.astype(str)
                ],
                "unrealized_return": [
                    (
                        None
                        if date not in held.index
                        or pd.isna(held.at[date, "unrealized_return"])
                        else float(held.at[date, "unrealized_return"])
                    )
                    for date in matrix.index.astype(str)
                ],
            }
        )
    workbook_payload = {
        "summary": summary,
        "factor_meta": factor_meta.fillna("").to_dict("records"),
        "symbols": symbol_payloads,
        "daily_constraints": json.loads(
            daily.to_json(orient="records", date_format="iso")
        ),
        "closed_trades": json.loads(
            trades.to_json(orient="records", date_format="iso")
        ),
        "active_sell_diagnostics": json.loads(
            active_exits.to_json(orient="records", date_format="iso")
        ),
    }
    (output_dir / "workbook_payload.json").write_text(
        json.dumps(workbook_payload, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "analysis_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def build_integrated_products(
    run_dir: Path,
    *,
    build_workbook: bool = True,
    strict: bool = True,
    output_dir: Path | None = None,
) -> dict[str, object]:
    """Create the standard post-run factor dataset and Excel product.

    The product remains read-only and is deliberately generated only from
    persisted run ledgers.  It never participates in same-run decisions.
    """
    run_dir = Path(run_dir).resolve()
    output_dir = (
        Path(output_dir).resolve()
        if output_dir is not None
        else run_dir / FACTOR_PRODUCT_DIRNAME
    )
    summary = build_dataset(run_dir, output_dir)
    product_status: dict[str, object] = {
        **summary,
        "data_dir": str(output_dir),
        "workbook_status": "not_requested",
        "workbook_path": "",
        "file_generated": False,
        "content_checks_passed": False,
        "content_check_failures": [],
        "visual_verification_status": "not_run",
    }
    content_failures = workbook_content_check_failures(summary)
    product_status["content_check_failures"] = content_failures
    product_status["content_checks_passed"] = not content_failures
    if build_workbook:
        node_path = Path(
            os.environ.get("TDX_ARTIFACT_NODE", str(DEFAULT_ARTIFACT_NODE))
        )
        builder_path = PROJECT_DIR / "tools" / "build_scap_factor_workbook.mjs"
        workbook_path = output_dir / FACTOR_WORKBOOK_NAME
        if not node_path.is_file():
            message = f"artifact Node executable is unavailable: {node_path}"
            product_status.update(
                {"workbook_status": "failed", "workbook_error": message}
            )
            if strict:
                raise FileNotFoundError(message)
        elif not builder_path.is_file():
            message = f"factor workbook builder is unavailable: {builder_path}"
            product_status.update(
                {"workbook_status": "failed", "workbook_error": message}
            )
            if strict:
                raise FileNotFoundError(message)
        else:
            completed = subprocess.run(
                [
                    str(node_path),
                    str(builder_path),
                    str(output_dir),
                    str(workbook_path),
                ],
                cwd=str(PROJECT_DIR),
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0 or not workbook_path.is_file():
                message = (
                    f"factor workbook build failed (exit={completed.returncode}): "
                    f"{completed.stderr.strip() or completed.stdout.strip()}"
                )
                product_status.update(
                    {"workbook_status": "failed", "workbook_error": message}
                )
                if strict:
                    raise RuntimeError(message)
            else:
                verification_dir = output_dir / "_workbook_verification"
                verifier_path = PROJECT_DIR / "tools" / "verify_scap_factor_workbook.mjs"
                verification = subprocess.run(
                    [
                        str(node_path),
                        str(verifier_path),
                        str(workbook_path),
                        str(verification_dir),
                    ],
                    cwd=str(PROJECT_DIR),
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    check=False,
                )
                visual_ok = verification.returncode == 0
                product_status.update(
                    {
                        "workbook_status": (
                            "ok"
                            if visual_ok and not content_failures
                            else "failed_content_or_visual_checks"
                        ),
                        "workbook_path": str(workbook_path),
                        "workbook_bytes": int(workbook_path.stat().st_size),
                        "file_generated": True,
                        "visual_verification_status": (
                            "passed" if visual_ok else "failed"
                        ),
                        "visual_verification_dir": str(verification_dir),
                        "visual_verification_error": (
                            ""
                            if visual_ok
                            else verification.stderr.strip()
                            or verification.stdout.strip()[-4000:]
                        ),
                    }
                )
                if strict and product_status["workbook_status"] != "ok":
                    (output_dir / "product_status.json").write_text(
                        json.dumps(product_status, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    raise RuntimeError(
                        "factor workbook content/visual verification failed: "
                        f"{product_status['content_check_failures']} | "
                        f"{product_status['visual_verification_status']}"
                    )
    (output_dir / "product_status.json").write_text(
        json.dumps(product_status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return product_status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    summary = build_dataset(args.run_dir.resolve(), args.output_dir.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
