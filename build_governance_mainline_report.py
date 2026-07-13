# -*- coding: utf-8 -*-
"""Build a focused governance mainline review report."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from config import DEFAULT_ALPHA_BUNDLE, DEFAULT_GOVERNANCE_VARIANT, REPORT_DIR
from functions.data_integrity import build_data_integrity_report
from functions.decision_council.ml_metrics import compute_all_metrics
from functions.formal_admission import build_formal_admission_report
from functions.decision_council.factor_source import (
    FACTOR_SOURCE_LEGACY,
    LEGACY_GOVERNANCE_ALPHA_BUNDLE,
    factor_source_output_label,
    resolve_factor_source,
)


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = REPORT_DIR
REVIEW_UNIVERSES = ("hs300_csi500_a500_strict", "hs300_strict")
DEFAULT_REVIEW_ALPHA_BUNDLE = "diversified_pre_screen_bundle_v2"


def _legacy_summary_path(universe_name: str, *, alpha_bundle: str) -> Path:
    return (
        PROJECT_DIR
        / "results"
        / "governance"
        / universe_name
        / DEFAULT_GOVERNANCE_VARIANT
        / alpha_bundle
        / "governance_strategy_summary.csv"
    )


def _alpha_bundle_dir(universe_name: str, *, alpha_bundle: str) -> Path:
    return (
        PROJECT_DIR
        / "results"
        / "governance"
        / universe_name
        / DEFAULT_GOVERNANCE_VARIANT
        / alpha_bundle
    )


def _candidate_summary_paths(universe_name: str, *, alpha_bundle: str) -> list[Path]:
    base = _alpha_bundle_dir(universe_name, alpha_bundle=alpha_bundle)
    paths: list[Path] = []
    legacy = _legacy_summary_path(universe_name, alpha_bundle=alpha_bundle)
    if legacy.exists():
        paths.append(legacy)
    if base.exists():
        paths.extend(sorted(base.glob("**/governance_strategy_summary.csv")))
    unique: dict[str, Path] = {}
    for path in paths:
        unique[str(path.resolve())] = path
    return list(unique.values())


def _read_capital_usage_mode(output_dir: Path, summary: pd.DataFrame) -> str:
    if "capital_usage_mode" in summary.columns:
        values = summary["capital_usage_mode"].dropna().astype(str)
        if not values.empty:
            return values.iloc[-1]
    daily_path = output_dir / "governance_daily_result.csv"
    if daily_path.exists() and daily_path.stat().st_size > 5:
        try:
            daily = pd.read_csv(daily_path, usecols=lambda column: column in {"capital_usage_mode"})
            values = daily.get("capital_usage_mode", pd.Series(dtype=str)).dropna().astype(str)
            if not values.empty:
                return values.iloc[-1]
        except Exception:
            pass
    path_text = str(output_dir).lower()
    if "force" in path_text:
        return "force_deploy"
    if "cashok" in path_text:
        return "allow_cash"
    return "unknown"


def _run_id_from_output_dir(output_dir: Path) -> str:
    for part in reversed(output_dir.parts):
        if str(part).startswith("run"):
            return str(part)
    return "legacy"


def _load_universe_rows(*, alpha_bundle: str = DEFAULT_REVIEW_ALPHA_BUNDLE) -> pd.DataFrame:
    rows = []
    for universe_name in REVIEW_UNIVERSES:
        expected_dir = _alpha_bundle_dir(universe_name, alpha_bundle=alpha_bundle)
        summary_paths = _candidate_summary_paths(universe_name, alpha_bundle=alpha_bundle)
        if not summary_paths:
            rows.append(
                {
                    "universe_name": universe_name,
                    "alpha_bundle": alpha_bundle,
                    "status": "missing_results",
                    "expected_search_dir": str(expected_dir),
                    "found_output_dir": "",
                    "run_id": "",
                    "capital_usage_mode": "",
                }
            )
            continue
        for summary_path in summary_paths:
            output_dir = summary_path.parent
            try:
                summary = pd.read_csv(summary_path)
            except Exception as exc:
                rows.append(
                    {
                        "universe_name": universe_name,
                        "alpha_bundle": alpha_bundle,
                        "status": "read_error",
                        "error": str(exc),
                        "expected_search_dir": str(expected_dir),
                        "found_output_dir": str(output_dir),
                        "run_id": _run_id_from_output_dir(output_dir),
                    }
                )
                continue
            if summary.empty:
                rows.append(
                    {
                        "universe_name": universe_name,
                        "alpha_bundle": alpha_bundle,
                        "status": "empty_summary",
                        "expected_search_dir": str(expected_dir),
                        "found_output_dir": str(output_dir),
                        "run_id": _run_id_from_output_dir(output_dir),
                    }
                )
                continue
            row = summary.iloc[0].to_dict()
            row["universe_name"] = universe_name
            row["alpha_bundle"] = str(row.get("alpha_bundle") or alpha_bundle)
            row["status"] = "completed"
            row["expected_search_dir"] = str(expected_dir)
            row["found_output_dir"] = str(output_dir)
            row["run_id"] = _run_id_from_output_dir(output_dir)
            row["capital_usage_mode"] = _read_capital_usage_mode(output_dir, summary)
            row["_output_mtime"] = summary_path.stat().st_mtime
            row.update(compute_all_metrics(output_dir))
            rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty or "status" not in frame.columns:
        return frame
    completed = frame[frame["status"].astype(str).eq("completed")].copy()
    other = frame[~frame["status"].astype(str).eq("completed")].copy()
    if completed.empty:
        return frame
    completed["trading_days"] = pd.to_numeric(completed.get("trading_days"), errors="coerce").fillna(0.0)
    completed["_output_mtime"] = pd.to_numeric(completed.get("_output_mtime"), errors="coerce").fillna(0.0)
    completed = (
        completed.sort_values(["universe_name", "capital_usage_mode", "trading_days", "_output_mtime"])
        .groupby(["universe_name", "capital_usage_mode"], as_index=False, dropna=False)
        .tail(1)
    )
    result = pd.concat([completed, other], ignore_index=True, sort=False)
    return result.drop(columns=["_output_mtime"], errors="ignore")


def _load_safety_failure_messages() -> list[str]:
    verify_path = PROJECT_DIR / "verify_decision_council_phase_one.py"
    text = verify_path.read_text(encoding="utf-8")
    patterns = [
        "confirmed safety signal should require consecutive stress days",
        "confirmed safety signal should react after stress persists",
        "safety exposure cap should fall under stress",
    ]
    found = []
    for pattern in patterns:
        if pattern in text:
            found.append(pattern)
    return found


def _format_blocker_table(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return ["No blocker data available."]
    cols = [column for column in ["gate", "status", "formal_block_reason_code", "detail"] if column in frame.columns]
    return [frame.loc[:, cols].to_markdown(index=False)]


def _recommendation_lines(blocked: pd.DataFrame) -> list[str]:
    lines = []
    blocker_map = {
        "pit_adjustment_artifact": "Freeze one authoritative PIT adjustment artifact, add source/version checks, and bind it into the formal manifest.",
        "corporate_action_artifact": "Promote corporate action history from exploratory artifact to audited PIT ledger with ex-date / pay-date reconciliation.",
        "benchmark_report": "Define an investable benchmark series and publish excess-return validation instead of the current safety-only proxy status.",
        "v6_data_verified": "Close the remaining V6 objective gates before any formal admission attempt.",
        "feature_timestamp_audit": "Move timestamp audit from artifact existence to explicit pass/fail evidence in every formal run.",
        "reproducibility_manifest": "Package code snapshot, config snapshot, input fingerprints, and run command into one reproducible release artifact.",
        "test_lock_enabled": "Keep test lock enabled so post-test contamination cannot invalidate the admission package.",
    }
    for gate in blocked.get("gate", pd.Series(dtype=str)).astype(str).tolist():
        recommendation = blocker_map.get(gate)
        if recommendation and recommendation not in lines:
            lines.append(f"- `{gate}`: {recommendation}")
    return lines


def build_report(
    *,
    alpha_bundle: str = DEFAULT_REVIEW_ALPHA_BUNDLE,
    factor_source: str = FACTOR_SOURCE_LEGACY,
    factor_cabinet_run_id: str = "",
    factor_cabinet_path: str = "",
) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    factor_spec = resolve_factor_source(
        factor_source=factor_source,
        factor_cabinet_run_id=factor_cabinet_run_id,
        factor_cabinet_path=factor_cabinet_path,
        alpha_bundle=alpha_bundle,
    )
    effective_alpha_bundle = factor_source_output_label(factor_spec)
    universe_rows = _load_universe_rows(alpha_bundle=effective_alpha_bundle)
    comparison_path = OUTPUT_DIR / "governance_mainline_review_summary.csv"
    universe_rows.to_csv(comparison_path, index=False, encoding="utf-8-sig")
    history_dir = OUTPUT_DIR / "governance_mainline_history"
    history_dir.mkdir(parents=True, exist_ok=True)
    snapshot_tag = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    snapshot_comparison_path = history_dir / f"governance_mainline_review_summary_{snapshot_tag}.csv"
    universe_rows.to_csv(snapshot_comparison_path, index=False, encoding="utf-8-sig")

    formal = build_formal_admission_report()
    integrity = build_data_integrity_report()
    safety_failures = _load_safety_failure_messages()

    completed = universe_rows[universe_rows.get("status", "").astype(str) == "completed"].copy()
    completed = completed.sort_values("total_return", ascending=False) if not completed.empty and "total_return" in completed.columns else completed

    lines = [
        "# Governance Mainline Phase 1.5 Review",
        "",
        "## Mainline Decision",
        f"- Variant: `{DEFAULT_GOVERNANCE_VARIANT}`",
        f"- Alpha bundle: `{effective_alpha_bundle}`",
        f"- Factor source: `{factor_spec.factor_source}`",
        f"- Factor cabinet run id: `{factor_spec.factor_cabinet_run_id}`",
        f"- Factor cabinet path: `{factor_spec.factor_cabinet_path}`",
        f"- Factor count: `{factor_spec.factor_count}`",
        f"- Role distribution: `{factor_spec.role_distribution or {}}`",
        f"- Strict entry alpha count: `{factor_spec.strict_entry_alpha_count}`",
        f"- Proxy entry alpha count: `{factor_spec.proxy_entry_alpha_count}`",
        "- Review scope: `hs300_csi500_a500_strict` and `hs300_strict` only",
        "- Universe note: `CSI500` remains the intended second-layer pool because it adds a distinct mid-cap constituent set instead of duplicating the `HS300/CSI300` large-cap exposure.",
        "",
        "## Result Comparison",
    ]
    if completed.empty:
        lines.append("No completed governance outputs were found for the requested review scope.")
    else:
        cols = [
            column
            for column in [
                "universe_name",
                "run_id",
                "capital_usage_mode",
                "factor_source",
                "factor_cabinet_run_id",
                "factor_cabinet_path",
                "factor_count",
                "role_distribution",
                "strict_entry_alpha_count",
                "proxy_entry_alpha_count",
                "found_output_dir",
                "date_window",
                "total_return",
                "annual_return",
                "sharpe",
                "calmar",
                "sortino",
                "max_drawdown",
                "win_rate",
                "negative_block_rate",
                "top1_weight",
                "top5_weight_sum",
                "effective_n",
                "concentration_method",
                "trading_freeze_trigger_count",
                "emergency_deleveraging_trigger_count",
                "portfolio_exposure_cap",
                "research_gate_status",
                "research_gate_fail_count",
                "alpha_driven_trade_count",
                "force_deploy_defensive_trade_count",
            ]
            if column in completed.columns
        ]
        lines.append(completed.loc[:, cols].to_markdown(index=False))
        best = completed.iloc[0]
        date_windows = completed["date_window"].dropna().astype(str).unique().tolist() if "date_window" in completed.columns else []
        lines.extend(
            [
                "",
                "### Review Readout",
                f"- Preferred review universe: `{best['universe_name']}` based on current total return / Sharpe leadership inside the narrowed scope.",
                "- Keep `hs300_strict` as the tighter-control benchmark line, not as the primary deployment target.",
                "- Treat emergency deleveraging counts as provisional until the safety-chain verification is green.",
            ]
        )
        concentration_methods = completed.get("concentration_method", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()
        if concentration_methods and any("recompute_required" in item for item in concentration_methods):
            lines.append("- At least one reviewed universe is using legacy artifacts without a holdings ledger; concentration metrics for that run require a fresh replay to become trustworthy.")
        if len(date_windows) > 1:
            lines.append("- Current review windows are not aligned across universes yet; treat this report as a staging review until both universes finish on the same date range.")

    lines.extend(
        [
            "",
            "## Institutional Blockers",
            "- These are the blockers that keep reports at `Formal eligible=False`.",
            "",
            "### Formal Admission Gates",
        ]
    )
    lines.extend(_format_blocker_table(formal))
    lines.extend(["", "### Data Integrity Gates"])
    lines.extend(_format_blocker_table(integrity.assign(formal_block_reason_code="")))

    failed_formal = formal[formal.get("status", "").astype(str) != "passed"].copy()
    lines.extend(["", "### Recommended Closure Path"])
    lines.extend(_recommendation_lines(failed_formal) or ["- No formal blockers detected."])

    lines.extend(
        [
            "",
            "## Behavioral Blockers",
            "- The main issue is not simply low return. The safety confirmation chain is not yet trustworthy enough for deployment-grade drawdown interpretation.",
            "- The problematic chain is: `raw_risk_level -> trigger_streak_days -> risk_level -> exposure_cap`.",
            "",
            "### Current Safety Verification Focus",
        ]
    )
    for item in safety_failures:
        lines.append(f"- `{item}`")
    lines.extend(
        [
            "",
            "### Why This Matters",
            "- If consecutive-stress confirmation is wrong, the model may de-risk too early or too late.",
            "- If confirmed `risk_level` is wrong, the report's emergency deleveraging counts are not reliable evidence of correct policy behavior.",
            "- If `exposure_cap` does not fall when confirmed stress is present, backtest drawdown control is overstated.",
            "",
            "### Safety Remediation Plan",
            "1. Build a day-by-day audit table for stress episodes showing benchmark drawdown, liquidity stress, raw level, streak, confirmed level, and final exposure cap.",
            "2. Reconcile the synthetic verification scenario in `verify_decision_council_phase_one.py` with the exact threshold logic in `functions/decision_council/safety.py`.",
            "3. Confirm whether the mismatch is in signal construction, confirmation counting, or cap mapping before any alpha conclusion is trusted.",
            "4. Re-run the two review universes after the safety chain is green and compare trigger counts again before changing alpha conclusions.",
            "",
            "## Mainline Review Workstream",
            "- Revenue source review: inspect which alpha contributors dominate selected names in `hs300_csi500_a500_strict` versus `hs300_strict`.",
            "- Drawdown source review: align the largest NAV drawdown windows with the safety ledger and execution ledger.",
            "- Risk trigger review: isolate every freeze / deleverage episode and classify it as justified, delayed, or false-positive.",
            "",
            "## Benchmark and Formalization Workstream",
            "- Define one investable benchmark for governance results and publish excess-return calculations beside the safety proxy.",
            "- Promote PIT adjustment, corporate action, and universe evidence from 'artifact exists' to 'audited pass/fail with coverage proof'.",
            "- Produce a formal run package containing config snapshot, code snapshot, input fingerprints, output fingerprints, and admission verdict.",
            "",
            "## Go-Live Acceptance Template",
            "- Verification: `verify_decision_council_phase_one.py` must pass with no manual waivers.",
            "- Formal gates: no failed item in the formal admission report for PIT, benchmark, reproducibility, or timestamp evidence.",
            "- Mainline performance: `hs300_csi500_a500_strict` must remain better than or comparable to `hs300_strict` on return-adjusted-risk metrics, not just raw return.",
            "- Safety credibility: every emergency deleveraging episode in the narrowed review scope must be explainable from the safety ledger.",
            "- Reporting package: keep performance, drawdown, rolling Sharpe, capital allocation, holdings, and explicit overfitting diagnostics in the final delivery bundle.",
            "",
            f"Generated comparison CSV: `{comparison_path}`",
        ]
    )

    report_path = OUTPUT_DIR / "governance_mainline_phase15_review.md"
    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text, encoding="utf-8")
    snapshot_report_path = history_dir / f"governance_mainline_phase15_review_{snapshot_tag}.md"
    snapshot_report_path.write_text(report_text, encoding="utf-8")
    return report_path, comparison_path


def main() -> None:
    report_path, comparison_path = build_report()
    print(f"Saved report: {report_path}")
    print(f"Saved comparison: {comparison_path}")


if __name__ == "__main__":
    main()
