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
FACTOR_WORKBOOK_NAME = "SCAP_持仓逐因子曲线.xlsx"


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

    coverage = (
        factor_long.loc[factor_long["model_name"].notna(), ["date", "symbol"]]
        .drop_duplicates()
        .shape[0]
    )
    full_slot = daily["holding_count"].ge(5)
    full_slot_gap = full_slot & daily["exposure_gap"].gt(0.05)
    summary = {
        "source_run": str(run_dir.resolve()),
        "date_start": str(daily["date"].min()),
        "date_end": str(daily["date"].max()),
        "trading_days": int(len(daily)),
        "held_symbol_count": int(holdings["symbol"].nunique()),
        "holding_symbol_days": int(len(holding_keys)),
        "factor_model_count": int(factor_long["model_name"].nunique()),
        "factor_score_rows": int(len(factor_long)),
        "covered_holding_symbol_days": int(coverage),
        "full_slot_days": int(full_slot.sum()),
        "full_slot_gap_gt_5pct_days": int(full_slot_gap.sum()),
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
        matrix = (
            symbol_rows.pivot_table(
                index="date",
                columns="model_name",
                values="predicted_return_5d",
                aggfunc="last",
            )
            .sort_index()
        )
        top_factors = (
            matrix.std(axis=0)
            .fillna(0.0)
            .sort_values(ascending=False)
            .head(12)
            .index.astype(str)
            .tolist()
        )
        held = (
            holdings[holdings["symbol"].astype(str).eq(str(symbol))]
            .sort_values("date")
            .drop_duplicates("date", keep="last")
            .set_index("date")
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
) -> dict[str, object]:
    """Create the standard post-run factor dataset and Excel product.

    The product remains read-only and is deliberately generated only from
    persisted run ledgers.  It never participates in same-run decisions.
    """
    run_dir = Path(run_dir).resolve()
    output_dir = run_dir / FACTOR_PRODUCT_DIRNAME
    summary = build_dataset(run_dir, output_dir)
    product_status: dict[str, object] = {
        **summary,
        "data_dir": str(output_dir),
        "workbook_status": "not_requested",
        "workbook_path": "",
    }
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
                product_status.update(
                    {
                        "workbook_status": "ok",
                        "workbook_path": str(workbook_path),
                        "workbook_bytes": int(workbook_path.stat().st_size),
                    }
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
