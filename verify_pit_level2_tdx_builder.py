from pathlib import Path

import pandas as pd

from functions.data.pit_level2_store import validate_pit_level2_frame
from functions.data.pit_level2_tdx_builder import (
    build_research_pit_level2_from_local_tdx,
    parse_tdx_finance_snapshot,
)


def main() -> int:
    paths = sorted(Path("data/raw_external").glob("gpcw*.zip"))
    if not paths:
        print("[SKIP] no local TDX gpcw snapshots")
        return 0
    financial, events = pd.DataFrame(), pd.DataFrame()
    for path in reversed(paths):
        financial, events = parse_tdx_finance_snapshot(path, symbol_limit=20)
        if not financial.empty:
            break
    if financial.empty:
        print("[FAIL] local TDX snapshot produced no timestamped financial rows")
        return 1
    audit = validate_pit_level2_frame(financial, table_name="financial_statement_pit")
    if not audit["passed"].all():
        print(f"[FAIL] financial Level-2 validation: {audit.to_dict('records')}")
        return 1
    if not (financial["effective_from"].dt.normalize() > financial["known_at"].dt.normalize()).all():
        print("[FAIL] TDX financial rows were not delayed until after announcement date")
        return 1
    tables = build_research_pit_level2_from_local_tdx(max_files=1, symbol_limit=20)
    full_financial = tables["financial_statement_pit"]
    identity = ["symbol", "report_period", "statement_type", "revision_id"]
    if full_financial.duplicated(identity).any():
        print("[FAIL] exact source duplicates were not removed")
        return 1
    valuation = tables["valuation_daily_pit"]
    if valuation.empty:
        print("[FAIL] existing market-cap history did not produce valuation PIT rows")
        return 1
    valuation_audit = validate_pit_level2_frame(valuation, table_name="valuation_daily_pit")
    if not valuation_audit["passed"].all():
        print(f"[FAIL] valuation Level-2 validation: {valuation_audit.to_dict('records')}")
        return 1
    print(
        "[PASS] local TDX research-only Level-2 builder "
        f"financial={len(financial)}, events={len(events)}, valuation={len(valuation)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
