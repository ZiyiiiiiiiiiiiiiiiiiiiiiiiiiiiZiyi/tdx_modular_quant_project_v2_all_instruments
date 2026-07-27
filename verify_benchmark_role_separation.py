from __future__ import annotations

import pandas as pd

from config import MARKET_REGIME_BENCHMARK_SYMBOL
from functions.decision_council.analytics import build_top_pool_benchmark_series


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    rows = []
    for date, stock_close, etf_close in (
        ("2024-01-02", 10.0, 4.0),
        ("2024-01-03", 11.0, 2.0),
    ):
        rows.extend(
            [
                {"date": date, "symbol": "sh600000", "close": stock_close, "amount": 100.0, "instrument_type": "stock", "is_trading": True},
                {"date": date, "symbol": MARKET_REGIME_BENCHMARK_SYMBOL, "close": etf_close, "amount": 10_000.0, "instrument_type": "etf_fund", "is_trading": True},
            ]
        )
    benchmark = build_top_pool_benchmark_series(pd.DataFrame(rows), top_n=1, rebalance="daily")
    expect(
        abs(float(benchmark.iloc[-1]["benchmark_gross_daily_return"]) - 0.10) < 1e-12
        and float(benchmark.iloc[-1]["benchmark_daily_return"]) < 0.10,
        "performance benchmark contains stocks and excludes the safety ETF even when ETF liquidity is larger",
    )
    expect(
        str(MARKET_REGIME_BENCHMARK_SYMBOL) == "sh510300",
        "safety/regime benchmark remains the independent CSI 300 ETF proxy",
    )
    source = open("functions/decision_council/runner.py", encoding="utf-8").read()
    expect(
        'benchmark_symbol=performance_benchmark_symbol' in source,
        "sell/hold/replace counterfactual rewards use the performance pool rather than the safety ETF",
    )
    print("[PASS] benchmark role-separation verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
