import json
from pathlib import Path
from tempfile import TemporaryDirectory

import main_launcher_web


def main() -> int:
    html = main_launcher_web._render_run_html()
    for token in (
        'id="orderflow_parameter_research"',
        'id="pit_level1_audit"',
        'id="pit_index_membership_build"',
        'id="index_a500_history_file"',
        'id="pit_level2_audit"',
        'id="pit_level2_build"',
        'id="registered_mainline_v2_suite"',
        'id="pit_mode"',
        'value="research" selected',
        'id="research_max_runtime_seconds"',
        'id="performance_benchmark_top_n"',
        'id="performance_benchmark_rebalance"',
        'performance_benchmark_top_n: performanceBenchmarkTopN',
        'value="1800"',
        'research_max_runtime_seconds: researchMaxRuntimeSeconds',
        'id="progress_task"',
        'id="progress_connection"',
        'id="progress_updated"',
        'data.task_name === "interactive_task_suite"',
        '进度接口暂时不可用，页面会继续重试',
        'selected_factor_cabinet requires an available factor cabinet run_id.',
        'const tasks = ["factor_appeal_judge", "orderflow_parameter_research", "factor_cabinet"]',
    ):
        assert token in html, token
    assert 'position: fixed' in html
    all_tasks_line = next(line for line in html.splitlines() if "const tasks =" in line and "main_pipeline" in line)
    assert "orderflow_parameter_research" not in all_tasks_line
    assert "registered_mainline_v2_suite" not in all_tasks_line
    clean = main_launcher_web._sanitize_selection_payload(
        {"tasks": ["pit_level1_audit", "pit_level1_audit"], "profile": "fast"}
    )
    assert clean["tasks"] == ["pit_level1_audit"]
    historical = main_launcher_web._sanitize_selection_payload({
        "tasks": ["pit_index_membership_build"],
        "profile": "full",
        "governance": {
            "validation_window_preset": "short_5",
            "max_days": "5",
            "index_a500_history_file": r"F:\data\a500_history.parquet",
        },
    })
    assert historical["tasks"] == ["pit_index_membership_build"]
    assert historical["governance"]["index_a500_history_file"].endswith("a500_history.parquet")
    cabinet_flow = main_launcher_web._sanitize_selection_payload({
        "tasks": ["factor_cabinet"],
        "governance": {
            "factor_source": "selected_factor_cabinet",
            "factor_cabinet_run_id": "run20260713_213546_273503",
        },
    })
    assert cabinet_flow["tasks"] == [
        "factor_appeal_judge", "orderflow_parameter_research", "factor_cabinet",
    ]
    try:
        main_launcher_web._sanitize_selection_payload({"tasks": ["unknown_task"]})
    except ValueError as exc:
        assert "Unsupported interactive tasks" in str(exc)
    else:
        raise AssertionError("unknown Web task was accepted")
    valid_selected = main_launcher_web._sanitize_selection_payload(
        {
            "tasks": ["factor_cabinet_feature_cache"],
            "governance": {
                "factor_source": "selected_factor_cabinet",
                "factor_cabinet_run_id": "run20260713_213546_273503",
            },
        }
    )
    assert valid_selected["governance"]["factor_cabinet_run_id"] == "run20260713_213546_273503"
    long_window = main_launcher_web._sanitize_selection_payload({
        "tasks": ["governance_layer_validation"],
        "profile": "full",
        "governance": {
            "validation_window_preset": "long_180",
            "max_days": "180",
            "factor_source": "selected_factor_cabinet",
            "factor_cabinet_run_id": "run20260713_213546_273503",
        },
    })
    assert long_window["governance"]["max_days"] == "180"
    unlimited = main_launcher_web._sanitize_selection_payload({
        "tasks": ["pit_level1_audit"], "profile": "full",
        "governance": {"validation_window_preset": "custom", "max_days": ""},
    })
    assert unlimited["governance"]["max_days"] == ""
    assert unlimited["governance"]["performance_benchmark_top_n"] == "100"
    assert unlimited["governance"]["performance_benchmark_rebalance"] == "monthly"
    for bad_benchmark in (
        {"performance_benchmark_top_n": "30"},
        {"performance_benchmark_rebalance": "quarterly"},
    ):
        try:
            main_launcher_web._sanitize_selection_payload({
                "tasks": ["pit_level1_audit"], "governance": bad_benchmark,
            })
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid benchmark setting was accepted: {bad_benchmark}")
    for bad in (
        {"validation_window_preset": "long_180", "max_days": "20"},
        {"validation_window_preset": "custom", "max_days": "5"},
        {"validation_window_preset": "unknown", "max_days": "180"},
    ):
        try:
            main_launcher_web._sanitize_selection_payload({
                "tasks": ["pit_level1_audit"], "profile": "full", "governance": bad,
            })
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid validation preset was accepted: {bad}")
    try:
        main_launcher_web._sanitize_selection_payload({
            "tasks": ["pit_level1_audit"], "profile": "fast",
            "governance": {"validation_window_preset": "long_180", "max_days": "180"},
        })
    except ValueError as exc:
        assert "requires full profile" in str(exc)
    else:
        raise AssertionError("registered validation preset was accepted in fast mode")
    try:
        main_launcher_web._sanitize_selection_payload(
            {
                "tasks": ["factor_cabinet_feature_cache"],
                "governance": {"factor_source": "selected_factor_cabinet"},
            }
        )
    except ValueError as exc:
        assert "requires factor_cabinet_run_id" in str(exc)
    else:
        raise AssertionError("selected cabinet task accepted an empty run_id")
    assert main_launcher_web.MAX_SUBMIT_BODY_BYTES == 1024 * 1024
    assert main_launcher_web.DEFAULT_SELECTED_FACTOR_CABINET_RUN_ID == "pruned_run20260714_184846_581132_20260715_230524"
    assert '<option value="selected_factor_cabinet" selected>' in html
    assert 'factorSource.value = "selected_factor_cabinet"' in html
    cabinet_options = main_launcher_web._render_factor_cabinet_options()
    rows = main_launcher_web.list_factor_cabinet_runs()
    expected_default_run, expected_default_reason = main_launcher_web._select_default_factor_cabinet_run(rows)
    selected_option = next(
        option for option in cabinet_options.split("</option>")
        if f'value="{expected_default_run}"' in option
    )
    assert " selected>" in selected_option
    assert f"default={expected_default_reason}" in selected_option
    assert "lineage=pending_prune" in selected_option or "lineage=pruned" in selected_option
    original_list_runs = main_launcher_web.list_factor_cabinet_runs
    main_launcher_web.list_factor_cabinet_runs = lambda: [
        {
            "run_id": "different_run",
            "path": "different_run/factor_cabinet.json",
            "factor_count": 1,
        }
    ]
    try:
        missing_default_options = main_launcher_web._render_factor_cabinet_options()
    finally:
        main_launcher_web.list_factor_cabinet_runs = original_list_runs
    assert "默认因子柜不可用" in missing_default_options
    assert 'value="different_run"' in missing_default_options
    different_option = next(
        option for option in missing_default_options.split("</option>")
        if 'value="different_run"' in option
    )
    assert " selected>" not in different_option
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        base_path = root / "base.json"
        augmented_path = root / "augmented.json"
        pruned_path = root / "pruned.json"
        base_path.write_text(json.dumps({"run_id": "base"}), encoding="utf-8")
        augmented_path.write_text(json.dumps({
            "run_id": "augmented",
            "artifact_type": "factor_cabinet_pit_augmented",
            "generation_policy": "pit_augmented_v2",
            "default_eligible": True,
        }), encoding="utf-8")
        pruned_path.write_text(json.dumps({
            "run_id": "pruned_augmented",
            "artifact_type": "factor_cabinet_pruned",
            "source_run_id": "augmented",
        }), encoding="utf-8")
        selected_run, reason = main_launcher_web._select_default_factor_cabinet_run([
            {"run_id": "pruned_augmented", "path": str(pruned_path)},
            {"run_id": "augmented", "path": str(augmented_path)},
            {"run_id": "base", "path": str(base_path)},
        ])
        assert selected_run == "pruned_augmented"
        assert reason == "latest_pit_augmented"
    source = open("main_launcher_web.py", encoding="utf-8").read()
    assert 'host_name not in {"127.0.0.1", "localhost"}' in source
    print("[PASS] web exposes bounded research controls without adding long tasks to run-all")
    print("[PASS] web task allowlist, localhost gate, and request-size boundary are active")
    print(f"[PASS] web defaults to selected cabinet {expected_default_run} ({expected_default_reason})")
    print("[PASS] newest PIT-augmented cabinet lineage automatically becomes the Web default")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
