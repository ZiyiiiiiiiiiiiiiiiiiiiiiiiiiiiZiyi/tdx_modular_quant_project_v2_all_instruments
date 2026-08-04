from __future__ import annotations

import json
from pathlib import Path


ROOT = Path("results/decision_council/derived_products/run20260804_221302")
SNAPSHOT = json.loads(
    Path("reports/SCAP_20260805_338D_BASELINE_SNAPSHOT.json").read_text(
        encoding="utf-8"
    )
)
VERDICT = json.loads(
    (ROOT / "phase8_gate_verdict_20260805.json").read_text(encoding="utf-8")
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"[PASS] {message}")


check(SNAPSHOT["trading_days"] == 338, "baseline snapshot preserves 338 days")
check(
    SNAPSHOT["runtime_identity_hash"]
    == "dfd4e14447ee211f1ca4aeb3e2cadd4c6e5a091e4c4e1241e9284746220725c4",
    "baseline snapshot preserves runtime identity",
)
check(
    all(item["exists"] and item["sha256"] for item in SNAPSHOT["files"].values()),
    "all required baseline evidence files are hashed",
)
check(VERDICT["engineering_gate"] == "pass", "engineering gate passes")
check(VERDICT["research_gate"] == "blocked", "research gate remains fail-closed")
check(VERDICT["production_gate"] == "blocked", "production gate remains fail-closed")
check(
    VERDICT["decision"] == "engineering_products_accepted_no_trading_authority",
    "engineering acceptance grants no trading authority",
)
