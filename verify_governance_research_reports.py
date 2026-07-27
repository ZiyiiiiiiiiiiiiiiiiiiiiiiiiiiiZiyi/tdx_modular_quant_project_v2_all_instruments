"""Verify governance research-gate diagnostic reports.

Run:
& "C:\\Users\\Ziyi Wang\\.conda\\envs\\stock_ai\\python.exe" verify_governance_research_reports.py
"""
from __future__ import annotations

import sys

import pandas as pd

from functions.decision_council.quality_reports import build_governance_quality_reports


def _sample_features() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=45)
    symbols = ["sh600000", "sz000001", "sh600519", "sz000002", "sh601318", "sz000333"]
    rows = []
    for symbol_index, symbol in enumerate(symbols):
        price = 10.0 + symbol_index
        for day_index, date in enumerate(dates):
            price *= 1.0 + 0.001 * ((day_index % 5) - 2) + 0.0005 * symbol_index
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "close_nominal": price,
                    "ret_20": day_index / len(dates) + symbol_index / 10.0,
                    "score_mom_lowvol": (len(dates) - day_index) / len(dates),
                    "close_to_ma20": (day_index % 7) / 10.0,
                    "score_orderflow_amount_shock": ((day_index + symbol_index) % 9) / 9.0,
                    "score_orderflow_close_drive": (day_index % 11) / 11.0,
                }
            )
    return pd.DataFrame(rows)


def main() -> int:
    features = _sample_features()
    dates = sorted(features["date"].unique())
    ideal = features[["date", "symbol"]].rename(columns={"date": "decision_date"}).copy()
    ideal["p_win_10d_calibrated"] = 0.55
    ideal["ideal_weight"] = 0.01
    execution = pd.DataFrame(
        [
            {
                "trade_date": dates[5],
                "symbol": "sh600000",
                "side": "buy",
                "price": 10.0,
                "reason": "normal_buy",
                "executed_shares": 100,
                "trade_notional": 1000,
                "entry_matrix_score": 0.70,
                "alpha_quality_score": 0.60,
            },
            {
                "trade_date": dates[20],
                "symbol": "sh600000",
                "side": "sell",
                "price": 9.2,
                "reason": "post_entry_failure_exit",
                "executed_shares": 100,
                "trade_notional": 920,
            },
        ]
    )
    daily = pd.DataFrame(
        {
            "date": dates,
            "account_effective_n": [3.0] * len(dates),
            "top1_account_weight": [0.40] * len(dates),
            "top5_account_weight_sum": [0.90] * len(dates),
            "holding_count": [3] * len(dates),
            "configured_max_positions": [3] * len(dates),
            "target_holding_count": [2] * len(dates),
            "actual_exposure": [0.50] * len(dates),
        }
    )
    reports = build_governance_quality_reports(
        ideal_portfolio_plan=ideal,
        executable_order_plan=execution,
        execution_ledger=execution,
        alpha_proposals=pd.DataFrame(),
        feature_data=features,
        benchmark_symbol=None,
        daily_result=daily,
        attribution_ledger=pd.DataFrame(),
        return_pivot=None,
    )
    required = [
        "governance_factor_registry_snapshot",
        "governance_factor_validation_report",
        "governance_factor_ic_timeseries",
        "governance_factor_layer_return_report",
        "governance_factor_quantile_report",
        "governance_factor_cluster_report",
        "governance_entry_gate_policy",
        "governance_portfolio_constraint_report",
        "governance_entry_failure_timing_report",
        "governance_research_gate_report",
    ]
    failures = []
    for name in required:
        if name not in reports:
            failures.append(f"missing report: {name}")
        elif reports[name] is None:
            failures.append(f"report is None: {name}")
    gate = reports.get("governance_research_gate_report", pd.DataFrame())
    if gate.empty or "overall_status" not in gate.columns:
        failures.append("research gate report missing overall_status")
    elif "blocked" not in set(gate["overall_status"].astype(str)):
        failures.append("research gate should block concentrated weak sample")
    constraints = reports.get("governance_portfolio_constraint_report", pd.DataFrame())
    if constraints.empty or bool(constraints["constraint_pass"].iloc[-1]):
        failures.append("portfolio constraint report should fail concentrated sample")
    elif int(constraints["configured_max_positions"].iloc[-1]) != 3:
        failures.append("portfolio constraint report confused max positions with target holdings")
    elif float(constraints["effective_n_required"].iloc[-1]) != 3.0:
        failures.append("cash component incorrectly increased the effective-N requirement")
    validation = reports.get("governance_factor_validation_report", pd.DataFrame())
    expected_validation_cols = {"max_drawdown_top_bucket", "industry_exposure_max", "size_corr", "liquidity_corr"}
    if not expected_validation_cols.issubset(set(validation.columns)):
        failures.append("factor validation report missing blueprint exposure columns")
    registry = reports.get("governance_factor_registry_snapshot", pd.DataFrame())
    if registry.empty or "pre_screen_candidate" not in set(registry.get("candidate_pool", pd.Series(dtype=str)).astype(str)):
        failures.append("factor registry should include pre_screen_candidate pool")
    entry_gate = reports.get("governance_entry_gate_policy", pd.DataFrame())
    if entry_gate.empty or not {"allow_buy", "max_entry_lots", "reason"}.issubset(set(entry_gate.columns)):
        failures.append("entry gate policy report missing decision fields")

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1
    for name in required:
        print(f"[PASS] {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
