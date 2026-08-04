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


def _find_output_dir(saved: dict) -> Path:
    candidates = [Path(value).parent for value in saved.values() if isinstance(value, Path)]
    if not candidates:
        raise RuntimeError("controlled run returned no saved paths")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a one-variable SCAP capital matrix")
    parser.add_argument("--cash", nargs="+", type=float, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", default="2026-05-29")
    parser.add_argument("--max-days", type=int, required=True)
    parser.add_argument("--matrix-id", required=True)
    parser.add_argument("--comparison-output", required=True)
    args = parser.parse_args()
    rows = []
    for cash in args.cash:
        profile = get_backtest_capital_profile(
            "small_capital_lean", initial_cash=cash,
            min_cash_buffer=1000.0, capital_usage_mode="allow_cash",
        )
        saved = run_single_experiment(
            variant_name="governance_layer_validation",
            alpha_bundle="diversified_pre_screen_bundle_v2",
            universe_name="all_a_share_research",
            start_date=args.start_date, end_date=args.end_date, max_days=args.max_days,
            safety_proxy_mode="strict", low_memory=True,
            enable_shadow_portfolios=False, show_live_monitor=False,
            output_dir_suffix=f"{args.matrix_id}_cash_{int(cash)}",
            initial_cash=cash, max_positions=None, capital_profile=profile,
            governance_control_mode="aggressive_lean", alpha_collapse_exit_enabled=True,
            factor_source="selected_factor_cabinet",
            factor_cabinet_run_id="pruned_run20260714_184846_581132_20260715_230524",
            strategy_logic_version="mainline_v3_cabinet_native",
            pit_mode="research", performance_benchmark_top_n=100,
            performance_benchmark_rebalance="monthly",
        )
        output_dir = _find_output_dir(saved)
        summary_path = output_dir / "governance_strategy_summary.csv"
        summary = pd.read_csv(summary_path).iloc[-1].to_dict()
        daily = pd.read_csv(output_dir / "governance_daily_result.csv")
        execution = pd.read_csv(output_dir / "governance_execution_ledger.csv")
        buys = execution[execution.get("side", pd.Series(index=execution.index, dtype=str)).astype(str).eq("buy")]
        rows.append({
            "matrix_id": args.matrix_id, "initial_cash": cash, "output_dir": str(output_dir),
            "runtime_identity_hash": summary.get("runtime_identity_hash", ""),
            "trading_days": summary.get("trading_days"), "final_net_value": summary.get("final_net_value"),
            "total_return": summary.get("total_return"), "max_drawdown": summary.get("max_drawdown"),
            "closed_trade_count": summary.get("closed_trade_count"), "profit_factor": summary.get("profit_factor"),
            "average_exposure": pd.to_numeric(daily.get("actual_exposure"), errors="coerce").mean(),
            "average_holding_count": pd.to_numeric(daily.get("holding_count"), errors="coerce").mean(),
            "maximum_holding_count": pd.to_numeric(daily.get("holding_count"), errors="coerce").max(),
            "executed_buy_fills": int(len(buys)),
            "total_explicit_cost": pd.to_numeric(execution.get("total_cost"), errors="coerce").sum(),
            "observed_commission_to_notional": (
                pd.to_numeric(execution.get("commission_cost"), errors="coerce").sum()
                / max(pd.to_numeric(execution.get("trade_notional"), errors="coerce").sum(), 1e-12)
            ),
            "fixed_min_commission_buy_fill_share": (
                pd.to_numeric(buys.get("commission_cost"), errors="coerce")
                .sub(float(profile.get("minimum_commission", 5.0)))
                .abs()
                .le(1e-8)
                .mean()
                if len(buys)
                else float("nan")
            ),
        })
        pd.DataFrame(rows).to_csv(args.comparison_output, index=False, encoding="utf-8-sig")
        gc.collect()
    Path(args.comparison_output).with_suffix(".manifest.json").write_text(
        json.dumps({
            "matrix_id": args.matrix_id, "changed_variable": "initial_cash_only",
            "cash_values": args.cash, "start_date": args.start_date,
            "end_date": args.end_date, "max_days": args.max_days,
            "fixed": {
                "code_state": "same process/worktree", "factor_cabinet": "b8dd096a6706b63e6e960d01e23fa647763b7cd5113ace055db58e2395788b90",
                "cash_buffer_amount": 1000.0, "capital_usage_mode": "allow_cash",
                "universe": "all_a_share_research", "cost_model": "same configured model",
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8",
    )


if __name__ == "__main__":
    main()
