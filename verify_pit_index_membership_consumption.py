"""Verify the investable-universe interface consumes Level-1 membership first."""
from pathlib import Path

import pandas as pd

from functions.investable_universe import active_index_members, load_index_constituents


def main():
    base = Path("reports/verify_pit_index_membership_consumption")
    base.mkdir(parents=True, exist_ok=True)
    pit = base / "index_membership_pit.parquet"
    pd.DataFrame([{
        "symbol": "sh600000", "index_code": "000300",
        "effective_from": "2024-01-05", "effective_to": pd.NaT,
        "known_at": "2024-01-04", "source": "csindex_announcement",
    }]).to_parquet(pit, index=False)
    loaded = load_index_constituents(path=None, pit_path=pit)
    assert pd.Timestamp(loaded.iloc[0]["first_trade_date"]) == pd.Timestamp("2024-01-05")
    assert pd.Timestamp(loaded.iloc[0]["asof_date"]) == pd.Timestamp("2024-01-04")
    assert active_index_members(loaded, as_of_date="2024-01-04").empty
    assert set(active_index_members(loaded, as_of_date="2024-01-05")["symbol"]) == {"sh600000"}
    print("[PASS] Level-1 known-at/effective dates drive investable membership")


if __name__ == "__main__":
    main()
