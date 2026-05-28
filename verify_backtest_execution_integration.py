# -*- coding: utf-8 -*-
import tempfile
from pathlib import Path

import pandas as pd

from functions.backtest_engine import _apply_weight_constraints, run_backtest


def verify_backtest_execution_integration():
    failures: list[str] = []
    print("=== Verify backtest execution integration ===")

    sample_dir = Path("results")
    sample_dir.mkdir(parents=True, exist_ok=True)

    selection = pd.DataFrame(
        {
            "rebalance_date": pd.to_datetime(["2024-01-05", "2024-01-05", "2024-01-10", "2024-01-10"]),
            "symbol": ["sh600000", "sz000001", "sh600000", "sz000001"],
            "weight": [0.5, 0.5, 0.4, 0.6],
        }
    )
    capped = _apply_weight_constraints(selection[selection["rebalance_date"] == pd.Timestamp("2024-01-05")], 0.2)
    if float(capped["weight"].max()) > 0.2 or float(capped["weight"].sum()) > 0.4:
        failures.append("hard max_weight constraint was undone by renormalization")
        print("[FAIL] hard max_weight constraint was undone by renormalization")
    else:
        print("[PASS] hard max_weight constraint retains cash when the universe is too small")

    with tempfile.TemporaryDirectory() as tmpdir:
        temp = Path(tmpdir)
        feature_df = pd.DataFrame(
            {
                "date": pd.to_datetime(
                    [
                        "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11",
                        "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11",
                    ]
                ),
                "symbol": ["sh600000"] * 5 + ["sz000001"] * 5,
                "close": [100.0, 90.0, 80.0, 70.0, 60.0, 200.0, 180.0, 160.0, 140.0, 120.0],
                "close_nominal": [10.0, 10.1, 10.2, 10.3, 10.4, 20.0, 20.2, 20.1, 20.3, 20.4],
                "is_trading": [True] * 10,
                "abnormal_jump": [False] * 10,
                "rough_limit_up": [False] * 10,
                "rough_limit_down": [False, False, False, True, False] + [False] * 5,
            }
        )
        feature_path = temp / "tdx_daily_features.parquet"
        feature_df.to_parquet(feature_path, index=False)

        from config import FEATURE_DAILY_PARQUET as original_feature_path
        import functions.backtest_engine as backtest_engine_module

        old_feature_path = backtest_engine_module.FEATURE_DAILY_PARQUET
        backtest_engine_module.FEATURE_DAILY_PARQUET = feature_path
        try:
            daily_result, metrics, holdings = run_backtest(
                selection,
                initial_cash=100000.0,
                risk_free_rate=0.0,
                max_weight=1.0,
                show_plot=False,
                strategy_name="integration_test",
            )
        finally:
            backtest_engine_module.FEATURE_DAILY_PARQUET = old_feature_path

    required_daily_cols = {"gross_daily_return", "net_daily_return", "transaction_cost", "gross_turnover"}
    missing_daily_cols = sorted(required_daily_cols - set(daily_result.columns))
    if missing_daily_cols:
        failures.append(f"daily result missing columns: {missing_daily_cols}")
        print(f"[FAIL] daily result missing columns: {missing_daily_cols}")
    else:
        print("[PASS] daily result execution columns generated")

    if daily_result["blocked_order_count"].sum() <= 0:
        failures.append("price-limit blocked order was not reflected in daily result")
        print("[FAIL] price-limit blocked order was not reflected in daily result")
    else:
        print("[PASS] price-limit blocked order reflected in daily result")

    if float(daily_result["net_value"].iloc[-1]) <= 100000.0:
        failures.append("backtest returns do not appear to use rising nominal trade prices")
        print("[FAIL] backtest returns do not appear to use rising nominal trade prices")
    else:
        print("[PASS] nominal trade prices drive realized return series")

    if holdings.empty:
        failures.append("holdings should not be empty")
        print("[FAIL] holdings should not be empty")
    else:
        print("[PASS] holdings generated")

    if metrics.empty:
        failures.append("metrics should not be empty")
        print("[FAIL] metrics should not be empty")
    else:
        print("[PASS] metrics generated")
    execution_metric_names = {
        "gross_total_return",
        "net_total_return",
        "turnover_ratio",
        "transaction_cost_ratio",
        "blocked_order_count",
    }
    missing_metrics = execution_metric_names - set(metrics["metric"])
    if missing_metrics:
        failures.append(f"execution metrics missing: {sorted(missing_metrics)}")
        print(f"[FAIL] execution metrics missing: {sorted(missing_metrics)}")
    else:
        print("[PASS] execution diagnostics metrics generated")
        metric_map = dict(zip(metrics["metric"], metrics["value"]))
        if float(metric_map["gross_total_return"]) <= float(metric_map["net_total_return"]):
            failures.append("net return should reflect transaction costs below gross return")
            print("[FAIL] net return does not reflect transaction costs")
        else:
            print("[PASS] net return includes transaction-cost drag")

    print()
    if failures:
        print("Backtest execution integration verification failed.")
        for item in failures:
            print("-", item)
        raise SystemExit(1)

    print("Backtest execution integration verification passed.")


if __name__ == "__main__":
    verify_backtest_execution_integration()
