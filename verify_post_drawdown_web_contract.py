"""Read-only Web/API checks for post-drawdown diagnostic products."""
from __future__ import annotations

from pathlib import Path

from functions.decision_council.live_monitor_dashboard import HTML
from functions.decision_council.live_monitor_web import (
    DIAGNOSTIC_PRODUCTS,
    _diagnostic_product_payload,
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


root = Path(__file__).resolve().parent
source = (root / "functions/decision_council/live_monitor_web.py").read_text(
    encoding="utf-8"
)
for endpoint in (
    "/api/market-state", "/api/benchmarks", "/api/exit-authority",
    "/api/entry-quality", "/api/regime-factors", "/api/gates",
    "/api/diagnostic-export",
):
    check(endpoint in source, f"handler exposes {endpoint}")

for token in (
    'data-tab="diagnostics"', 'id="diagnosticDate"',
    'id="diagnosticSignal"', 'id="marketStateProduct"',
    'id="benchmarkProduct"', 'id="exitProduct"',
    'id="entryProduct"', 'id="factorProduct"', 'id="gateProduct"',
    "loadDiagnosticProducts", "authority=", "full_universe_oos_status",
):
    check(token in HTML, f"dashboard contains {token}")

pending = _diagnostic_product_payload({}, "market-state")
check(
    pending["status"] == "pending" and pending["rows"] == [],
    "missing run directory is pending rather than forged zero data",
)

# Reuse a factual immutable historical CSV to exercise encoding, bounded row
# reads and the fixed allowlist without creating or deleting test artifacts.
run_dir = (
    root / "results/decision_council/scap/cab_c6dae8d4d69c/"
    "e4_l1200/v3/run20260809_214739"
)
original = DIAGNOSTIC_PRODUCTS["market-state"]["filename"]
try:
    DIAGNOSTIC_PRODUCTS["market-state"]["filename"] = (
        "governance_daily_result.csv"
    )
    loaded = _diagnostic_product_payload(
        {"output_dir": str(run_dir)}, "market-state", {"limit": ["2"]}
    )
finally:
    DIAGNOSTIC_PRODUCTS["market-state"]["filename"] = original
check(
    loaded["status"] == "ok" and loaded["row_count"] == 2,
    "diagnostic CSV reads are bounded and return an explicit authority envelope",
)

print("[PASS] post-drawdown Web contract verification completed")
