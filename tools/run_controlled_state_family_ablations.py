"""Run two one-variable SCAP policy ablations on a frozen window."""

from __future__ import annotations

import argparse
import gc
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_backtest_capital_profile
from run_governance_experiments import run_single_experiment


def _output_dir(saved: dict) -> Path:
    paths = [Path(value).parent for value in saved.values() if isinstance(value, Path)]
    if not paths:
        raise RuntimeError("controlled ablation returned no saved paths")
    return paths[0]


def _row(output_dir: Path, *, experiment: str, changed_variable: str) -> dict:
    summary = pd.read_csv(output_dir / "governance_strategy_summary.csv").iloc[-1]
    daily = pd.read_csv(output_dir / "governance_daily_result.csv", low_memory=False)
    execution = pd.read_csv(
        output_dir / "governance_execution_ledger.csv", low_memory=False
    )
    buys = execution[
        execution.get("side", pd.Series(index=execution.index, dtype=str))
        .astype(str)
        .eq("buy")
    ]
    return {
        "experiment": experiment,
        "changed_variable": changed_variable,
        "output_dir": str(output_dir),
        "runtime_identity_hash": summary.get("runtime_identity_hash", ""),
        "trading_days": summary.get("trading_days"),
        "total_return": summary.get("total_return"),
        "max_drawdown": summary.get("max_drawdown"),
        "closed_trade_count": summary.get("closed_trade_count"),
        "profit_factor": summary.get("profit_factor"),
        "average_exposure": pd.to_numeric(
            daily.get("actual_exposure"), errors="coerce"
        ).mean(),
        "average_holding_count": pd.to_numeric(
            daily.get("holding_count"), errors="coerce"
        ).mean(),
        "executed_buy_fills": int(len(buys)),
    }


def _run(*, suffix: str, profile: dict, start: str, end: str, days: int,
         overlay_enabled: bool, overlay_mode: str) -> Path:
    saved = run_single_experiment(
        variant_name="governance_layer_validation",
        alpha_bundle="diversified_pre_screen_bundle_v2",
        universe_name="all_a_share_research",
        start_date=start,
        end_date=end,
        max_days=days,
        safety_proxy_mode="strict",
        low_memory=True,
        enable_shadow_portfolios=False,
        show_live_monitor=False,
        output_dir_suffix=suffix,
        initial_cash=20_000.0,
        max_positions=None,
        capital_profile=profile,
        governance_control_mode="aggressive_lean",
        alpha_collapse_exit_enabled=True,
        factor_source="selected_factor_cabinet",
        factor_cabinet_run_id="pruned_run20260714_184846_581132_20260715_230524",
        strategy_logic_version="mainline_v3_cabinet_native",
        regime_overlay_mode_override=overlay_mode,
        enable_market_regime_policy_override=overlay_enabled,
        pit_mode="research",
        performance_benchmark_top_n=100,
        performance_benchmark_rebalance="monthly",
    )
    return _output_dir(saved)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--max-days", type=int, required=True)
    parser.add_argument("--matrix-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base = get_backtest_capital_profile(
        "small_capital_lean",
        initial_cash=20_000.0,
        min_cash_buffer=1_000.0,
        capital_usage_mode="allow_cash",
    )
    rows = []
    control_dir = _run(
        suffix=f"{args.matrix_id}_control",
        profile=dict(base),
        start=args.start_date,
        end=args.end_date,
        days=args.max_days,
        overlay_enabled=False,
        overlay_mode="off",
    )
    rows.append(
        _row(
            control_dir,
            experiment="control",
            changed_variable="none_frozen_reference",
        )
    )
    pd.DataFrame(rows).to_csv(args.output, index=False, encoding="utf-8-sig")
    gc.collect()

    state_dir = _run(
        suffix=f"{args.matrix_id}_state_overlay_full",
        profile=dict(base),
        start=args.start_date,
        end=args.end_date,
        days=args.max_days,
        overlay_enabled=True,
        overlay_mode="full",
    )
    rows.append(
        _row(
            state_dir,
            experiment="state_overlay_full",
            changed_variable="optional_regime_overlay:false_to_true_full",
        )
    )
    pd.DataFrame(rows).to_csv(args.output, index=False, encoding="utf-8-sig")
    gc.collect()

    family_profile = dict(base)
    family_profile["scap_candidate_pool_per_thesis"] = 1
    family_dir = _run(
        suffix=f"{args.matrix_id}_family_reserve_one",
        profile=family_profile,
        start=args.start_date,
        end=args.end_date,
        days=args.max_days,
        overlay_enabled=False,
        overlay_mode="off",
    )
    rows.append(
        _row(
            family_dir,
            experiment="family_reserve_one",
            changed_variable="scap_candidate_pool_per_thesis:2_to_1",
        )
    )
    pd.DataFrame(rows).to_csv(args.output, index=False, encoding="utf-8-sig")
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "matrix_id": args.matrix_id,
                "start_date": args.start_date,
                "end_date": args.end_date,
                "max_days": args.max_days,
                "control_reference": "same-process control row",
                "experiments": [
                    {
                        "name": "control",
                        "single_change": "none; frozen reference",
                    },
                    {
                        "name": "state_overlay_full",
                        "single_change": "enable optional regime overlay in full mode",
                    },
                    {
                        "name": "family_reserve_one",
                        "single_change": "candidate pool reserve per thesis from 2 to 1",
                    },
                ],
                "fixed": {
                    "initial_cash": 20_000.0,
                    "cash_buffer_amount": 1_000.0,
                    "factor_cabinet": "b8dd096a6706b63e6e960d01e23fa647763b7cd5113ace055db58e2395788b90",
                    "universe": "all_a_share_research",
                    "pit_mode": "research",
                    "cost_model": "same configured model",
                },
                "decision_authority": "none_research_only",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
