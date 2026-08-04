"""Verify completed-day snapshots survive independently from final saving."""
from __future__ import annotations

import json
from pathlib import Path

from functions.decision_council.runtime_checkpoint import (
    DAILY_SNAPSHOT_SCHEMA_VERSION,
    write_daily_atomic_snapshot,
)


output = Path("results") / "_verification_daily_atomic_snapshot"
path = write_daily_atomic_snapshot(
    output,
    trading_day_index=3,
    trade_date="2025-02-26",
    runtime_identity_hash="fixture_hash",
    payload={
        "account": {"cash": 12_345.0, "holding_count": 1},
        "positions": [{"symbol": "sz000001", "shares": 100}],
        "pending_orders": [],
        "execution_events_tail": [{"fill_id": "f1"}],
        "policy_pool_plan_ledgers": {
            "constraint_allocation_ledger": [
                {"policy_holding_floor": 5, "planned_holding_count": 1}
            ]
        },
    },
)
assert path.exists()
latest = output / "latest_daily_snapshot.json"
assert latest.exists()
payload = json.loads(path.read_text(encoding="utf-8"))
assert payload["schema_version"] == DAILY_SNAPSHOT_SCHEMA_VERSION
assert payload["account"]["holding_count"] == 1
assert payload["policy_pool_plan_ledgers"]["constraint_allocation_ledger"][0][
    "policy_holding_floor"
] == 5
assert json.loads(latest.read_text(encoding="utf-8"))["trading_day_index"] == 3
print("[PASS] daily policy/pool/plan/pending/fill/account snapshot is atomic and readable")
