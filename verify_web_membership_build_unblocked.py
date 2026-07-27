from __future__ import annotations

from main_launcher_web import _render_run_html, _sanitize_selection_payload


def _payload(tasks):
    return {
        "tasks": list(tasks),
        "profile": "full",
        "allow_multi_task": False,
        "backtest": {},
        "governance": {
            "universes": ["hs300_csi500_a500_strict"],
            "start_month": "2025-01",
            "end_month": "2026-05",
            "max_days": "",
            "validation_window_preset": "custom",
            "pit_mode": "research",
            "factor_source": "selected_factor_cabinet",
            "factor_cabinet_run_id": "pruned_run20260714_184846_581132_20260715_230524",
        },
    }


def main() -> None:
    html = _render_run_html()
    fragment = 'id="governance_layer_validation"'
    start = html.index(fragment)
    assert "checked" not in html[start : start + 120]
    assert "TASK_CHECKBOX_IDS.forEach" in html
    assert "enforceMembershipBuildIsolation" in html

    saved = _sanitize_selection_payload(
        _payload(["governance_mainline_review", "pit_index_membership_build"])
    )
    assert saved["tasks"] == ["pit_index_membership_build"], saved
    assert saved["sanitized_task_note"] == "isolated_pit_index_membership_build_from_stale_multi_task_selection"
    print("[PASS] Web starts with no task and isolates membership build from stale governance state")


if __name__ == "__main__":
    main()
