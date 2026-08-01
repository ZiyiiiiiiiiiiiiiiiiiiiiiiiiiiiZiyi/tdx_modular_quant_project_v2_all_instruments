from pathlib import Path


launcher = Path("main_launcher_web.py").read_text(encoding="utf-8")
monitor = Path("functions/decision_council/live_monitor_web.py").read_text(encoding="utf-8")
dashboard = Path("functions/decision_council/live_monitor_dashboard.py").read_text(encoding="utf-8")

checks = {
    "Cabinet Native is the fail-safe initialized baseline": 'value="mainline_v3_cabinet_native" selected' in launcher,
    "layer validation is the single initialized task": 'id="governance_layer_validation" checked' in launcher and 'id === "governance_layer_validation"' in launcher,
    "SCAP E4 is the initialized control profile": 'value="aggressive_lean" selected' in launcher and 'value="E4" selected' in launcher,
    "Web guidance carries the passed 20-day chain into the next 180-day run": '20日SCAP-V2全链工程验收已通过' in launcher and '180日受控开发窗口' in launcher and '不要同时勾选其他任务' in launcher,
    "v3.1 rolling reliability is disclosed": 'mainline_v3_reliability_weighted' in launcher and '滚动成熟标签可靠性' in launcher,
    "sealed 2025 to 2026-05 range is initialized": 'id="start_month" value="2025-01"' in launcher and 'id="end_month" value="2026-05"' in launcher,
    "180-day next-step window is initialized": 'value="long_180" selected>180 日' in launcher and 'id="max_days" min="1" step="1" readonly' in launcher,
    "validation window presets are selectable": all(token in launcher for token in ('id="validation_window_preset"', 'value="short_5"', 'value="short_20"', 'value="long_180"')),
    "presets only change day limit": all(token in launcher for token in ('short_5: {maxDays: "5", profile: "full"}', 'short_20: {maxDays: "20", profile: "full"}', 'long_180: {maxDays: "180", profile: "full"}')),
    "preset logic does not overwrite months": 'preset.startMonth' not in launcher and 'preset.endMonth' not in launcher,
    "small account profile owns default cash": 'id="initial_cash" min="1" step="1000" value=""' in launcher,
    "optional Web hard cap remains editable and is not a target": 'id="max_positions_account" min="0" step="1" value=""' in launcher and '留空或0=不加用户上限；系统仍按资金/整手/成本自动决定' in launcher,
    "capital profile owns default cash buffer": 'id="min_cash_buffer" min="0" step="100" value=""' in launcher,
    "all-A research universe is the only checked universe": 'value="all_a_share_research" checked' in launcher and 'value="hs300_csi500_a500_strict" checked' not in launcher,
    "controlled factor cabinet is pinned first": 'return DEFAULT_SELECTED_FACTOR_CABINET_RUN_ID, "controlled_scap_baseline"' in launcher,
    "monthly ML weight is pre-registered": 'id="monthly_lgbm_maximum_weight"' in launcher and 'value="0.20"' in launcher,
    "dual-horizon ML and auditable curves are disclosed": all(token in launcher for token in ('5日模型负责入场排序', '20日模型负责持有/替换价值', '逐轮 NDCG', 'Top-5 处理效应')),
    "fixed top-pool performance benchmark is initialized": all(token in launcher for token in ('id="performance_benchmark_top_n"', 'value="100" selected', 'id="performance_benchmark_rebalance"', 'value="monthly" selected')),
    "benchmark roles are disclosed separately": '沪深300 ETF 只用于安全/市场状态' in launcher and '固定 Top-N 流动性股票池' in monitor,
    "small-account replacement state is visibly profile-owned": 'id="active_replacement_enabled" disabled' in launcher and '资金档案唯一控制' in launcher,
    "all v3 variants share monitor semantics": '.startsWith("mainline_v3")' in monitor and '.startsWith("mainline_v3")' in dashboard,
    "launcher exposes a localhost health endpoint": 'parsed.path == "/api/health"' in launcher and '"progress_path": "/api/progress"' in launcher,
    "launcher exposes data and constituent preflight": 'parsed.path == "/api/governance-preflight"' in launcher and 'id="data_preflight"' in launcher,
    "Level-1 research builder is selectable without weakening PIT audit": 'id="pit_level1_build"' in launcher and '"pit_level1_build",' in launcher and 'id="pit_level1_audit"' in launcher,
    "historical membership builder exposes conservative A500 reconstruction": all(token in launcher for token in ('id="pit_index_membership_build"', 'id="index_a500_history_file"', '不会把当前500只直接倒填')),
    "formal readiness defaults are visible": all(token in monitor for token in ("NOT_EVALUATED", "pit_level2_runtime_state", "factor_temporal_isolation_status")),
}
for label, passed in checks.items():
    if not passed:
        raise AssertionError(label)
    print(f"[PASS] {label}")
