"""Independent acceptance checks for a saved SCAP sizing-contract run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


VERSION = "scap_portfolio_sizing_v2"


def passed(message: str) -> None:
    print(f"[PASS] {message}")


def read(run_dir: Path, name: str) -> pd.DataFrame:
    path = run_dir / name
    assert path.is_file(), f"missing artifact: {path}"
    return pd.read_csv(path)


def assert_identity(frame: pd.DataFrame, column: str, label: str) -> None:
    assert column in frame.columns, f"{label} is missing {column}"
    assert frame[column].fillna("").astype(str).str.strip().ne("").all(), (
        f"{label} contains blank {column}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--expected-days", type=int, default=20)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()

    complete = json.loads((run_dir / "COMPLETE.json").read_text(encoding="utf-8"))
    assert complete["status"] == "complete"
    assert int(complete["trading_days"]) == args.expected_days
    passed("COMPLETE marker records the expected full saved window")

    daily = read(run_dir, "governance_daily_result.csv")
    assert len(daily) == args.expected_days
    assert daily["date"].nunique() == args.expected_days
    assert daily["decision_id"].nunique() == args.expected_days
    assert daily["sizing_contract_version"].eq(VERSION).all()
    assert_identity(daily, "sizing_contract_id", "daily result")
    assert daily["sizing_contract_id"].nunique() == args.expected_days
    passed("every trading day has one unique v2 sizing intent")

    numeric = lambda name: pd.to_numeric(daily[name], errors="raise")
    assert numeric("cash").ge(-1e-8).all()
    assert numeric("holding_count").ge(0).all()
    assert (
        numeric("actual_exposure") <= numeric("hard_exposure_ceiling") + 1e-9
    ).all()
    assert (
        numeric("holding_count") <= numeric("daily_effective_holding_ceiling")
    ).all()
    passed("cash, holdings, and actual exposure respect factual hard bounds")

    class_cols = [
        "plan_floor_contract_violation",
        "structural_floor_infeasible",
        "floor_violation_unresolved_search",
    ]
    classes = daily[class_cols].astype(bool).sum(axis=1)
    floor_breach = numeric("holding_floor_violation_count").gt(0) | numeric(
        "exposure_floor_violation"
    ).gt(1e-9)
    assert classes.le(1).all(), "floor classifications must be mutually exclusive"
    assert classes.loc[floor_breach].eq(1).all(), (
        "every observed floor breach must have exactly one factual classification"
    )
    passed("floor shortfalls are mutually exclusive and completely classified")

    daily_ids = daily.set_index("decision_id")["sizing_contract_id"].astype(str)
    sizing = read(run_dir, "governance_entry_sizing_audit.csv")
    assert sizing["scap_sizing_contract_version"].eq(VERSION).all()
    assert_identity(sizing, "scap_sizing_contract_id", "entry sizing audit")
    assert sizing["scap_sizing_contract_id"].astype(str).eq(
        sizing["decision_id"].map(daily_ids)
    ).all()
    final_lots = pd.to_numeric(sizing["scap_sizing_final_max_lots"], errors="raise")
    assert final_lots.ge(0).all()
    for cap in (
        "scap_sizing_authority_max_lots",
        "scap_sizing_cash_max_lots",
        "scap_sizing_single_name_max_lots",
    ):
        assert final_lots.le(pd.to_numeric(sizing[cap], errors="raise")).all()
    assert final_lots.loc[sizing["scap_v31_authority_tier"].eq("D")].eq(0).all()
    passed("candidate integer lots obey authority, cash, and single-name caps")

    lineage_specs = (
        ("governance_action_proposal_ledger.csv", "proposal"),
        ("governance_action_plan_ledger.csv", "plan"),
        ("executable_order_plan.csv", "order"),
        ("governance_execution_ledger.csv", "execution"),
    )
    frames: dict[str, pd.DataFrame] = {}
    for filename, label in lineage_specs:
        frame = read(run_dir, filename)
        frames[label] = frame
        assert_identity(frame, "sizing_contract_id", label)
        assert frame["sizing_contract_id"].astype(str).eq(
            frame["decision_id"].map(daily_ids)
        ).all(), f"{label} sizing identity does not match its daily decision"
    passed("sizing identity traces through proposals, all plans, orders, and fills")

    orders = frames["order"]
    executions = frames["execution"]
    if not orders.empty:
        buy_orders = orders[orders["side"].astype(str).str.lower().eq("buy")]
        assert pd.to_numeric(buy_orders["authorized_lots"], errors="raise").ge(1).all()
    if not executions.empty:
        buy_exec = executions[
            executions["side"].astype(str).str.lower().eq("buy")
        ]
        authorized_shares = (
            pd.to_numeric(buy_exec["authorized_lots"], errors="raise") * 100
        )
        assert pd.to_numeric(buy_exec["target_shares"], errors="raise").le(
            authorized_shares
        ).all()
        assert pd.to_numeric(buy_exec["executed_shares"], errors="raise").le(
            authorized_shares
        ).all()
    passed("buy orders and fills never exceed authorized integer lots")

    verification_path = (
        run_dir
        / "holding_factor_curves"
        / "_workbook_verification"
        / "workbook_visual_verification.json"
    )
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    assert int(verification["formulaErrorCount"]) == 0
    assert int(verification["checksFailureCount"]) == 0
    assert int(verification["sheetCount"]) >= 6
    workbook = run_dir / "holding_factor_curves" / "SCAP_持仓逐因子曲线.xlsx"
    assert workbook.is_file() and workbook.stat().st_size > 0
    passed("factor workbook content, formulas, and rendered visual checks pass")

    if args.baseline is not None:
        baseline = read(args.baseline.resolve(), "governance_daily_result.csv")
        compare_cols = [
            "date",
            "cash",
            "invested_value",
            "holding_count",
            "actual_exposure",
            "nominal_nav",
            "selected_position_count",
            "retail_order_count",
        ]
        pd.testing.assert_frame_equal(
            daily[compare_cols].reset_index(drop=True),
            baseline[compare_cols].reset_index(drop=True),
            check_exact=True,
        )
        passed("evidence-lineage fix leaves the controlled 20-day trading path unchanged")


if __name__ == "__main__":
    main()
