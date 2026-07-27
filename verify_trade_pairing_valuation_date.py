from __future__ import annotations

import pandas as pd

from functions.execution.trade_pairing import build_trade_pairing_ledgers


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


def main() -> int:
    orders = pd.DataFrame([
        {
            "symbol": "sh600000",
            "trade_date": "2024-01-02",
            "side": "buy",
            "price": 10.0,
            "executed_shares": 100.0,
            "total_cost": 1.0,
            "execution_status": "filled",
        }
    ])
    prices = pd.DataFrame([
        {"date": "2024-01-03", "symbol": "sh600000", "trade_close": 10.2},
        {"date": "2024-12-31", "symbol": "sh600000", "trade_close": 12.5},
    ])
    _, open_positions, _ = build_trade_pairing_ledgers(orders, prices)
    row = open_positions.iloc[0]
    expect(pd.Timestamp(row["valuation_date"]) == pd.Timestamp("2024-12-31"),
           "open position valuation date comes from the latest symbol price, not the last fill")
    expect(abs(float(row["latest_price"]) - 12.5) < 1e-12,
           "open position value and valuation date use the same snapshot")
    print("[PASS] trade-pairing valuation-date verification completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
