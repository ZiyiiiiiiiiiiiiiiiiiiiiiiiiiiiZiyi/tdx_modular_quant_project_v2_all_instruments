"""Verify empty trade-pairing outputs remain machine-readable."""
from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path

import pandas as pd

from functions.execution.trade_pairing import build_trade_pairing_ledgers


def main() -> None:
    pairs, open_positions, summary = build_trade_pairing_ledgers(pd.DataFrame())
    assert {"trade_id", "symbol", "realized_pnl_pct", "sell_order_id"}.issubset(pairs.columns)
    assert {"symbol", "avg_cost", "unrealized_pnl_pct"}.issubset(open_positions.columns)
    assert summary["realized_trade_count"] == 0
    with TemporaryDirectory() as temporary:
        pair_path = Path(temporary) / "pairs.csv"
        open_path = Path(temporary) / "open.csv"
        pairs.to_csv(pair_path, index=False, encoding="utf-8-sig")
        open_positions.to_csv(open_path, index=False, encoding="utf-8-sig")
        assert pd.read_csv(pair_path).empty
        assert pd.read_csv(open_path).empty
    print("[PASS] empty trade pairing outputs preserve CSV schemas")


if __name__ == "__main__":
    main()
