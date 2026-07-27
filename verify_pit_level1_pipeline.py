"""Product verification for the conservative low-memory Level-1 publisher."""
from pathlib import Path

import pandas as pd

from functions.data.pit_level1_pipeline import publish_research_pit_level1_low_memory
from functions.data.pit_level1_store import load_pit_table, pit_store_status, run_pit_preflight


def main():
    base = Path("reports/verify_pit_level1_pipeline")
    base.mkdir(parents=True, exist_ok=True)
    clean = base / "clean.parquet"
    index = base / "index.parquet"
    actions = base / "actions.parquet"
    root = base / "store"

    pd.DataFrame([
        {"date": "2024-01-02", "symbol": "sh600000", "is_trading": True, "is_st": False},
        {"date": "2024-01-03", "symbol": "sh600000", "is_trading": True, "is_st": False},
        {"date": "2024-01-03", "symbol": "sz000001", "is_trading": False, "is_st": True},
    ]).to_parquet(clean, index=False)
    pd.DataFrame([{
        "index_code": "000300", "index_name": "CSI300", "symbol": "sh600000",
        "first_trade_date": "2020-01-01", "out_date": pd.NaT,
        "source": "current_snapshot", "asof_date": "2024-01-05",
    }]).to_parquet(index, index=False)
    pd.DataFrame([{
        "source_name": "local", "symbol": "sh600000", "action_date": "2024-01-04",
        "action_type": "dividend", "cash_dividend": 0.1,
        "stock_dividend_ratio": 0.0, "rights_issue_ratio": 0.0,
    }]).to_parquet(actions, index=False)

    saved = publish_research_pit_level1_low_memory(
        clean_daily_path=clean,
        index_constituents_path=index,
        corporate_actions_path=actions,
        output_root=root,
        batch_size=2,
        max_runtime_seconds=60,
    )
    assert len(saved) == 4 and all(path.exists() for path in saved.values())
    status = pit_store_status(root=root)
    assert status["available"].all() and not status["formal_eligible"].any()
    print("[PASS] all four Level-1 tables publish as explicit research-only artifacts")

    membership = load_pit_table("index_membership_pit", root=root)
    assert pd.Timestamp(membership.iloc[0]["effective_from"]) == pd.Timestamp("2024-01-05")
    assert pd.Timestamp(membership.iloc[0]["known_at"]) == pd.Timestamp("2024-01-05")
    print("[PASS] current index snapshot is not backfilled before its known-at date")

    preflight = run_pit_preflight(mode="research", root=root)
    assert preflight["pit_runtime_state"] == "research_only"
    assert len(preflight["formal_ineligible_tables"]) == 4
    print("[PASS] research preflight permits inspection while formal mode remains blocked")


if __name__ == "__main__":
    main()
