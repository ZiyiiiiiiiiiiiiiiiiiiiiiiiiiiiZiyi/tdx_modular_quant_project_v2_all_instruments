"""Static checks for the controlled-run determinism verifier."""

from pathlib import Path


source = (Path(__file__).parent / "tools" / "verify_control_run_determinism.py").read_text(
    encoding="utf-8"
)
checks = {
    "uuid_keys_are_explicitly_excluded": '"order_id", "fill_id"' in source,
    "trade_pair_uuid_keys_are_excluded": '"entry_order_id", "sell_order_id"' in source,
    "tight_numeric_tolerance": "rtol=1e-12, atol=1e-12" in source,
    "daily_ledger_is_checked": '"governance_daily_result.csv"' in source,
    "execution_ledger_is_checked": '"governance_execution_ledger.csv"' in source,
}
for name, passed in checks.items():
    print(f"[{'PASS' if passed else 'FAIL'}] {name}")
raise SystemExit(0 if all(checks.values()) else 1)
