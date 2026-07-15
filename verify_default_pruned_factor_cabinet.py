from __future__ import annotations

import json
from pathlib import Path

import main_launcher_web
from functions.decision_council.factor_source import resolve_factor_source


EXPECTED_RUN_ID = "pruned_run20260714_184846_581132_20260715_230524"


def main() -> int:
    assert main_launcher_web.DEFAULT_SELECTED_FACTOR_CABINET_RUN_ID == EXPECTED_RUN_ID
    selected_run_id, reason = main_launcher_web._select_default_factor_cabinet_run(
        main_launcher_web.list_factor_cabinet_runs()
    )
    assert selected_run_id == EXPECTED_RUN_ID
    assert reason == "latest_pit_augmented"

    spec = resolve_factor_source(
        factor_source="selected_factor_cabinet",
        factor_cabinet_run_id=EXPECTED_RUN_ID,
    )
    payload = json.loads(Path(spec.factor_cabinet_path).read_text(encoding="utf-8"))
    assert payload["artifact_type"] == "factor_cabinet_pruned"
    assert payload["source_run_id"] == "run20260714_184846_581132"
    assert payload["default_eligible"] is True
    assert spec.factor_count == 74
    factor_names = set(spec.alpha_models)
    assert {"orderflow_close_drive", "turtle_breakout"} <= factor_names
    assert {
        "fund_book_to_price",
        "fund_fcf_yield",
        "fund_growth_surprise",
        "rsi_recovery_14",
    } <= factor_names
    assert spec.role_distribution == {
        "entry_alpha": 6,
        "entry_alpha_proxy": 12,
        "hold_validation": 12,
        "liquidity_filter": 12,
        "risk_override": 16,
        "timing_filter": 16,
    }
    print(f"[PASS] verified pruned cabinet is the Web default: {EXPECTED_RUN_ID}")
    print("[PASS] runtime resolver preserves required families and exact role distribution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
